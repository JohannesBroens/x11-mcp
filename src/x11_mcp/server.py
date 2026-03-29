"""x11-mcp: Native X11 MCP server for Claude Code.

Fast desktop automation via python-xlib capture, python-uinput input,
and AT-SPI accessibility. No Docker, no virtual displays.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from mcp.server.fastmcp import FastMCP, Image

from x11_mcp.scaling import get_state
from x11_mcp.screenshot import take_screenshot
from x11_mcp.input import get_input_device
from x11_mcp.window import (
    list_windows as _list_windows,
    get_active_window,
    get_monitor_geometries,
    focus_window as _focus_window,
    resize_window as _resize_window,
    move_window as _move_window,
    optimize_for_capture as _optimize,
)
from x11_mcp.accessibility import (
    get_accessibility_tree as _get_tree,
    find_element as _find_element,
)

mcp = FastMCP("x11-mcp")


@mcp.tool()
def screenshot(
    mode: str = "fullscreen",
    window_id: int | None = None,
    region_x: int | None = None,
    region_y: int | None = None,
    region_w: int | None = None,
    region_h: int | None = None,
) -> list:
    """Capture the screen. Returns an image Claude can see.

    Args:
        mode: "fullscreen" (active monitor), "window" (specific window), or "region" (arbitrary rect).
        window_id: X11 window ID (required for mode="window").
        region_x, region_y, region_w, region_h: Region bounds (required for mode="region").
    """
    region = None
    if mode == "region" and all(v is not None for v in [region_x, region_y, region_w, region_h]):
        region = {"x": region_x, "y": region_y, "w": region_w, "h": region_h}

    b64, meta = take_screenshot(mode=mode, window_id=window_id, region=region)
    return [
        Image(data=b64, format="jpeg"),
        json.dumps(meta, indent=2),
    ]


@mcp.tool()
def zoom(x: int, y: int, size: int = 512) -> list:
    """Zoom into a region at native resolution for detail inspection.

    Use when you need to read small text or inspect fine UI details.
    Coordinates are in the same space as the last screenshot.
    After zooming, click coordinates map to the zoomed region until the next full screenshot.

    Args:
        x: Center x coordinate (API space).
        y: Center y coordinate (API space).
        size: Crop size in pixels (default 512x512 at native resolution).
    """
    b64, meta = take_screenshot(mode="zoom", zoom_center=(x, y), zoom_size=size)
    return [
        Image(data=b64, format="jpeg"),
        json.dumps(meta, indent=2),
    ]


@mcp.tool()
def mouse_click(x: int, y: int, button: str = "left", count: int = 1) -> str:
    """Click at coordinates. Coordinates are in the same space as the last screenshot.

    Args:
        x: X coordinate.
        y: Y coordinate.
        button: "left", "right", or "middle".
        count: Number of clicks (1=single, 2=double, 3=triple).
    """
    dev = get_input_device()
    dev.click(x, y, button=button, count=count)
    return f"Clicked {button} at ({x}, {y}) x{count}"


@mcp.tool()
def mouse_move(x: int, y: int) -> str:
    """Move the mouse cursor without clicking.

    Args:
        x: X coordinate.
        y: Y coordinate.
    """
    dev = get_input_device()
    dev.move(x, y)
    return f"Moved cursor to ({x}, {y})"


@mcp.tool()
def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left") -> str:
    """Drag from one point to another (click-hold-move-release).

    Args:
        start_x: Start X coordinate.
        start_y: Start Y coordinate.
        end_x: End X coordinate.
        end_y: End Y coordinate.
        button: "left", "right", or "middle".
    """
    dev = get_input_device()
    dev.drag(start_x, start_y, end_x, end_y, button=button)
    return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"


@mcp.tool()
def mouse_scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> str:
    """Scroll at a position.

    Args:
        x: X coordinate.
        y: Y coordinate.
        direction: "up", "down", "left", or "right".
        amount: Number of scroll ticks (default 3).
    """
    dev = get_input_device()
    dev.scroll(x, y, direction=direction, amount=amount)
    return f"Scrolled {direction} x{amount} at ({x}, {y})"


@mcp.tool()
def type_text(text: str, delay_ms: int = 12) -> str:
    """Type text by synthesizing keyboard events.

    Args:
        text: The text to type.
        delay_ms: Delay between keystrokes in milliseconds (default 12).
    """
    dev = get_input_device()
    dev.type_text(text, delay_ms=delay_ms)
    return f"Typed {len(text)} characters"


@mcp.tool()
def key_press(keys: str, repeat: int = 1) -> str:
    """Press a key or key combination.

    Examples: "Return", "ctrl+c", "alt+Tab", "ctrl+shift+t", "Escape"

    Args:
        keys: Key combo string (e.g., "ctrl+c").
        repeat: Number of times to press (default 1).
    """
    dev = get_input_device()
    dev.key(keys, repeat=repeat)
    return f"Pressed {keys}" + (f" x{repeat}" if repeat > 1 else "")


@mcp.tool()
def hold_key(key: str, duration: float = 1.0) -> str:
    """Hold a key down for a duration.

    Args:
        key: Key name (e.g., "shift", "ctrl").
        duration: Hold duration in seconds.
    """
    dev = get_input_device()
    dev.hold_key(key, duration)
    return f"Held {key} for {duration}s"


@mcp.tool()
def get_accessibility_tree(max_depth: int = 3) -> str:
    """Get the accessibility tree of the focused window.

    Returns structured text showing all UI elements with their roles,
    names, coordinates, and states. Use this alongside screenshots for
    precise element targeting.

    Args:
        max_depth: Maximum tree depth to traverse (default 3).
    """
    return _get_tree(max_depth=max_depth)


@mcp.tool()
def find_element(query: str, max_depth: int = 5) -> str:
    """Find UI elements by name, role, or label text.

    Case-insensitive substring search. Returns matching elements with
    exact coordinates and a suggested click target (center point).

    Example: find_element("Save") finds Save buttons with click coordinates.

    Args:
        query: Search string to match against element names/roles/labels.
        max_depth: Maximum tree depth to search (default 5).
    """
    return _find_element(query, max_depth=max_depth)


@mcp.tool()
def list_windows() -> str:
    """List all visible windows with their IDs, titles, and geometry."""
    windows = _list_windows()
    if not windows:
        return "No windows found"
    lines = []
    for w in windows:
        lines.append(
            f"[{w['id_hex']}] \"{w['title']}\" "
            f"({w['x']},{w['y']} {w['width']}x{w['height']})"
        )
    return "\n".join(lines)


@mcp.tool()
def focus_window(window_id: int | None = None, name: str | None = None) -> str:
    """Bring a window to front and focus it.

    Args:
        window_id: X11 window ID (from list_windows).
        name: Window title substring to match.
    """
    if window_id is None and name is None:
        return "Error: provide either window_id or name"
    ok = _focus_window(window_id=window_id, name=name)
    target = hex(window_id) if window_id else name
    return f"Focused window {target}" if ok else f"Failed to focus window {target}"


@mcp.tool()
def resize_window(window_id: int, width: int, height: int) -> str:
    """Resize a window.

    Args:
        window_id: X11 window ID (from list_windows).
        width: New width in pixels.
        height: New height in pixels.
    """
    ok = _resize_window(window_id, width, height)
    return f"Resized {hex(window_id)} to {width}x{height}" if ok else "Resize failed"


@mcp.tool()
def move_window(window_id: int, x: int, y: int) -> str:
    """Move a window to a position.

    Args:
        window_id: X11 window ID (from list_windows).
        x: New X position.
        y: New Y position.
    """
    ok = _move_window(window_id, x, y)
    return f"Moved {hex(window_id)} to ({x}, {y})" if ok else "Move failed"


@mcp.tool()
def optimize_for_capture(window_id: int | None = None) -> str:
    """Resize the window to 1280x800 for pixel-perfect screenshots.

    This eliminates coordinate scaling — what you see in the screenshot
    maps 1:1 to the screen. Use this when you need maximum accuracy.

    Args:
        window_id: Window to optimize (default: active window).
    """
    result = _optimize(window_id=window_id)
    return json.dumps(result, indent=2)


@mcp.tool()
def batch(actions: list[dict]) -> str:
    """Execute multiple actions in rapid sequence without thinking gaps.

    Each action is a dict with "action" key and parameters.
    Supported actions: click, double_click, right_click, move, type, key, scroll, wait, focus.

    Example: [{"action": "click", "x": 100, "y": 200}, {"action": "type", "text": "hello"}, {"action": "key", "keys": "Return"}]
    """
    dev = get_input_device()
    log = []

    for i, act in enumerate(actions):
        action = act.get("action", "")
        try:
            if action == "click":
                dev.click(act["x"], act["y"], button=act.get("button", "left"), count=1)
                log.append(f"{i+1}. click ({act['x']}, {act['y']})")
            elif action == "double_click":
                dev.click(act["x"], act["y"], button="left", count=2)
                log.append(f"{i+1}. double_click ({act['x']}, {act['y']})")
            elif action == "right_click":
                dev.click(act["x"], act["y"], button="right", count=1)
                log.append(f"{i+1}. right_click ({act['x']}, {act['y']})")
            elif action == "move":
                dev.move(act["x"], act["y"])
                log.append(f"{i+1}. move ({act['x']}, {act['y']})")
            elif action == "type":
                dev.type_text(act["text"], delay_ms=act.get("delay_ms", 12))
                log.append(f"{i+1}. type {len(act['text'])} chars")
            elif action == "key":
                dev.key(act["keys"], repeat=act.get("repeat", 1))
                log.append(f"{i+1}. key {act['keys']}")
            elif action == "scroll":
                dev.scroll(act["x"], act["y"], direction=act.get("direction", "down"), amount=act.get("amount", 3))
                log.append(f"{i+1}. scroll {act.get('direction', 'down')}")
            elif action == "wait":
                time.sleep(min(act.get("seconds", 0.5), 10))
                log.append(f"{i+1}. wait {act.get('seconds', 0.5)}s")
            elif action == "focus":
                _focus_window(window_id=act.get("window_id"), name=act.get("name"))
                log.append(f"{i+1}. focus {act.get('name', act.get('window_id'))}")
            else:
                log.append(f"{i+1}. unknown action: {action}")
        except Exception as e:
            log.append(f"{i+1}. ERROR in {action}: {e}")
            break

    return "\n".join(log)


@mcp.tool()
def screen_info() -> str:
    """Get screen resolution, mouse position, and scaling state."""
    state = get_state()
    monitors = get_monitor_geometries()
    info = {
        "monitors": monitors,
        "scaling": {
            "screen_size": state.screen_size,
            "api_size": state.api_size,
            "monitor_offset": state.monitor_offset,
            "zoom_active": state.is_zoom_active,
        },
    }
    try:
        from Xlib import display as xdisplay

        d = xdisplay.Display()
        data = d.screen().root.query_pointer()
        info["mouse"] = {"x": data.root_x, "y": data.root_y}
        d.close()
    except Exception:
        info["mouse"] = {"error": "Could not query mouse position"}
    return json.dumps(info, indent=2)


@mcp.tool()
def calibrate() -> str:
    """Self-test coordinate scaling accuracy.

    Moves the mouse to 5 known positions and verifies the actual
    screen position matches the expected position. Reports PASS
    if all errors are <= 2px.
    """
    state = get_state()
    if state.screen_size == (0, 0):
        return "Error: Take a screenshot first to initialize scaling."

    dev = get_input_device()
    api_w, api_h = state.api_size

    test_points = [
        ("center", api_w // 2, api_h // 2),
        ("top-left quarter", api_w // 4, api_h // 4),
        ("top-right quarter", 3 * api_w // 4, api_h // 4),
        ("bottom-left quarter", api_w // 4, 3 * api_h // 4),
        ("bottom-right quarter", 3 * api_w // 4, 3 * api_h // 4),
    ]

    results = []
    max_error = 0

    for name, ax, ay in test_points:
        expected_sx, expected_sy = state.api_to_screen(ax, ay)
        dev.move(ax, ay)
        time.sleep(0.1)

        try:
            from Xlib import display as xdisplay

            d = xdisplay.Display()
            data = d.screen().root.query_pointer()
            actual_sx, actual_sy = data.root_x, data.root_y
            d.close()
        except Exception:
            results.append(f"  {name}: COULD NOT READ POSITION")
            continue

        err_x = abs(actual_sx - expected_sx)
        err_y = abs(actual_sy - expected_sy)
        error = max(err_x, err_y)
        max_error = max(max_error, error)
        status = "OK" if error <= 2 else "DRIFT"
        results.append(
            f"  {name}: expected ({expected_sx},{expected_sy}), "
            f"actual ({actual_sx},{actual_sy}), error {error}px [{status}]"
        )

    verdict = "PASS" if max_error <= 2 else f"FAIL (max error: {max_error}px)"
    return f"Calibration: {verdict}\n" + "\n".join(results)


@mcp.tool()
def clipboard(action: str = "get", text: str | None = None) -> str:
    """Read or write the system clipboard.

    Args:
        action: "get" to read clipboard, "set" to write.
        text: Text to write (required for action="set").
    """
    if action == "set" and text is not None:
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(), capture_output=True, timeout=5
        )
        return f"Clipboard set ({len(text)} chars)"
    elif action == "get":
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True, text=True, timeout=5
        )
        return proc.stdout
    return "Error: action must be 'get' or 'set'"


@mcp.tool()
def launch_app(command: str) -> str:
    """Launch a desktop application.

    Args:
        command: The command to run (e.g., "firefox", "nautilus ~/Documents").
    """
    proc = subprocess.Popen(
        command, shell=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return f"Launched: {command} (PID {proc.pid})"


@mcp.tool()
def wait(seconds: float = 1.0) -> str:
    """Wait for a specified duration (e.g., for animations or page loads).

    Args:
        seconds: Duration to wait (0.1 to 10 seconds).
    """
    seconds = max(0.1, min(seconds, 10.0))
    time.sleep(seconds)
    return f"Waited {seconds}s"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
