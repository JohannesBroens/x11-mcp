import hashlib
from io import BytesIO

from PIL import Image

from x11_mcp.screenshot import (
    compute_target_size,
    encode_jpeg,
    image_hash,
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

    def test_different_image_different_hash(self):
        img1 = Image.new("RGB", (100, 100), color="green")
        img2 = Image.new("RGB", (100, 100), color="red")
        assert image_hash(img1) != image_hash(img2)
