"""Tests for Foundry pipeline-runner wrapper + validator services.

Follows the static service-wiring TDD pattern: Bootstrap only wires safe local
execution and validates mechanical boundaries. Foundry owns pipeline verdicts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_foundry_real_trace_ingestion_wrapper import (
    test_existing_services_unchanged as real_trace_existing_services_unchanged,
    test_real_trace_service_is_manual_default_off,
    test_real_trace_service_no_github,
    test_real_trace_service_no_network,
    test_real_trace_service_wraps_foundry_safely,
    test_real_trace_validator_service_is_readonly,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"
VALIDATOR = REPO_ROOT / "scripts" / "harness" / "validate_foundry_pipeline_runner.py"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _service_block(name: str) -> str:
    text = _harness_text()
    svc_name = f"systemd.services.{name}"
    svc_start = text.index(svc_name)
    svc_end = text.find("systemd.", svc_start + 1)
    return text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]


def _binding_block(name: str) -> str:
    text = _harness_text()
    binding_start = text.index(f"  {name} = pkgs.writeShellApplication")
    binding_end = text.find("  };", binding_start) + len("  };")
    return text[binding_start:binding_end]


# ---------------------------------------------------------------------------
# Pipeline runner writeShellApplication
# ---------------------------------------------------------------------------


def test_pipeline_runner_nix_binding_exists():
    text = _harness_text()
    assert "foundryPipelineRunner" in text
    assert 'name = "hermes-evolution-foundry-pipeline-runner"' in text


def test_pipeline_runner_nix_binding_calls_correct_module():
    binding = _binding_block("foundryPipelineRunner")
    assert "evolution.core.pipeline_runner" in binding
    assert "--no-network" in binding
    assert "--no-external-writes" in binding


def test_pipeline_runner_nix_binding_supports_fixture_mode_default():
    binding = _binding_block("foundryPipelineRunner")
    assert "mode=\"''${FOUNDRY_PIPELINE_MODE:-fixture}\"" in binding
    assert '--mode "$mode"' in binding


def test_pipeline_runner_nix_binding_supports_real_trace_mode_with_optional_trace():
    binding = _binding_block("foundryPipelineRunner")
    assert "trace=\"''${FOUNDRY_PIPELINE_TRACE:-}\"" in binding
    assert 'if [ "$mode" = "real_trace" ]; then' in binding
    assert '--trace "$trace"' in binding


def test_pipeline_runner_nix_binding_rejects_invalid_mode():
    binding = _binding_block("foundryPipelineRunner")
    assert 'fixture|real_trace' in binding
    assert "Unsupported FOUNDRY_PIPELINE_MODE" in binding


def test_pipeline_runner_nix_binding_requires_trace_file_for_real_trace_mode():
    binding = _binding_block("foundryPipelineRunner")
    assert "FOUNDRY_PIPELINE_TRACE is required" in binding
    assert 'if [ ! -f "$trace" ]; then' in binding


def test_pipeline_runner_nix_binding_writes_pipeline_runner_output_path():
    binding = _binding_block("foundryPipelineRunner")
    assert "/var/lib/hermes/reports/evolution/pipeline-runner" in binding


def test_pipeline_runner_nix_binding_uses_local_foundry_checkout_only():
    binding = _binding_block("foundryPipelineRunner")
    assert "foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution" in binding
    assert 'cd "$foundry_repo"' in binding
    assert "git clone" not in binding
    assert "git pull" not in binding


def test_pipeline_runner_nix_binding_has_no_external_write_tools():
    binding = _binding_block("foundryPipelineRunner")
    assert "gh " not in binding
    assert "github" not in binding.lower()
    assert "curl" not in binding
    assert "GITHUB_TOKEN" not in binding


# ---------------------------------------------------------------------------
# Validator writeShellApplication + service
# ---------------------------------------------------------------------------


def test_pipeline_runner_validator_python_script_exists():
    assert VALIDATOR.is_file()


def test_pipeline_runner_validator_nix_binding_exists():
    text = _harness_text()
    assert "validateFoundryPipelineRunner" in text
    assert 'name = "hermes-validate-foundry-pipeline-runner"' in text


def test_pipeline_runner_validator_nix_binding_calls_validator_script():
    binding = _binding_block("validateFoundryPipelineRunner")
    assert "validate_foundry_pipeline_runner.py" in binding
    assert "/var/lib/hermes/reports/evolution/pipeline-runner" in binding
    assert "curl" not in binding
    assert "gh " not in binding


def test_pipeline_runner_validator_checks_expected_file_and_fields():
    text = VALIDATOR.read_text()
    assert "pipeline_run.json" in text
    assert "schema_version" in text
    assert "external_writes_allowed" in text
    assert "child_reports" in text
    assert "safety" in text


# ---------------------------------------------------------------------------
# Pipeline runner service is manual/default-off and safely bounded
# ---------------------------------------------------------------------------


def test_pipeline_runner_service_is_manual_default_off():
    text = _harness_text()
    svc_name = "systemd.services.hermes-evolution-foundry-pipeline-runner"
    timer_name = "systemd.timers.hermes-evolution-foundry-pipeline-runner"

    assert svc_name in text
    assert timer_name not in text

    svc_block = _service_block("hermes-evolution-foundry-pipeline-runner")
    assert "wantedBy" not in svc_block


def test_pipeline_runner_service_wraps_foundry_safely():
    svc_block = _service_block("hermes-evolution-foundry-pipeline-runner")

    assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/pipeline-runner" ]' in svc_block
    assert "ReadOnlyPaths" in svc_block
    assert '"/var/lib/hermes/foundry"' in svc_block
    assert '"/var/lib/hermes/.hermes/sessions"' in svc_block
    assert "InaccessiblePaths" in svc_block
    assert '"-/var/lib/hermes/secrets"' in svc_block
    assert '"-/var/lib/hermes/.hermes/.env"' in svc_block
    assert "EnvironmentFile" not in svc_block


def test_pipeline_runner_service_no_network():
    svc_block = _service_block("hermes-evolution-foundry-pipeline-runner")

    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_pipeline_runner_service_no_github():
    svc_block = _service_block("hermes-evolution-foundry-pipeline-runner")

    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block
    assert "gh pr" not in svc_block


def test_pipeline_runner_activation_creates_output_directory():
    text = _harness_text()
    assert "/var/lib/hermes/reports/evolution/pipeline-runner" in text
    assert "install -d" in text


# ---------------------------------------------------------------------------
# Validator service is read-only/manual/default-off
# ---------------------------------------------------------------------------


def test_pipeline_runner_validator_service_is_manual_default_off():
    text = _harness_text()
    svc_name = "systemd.services.hermes-validate-foundry-pipeline-runner"
    timer_name = "systemd.timers.hermes-validate-foundry-pipeline-runner"

    assert svc_name in text
    assert timer_name not in text

    svc_block = _service_block("hermes-validate-foundry-pipeline-runner")
    assert "wantedBy" not in svc_block


def test_pipeline_runner_validator_service_is_readonly():
    svc_block = _service_block("hermes-validate-foundry-pipeline-runner")

    assert "ReadWritePaths = lib.mkForce [ ]" in svc_block
    assert '"/var/lib/hermes/reports/evolution/pipeline-runner"' in svc_block


def test_pipeline_runner_validator_service_no_network():
    svc_block = _service_block("hermes-validate-foundry-pipeline-runner")

    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_pipeline_runner_validator_service_no_github():
    svc_block = _service_block("hermes-validate-foundry-pipeline-runner")

    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block


# ---------------------------------------------------------------------------
# Validator behavior
# ---------------------------------------------------------------------------


def _write_pipeline_run(out_dir: Path, **overrides: object) -> Path:
    out_dir.mkdir()
    payload = {
        "schema_version": 1,
        "mode": "fixture",
        "task_type": "pipeline_runner",
        "external_writes_allowed": False,
        "child_reports": [
            {
                "name": "action_routing_demo",
                "run_report": "/var/lib/hermes/reports/evolution/pipeline-runner/action_routing_demo/run_report.json",
                "verdict": "pass",
            }
        ],
        "safety": {
            "external_writes_allowed": False,
            "github_writes_allowed": False,
            "network_allowed": False,
            "production_mutation_allowed": False,
        },
        "verdict": "pass",
    }
    payload.update(overrides)
    path = out_dir / "pipeline_run.json"
    path.write_text(json.dumps(payload))
    return path


def _run_validator(out_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_pipeline_runner_validator_accepts_safe_child_reports_output(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    _write_pipeline_run(out_dir)

    result = _run_validator(out_dir)

    assert result.returncode == 0, result.stderr


def test_pipeline_runner_validator_accepts_foundry_reports_alias(tmp_path: Path):
    """Foundry #17 emits reports; accept it as the child-report array alias."""
    out_dir = tmp_path / "pipeline-runner"
    path = _write_pipeline_run(out_dir)
    payload = json.loads(path.read_text())
    payload["reports"] = payload.pop("child_reports")
    path.write_text(json.dumps(payload))

    result = _run_validator(out_dir)

    assert result.returncode == 0, result.stderr


