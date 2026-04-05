"""Screenshot capture via python-xlib with PIL scaling.

Captures the X11 framebuffer directly into RAM — zero disk I/O.
Scales to Claude's target resolution using LANCZOS resampling.
"""

from __future__ import annotations

import base64
import time as _time
from io import BytesIO
from typing import Optional

from PIL import Image

from x11_mcp.scaling import get_state

MAX_WIDTH = 1280
MAX_HEIGHT = 800

_last_hash: Optional[int] = None
_xrandr_cache: tuple[float, list[dict]] = (0.0, [])


def compute_target_size(
    width: int, height: int, max_width: int = MAX_WIDTH, max_height: int = MAX_HEIGHT
) -> tuple[int, int]:
    if width <= max_width and height <= max_height:
        return (width, height)
    ratio_w = max_width / width
    ratio_h = max_height / height
    ratio = min(ratio_w, ratio_h)
    return (int(width * ratio), int(height * ratio))


def encode_jpeg(img: Image.Image, quality: int = 75) -> bytes:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def image_hash(img: Image.Image) -> int:
    """Compute a 64-bit perceptual difference hash (dHash).

    Encodes relative brightness changes between adjacent pixels,
    tolerant of minor rendering differences (cursor blink, clock tick).
    """
    small = img.resize((9, 8), Image.Resampling.LANCZOS).convert("L")
    pixels = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            idx = row * 9 + col
            if pixels[idx] > pixels[idx + 1]:
                bits |= 1 << (row * 8 + col)
    return bits


def images_match(hash1: int, hash2: int, threshold: int = 5) -> bool:
    """Compare two dHash values via Hamming distance.

    Args:
        threshold: Max number of differing bits (default 5 of 64).
    """
    return bin(hash1 ^ hash2).count("1") <= threshold


def scale_image(img: Image.Image) -> Image.Image:
    target_w, target_h = compute_target_size(img.width, img.height)
    if (target_w, target_h) == (img.width, img.height):
        return img
    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)


def encode_for_api(img: Image.Image) -> tuple[str, int]:
    for quality in [75, 50, 30]:
        data = encode_jpeg(img, quality=quality)
        b64 = base64.b64encode(data).decode("ascii")
        if len(b64) <= 100_000 or quality == 30:
            return (b64, len(data))
    data = encode_jpeg(img, quality=30)
    return (base64.b64encode(data).decode("ascii"), len(data))


def _patch_randr_errors() -> None:
    """Patch python-xlib's RandR error classes to inherit XError.

    The upstream stubs (BadRRCrtcError, BadRRModeError, BadRROutputError) extend
    bare Exception instead of XError, so they never get a sequence_number attribute.
    When the X server sends one of these error events, python-xlib's display loop
    crashes with AttributeError: 'BadRRCrtcError' object has no attribute
    'sequence_number', poisoning the connection.  Rebasing onto XError fixes this.
    """
    try:
        from Xlib import error as xerror
        from Xlib.ext import randr

        for cls_name in ("BadRRCrtcError", "BadRRModeError", "BadRROutputError"):
            cls = getattr(randr, cls_name, None)
            if cls is not None and not issubclass(cls, xerror.XError):
                patched = type(cls_name, (xerror.XError,), dict(cls.__dict__))
                setattr(randr, cls_name, patched)
    except Exception:
        pass


def capture_fullscreen(display=None, monitor: str | None = None) -> tuple[Image.Image, dict]:
    from Xlib import X, display as xdisplay

    _patch_randr_errors()

    owns_display = display is None
    if owns_display:
        display = xdisplay.Display()

    try:
        root = display.screen().root
        root_geom = root.get_geometry()
        full_w, full_h = root_geom.width, root_geom.height

        mon_x, mon_y, mon_w, mon_h, mon_name, mon_warning = _get_target_monitor_geometry(
            full_w, full_h, monitor=monitor
        )

        # Hide cursor during capture
        try:
            from Xlib.ext import xfixes
            xfixes.hide_cursor(root)
            cursor_hidden = True
        except Exception:
            cursor_hidden = False

        # Try XShm fast path
        img = None
        capture_method = "get_image"
        try:
            img = _capture_xshm(display, root, mon_x, mon_y, mon_w, mon_h)
            capture_method = "xshm"
        except Exception:
            pass

        # Fallback to get_image
        if img is None:
            raw = root.get_image(mon_x, mon_y, mon_w, mon_h, X.ZPixmap, 0xFFFFFFFF)
            img = Image.frombytes("RGBX", (mon_w, mon_h), raw.data, "raw", "BGRX")
            img = img.convert("RGB")

        # Show cursor again
        if cursor_hidden:
            try:
                xfixes.show_cursor(root)
            except Exception:
                pass

        metadata = {
            "capture_mode": "fullscreen",
            "capture_method": capture_method,
            "monitor": mon_name,
            "native_width": mon_w,
            "native_height": mon_h,
            "monitor_x": mon_x,
            "monitor_y": mon_y,
        }
        if mon_warning:
            metadata["warning"] = mon_warning
        return (img, metadata)
    finally:
        if owns_display:
            display.close()


