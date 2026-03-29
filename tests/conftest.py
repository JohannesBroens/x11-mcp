import os
import pytest


def has_x11_display():
    """Check if an X11 display is available."""
    display = os.environ.get("DISPLAY")
    if not display:
        return False
    try:
        from Xlib import display as xdisplay
        d = xdisplay.Display()
        d.close()
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if not has_x11_display():
        skip_x11 = pytest.mark.skip(reason="No X11 display available")
        for item in items:
            if "x11" in item.keywords:
                item.add_marker(skip_x11)
