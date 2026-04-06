from unittest.mock import MagicMock, patch

from x11_mcp.input import _detect_screen_size, char_to_key_events, parse_key_combo


class TestDetectScreenSize:
    def test_xrandr_parses_current_resolution(self):
        mock_result = MagicMock()
        mock_result.stdout = (
            "Screen 0: minimum 320 x 200, current 3840 x 2160, maximum 16384 x 16384\n"
            "DP-0 connected primary 3840x2160+0+0\n"
        )
        with patch("subprocess.run", return_value=mock_result):
            assert _detect_screen_size() == (3840, 2160)

    def test_falls_back_on_xrandr_failure(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            w, h = _detect_screen_size()
            # Should still return something valid (xlib or default)
            assert w > 0 and h > 0


class TestKeyParsing:
    def test_single_key(self):
        result = parse_key_combo("Return")
        assert result == ([], "Return")

    def test_ctrl_c(self):
        modifiers, key = parse_key_combo("ctrl+c")
        assert modifiers == ["ctrl"]
        assert key == "c"

    def test_ctrl_shift_t(self):
        modifiers, key = parse_key_combo("ctrl+shift+t")
        assert set(modifiers) == {"ctrl", "shift"}
        assert key == "t"

    def test_alt_tab(self):
        modifiers, key = parse_key_combo("alt+Tab")
        assert modifiers == ["alt"]
        assert key == "Tab"

    def test_single_letter(self):
        modifiers, key = parse_key_combo("a")
        assert modifiers == []
        assert key == "a"


class TestCharToKeyEvents:
    def test_lowercase(self):
        events = char_to_key_events("a")
        assert events == [("key", "a")]

    def test_uppercase(self):
        events = char_to_key_events("A")
        assert events == [("hold", "shift"), ("key", "a"), ("release", "shift")]

    def test_space(self):
        events = char_to_key_events(" ")
        assert events == [("key", "space")]

    def test_symbol_shift(self):
        events = char_to_key_events("!")
        assert events[0] == ("hold", "shift")
        assert events[-1] == ("release", "shift")

    def test_newline(self):
        events = char_to_key_events("\n")
        assert events == [("key", "Return")]

    def test_tab(self):
        events = char_to_key_events("\t")
        assert events == [("key", "Tab")]
