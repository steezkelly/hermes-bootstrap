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
    test_foundry_provisioning_service_is_manual_default_off,
    test_foundry_provisioning_has_no_action_queue_logic,
    test_foundry_provisioning_has_no_gate_logic,
    test_foundry_provisioning_has_no_dossier_text,
    test_foundry_provisioning_has_no_network_in_service,
    test_foundry_provisioning_has_no_github_write_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"
VALIDATOR_PY = REPO_ROOT / "scripts" / "harness" / "validate_foundry_action_routing_fixture.py"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _validator_text() -> str:
    return VALIDATOR_PY.read_text()


# ---------------------------------------------------------------------------
# Validator script exists (Nix binding)
# ---------------------------------------------------------------------------

def test_boundary_validator_nix_binding_exists():
    """The validateFoundryActionRoutingFixture writeShellApplication must exist in harness.nix."""
    text = _harness_text()
    assert "validateFoundryActionRoutingFixture" in text
    assert 'name = "hermes-validate-foundry-action-routing-fixture"' in text


def test_boundary_validator_nix_binding_calls_python_script():
    """The binding must invoke the Python validator script."""
    text = _harness_text()
    assert "validate_foundry_action_routing_fixture.py" in text


# ---------------------------------------------------------------------------
# Validator Python script exists on disk
# ---------------------------------------------------------------------------

def test_boundary_validator_python_script_exists():
    """The Python validator script must exist on disk."""
    assert VALIDATOR_PY.is_file(), f"Missing: {VALIDATOR_PY}"


# ---------------------------------------------------------------------------
# Manual / default-off service
# ---------------------------------------------------------------------------

def test_boundary_validator_service_is_manual_default_off():
    """The validator service must be manual, no timer, no wantedBy."""
    text = _harness_text()
    assert "systemd.services.hermes-validate-foundry-action-routing-fixture" in text
    assert "systemd.timers.hermes-validate-foundry-action-routing-fixture" not in text

    service_start = text.index(
        "systemd.services.hermes-validate-foundry-action-routing-fixture"
    )
    service_end = text.find("systemd.", service_start + 1)
    service_block = (
        text[service_start:] if service_end == -1 else text[service_start:service_end]
    )
    assert "wantedBy" not in service_block


# ---------------------------------------------------------------------------
# Validator checks the right things (mechanical only)
# ---------------------------------------------------------------------------

def test_boundary_validator_checks_expected_files_exist():
    """Validator Python script must reference the 4 expected output files."""
    vtext = _validator_text()
    assert "run_report.json" in vtext
    assert "action_queue.json" in vtext
    assert "promotion_dossier.md" in vtext
    assert "artifact_manifest.json" in vtext


def test_boundary_validator_checks_json_parse():
    """Validator must attempt JSON parsing of .json artifacts."""
    vtext = _validator_text()
    vlower = vtext.lower()
    assert "json.loads" in vlower or "json.load" in vlower


def test_boundary_validator_checks_schema_version():
    """Validator must verify schema_version is a positive integer."""
    vtext = _validator_text()
    assert "schema_version" in vtext


def test_boundary_validator_checks_no_external_writes():
    """Validator must verify external_writes_allowed is explicitly false."""
    vtext = _validator_text()
    assert "external_writes_allowed" in vtext


# ---------------------------------------------------------------------------
# Validator must NOT check semantics
# ---------------------------------------------------------------------------

def test_boundary_validator_has_no_queue_ranking():
    """Validator must not evaluate action item priority or ranking."""
    vtext = _validator_text()

    # Strip the module docstring so we don't match the disclaimer text itself.
    _, sep, body = vtext.partition('"""')
    if sep:
        _, _, body = body.partition('"""')

    assert "priority" not in body
    assert "bucket" not in body


def test_boundary_validator_has_no_gate_semantics():
    """Validator must not evaluate baseline vs candidate verdicts."""
    vtext = _validator_text()

    # Strip the module docstring so we don't match the disclaimer text itself.
    _, sep, body = vtext.partition('"""')
    if sep:
        _, _, body = body.partition('"""')

    assert "baseline_pass" not in body
    assert "candidate_pass" not in body
    assert "verdict" not in body


def test_boundary_validator_has_no_dossier_evaluation():
    """Validator must not evaluate recommendation or dossier prose."""
    vtext = _validator_text()
    assert "Recommend" not in vtext
    assert "promote" not in vtext


# ---------------------------------------------------------------------------
# Validator has no network or external write capability
# ---------------------------------------------------------------------------

def test_boundary_validator_service_no_network():
    """Validator service must have no network-accessible paths."""
    text = _harness_text()
    svc_start = text.index(
        "systemd.services.hermes-validate-foundry-action-routing-fixture"
    )
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]

    assert "http" not in svc_block
    assert "github.com" not in svc_block


def test_boundary_validator_service_no_github():
    """Validator service must have no GitHub credentials or write paths."""
    text = _harness_text()
    svc_start = text.index(
        "systemd.services.hermes-validate-foundry-action-routing-fixture"
    )
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]

    assert "EnvironmentFile" not in svc_block
    assert "GITHUB_TOKEN" not in svc_block


def test_boundary_validator_service_is_readonly():
    """Validator service must have no ReadWritePaths."""
    text = _harness_text()
    svc_start = text.index(
        "systemd.services.hermes-validate-foundry-action-routing-fixture"
    )
    svc_end = text.find("systemd.", svc_start + 1)
    svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]

    assert 'ReadWritePaths = lib.mkForce [ ]' in svc_block
    assert "ReadOnlyPaths" in svc_block


# ---------------------------------------------------------------------------
# Existing services unchanged
# ---------------------------------------------------------------------------

def test_existing_wrapper_and_provisioning_unchanged():
    """Boundary validation must not alter existing wrapper or provisioning."""
    test_foundry_dry_run_service_invokes_foundry_fixture_safely()
    test_foundry_dry_run_service_is_manual_default_off()
    test_foundry_dry_run_service_has_thin_boundary_permissions()
    test_foundry_report_directory_created_by_activation()
    test_foundry_provisioning_script_exists()
    test_foundry_provisioning_script_has_safe_name()
    test_foundry_provisioning_service_is_manual_default_off()
    test_foundry_provisioning_has_no_action_queue_logic()
    test_foundry_provisioning_has_no_gate_logic()
    test_foundry_provisioning_has_no_dossier_text()
    test_foundry_provisioning_has_no_network_in_service()
    test_foundry_provisioning_has_no_github_write_path()
