"""Tests for the manual Hermes session-end Foundry ingestion hook.

The service remains default-off/manual-only.  It exports the most recent
Hermes session to a temp JSONL and ingests it through the same Foundry
real-trace path as the existing manual REAL_TRACE_SOURCE wrapper.
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
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "harness" / "export_and_ingest_last_session.py"
VALIDATOR_SCRIPT = REPO_ROOT / "scripts" / "harness" / "validate_session_end_ingest.py"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _service_block(name: str) -> str:
    text = _harness_text()
    svc_name = f"systemd.services.{name}"
    start = text.index(svc_name)
    end = text.find("systemd.", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_session_end_export_script_exists():
    assert EXPORT_SCRIPT.is_file()


def test_session_end_export_script_uses_hermes_sessions_export_to_temp_jsonl():
    text = EXPORT_SCRIPT.read_text()
    assert "tempfile" in text
    assert "sessions" in text
    assert "export" in text
    assert "hermes sessions export" in text


def test_session_end_export_script_invokes_real_trace_ingestion_path():
    text = EXPORT_SCRIPT.read_text()
    assert "evolution.core.real_trace_ingestion" in text
    assert "--mode" in text and "real_trace" in text
    assert "--no-network" in text
    assert "--no-external-writes" in text


def test_session_end_nix_binding_exists():
    text = _harness_text()
    assert "sessionEndIngest" in text
    assert 'name = "hermes-session-end-ingest"' in text
    assert "export_and_ingest_last_session.py" in text


def test_session_end_binding_exports_hermes_state_home_without_secrets():
    text = _harness_text()
    assert "HERMES_HOME=/var/lib/hermes/.hermes" in text
    assert "HERMES_CONFIG" not in text
    assert "EnvironmentFile" not in _service_block("hermes-session-end-ingest")


def test_session_end_service_is_manual_default_off():
    text = _harness_text()
    assert "systemd.services.hermes-session-end-ingest" in text
    assert "systemd.timers.hermes-session-end-ingest" not in text

    block = _service_block("hermes-session-end-ingest")
    assert "wantedBy" not in block
    assert 'Type = "oneshot"' not in block  # inherited from commonServiceConfig


def test_session_end_service_has_no_network_or_github_write_path():
    block = _service_block("hermes-session-end-ingest")
    assert "http" not in block
    assert "github.com" not in block
    assert "GITHUB_TOKEN" not in block
    assert "EnvironmentFile" not in block
    assert "gh pr" not in block


def test_session_end_service_boundaries_match_foundry_wrappers():
    block = _service_block("hermes-session-end-ingest")
    assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ]' in block
    assert "ReadOnlyPaths = lib.mkForce" in block
    assert '"/var/lib/hermes/foundry"' in block
    assert '"/var/lib/hermes/.hermes/sessions"' in block
    assert "InaccessiblePaths = lib.mkForce" in block
    assert '"-/var/lib/hermes/secrets"' in block
    assert '"-/var/lib/hermes/.hermes/.env"' in block


def test_session_end_validator_script_exists():
    assert VALIDATOR_SCRIPT.is_file()


def test_session_end_validator_checks_exported_jsonl_and_ingestion_report():
    text = VALIDATOR_SCRIPT.read_text()
    assert "json.loads" in text
    assert "run_report.json" in text
    assert "external_writes_allowed" in text


def test_session_end_validator_accepts_safe_output(tmp_path: Path):
    export_path = tmp_path / "export.jsonl"
    export_path.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "run_report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "real_trace",
                "external_writes_allowed": False,
                "safety": {"external_writes_allowed": False},
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), str(export_path), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_session_end_validator_rejects_external_writes_true(tmp_path: Path):
    export_path = tmp_path / "export.jsonl"
    export_path.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "run_report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "real_trace",
                "external_writes_allowed": True,
                "safety": {"external_writes_allowed": True},
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), str(export_path), str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "external_writes_allowed" in result.stderr


def test_existing_foundry_services_unchanged():
    real_trace_existing_services_unchanged()
    test_real_trace_service_is_manual_default_off()
    test_real_trace_service_wraps_foundry_safely()
    test_real_trace_service_no_network()
    test_real_trace_service_no_github()
    test_real_trace_validator_service_is_readonly()
