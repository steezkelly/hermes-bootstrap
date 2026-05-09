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
    test_foundry_provisioning_service_is_manual_default_off as provisioning_service_is_manual,
    test_foundry_provisioning_has_no_action_queue_logic,
    test_foundry_provisioning_has_no_gate_logic,
    test_foundry_provisioning_has_no_dossier_text,
    test_foundry_provisioning_has_no_network_in_service,
    test_foundry_provisioning_has_no_github_write_path,
)
from test_foundry_boundary_validation import (
    test_boundary_validator_nix_binding_exists,
    test_boundary_validator_python_script_exists,
    test_boundary_validator_service_is_manual_default_off as action_validator_manual_off,
    test_boundary_validator_service_no_network,
    test_boundary_validator_service_no_github,
    test_boundary_validator_service_is_readonly,
)
from test_foundry_session_import_wrapper import (
    test_session_import_fixture_nix_binding_exists,
    test_session_import_service_is_manual_default_off,
    test_session_import_service_wraps_foundry_safely,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"
VALIDATOR_PY = (
    REPO_ROOT
    / "scripts"
    / "harness"
    / "validate_foundry_session_import_fixture.py"
)


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _validator_text() -> str:
    return VALIDATOR_PY.read_text()


# ---------------------------------------------------------------------------
# Nix binding exists
# ---------------------------------------------------------------------------

def test_si_validator_nix_binding_exists():
    """validateFoundrySessionImportFixture writeShellApplication must exist."""
    text = _harness_text()
    assert "validateFoundrySessionImportFixture" in text
    assert 'name = "hermes-validate-foundry-session-import-fixture"' in text


def test_si_validator_nix_binding_calls_python_script():
    """The binding must invoke the Python validator script."""
    text = _harness_text()
    assert "validate_foundry_session_import_fixture.py" in text


# ---------------------------------------------------------------------------
# Python script exists on disk
# ---------------------------------------------------------------------------

def test_si_validator_python_script_exists():
    """The Python validator script must exist on disk."""
    assert VALIDATOR_PY.is_file(), f"Missing: {VALIDATOR_PY}"


# ---------------------------------------------------------------------------
# Manual / default-off service
# ---------------------------------------------------------------------------

def test_si_validator_service_is_manual_default_off():
    """The validator service must be manual, no timer, no wantedBy."""
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-session-import-fixture"
    tmr = "systemd.timers.hermes-validate-foundry-session-import-fixture"
    assert svc in text
    assert tmr not in text

    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "wantedBy" not in svc_block


# ---------------------------------------------------------------------------
# Validator checks the right things (mechanical only)
# ---------------------------------------------------------------------------

def test_si_validator_checks_expected_files():
    """Validator Python script must reference the 4 expected output files."""
    vtext = _validator_text()
    assert "run_report.json" in vtext
    assert "eval_examples.json" in vtext
    assert "promotion_dossier.md" in vtext
    assert "artifact_manifest.json" in vtext


def test_si_validator_checks_json_parse():
    """Validator must attempt JSON parsing of .json artifacts."""
    vtext = _validator_text()
    vlower = vtext.lower()
    assert "json.loads" in vlower or "json.load" in vlower


def test_si_validator_checks_schema_version():
    """Validator must verify schema_version is a positive integer."""
    vtext = _validator_text()
    assert "schema_version" in vtext


def test_si_validator_checks_external_writes():
    """Validator must verify external_writes_allowed is explicitly false."""
    vtext = _validator_text()
    assert "external_writes_allowed" in vtext


# ---------------------------------------------------------------------------
# Validator must NOT check semantics
# ---------------------------------------------------------------------------

def test_si_validator_has_no_priority_or_bucket():
    """Validator must not evaluate action item priority or bucket."""
    _, sep, body = _validator_text().partition('"""')
    if sep:
        _, _, body = body.partition('"""')
    assert "priority" not in body
    assert "bucket" not in body


def test_si_validator_has_no_gate_semantics():
    """Validator must not evaluate baseline vs candidate verdicts."""
    _, sep, body = _validator_text().partition('"""')
    if sep:
        _, _, body = body.partition('"""')
    assert "baseline_pass" not in body
    assert "candidate_pass" not in body
    assert "verdict" not in body


def test_si_validator_has_no_dossier_evaluation():
    """Validator must not evaluate recommendation or dossier prose."""
    _, sep, body = _validator_text().partition('"""')
    if sep:
        _, _, body = body.partition('"""')
    assert "Recommend" not in body
    assert "promote" not in body


# ---------------------------------------------------------------------------
# Validator has no network or external write capability
# ---------------------------------------------------------------------------

def test_si_validator_service_no_network():
    """Validator service must have no network-accessible paths."""
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-session-import-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_si_validator_service_no_github():
    """Validator service must have no GitHub credentials."""
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-session-import-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block


def test_si_validator_service_is_readonly():
    """Validator service must have no ReadWritePaths."""
    text = _harness_text()
    svc = "systemd.services.hermes-validate-foundry-session-import-fixture"
    svc_start = text.index(svc)
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
    assert 'ReadWritePaths = lib.mkForce [ ]' in svc_block
    assert "ReadOnlyPaths" in svc_block


# ---------------------------------------------------------------------------
# Existing services unchanged
# ---------------------------------------------------------------------------

def test_existing_services_unchanged():
    """New validator must not break existing services."""
    test_foundry_dry_run_service_invokes_foundry_fixture_safely()
    test_foundry_dry_run_service_is_manual_default_off()
    test_foundry_dry_run_service_has_thin_boundary_permissions()
    test_foundry_report_directory_created_by_activation()
    test_foundry_provisioning_script_exists()
    test_foundry_provisioning_script_has_safe_name()
    provisioning_service_is_manual()
    test_foundry_provisioning_has_no_action_queue_logic()
    test_foundry_provisioning_has_no_gate_logic()
    test_foundry_provisioning_has_no_dossier_text()
    test_foundry_provisioning_has_no_network_in_service()
    test_foundry_provisioning_has_no_github_write_path()
    test_boundary_validator_nix_binding_exists()
    test_boundary_validator_python_script_exists()
    action_validator_manual_off()
    test_boundary_validator_service_no_network()
    test_boundary_validator_service_no_github()
    test_boundary_validator_service_is_readonly()
    test_session_import_fixture_nix_binding_exists()
    test_session_import_service_is_manual_default_off()
    test_session_import_service_wraps_foundry_safely()
