"""Tests for Foundry attention-router bridge wrapper + validator services.

Follows the TDD service-wiring pattern: tests first, manual/default-off
systemd services, no network/GitHub, and bootstrap-only mechanical boundary
validation.
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
VALIDATOR = REPO_ROOT / "scripts" / "harness" / "validate_foundry_attention_router_bridge.py"


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
# Nix binding exists
# ---------------------------------------------------------------------------


def test_attention_router_bridge_nix_binding_exists():
    text = _harness_text()
    assert "foundryAttentionRouterBridge" in text
    assert 'name = "hermes-evolution-foundry-attention-router-bridge"' in text


def test_attention_router_bridge_nix_binding_calls_correct_module():
    text = _harness_text()
    assert "evolution.core.attention_router_bridge" in text
    assert "--mode attention_router_bridge" in text
    assert "--no-network" in text
    assert "--no-external-writes" in text


def test_attention_router_bridge_nix_binding_reads_real_trace_report():
    text = _harness_text()
    assert "--input /var/lib/hermes/reports/evolution/real-trace-ingestion" in text
    assert "/var/lib/hermes/reports/evolution/attention-router-bridge" in text


def test_attention_router_bridge_nix_binding_has_no_external_write_tools():
    binding = _binding_block("foundryAttentionRouterBridge")
    assert "gh " not in binding
    assert "github" not in binding.lower()
    assert "curl" not in binding
    assert "GITHUB_TOKEN" not in binding


def test_attention_router_bridge_nix_binding_checks_real_trace_report_first():
    binding = _binding_block("foundryAttentionRouterBridge")
    assert 'input=/var/lib/hermes/reports/evolution/real-trace-ingestion' in binding
    assert 'if [ ! -f "$input/run_report.json" ]; then' in binding
    assert "Real-trace ingestion report missing" in binding


def test_attention_router_bridge_nix_binding_uses_local_foundry_checkout():
    binding = _binding_block("foundryAttentionRouterBridge")
    assert "foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution" in binding
    assert 'cd "$foundry_repo"' in binding
    assert "git clone" not in binding
    assert "git pull" not in binding


# ---------------------------------------------------------------------------
# Bridge service is manual/default-off and safely bounded
# ---------------------------------------------------------------------------


def test_attention_router_bridge_service_is_manual_default_off():
    text = _harness_text()
    svc_name = "systemd.services.hermes-evolution-foundry-attention-router-bridge"
    timer_name = "systemd.timers.hermes-evolution-foundry-attention-router-bridge"

    assert svc_name in text
    assert timer_name not in text

    svc_block = _service_block("hermes-evolution-foundry-attention-router-bridge")
    assert "wantedBy" not in svc_block


def test_attention_router_bridge_service_wraps_foundry_safely():
    svc_block = _service_block("hermes-evolution-foundry-attention-router-bridge")

    assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/attention-router-bridge" ]' in svc_block
    assert "ReadOnlyPaths" in svc_block
    assert '"/var/lib/hermes/foundry"' in svc_block
    assert '"/var/lib/hermes/reports/evolution/real-trace-ingestion"' in svc_block
    assert "InaccessiblePaths" in svc_block
    assert "EnvironmentFile" not in svc_block


def test_attention_router_bridge_service_no_network():
    svc_block = _service_block("hermes-evolution-foundry-attention-router-bridge")

    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_attention_router_bridge_service_no_github():
    svc_block = _service_block("hermes-evolution-foundry-attention-router-bridge")

    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block
    assert "gh pr" not in svc_block


# ---------------------------------------------------------------------------
# Validator wiring and behavior
# ---------------------------------------------------------------------------


def test_attention_router_bridge_validator_python_script_exists():
    assert VALIDATOR.is_file()


def test_attention_router_bridge_validator_nix_binding_exists():
    text = _harness_text()
    assert "validateFoundryAttentionRouterBridge" in text
    assert 'name = "hermes-validate-foundry-attention-router-bridge"' in text


def test_attention_router_bridge_validator_nix_binding_calls_validator_script():
    binding = _binding_block("validateFoundryAttentionRouterBridge")
    assert "validate_foundry_attention_router_bridge.py" in binding
    assert "/var/lib/hermes/reports/evolution/attention-router-bridge" in binding
    assert "curl" not in binding
    assert "gh " not in binding


def test_attention_router_bridge_validator_service_is_manual_default_off():
    text = _harness_text()
    svc_name = "systemd.services.hermes-validate-foundry-attention-router-bridge"
    timer_name = "systemd.timers.hermes-validate-foundry-attention-router-bridge"

    assert svc_name in text
    assert timer_name not in text

    svc_block = _service_block("hermes-validate-foundry-attention-router-bridge")
    assert "wantedBy" not in svc_block


def test_attention_router_bridge_validator_checks_expected_files_exist():
    text = VALIDATOR.read_text()
    assert "run_report.json" in text
    assert "action_queue.json" in text
    assert "promotion_dossier.md" in text
    assert "artifact_manifest.json" in text


def test_attention_router_bridge_validator_checks_json_and_safety_fields():
    text = VALIDATOR.read_text()
    assert "json.loads" in text
    assert "schema_version" in text
    assert "external_writes_allowed" in text


def test_attention_router_bridge_validator_service_no_network():
    svc_block = _service_block("hermes-validate-foundry-attention-router-bridge")

    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_attention_router_bridge_validator_service_no_github():
    svc_block = _service_block("hermes-validate-foundry-attention-router-bridge")

    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block


def test_attention_router_bridge_validator_service_is_readonly():
    svc_block = _service_block("hermes-validate-foundry-attention-router-bridge")

    assert "ReadWritePaths = lib.mkForce [ ]" in svc_block
    assert '"/var/lib/hermes/reports/evolution/attention-router-bridge"' in svc_block


def _write_valid_bridge_output(out_dir: Path) -> None:
    out_dir.mkdir()
    (out_dir / "run_report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "attention_router_bridge",
                "safety": {
                    "external_writes_allowed": False,
                    "github_writes_allowed": False,
                    "network_allowed": False,
                    "production_mutation_allowed": False,
                },
            }
        )
    )
    (out_dir / "action_queue.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "attention_router_bridge",
                "external_writes_allowed": False,
                "items": [],
            }
        )
    )
    (out_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "attention_router_bridge",
                "external_writes_allowed": False,
                "review_required": True,
            }
        )
    )
    (out_dir / "promotion_dossier.md").write_text("# Attention-router bridge\n")


def test_attention_router_bridge_validator_accepts_safe_output(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_attention_router_bridge_validator_rejects_external_writes_true(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)
    (out_dir / "action_queue.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "attention_router_bridge",
                "external_writes_allowed": True,
                "items": [],
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "external_writes_allowed" in result.stderr


def test_attention_router_bridge_validator_rejects_missing_report(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)
    (out_dir / "run_report.json").unlink()

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "missing expected file" in result.stderr


def test_attention_router_bridge_validator_rejects_invalid_json(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)
    (out_dir / "artifact_manifest.json").write_text("{not-json")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid JSON" in result.stderr


def test_attention_router_bridge_validator_rejects_schema_version_zero(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)
    (out_dir / "run_report.json").write_text(
        json.dumps(
            {
                "schema_version": 0,
                "mode": "attention_router_bridge",
                "safety": {
                    "external_writes_allowed": False,
                    "github_writes_allowed": False,
                    "network_allowed": False,
                    "production_mutation_allowed": False,
                },
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "schema_version" in result.stderr


def test_attention_router_bridge_validator_rejects_wrong_mode(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)
    (out_dir / "action_queue.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "wrong_mode",
                "external_writes_allowed": False,
                "items": [],
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "attention_router_bridge" in result.stderr


def test_attention_router_bridge_validator_rejects_network_allowed_true(tmp_path: Path):
    out_dir = tmp_path / "attention-router-bridge"
    _write_valid_bridge_output(out_dir)
    (out_dir / "run_report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "attention_router_bridge",
                "safety": {
                    "external_writes_allowed": False,
                    "github_writes_allowed": False,
                    "network_allowed": True,
                    "production_mutation_allowed": False,
                },
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "network_allowed" in result.stderr


def test_attention_router_bridge_validator_usage_requires_output_dir():
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
