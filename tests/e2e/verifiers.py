"""Verification functions for E2E test specs.

Each verifier takes an AgentOutput-like object and a check dict,
returns a CheckResult indicating pass/fail with a message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class AgentOutput(Protocol):
    text: str
    errored: bool
    has_images: bool


@dataclass
class CheckResult:
    passed: bool
    check_type: str
    message: str


def _output_contains(output: AgentOutput, check: dict) -> CheckResult:
    value = check["value"]
    text = output.text
    case_sensitive = check.get("case_sensitive", True)
    if not case_sensitive:
        text = text.lower()
        value = value.lower()
    passed = value in text
    return CheckResult(
        passed=passed,
        check_type="output_contains",
        message=f"Found '{check['value']}'" if passed else f"'{check['value']}' not found in output",
    )


def _output_not_contains(output: AgentOutput, check: dict) -> CheckResult:
    value = check["value"]
    text = output.text
    case_sensitive = check.get("case_sensitive", True)
    if not case_sensitive:
        text = text.lower()
        value = value.lower()
    passed = value not in text
    return CheckResult(
        passed=passed,
        check_type="output_not_contains",
        message=f"'{check['value']}' correctly absent" if passed else f"'{check['value']}' found in output",
    )


def _output_matches(output: AgentOutput, check: dict) -> CheckResult:
    pattern = check["pattern"]
    passed = bool(re.search(pattern, output.text))
    return CheckResult(
        passed=passed,
        check_type="output_matches",
        message=f"Pattern matched" if passed else f"Pattern '{pattern}' not found",
    )


def _screenshot_returned(output: AgentOutput, check: dict) -> CheckResult:
    expected = check.get("value", True)
    passed = output.has_images == expected
    return CheckResult(
        passed=passed,
        check_type="screenshot_returned",
        message=f"Images present: {output.has_images}" if passed else f"Expected images={expected}, got {output.has_images}",
    )


def _exit_clean(output: AgentOutput, check: dict) -> CheckResult:
    passed = not output.errored
    return CheckResult(
        passed=passed,
        check_type="exit_clean",
        message="Agent exited cleanly" if passed else "Agent errored",
    )


_VERIFIERS = {
    "output_contains": _output_contains,
    "output_not_contains": _output_not_contains,
    "output_matches": _output_matches,
    "screenshot_returned": _screenshot_returned,
    "exit_clean": _exit_clean,
}


def run_verification(check: dict, output: Any) -> CheckResult:
    """Run a single verification check against agent output."""
    check_type = check.get("type", "")
    verifier = _VERIFIERS.get(check_type)
    if verifier is None:
        return CheckResult(
            passed=False,
            check_type=check_type,
            message=f"Unknown verification type: '{check_type}'",
        )
    return verifier(output, check)
