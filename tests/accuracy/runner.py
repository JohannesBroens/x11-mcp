"""Click accuracy test runner for x11-mcp.

Spawns a target window with dots at known positions, then uses x11-mcp's
screenshot + click tools to aim at each dot. After each click, reads the
actual mouse position via xdotool and compares to the intended target.

This measures the accuracy of the full pipeline:
  API coordinates → scaling → screen coordinates → input backend → actual position

Usage:
    python -m tests.accuracy.runner [--scenario SCENARIO] [--backend BACKEND] [-v]
    python -m tests.accuracy.runner --all
    python -m tests.accuracy.runner --all --backend xdotool
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


def run_scenario(
    scenario: str,
    backend: str = "uinput",
    win_x: int = 100,
    win_y: int = 100,
    win_w: int = 800,
    win_h: int = 600,
    verbose: bool = False,
) -> ScenarioResult:
    """Run a single accuracy test scenario."""
    venv_python = str(Path(__file__).parent.parent.parent / ".venv" / "bin" / "python")

    # Start target window as subprocess (for visual reference)
    proc = subprocess.Popen(
        [venv_python, "-m", "tests.accuracy.target_window",
         "--scenario", scenario,
         "--x", str(win_x), "--y", str(win_y),
         "--w", str(win_w), "--h", str(win_h),
         "--timeout", "60"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )

    t0 = time.monotonic()

    try:
        # Wait for target window to appear and report targets
        time.sleep(1.5)

        # Read the targets line
        targets_line = proc.stdout.readline()
        if not targets_line:
            proc.terminate()
            return ScenarioResult(
                scenario=scenario, backend=backend,
                window_pos=(win_x, win_y), window_size=(win_w, win_h),
                targets_total=0, targets_hit=0,
            )

        targets_data = json.loads(targets_line)
        targets = targets_data["targets"]

        if verbose:
            print(f"  Targets: {len(targets)} dots in '{scenario}' scenario")

        # Initialize x11-mcp
        from x11_mcp.screenshot import take_screenshot
        from x11_mcp.scaling import get_state
        from x11_mcp.input import set_input_backend, get_input_device

        set_input_backend(backend)

        # Take a screenshot to initialize coordinate scaling
        take_screenshot(mode="fullscreen")
        state = get_state()

        if verbose:
            print(f"  Screen: {state.screen_size}, API: {state.api_size}, Offset: {state.monitor_offset}")

        # Click each target and measure where the click actually landed
        clicks = []
        for target in targets:
            screen_x = target["screen_x"]
            screen_y = target["screen_y"]
            radius = target["radius"]

            # Convert screen coords to API coords
            api_x, api_y = state.screen_to_api(screen_x, screen_y)

            if verbose:
                print(f"  Target {target['id']}: screen ({screen_x},{screen_y}) -> API ({api_x},{api_y})")

            # Move mouse first (so we can read position after), then click
            dev = get_input_device()
            dev.move(api_x, api_y)
            time.sleep(0.05)

            # Read actual mouse position BEFORE clicking (this is what matters for accuracy)
            actual_x, actual_y = _get_mouse_position()

            # Now click (for visual feedback on the target window)
            dev.click(api_x, api_y, button="left", count=1)
            time.sleep(0.1)

            # Compute error
            error = ((actual_x - screen_x) ** 2 + (actual_y - screen_y) ** 2) ** 0.5
            hit = error <= radius + 2  # small tolerance

            clicks.append(ClickResult(
                target_id=target["id"],
                target_screen_x=screen_x,
                target_screen_y=screen_y,
                target_api_x=api_x,
                target_api_y=api_y,
                target_radius=radius,
                actual_screen_x=actual_x,
                actual_screen_y=actual_y,
                error_px=round(error, 1),
                hit=hit,
            ))

            if verbose:
                status = f"HIT (err={error:.1f}px)" if hit else f"MISS (err={error:.1f}px)"
                print(f"    -> actual ({actual_x},{actual_y}) {status}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    duration = time.monotonic() - t0

    # Compute statistics
    hits = [c for c in clicks if c.hit]
    errors = [c.error_px for c in clicks]
    bias_x_vals = [c.actual_screen_x - c.target_screen_x for c in clicks]
    bias_y_vals = [c.actual_screen_y - c.target_screen_y for c in clicks]

    return ScenarioResult(
        scenario=scenario,
        backend=backend,
        window_pos=(win_x, win_y),
        window_size=(win_w, win_h),
        targets_total=len(targets),
        targets_hit=len(hits),
        clicks=clicks,
        mean_error=sum(errors) / len(errors) if errors else 0.0,
        max_error=max(errors) if errors else 0.0,
        bias_x=sum(bias_x_vals) / len(bias_x_vals) if bias_x_vals else 0.0,
        bias_y=sum(bias_y_vals) / len(bias_y_vals) if bias_y_vals else 0.0,
        duration=duration,
    )


def format_report(results: list[ScenarioResult]) -> str:
    """Format accuracy test results into a human-readable report."""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("x11-mcp Click Accuracy Report")
    lines.append("=" * 70)

    total_targets = 0
    total_hits = 0
    all_errors = []

    for r in results:
        total_targets += r.targets_total
        total_hits += r.targets_hit

        hit_rate = (r.targets_hit / r.targets_total * 100) if r.targets_total else 0
        lines.append(f"\n  [{r.scenario}] backend={r.backend}")
        lines.append(f"    Hit rate: {r.targets_hit}/{r.targets_total} ({hit_rate:.0f}%)")
        lines.append(f"    Mean error: {r.mean_error:.1f}px")
        lines.append(f"    Max error:  {r.max_error:.1f}px")
        lines.append(f"    Bias:       x={r.bias_x:+.1f}px  y={r.bias_y:+.1f}px")
        lines.append(f"    Duration:   {r.duration:.1f}s")

        for c in r.clicks:
            status = "HIT " if c.hit else "MISS"
            dx = c.actual_screen_x - c.target_screen_x
            dy = c.actual_screen_y - c.target_screen_y
            lines.append(
                f"      T{c.target_id}: target({c.target_screen_x},{c.target_screen_y}) "
                f"api({c.target_api_x},{c.target_api_y}) -> "
                f"actual({c.actual_screen_x},{c.actual_screen_y}) "
                f"err={c.error_px}px dx={dx:+d} dy={dy:+d} [{status}]"
            )
            all_errors.append(c.error_px)

    lines.append("")
    lines.append("-" * 70)
    overall_rate = (total_hits / total_targets * 100) if total_targets else 0
    overall_mean = sum(all_errors) / len(all_errors) if all_errors else 0
    overall_max = max(all_errors) if all_errors else 0

    lines.append(f"  OVERALL: {total_hits}/{total_targets} ({overall_rate:.0f}%) targets hit")
    lines.append(f"  Mean error: {overall_mean:.1f}px | Max error: {overall_max:.1f}px")

    if overall_rate == 100 and overall_mean <= 3:
        lines.append(f"  VERDICT: EXCELLENT")
    elif overall_rate >= 90 and overall_mean <= 8:
        lines.append(f"  VERDICT: GOOD")
    elif overall_rate >= 70:
        lines.append(f"  VERDICT: FAIR — may miss small targets")
    else:
        lines.append(f"  VERDICT: POOR — systematic aim issues")

    # Bias analysis
    all_bias_x = [r.bias_x for r in results if r.targets_total > 0]
    all_bias_y = [r.bias_y for r in results if r.targets_total > 0]
    if all_bias_x:
        avg_bias_x = sum(all_bias_x) / len(all_bias_x)
        avg_bias_y = sum(all_bias_y) / len(all_bias_y)
        if abs(avg_bias_x) > 3 or abs(avg_bias_y) > 3:
            lines.append(f"\n  SYSTEMATIC BIAS DETECTED:")
            lines.append(f"    Average drift: x={avg_bias_x:+.1f}px  y={avg_bias_y:+.1f}px")
            if avg_bias_x > 3:
                lines.append(f"    Clicks land {avg_bias_x:.0f}px too far RIGHT")
            elif avg_bias_x < -3:
                lines.append(f"    Clicks land {abs(avg_bias_x):.0f}px too far LEFT")
            if avg_bias_y > 3:
                lines.append(f"    Clicks land {avg_bias_y:.0f}px too far DOWN")
            elif avg_bias_y < -3:
                lines.append(f"    Clicks land {abs(avg_bias_y):.0f}px too far UP")
        else:
            lines.append(f"\n  No systematic bias detected (drift < 3px)")

    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="x11-mcp click accuracy test runner")
    parser.add_argument("--scenario", default="grid", choices=["grid", "edges", "small", "dense", "diagonal"])
    parser.add_argument("--backend", default="uinput", choices=["uinput", "xdotool", "both"])
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--report", help="Save JSON report to file")
    args = parser.parse_args()

    scenarios = ["grid", "edges", "small", "dense", "diagonal"] if args.all else [args.scenario]
    backends = ["uinput", "xdotool"] if args.backend == "both" else [args.backend]

    results = []
    for scenario in scenarios:
        for backend in backends:
            print(f"Running: {scenario} (backend={backend})...")
            result = run_scenario(
                scenario=scenario,
                backend=backend,
                verbose=args.verbose,
            )
            results.append(result)

    report = format_report(results)
    print(report)

    if args.report:
        report_data = []
        for r in results:
            report_data.append({
                "scenario": r.scenario,
                "backend": r.backend,
                "targets_total": r.targets_total,
                "targets_hit": r.targets_hit,
                "mean_error": round(r.mean_error, 1),
                "max_error": round(r.max_error, 1),
                "bias_x": round(r.bias_x, 1),
                "bias_y": round(r.bias_y, 1),
                "clicks": [
                    {
                        "target_id": c.target_id,
                        "target_screen": [c.target_screen_x, c.target_screen_y],
                        "target_api": [c.target_api_x, c.target_api_y],
                        "actual_screen": [c.actual_screen_x, c.actual_screen_y],
                        "radius": c.target_radius,
                        "hit": c.hit,
                        "error_px": c.error_px,
                    }
                    for c in r.clicks
                ],
            })
        with open(args.report, "w") as f:
            json.dump(report_data, f, indent=2)
        print(f"\nJSON report saved to: {args.report}")

    total = sum(r.targets_total for r in results)
    hits = sum(r.targets_hit for r in results)
    sys.exit(0 if total > 0 and (hits / total) >= 0.8 else 1)


if __name__ == "__main__":
    main()
