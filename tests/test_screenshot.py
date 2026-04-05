from io import BytesIO
from unittest.mock import patch, MagicMock

from PIL import Image

from x11_mcp.screenshot import (
    compute_target_size,
    encode_jpeg,
    image_hash,
    images_match,
    _parse_xrandr_monitors,
    _get_primary_monitor,
    _find_monitor_by_name,
    _get_target_monitor_geometry,
)


class TestResizeComputation:
    def test_no_resize_needed(self):
        w, h = compute_target_size(1280, 800, max_width=1280, max_height=800)
        assert (w, h) == (1280, 800)

    def test_downscale_preserves_aspect(self):
        w, h = compute_target_size(2560, 1440, max_width=1280, max_height=800)
        assert w == 1280
        assert h == 720

    def test_tall_image(self):
        w, h = compute_target_size(1080, 1920, max_width=1280, max_height=800)
        assert w == 450
        assert h == 800

    def test_small_image_not_upscaled(self):
        w, h = compute_target_size(800, 600, max_width=1280, max_height=800)
        assert (w, h) == (800, 600)


class TestJpegEncoding:
    def test_encode_returns_bytes(self):
        img = Image.new("RGB", (100, 100), color="red")
        data = encode_jpeg(img, quality=75)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_lower_quality_smaller(self):
        img = Image.new("RGB", (500, 500), color="blue")
        q75 = encode_jpeg(img, quality=75)
        q30 = encode_jpeg(img, quality=30)
        assert len(q30) < len(q75)


class TestImageHash:
    def test_same_image_same_hash(self):
        img = Image.new("RGB", (100, 100), color="green")
        assert image_hash(img) == image_hash(img)

    def test_different_gradient_images(self):
        """Images with different gradient patterns should have different hashes."""
        # Left-to-right increasing gradient (each pixel brighter than its right neighbour)
        img1 = Image.new("L", (100, 100))
        for x in range(100):
            for y in range(100):
                img1.putpixel((x, y), x * 2)
        img1 = img1.convert("RGB")
        # Right-to-left increasing gradient (reversed — each pixel darker than its right neighbour)
        img2 = Image.new("L", (100, 100))
        for x in range(100):
            for y in range(100):
                img2.putpixel((x, y), (99 - x) * 2)
        img2 = img2.convert("RGB")
        assert not images_match(image_hash(img1), image_hash(img2))

    def test_returns_int(self):
        img = Image.new("RGB", (100, 100), color="blue")
        assert isinstance(image_hash(img), int)

    def test_slightly_different_images_match(self):
        """Perceptual hash should tolerate minor pixel differences."""
        img1 = Image.new("RGB", (100, 100), color=(128, 128, 128))
        img2 = img1.copy()
        img2.putpixel((10, 10), (130, 128, 128))
        img2.putpixel((50, 50), (126, 128, 128))
        assert images_match(image_hash(img1), image_hash(img2))

    def test_very_different_images_dont_match(self):
        """Images with completely different structures should not match."""
        # Checkerboard pattern
        img1 = Image.new("L", (100, 100))
        for x in range(100):
            for y in range(100):
                img1.putpixel((x, y), 255 if (x + y) % 2 == 0 else 0)
        img1 = img1.convert("RGB")
        # Inverse checkerboard
        img2 = Image.new("L", (100, 100))
        for x in range(100):
            for y in range(100):
                img2.putpixel((x, y), 0 if (x + y) % 2 == 0 else 255)
        img2 = img2.convert("RGB")
        assert not images_match(image_hash(img1), image_hash(img2))


XRANDR_DUAL_MONITOR = """\
Screen 0: minimum 320 x 200, current 5120 x 1440, maximum 16384 x 16384
DP-2 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
HDMI-1 connected 2560x1440+2560+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
"""

XRANDR_SINGLE_MONITOR = """\
Screen 0: minimum 320 x 200, current 2560 x 1440, maximum 16384 x 16384
DP-2 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
"""

XRANDR_NO_PRIMARY = """\
Screen 0: minimum 320 x 200, current 5120 x 1440, maximum 16384 x 16384
DP-2 connected 2560x1440+0+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
HDMI-1 connected 2560x1440+2560+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
"""


def _mock_xrandr(output: str):
    """Return a patch that makes _parse_xrandr_monitors use the given xrandr output."""
    mock_result = MagicMock()
    mock_result.stdout = output
    return patch("subprocess.run", return_value=mock_result)


class TestParseXrandrMonitors:
    def test_dual_monitor(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            monitors = _parse_xrandr_monitors()
        assert len(monitors) == 2
        assert monitors[0]["name"] == "DP-2"
        assert monitors[0]["is_primary"] is True
        assert monitors[0]["x"] == 0
        assert monitors[0]["w"] == 2560
        assert monitors[1]["name"] == "HDMI-1"
        assert monitors[1]["is_primary"] is False
        assert monitors[1]["x"] == 2560

    def test_single_monitor(self):
        with _mock_xrandr(XRANDR_SINGLE_MONITOR):
            monitors = _parse_xrandr_monitors()
        assert len(monitors) == 1
        assert monitors[0]["is_primary"] is True

    def test_no_primary_flag(self):
        with _mock_xrandr(XRANDR_NO_PRIMARY):
            monitors = _parse_xrandr_monitors()
        assert len(monitors) == 2
        assert all(not m["is_primary"] for m in monitors)


class TestGetPrimaryMonitor:
    def test_returns_primary(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            monitors = _parse_xrandr_monitors()
        primary = _get_primary_monitor(monitors)
        assert primary["name"] == "DP-2"
        assert primary["is_primary"] is True

    def test_falls_back_to_first(self):
        with _mock_xrandr(XRANDR_NO_PRIMARY):
            monitors = _parse_xrandr_monitors()
        primary = _get_primary_monitor(monitors)
        assert primary["name"] == "DP-2"

    def test_empty_list(self):
        assert _get_primary_monitor([]) is None


class TestFindMonitorByName:
    def test_finds_existing(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            monitors = _parse_xrandr_monitors()
        found = _find_monitor_by_name("HDMI-1", monitors)
        assert found is not None
        assert found["x"] == 2560

    def test_returns_none_for_missing(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            monitors = _parse_xrandr_monitors()
        assert _find_monitor_by_name("VGA-1", monitors) is None


class TestGetTargetMonitorGeometry:
    def test_defaults_to_primary(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            x, y, w, h, name, warning = _get_target_monitor_geometry(5120, 1440)
        assert x == 0
        assert w == 2560
        assert name == "DP-2"
        assert warning is None

    def test_explicit_monitor(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            x, y, w, h, name, warning = _get_target_monitor_geometry(5120, 1440, monitor="HDMI-1")
        assert x == 2560
        assert name == "HDMI-1"
        assert warning is None

    def test_missing_monitor_warns_and_falls_back(self):
        with _mock_xrandr(XRANDR_DUAL_MONITOR):
            x, y, w, h, name, warning = _get_target_monitor_geometry(5120, 1440, monitor="VGA-1")
        assert name == "DP-2"  # fell back to primary
        assert warning is not None
        assert "VGA-1" in warning
        assert "not found" in warning

    def test_no_monitors_falls_back_to_full(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            x, y, w, h, name, warning = _get_target_monitor_geometry(5120, 1440)
        assert (x, y, w, h) == (0, 0, 5120, 1440)
        assert name == "unknown"
