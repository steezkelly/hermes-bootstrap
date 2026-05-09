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
PROMOTE_PY = REPO_ROOT / "scripts" / "harness" / "promote_foundry_fixture.py"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


def _promote_text() -> str:
    return PROMOTE_PY.read_text()


# ---------------------------------------------------------------------------
# Nix binding
# ---------------------------------------------------------------------------

def test_promotion_nix_binding_exists():
    text = _harness_text()
    assert "promoteFoundryFixture" in text
    assert 'name = "hermes-promote-foundry-fixture"' in text


# ---------------------------------------------------------------------------
# Python script
# ---------------------------------------------------------------------------

def test_promotion_python_script_exists():
    assert PROMOTE_PY.is_file()


def test_promotion_script_refuses_without_manifest():
    ptext = _promote_text()
    assert "artifact_manifest.json" in ptext
    assert "not found" in ptext.lower()


def test_promotion_script_reads_dossier():
    ptext = _promote_text()
    assert "promotion_dossier.md" in ptext


def test_promotion_script_refuses_when_external_writes_true():
    ptext = _promote_text()
    assert "external_writes_allowed" in ptext and "Refusing" in ptext


def test_promotion_script_requires_review_required():
    ptext = _promote_text()
    assert "review_required" in ptext


def test_promotion_script_creates_draft_pr():
    ptext = _promote_text()
    assert "--draft" in ptext
    assert "gh pr create" in ptext
    assert "--head" in ptext


# ---------------------------------------------------------------------------
# Existing services unchanged
# ---------------------------------------------------------------------------

def test_existing_services_unchanged():
    test_foundry_dry_run_service_invokes_foundry_fixture_safely()
    test_foundry_dry_run_service_is_manual_default_off()
    test_foundry_dry_run_service_has_thin_boundary_permissions()
    test_foundry_report_directory_created_by_activation()
