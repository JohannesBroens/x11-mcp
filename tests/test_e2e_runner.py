"""Tests for E2E runner spec loading and execution."""

from pathlib import Path

import yaml


class TestLoadSpecs:
    def test_loads_yaml_spec(self, tmp_path):
        from tests.e2e.runner import load_specs

        spec_file = tmp_path / "test.yaml"
        spec_file.write_text(yaml.dump({
            "name": "Test spec",
            "description": "A test",
            "tags": ["smoke"],
            "timeout": 10,
            "task": "Do something",
            "verify": [{"type": "exit_clean"}],
        }))

        specs = load_specs(str(tmp_path))
        assert len(specs) == 1
        assert specs[0]["name"] == "Test spec"
        assert specs[0]["tags"] == ["smoke"]

    def test_filters_by_tag(self, tmp_path):
        from tests.e2e.runner import load_specs

        for name, tags in [("a.yaml", ["smoke"]), ("b.yaml", ["slow"]), ("c.yaml", ["smoke", "slow"])]:
            (tmp_path / name).write_text(yaml.dump({
                "name": name, "tags": tags, "task": "x", "verify": [],
            }))

        specs = load_specs(str(tmp_path), tag="smoke")
        names = [s["name"] for s in specs]
        assert "a.yaml" in names
        assert "c.yaml" in names
        assert "b.yaml" not in names

    def test_filters_by_spec_name(self, tmp_path):
        from tests.e2e.runner import load_specs

        for name in ["00-screenshot.yaml", "01-window.yaml"]:
            (tmp_path / name).write_text(yaml.dump({
                "name": name, "tags": [], "task": "x", "verify": [],
            }))

        specs = load_specs(str(tmp_path), spec_name="00-screenshot")
        assert len(specs) == 1
        assert specs[0]["name"] == "00-screenshot.yaml"


class TestTestResult:
    def test_result_dataclass(self):
        from tests.e2e.runner import TestResult
        from tests.e2e.verifiers import CheckResult

        result = TestResult(
            name="test",
            passed=True,
            checks=[CheckResult(passed=True, check_type="exit_clean", message="ok")],
            duration=1.5,
            agent_output="done",
        )
        assert result.passed
        assert result.duration == 1.5


class TestFormatReport:
    def test_summary_format(self):
        from tests.e2e.runner import TestResult, format_report
        from tests.e2e.verifiers import CheckResult

        results = [
            TestResult("test1", True, [CheckResult(True, "exit_clean", "ok")], 1.0, ""),
            TestResult("test2", False, [CheckResult(False, "output_contains", "not found")], 2.0, ""),
        ]
        report = format_report(results)
        assert "1 passed" in report
        assert "1 failed" in report
        assert "test1" in report
        assert "test2" in report
