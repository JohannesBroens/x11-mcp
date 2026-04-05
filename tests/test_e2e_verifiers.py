"""Tests for E2E verification functions."""

from dataclasses import dataclass


@dataclass
class FakeOutput:
    text: str
    errored: bool = False
    has_images: bool = False


class TestOutputContains:
    def test_passes_when_present(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text='monitor: "DP-2", native_width: 2560')
        result = run_verification({"type": "output_contains", "value": "DP-2"}, out)
        assert result.passed

    def test_fails_when_absent(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="everything is fine")
        result = run_verification({"type": "output_contains", "value": "DP-2"}, out)
        assert not result.passed


class TestOutputNotContains:
    def test_passes_when_absent(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="all good")
        result = run_verification({"type": "output_not_contains", "value": "error"}, out)
        assert result.passed

    def test_fails_when_present(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="something went error here")
        result = run_verification({"type": "output_not_contains", "value": "error"}, out)
        assert not result.passed

    def test_case_insensitive(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="Error: something failed")
        result = run_verification(
            {"type": "output_not_contains", "value": "error", "case_sensitive": False}, out
        )
        assert not result.passed


class TestOutputMatches:
    def test_regex_match(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text='{"native_width": 2560}')
        result = run_verification(
            {"type": "output_matches", "pattern": r'"native_width":\s*2560'}, out
        )
        assert result.passed

    def test_regex_no_match(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text='{"native_width": 1920}')
        result = run_verification(
            {"type": "output_matches", "pattern": r'"native_width":\s*2560'}, out
        )
        assert not result.passed


class TestScreenshotReturned:
    def test_passes_when_images_present(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="ok", has_images=True)
        result = run_verification({"type": "screenshot_returned", "value": True}, out)
        assert result.passed

    def test_fails_when_no_images(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="ok", has_images=False)
        result = run_verification({"type": "screenshot_returned", "value": True}, out)
        assert not result.passed


class TestExitClean:
    def test_passes_when_no_error(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="done", errored=False)
        result = run_verification({"type": "exit_clean"}, out)
        assert result.passed

    def test_fails_when_errored(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="crash", errored=True)
        result = run_verification({"type": "exit_clean"}, out)
        assert not result.passed


class TestUnknownVerifier:
    def test_unknown_type_fails(self):
        from tests.e2e.verifiers import run_verification
        out = FakeOutput(text="ok")
        result = run_verification({"type": "nonexistent_check"}, out)
        assert not result.passed
        assert "Unknown" in result.message
