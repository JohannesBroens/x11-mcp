"""Integration tests — require a running X11 display.

Run with: pytest tests/test_integration.py -v -m x11
Skip with: pytest -m 'not x11'
"""

import json
import pytest

pytestmark = pytest.mark.x11


class TestScreenshotIntegration:
    def test_fullscreen_capture(self):
        from x11_mcp.screenshot import take_screenshot

        b64, meta = take_screenshot(mode="fullscreen")
        assert len(b64) > 0
        assert meta["capture_mode"] == "fullscreen"
        assert meta["api_width"] > 0
        assert meta["api_height"] > 0
        assert meta["native_width"] > 0
        assert meta["native_height"] > 0

    def test_no_op_detection(self):
        from x11_mcp.screenshot import take_screenshot

        _, meta1 = take_screenshot(mode="fullscreen")
        _, meta2 = take_screenshot(mode="fullscreen")
        assert meta2["unchanged"] is True

    def test_zoom_capture(self):
        from x11_mcp.screenshot import take_screenshot

        take_screenshot(mode="fullscreen")
        b64, meta = take_screenshot(mode="zoom", zoom_center=(640, 400), zoom_size=256)
        assert meta["capture_mode"] == "zoom"
        assert meta["native_resolution"] is True


class TestScalingIntegration:
    def test_scaling_state_updated_after_screenshot(self):
        from x11_mcp.screenshot import take_screenshot
        from x11_mcp.scaling import get_state

        take_screenshot(mode="fullscreen")
        state = get_state()
        assert state.screen_size[0] > 0
        assert state.api_size[0] > 0
        assert state.api_size[0] <= 1280
        assert state.api_size[1] <= 800


class TestWindowIntegration:
    def test_list_windows(self):
        from x11_mcp.window import list_windows

        windows = list_windows()
        assert isinstance(windows, list)

    def test_get_monitors(self):
        from x11_mcp.window import get_monitor_geometries

        monitors = get_monitor_geometries()
        assert len(monitors) >= 1
        assert monitors[0]["width"] > 0


class TestXshmIntegration:
    def test_xshm_capture_produces_valid_image(self):
        """XShm capture returns a valid image with correct dimensions."""
        from x11_mcp.screenshot import take_screenshot

        b64, meta = take_screenshot(mode="fullscreen")
        assert len(b64) > 0
        assert meta["api_width"] > 0
        # Should report capture method
        assert "capture_method" in meta
        assert meta["capture_method"] in ("xshm", "get_image")

    def test_capture_method_reported_in_metadata(self):
        """Metadata includes which capture path was used."""
        from x11_mcp.screenshot import take_screenshot

        _, meta = take_screenshot(mode="fullscreen")
        assert "capture_method" in meta


class TestCalibration:
    def test_calibration_runs(self):
        from x11_mcp.screenshot import take_screenshot
        from x11_mcp.server import calibrate

        take_screenshot(mode="fullscreen")
        result = calibrate()
        assert "Calibration:" in result
        assert "center:" in result
