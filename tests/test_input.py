from unittest.mock import patch, MagicMock, call

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


class TestResolveWindow:
    def test_title_match(self):
        windows = [
            {"id": 1, "title": "YouTube Music", "class": "chromium.Chromium"},
            {"id": 2, "title": "Steam", "class": "steamwebhelper.steam"},
        ]
        with patch("x11_mcp.server._list_windows", return_value=windows):
            from x11_mcp.server import _resolve_window
            assert _resolve_window(None, "YouTube") == 1

    def test_class_match_when_title_fails(self):
        windows = [
            {"id": 1, "title": "main Steam", "class": "steamwebhelper.steam"},
            {"id": 2, "title": "Some Helper", "class": "steamwebhelper.steam"},
        ]
        with patch("x11_mcp.server._list_windows", return_value=windows):
            from x11_mcp.server import _resolve_window
            # "steamwebhelper" doesn't match any title but matches class
            assert _resolve_window(None, "steamwebhelper") in (1, 2)

    def test_title_takes_priority_over_class(self):
        windows = [
            {"id": 1, "title": "Some App", "class": "steam.Steam"},
            {"id": 2, "title": "Steam Window", "class": "other.Other"},
        ]
        with patch("x11_mcp.server._list_windows", return_value=windows):
            from x11_mcp.server import _resolve_window
            # "Steam" matches window 2's title, not window 1's class
            assert _resolve_window(None, "Steam") == 2

    def test_returns_none_when_nothing_matches(self):
        windows = [{"id": 1, "title": "Firefox", "class": "firefox.Firefox"}]
        with patch("x11_mcp.server._list_windows", return_value=windows):
            from x11_mcp.server import _resolve_window
            assert _resolve_window(None, "Steam") is None

    def test_window_id_takes_priority(self):
        from x11_mcp.server import _resolve_window
        assert _resolve_window(42, "anything") == 42


class TestXdotoolBackend:
    def test_click_constructs_correct_command(self):
        from x11_mcp.input import XdotoolBackend
        backend = XdotoolBackend()

        # Mock scaling to return screen coords directly
        mock_state = MagicMock()
        mock_state.api_to_screen.return_value = (500, 300)

        with patch("x11_mcp.input.get_state", return_value=mock_state):
            with patch("subprocess.run") as mock_run:
                backend.click(250, 150, button="left", count=1)

                calls = mock_run.call_args_list
                # Should have mousemove then click
                assert any("mousemove" in str(c) for c in calls)
                assert any("click" in str(c) for c in calls)
                # Check button mapping: left = 1
                click_call = [c for c in calls if "click" in str(c.args[0])][0]
                assert "1" in click_call.args[0]

    def test_right_click_uses_button_3(self):
        from x11_mcp.input import XdotoolBackend
        backend = XdotoolBackend()

        mock_state = MagicMock()
        mock_state.api_to_screen.return_value = (100, 200)

        with patch("x11_mcp.input.get_state", return_value=mock_state):
            with patch("subprocess.run") as mock_run:
                backend.click(50, 100, button="right", count=1)
                click_call = [c for c in mock_run.call_args_list if "click" in str(c.args[0])][0]
                assert "3" in click_call.args[0]

    def test_type_text_uses_xdotool_type(self):
        from x11_mcp.input import XdotoolBackend
        backend = XdotoolBackend()

        with patch("subprocess.run") as mock_run:
            backend.type_text("hello", delay_ms=20)
            mock_run.assert_called_once()
            args = mock_run.call_args.args[0]
            assert args[0] == "xdotool"
            assert "type" in args
            assert "hello" in args

    def test_key_combo(self):
        from x11_mcp.input import XdotoolBackend
        backend = XdotoolBackend()

        with patch("subprocess.run") as mock_run:
            backend.key("ctrl+c", repeat=1)
            args = mock_run.call_args.args[0]
            assert "key" in args
            assert "ctrl+c" in args

    def test_scroll_down(self):
        from x11_mcp.input import XdotoolBackend
        backend = XdotoolBackend()

        mock_state = MagicMock()
        mock_state.api_to_screen.return_value = (640, 360)

        with patch("x11_mcp.input.get_state", return_value=mock_state):
            with patch("subprocess.run") as mock_run:
                backend.scroll(320, 180, direction="down", amount=3)
                click_call = [c for c in mock_run.call_args_list if "click" in str(c.args[0])][0]
                assert "5" in click_call.args[0]  # button 5 = scroll down


class TestBackendSwitching:
    def test_default_is_uinput(self):
        from x11_mcp.input import get_input_backend
        # Reset to default
        from x11_mcp import input as inp
        inp._active_backend = "uinput"
        assert get_input_backend() == "uinput"

    def test_switch_to_xdotool(self):
        from x11_mcp.input import set_input_backend, get_input_backend, get_input_device, XdotoolBackend
        set_input_backend("xdotool")
        assert get_input_backend() == "xdotool"
        assert isinstance(get_input_device(), XdotoolBackend)
        # Reset
        set_input_backend("uinput")

    def test_invalid_backend_raises(self):
        from x11_mcp.input import set_input_backend
        import pytest
        with pytest.raises(ValueError):
            set_input_backend("invalid")
        # Reset
        set_input_backend("uinput")
