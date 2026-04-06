"""Click accuracy stress test runner for x11-mcp.

Spawns target windows in various extreme configurations and measures
click accuracy across all of them. Designed to find systematic bugs
in coordinate mapping, scaling, and input delivery.

Test configurations:
  - Normal window on primary monitor (baseline)
  - Window on secondary monitor (cross-monitor targeting)
  - Extreme aspect ratios (ultra-wide, ultra-tall)
  - Window half off-screen (clipped by screen edge)
  - Fullscreen window covering entire primary monitor
  - Tiny 60x40 window with micro dots
  - Varying dot sizes from 2px to 12px radius

Usage:
    python -m tests.accuracy.runner                    # baseline grid test
    python -m tests.accuracy.runner --stress           # all stress configurations
    python -m tests.accuracy.runner --stress --backend both  # compare uinput vs xdotool
    python -m tests.accuracy.runner --report results.json -v
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
    target_screen_x: int
    target_screen_y: int
    target_api_x: int
    target_api_y: int
    target_radius: int
    actual_screen_x: int
    actual_screen_y: int
    error_px: float
    hit: bool


@dataclass
class ScenarioResult:
    name: str
    scenario: str
    backend: str
    window_pos: tuple[int, int]
    window_size: tuple[int, int]
    targets_total: int
    targets_hit: int
    clicks: list[ClickResult] = field(default_factory=list)
    mean_error: float = 0.0
    max_error: float = 0.0
    bias_x: float = 0.0
    bias_y: float = 0.0
    duration: float = 0.0
    notes: str = ""


# --- Stress test configurations ---

STRESS_CONFIGS = [
    # (name, scenario, x, y, w, h, notes)
    ("baseline", "grid", 400, 200, 800, 600, "Normal window on primary monitor"),
    ("secondary-monitor", "grid", 2700, 200, 800, 600, "Window on secondary monitor (x=2700)"),
    ("ultra-wide", "diagonal", 100, 400, 1600, 120, "Ultra-wide aspect ratio (13:1)"),
    ("ultra-tall", "diagonal", 400, 50, 120, 1200, "Ultra-tall aspect ratio (1:10)"),
    ("off-right", "edges", 2200, 300, 800, 600, "Hanging off right edge of primary (2200+800=3000 > 2560)"),
    ("off-bottom", "edges", 300, 1100, 800, 600, "Hanging off bottom edge (1100+600=1700 > 1440)"),
    ("off-top-left", "edges", -200, -100, 800, 600, "Hanging off top-left corner"),
    ("fullscreen", "grid", 0, 0, 2560, 1440, "Fullscreen on primary monitor"),
    ("tiny-window", "small", 600, 400, 60, 40, "Tiny 60x40 window with 4px dots"),
    ("micro-dots", "micro", 200, 200, 800, 600, "Varying dot sizes 2px-12px"),
    ("small-square", "grid", 800, 500, 150, 150, "Small 150x150 square"),
    ("corner-primary", "edges", 0, 0, 400, 300, "Tucked into top-left corner of primary"),
    ("corner-bottom-right", "edges", 2160, 1140, 400, 300, "Bottom-right corner of primary"),
]


def _get_mouse_position() -> tuple[int, int]:
    """Get current mouse position via xdotool."""
    result = subprocess.run(
        ["xdotool", "getmouselocation"],
        capture_output=True, text=True, timeout=5,
    )
    m = re.search(r"x:(\d+) y:(\d+)", result.stdout)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    raise RuntimeError(f"Could not read mouse position: {result.stdout}")


def run_config(
    name: str,
    scenario: str,
    win_x: int,
    win_y: int,
    win_w: int,
    win_h: int,
    backend: str = "uinput",
    notes: str = "",
    verbose: bool = False,
) -> ScenarioResult:
    """Run a single accuracy test configuration."""
    venv_python = str(Path(__file__).parent.parent.parent / ".venv" / "bin" / "python")

    # Clamp minimum window size (X11 won't create < 1x1)
    win_w = max(win_w, 10)
    win_h = max(win_h, 10)

    proc = subprocess.Popen(
        [venv_python, "-m", "tests.accuracy.target_window",
         "--scenario", scenario,
         "--x", str(win_x), "--y", str(win_y),
         "--w", str(win_w), "--h", str(win_h),
         "--timeout", "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )

    t0 = time.monotonic()

    try:
        time.sleep(1.5)

        targets_line = proc.stdout.readline()
        if not targets_line:
            return ScenarioResult(
                name=name, scenario=scenario, backend=backend,
                window_pos=(win_x, win_y), window_size=(win_w, win_h),
                targets_total=0, targets_hit=0, notes=f"SKIP: no targets reported. {notes}",
            )

        targets_data = json.loads(targets_line)
        targets = targets_data.get("targets", [])

        if not targets:
            return ScenarioResult(
                name=name, scenario=scenario, backend=backend,
                window_pos=(win_x, win_y), window_size=(win_w, win_h),
                targets_total=0, targets_hit=0, notes=f"SKIP: empty targets. {notes}",
            )

        if verbose:
            print(f"  {len(targets)} targets, window actual pos from target_window")

        from x11_mcp.screenshot import take_screenshot
        from x11_mcp.scaling import get_state
        from x11_mcp.input import set_input_backend, get_input_device

        set_input_backend(backend)
        take_screenshot(mode="fullscreen")
        state = get_state()

        if verbose:
            print(f"  Screen: {state.screen_size}, API: {state.api_size}, Offset: {state.monitor_offset}")

        clicks = []
        for target in targets:
            screen_x = target["screen_x"]
            screen_y = target["screen_y"]
            radius = target["radius"]

            # Skip targets that are off-screen (negative or beyond root)
            if screen_x < 0 or screen_y < 0:
                clicks.append(ClickResult(
                    target_id=target["id"],
                    target_screen_x=screen_x, target_screen_y=screen_y,
                    target_api_x=0, target_api_y=0,
                    target_radius=radius,
                    actual_screen_x=0, actual_screen_y=0,
                    error_px=999.0, hit=False,
                ))
                if verbose:
                    print(f"  T{target['id']}: SKIP (off-screen at {screen_x},{screen_y})")
                continue

            api_x, api_y = state.screen_to_api(screen_x, screen_y)

            if verbose:
                print(f"  T{target['id']}: screen({screen_x},{screen_y}) r={radius} -> API({api_x},{api_y})", end="")

            dev = get_input_device()
            dev.move(api_x, api_y)
            time.sleep(0.05)

            actual_x, actual_y = _get_mouse_position()

            dev.click(api_x, api_y, button="left", count=1)
            time.sleep(0.08)

            error = ((actual_x - screen_x) ** 2 + (actual_y - screen_y) ** 2) ** 0.5
            hit = error <= radius + 2

            clicks.append(ClickResult(
                target_id=target["id"],
                target_screen_x=screen_x, target_screen_y=screen_y,
                target_api_x=api_x, target_api_y=api_y,
                target_radius=radius,
                actual_screen_x=actual_x, actual_screen_y=actual_y,
                error_px=round(error, 1),
                hit=hit,
            ))

            if verbose:
                status = f"HIT({error:.1f}px)" if hit else f"MISS({error:.1f}px)"
                print(f" -> actual({actual_x},{actual_y}) {status}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    duration = time.monotonic() - t0

    valid_clicks = [c for c in clicks if c.error_px < 900]
    hits = [c for c in valid_clicks if c.hit]
    errors = [c.error_px for c in valid_clicks]
    bias_x_vals = [c.actual_screen_x - c.target_screen_x for c in valid_clicks]
    bias_y_vals = [c.actual_screen_y - c.target_screen_y for c in valid_clicks]

    return ScenarioResult(
        name=name, scenario=scenario, backend=backend,
        window_pos=(win_x, win_y), window_size=(win_w, win_h),
        targets_total=len(valid_clicks),
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
    """Format accuracy test results into a human-readable report."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("x11-mcp Click Accuracy Stress Test Report")
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
        lines.append(f"    Window: ({r.window_pos[0]},{r.window_pos[1]}) {r.window_size[0]}x{r.window_size[1]}")
        lines.append(f"    Hits: {r.targets_hit}/{r.targets_total} ({hit_rate:.0f}%) | "
                     f"Mean err: {r.mean_error:.1f}px | Max: {r.max_error:.1f}px | "
                     f"Bias: x={r.bias_x:+.1f} y={r.bias_y:+.1f}")

        if status == "FAIL":
            failures.append(r.name)

        # Show individual clicks for failures or verbose
        for c in r.clicks:
            if c.error_px >= 900:
                lines.append(f"      T{c.target_id}: SKIPPED (off-screen)")
                continue
            status_c = "HIT " if c.hit else "MISS"
            dx = c.actual_screen_x - c.target_screen_x
            dy = c.actual_screen_y - c.target_screen_y
            lines.append(
                f"      T{c.target_id}: r={c.target_radius}px "
                f"target({c.target_screen_x},{c.target_screen_y}) -> "
                f"actual({c.actual_screen_x},{c.actual_screen_y}) "
                f"err={c.error_px}px dx={dx:+d} dy={dy:+d} [{status_c}]"
            )
            if c.error_px < 900:
                all_errors.append(c.error_px)

    # Summary
    lines.append("")
    lines.append("=" * 80)
    overall_rate = (total_hits / total_targets * 100) if total_targets else 0
    overall_mean = sum(all_errors) / len(all_errors) if all_errors else 0
    overall_max = max(all_errors) if all_errors else 0

    lines.append(f"  TOTAL: {total_hits}/{total_targets} ({overall_rate:.0f}%) targets hit across {len(results)} configs")
    lines.append(f"  Mean error: {overall_mean:.1f}px | Max error: {overall_max:.1f}px")

    if failures:
        lines.append(f"\n  FAILED CONFIGS: {', '.join(failures)}")

    # Bias analysis
    all_bias_x = [r.bias_x for r in results if r.targets_hit > 0]
    all_bias_y = [r.bias_y for r in results if r.targets_hit > 0]
    if all_bias_x:
        avg_bias_x = sum(all_bias_x) / len(all_bias_x)
        avg_bias_y = sum(all_bias_y) / len(all_bias_y)
        if abs(avg_bias_x) > 3 or abs(avg_bias_y) > 3:
            lines.append(f"\n  SYSTEMATIC BIAS: x={avg_bias_x:+.1f}px  y={avg_bias_y:+.1f}px")
        else:
            lines.append(f"\n  Bias: x={avg_bias_x:+.1f}px y={avg_bias_y:+.1f}px (within tolerance)")

    # Error distribution by dot size
    size_errors: dict[int, list[float]] = {}
    for r in results:
        for c in r.clicks:
            if c.error_px < 900:
                size_errors.setdefault(c.target_radius, []).append(c.error_px)
    if size_errors:
        lines.append(f"\n  Error by dot radius:")
        for radius in sorted(size_errors.keys()):
            errs = size_errors[radius]
            hits = sum(1 for e in errs if e <= radius + 2)
            mean = sum(errs) / len(errs)
            lines.append(f"    r={radius:2d}px: {hits}/{len(errs)} hit, mean err={mean:.1f}px")

    if overall_rate == 100 and overall_mean <= 3:
        lines.append(f"\n  VERDICT: EXCELLENT")
    elif overall_rate >= 90 and overall_mean <= 8:
        lines.append(f"\n  VERDICT: GOOD")
    elif overall_rate >= 70:
        lines.append(f"\n  VERDICT: FAIR")
    else:
        lines.append(f"\n  VERDICT: POOR — investigate failed configs")

    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="x11-mcp click accuracy stress test")
    parser.add_argument("--scenario", default="grid")
    parser.add_argument("--backend", default="uinput", choices=["uinput", "xdotool", "both"])
    parser.add_argument("--stress", action="store_true", help="Run all stress configurations")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--report", help="Save JSON report to file")
    args = parser.parse_args()

    backends = ["uinput", "xdotool"] if args.backend == "both" else [args.backend]

    results = []
    if args.stress:
        configs = STRESS_CONFIGS
    else:
        configs = [("baseline", args.scenario, 200, 200, 800, 600, "Single scenario run")]

    for backend in backends:
        for name, scenario, x, y, w, h, notes in configs:
            label = f"{name}" if len(backends) == 1 else f"{name}/{backend}"
            print(f"  {label}...", end=" ", flush=True)
            result = run_config(
                name=name, scenario=scenario,
                win_x=x, win_y=y, win_w=w, win_h=h,
                backend=backend, notes=notes,
                verbose=args.verbose,
            )
            results.append(result)
            rate = f"{result.targets_hit}/{result.targets_total}" if result.targets_total else "skip"
            print(f"{rate} (err={result.mean_error:.1f}px)")

    report = format_report(results)
    print(report)

    if args.report:
        report_data = []
        for r in results:
            report_data.append({
                "name": r.name, "scenario": r.scenario, "backend": r.backend,
                "window_pos": list(r.window_pos), "window_size": list(r.window_size),
                "targets_total": r.targets_total, "targets_hit": r.targets_hit,
                "mean_error": round(r.mean_error, 1), "max_error": round(r.max_error, 1),
                "bias_x": round(r.bias_x, 1), "bias_y": round(r.bias_y, 1),
                "notes": r.notes,
                "clicks": [
                    {
                        "id": c.target_id, "radius": c.target_radius,
                        "target": [c.target_screen_x, c.target_screen_y],
                        "actual": [c.actual_screen_x, c.actual_screen_y],
                        "error": c.error_px, "hit": c.hit,
                    }
                    for c in r.clicks
                ],
            })
        with open(args.report, "w") as f:
            json.dump(report_data, f, indent=2)
        print(f"\nReport: {args.report}")

    total = sum(r.targets_total for r in results)
    hits = sum(r.targets_hit for r in results)
    sys.exit(0 if total > 0 and (hits / total) >= 0.8 else 1)


if __name__ == "__main__":
    main()
