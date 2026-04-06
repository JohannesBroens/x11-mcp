"""Input injection backends for x11-mcp.

UinputBackend: kernel-level via python-uinput (fast, default).
XdotoolBackend: XTest synthetic events via xdotool subprocess (works with CEF/Electron).
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Optional

from x11_mcp.scaling import get_state


def _detect_screen_size() -> tuple[int, int]:
    """Detect screen resolution via xrandr or python-xlib."""
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=5
        )
        match = re.search(r"current (\d+) x (\d+)", result.stdout)
        if match:
            return (int(match.group(1)), int(match.group(2)))
    except Exception:
        pass
    try:
        from Xlib import display as xdisplay
        d = xdisplay.Display()
        try:
            geom = d.screen().root.get_geometry()
            return (geom.width, geom.height)
        finally:
            d.close()
    except Exception:
        pass
    return (1920, 1080)

MODIFIER_MAP = {
    "ctrl": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "alt": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA",
    "meta": "KEY_LEFTMETA",
}

SPECIAL_CHARS = {
    " ": "space",
    "\n": "Return",
    "\r": "Return",
    "\t": "Tab",
    "\b": "BackSpace",
}

SHIFT_SYMBOLS = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "minus", "+": "equal", "{": "bracketleft", "}": "bracketright",
    "|": "backslash", ":": "semicolon", '"': "apostrophe",
    "<": "comma", ">": "period", "?": "slash", "~": "grave",
}


def parse_key_combo(combo: str) -> tuple[list[str], str]:
    parts = combo.split("+")
    modifiers = []
    for part in parts[:-1]:
        low = part.lower().strip()
        if low in MODIFIER_MAP or low in ("ctrl", "shift", "alt", "super", "meta"):
            modifiers.append(low)
    key = parts[-1].strip()
    return (modifiers, key)


def char_to_key_events(char: str) -> list[tuple[str, str]]:
    if char in SPECIAL_CHARS:
        return [("key", SPECIAL_CHARS[char])]
    if char in SHIFT_SYMBOLS:
        base_key = SHIFT_SYMBOLS[char]
        return [("hold", "shift"), ("key", base_key), ("release", "shift")]
    if char.isupper():
        return [("hold", "shift"), ("key", char.lower()), ("release", "shift")]
    if char.islower() or char.isdigit():
        return [("key", char)]
    simple_punct = {
        "-": "minus", "=": "equal", "[": "bracketleft", "]": "bracketright",
        "\\": "backslash", ";": "semicolon", "'": "apostrophe",
        ",": "comma", ".": "period", "/": "slash", "`": "grave",
    }
    if char in simple_punct:
        return [("key", simple_punct[char])]
    return [("key", char)]


_KEY_NAME_TO_CODE: dict[str, int] = {}


def _build_key_map():
    global _KEY_NAME_TO_CODE
    if _KEY_NAME_TO_CODE:
        return
    try:
        import uinput
        for c in "abcdefghijklmnopqrstuvwxyz":
            code = getattr(uinput, f"KEY_{c.upper()}", None)
            if code:
                _KEY_NAME_TO_CODE[c] = code
        for d in "0123456789":
            code = getattr(uinput, f"KEY_{d}", None)
            if code:
                _KEY_NAME_TO_CODE[d] = code
        for i in range(1, 13):
            code = getattr(uinput, f"KEY_F{i}", None)
            if code:
                _KEY_NAME_TO_CODE[f"F{i}"] = code
                _KEY_NAME_TO_CODE[f"f{i}"] = code
        uinput_names = {
            "Return": "KEY_ENTER", "Tab": "KEY_TAB", "BackSpace": "KEY_BACKSPACE",
            "Delete": "KEY_DELETE", "Escape": "KEY_ESC",
            "Up": "KEY_UP", "Down": "KEY_DOWN", "Left": "KEY_LEFT", "Right": "KEY_RIGHT",
            "Home": "KEY_HOME", "End": "KEY_END", "PageUp": "KEY_PAGEUP",
            "PageDown": "KEY_PAGEDOWN", "Insert": "KEY_INSERT",
            "Pause": "KEY_PAUSE", "Print": "KEY_PRINT",
        }
        for name, uname in uinput_names.items():
            code = getattr(uinput, uname, None)
            if code:
                _KEY_NAME_TO_CODE[name] = code
                _KEY_NAME_TO_CODE[name.lower()] = code
        punct_map = {
            "space": "KEY_SPACE", "minus": "KEY_MINUS", "equal": "KEY_EQUAL",
            "bracketleft": "KEY_LEFTBRACE", "bracketright": "KEY_RIGHTBRACE",
            "backslash": "KEY_BACKSLASH", "semicolon": "KEY_SEMICOLON",
            "apostrophe": "KEY_APOSTROPHE", "comma": "KEY_COMMA",
            "period": "KEY_DOT", "slash": "KEY_SLASH", "grave": "KEY_GRAVE",
        }
        for name, uname in punct_map.items():
            code = getattr(uinput, uname, None)
            if code:
                _KEY_NAME_TO_CODE[name] = code
        mod_map = {
            "shift": "KEY_LEFTSHIFT", "ctrl": "KEY_LEFTCTRL",
            "alt": "KEY_LEFTALT", "super": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA",
        }
        for name, uname in mod_map.items():
            code = getattr(uinput, uname, None)
            if code:
                _KEY_NAME_TO_CODE[name] = code
    except ImportError:
        pass


def _get_key_code(name: str) -> int:
    _build_key_map()
    code = _KEY_NAME_TO_CODE.get(name)
    if code is None:
        code = _KEY_NAME_TO_CODE.get(name.lower())
    if code is None:
        raise ValueError(f"Unknown key name: {name!r}")
    return code


class UinputBackend:
    _instance: Optional["UinputBackend"] = None
    _device = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_device(self):
        if self._device is not None:
            return
        import uinput

        # ABS range must cover the FULL virtual desktop (all monitors),
        # not just the primary monitor. The kernel maps ABS_X/ABS_Y
        # proportionally across the total root geometry.
        sw, sh = _detect_screen_size()

        events = [
            uinput.BTN_LEFT, uinput.BTN_RIGHT, uinput.BTN_MIDDLE,
            uinput.ABS_X + (0, sw, 0, 0),
            uinput.ABS_Y + (0, sh, 0, 0),
            uinput.REL_WHEEL, uinput.REL_HWHEEL,
        ]
        _build_key_map()
        for code in _KEY_NAME_TO_CODE.values():
            if code not in events:
                events.append(code)
        self._device = uinput.Device(events, name="x11-mcp-virtual-input")
        time.sleep(0.1)

    def move(self, x: int, y: int) -> None:
        self._ensure_device()
        state = get_state()
        sx, sy = state.api_to_screen(x, y)
        import uinput as u
        self._device.emit(u.ABS_X, sx, syn=False)
        self._device.emit(u.ABS_Y, sy)

    def _read_cursor(self) -> tuple[int, int] | None:
        """Read actual cursor position. Returns None on failure."""
        try:
            r = subprocess.run(
                ["xdotool", "getmouselocation"],
                capture_output=True, text=True, timeout=1,
            )
            m = re.match(r"x:(\d+) y:(\d+)", r.stdout)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass
        return None

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        import uinput as u
        self._ensure_device()
        state = get_state()
        target_sx, target_sy = state.api_to_screen(x, y)

        # Move and verify cursor arrived. After focus grabs, the kernel
        # may swallow the first ABS move. Retry up to 3 times.
        for attempt in range(3):
            self.move(x, y)
            time.sleep(0.01)
            pos = self._read_cursor()
            if pos and abs(pos[0] - target_sx) <= 2 and abs(pos[1] - target_sy) <= 2:
                break
            time.sleep(0.02)
        btn = {"left": u.BTN_LEFT, "right": u.BTN_RIGHT, "middle": u.BTN_MIDDLE}[button]
        for _ in range(count):
            self._device.emit(btn, 1)
            time.sleep(0.01)
            self._device.emit(btn, 0)
            if count > 1:
                time.sleep(0.03)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left") -> None:
        import uinput as u
        self._ensure_device()
        btn = {"left": u.BTN_LEFT, "right": u.BTN_RIGHT, "middle": u.BTN_MIDDLE}[button]
        self.move(start_x, start_y)
        time.sleep(0.02)
        self._device.emit(btn, 1)
        time.sleep(0.05)
        self.move(end_x, end_y)
        time.sleep(0.05)
        self._device.emit(btn, 0)

    def scroll(self, x: int, y: int, direction: str = "down", amount: int = 3) -> None:
        import uinput as u
        self._ensure_device()
        self.move(x, y)
        time.sleep(0.01)
        axis_map = {
            "up": (u.REL_WHEEL, 1),
            "down": (u.REL_WHEEL, -1),
            "left": (u.REL_HWHEEL, -1),
            "right": (u.REL_HWHEEL, 1),
        }
        axis, direction_val = axis_map[direction]
        for _ in range(amount):
            self._device.emit(axis, direction_val)
            time.sleep(0.02)

    def type_text(self, text: str, delay_ms: int = 12) -> None:
        self._ensure_device()
        delay_s = delay_ms / 1000.0
        for char in text:
            events = char_to_key_events(char)
            for action, key_name in events:
                code = _get_key_code(key_name)
                if action == "key":
                    self._device.emit(code, 1)
                    time.sleep(0.005)
                    self._device.emit(code, 0)
                elif action == "hold":
                    self._device.emit(code, 1)
                elif action == "release":
                    self._device.emit(code, 0)
            time.sleep(delay_s)

    def key(self, combo: str, repeat: int = 1) -> None:
        self._ensure_device()
        modifiers, key_name = parse_key_combo(combo)
        for _ in range(repeat):
            held = []
            for mod in modifiers:
                code = _get_key_code(mod)
                self._device.emit(code, 1)
                held.append(code)
            time.sleep(0.005)
            key_code = _get_key_code(key_name)
            self._device.emit(key_code, 1)
            time.sleep(0.005)
            self._device.emit(key_code, 0)
            time.sleep(0.005)
            for code in reversed(held):
                self._device.emit(code, 0)
            time.sleep(0.02)

    def hold_key(self, key_name: str, duration: float) -> None:
        self._ensure_device()
        code = _get_key_code(key_name)
        self._device.emit(code, 1)
        time.sleep(duration)
        self._device.emit(code, 0)


class XdotoolBackend:
    """Input injection via xdotool (XTest synthetic events).

    Slower than uinput but works with CEF/Electron apps (Steam, Discord, VS Code)
    that ignore kernel-level input events.
    """
    _instance: Optional["XdotoolBackend"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _run(self, args: list[str]) -> None:
        subprocess.run(["xdotool"] + args, capture_output=True, timeout=5)

    def move(self, x: int, y: int) -> None:
        state = get_state()
        sx, sy = state.api_to_screen(x, y)
        self._run(["mousemove", "--sync", str(sx), str(sy)])

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        state = get_state()
        sx, sy = state.api_to_screen(x, y)
        btn_map = {"left": "1", "right": "3", "middle": "2"}
        btn = btn_map.get(button, "1")
        self._run(["mousemove", "--sync", str(sx), str(sy)])
        self._run(["click", "--repeat", str(count), btn])

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left") -> None:
        state = get_state()
        sx1, sy1 = state.api_to_screen(start_x, start_y)
        sx2, sy2 = state.api_to_screen(end_x, end_y)
        btn_map = {"left": "1", "right": "3", "middle": "2"}
        btn = btn_map.get(button, "1")
        self._run(["mousemove", "--sync", str(sx1), str(sy1)])
        self._run(["mousedown", btn])
        self._run(["mousemove", "--sync", str(sx2), str(sy2)])
        self._run(["mouseup", btn])

    def scroll(self, x: int, y: int, direction: str = "down", amount: int = 3) -> None:
        state = get_state()
        sx, sy = state.api_to_screen(x, y)
        # xdotool scroll: button 4=up, 5=down, 6=left, 7=right
        scroll_btn = {"up": "4", "down": "5", "left": "6", "right": "7"}
        btn = scroll_btn.get(direction, "5")
        self._run(["mousemove", "--sync", str(sx), str(sy)])
        self._run(["click", "--repeat", str(amount), btn])

    def type_text(self, text: str, delay_ms: int = 12) -> None:
        self._run(["type", "--delay", str(delay_ms), "--", text])

    def key(self, combo: str, repeat: int = 1) -> None:
        self._run(["key", "--repeat", str(repeat), combo])

    def hold_key(self, key_name: str, duration: float) -> None:
        self._run(["keydown", key_name])
        time.sleep(duration)
        self._run(["keyup", key_name])


_active_backend: str = "uinput"


def set_input_backend(backend: str) -> str:
    """Switch between 'uinput' and 'xdotool' input backends."""
    global _active_backend
    if backend not in ("uinput", "xdotool"):
        raise ValueError(f"Unknown backend: {backend!r}. Use 'uinput' or 'xdotool'.")
    _active_backend = backend
    return _active_backend


def get_input_backend() -> str:
    """Return the name of the active input backend."""
    return _active_backend


def get_input_device():
    """Return the active input backend instance."""
    if _active_backend == "xdotool":
        return XdotoolBackend()
    return UinputBackend()
