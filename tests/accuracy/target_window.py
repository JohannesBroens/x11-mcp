"""X11 target window for click accuracy testing.

Creates a window with colored dots at known positions.
Records ButtonPress events to detect actual clicks.
Forces window placement via wmctrl to ensure correct monitor.

Usage:
    python -m tests.accuracy.target_window [--scenario SCENARIO] [--x X] [--y Y] [--w W] [--h H]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from Xlib import display as xdisplay, X


@dataclass
class Target:
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
    _click_log: list = field(default_factory=list)

    def _alloc_color(self, name: str) -> int:
        colors = {
            "red": 0xFF0000, "green": 0x00FF00, "blue": 0x0000FF,
            "yellow": 0xFFFF00, "cyan": 0x00FFFF, "magenta": 0xFF00FF,
            "white": 0xFFFFFF, "orange": 0xFF8800,
        }
        return colors.get(name, 0xFF0000)

    def create(self) -> None:
        self._display = xdisplay.Display()
        screen = self._display.screen()

        self._window = screen.root.create_window(
            self.win_x, self.win_y, self.win_w, self.win_h, 0,
            screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=0x1A1A2E,
            border_pixel=0xFFFFFF,
            event_mask=(
                X.ExposureMask | X.ButtonPressMask |
                X.ButtonReleaseMask | X.StructureNotifyMask
            ),
        )

        self._window.set_wm_name(self.title)
        self._window.set_wm_class("accuracy-test", "x11-mcp-accuracy-test")

        self._gc = self._window.create_gc(
            foreground=0xFF0000,
            background=0x1A1A2E,
        )

        self._window.map()
        self._display.sync()
        time.sleep(0.5)

        # Force window to the correct position using wmctrl
        self._force_position()

    def _force_position(self) -> None:
        """Force window to requested position via wmctrl, then verify."""
        wid = self._window.id

        # Remove maximized state if WM set it
        try:
            subprocess.run(
                ["wmctrl", "-i", "-r", hex(wid),
                 "-b", "remove,maximized_vert,maximized_horz"],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass

        # Force exact position and size
        try:
            subprocess.run(
                ["wmctrl", "-i", "-r", hex(wid),
                 "-e", f"0,{self.win_x},{self.win_y},{self.win_w},{self.win_h}"],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass

        time.sleep(0.3)

        # Read actual position back
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", str(wid)],
                capture_output=True, text=True, timeout=3,
            )
            m = re.search(r"Position: (\d+),(\d+)", result.stdout)
            if m:
                self.win_x = int(m.group(1))
                self.win_y = int(m.group(2))
        except Exception:
            pass

        self._display.sync()

    def draw_targets(self) -> None:
        for t in self.targets:
            pixel = self._alloc_color(t.color_name)
            self._gc.change(foreground=pixel)
            self._window.fill_arc(
                self._gc,
                t.x - t.radius, t.y - t.radius,
                t.radius * 2, t.radius * 2,
                0, 360 * 64,
            )
            # White outline
            self._gc.change(foreground=0xFFFFFF)
            self._window.arc(
                self._gc,
                t.x - t.radius, t.y - t.radius,
                t.radius * 2, t.radius * 2,
                0, 360 * 64,
            )
            # Center cross
            self._window.line(self._gc, t.x - 2, t.y, t.x + 2, t.y)
            self._window.line(self._gc, t.x, t.y - 2, t.x, t.y + 2)

        # Draw click marks (green X for hits, red X for misses)
        for entry in self._click_log:
            cx, cy = entry["win_x"], entry["win_y"]
            color = 0x00FF00 if entry.get("hit_target") is not None else 0xFF4444
            self._gc.change(foreground=color)
            self._window.line(self._gc, cx - 5, cy - 5, cx + 5, cy + 5)
            self._window.line(self._gc, cx - 5, cy + 5, cx + 5, cy - 5)

        self._display.sync()

    def register_click(self, win_x: int, win_y: int) -> Target | None:
        best = None
        best_dist = 999999
        for t in self.targets:
            dist = ((win_x - t.x) ** 2 + (win_y - t.y) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = t
        if best is not None and best_dist <= best.radius + 5:
            best.hit = True
            best.click_x = win_x
            best.click_y = win_y
            best.error_px = best_dist
            return best
        return None

    def run_event_loop(self, timeout: float = 30.0) -> None:
        self._running = True
        start = time.monotonic()

        # Report target positions (with actual window position)
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
        print(json.dumps({"type": "targets", "window_x": self.win_x, "window_y": self.win_y, "targets": target_info}), flush=True)

        while self._running and (time.monotonic() - start) < timeout:
            if self._display.pending_events():
                ev = self._display.next_event()
                if ev.type == X.Expose:
                    self.draw_targets()
                elif ev.type == X.ButtonPress:
                    hit = self.register_click(ev.event_x, ev.event_y)
                    entry = {
                        "type": "click",
                        "win_x": ev.event_x,
                        "win_y": ev.event_y,
                        "screen_x": self.win_x + ev.event_x,
                        "screen_y": self.win_y + ev.event_y,
                        "button": ev.detail,
                        "hit_target": hit.id if hit else None,
                        "error_px": round(hit.error_px, 1) if hit else None,
                    }
                    self._click_log.append(entry)
                    print(json.dumps(entry), flush=True)
                    # Redraw to show click mark
                    self.draw_targets()
            else:
                time.sleep(0.01)

        # Summary
        results = []
        for t in self.targets:
            results.append({
                "id": t.id, "x": t.x, "y": t.y, "radius": t.radius,
                "hit": t.hit,
                "error_px": round(t.error_px, 1) if t.hit else None,
                "click_x": t.click_x if t.hit else None,
                "click_y": t.click_y if t.hit else None,
            })
        print(json.dumps({
            "type": "summary",
            "total_clicks": len(self._click_log),
            "results": results,
        }), flush=True)

    def destroy(self) -> None:
        self._running = False
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
        if self._display:
            try:
                self._display.sync()
                self._display.close()
            except Exception:
                pass


# --- Scenario definitions ---

def _grid_targets(w: int, h: int, radius: int = 15) -> list[Target]:
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta", "red", "green", "blue"]
    targets = []
    for row in range(3):
        for col in range(3):
            x = int(w * (col + 1) / 4)
            y = int(h * (row + 1) / 4)
            idx = row * 3 + col
            targets.append(Target(id=idx, x=x, y=y, radius=radius, color_name=colors[idx]))
    return targets


def _edge_targets(w: int, h: int, radius: int = 12) -> list[Target]:
    margin = 20
    return [
        Target(0, margin, margin, radius, "red"),
        Target(1, w // 2, margin, radius, "green"),
        Target(2, w - margin, margin, radius, "blue"),
        Target(3, margin, h // 2, radius, "yellow"),
        Target(4, w - margin, h // 2, radius, "cyan"),
        Target(5, margin, h - margin, radius, "magenta"),
        Target(6, w // 2, h - margin, radius, "red"),
        Target(7, w - margin, h - margin, radius, "green"),
    ]


def _small_targets(w: int, h: int) -> list[Target]:
    return [
        Target(0, w // 4, h // 4, 4, "red"),
        Target(1, 3 * w // 4, h // 4, 4, "green"),
        Target(2, w // 2, h // 2, 4, "blue"),
        Target(3, w // 4, 3 * h // 4, 4, "yellow"),
        Target(4, 3 * w // 4, 3 * h // 4, 4, "cyan"),
    ]


def _dense_targets(w: int, h: int, radius: int = 8) -> list[Target]:
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta"]
    targets = []
    idx = 0
    for row in range(4):
        for col in range(5):
            x = int(w * (col + 1) / 6)
            y = int(h * (row + 1) / 5)
            targets.append(Target(id=idx, x=x, y=y, radius=radius, color_name=colors[idx % len(colors)]))
            idx += 1
    return targets


def _diagonal_targets(w: int, h: int, radius: int = 10) -> list[Target]:
    colors = ["red", "green", "blue", "yellow", "cyan"]
    targets = []
    for i in range(5):
        frac = (i + 1) / 6
        targets.append(Target(id=i, x=int(w * frac), y=int(h * frac), radius=radius, color_name=colors[i]))
    return targets


def _micro_targets(w: int, h: int) -> list[Target]:
    sizes = [2, 2, 3, 3, 4, 5, 6, 8, 10, 12]
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta"]
    targets = []
    for i, radius in enumerate(sizes):
        row = i // 5
        col = i % 5
        x = int(w * (col + 1) / 6)
        y = int(h * (row + 1) / 3)
        targets.append(Target(id=i, x=x, y=y, radius=radius, color_name=colors[i % len(colors)]))
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
    parser.add_argument("--x", type=int, default=100)
    parser.add_argument("--y", type=int, default=100)
    parser.add_argument("--w", type=int, default=800)
    parser.add_argument("--h", type=int, default=600)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    scenario_fn = SCENARIOS.get(args.scenario, _grid_targets)
    targets = scenario_fn(args.w, args.h)

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
