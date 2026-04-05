"""E2E test runner for x11-mcp.

Loads YAML test specs, executes them via sub-agents or direct MCP calls,
and verifies results.

Usage:
    python -m tests.e2e.runner [--tag TAG] [--spec NAME] [--verbose] [--report FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tests.e2e.verifiers import CheckResult, run_verification

SPECS_DIR = Path(__file__).parent / "specs"


@dataclass
class TestResult:
    name: str
    passed: bool
    checks: list[CheckResult]
    duration: float
    agent_output: str
    error: str = ""


def load_specs(
    specs_dir: str | None = None,
    tag: str | None = None,
    spec_name: str | None = None,
) -> list[dict]:
    """Load YAML test specs from directory, optionally filtering by tag or name."""
    directory = Path(specs_dir) if specs_dir else SPECS_DIR
    specs = []

    for path in sorted(directory.glob("*.yaml")):
        with open(path) as f:
            spec = yaml.safe_load(f)
        if spec is None:
            continue
        spec.setdefault("name", path.stem)
        spec.setdefault("tags", [])
        spec.setdefault("timeout", 30)
        spec.setdefault("verify", [])

        if spec_name and spec_name not in path.stem:
            continue

        if tag and tag not in spec.get("tags", []):
            continue

        specs.append(spec)

    return specs


def format_report(results: list[TestResult]) -> str:
    """Format test results into a human-readable report."""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("E2E Test Results")
    lines.append("=" * 60)

    for r in results:
        icon = "PASS" if r.passed else "FAIL"
        lines.append(f"  [{icon}] {r.name} ({r.duration:.1f}s)")
        for check in r.checks:
            check_icon = "  ok" if check.passed else "FAIL"
            lines.append(f"    [{check_icon}] {check.check_type}: {check.message}")
        if r.error:
            lines.append(f"    ERROR: {r.error}")

    lines.append("-" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_time = sum(r.duration for r in results)
    lines.append(f"  {passed} passed, {failed} failed in {total_time:.1f}s")
    lines.append("=" * 60)

    return "\n".join(lines)


def run_spec_direct(spec: dict) -> TestResult:
    """Run a spec via direct MCP tool calls (no sub-agent).

    This is the deterministic path for CI — executes tool calls
    programmatically based on the spec's task field.
    """
    from dataclasses import dataclass as _dc

    @_dc
    class DirectOutput:
        text: str = ""
        errored: bool = False
        has_images: bool = False

    t0 = time.monotonic()

    try:
        from x11_mcp.screenshot import take_screenshot
        from x11_mcp.window import list_windows, get_monitor_geometries

        output_parts = []
        task = spec.get("task", "")

        if "screenshot" in task.lower():
            b64, meta = take_screenshot(mode="fullscreen")
            output_parts.append(json.dumps(meta, indent=2))
            has_images = len(b64) > 0
        elif "list_windows" in task.lower() or "window" in task.lower():
            windows = list_windows()
            output_parts.append(json.dumps(windows, indent=2, default=str))
            has_images = False
        elif "monitor" in task.lower():
            monitors = get_monitor_geometries()
            output_parts.append(json.dumps(monitors, indent=2))
            has_images = False
        else:
            output_parts.append(f"Direct mode: unrecognized task pattern")
            has_images = False

        output = DirectOutput(
            text="\n".join(output_parts),
            errored=False,
            has_images=has_images,
        )

    except Exception as e:
        output = DirectOutput(text=str(e), errored=True, has_images=False)

    duration = time.monotonic() - t0

    checks = [run_verification(check, output) for check in spec.get("verify", [])]

    return TestResult(
        name=spec["name"],
        passed=all(c.passed for c in checks) and not output.errored,
        checks=checks,
        duration=duration,
        agent_output=output.text,
        error="" if not output.errored else output.text,
    )


def main():
    parser = argparse.ArgumentParser(description="x11-mcp E2E test runner")
    parser.add_argument("--tag", help="Filter specs by tag")
    parser.add_argument("--spec", help="Filter specs by name substring")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show agent output")
    parser.add_argument("--report", help="Save JSON report to file")
    parser.add_argument("--specs-dir", help="Custom specs directory")
    args = parser.parse_args()

    specs = load_specs(specs_dir=args.specs_dir, tag=args.tag, spec_name=args.spec)
    if not specs:
        print("No specs found matching criteria.")
        sys.exit(1)

    print(f"Running {len(specs)} E2E spec(s)...\n")

    results = []
    for spec in specs:
        print(f"  Running: {spec['name']}...", end=" ", flush=True)
        result = run_spec_direct(spec)
        results.append(result)
        print("PASS" if result.passed else "FAIL")

        if args.verbose and result.agent_output:
            print(f"    Output: {result.agent_output[:200]}")

    report = format_report(results)
    print(report)

    if args.report:
        report_data = [
            {
                "name": r.name,
                "passed": r.passed,
                "duration": r.duration,
                "checks": [{"type": c.check_type, "passed": c.passed, "message": c.message} for c in r.checks],
                "error": r.error,
            }
            for r in results
        ]
        with open(args.report, "w") as f:
            json.dump(report_data, f, indent=2)
        print(f"\nReport saved to {args.report}")

    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
