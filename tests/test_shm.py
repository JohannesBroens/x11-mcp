"""Tests for System V shared memory and MIT-SHM X protocol."""

import ctypes
import ctypes.util

import pytest


class TestShmSegment:
    def test_lifecycle(self):
        """Allocate, attach, write, read, detach, destroy."""
        from x11_mcp._shm import ShmSegment

        with ShmSegment(1024) as seg:
            assert seg.shmid >= 0
            assert seg.addr is not None
            # Write and read back
            ctypes.memset(seg.addr, 0xAB, 1024)
            data = seg.as_bytes(4)
            assert data == b"\xab\xab\xab\xab"

    def test_cleanup_on_exception(self):
        """SHM segment is cleaned up even if body raises."""
        from x11_mcp._shm import ShmSegment

        shmid_captured = None
        try:
            with ShmSegment(512) as seg:
                shmid_captured = seg.shmid
                raise ValueError("test")
        except ValueError:
            pass

        # Segment should be destroyed — trying to attach should fail
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        libc.shmat.restype = ctypes.c_void_p
        libc.shmat.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        addr = libc.shmat(shmid_captured, None, 0)
        # shmat returns -1 cast to void* on failure
        assert addr == ctypes.c_void_p(-1).value

    def test_zero_size_raises(self):
        from x11_mcp._shm import ShmSegment

        with pytest.raises(OSError):
            with ShmSegment(0):
                pass
