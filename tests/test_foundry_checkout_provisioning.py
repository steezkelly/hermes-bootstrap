from __future__ import annotations

from pathlib import Path

from test_foundry_service_contract import (
    test_foundry_dry_run_service_has_thin_boundary_permissions,
    test_foundry_dry_run_service_invokes_foundry_fixture_safely,
    test_foundry_dry_run_service_is_manual_default_off,
    test_foundry_report_directory_created_by_activation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


# ---------------------------------------------------------------------------
# Provisioning script / mechanism exists
# ---------------------------------------------------------------------------

def test_foundry_provisioning_script_exists():
    """A provisioning script or writeShellApplication must exist."""
    text = _harness_text()
    assert "provisionFoundryCheckout" in text


def test_foundry_provisioning_script_has_safe_name():
    """The shell app name should signal it is a bootstrap provisioning tool."""
    text = _harness_text()

    # After the writeShellApplication let binding, the name is set.
    assert 'name = "hermes-provision-foundry-checkout"' in text


def test_foundry_provisioning_script_copies_or_links_repo():
    """The provisioning script must place a Foundry checkout, not clone from network."""
    text = _harness_text()

    # Must reference the target path or a source env-var for the local checkout.
    assert "/var/lib/hermes/foundry/hermes-agent-self-evolution" in text


# ---------------------------------------------------------------------------
# Manual / default-off service
# ---------------------------------------------------------------------------

def test_foundry_provisioning_service_is_manual_default_off():
    """The provisioning service must be manual, no timer, no wantedBy."""
    text = _harness_text()

    assert "systemd.services.hermes-provision-foundry-checkout" in text
    assert "systemd.timers.hermes-provision-foundry-checkout" not in text

    service_start = text.index("systemd.services.hermes-provision-foundry-checkout")
    service_end = text.find("systemd.", service_start + 1)
    service_block = text[service_start:] if service_end == -1 else text[service_start:service_end]
    assert "wantedBy" not in service_block


# ---------------------------------------------------------------------------
# Boundary: no Foundry business logic in bootstrap
# ---------------------------------------------------------------------------

def test_foundry_provisioning_has_no_action_queue_logic():
    """Bootstrap provisioning must not generate or interpret action queues."""
    text = _harness_text()
    provisioning_start = text.index("provisionFoundryCheckout")
    provisioning_end = text.find("\n  ", provisioning_start)  # next let binding
    if provisioning_end == -1:
        provisioning_end = text.find("\nin\n", provisioning_start)
    block = text[provisioning_start:provisioning_end] if provisioning_end != -1 else text[provisioning_start:]

    assert "action_queue" not in block
    assert "action_item" not in block
    assert "bucket" not in block


def test_foundry_provisioning_has_no_gate_logic():
    """Bootstrap provisioning must not evaluate pass/fail gates."""
    text = _harness_text()
    provisioning_start = text.index("provisionFoundryCheckout")
    provisioning_end = text.find("\n  ", provisioning_start)
    if provisioning_end == -1:
        provisioning_end = text.find("\nin\n", provisioning_start)
    block = text[provisioning_start:provisioning_end] if provisioning_end != -1 else text[provisioning_start:]

    assert "baseline_passed" not in block
    assert "candidate_passed" not in block
    assert "verdict" not in block


def test_foundry_provisioning_has_no_dossier_text():
    """Bootstrap provisioning must not render promotion dossiers."""
    text = _harness_text()
    provisioning_start = text.index("provisionFoundryCheckout")
    provisioning_end = text.find("\n  ", provisioning_start)
    if provisioning_end == -1:
        provisioning_end = text.find("\nin\n", provisioning_start)
    block = text[provisioning_start:provisioning_end] if provisioning_end != -1 else text[provisioning_start:]

    assert "promotion_dossier" not in block
    assert "dossier" not in block


# ---------------------------------------------------------------------------
# Boundary: no network, no external writes, no GitHub
# ---------------------------------------------------------------------------

def test_foundry_provisioning_has_no_network_in_service():
    """Provisioning service must use local-only paths, no network flags."""
    text = _harness_text()
    if "systemd.services.hermes-provision-foundry-checkout" not in text:
        return  # will be caught by the existence test above
    service_start = text.index("systemd.services.hermes-provision-foundry-checkout")
    service_end = text.find("systemd.", service_start + 1)
    service_block = text[service_start:] if service_end == -1 else text[service_start:service_end]

    # No network-reachable paths in ReadWritePaths
    assert "github.com" not in service_block
    assert "http" not in service_block


def test_foundry_provisioning_has_no_github_write_path():
    """Provisioning must have no GitHub credentials or write paths."""
    text = _harness_text()
    if "systemd.services.hermes-provision-foundry-checkout" not in text:
        return
    service_start = text.index("systemd.services.hermes-provision-foundry-checkout")
    service_end = text.find("systemd.", service_start + 1)
    service_block = text[service_start:] if service_end == -1 else text[service_start:service_end]

    assert "EnvironmentFile" not in service_block
    assert "GITHUB_TOKEN" not in service_block
    assert "gh " not in service_block


# ---------------------------------------------------------------------------
# Existing wrapper service still safe after provisioning addition
# ---------------------------------------------------------------------------

def test_existing_wrapper_unchanged_by_provisioning():
    """Adding provisioning must not alter the existing wrapper service contract."""
    test_foundry_dry_run_service_invokes_foundry_fixture_safely()
    test_foundry_dry_run_service_is_manual_default_off()
    test_foundry_dry_run_service_has_thin_boundary_permissions()
    test_foundry_report_directory_created_by_activation()
