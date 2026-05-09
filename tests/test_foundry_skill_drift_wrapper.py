from __future__ import annotations

from pathlib import Path

from test_foundry_service_contract import (
    test_foundry_dry_run_service_has_thin_boundary_permissions,
    test_foundry_dry_run_service_invokes_foundry_fixture_safely,
    test_foundry_dry_run_service_is_manual_default_off,
    test_foundry_report_directory_created_by_activation,
)
from test_foundry_checkout_provisioning import (
    test_foundry_provisioning_script_exists,
    test_foundry_provisioning_script_has_safe_name,
    test_foundry_provisioning_service_is_manual_default_off as prov_manual,
    test_foundry_provisioning_has_no_action_queue_logic,
    test_foundry_provisioning_has_no_gate_logic,
    test_foundry_provisioning_has_no_dossier_text,
    test_foundry_provisioning_has_no_network_in_service,
    test_foundry_provisioning_has_no_github_write_path,
)
from test_foundry_boundary_validation import (
    test_boundary_validator_nix_binding_exists,
    test_boundary_validator_python_script_exists,
    test_boundary_validator_service_is_manual_default_off as ar_val_off,
    test_boundary_validator_service_no_network as ar_val_nonet,
    test_boundary_validator_service_no_github as ar_val_nogh,
    test_boundary_validator_service_is_readonly as ar_val_ro,
)
from test_foundry_session_import_wrapper import (
    test_session_import_fixture_nix_binding_exists,
    test_session_import_service_is_manual_default_off,
    test_session_import_service_wraps_foundry_safely,
)
from test_foundry_session_import_validation import (
    test_si_validator_service_is_manual_default_off,
    test_si_validator_service_no_network,
    test_si_validator_service_no_github,
    test_si_validator_service_is_readonly,
)
from test_foundry_tool_underuse_wrapper import (
    test_tool_underuse_wrapper_nix_binding_exists,
    test_tool_underuse_wrapper_service_is_manual_default_off,
    test_tool_underuse_wrapper_service_safe,
    test_tool_underuse_wrapper_service_no_network,
    test_tool_underuse_wrapper_service_no_github,
    test_tool_underuse_validator_nix_binding_exists,
    test_tool_underuse_validator_python_script_exists,
    test_tool_underuse_validator_service_is_manual_default_off,
    test_tool_underuse_validator_service_no_network,
    test_tool_underuse_validator_service_no_github,
    test_tool_underuse_validator_service_is_readonly,
)
from test_foundry_weekly_timer import (
    test_weekly_timer_exists_in_harness,
    test_weekly_timer_targets_action_routing_fixture,
    test_weekly_timer_is_default_disabled,
    test_weekly_timer_has_no_network_credentials,
    test_weekly_timer_does_not_break_existing_timers,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"
VALIDATOR_PY = REPO_ROOT / "scripts" / "harness" / "validate_foundry_skill_drift_fixture.py"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _validator_text() -> str:
    return VALIDATOR_PY.read_text()


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------

def test_skill_drift_wrapper_nix_binding_exists():
    text = _harness_text()
    assert "foundrySkillDriftFixture" in text
    assert 'name = "hermes-evolution-foundry-skill-drift-fixture"' in text


def test_skill_drift_wrapper_nix_binding_calls_python():
    text = _harness_text()
    assert "evolution.core.skill_drift_demo" in text
    assert "/var/lib/hermes/reports/evolution/skill-drift-fixture" in text


def test_skill_drift_wrapper_service_is_manual_default_off():
    text = _harness_text()
    svc = "systemd.services.hermes-evolution-foundry-skill-drift-fixture"
    tmr = "systemd.timers.hermes-evolution-foundry-skill-drift-fixture"
    assert svc in text
    assert tmr not in text
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "wantedBy" not in block


def test_skill_drift_wrapper_service_safe():
    text = _harness_text()
    svc = "systemd.services.hermes-evolution-foundry-skill-drift-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ]' in block
    assert "ReadOnlyPaths" in block
    assert "InaccessiblePaths" in block


def test_skill_drift_wrapper_service_no_network():
    text = _harness_text()
    svc = "systemd.services.hermes-evolution-foundry-skill-drift-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "http" not in block


def test_skill_drift_wrapper_service_no_github():
    text = _harness_text()
    svc = "systemd.services.hermes-evolution-foundry-skill-drift-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "EnvironmentFile" not in block


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def test_skill_drift_validator_nix_binding_exists():
    text = _harness_text()
    assert "validateFoundrySkillDriftFixture" in text
    assert 'name = "hermes-validate-foundry-skill-drift-fixture"' in text


def test_skill_drift_validator_python_script_exists():
    assert VALIDATOR_PY.is_file()


def test_skill_drift_validator_service_is_manual_default_off():
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-skill-drift-fixture"
    tmr = "systemd.timers.hermes-validate-foundry-skill-drift-fixture"
    assert svc in text
    assert tmr not in text
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "wantedBy" not in block


def test_skill_drift_validator_checks_expected_files():
    vtext = _validator_text()
    assert "run_report.json" in vtext
    assert "skill_diff.txt" in vtext
    assert "artifact_manifest.json" in vtext


def test_skill_drift_validator_service_no_network():
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-skill-drift-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "http" not in block


def test_skill_drift_validator_service_no_github():
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-skill-drift-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "EnvironmentFile" not in block


def test_skill_drift_validator_service_is_readonly():
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-skill-drift-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert 'ReadWritePaths = lib.mkForce [ ]' in block
    assert "ReadOnlyPaths" in block


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

def test_existing_services_unchanged():
    test_foundry_dry_run_service_invokes_foundry_fixture_safely()
    test_foundry_dry_run_service_is_manual_default_off()
    test_foundry_dry_run_service_has_thin_boundary_permissions()
    test_foundry_report_directory_created_by_activation()
    test_foundry_provisioning_script_exists()
    test_foundry_provisioning_script_has_safe_name()
    prov_manual()
    test_foundry_provisioning_has_no_action_queue_logic()
    test_foundry_provisioning_has_no_gate_logic()
    test_foundry_provisioning_has_no_dossier_text()
    test_foundry_provisioning_has_no_network_in_service()
    test_foundry_provisioning_has_no_github_write_path()
    test_boundary_validator_nix_binding_exists()
    test_boundary_validator_python_script_exists()
    ar_val_off()
    ar_val_nonet()
    ar_val_nogh()
    ar_val_ro()
    test_session_import_fixture_nix_binding_exists()
    test_session_import_service_is_manual_default_off()
    test_session_import_service_wraps_foundry_safely()
    test_si_validator_service_is_manual_default_off()
    test_si_validator_service_no_network()
    test_si_validator_service_no_github()
    test_si_validator_service_is_readonly()
    test_tool_underuse_wrapper_nix_binding_exists()
    test_tool_underuse_wrapper_service_is_manual_default_off()
    test_tool_underuse_wrapper_service_safe()
    test_tool_underuse_wrapper_service_no_network()
    test_tool_underuse_wrapper_service_no_github()
    test_tool_underuse_validator_nix_binding_exists()
    test_tool_underuse_validator_python_script_exists()
    test_tool_underuse_validator_service_is_manual_default_off()
    test_tool_underuse_validator_service_no_network()
    test_tool_underuse_validator_service_no_github()
    test_tool_underuse_validator_service_is_readonly()
    test_weekly_timer_exists_in_harness()
    test_weekly_timer_targets_action_routing_fixture()
    test_weekly_timer_is_default_disabled()
    test_weekly_timer_has_no_network_credentials()
    test_weekly_timer_does_not_break_existing_timers()
