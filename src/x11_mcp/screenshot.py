"""Screenshot capture via python-xlib with PIL scaling.

Captures the X11 framebuffer directly into RAM — zero disk I/O.
Scales to Claude's target resolution using LANCZOS resampling.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from typing import Optional

from PIL import Image

from x11_mcp.scaling import get_state

MAX_WIDTH = 1280
MAX_HEIGHT = 800

_last_hash: Optional[str] = None


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


def image_hash(img: Image.Image) -> str:
    small = img.resize((16, 16), Image.Resampling.LANCZOS).convert("L")
    return hashlib.md5(small.tobytes()).hexdigest()


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


def capture_fullscreen(display=None) -> tuple[Image.Image, dict]:
    from Xlib import X, display as xdisplay

    _patch_randr_errors()

    if display is None:
        display = xdisplay.Display()

    root = display.screen().root
    root_geom = root.get_geometry()
    full_w, full_h = root_geom.width, root_geom.height

    # Use a separate Display connection for monitor detection to avoid
    # cross-contamination from any Xrandr errors on the capture connection
    try:
        det_display = xdisplay.Display()
        mon_x, mon_y, mon_w, mon_h = _get_active_monitor_geometry(det_display, full_w, full_h)
        det_display.close()
    except Exception:
        mon_x, mon_y, mon_w, mon_h = 0, 0, full_w, full_h

    # Hide cursor during capture
    try:
        from Xlib.ext import xfixes
        xfixes.hide_cursor(root)
        cursor_hidden = True
    except Exception:
        cursor_hidden = False

    raw = root.get_image(mon_x, mon_y, mon_w, mon_h, X.ZPixmap, 0xFFFFFFFF)

    # Show cursor again
    if cursor_hidden:
        try:
            xfixes.show_cursor(root)
        except Exception:
            pass

    img = Image.frombytes("RGBX", (mon_w, mon_h), raw.data, "raw", "BGRX")
    img = img.convert("RGB")

    metadata = {
        "capture_mode": "fullscreen",
        "native_width": mon_w,
        "native_height": mon_h,
        "monitor_x": mon_x,
        "monitor_y": mon_y,
    }
    return (img, metadata)


def capture_window(window_id: int, display=None) -> tuple[Image.Image, dict]:
    from Xlib import X, display as xdisplay

    if display is None:
        display = xdisplay.Display()

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


def capture_region(x: int, y: int, w: int, h: int, display=None) -> tuple[Image.Image, dict]:
    from Xlib import X, display as xdisplay

    if display is None:
        display = xdisplay.Display()

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
        img, meta = capture_fullscreen()

    state.clear_zoom()

    h = image_hash(img)
    meta["unchanged"] = (h == _last_hash)
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


def _get_active_monitor_geometry(
    display, full_w: int, full_h: int
) -> tuple[int, int, int, int]:
    """Find the geometry of the monitor containing the active window."""
    try:
        from Xlib import Xatom

        root = display.screen().root

        # Get active window position
        prop = root.get_full_property(
            display.intern_atom("_NET_ACTIVE_WINDOW"), Xatom.WINDOW
        )
        if prop is None or len(prop.value) == 0:
            return (0, 0, full_w, full_h)

        active_win_id = prop.value[0]
        active_win = display.create_resource_object("window", active_win_id)
        coords = active_win.translate_coords(root, 0, 0)
        win_x = abs(coords.x)
        win_y = abs(coords.y)

        # Parse monitor geometries from xrandr CLI (avoids python-xlib Xrandr bugs)
        monitors = _parse_xrandr_monitors()
        if not monitors:
            return (0, 0, full_w, full_h)

        # Find which monitor contains the active window
        for mx, my, mw, mh in monitors:
            if mx <= win_x < mx + mw and my <= win_y < my + mh:
                return (mx, my, mw, mh)

        return monitors[0]
    except Exception:
        return (0, 0, full_w, full_h)


def _parse_xrandr_monitors() -> list[tuple[int, int, int, int]]:
    """Parse monitor geometries from xrandr CLI output."""
    import re
    import subprocess
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=5
        )
        monitors = []
        for line in result.stdout.splitlines():
            if " connected" in line:
                # Match patterns like "2560x1440+0+0" or "2560x1440+2560+0"
                match = re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)", line)
                if match:
                    w, h, x, y = (
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                        int(match.group(4)),
                    )
                    monitors.append((x, y, w, h))
        return monitors
    except Exception:
        return []
