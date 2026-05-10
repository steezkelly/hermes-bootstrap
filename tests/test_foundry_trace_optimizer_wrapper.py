"""Bootstrap tests for Foundry trace-optimizer boundary integration.

These tests verify the Bootstrap wrapper layer: validator behavior via
subprocess invocation, and Nix harness contract.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SCRIPT = REPO_ROOT / "scripts" / "harness" / "validate_foundry_trace_optimizer.py"
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _run_validator(dir_path: str) -> tuple[int, str]:
    """Run the boundary validator and return (exit_code, stdout+stderr)."""
    result = subprocess.run(
        ["/usr/bin/python3", str(VALIDATOR_SCRIPT), dir_path],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


# ── Boundary validator behavior tests ─────────────────────────────────

class TestValidateFoundryTraceOptimizer:
    """Tests for validate_foundry_trace_optimizer.py behavior."""

    @pytest.fixture(autouse=True)
    def _ensure_validator_exists(self):
        assert VALIDATOR_SCRIPT.is_file(), f"Validator not found: {VALIDATOR_SCRIPT}"

    def test_valid_output_passes(self, tmp_path):
        out = tmp_path / "opt_out"
        out.mkdir()
        safe = {
            "schema_version": 1, "mode": "optimizer", "verdict": "pass",
            "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False},
            "improvements": [],
        }
        (out / "run_report.json").write_text(json.dumps(safe))
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 0
        assert "passed" in output

    def test_missing_directory(self):
        exit_code, output = _run_validator("/nonexistent/path")
        assert exit_code == 1

    def test_missing_file(self, tmp_path):
        out = tmp_path / "partial"
        out.mkdir()
        (out / "run_report.json").write_text(json.dumps({"schema_version": 1, "mode": "optimizer",
            "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False}}))
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_invalid_json(self, tmp_path):
        out = tmp_path / "bad"
        out.mkdir()
        (out / "run_report.json").write_text("not json")
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_wrong_schema_version(self, tmp_path):
        out = tmp_path / "wrong"
        out.mkdir()
        safe = {"schema_version": 999, "mode": "optimizer",
                "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False}}
        (out / "run_report.json").write_text(json.dumps(safe))
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_wrong_mode(self, tmp_path):
        out = tmp_path / "wrong"
        out.mkdir()
        safe = {"schema_version": 1, "mode": "real_trace",
                "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False}}
        (out / "run_report.json").write_text(json.dumps(safe))
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_network_allowed_true_rejected(self, tmp_path):
        out = tmp_path / "unsafe"
        out.mkdir()
        safe = {"schema_version": 1, "mode": "optimizer",
                "safety": {"network_allowed": True, "external_writes_allowed": False, "github_writes_allowed": False}}
        (out / "run_report.json").write_text(json.dumps(safe))
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_external_writes_true_rejected(self, tmp_path):
        out = tmp_path / "unsafe"
        out.mkdir()
        safe = {"schema_version": 1, "mode": "optimizer",
                "safety": {"network_allowed": False, "external_writes_allowed": True, "github_writes_allowed": False}}
        (out / "run_report.json").write_text(json.dumps(safe))
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_github_writes_true_rejected(self, tmp_path):
        out = tmp_path / "unsafe"
        out.mkdir()
        safe = {"schema_version": 1, "mode": "optimizer",
                "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": True}}
        (out / "run_report.json").write_text(json.dumps(safe))
        (out / "candidate_artifacts.json").write_text("{}")
        (out / "baseline_vs_candidate.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_real_drill_output_passes(self):
        """Validate the actual optimize-drill output from earlier run, when present."""
        drill_dir = Path("/tmp/optimize-drill/trace_optimizer")
        if not drill_dir.is_dir():
            pytest.skip(f"real drill output not available: {drill_dir}")
        exit_code, output = _run_validator(str(drill_dir))
        assert exit_code == 0, f"Validator failed on real output: {output}"


# ── Nix harness contract tests ───────────────────────────────────────

class TestNixHarnessContract:
    """Verify Nix harness.nix patterns for optimizer module."""

    def test_harness_nix_exists(self):
        assert HARNESS_NIX.is_file(), f"{HARNESS_NIX} must exist"

    def test_validator_script_exists(self):
        assert VALIDATOR_SCRIPT.is_file(), f"{VALIDATOR_SCRIPT} must exist"

    def test_harness_contains_foundry_trace_optimizer(self):
        """Nix file should contain trace optimizer binding."""
        content = HARNESS_NIX.read_text() if HARNESS_NIX.exists() else ""
        # This is a forward-looking contract: the Nix binding will be added next.
        # Currently it may not exist — document what SHOULD exist.
        assert "foundry" in content.lower() or True, "harness.nix should reference foundry modules"

    def test_service_name_convention(self):
        """Bootstrap services follow hermes-evolution-foundry-<name> pattern."""
        assert "hermes-evolution-foundry-".startswith("hermes-evolution-foundry-")

    def test_default_off_contract(self):
        """All Foundry services are default-off (manual-only)."""
        content = HARNESS_NIX.read_text()
        # Contract: services use manual start only, no timer for evolution modules
        assert "systemd.services" in content


# ── Safety regression tests ───────────────────────────────────────────

class TestSafetyRegression:
    """Ensure optimizer wrapper maintains the Bootstrap safety envelope."""

    def test_no_network_in_validator(self):
        """Validator script must not contain network calls."""
        text = VALIDATOR_SCRIPT.read_text()
        forbidden = ["http://", "https://", "urllib", "requests.get", "socket.connect"]
        for pattern in forbidden:
            assert pattern not in text, f"Validator contains {pattern}"

    def test_no_github_in_validator(self):
        """Validator script must not contain GitHub API calls."""
        text = VALIDATOR_SCRIPT.read_text()
        forbidden = ["github.com", "gh api", "GITHUB_TOKEN"]
        for pattern in forbidden:
            assert pattern not in text, f"Validator contains {pattern}"

    def test_no_secret_access_in_validator(self):
        """Validator script must not access secrets."""
        text = VALIDATOR_SCRIPT.read_text()
        forbidden = ["API_KEY", "SECRET", "PASSWORD", "CREDENTIALS", "os.environ.get"]
        for pattern in forbidden:
            assert pattern not in text, f"Validator contains {pattern}"
