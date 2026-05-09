from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def test_foundry_dry_run_service_invokes_foundry_fixture_safely():
    text = _harness_text()

    assert "foundryActionRoutingFixture" in text
    assert "systemd.services.hermes-evolution-foundry-action-routing-fixture" in text
    assert "python3 -m evolution.core.action_routing_demo" in text
    assert "--mode fixture" in text
    assert "--no-network" in text
    assert "--no-external-writes" in text
    assert "/var/lib/hermes/reports/evolution/action-routing-fixture" in text
    assert "Type = \"oneshot\";" in text


def test_foundry_dry_run_service_is_manual_default_off():
    text = _harness_text()

    assert "systemd.timers.hermes-evolution-foundry-action-routing-fixture" not in text
    service_start = text.index("systemd.services.hermes-evolution-foundry-action-routing-fixture")
    service_end = text.find("systemd.", service_start + 1)
    service_block = text[service_start:] if service_end == -1 else text[service_start:service_end]
    assert "wantedBy" not in service_block


def test_foundry_dry_run_service_has_thin_boundary_permissions():
    text = _harness_text()

    service_start = text.index("systemd.services.hermes-evolution-foundry-action-routing-fixture")
    service_end = text.find("systemd.", service_start + 1)
    service_block = text[service_start:] if service_end == -1 else text[service_start:service_end]

    assert "ReadWritePaths = lib.mkForce [ \"/var/lib/hermes/reports/evolution\" ];" in service_block
    assert "ReadOnlyPaths = lib.mkForce [" in service_block
    assert '"/var/lib/hermes/foundry"' in service_block
    assert "InaccessiblePaths" in service_block
    assert "-/var/lib/hermes/secrets" in service_block
    assert "EnvironmentFile" not in service_block


def test_foundry_report_directory_created_by_activation():
    text = _harness_text()

    assert "/var/lib/hermes/reports/evolution" in text
    assert "/var/lib/hermes/foundry" in text
    assert "install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/evolution" in text
    assert "install -d -o hermes-harness -g hermes -m 2750 /var/lib/hermes/foundry" in text
