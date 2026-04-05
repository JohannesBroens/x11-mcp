"""System V shared memory + MIT-SHM X11 protocol for zero-copy capture.

Uses ctypes for SysV IPC (shmget/shmat/shmdt/shmctl) and python-xlib's
protocol request infrastructure for MIT-SHM Attach/GetImage/Detach.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Optional

from Xlib.protocol import rq

# --- System V IPC constants ---
IPC_PRIVATE = 0
IPC_CREAT = 0o1000
IPC_RMID = 0

# --- libc SHM bindings ---
_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

_shmget = _libc.shmget
_shmget.restype = ctypes.c_int
_shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]

_shmat = _libc.shmat
_shmat.restype = ctypes.c_void_p
_shmat.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]

_shmdt = _libc.shmdt
_shmdt.restype = ctypes.c_int
_shmdt.argtypes = [ctypes.c_void_p]

_shmctl = _libc.shmctl
_shmctl.restype = ctypes.c_int
_shmctl.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]


class ShmSegment:
    """Context manager for a System V shared memory segment.

    Usage:
        with ShmSegment(size) as seg:
            # seg.shmid, seg.addr available
            data = seg.as_bytes(size)
        # automatically detached + destroyed
    """

    def __init__(self, size: int):
        self.size = size
        self.shmid: int = -1
        self.addr: Optional[int] = None

    def __enter__(self) -> "ShmSegment":
        self.shmid = _shmget(IPC_PRIVATE, self.size, IPC_CREAT | 0o600)
        if self.shmid < 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"shmget failed for size {self.size}")

        self.addr = _shmat(self.shmid, None, 0)
        if self.addr == ctypes.c_void_p(-1).value:
            _shmctl(self.shmid, IPC_RMID, None)
            errno = ctypes.get_errno()
            raise OSError(errno, "shmat failed")

        return self

    def __exit__(self, *exc) -> None:
        if self.addr is not None and self.addr != ctypes.c_void_p(-1).value:
            _shmdt(self.addr)
            self.addr = None
        if self.shmid >= 0:
            _shmctl(self.shmid, IPC_RMID, None)
            self.shmid = -1

    def as_bytes(self, nbytes: int) -> bytes:
        """Read nbytes from the shared memory segment."""
        return ctypes.string_at(self.addr, nbytes)


# --- MIT-SHM X protocol requests ---

class ShmAttach(rq.Request):
    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(1),  # ShmAttach minor opcode
        rq.RequestLength(),
        rq.Card32("shmseg"),
        rq.Card32("shmid"),
        rq.Bool("read_only"),
        rq.Pad(3),
    )


class ShmDetach(rq.Request):
    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(2),  # ShmDetach minor opcode
        rq.RequestLength(),
        rq.Card32("shmseg"),
    )


class ShmGetImage(rq.ReplyRequest):
    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(4),  # ShmGetImage minor opcode
        rq.RequestLength(),
        rq.Drawable("drawable"),
        rq.Int16("x"),
        rq.Int16("y"),
        rq.Card16("width"),
        rq.Card16("height"),
        rq.Card32("plane_mask"),
        rq.Card8("format"),
        rq.Pad(3),
        rq.Card32("shmseg"),
        rq.Card32("offset"),
    )
    _reply = rq.Struct(
        rq.ReplyCode(),
        rq.Card8("depth"),
        rq.Card16("sequence_number"),
        rq.ReplyLength(),
        rq.Card32("visual"),
        rq.Card32("size"),
        rq.Pad(16),
    )


# --- MIT-SHM availability probe ---

_shm_supported: Optional[bool] = None


def xshm_available(display) -> bool:
    """Check if the X server supports MIT-SHM.

    Result is cached after first call.
    """
    global _shm_supported
    if _shm_supported is not None:
        return _shm_supported
    try:
        ext = display.query_extension("MIT-SHM")
        _shm_supported = bool(ext and ext.present)
    except Exception:
        _shm_supported = False
    return _shm_supported


def get_shm_opcode(display) -> int:
    """Get the major opcode for MIT-SHM extension."""
    ext = display.query_extension("MIT-SHM")
    return ext.major_opcode


def _reset_shm_cache() -> None:
    """Reset the SHM availability cache (for testing)."""
    global _shm_supported
    _shm_supported = None
