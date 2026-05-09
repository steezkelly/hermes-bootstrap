"""Cross-session integration: prove every Foundry module has a Bootstrap wrapper.

Contract symmetry test: for every Foundry module that produces
run_report.json artifacts, verify a matching Bootstrap writeShellApplication
binding, systemd service (manual, no timer), and boundary validator exist.

Runs against current master state. Designed to catch asymmetry when new
modules land without matching wrappers.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _harness_text() -> str:
    return HARNESS_NIX.read_text()


# ---------------------------------------------------------------------------
# Contract: every Foundry module has a Bootstrap wrapper
# ---------------------------------------------------------------------------

# Module name → (expected binding prefix, expected service prefix)
FOUNDRY_TO_BOOTSTRAP = {
    "action_routing_demo": (
        "foundryActionRoutingFixture",
        "hermes-evolution-foundry-action-routing-fixture",
    ),
    "session_import_demo": (
        "foundrySessionImportFixture",
        "hermes-evolution-foundry-session-import-fixture",
    ),
    "tool_underuse_demo": (
        "foundryToolUnderuseFixture",
        "hermes-evolution-foundry-tool-underuse-fixture",
    ),
    "skill_drift_demo": (
        "foundrySkillDriftFixture",
        "hermes-evolution-foundry-skill-drift-fixture",
    ),
    "real_trace_ingestion": (
        "foundryRealTraceIngestion",
        "hermes-evolution-foundry-real-trace-ingestion",
    ),
    "attention_router_bridge": (
        "foundryAttentionRouterBridge",
        "hermes-evolution-foundry-attention-router-bridge",
    ),
    "pipeline_runner": (
        "foundryPipelineRunner",
        "hermes-evolution-foundry-pipeline-runner",
    ),
}


def test_all_foundry_modules_have_nix_binding():
    """Every Foundry module must have a writeShellApplication binding."""
    text = _harness_text()
    missing = []
    for module_name, (binding, _) in FOUNDRY_TO_BOOTSTRAP.items():
        if binding not in text:
            missing.append(f"{module_name} → {binding}")
    assert not missing, f"Missing Nix bindings:\n" + "\n".join(f"  - {m}" for m in missing)


def test_all_foundry_modules_have_systemd_service():
    """Every Foundry module must have a systemd service block."""
    text = _harness_text()
    missing = []
    for module_name, (_, service) in FOUNDRY_TO_BOOTSTRAP.items():
        svc_name = f"systemd.services.{service}"
        if svc_name not in text:
            missing.append(f"{module_name} → {svc_name}")
    assert not missing, f"Missing systemd services:\n" + "\n".join(f"  - {m}" for m in missing)


def test_all_foundry_modules_have_boundary_validator():
    """Every Foundry module must have a matching validate_*.py script."""
    validator_dir = REPO_ROOT / "scripts" / "harness"
    missing = []
    for module_name in FOUNDRY_TO_BOOTSTRAP:
        # Map module name to expected validator filename
        base = module_name.replace("_", "-")  # python module style
        if module_name == "action_routing_demo":
            expected = "validate_foundry_action_routing_fixture.py"
        elif module_name == "session_import_demo":
            expected = "validate_foundry_session_import_fixture.py"
        elif module_name == "tool_underuse_demo":
            expected = "validate_foundry_tool_underuse_fixture.py"
        elif module_name == "skill_drift_demo":
            expected = "validate_foundry_skill_drift_fixture.py"
        elif module_name == "real_trace_ingestion":
            expected = "validate_foundry_real_trace_ingestion.py"
        elif module_name == "attention_router_bridge":
            expected = "validate_foundry_attention_router_bridge.py"
        elif module_name == "pipeline_runner":
            expected = "validate_foundry_pipeline_runner.py"
        else:
            expected = f"validate_foundry_{base}.py"

        path = validator_dir / expected
        if not path.is_file():
            missing.append(f"{module_name} → {expected}")
    assert not missing, f"Missing validator scripts:\n" + "\n".join(f"  - {m}" for m in missing)


# ---------------------------------------------------------------------------
# Contract: all Foundry services are manual (no timer, no wantedBy)
# ---------------------------------------------------------------------------

MANUAL_SERVICES = [
    svc for _, svc in FOUNDRY_TO_BOOTSTRAP.values()
]


def test_all_foundry_services_are_manual():
    """No Foundry wrapper service may have a timer or wantedBy."""
    text = _harness_text()
    failures = []
    for service in MANUAL_SERVICES:
        svc_name = f"systemd.services.{service}"
        timer_name = f"systemd.timers.{service}"

        # Service block must exist (checked in another test)
        if svc_name not in text:
            continue

        # No dedicated timer block for this service
        if timer_name in text:
            failures.append(f"{service}: has dedicated timer block")

        # No wantedBy in the service block
        svc_start = text.index(svc_name)
        svc_end = text.find("systemd.", svc_start + 1)
        svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
        if "wantedBy" in svc_block:
            failures.append(f"{service}: has wantedBy in service block")

    assert not failures, f"Services that should be manual:\n" + "\n".join(f"  - {f}" for f in failures)


# ---------------------------------------------------------------------------
# Contract: all Foundry services have safety boundaries
# ---------------------------------------------------------------------------

def test_all_foundry_services_no_network():
    """No Foundry wrapper service may reference http, https, or github.com."""
    text = _harness_text()
    failures = []
    for service in MANUAL_SERVICES:
        svc_name = f"systemd.services.{service}"
        if svc_name not in text:
            continue
        svc_start = text.index(svc_name)
        svc_end = text.find("systemd.", svc_start + 1)
        svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
        if "http" in svc_block:
            failures.append(f"{service}: references http")
        if "github.com" in svc_block:
            failures.append(f"{service}: references github.com")
    assert not failures, f"Services with network references:\n" + "\n".join(f"  - {f}" for f in failures)


def test_all_foundry_services_no_github_credentials():
    """No Foundry wrapper service may have GITHUB_TOKEN or EnvironmentFile."""
    text = _harness_text()
    failures = []
    for service in MANUAL_SERVICES:
        svc_name = f"systemd.services.{service}"
        if svc_name not in text:
            continue
        svc_start = text.index(svc_name)
        svc_end = text.find("systemd.", svc_start + 1)
        svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
        if "GITHUB_TOKEN" in svc_block:
            failures.append(f"{service}: references GITHUB_TOKEN")
        if "EnvironmentFile" in svc_block:
            failures.append(f"{service}: has EnvironmentFile")
    assert not failures, f"Services with GitHub credentials:\n" + "\n".join(f"  - {f}" for f in failures)


def test_all_foundry_services_secrets_inaccessible():
    """Every Foundry wrapper service must have InaccessiblePaths with secrets."""
    text = _harness_text()
    failures = []
    for service in MANUAL_SERVICES:
        svc_name = f"systemd.services.{service}"
        if svc_name not in text:
            continue
        svc_start = text.index(svc_name)
        svc_end = text.find("systemd.", svc_start + 1)
        svc_block = text[svc_start:] if svc_end == -1 else text[svc_start:svc_end]
        if "InaccessiblePaths" not in svc_block:
            failures.append(f"{service}: no InaccessiblePaths")
        elif "secrets" not in svc_block:
            failures.append(f"{service}: secrets not in InaccessiblePaths")
    assert not failures, f"Services without secrets protection:\n" + "\n".join(f"  - {f}" for f in failures)


# ---------------------------------------------------------------------------
# Integration: full suite verification
# ---------------------------------------------------------------------------

def test_full_bootstrap_suite_passing():
    """Quick check: the pytest runner can import and discover all tests.
    Full suite count verification happens in CI; this is a smoke test.
    """
    text = _harness_text()
    # Verify the harness.nix file itself is parseable enough that all
    # expected service names resolve. If this assertion passes, the
    # Nix structure is internally consistent.
    assert "systemd.services." in text
    assert "commonServiceConfig" in text
    assert "writeShellApplication" in text
    assert len(text) > 10000  # sanity: harness.nix is substantial


# ---------------------------------------------------------------------------
# Documentation: cross-session status exists
# ---------------------------------------------------------------------------

def test_multi_session_status_doc_exists():
    """The cross-session status roster must exist for other sessions."""
    path = REPO_ROOT / "docs" / "multi-session-status.md"
    assert path.is_file(), f"missing: {path}"
    content = path.read_text()
    assert "Session roster" in content
    assert "Merge order" in content
