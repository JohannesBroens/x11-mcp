from x11_mcp.scaling import ScalingState


class TestScalingMath:
    def test_identity_scaling(self):
        """When API size equals screen size, coordinates pass through."""
        s = ScalingState()
        s.update(screen_width=1280, screen_height=800, api_width=1280, api_height=800)
        assert s.api_to_screen(640, 400) == (640, 400)
        assert s.screen_to_api(640, 400) == (640, 400)

    def test_2x_downscale(self):
        """2560x1440 screen scaled to 1280x720 API space."""
        s = ScalingState()
        s.update(screen_width=2560, screen_height=1440, api_width=1280, api_height=720)
        assert s.api_to_screen(640, 360) == (1280, 720)
        assert s.screen_to_api(1280, 720) == (640, 360)

    def test_monitor_offset(self):
        """Second monitor at x=2560 offsets all coordinates."""
        s = ScalingState()
        # Set root size explicitly so test doesn't depend on live display
        s._root_size = (5120, 1440)
        s.update(
            screen_width=2560, screen_height=1440,
            api_width=1280, api_height=720,
            monitor_offset_x=2560, monitor_offset_y=0,
        )
        assert s.api_to_screen(0, 0) == (2560, 0)
        sx, sy = s.api_to_screen(1280, 720)
        # int(1280/0.5 + 0.5) + 2560 = 5121, clamped to 5119 (root_w - 1)
        assert sx == 5119
        assert sy == 1439

    def test_clamping(self):
        """Coordinates are clamped to virtual desktop bounds."""
        s = ScalingState()
        s.update(screen_width=2560, screen_height=1440, api_width=1280, api_height=720)
        sx, sy = s.api_to_screen(-100, -50)
        assert sx >= 0 and sy >= 0
        # Clamped to full virtual desktop (root), not just primary monitor
        sx, sy = s.api_to_screen(9999, 9999)
        assert sx >= 0 and sy >= 0  # just verify no crash; exact value depends on root size

    def test_roundtrip(self):
        """screen_to_api(api_to_screen(x, y)) ≈ (x, y) within 1px."""
        s = ScalingState()
        s.update(screen_width=2560, screen_height=1440, api_width=1280, api_height=800)
        for x, y in [(0, 0), (640, 400), (1279, 799), (100, 500)]:
            sx, sy = s.api_to_screen(x, y)
            rx, ry = s.screen_to_api(sx, sy)
            assert abs(rx - x) <= 1 and abs(ry - y) <= 1, f"Roundtrip failed for ({x},{y})"


class TestZoomScaling:
    def test_zoom_coordinates(self):
        """Zoom region maps API coords back to screen with region offset."""
        s = ScalingState()
        s.update(screen_width=2560, screen_height=1440, api_width=1280, api_height=800)
        s.set_zoom(region_x=500, region_y=300, region_w=512, region_h=512)
        assert s.api_to_screen(0, 0) == (500, 300)
        assert s.api_to_screen(512, 512) == (1012, 812)

    def test_clear_zoom(self):
        """After clearing zoom, normal scaling resumes."""
        s = ScalingState()
        s.update(screen_width=2560, screen_height=1440, api_width=1280, api_height=800)
        s.set_zoom(region_x=500, region_y=300, region_w=512, region_h=512)
        s.clear_zoom()
        sx, sy = s.api_to_screen(0, 0)
        assert sx == 0 and sy == 0