def test_pipeline_runner_validator_rejects_missing_pipeline_run(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    out_dir.mkdir()

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "missing expected file" in result.stderr


def test_pipeline_runner_validator_rejects_invalid_json(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    out_dir.mkdir()
    (out_dir / "pipeline_run.json").write_text("{not-json")

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "invalid JSON" in result.stderr


def test_pipeline_runner_validator_rejects_non_object_json(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    out_dir.mkdir()
    (out_dir / "pipeline_run.json").write_text("[]")

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "must be an object" in result.stderr


def test_pipeline_runner_validator_rejects_schema_version_zero(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    _write_pipeline_run(out_dir, schema_version=0)

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "schema_version" in result.stderr


def test_pipeline_runner_validator_rejects_external_writes_true(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    _write_pipeline_run(out_dir, external_writes_allowed=True)

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "external_writes_allowed" in result.stderr


def test_pipeline_runner_validator_rejects_missing_child_reports_array(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    path = _write_pipeline_run(out_dir)
    payload = json.loads(path.read_text())
    payload.pop("child_reports")
    path.write_text(json.dumps(payload))

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "child_reports" in result.stderr


def test_pipeline_runner_validator_rejects_child_reports_not_array(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    _write_pipeline_run(out_dir, child_reports={"not": "a list"})

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "child_reports" in result.stderr


def test_pipeline_runner_validator_rejects_missing_safety_section(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    path = _write_pipeline_run(out_dir)
    payload = json.loads(path.read_text())
    payload.pop("safety")
    path.write_text(json.dumps(payload))

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "safety" in result.stderr


def test_pipeline_runner_validator_rejects_safety_not_object(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    _write_pipeline_run(out_dir, safety=[])

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "safety" in result.stderr


def test_pipeline_runner_validator_rejects_network_allowed_true(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    safety = {
        "external_writes_allowed": False,
        "github_writes_allowed": False,
        "network_allowed": True,
        "production_mutation_allowed": False,
    }
    _write_pipeline_run(out_dir, safety=safety)

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "network_allowed" in result.stderr


def test_pipeline_runner_validator_rejects_github_writes_allowed_true(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    safety = {
        "external_writes_allowed": False,
        "github_writes_allowed": True,
        "network_allowed": False,
        "production_mutation_allowed": False,
    }
    _write_pipeline_run(out_dir, safety=safety)

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "github_writes_allowed" in result.stderr


def test_pipeline_runner_validator_rejects_production_mutation_allowed_true(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    safety = {
        "external_writes_allowed": False,
        "github_writes_allowed": False,
        "network_allowed": False,
        "production_mutation_allowed": True,
    }
    _write_pipeline_run(out_dir, safety=safety)

    result = _run_validator(out_dir)

    assert result.returncode == 1
    assert "production_mutation_allowed" in result.stderr


def test_pipeline_runner_validator_does_not_judge_verdict_correctness(tmp_path: Path):
    out_dir = tmp_path / "pipeline-runner"
    _write_pipeline_run(out_dir, verdict="fail")

    result = _run_validator(out_dir)

    assert result.returncode == 0, result.stderr


def test_pipeline_runner_validator_usage_requires_output_dir():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Usage:" in result.stderr


# ---------------------------------------------------------------------------
# Existing services unchanged
# ---------------------------------------------------------------------------


def test_existing_services_unchanged():
    real_trace_existing_services_unchanged()
    test_real_trace_service_is_manual_default_off()
    test_real_trace_service_wraps_foundry_safely()
    test_real_trace_service_no_network()
    test_real_trace_service_no_github()
    test_real_trace_validator_service_is_readonly()