def _capture_xshm(display, root, x: int, y: int, w: int, h: int) -> Image.Image:
    """Capture a screen region via MIT-SHM shared memory.

    Uses zero-copy shared memory instead of copying pixels over the X11 socket.
    ~3x faster than get_image on 2560x1440.

    Raises Exception on any failure (caller falls back to get_image).
    """
    from x11_mcp._shm import (
        ShmSegment, ShmAttach, ShmDetach, ShmGetImage,
        xshm_available, get_shm_opcode,
    )

    if not xshm_available(display):
        raise RuntimeError("MIT-SHM not available")

    opcode = get_shm_opcode(display)
    size = w * h * 4  # BGRX = 4 bytes per pixel

    with ShmSegment(size) as seg:
        shmseg = display.display.allocate_resource_id()
        try:
            ShmAttach(
                display=display.display, opcode=opcode,
                shmseg=shmseg, shmid=seg.shmid, read_only=False,
            )
            display.sync()

            ShmGetImage(
                display=display.display, opcode=opcode,
                drawable=root.id,
                x=x, y=y, width=w, height=h,
                plane_mask=0xFFFFFFFF, format=2,  # ZPixmap
                shmseg=shmseg, offset=0,
            )

            raw = seg.as_bytes(size)
            img = Image.frombytes("RGBX", (w, h), raw, "raw", "BGRX")
            img = img.convert("RGB")
        finally:
            ShmDetach(display=display.display, opcode=opcode, shmseg=shmseg)
            display.sync()

    return img


def capture_window(window_id: int, display=None) -> tuple[Image.Image, dict]:
    from Xlib import X, display as xdisplay

    owns_display = display is None
    if owns_display:
        display = xdisplay.Display()

    try:
        window = display.create_resource_object("window", window_id)
        geom = window.get_geometry()
        w, h = geom.width, geom.height

        raw = window.get_image(0, 0, w, h, X.ZPixmap, 0xFFFFFFFF)
        img = Image.frombytes("RGBX", (w, h), raw.data, "raw", "BGRX")
        img = img.convert("RGB")

        metadata = {
            "capture_mode": "window",
            "window_id": window_id,
            "native_width": w,
            "native_height": h,
        }
        return (img, metadata)
    finally:
        if owns_display:
            display.close()


def capture_region(x: int, y: int, w: int, h: int, display=None) -> tuple[Image.Image, dict]:
    from Xlib import X, display as xdisplay

    owns_display = display is None
    if owns_display:
        display = xdisplay.Display()

    try:
        root = display.screen().root
        raw = root.get_image(x, y, w, h, X.ZPixmap, 0xFFFFFFFF)
        img = Image.frombytes("RGBX", (w, h), raw.data, "raw", "BGRX")
        img = img.convert("RGB")

        metadata = {
            "capture_mode": "region",
            "region": {"x": x, "y": y, "w": w, "h": h},
            "native_width": w,
            "native_height": h,
        }
        return (img, metadata)
    finally:
        if owns_display:
            display.close()


def capture_zoom(x: int, y: int, size: int = 512, display=None) -> tuple[Image.Image, dict]:
    state = get_state()
    screen_x, screen_y = state.api_to_screen(x, y)

    half = size // 2
    crop_x = max(0, screen_x - half)
    crop_y = max(0, screen_y - half)

    img, _ = capture_region(crop_x, crop_y, size, size, display=display)

    state.set_zoom(region_x=crop_x, region_y=crop_y, region_w=size, region_h=size)

    metadata = {
        "capture_mode": "zoom",
        "center_api": {"x": x, "y": y},
        "center_screen": {"x": screen_x, "y": screen_y},
        "crop_origin": {"x": crop_x, "y": crop_y},
        "size": size,
        "native_resolution": True,
    }
    return (img, metadata)


