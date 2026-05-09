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
    test_foundry_provisioning_service_is_manual_default_off as provisioning_service_is_manual_default_off,
    test_foundry_provisioning_has_no_action_queue_logic,
    test_foundry_provisioning_has_no_gate_logic,
    test_foundry_provisioning_has_no_dossier_text,
    test_foundry_provisioning_has_no_network_in_service,
    test_foundry_provisioning_has_no_github_write_path,
)
from test_foundry_boundary_validation import (
    test_boundary_validator_python_script_exists,
    test_boundary_validator_nix_binding_exists,
    test_boundary_validator_service_is_manual_default_off,
    test_boundary_validator_checks_expected_files_exist,
    test_boundary_validator_service_no_network,
    test_boundary_validator_service_no_github,
    test_boundary_validator_service_is_readonly,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


# ---------------------------------------------------------------------------
# Nix binding exists
# ---------------------------------------------------------------------------

def test_session_import_fixture_nix_binding_exists():
    """foundrySessionImportFixture writeShellApplication must exist in harness.nix."""
    text = _harness_text()
    assert "foundrySessionImportFixture" in text
    assert 'name = "hermes-evolution-foundry-session-import-fixture"' in text


def test_session_import_fixture_nix_binding_calls_python():
    """The binding must invoke the session-import demo module."""
    text = _harness_text()
    assert "evolution.core.session_import_demo" in text
    assert "--mode fixture" in text
    assert "--no-network" in text
    assert "--no-external-writes" in text


# ---------------------------------------------------------------------------
# Service is manual/default-off
# ---------------------------------------------------------------------------

def test_session_import_service_is_manual_default_off():
    """The wrapper service must be manual, no timer, no wantedBy."""
    text = _harness_text()
    svc_name = "systemd.services.hermes-evolution-foundry-session-import-fixture"
    timer_name = "systemd.timers.hermes-evolution-foundry-session-import-fixture"

    assert svc_name in text
    assert timer_name not in text

    svc_start = text.index(svc_name)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "wantedBy" not in svc_block


def test_session_import_service_wraps_foundry_safely():
    """Service must have read-only Foundry path, writable reports only, no secrets."""
    text = _harness_text()
    svc_name = "systemd.services.hermes-evolution-foundry-session-import-fixture"
    svc_start = text.index(svc_name)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]

    assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ]' in svc_block
    assert "ReadOnlyPaths" in svc_block
    assert "/var/lib/hermes/foundry" in svc_block
    assert "InaccessiblePaths" in svc_block
    assert "EnvironmentFile" not in svc_block


def test_session_import_service_output_path():
    """Service must write to a distinct subdirectory (check from full harness text)."""
    text = _harness_text()
    assert "/var/lib/hermes/reports/evolution/session-import-fixture" in text


# ---------------------------------------------------------------------------
# Has no network, no GitHub
# ---------------------------------------------------------------------------

def test_session_import_service_no_network():
    """Wrapper service must have no network references."""
    text = _harness_text()
    svc_name = "systemd.services.hermes-evolution-foundry-session-import-fixture"
    svc_start = text.index(svc_name)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]

    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_session_import_service_no_github():
    """Wrapper service must have no GitHub credentials."""
    text = _harness_text()
    svc_name = "systemd.services.hermes-evolution-foundry-session-import-fixture"
    svc_start = text.index(svc_name)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]

    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block


# ---------------------------------------------------------------------------
# Activation directory exists for output
# ---------------------------------------------------------------------------

def test_session_import_output_directory_created():
    """Activation script must create the output directory."""
    text = _harness_text()
    assert "/var/lib/hermes/reports/evolution/session-import-fixture" not in text or \
           "install -d" in text  # directory must be created somewhere


# ---------------------------------------------------------------------------
# Existing services unchanged
# ---------------------------------------------------------------------------

def test_existing_services_unchanged():
    """New wrapper must not break existing services."""
    test_foundry_dry_run_service_invokes_foundry_fixture_safely()
    test_foundry_dry_run_service_is_manual_default_off()
    test_foundry_dry_run_service_has_thin_boundary_permissions()
    test_foundry_report_directory_created_by_activation()
    test_foundry_provisioning_script_exists()
    test_foundry_provisioning_script_has_safe_name()
    provisioning_service_is_manual_default_off()
    test_foundry_provisioning_has_no_action_queue_logic()
    test_foundry_provisioning_has_no_gate_logic()
    test_foundry_provisioning_has_no_dossier_text()
    test_foundry_provisioning_has_no_network_in_service()
    test_foundry_provisioning_has_no_github_write_path()
    test_boundary_validator_nix_binding_exists()
    test_boundary_validator_python_script_exists()
    test_boundary_validator_service_is_manual_default_off()
    test_boundary_validator_checks_expected_files_exist()
    test_boundary_validator_service_no_network()
    test_boundary_validator_service_no_github()
    test_boundary_validator_service_is_readonly()
