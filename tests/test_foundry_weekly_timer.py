from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"
DEPLOYMENT_OPTS = REPO_ROOT / "system" / "nixos" / "deployment-options.nix"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _deployment_text() -> str:
    return DEPLOYMENT_OPTS.read_text()


def test_weekly_timer_exists_in_harness():
    """Weekly dry-run timer binding must exist, gated by mkIf."""
    text = _harness_text()
    assert "hermes-evolution-foundry-weekly-dry-run" in text
    assert "lib.mkIf deployment.evolutionFoundryTimerEnabled" in text


def test_weekly_timer_targets_action_routing_fixture():
    """Timer fires the action-routing fixture (pipeline entry point)."""
    text = _harness_text()
    assert 'Unit = "hermes-evolution-foundry-action-routing-fixture.service"' in text


def test_weekly_timer_is_default_disabled():
    """evolutionFoundryTimerEnabled must default to false."""
    text = _deployment_text()
    assert "evolutionFoundryTimerEnabled = false" in text


def test_weekly_timer_has_calendar():
    """Calendar option must exist with a default."""
    text = _deployment_text()
    assert "evolutionFoundryTimerCalendar" in text
    assert "Sat" in text or "weekly" in text.lower()


def test_weekly_timer_has_no_network_credentials():
    """Timer does not add EnvironmentFile or GitHub tokens."""
    text = _harness_text()
    timer_name = "hermes-evolution-foundry-weekly-dry-run"
    t_start = text.index(timer_name)
    t_end = text.find("systemd.", t_start + 1)
    block = text[t_start:] if t_end == -1 else text[t_start:t_end]
    assert "EnvironmentFile" not in block
    assert "GITHUB_TOKEN" not in block


def test_weekly_timer_does_not_break_existing_timers():
    """Existing timers (daily-local-brief, phase2-delivery) still present."""
    text = _harness_text()
    assert "hermes-daily-local-brief" in text
    assert "hermes-phase2-delivery-brief-send" in text
