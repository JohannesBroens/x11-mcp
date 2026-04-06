"""Click accuracy test runner for x11-mcp.

Uses the real automation workflow: for each test window, moves it to the
primary monitor, takes a screenshot to initialize scaling, clicks each
target, verifies accuracy, then restores the window to its original position.

This tests the FULL pipeline as Claude would use it in production:
  focus_and_capture → screenshot → api_to_screen → click → verify

Usage:
    python -m tests.accuracy.runner                    # baseline test
    python -m tests.accuracy.runner --stress           # all stress configs
    python -m tests.accuracy.runner --stress -v        # verbose with per-target details
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ClickResult:
    target_id: int
    target_radius: int
    # Screen coords after window was moved to primary
    target_screen_x: int
    target_screen_y: int
    target_api_x: int
    target_api_y: int
    actual_screen_x: int
    actual_screen_y: int
    error_px: float
    hit: bool


@dataclass
class ScenarioResult:
    name: str
    scenario: str
    backend: str
    original_pos: tuple[int, int]
    original_size: tuple[int, int]
    placed_pos: tuple[int, int]
    placed_size: tuple[int, int]
    targets_total: int
    targets_hit: int
    clicks: list[ClickResult] = field(default_factory=list)
    mean_error: float = 0.0
    max_error: float = 0.0
    bias_x: float = 0.0
    bias_y: float = 0.0
    duration: float = 0.0
    notes: str = ""


# Stress configs: (name, scenario, initial_x, initial_y, w, h, notes)
# These are the INITIAL positions — the runner will move them to primary before clicking
STRESS_CONFIGS = [
    ("baseline", "grid", 400, 200, 800, 600, "Normal window on primary"),
    ("from-secondary", "grid", 2800, 200, 800, 600, "Starts on secondary, moved to primary for clicking"),
    ("ultra-wide", "diagonal", 100, 400, 1600, 120, "Ultra-wide 13:1 ratio"),
    ("ultra-tall", "diagonal", 400, 50, 120, 1200, "Ultra-tall 1:10 ratio"),
    ("off-screen-right", "edges", 2200, 300, 800, 600, "Initially half off-screen right"),
    ("off-screen-bottom", "edges", 300, 1100, 800, 600, "Initially half off-screen bottom"),
    ("fullscreen", "grid", 0, 0, 2560, 1440, "Fullscreen primary monitor"),
    ("tiny-window", "small", 600, 400, 60, 40, "Tiny 60x40 with 4px dots"),
    ("micro-dots", "micro", 200, 200, 800, 600, "Varying dot sizes 2px-12px"),
    ("small-square", "grid", 800, 500, 150, 150, "Small 150x150"),
    ("corner-top-left", "edges", 0, 0, 400, 300, "Top-left corner"),
    ("bottom-right", "edges", 1800, 900, 400, 300, "Bottom-right area"),
    ("from-far-secondary", "dense", 3500, 500, 800, 600, "Far right on secondary, 20 targets"),
]


def _get_mouse_position() -> tuple[int, int]:
    result = subprocess.run(
        ["xdotool", "getmouselocation"],
        capture_output=True, text=True, timeout=5,
    )
    m = re.search(r"x:(\d+) y:(\d+)", result.stdout)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    raise RuntimeError(f"Could not read mouse position: {result.stdout}")


def _move_window(wid: int, x: int, y: int, w: int, h: int) -> None:
    """Move and resize a window via wmctrl."""
    try:
        subprocess.run(
            ["wmctrl", "-i", "-r", hex(wid),
             "-b", "remove,maximized_vert,maximized_horz"],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass
    subprocess.run(
        ["wmctrl", "-i", "-r", hex(wid),
         "-e", f"0,{x},{y},{w},{h}"],
        capture_output=True, timeout=3,
    )
    time.sleep(0.2)


def _get_window_geometry(wid: int) -> tuple[int, int, int, int]:
    """Get actual window position and size."""
    result = subprocess.run(
        ["xdotool", "getwindowgeometry", str(wid)],
        capture_output=True, text=True, timeout=3,
    )
    pos_m = re.search(r"Position: (\d+),(\d+)", result.stdout)
    geo_m = re.search(r"Geometry: (\d+)x(\d+)", result.stdout)
    if pos_m and geo_m:
        return (int(pos_m.group(1)), int(pos_m.group(2)),
                int(geo_m.group(1)), int(geo_m.group(2)))
    raise RuntimeError(f"Could not read geometry: {result.stdout}")


def run_config(
    name: str,
    scenario: str,
    init_x: int, init_y: int,
    init_w: int, init_h: int,
    backend: str = "uinput",
    notes: str = "",
    verbose: bool = False,
) -> ScenarioResult:
    """Run a single accuracy test using the full automation workflow."""
    venv_python = str(Path(__file__).parent.parent.parent / ".venv" / "bin" / "python")

    init_w = max(init_w, 10)
    init_h = max(init_h, 10)

    # 1. Spawn target window at initial position
    proc = subprocess.Popen(
        [venv_python, "-m", "tests.accuracy.target_window",
         "--scenario", scenario,
         "--x", str(init_x), "--y", str(init_y),
         "--w", str(init_w), "--h", str(init_h),
         "--timeout", "45"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )

    t0 = time.monotonic()

    try:
        time.sleep(1.5)

        targets_line = proc.stdout.readline()
        if not targets_line:
            return ScenarioResult(
                name=name, scenario=scenario, backend=backend,
                original_pos=(init_x, init_y), original_size=(init_w, init_h),
                placed_pos=(0, 0), placed_size=(0, 0),
                targets_total=0, targets_hit=0,
                notes=f"SKIP: no targets. {notes}",
            )

        targets_data = json.loads(targets_line)
        targets = targets_data.get("targets", [])
        actual_win_x = targets_data.get("window_x", init_x)
        actual_win_y = targets_data.get("window_y", init_y)

        if verbose:
            print(f"  {len(targets)} targets, initial pos=({actual_win_x},{actual_win_y})")

        # 2. Find the window ID
        wid = None
        result = subprocess.run(
            ["xdotool", "search", "--name", f"x11-mcp-accuracy-{scenario}"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split():
            wid = int(line)
            break

        if wid is None:
            return ScenarioResult(
                name=name, scenario=scenario, backend=backend,
                original_pos=(init_x, init_y), original_size=(init_w, init_h),
                placed_pos=(0, 0), placed_size=(0, 0),
                targets_total=0, targets_hit=0,
                notes=f"SKIP: window not found. {notes}",
            )

        # 3. Save original geometry for restoration
        orig_x, orig_y, orig_w, orig_h = _get_window_geometry(wid)

        # 4. MOVE TO PRIMARY MONITOR (this is the key step!)
        # Place at a safe position fully within the primary monitor
        primary_w, primary_h = 2560, 1440  # will be overridden by detect
        try:
            from x11_mcp.input import _detect_screen_size
            from x11_mcp.screenshot import _get_primary_monitor
            pm = _get_primary_monitor()
            if pm:
                primary_w, primary_h = pm["w"], pm["h"]
        except Exception:
            pass

        # Ensure window fits on primary
        place_w = min(init_w, primary_w - 40)
        place_h = min(init_h, primary_h - 80)
        place_x = max(20, min(200, primary_w - place_w - 20))
        place_y = max(40, min(100, primary_h - place_h - 20))

        _move_window(wid, place_x, place_y, place_w, place_h)

        # 5. Focus + raise the window
        subprocess.run(["wmctrl", "-i", "-a", hex(wid)], capture_output=True, timeout=3)
        time.sleep(0.3)

        # 6. Read actual placed geometry
        placed_x, placed_y, placed_w, placed_h = _get_window_geometry(wid)

        if verbose:
            print(f"  Moved: ({orig_x},{orig_y}) {orig_w}x{orig_h} -> ({placed_x},{placed_y}) {placed_w}x{placed_h}")

        # 7. Take screenshot to initialize scaling
        from x11_mcp.screenshot import take_screenshot
        from x11_mcp.scaling import get_state
        from x11_mcp.input import set_input_backend, get_input_device

        set_input_backend(backend)
        take_screenshot(mode="fullscreen")
        state = get_state()

        if verbose:
            print(f"  Scaling: screen={state.screen_size}, api={state.api_size}, offset={state.monitor_offset}")

        # 8. Compute target screen positions using the PLACED window position
        # Targets are relative to window content area — placed_x/y is the content origin
        clicks = []
        for t in targets:
            # Target's screen position = window position + target offset within window
            screen_x = placed_x + t["win_x"]
            screen_y = placed_y + t["win_y"]
            radius = t["radius"]

            api_x, api_y = state.screen_to_api(screen_x, screen_y)

            if verbose:
                print(f"  T{t['id']}: win({t['win_x']},{t['win_y']}) + placed({placed_x},{placed_y}) = screen({screen_x},{screen_y}) -> API({api_x},{api_y})", end="")

            dev = get_input_device()
            dev.move(api_x, api_y)
            time.sleep(0.04)

            actual_x, actual_y = _get_mouse_position()

            dev.click(api_x, api_y, button="left", count=1)
            time.sleep(0.06)

            error = ((actual_x - screen_x) ** 2 + (actual_y - screen_y) ** 2) ** 0.5
            hit = error <= radius + 2

            clicks.append(ClickResult(
                target_id=t["id"], target_radius=radius,
                target_screen_x=screen_x, target_screen_y=screen_y,
                target_api_x=api_x, target_api_y=api_y,
                actual_screen_x=actual_x, actual_screen_y=actual_y,
                error_px=round(error, 1), hit=hit,
            ))

            if verbose:
                status = f"HIT({error:.1f}px)" if hit else f"MISS({error:.1f}px)"
                print(f" -> actual({actual_x},{actual_y}) {status}")

        # 9. RESTORE original geometry
        _move_window(wid, orig_x, orig_y, orig_w, orig_h)

        if verbose:
            print(f"  Restored to ({orig_x},{orig_y}) {orig_w}x{orig_h}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    duration = time.monotonic() - t0

    errors = [c.error_px for c in clicks]
    hits = [c for c in clicks if c.hit]
    bias_x_vals = [c.actual_screen_x - c.target_screen_x for c in clicks]
    bias_y_vals = [c.actual_screen_y - c.target_screen_y for c in clicks]

    return ScenarioResult(
        name=name, scenario=scenario, backend=backend,
        original_pos=(init_x, init_y), original_size=(init_w, init_h),
        placed_pos=(placed_x, placed_y), placed_size=(placed_w, placed_h),
        targets_total=len(clicks),
        targets_hit=len(hits),
        clicks=clicks,
        mean_error=sum(errors) / len(errors) if errors else 0.0,
        max_error=max(errors) if errors else 0.0,
        bias_x=sum(bias_x_vals) / len(bias_x_vals) if bias_x_vals else 0.0,
        bias_y=sum(bias_y_vals) / len(bias_y_vals) if bias_y_vals else 0.0,
        duration=duration,
        notes=notes,
    )


def format_report(results: list[ScenarioResult]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("x11-mcp Click Accuracy Report (Full Workflow)")
    lines.append("=" * 80)

    total_targets = 0
    total_hits = 0
    all_errors = []
    failures = []

    for r in results:
        total_targets += r.targets_total
        total_hits += r.targets_hit

        hit_rate = (r.targets_hit / r.targets_total * 100) if r.targets_total else 0
        status = "PASS" if r.targets_total > 0 and hit_rate >= 80 else "FAIL" if r.targets_total > 0 else "SKIP"

        lines.append(f"\n  [{status}] {r.name} ({r.backend})")
        lines.append(f"    {r.notes}")
        lines.append(f"    Original: ({r.original_pos[0]},{r.original_pos[1]}) {r.original_size[0]}x{r.original_size[1]}"
                     f" -> Placed: ({r.placed_pos[0]},{r.placed_pos[1]}) {r.placed_size[0]}x{r.placed_size[1]}")
        lines.append(f"    Hits: {r.targets_hit}/{r.targets_total} ({hit_rate:.0f}%) | "
                     f"Err: {r.mean_error:.1f}px avg, {r.max_error:.1f}px max | "
                     f"Bias: x={r.bias_x:+.1f} y={r.bias_y:+.1f}")

        if status == "FAIL":
            failures.append(r.name)

        for c in r.clicks:
            dx = c.actual_screen_x - c.target_screen_x
            dy = c.actual_screen_y - c.target_screen_y
            s = "HIT " if c.hit else "MISS"
            lines.append(
                f"      T{c.target_id}: r={c.target_radius}px "
                f"({c.target_screen_x},{c.target_screen_y})->"
                f"({c.actual_screen_x},{c.actual_screen_y}) "
                f"err={c.error_px}px dx={dx:+d} dy={dy:+d} [{s}]"
            )
            all_errors.append(c.error_px)

    lines.append("")
    lines.append("=" * 80)
    overall_rate = (total_hits / total_targets * 100) if total_targets else 0
    overall_mean = sum(all_errors) / len(all_errors) if all_errors else 0
    overall_max = max(all_errors) if all_errors else 0

    lines.append(f"  TOTAL: {total_hits}/{total_targets} ({overall_rate:.0f}%) across {len(results)} configs")
    lines.append(f"  Mean error: {overall_mean:.1f}px | Max: {overall_max:.1f}px")

    if failures:
        lines.append(f"  FAILED: {', '.join(failures)}")

    all_bias_x = [r.bias_x for r in results if r.targets_total > 0]
    all_bias_y = [r.bias_y for r in results if r.targets_total > 0]
    if all_bias_x:
        bx = sum(all_bias_x) / len(all_bias_x)
        by = sum(all_bias_y) / len(all_bias_y)
        lines.append(f"  Bias: x={bx:+.1f}px y={by:+.1f}px {'(DRIFT!)' if abs(bx) > 3 or abs(by) > 3 else '(OK)'}")

    size_errors: dict[int, list[float]] = {}
    for r in results:
        for c in r.clicks:
            size_errors.setdefault(c.target_radius, []).append(c.error_px)
    if size_errors:
        lines.append(f"\n  Accuracy by dot size:")
        for radius in sorted(size_errors.keys()):
            errs = size_errors[radius]
            hits = sum(1 for e in errs if e <= radius + 2)
            mean = sum(errs) / len(errs)
            lines.append(f"    r={radius:2d}px: {hits}/{len(errs)} hit ({mean:.1f}px avg)")

    verdict = ("EXCELLENT" if overall_rate == 100 and overall_mean <= 3
               else "GOOD" if overall_rate >= 90
               else "FAIR" if overall_rate >= 70
               else "POOR")
    lines.append(f"\n  VERDICT: {verdict}")
    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="x11-mcp click accuracy test")
    parser.add_argument("--scenario", default="grid")
    parser.add_argument("--backend", default="uinput", choices=["uinput", "xdotool", "both"])
    parser.add_argument("--stress", action="store_true", help="Run all stress configs")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--report", help="Save JSON report")
    args = parser.parse_args()

    backends = ["uinput", "xdotool"] if args.backend == "both" else [args.backend]
    configs = STRESS_CONFIGS if args.stress else [("run", args.scenario, 400, 200, 800, 600, "Single run")]

    results = []
    for backend in backends:
        for name, scenario, x, y, w, h, notes in configs:
            label = f"{name}" if len(backends) == 1 else f"{name}/{backend}"
            print(f"  {label}...", end=" ", flush=True)
            result = run_config(
                name=name, scenario=scenario,
                init_x=x, init_y=y, init_w=w, init_h=h,
                backend=backend, notes=notes, verbose=args.verbose,
            )
            rate = f"{result.targets_hit}/{result.targets_total}" if result.targets_total else "skip"
            print(f"{rate} ({result.mean_error:.1f}px)")
            results.append(result)

    report = format_report(results)
    print(report)

    if args.report:
        data = [{"name": r.name, "backend": r.backend,
                 "original": list(r.original_pos) + list(r.original_size),
                 "placed": list(r.placed_pos) + list(r.placed_size),
                 "hits": r.targets_hit, "total": r.targets_total,
                 "mean_error": round(r.mean_error, 1), "max_error": round(r.max_error, 1),
                 "bias": [round(r.bias_x, 1), round(r.bias_y, 1)],
                 "clicks": [{"id": c.target_id, "r": c.target_radius,
                             "target": [c.target_screen_x, c.target_screen_y],
                             "actual": [c.actual_screen_x, c.actual_screen_y],
                             "error": c.error_px, "hit": c.hit} for c in r.clicks],
                 } for r in results]
        with open(args.report, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nReport: {args.report}")

    total = sum(r.targets_total for r in results)
    hits = sum(r.targets_hit for r in results)
    sys.exit(0 if total > 0 and (hits / total) >= 0.9 else 1)


if __name__ == "__main__":
    main()
