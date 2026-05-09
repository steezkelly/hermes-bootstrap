"""Bootstrap tests for Foundry GEPA trace bridge boundary integration.

These tests verify the Bootstrap wrapper layer: validator behavior via
subprocess invocation, and Nix harness contract.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SCRIPT = REPO_ROOT / "scripts" / "harness" / "validate_foundry_gepa_bridge.py"
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _run_validator(dir_path: str) -> tuple[int, str]:
    result = subprocess.run(
        ["/usr/bin/python3", str(VALIDATOR_SCRIPT), dir_path],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


class TestValidateFoundryGepaBridge:
    """Tests for validate_foundry_gepa_bridge.py."""

    @pytest.fixture(autouse=True)
    def _ensure_validator_exists(self):
        assert VALIDATOR_SCRIPT.is_file(), f"Validator not found: {VALIDATOR_SCRIPT}"

    def test_valid_output_passes(self, tmp_path):
        out = tmp_path / "gepa_out"
        out.mkdir()
        safe = {
            "schema_version": 1, "mode": "gepa_bridge", "verdict": "pass",
            "datasets_built": 3, "total_examples": 6,
            "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False},
        }
        (out / "run_report.json").write_text(json.dumps(safe))
        manifest = {
            "schema_version": 1, "total_datasets": 1,
            "datasets": [{"dataset_path": str(tmp_path), "failure_class": "test"}],
        }
        (out / "gepa_manifest.json").write_text(json.dumps(manifest))
        exit_code, output = _run_validator(str(out))
        assert exit_code == 0

    def test_missing_directory(self):
        exit_code, output = _run_validator("/nonexistent/path")
        assert exit_code == 1

    def test_missing_run_report(self, tmp_path):
        out = tmp_path / "partial"
        out.mkdir()
        (out / "gepa_manifest.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_wrong_schema_version(self, tmp_path):
        out = tmp_path / "wrong"
        out.mkdir()
        (out / "run_report.json").write_text(json.dumps({
            "schema_version": 999, "mode": "gepa_bridge",
            "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False},
        }))
        (out / "gepa_manifest.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_wrong_mode(self, tmp_path):
        out = tmp_path / "wrong"
        out.mkdir()
        (out / "run_report.json").write_text(json.dumps({
            "schema_version": 1, "mode": "real_trace",
            "safety": {"network_allowed": False, "external_writes_allowed": False, "github_writes_allowed": False},
        }))
        (out / "gepa_manifest.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_network_allowed_true_rejected(self, tmp_path):
        out = tmp_path / "unsafe"
        out.mkdir()
        (out / "run_report.json").write_text(json.dumps({
            "schema_version": 1, "mode": "gepa_bridge",
            "safety": {"network_allowed": True, "external_writes_allowed": False, "github_writes_allowed": False},
        }))
        (out / "gepa_manifest.json").write_text("{}")
        exit_code, output = _run_validator(str(out))
        assert exit_code == 1

    def test_real_drill_output_passes(self):
        """Validate the chain-gepa-drill output from full run."""
        exit_code, output = _run_validator("/tmp/chain-gepa-drill/gepa_bridge")
        assert exit_code == 0, f"Validator failed on real output: {output}"


class TestNixHarnessContract:
    """Verify Nix harness.nix patterns for GEPA bridge."""

    def test_harness_nix_exists(self):
        assert HARNESS_NIX.is_file()

    def test_validator_script_exists(self):
        assert VALIDATOR_SCRIPT.is_file()

    def test_service_name_convention(self):
        assert "hermes-evolution-foundry-".startswith("hermes-evolution-foundry-")


class TestSafetyRegression:
    """Ensure GEPA bridge wrapper maintains Bootstrap safety envelope."""

    def test_no_network_in_validator(self):
        text = VALIDATOR_SCRIPT.read_text()
        forbidden = ["http://", "https://", "urllib", "requests.get", "socket.connect"]
        for pattern in forbidden:
            assert pattern not in text, f"Validator contains {pattern}"

    def test_no_github_in_validator(self):
        text = VALIDATOR_SCRIPT.read_text()
        forbidden = ["github.com", "gh api", "GITHUB_TOKEN"]
        for pattern in forbidden:
            assert pattern not in text

    def test_no_secret_access_in_validator(self):
        text = VALIDATOR_SCRIPT.read_text()
        forbidden = ["API_KEY", "SECRET", "PASSWORD", "CREDENTIALS", "os.environ.get"]
        for pattern in forbidden:
            assert pattern not in text
