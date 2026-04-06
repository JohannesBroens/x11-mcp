"""Click accuracy test runner for x11-mcp.

Cursor-position verification only. Moves the cursor to API coordinates,
reads actual position via xdotool, compares to expected screen position.
No windows, no clicks, no compositor interaction.

Cursor position IS the accuracy. If the cursor lands at the right spot,
the coordinate pipeline works. Click delivery to specific applications
should be tested manually via the MCP tools (focus_and_capture + click_and_verify).

Usage:
    python -m tests.accuracy.runner                    # grid test, uinput
    python -m tests.accuracy.runner --backend both     # both backends
    python -m tests.accuracy.runner --stress -v        # all scenarios, verbose
    python -m tests.accuracy.runner --report results.json
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


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PointResult:
    name: str
    api_x: int
    api_y: int
    expected_screen_x: int
    expected_screen_y: int
    actual_screen_x: int
    actual_screen_y: int
    error_px: float


@dataclass
class ScenarioResult:
    scenario: str
    backend: str
    points: list[PointResult] = field(default_factory=list)
    mean_error: float = 0.0
    max_error: float = 0.0
    p50_error: float = 0.0
    p95_error: float = 0.0
    bias_x: float = 0.0
    bias_y: float = 0.0
    duration: float = 0.0
    notes: str = ""


# ---------------------------------------------------------------------------
# Cursor position reading (ground truth)
# ---------------------------------------------------------------------------

def read_cursor() -> tuple[int, int]:
    """Read actual cursor position via xdotool. Raises on failure."""
    result = subprocess.run(
        ["xdotool", "getmouselocation"],
        capture_output=True, text=True, timeout=2,
    )
    m = re.match(r"x:(\d+) y:(\d+)", result.stdout)
    if not m:
        raise RuntimeError(f"Could not read cursor: {result.stdout}")
    return (int(m.group(1)), int(m.group(2)))


def poll_cursor(expected_x: int, expected_y: int, timeout_ms: int = 100) -> tuple[int, int]:
    """Read cursor position, polling until stable or timeout."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    last_x, last_y = -1, -1
    while time.monotonic() < deadline:
        x, y = read_cursor()
        if x == last_x and y == last_y:
            return (x, y)
        last_x, last_y = x, y
        time.sleep(0.01)
    return (last_x, last_y)


# ---------------------------------------------------------------------------
# Test point generators
# ---------------------------------------------------------------------------

def _grid_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """3x3 grid across the API space."""
    points = []
    for row in range(3):
        for col in range(3):
            x = int(api_w * (col + 1) / 4)
            y = int(api_h * (row + 1) / 4)
            points.append((f"grid-{row}-{col}", x, y))
    return points


