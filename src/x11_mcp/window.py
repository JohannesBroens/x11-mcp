"""Window management via python-xlib and wmctrl.

Queries use python-xlib (fast, in-process). Resize/move uses wmctrl
(reliable across window managers, handles decorations correctly).
"""

from __future__ import annotations

import subprocess
import time
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
        # wmctrl -l -G -x format: ID DESKTOP X Y W H CLASS HOST TITLE...
        # split(None, 8) keeps the full title (including spaces) in parts[8]
        parts = line.split(None, 8)
        if len(parts) < 9:
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
                "title": parts[8],
            })
        except (ValueError, IndexError):
            continue
    return windows


def _list_windows_xlib() -> list[dict]:
    from Xlib import display as xdisplay, Xatom

    d = xdisplay.Display()
    try:
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
                class_prop = win.get_wm_class()
                wm_class = ".".join(class_prop) if class_prop else ""
                windows.append({
                    "id": win_id,
                    "id_hex": hex(win_id),
                    "x": 0, "y": 0,
                    "width": geom.width,
                    "height": geom.height,
                    "class": wm_class,
                    "title": name,
                })
            except Exception:
                continue
        return windows
    finally:
        d.close()


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
    """Return monitor geometries with primary annotation.

    Uses xrandr CLI (more reliable than python-xlib's RandR bindings on Nvidia).
    Falls back to python-xlib if xrandr is unavailable.
    """
    from x11_mcp.screenshot import _parse_xrandr_monitors

    xrandr_mons = _parse_xrandr_monitors()
    if xrandr_mons:
        return [
            {
                "name": m["name"],
                "x": m["x"],
                "y": m["y"],
                "width": m["w"],
                "height": m["h"],
                "is_primary": m["is_primary"],
            }
            for m in xrandr_mons
        ]

    # Fallback to python-xlib
    try:
        from Xlib import display as xdisplay
        from Xlib.ext import randr

        d = xdisplay.Display()
        try:
            root = d.screen().root
            monitors = []

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
                        "is_primary": len(monitors) == 0,
                    })
        finally:
            d.close()
        if monitors:
            return monitors
    except Exception:
        pass

    # Last resort: full root geometry
    try:
        from Xlib import display as xdisplay
        d = xdisplay.Display()
        try:
            geom = d.screen().root.get_geometry()
        finally:
            d.close()
        return [{
            "x": 0, "y": 0,
            "width": geom.width, "height": geom.height,
            "name": "default", "is_primary": True,
        }]
    except Exception:
        return []


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
            try:
                win = d.create_resource_object("window", window_id)
                win.raise_window()
                win.set_input_focus(X.RevertToParent, 0)
                d.sync()
            finally:
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
        try:
            win = d.create_resource_object("window", window_id)
            win.configure(width=width, height=height)
            d.sync()
        finally:
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
        try:
            win = d.create_resource_object("window", window_id)
            win.configure(x=x, y=y)
            d.sync()
        finally:
            d.close()
        return True
    except Exception:
        return False


def ensure_on_monitor(
    window_id: int,
    monitor_name: str | None = None,
    optimize: bool = True,
) -> dict:
    """Move a window to the target monitor, optionally resizing for capture.

    Args:
        window_id: X11 window ID.
        monitor_name: Target monitor output name (e.g., "DP-2"). Defaults to primary.
        optimize: If True, resize to MAX_WIDTH x MAX_HEIGHT for 1:1 screenshot mapping.

    Returns:
        Dict with result info including final position and any warnings.
    """
    from x11_mcp.screenshot import _get_primary_monitor, _find_monitor_by_name

    if monitor_name:
        target = _find_monitor_by_name(monitor_name)
    else:
        target = _get_primary_monitor()

    if target is None:
        return {"error": "Could not determine target monitor"}

    target_x, target_y = target["x"], target["y"]
    target_w, target_h = target["w"], target["h"]

    if optimize:
        win_w = min(MAX_WIDTH, target_w)
        win_h = min(MAX_HEIGHT, target_h)
    else:
        # Preserve current window size, just move it
        try:
            from Xlib import display as xdisplay
            d = xdisplay.Display()
            try:
                win = d.create_resource_object("window", window_id)
                geom = win.get_geometry()
                win_w, win_h = geom.width, geom.height
            finally:
                d.close()
        except Exception:
            win_w, win_h = MAX_WIDTH, MAX_HEIGHT

    # Move and optionally resize via wmctrl (single command, handles decorations)
    try:
        _run_check([
            "wmctrl", "-i", "-r", hex(window_id),
            "-e", f"0,{target_x},{target_y},{win_w},{win_h}"
        ])
    except (RuntimeError, FileNotFoundError):
        # Fallback: separate move + resize
        move_window(window_id, target_x, target_y)
        if optimize:
            resize_window(window_id, win_w, win_h)

    # Focus the window
    focus_window(window_id=window_id)

    # Wait for WM to finish placing the window (poll, don't blind-sleep).
    # The WM may take a few frames to process the move/resize. We poll the
    # actual geometry until it stabilizes or we hit a timeout.
    actual_w, actual_h = win_w, win_h
    settled = False
    prev_x, prev_y, prev_w, prev_h = -1, -1, -1, -1
    for _ in range(20):  # max 20 polls * 15ms = 300ms worst case
        time.sleep(0.015)
        try:
            from Xlib import display as xdisplay
            d = xdisplay.Display()
            try:
                win = d.create_resource_object("window", window_id)
                geom = win.get_geometry()
                coords = win.translate_coords(d.screen().root, 0, 0)
                cur_x, cur_y = abs(coords.x), abs(coords.y)
                cur_w, cur_h = geom.width, geom.height
            finally:
                d.close()

            if (cur_x, cur_y, cur_w, cur_h) == (prev_x, prev_y, prev_w, prev_h):
                # Geometry hasn't changed between polls — WM is done
                actual_w, actual_h = cur_w, cur_h
                settled = True
                break
            prev_x, prev_y, prev_w, prev_h = cur_x, cur_y, cur_w, cur_h
        except Exception:
            break

    if not settled:
        # Final read even if we didn't see stabilization
        try:
            from Xlib import display as xdisplay
            d = xdisplay.Display()
            try:
                win = d.create_resource_object("window", window_id)
                geom = win.get_geometry()
                actual_w, actual_h = geom.width, geom.height
            finally:
                d.close()
        except Exception:
            pass

    result = {
        "window_id": window_id,
        "monitor": target.get("name", "unknown"),
        "x": target_x,
        "y": target_y,
        "width": actual_w,
        "height": actual_h,
        "optimized": optimize,
    }

    if optimize and (actual_w != win_w or actual_h != win_h):
        result["warning"] = (
            f"Window resized to {actual_w}x{actual_h} instead of requested "
            f"{win_w}x{win_h}. The window may have size constraints."
        )

    return result


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
