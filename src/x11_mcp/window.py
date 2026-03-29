"""Window management via python-xlib and wmctrl.

Queries use python-xlib (fast, in-process). Resize/move uses wmctrl
(reliable across window managers, handles decorations correctly).
"""

from __future__ import annotations

import subprocess
from typing import Optional

from x11_mcp.scaling import get_state
from x11_mcp.screenshot import MAX_WIDTH, MAX_HEIGHT


def _run(cmd: list[str], timeout: int = 5) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def _run_check(cmd: list[str], timeout: int = 5) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def list_windows() -> list[dict]:
    try:
        output = _run(["wmctrl", "-l", "-G", "-x"])
    except FileNotFoundError:
        return _list_windows_xlib()

    windows = []
    for line in output.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 10:
            continue
        win_id = parts[0]
        try:
            windows.append({
                "id": int(win_id, 16),
                "id_hex": win_id,
                "x": int(parts[2]),
                "y": int(parts[3]),
                "width": int(parts[4]),
                "height": int(parts[5]),
                "class": parts[6],
                "title": parts[9] if len(parts) > 9 else parts[8],
            })
        except (ValueError, IndexError):
            continue
    return windows


def _list_windows_xlib() -> list[dict]:
    from Xlib import display as xdisplay, Xatom

    d = xdisplay.Display()
    root = d.screen().root

    prop = root.get_full_property(d.intern_atom("_NET_CLIENT_LIST"), Xatom.WINDOW)
    if prop is None:
        return []

    windows = []
    for win_id in prop.value:
        try:
            win = d.create_resource_object("window", win_id)
            geom = win.get_geometry()
            name_prop = win.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
            name = name_prop.value.decode("utf-8", errors="replace") if name_prop else ""
            windows.append({
                "id": win_id,
                "id_hex": hex(win_id),
                "x": 0, "y": 0,
                "width": geom.width,
                "height": geom.height,
                "class": "",
                "title": name,
            })
        except Exception:
            continue
    d.close()
    return windows


def get_active_window() -> Optional[dict]:
    from Xlib import display as xdisplay, Xatom

    d = xdisplay.Display()
    root = d.screen().root

    prop = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), Xatom.WINDOW)
    if prop is None or len(prop.value) == 0:
        d.close()
        return None

    win_id = prop.value[0]
    try:
        win = d.create_resource_object("window", win_id)
        geom = win.get_geometry()
        name_prop = win.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
        name = name_prop.value.decode("utf-8", errors="replace") if name_prop else ""
        coords = win.translate_coords(root, 0, 0)
        d.close()
        return {
            "id": win_id,
            "id_hex": hex(win_id),
            "x": abs(coords.x),
            "y": abs(coords.y),
            "width": geom.width,
            "height": geom.height,
            "title": name,
        }
    except Exception:
        d.close()
        return None


def get_monitor_geometries() -> list[dict]:
    from Xlib import display as xdisplay
    from Xlib.ext import randr

    d = xdisplay.Display()
    root = d.screen().root
    monitors = []

    try:
        resources = randr.get_screen_resources(root)
        for output_id in resources.outputs:
            output_info = randr.get_output_info(d, output_id, resources.config_timestamp)
            if output_info.crtc:
                crtc = randr.get_crtc_info(d, output_info.crtc, resources.config_timestamp)
                monitors.append({
                    "x": crtc.x,
                    "y": crtc.y,
                    "width": crtc.width,
                    "height": crtc.height,
                    "name": output_info.name,
                })
    except Exception:
        geom = root.get_geometry()
        monitors.append({
            "x": 0, "y": 0,
            "width": geom.width, "height": geom.height,
            "name": "default",
        })
    d.close()
    return monitors


def focus_window(window_id: int | None = None, name: str | None = None) -> bool:
    if window_id is not None:
        try:
            _run_check(["wmctrl", "-i", "-a", hex(window_id)])
            return True
        except (RuntimeError, FileNotFoundError):
            pass
        try:
            from Xlib import display as xdisplay, X

            d = xdisplay.Display()
            win = d.create_resource_object("window", window_id)
            win.raise_window()
            win.set_input_focus(X.RevertToParent, 0)
            d.sync()
            d.close()
            return True
        except Exception:
            return False

    if name is not None:
        try:
            _run_check(["wmctrl", "-a", name])
            return True
        except (RuntimeError, FileNotFoundError):
            return False

    return False


def resize_window(window_id: int, width: int, height: int) -> bool:
    try:
        _run_check(["wmctrl", "-i", "-r", hex(window_id), "-e", f"0,-1,-1,{width},{height}"])
        return True
    except (RuntimeError, FileNotFoundError):
        pass
    try:
        from Xlib import display as xdisplay

        d = xdisplay.Display()
        win = d.create_resource_object("window", window_id)
        win.configure(width=width, height=height)
        d.sync()
        d.close()
        return True
    except Exception:
        return False


def move_window(window_id: int, x: int, y: int) -> bool:
    try:
        _run_check(["wmctrl", "-i", "-r", hex(window_id), "-e", f"0,{x},{y},-1,-1"])
        return True
    except (RuntimeError, FileNotFoundError):
        pass
    try:
        from Xlib import display as xdisplay

        d = xdisplay.Display()
        win = d.create_resource_object("window", window_id)
        win.configure(x=x, y=y)
        d.sync()
        d.close()
        return True
    except Exception:
        return False


def optimize_for_capture(window_id: int | None = None) -> dict:
    if window_id is None:
        active = get_active_window()
        if active is None:
            return {"error": "No active window found"}
        window_id = active["id"]

    monitors = get_monitor_geometries()
    active = get_active_window()
    mon_x, mon_y = 0, 0
    if active and monitors:
        for mon in monitors:
            if mon["x"] <= active["x"] < mon["x"] + mon["width"]:
                mon_x, mon_y = mon["x"], mon["y"]
                break

    try:
        _run_check([
            "wmctrl", "-i", "-r", hex(window_id),
            "-e", f"0,{mon_x},{mon_y},{MAX_WIDTH},{MAX_HEIGHT}"
        ])
    except (RuntimeError, FileNotFoundError):
        move_window(window_id, mon_x, mon_y)
        resize_window(window_id, MAX_WIDTH, MAX_HEIGHT)

    return {
        "window_id": window_id,
        "x": mon_x, "y": mon_y,
        "width": MAX_WIDTH, "height": MAX_HEIGHT,
        "note": f"Window resized to {MAX_WIDTH}x{MAX_HEIGHT}. Screenshots will be 1:1 — no scaling needed.",
    }