def _edge_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Points near screen borders (20px margin in API space)."""
    m = 20
    return [
        ("edge-TL", m, m),
        ("edge-TC", api_w // 2, m),
        ("edge-TR", api_w - m, m),
        ("edge-ML", m, api_h // 2),
        ("edge-MR", api_w - m, api_h // 2),
        ("edge-BL", m, api_h - m),
        ("edge-BC", api_w // 2, api_h - m),
        ("edge-BR", api_w - m, api_h - m),
    ]


def _screen_edge_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Absolute screen edges — tests WM/panel clamping."""
    return [
        ("scr-TL", 0, 0),
        ("scr-TC", api_w // 2, 0),
        ("scr-TR", api_w - 1, 0),
        ("scr-ML", 0, api_h // 2),
        ("scr-MR", api_w - 1, api_h // 2),
        ("scr-BL", 0, api_h - 1),
        ("scr-BC", api_w // 2, api_h - 1),
        ("scr-BR", api_w - 1, api_h - 1),
    ]


def _diagonal_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Diagonal sweep from top-left to bottom-right."""
    points = []
    for i in range(5):
        frac = (i + 1) / 6
        points.append((f"diag-{i}", int(api_w * frac), int(api_h * frac)))
    return points


def _dense_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """4x5 grid, 20 points."""
    points = []
    for row in range(4):
        for col in range(5):
            x = int(api_w * (col + 1) / 6)
            y = int(api_h * (row + 1) / 5)
            points.append((f"dense-{row}-{col}", x, y))
    return points


def _micro_move_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Small increments from center — tests sub-pixel rounding."""
    cx, cy = api_w // 2, api_h // 2
    points = [("micro-center", cx, cy)]
    for delta in [1, 2, 3, 4, 5, -1, -2, -3, -5]:
        points.append((f"micro-dx{delta:+d}", cx + delta, cy))
    return points


def _large_jump_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Opposite corner jumps — max distance moves."""
    return [
        ("jump-TL", 10, 10),
        ("jump-BR", api_w - 10, api_h - 10),
        ("jump-TR", api_w - 10, 10),
        ("jump-BL", 10, api_h - 10),
        ("jump-center", api_w // 2, api_h // 2),
    ]


def _same_axis_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Horizontal-only and vertical-only moves."""
    cy = api_h // 2
    cx = api_w // 2
    return [
        ("haxis-L", 50, cy),
        ("haxis-M", api_w // 2, cy),
        ("haxis-R", api_w - 50, cy),
        ("vaxis-T", cx, 50),
        ("vaxis-M", cx, api_h // 2),
        ("vaxis-B", cx, api_h - 50),
    ]


def _random_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """20 random points — catches edge cases grids miss."""
    import random
    rng = random.Random(42)  # Fixed seed for reproducibility
    points = []
    for i in range(20):
        x = rng.randint(0, api_w - 1)
        y = rng.randint(0, api_h - 1)
        points.append((f"rand-{i}", x, y))
    return points


def _fractional_stress_points(api_w: int, api_h: int) -> list[tuple[str, int, int]]:
    """Points that stress fractional coordinate mapping."""
    points = []
    fractions = [1/3, 2/3, 1/7, 2/7, 3/7, 4/7, 5/7, 6/7, 1/11, 3/11, 5/11, 7/11, 9/11]
    for i, frac in enumerate(fractions):
        x = int(api_w * frac)
        y = int(api_h * (1 - frac))
        points.append((f"frac-{i}", x, y))
    return points


SCENARIOS = {
    "grid": _grid_points,
    "edges": _edge_points,
    "screen-edges": _screen_edge_points,
    "diagonal": _diagonal_points,
    "dense": _dense_points,
    "micro-moves": _micro_move_points,
    "large-jumps": _large_jump_points,
    "same-axis": _same_axis_points,
    "random": _random_points,
    "fractional": _fractional_stress_points,
}

STRESS_SCENARIOS = list(SCENARIOS.keys())


# ---------------------------------------------------------------------------
# Cursor position test
# ---------------------------------------------------------------------------

def run_cursor_test(
    scenario: str,
    backend: str,
    verbose: bool = False,
) -> ScenarioResult:
    """Move cursor to API coords, verify screen position via xdotool."""
    from x11_mcp.screenshot import take_screenshot
    from x11_mcp.scaling import get_state
    from x11_mcp.input import set_input_backend, get_input_device

    set_input_backend(backend)

    # Initialize scaling by taking a screenshot
    take_screenshot(mode="fullscreen")
    state = get_state()
    api_w, api_h = state.api_size

    if verbose:
        print(f"  Scaling: screen={state.screen_size}, api={state.api_size}, offset={state.monitor_offset}")

    gen = SCENARIOS.get(scenario)
    if gen is None:
        return ScenarioResult(scenario=scenario, backend=backend, notes=f"Unknown scenario: {scenario}")
    test_points = gen(api_w, api_h)

    t0 = time.monotonic()
    points = []

    for name, api_x, api_y in test_points:
        expected_sx, expected_sy = state.api_to_screen(api_x, api_y)

        dev = get_input_device()
        dev.move(api_x, api_y)
        actual_sx, actual_sy = poll_cursor(expected_sx, expected_sy)

        error = ((actual_sx - expected_sx) ** 2 + (actual_sy - expected_sy) ** 2) ** 0.5

        if verbose:
            dx = actual_sx - expected_sx
            dy = actual_sy - expected_sy
            status = f"OK({error:.1f}px)" if error <= 2 else f"DRIFT({error:.1f}px dx={dx:+d} dy={dy:+d})"
            print(f"    {name}: API({api_x},{api_y}) -> expect({expected_sx},{expected_sy}) actual({actual_sx},{actual_sy}) {status}")

        points.append(PointResult(
            name=name,
            api_x=api_x, api_y=api_y,
            expected_screen_x=expected_sx, expected_screen_y=expected_sy,
            actual_screen_x=actual_sx, actual_screen_y=actual_sy,
            error_px=round(error, 1),
        ))

    duration = time.monotonic() - t0
    return _compute_stats(ScenarioResult(
        scenario=scenario, backend=backend, points=points, duration=duration,
    ))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _compute_stats(result: ScenarioResult) -> ScenarioResult:
    if not result.points:
        return result

    errors = [p.error_px for p in result.points]
    dx_vals = [p.actual_screen_x - p.expected_screen_x for p in result.points]
    dy_vals = [p.actual_screen_y - p.expected_screen_y for p in result.points]

    result.mean_error = round(sum(errors) / len(errors), 1)
    result.max_error = round(max(errors), 1)
    result.bias_x = round(sum(dx_vals) / len(dx_vals), 2)
    result.bias_y = round(sum(dy_vals) / len(dy_vals), 2)

    sorted_errors = sorted(errors)
    result.p50_error = sorted_errors[len(sorted_errors) // 2]
    result.p95_error = sorted_errors[int(len(sorted_errors) * 0.95)] if len(sorted_errors) >= 2 else sorted_errors[-1]

    return result


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(results: list[ScenarioResult]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("x11-mcp Click Accuracy Report")
    lines.append("=" * 80)

    all_errors = []
    all_dx = []
    all_dy = []
    failures = []
    worst_points = []

    for r in results:
        hit_count = sum(1 for p in r.points if p.error_px <= 2)
        total = len(r.points)
        rate = (hit_count / total * 100) if total else 0
        status = "PASS" if total > 0 and rate >= 80 else "FAIL" if total > 0 else "SKIP"

        lines.append(f"\n  [{status}] {r.scenario} ({r.backend})")
        if r.notes:
            lines.append(f"    {r.notes}")
        lines.append(f"    {hit_count}/{total} within 2px | "
                     f"avg={r.mean_error}px max={r.max_error}px | "
                     f"bias: dx={r.bias_x:+.2f} dy={r.bias_y:+.2f}")

        if status == "FAIL":
            failures.append(f"{r.scenario}/{r.backend}")

        for p in r.points:
            dx = p.actual_screen_x - p.expected_screen_x
            dy = p.actual_screen_y - p.expected_screen_y
            all_errors.append(p.error_px)
            all_dx.append(dx)
            all_dy.append(dy)
            worst_points.append((p.error_px, r.scenario, r.backend, p))

    worst_points.sort(key=lambda x: -x[0])
    lines.append("")
    lines.append("=" * 80)
    lines.append("  WORST CASES:")
    lines.append("-" * 80)
    for err, scenario, backend, p in worst_points[:10]:
        dx = p.actual_screen_x - p.expected_screen_x
        dy = p.actual_screen_y - p.expected_screen_y
        lines.append(
            f"    {err:6.1f}px  {scenario}/{backend} {p.name}  "
            f"dx={dx:+d} dy={dy:+d}"
        )

    lines.append("")
    lines.append("-" * 80)
    if all_errors:
        sorted_e = sorted(all_errors)
        total_within_2 = sum(1 for e in sorted_e if e <= 2)
        p50 = sorted_e[len(sorted_e) // 2]
        p95 = sorted_e[int(len(sorted_e) * 0.95)]
        p99 = sorted_e[int(len(sorted_e) * 0.99)]

        lines.append(f"  TOTAL: {total_within_2}/{len(all_errors)} within 2px across {len(results)} scenarios")
        lines.append(f"  P50: {p50:.1f}px | P95: {p95:.1f}px | P99: {p99:.1f}px | MAX: {max(all_errors):.1f}px")

        if failures:
            lines.append(f"  FAILED: {', '.join(failures)}")

        mean_dx = sum(all_dx) / len(all_dx)
        mean_dy = sum(all_dy) / len(all_dy)
        lines.append(f"\n  SYSTEMATIC BIAS: dx={mean_dx:+.2f}px dy={mean_dy:+.2f}px")
        if abs(mean_dx) < 0.5 and abs(mean_dy) < 0.5:
            lines.append(f"    -> NONE (sub-pixel)")
        elif abs(mean_dx) <= 1.5 and abs(mean_dy) <= 1.5:
            lines.append(f"    -> MINIMAL (1px rounding)")
        else:
            lines.append(f"    -> SIGNIFICANT — investigate")

        verdict = ("EXCELLENT" if total_within_2 == len(all_errors) and p99 <= 3
                   else "GOOD" if total_within_2 / len(all_errors) >= 0.95 and p95 <= 5
                   else "FAIR" if total_within_2 / len(all_errors) >= 0.80
                   else "POOR")
        lines.append(f"\n  VERDICT: {verdict}")

    lines.append("=" * 80)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="x11-mcp accuracy test")
    parser.add_argument("--scenario", default="grid", choices=list(SCENARIOS.keys()) + ["all"])
    parser.add_argument("--backend", default="uinput", choices=["uinput", "xdotool", "both"])
    parser.add_argument("--stress", action="store_true", help="Run all scenarios")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--report", help="Save JSON report to file")
    args = parser.parse_args()

    backends = ["uinput", "xdotool"] if args.backend == "both" else [args.backend]
    scenarios = STRESS_SCENARIOS if args.stress or args.scenario == "all" else [args.scenario]

    results = []
    for backend in backends:
        for scenario in scenarios:
            label = f"{scenario}/{backend}"
            print(f"  {label}...", end=" ", flush=True)

            result = run_cursor_test(scenario, backend, verbose=args.verbose)

            within_2 = sum(1 for p in result.points if p.error_px <= 2)
            print(f"{within_2}/{len(result.points)} within 2px (avg={result.mean_error}px max={result.max_error}px)")
            results.append(result)

    report = format_report(results)
    print(report)

    if args.report:
        data = []
        for r in results:
            data.append({
                "scenario": r.scenario, "backend": r.backend,
                "mean_error": r.mean_error, "max_error": r.max_error,
                "p50": r.p50_error, "p95": r.p95_error,
                "bias": [r.bias_x, r.bias_y],
                "points": [{
                    "name": p.name,
                    "api": [p.api_x, p.api_y],
                    "expected": [p.expected_screen_x, p.expected_screen_y],
                    "actual": [p.actual_screen_x, p.actual_screen_y],
                    "error": p.error_px,
                } for p in r.points],
            })
        with open(args.report, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nReport saved: {args.report}")

    total = sum(len(r.points) for r in results)
    within_2 = sum(1 for r in results for p in r.points if p.error_px <= 2)
    sys.exit(0 if total > 0 and within_2 / total >= 0.9 else 1)


if __name__ == "__main__":
    main()
