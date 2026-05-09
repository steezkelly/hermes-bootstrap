# Hermes Architecture — Multi-Session Status Roster
# Generated 2026-05-09 ~20:00 UTC — paste to any session for orientation

## Repo state

### steezkelly/hermes-agent-self-evolution (Foundry)
  main: ffde60d
  Modules in evolution/core/:
    action_routing_demo.py      — long briefing → one action item
    session_import_demo.py      — raw trace → structured eval
    tool_underuse_demo.py       — describes instead of calls
    skill_drift_demo.py         — stale skill body detection
    real_trace_ingestion.py     — live JSONL → all four detectors
    attention_router_bridge.py  — detections → action items
    pipeline_runner.py          — orchestrates all above
    session_end_chain.py        — [SESSION 1 BUILDING] full chain module

  Open PRs:
    #1 — GEPA observatory (stale, conflicts, 349 passed)

### steezkelly/hermes-bootstrap
  master: f8dbac2
  Validators (scripts/harness/validate_*.py):
    validate_foundry_action_routing_fixture.py
    validate_foundry_session_import_fixture.py
    validate_foundry_tool_underuse_fixture.py
    validate_foundry_skill_drift_fixture.py
    validate_foundry_real_trace_ingestion.py
    validate_foundry_attention_router_bridge.py
    validate_session_end_ingest.py
    validate_foundry_pipeline_runner.py  — [SESSION 2 BUILDING]

  Services in system/nixos/harness.nix:
    Foundry fixture runners (4): action-routing, session-import, tool-underuse, skill-drift
    Real-trace: ingestion + validator
    Session-end: export + ingest + validator
    Bridge: attention-router-bridge + validator
    Chain: bridge-ingestion-to-attention-router (summary)
    Pipeline runner: [SESSION 2 BUILDING]

## Session roster

  Session 1 — Foundry: session_end_chain.py
    Building full chain module that runs ingestion → bridge in one call.
    File: evolution/core/session_end_chain.py
    No Bootstrap involvement.

  Session 2 — Bootstrap: pipeline runner wrapper
    Building validate_foundry_pipeline_runner.py +
    writeShellApplication + systemd services.
    Files: scripts/harness/validate_foundry_pipeline_runner.py,
    system/nixos/harness.nix additions.
    No Foundry involvement.

  Session 3 (me) — Integration
    Cross-session status doc + contract symmetry test.
    Verifying every Foundry module has a matching Bootstrap wrapper.

  Session 4 — Documentation
    CONTRIBUTING.md, docs/ARCHITECTURE.md, docs/ROADMAP.md.
    Pure docs, no code changes.

## Merge order
  1. Session 1 (Foundry) — no dependencies
  2. Session 2 (Bootstrap) — no dependencies
  3. Session 3 (contract test) — waits for session 2's wrapper
  4. Session 4 (docs) — no dependencies, can merge anytime

## Next after this phase
  Live NixOS drill: prove the full chain end-to-end on hardware.
  Command: hermes session ends → systemctl start hermes-session-end-ingest
  Expected: 3 action items produced from detected failures.
