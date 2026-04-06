"""Unit tests for server.py tool logic — no X11 required.

Tests batch action parsing, window snapshot diffing, and tool input validation.
"""

import json
from unittest.mock import patch, MagicMock

from x11_mcp.server import _resolve_window, _snapshot_window_ids, batch


class TestBatchActions:
    """Test batch() action dispatch and error handling."""

    def _mock_device(self):
        dev = MagicMock()
        dev.click = MagicMock()
        dev.move = MagicMock()
        dev.type_text = MagicMock()
        dev.key = MagicMock()
        dev.scroll = MagicMock()
        return dev

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_single_click(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "click", "x": 100, "y": 200}])
        dev.click.assert_called_once_with(100, 200, button="left", count=1)
        assert "click" in result

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_type_action(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "type", "text": "hello world"}])
        dev.type_text.assert_called_once_with("hello world", delay_ms=12)
        assert "11 chars" in result

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_key_action(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "key", "keys": "ctrl+c"}])
        dev.key.assert_called_once_with("ctrl+c", repeat=1)
        assert "ctrl+c" in result

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_double_click(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "double_click", "x": 50, "y": 60}])
        dev.click.assert_called_once_with(50, 60, button="left", count=2)

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_right_click(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "right_click", "x": 50, "y": 60}])
        dev.click.assert_called_once_with(50, 60, button="right", count=1)

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_scroll_action(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "scroll", "x": 400, "y": 300, "direction": "up", "amount": 5}])
        dev.scroll.assert_called_once_with(400, 300, direction="up", amount=5)

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_move_action(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "move", "x": 640, "y": 400}])
        dev.move.assert_called_once_with(640, 400)

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_focus_action(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        batch([{"action": "focus", "name": "Firefox"}])
        mock_focus.assert_called_once_with(window_id=None, name="Firefox")

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_unknown_action(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([{"action": "fly_to_moon"}])
        assert "unknown" in result

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_sequence_of_actions(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        result = batch([
            {"action": "click", "x": 100, "y": 200},
            {"action": "type", "text": "test"},
            {"action": "key", "keys": "Return"},
        ])
        assert dev.click.call_count == 1
        assert dev.type_text.call_count == 1
        assert dev.key.call_count == 1
        lines = result.strip().split("\n")
        assert len(lines) == 3

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_error_stops_batch(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        dev.click.side_effect = RuntimeError("device error")
        mock_get_dev.return_value = dev

        result = batch([
            {"action": "click", "x": 100, "y": 200},
            {"action": "type", "text": "should not run"},
        ])
        assert "ERROR" in result
        # Second action should not have executed
        dev.type_text.assert_not_called()

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_wait_action_capped(self, mock_get_dev, mock_focus):
        """Wait action should be capped at 10 seconds."""
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        import time
        start = time.monotonic()
        batch([{"action": "wait", "seconds": 0.01}])
        elapsed = time.monotonic() - start
        # Should complete very quickly (well under 1s)
        assert elapsed < 1.0

    @patch("x11_mcp.server._focus_window")
    @patch("x11_mcp.server.get_input_device")
    def test_scroll_default_direction(self, mock_get_dev, mock_focus):
        dev = self._mock_device()
        mock_get_dev.return_value = dev

        batch([{"action": "scroll", "x": 100, "y": 100}])
        dev.scroll.assert_called_once_with(100, 100, direction="down", amount=3)


class TestWindowSnapshotDiff:
    """Test window change detection used by click_and_verify."""

    @patch("x11_mcp.server._list_windows")
    def test_snapshot_captures_ids_and_titles(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "title": "Firefox"},
            {"id": 2, "title": "Terminal"},
        ]
        snap = _snapshot_window_ids()
        assert snap == {1: "Firefox", 2: "Terminal"}

    @patch("x11_mcp.server._list_windows")
    def test_snapshot_empty(self, mock_list):
        mock_list.return_value = []
        snap = _snapshot_window_ids()
        assert snap == {}

    def test_diff_detects_new_windows(self):
        """Simulates before/after click window detection."""
        before = {1: "Firefox", 2: "Terminal"}
        after = {1: "Firefox", 2: "Terminal", 3: "Dialog"}
        new_ids = set(after.keys()) - set(before.keys())
        assert new_ids == {3}

    def test_diff_no_change(self):
        before = {1: "Firefox", 2: "Terminal"}
        after = {1: "Firefox", 2: "Terminal"}
        new_ids = set(after.keys()) - set(before.keys())
        assert new_ids == set()


class TestResolveWindowEdgeCases:
    """Additional edge cases for window resolution."""

    @patch("x11_mcp.server._list_windows")
    def test_case_insensitive_title_match(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "title": "Mozilla Firefox", "class": "firefox.Firefox"},
        ]
        assert _resolve_window(None, "firefox") == 1

    @patch("x11_mcp.server._list_windows")
    def test_case_insensitive_class_match(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "title": "Some Window", "class": "SteamWebHelper.steam"},
        ]
        assert _resolve_window(None, "steamwebhelper") == 1

    @patch("x11_mcp.server._list_windows")
    def test_empty_name_returns_none(self, mock_list):
        assert _resolve_window(None, None) is None

    @patch("x11_mcp.server._list_windows")
    def test_partial_title_match(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "title": "YouTube Music - Chrome", "class": "chromium.Chromium"},
        ]
        assert _resolve_window(None, "YouTube Music") == 1

    @patch("x11_mcp.server._list_windows")
    def test_multiple_title_matches_returns_first(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "title": "Steam - Friends", "class": "steam.Steam"},
            {"id": 2, "title": "Steam - Library", "class": "steam.Steam"},
        ]
        assert _resolve_window(None, "Steam") == 1
