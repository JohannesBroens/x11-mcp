"""Coordinate scaling between screen space and API space.

Singleton state that all tools share. Updated by screenshot module,
consumed by input/window/accessibility modules.
"""

from __future__ import annotations


class ScalingState:
    """Bidirectional coordinate mapping between screen and API space."""

    def __init__(self):
        self._scale_x: float = 1.0
        self._scale_y: float = 1.0
        self._monitor_offset_x: int = 0
        self._monitor_offset_y: int = 0
        self._screen_width: int = 0
        self._screen_height: int = 0
        self._api_width: int = 0
        self._api_height: int = 0
        self._zoom_active: bool = False
        self._zoom_region_x: int = 0
        self._zoom_region_y: int = 0
        self._zoom_region_w: int = 0
        self._zoom_region_h: int = 0

    def update(
        self,
        screen_width: int,
        screen_height: int,
        api_width: int,
        api_height: int,
        monitor_offset_x: int = 0,
        monitor_offset_y: int = 0,
    ) -> None:
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._api_width = api_width
        self._api_height = api_height
        self._monitor_offset_x = monitor_offset_x
        self._monitor_offset_y = monitor_offset_y
        self._scale_x = api_width / screen_width if screen_width else 1.0
        self._scale_y = api_height / screen_height if screen_height else 1.0
        self._zoom_active = False

    def set_zoom(self, region_x: int, region_y: int, region_w: int, region_h: int) -> None:
        self._zoom_active = True
        self._zoom_region_x = region_x
        self._zoom_region_y = region_y
        self._zoom_region_w = region_w
        self._zoom_region_h = region_h

    def clear_zoom(self) -> None:
        self._zoom_active = False

    def api_to_screen(self, x: int, y: int) -> tuple[int, int]:
        if self._zoom_active:
            sx = x + self._zoom_region_x
            sy = y + self._zoom_region_y
        else:
            sx = int(x / self._scale_x) + self._monitor_offset_x
            sy = int(y / self._scale_y) + self._monitor_offset_y
        total_w = self._screen_width + self._monitor_offset_x
        total_h = self._screen_height + self._monitor_offset_y
        sx = max(0, min(sx, total_w))
        sy = max(0, min(sy, total_h))
        return (sx, sy)

    def screen_to_api(self, x: int, y: int) -> tuple[int, int]:
        if self._zoom_active:
            ax = x - self._zoom_region_x
            ay = y - self._zoom_region_y
        else:
            ax = int((x - self._monitor_offset_x) * self._scale_x)
            ay = int((y - self._monitor_offset_y) * self._scale_y)
        return (ax, ay)

    @property
    def is_zoom_active(self) -> bool:
        return self._zoom_active

    @property
    def screen_size(self) -> tuple[int, int]:
        return (self._screen_width, self._screen_height)

    @property
    def api_size(self) -> tuple[int, int]:
        return (self._api_width, self._api_height)

    @property
    def monitor_offset(self) -> tuple[int, int]:
        return (self._monitor_offset_x, self._monitor_offset_y)


_state = ScalingState()


def get_state() -> ScalingState:
    return _state