def take_screenshot(
    mode: str = "fullscreen",
    window_id: int | None = None,
    region: dict | None = None,
    zoom_center: tuple[int, int] | None = None,
    zoom_size: int = 512,
    monitor: str | None = None,
) -> tuple[str, dict]:
    global _last_hash
    state = get_state()

    if mode == "zoom" and zoom_center is not None:
        img, meta = capture_zoom(zoom_center[0], zoom_center[1], zoom_size)
        b64, byte_size = encode_for_api(img)
        meta["api_width"] = img.width
        meta["api_height"] = img.height
        meta["byte_size"] = byte_size
        return (b64, meta)

    if mode == "window" and window_id is not None:
        img, meta = capture_window(window_id)
    elif mode == "region" and region is not None:
        img, meta = capture_region(region["x"], region["y"], region["w"], region["h"])
    else:
        img, meta = capture_fullscreen(monitor=monitor)

    state.clear_zoom()

    h = image_hash(img)
    meta["unchanged"] = images_match(h, _last_hash) if _last_hash is not None else False
    _last_hash = h

    scaled = scale_image(img)
    meta["api_width"] = scaled.width
    meta["api_height"] = scaled.height

    mon_x = meta.get("monitor_x", 0)
    mon_y = meta.get("monitor_y", 0)
    state.update(
        screen_width=meta["native_width"],
        screen_height=meta["native_height"],
        api_width=scaled.width,
        api_height=scaled.height,
        monitor_offset_x=mon_x,
        monitor_offset_y=mon_y,
    )

    b64, byte_size = encode_for_api(scaled)
    meta["byte_size"] = byte_size
    meta["scale_x"] = scaled.width / meta["native_width"]
    meta["scale_y"] = scaled.height / meta["native_height"]

    return (b64, meta)


def _get_target_monitor_geometry(
    full_w: int, full_h: int, monitor: str | None = None
) -> tuple[int, int, int, int, str, str | None]:
    """Get the geometry of the target monitor for capture.

    Strategy:
    - If monitor name is given, use that specific monitor.
    - Otherwise, default to the primary monitor.
    - Falls back to full root geometry if detection fails.

    Returns:
        (x, y, w, h, monitor_name, warning_or_none)
    """
    try:
        monitors = _parse_xrandr_monitors()
        if not monitors:
            return (0, 0, full_w, full_h, "unknown", None)

        if monitor is not None:
            target = _find_monitor_by_name(monitor, monitors)
            if target:
                return (target["x"], target["y"], target["w"], target["h"], target["name"], None)
            # Requested monitor not found — fall back to primary with warning
            primary = _get_primary_monitor(monitors)
            if primary:
                available = [m["name"] for m in monitors]
                warning = (
                    f'Monitor "{monitor}" not found. Available: {available}. '
                    f'Falling back to primary monitor "{primary["name"]}".'
                )
                return (primary["x"], primary["y"], primary["w"], primary["h"], primary["name"], warning)

        primary = _get_primary_monitor(monitors)
        if primary:
            return (primary["x"], primary["y"], primary["w"], primary["h"], primary["name"], None)

        m = monitors[0]
        return (m["x"], m["y"], m["w"], m["h"], m["name"], None)
    except Exception:
        return (0, 0, full_w, full_h, "unknown", None)


def _parse_xrandr_monitors() -> list[dict]:
    """Parse monitor geometries from xrandr CLI output.

    Returns list of dicts with keys: name, x, y, w, h, is_primary.
    Results are cached for 1 second to avoid repeated subprocess calls
    during compound operations like focus_and_capture().
    """
    global _xrandr_cache
    now = _time.monotonic()
    if now - _xrandr_cache[0] < 1.0 and _xrandr_cache[1]:
        return _xrandr_cache[1]

    import re
    import subprocess
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=5
        )
        monitors = []
        for line in result.stdout.splitlines():
            if " connected" in line:
                match = re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)", line)
                if match:
                    w, h, x, y = (
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                        int(match.group(4)),
                    )
                    name = line.split()[0]
                    is_primary = " primary " in line
                    monitors.append({
                        "name": name,
                        "x": x, "y": y, "w": w, "h": h,
                        "is_primary": is_primary,
                    })
        _xrandr_cache = (now, monitors)
        return monitors
    except Exception:
        return []


def _get_primary_monitor(monitors: list[dict] | None = None) -> dict | None:
    """Return the primary monitor, or first connected if none marked primary."""
    if monitors is None:
        monitors = _parse_xrandr_monitors()
    if not monitors:
        return None
    for mon in monitors:
        if mon["is_primary"]:
            return mon
    return monitors[0]


def _find_monitor_by_name(name: str, monitors: list[dict] | None = None) -> dict | None:
    """Find a monitor by output name (e.g., 'DP-2', 'HDMI-1')."""
    if monitors is None:
        monitors = _parse_xrandr_monitors()
    for mon in monitors:
        if mon["name"] == name:
            return mon
    return None
