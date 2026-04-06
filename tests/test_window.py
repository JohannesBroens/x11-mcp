"""Unit tests for window.py — wmctrl output parsing and logic, no X11 required.

Note on wmctrl format: `wmctrl -l -G -x` outputs:
  WIN_ID DESKTOP X Y W H CLASS HOSTNAME TITLE...
The parser uses line.split(None, 9) which means:
  - parts[0..6] = WIN_ID through CLASS
  - parts[7] = HOSTNAME
  - parts[8] = first word of TITLE (lost due to split)
  - parts[9] = remainder of TITLE
This means single-word titles produce only 9 parts and are skipped (len < 10).
Multi-word titles lose their first word. This matches production behavior.
"""

from unittest.mock import patch, MagicMock

from x11_mcp.window import list_windows


# Real wmctrl -l -G -x format: ID DESKTOP X Y W H CLASS HOST TITLE...
# Titles must be 2+ words to parse (parts[9] captures from the 2nd word onward)
WMCTRL_DUAL_MONITOR = """\
0x03200003  0 0    0    2560 1440 navigator.Firefox  myhost Mozilla Firefox
0x04600002  0 2560 0    2560 1440 Alacritty.Alacritty  myhost Alacritty Terminal
0x05a00001  0 100  200  1280 800  steamwebhelper.steam  myhost Steam Client
0x06000003  0 0    50   800  600  code.Code  myhost Visual Studio Code
"""

WMCTRL_MINIMAL = """\
0x01000001  0 0    0    1920 1080 navigator.Firefox  myhost Mozilla Firefox
"""

WMCTRL_EMPTY = ""

WMCTRL_MALFORMED = """\
0x01 garbage line
not even close
0x02000001  0 100  200  1280 800  app.App  myhost Good Window
"""


class TestWmctrlParsing:
    """Test list_windows() parsing of wmctrl -l -G -x output."""

    @patch("subprocess.run")
    def test_parses_dual_monitor_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        assert len(windows) == 4
        # First window — id, geometry, class
        assert windows[0]["id"] == 0x03200003
        assert windows[0]["class"] == "navigator.Firefox"
        assert windows[0]["x"] == 0
        assert windows[0]["y"] == 0
        assert windows[0]["width"] == 2560
        assert windows[0]["height"] == 1440

    @patch("subprocess.run")
    def test_title_extraction(self, mock_run):
        """Parser uses parts[9] — the remainder after 9 splits. First word of title is lost."""
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        titles = [w["title"] for w in windows]
        # "Mozilla Firefox" → parts[9] = "Firefox"
        assert "Firefox" in titles
        # "Visual Studio Code" → parts[9] = "Studio Code"
        assert "Studio Code" in titles

    @patch("subprocess.run")
    def test_second_monitor_window_position(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        terminal = [w for w in windows if "Terminal" in w["title"]][0]
        assert terminal["x"] == 2560  # on second monitor
        assert terminal["class"] == "Alacritty.Alacritty"

    @patch("subprocess.run")
    def test_electron_app_class(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        steam = [w for w in windows if "steamwebhelper" in w["class"]][0]
        assert steam["width"] == 1280
        assert steam["height"] == 800

    @patch("subprocess.run")
    def test_minimal_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_MINIMAL)
        windows = list_windows()
        assert len(windows) == 1
        assert windows[0]["width"] == 1920

    @patch("subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_EMPTY)
        windows = list_windows()
        assert windows == []

    @patch("subprocess.run")
    def test_malformed_lines_skipped(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_MALFORMED)
        windows = list_windows()
        assert len(windows) == 1
        assert windows[0]["title"] == "Window"

    @patch("subprocess.run")
    def test_id_hex_field(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_MINIMAL)
        windows = list_windows()
        assert windows[0]["id_hex"] == "0x01000001"

    @patch("subprocess.run", side_effect=FileNotFoundError)
    @patch("x11_mcp.window._list_windows_xlib", return_value=[])
    def test_wmctrl_missing_falls_back_to_xlib(self, mock_xlib, mock_run):
        windows = list_windows()
        mock_xlib.assert_called_once()
        assert windows == []

    @patch("subprocess.run")
    def test_single_word_titles_skipped(self, mock_run):
        """Lines where the title is a single word produce only 9 parts and are skipped."""
        # "myhost Firefox" → split gives parts[7]="myhost", parts[8]="Firefox", no parts[9]
        mock_run.return_value = MagicMock(
            stdout="0x01000001  0 0 0 1920 1080 navigator.Firefox  myhost Firefox\n"
        )
        windows = list_windows()
        assert len(windows) == 0  # skipped because len(parts) < 10


class TestWindowSearchPatterns:
    """Verify the kind of window matching patterns used in production."""

    @patch("subprocess.run")
    def test_find_by_title_substring(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        matches = [w for w in windows if "firefox" in w["title"].lower()]
        assert len(matches) == 1

    @patch("subprocess.run")
    def test_find_by_class_substring(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        matches = [w for w in windows if "steamwebhelper" in w["class"].lower()]
        assert len(matches) == 1

    @patch("subprocess.run")
    def test_find_vscode_by_class(self, mock_run):
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        matches = [w for w in windows if "code" in w["class"].lower()]
        assert len(matches) == 1

    @patch("subprocess.run")
    def test_class_based_search_essential_for_electron(self, mock_run):
        """Electron apps often have generic titles; class-based search is critical."""
        mock_run.return_value = MagicMock(stdout=WMCTRL_DUAL_MONITOR)
        windows = list_windows()
        # Can find Steam via class even if title doesn't match well
        class_matches = [w for w in windows if "steam" in w["class"].lower()]
        assert len(class_matches) == 1
