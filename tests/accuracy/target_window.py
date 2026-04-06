"""X11 target window for click accuracy testing.

Creates a window with colored dots at known positions.
Listens for ButtonPress events and reports where clicks actually landed.
Runs as a subprocess — the test runner spawns it, clicks the dots,
and reads results from stdout.

Usage:
    python -m tests.accuracy.target_window [--scenario SCENARIO] [--x X] [--y Y] [--w W] [--h H]

Scenarios:
    grid      - 3x3 grid of large dots (default)
    edges     - dots at edges and corners
    small     - tiny 4px dots requiring zoom to hit
    dense     - many dots close together
    diagonal  - dots along the diagonal
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field

from Xlib import display as xdisplay, X, Xatom
from Xlib.protocol import event


@dataclass
class Target:
    """A clickable dot target."""
    id: int
    x: int  # center x within window
    y: int  # center y within window
    radius: int
    color_name: str
    hit: bool = False
    click_x: int = 0
    click_y: int = 0
    error_px: float = 0.0


@dataclass
class TargetWindow:
    """An X11 window with clickable dot targets."""
    win_x: int
    win_y: int
    win_w: int
    win_h: int
    targets: list[Target] = field(default_factory=list)
    title: str = "x11-mcp-accuracy-test"

    _display = None
    _window = None
    _gc = None
    _running: bool = False

    def _alloc_color(self, name: str) -> int:
        """Allocate a named color, returning pixel value."""
        colormap = self._display.screen().default_colormap
        try:
            color = colormap.alloc_named_color(name)
            return color.pixel
        except Exception:
            # Fallback to basic colors
            if "red" in name:
                return 0xFF0000
            elif "green" in name:
                return 0x00FF00
            elif "blue" in name:
                return 0x0000FF
            elif "yellow" in name:
                return 0xFFFF00
            elif "cyan" in name:
                return 0x00FFFF
            elif "magenta" in name:
                return 0xFF00FF
            elif "white" in name:
                return 0xFFFFFF
            return 0xFF0000

    def create(self) -> None:
        """Create the X11 window and draw targets."""
        self._display = xdisplay.Display()
        screen = self._display.screen()

        self._window = screen.root.create_window(
            self.win_x, self.win_y, self.win_w, self.win_h, 0,
            screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=0x1A1A2E,  # dark background
            border_pixel=0xFFFFFF,
            event_mask=(
                X.ExposureMask | X.ButtonPressMask |
                X.ButtonReleaseMask | X.StructureNotifyMask
            ),
            override_redirect=False,
        )

        # Set window title
        self._window.set_wm_name(self.title)
        self._window.set_wm_class("accuracy-test", "x11-mcp-accuracy-test")

        # Create GC for drawing
        self._gc = self._window.create_gc(
            foreground=0xFF0000,
            background=0x1A1A2E,
        )

        self._window.map()
        self._display.sync()

        # Wait for window manager to position the window
        time.sleep(0.5)

        # Query the ACTUAL position (WM may have moved it due to decorations/snapping)
        try:
            import subprocess
            result = subprocess.run(
                ["xdotool", "search", "--name", self.title],
                capture_output=True, text=True, timeout=5,
            )
            for wid in result.stdout.strip().split():
                r = subprocess.run(
                    ["xdotool", "getwindowgeometry", wid],
                    capture_output=True, text=True, timeout=5,
                )
                import re
                m = re.search(r"Position: (\d+),(\d+)", r.stdout)
                if m:
                    self.win_x = int(m.group(1))
                    self.win_y = int(m.group(2))
                    break
        except Exception:
            pass  # keep requested position as fallback

        self._display.sync()

    def draw_targets(self) -> None:
        """Draw all target dots on the window."""
        for t in self.targets:
            pixel = self._alloc_color(t.color_name)
            self._gc.change(foreground=pixel)

            # Filled circle
            self._window.fill_arc(
                self._gc,
                t.x - t.radius, t.y - t.radius,
                t.radius * 2, t.radius * 2,
                0, 360 * 64,
            )

            # White outline for visibility
            self._gc.change(foreground=0xFFFFFF)
            self._window.arc(
                self._gc,
                t.x - t.radius, t.y - t.radius,
                t.radius * 2, t.radius * 2,
                0, 360 * 64,
            )

        # Draw crosshair at center of each target for precision reference
        self._gc.change(foreground=0xFFFFFF)
        for t in self.targets:
            # tiny 1px cross
            self._window.line(self._gc, t.x - 2, t.y, t.x + 2, t.y)
            self._window.line(self._gc, t.x, t.y - 2, t.x, t.y + 2)

        self._display.sync()

    def register_click(self, win_x: int, win_y: int) -> Target | None:
        """Check if a click hit any target. Returns the target if hit."""
        for t in self.targets:
            dist = ((win_x - t.x) ** 2 + (win_y - t.y) ** 2) ** 0.5
            if dist <= t.radius + 3:  # small tolerance
                t.hit = True
                t.click_x = win_x
                t.click_y = win_y
                t.error_px = dist
                return t
        return None

    def run_event_loop(self, timeout: float = 30.0) -> None:
        """Run X11 event loop, reporting clicks to stdout as JSON."""
        self._running = True
        start = time.monotonic()

        # Report target positions
        target_info = []
        for t in self.targets:
            target_info.append({
                "id": t.id,
                "win_x": t.x, "win_y": t.y,
                "screen_x": self.win_x + t.x,
                "screen_y": self.win_y + t.y,
                "radius": t.radius,
                "color": t.color_name,
            })
        print(json.dumps({"type": "targets", "targets": target_info}), flush=True)

        while self._running and (time.monotonic() - start) < timeout:
            # Check for events with timeout
            if self._display.pending_events():
                ev = self._display.next_event()
                if ev.type == X.Expose:
                    self.draw_targets()
                elif ev.type == X.ButtonPress:
                    hit = self.register_click(ev.event_x, ev.event_y)
                    result = {
                        "type": "click",
                        "win_x": ev.event_x,
                        "win_y": ev.event_y,
                        "screen_x": self.win_x + ev.event_x,
                        "screen_y": self.win_y + ev.event_y,
                        "button": ev.detail,
                    }
                    if hit:
                        result["hit_target"] = hit.id
                        result["error_px"] = round(hit.error_px, 1)
                    else:
                        result["hit_target"] = None
                        result["error_px"] = None
                    print(json.dumps(result), flush=True)
            else:
                time.sleep(0.01)

        # Final report
        results = []
        for t in self.targets:
            results.append({
                "id": t.id,
                "x": t.x, "y": t.y,
                "radius": t.radius,
                "hit": t.hit,
                "error_px": round(t.error_px, 1) if t.hit else None,
                "click_x": t.click_x if t.hit else None,
                "click_y": t.click_y if t.hit else None,
            })
        print(json.dumps({"type": "summary", "results": results}), flush=True)

    def destroy(self) -> None:
        """Clean up."""
        self._running = False
        if self._window:
            self._window.destroy()
        if self._display:
            self._display.sync()
            self._display.close()


# --- Scenario definitions ---

def _grid_targets(w: int, h: int, radius: int = 15) -> list[Target]:
    """3x3 grid of large dots."""
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta", "red", "green", "blue"]
    targets = []
    for row in range(3):
        for col in range(3):
            x = int(w * (col + 1) / 4)
            y = int(h * (row + 1) / 4)
            idx = row * 3 + col
            targets.append(Target(
                id=idx, x=x, y=y, radius=radius,
                color_name=colors[idx],
            ))
    return targets


def _edge_targets(w: int, h: int, radius: int = 12) -> list[Target]:
    """Dots at edges and corners — hardest for coordinate mapping."""
    margin = 20
    return [
        Target(0, margin, margin, radius, "red"),                    # top-left
        Target(1, w // 2, margin, radius, "green"),                  # top-center
        Target(2, w - margin, margin, radius, "blue"),               # top-right
        Target(3, margin, h // 2, radius, "yellow"),                 # mid-left
        Target(4, w - margin, h // 2, radius, "cyan"),               # mid-right
        Target(5, margin, h - margin, radius, "magenta"),            # bottom-left
        Target(6, w // 2, h - margin, radius, "red"),                # bottom-center
        Target(7, w - margin, h - margin, radius, "green"),          # bottom-right
    ]


def _small_targets(w: int, h: int) -> list[Target]:
    """Tiny 4px dots — requires zoom to hit accurately."""
    return [
        Target(0, w // 4, h // 4, 4, "red"),
        Target(1, 3 * w // 4, h // 4, 4, "green"),
        Target(2, w // 2, h // 2, 4, "blue"),
        Target(3, w // 4, 3 * h // 4, 4, "yellow"),
        Target(4, 3 * w // 4, 3 * h // 4, 4, "cyan"),
    ]


def _dense_targets(w: int, h: int, radius: int = 8) -> list[Target]:
    """Many dots close together — tests precision at scale."""
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta"]
    targets = []
    idx = 0
    for row in range(4):
        for col in range(5):
            x = int(w * (col + 1) / 6)
            y = int(h * (row + 1) / 5)
            targets.append(Target(
                id=idx, x=x, y=y, radius=radius,
                color_name=colors[idx % len(colors)],
            ))
            idx += 1
    return targets


def _diagonal_targets(w: int, h: int, radius: int = 10) -> list[Target]:
    """Dots along the diagonal — tests consistent scaling across the screen."""
    colors = ["red", "green", "blue", "yellow", "cyan"]
    targets = []
    for i in range(5):
        frac = (i + 1) / 6
        targets.append(Target(
            id=i, x=int(w * frac), y=int(h * frac), radius=radius,
            color_name=colors[i],
        ))
    return targets


def _micro_targets(w: int, h: int) -> list[Target]:
    """Varying dot sizes from 2px to 12px — tests limits of accuracy."""
    sizes = [2, 2, 3, 3, 4, 5, 6, 8, 10, 12]
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta"]
    targets = []
    for i, radius in enumerate(sizes):
        row = i // 5
        col = i % 5
        x = int(w * (col + 1) / 6)
        y = int(h * (row + 1) / 3)
        targets.append(Target(
            id=i, x=x, y=y, radius=radius,
            color_name=colors[i % len(colors)],
        ))
    return targets


SCENARIOS = {
    "grid": _grid_targets,
    "edges": _edge_targets,
    "small": _small_targets,
    "dense": _dense_targets,
    "diagonal": _diagonal_targets,
    "micro": _micro_targets,
}


def main():
    parser = argparse.ArgumentParser(description="x11-mcp accuracy test target window")
    parser.add_argument("--scenario", default="grid")
    parser.add_argument("--x", type=int, default=100, help="Window X position")
    parser.add_argument("--y", type=int, default=100, help="Window Y position")
    parser.add_argument("--w", type=int, default=800, help="Window width")
    parser.add_argument("--h", type=int, default=600, help="Window height")
    parser.add_argument("--timeout", type=float, default=60.0, help="Seconds to wait for clicks")
    args = parser.parse_args()

    targets = SCENARIOS[args.scenario](args.w, args.h)

    tw = TargetWindow(
        win_x=args.x, win_y=args.y,
        win_w=args.w, win_h=args.h,
        targets=targets,
        title=f"x11-mcp-accuracy-{args.scenario}",
    )

    tw.create()
    try:
        tw.run_event_loop(timeout=args.timeout)
    except KeyboardInterrupt:
        pass
    finally:
        tw.destroy()


if __name__ == "__main__":
    main()
