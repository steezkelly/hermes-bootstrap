# Agent Evolution Foundry Appliance Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Keep hermes-bootstrap as the safe, reproducible appliance substrate for running Agent Evolution Foundry, without moving Foundry business logic into the bootstrap repo.

**Architecture:** Hermes Agent remains the runtime/organism and trace producer. Agent Evolution Foundry remains the trace-to-eval proving ground that normalizes traces, builds evals, tests candidate artifacts, gates regressions, emits action queues, and writes promotion dossiers. hermes-bootstrap owns only the habitat: NixOS wiring, users, permissions, data directories, retention, disabled/default-off services, local invocation, schema-version boundary validation, and fail-closed storage of Foundry outputs.

**Tech Stack:** NixOS modules, systemd oneshot services/timers, JSON/JSONL schema validation at repo boundaries, pytest + shell static tests, Foundry CLI invocation, local artifact directories under `/var/lib/hermes` or configured equivalents.

---

## Decision Memo from Adversarial Review

The deep-research correction is accepted:

> Bootstrap should package and supervise Foundry output, not reimplement Foundry's evidence model.

The smallest compounding loop is:

```text
one repeated failure -> one eval -> one better artifact -> one measured win -> one manual promotion
```

This plan intentionally narrows the original roadmap. It removes bootstrap-owned evidence renderers, action ranking policy, promotion dossier rendering, and event-sourced control-plane ambitions from the bootstrap side. Those semantics belong in Foundry.

## Product North Star

Do not build another briefing system. Do not build a report machine about itself.

Build a local, reviewable action path where a repeated failure becomes a measured improvement. Steve-facing output should be a concise action queue with ready-to-paste Hermes prompts, but the queue semantics and wording are Foundry artifacts. bootstrap only stores, validates, and exposes the queue file emitted by Foundry.

## Component Ownership Contract

| Component | Owns | Must not absorb |
|---|---|---|
| Hermes Agent | Runtime loop, tools, skills, memory, cron, delegation, gateway, MCP, session/trace export, artifact version stamping | Eval construction, optimizer policy, promotion governance |
| Agent Evolution Foundry | Trace ingestion, normalization, redaction, eval cases, holdouts, candidate artifacts, diagnostics, gates, action queue generation, promotion dossiers, evidence renderer | NixOS module setup, secrets wiring, service supervision, appliance permissions |
| hermes-bootstrap | NixOS modules, systemd oneshots/timers, users, permissions, repo/output path config, retention, local dry-run invocation, schema-version validation, fail-closed wrappers | Evidence semantics, queue ranking, `next_prompt` authoring, dossier wording, mutation/gate logic |

Boundary rule:

> If a component decides what improvement means, what counts as regression, how action items are ranked, or what text belongs in a promotion dossier, that component is Foundry.

bootstrap may run it, store it, expose it, and keep it disabled by default. bootstrap should not author those semantics.

## Non-Negotiable Safety Rules

1. No live external sends from bootstrap Foundry services.
2. No GitHub writes from bootstrap Foundry services.
3. No timers enabled by default.
4. No production skill/config mutation without explicit manual promotion.
5. Fixture and dry-run paths require no credentials.
6. Foundry artifacts are local first and schema-versioned.
7. bootstrap validation is boundary validation only: existence, schema version, required top-level fields, local paths, and fail-closed behavior.
8. Every future PR body must include local verification commands and evidence paths when checks are absent.

## Minimal Artifact Contract

Foundry is the producer of all semantic artifacts. bootstrap is a consumer/wrapper.

| Artifact | Producer | bootstrap responsibility |
|---|---|---|
| `traces.jsonl` | Hermes Agent | Provide configured input path and permissions; do not reinterpret trace semantics |
| `eval_cases.jsonl` | Foundry | Store if emitted; validate schema version only if used by a service boundary |
| `run_report.json` | Foundry | Require presence after successful dry-run; validate top-level contract |
| `action_queue.json` | Foundry | Store/surface; validate required fields, expiry, evidence paths, and local-only safety flags |
| `promotion_dossier.md` | Foundry | Store/surface; do not generate text in bootstrap |
| `artifact_manifest.json` | Foundry | Pin/rollback support for the appliance wrapper |

Do not add SQLite projections, dashboards, kanban card creation, or automatic PR text generation in bootstrap until one Foundry loop has shown holdout-backed value.

## First Demo Contract

The first demo should prove user value, not artifact volume.

Repeated failure:

```text
Hermes produces a long strategic briefing when Steve needs one concise action item with owner, evidence path, expiry, and a ready-to-paste next prompt.
```

Foundry loop:

1. Fixture trace/event captures the failure.
2. Foundry converts it into an `action_routing` eval case.
3. Baseline `action_router` artifact fails at least one deterministic assertion.
4. Candidate `action_router` artifact passes deterministic assertions.
5. Gate result proves baseline fail + candidate pass with no regressions on fixture/adversarial cases.
6. Foundry emits:
   - `run_report.json`
   - `action_queue.json`
   - `promotion_dossier.md`
   - `artifact_manifest.json`
7. bootstrap manually invokes this Foundry dry-run and stores the outputs locally.

Success is not “three files were generated.” Success is “one repeated failure has a replayable eval, a better artifact, and a manual promotion recommendation backed by evidence.”

## Deferred Until After the First Measured Loop

- bootstrap-owned evidence renderers
- bootstrap-owned action queue projection/ranking
- bootstrap-owned promotion dossier rendering
- event-sourced control plane in bootstrap
- SQLite projections for this loop
- kanban card creation from bootstrap services
- dashboard-heavy surfaces
- scheduled/default-on Foundry timers
- autonomous repair or mutation
- live sends or GitHub writes from services

---

## Milestone 0: Contract and Naming Alignment

**Objective:** Make the three-project architecture unambiguous before implementation.

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Create: `docs/agent-evolution-foundry.md`
- Test: docs sanity only unless shell/Nix files change

### Task 0.1: Add the vocabulary contract

**Objective:** Define the durable mental model.

Add this language to `docs/agent-evolution-foundry.md`:

```markdown
# Agent Evolution Foundry in hermes-bootstrap

Hermes Agent is the runtime/organism: tools, skills, memory, cron, gateway, delegation, MCP, and trace export.

Agent Evolution Foundry is the trace-to-eval proving ground: traces become evals, evals test candidate artifacts, candidates are gated against regressions, and only evidence-backed upgrades are recommended for promotion.

hermes-bootstrap is the habitat/appliance substrate: reproducible NixOS wiring, local directories, permissions, disabled/default-off service wrappers, retention, and boundary validation for Foundry outputs.
```

**Verification:**

```bash
grep -R "trace-to-eval proving ground" README.md SPEC.md docs/agent-evolution-foundry.md
```

Expected: at least one match in docs and a concise pointer from README/SPEC.

### Task 0.2: Document explicit out-of-scope claims

**Objective:** Prevent hype drift and semantic creep.

Add an "Out of scope for bootstrap" section:

```markdown
## Out of scope for bootstrap

- Evidence semantics
- Eval generation
- Candidate artifact generation
- Gate verdict logic
- Action queue ranking or wording
- Promotion dossier wording
- Autonomous production mutation
- Live delivery from evolution services
- Automatic GitHub writes from appliance services
```

**Verification:**

```bash
grep -n "Out of scope for bootstrap" docs/agent-evolution-foundry.md
```

Expected: section exists.

---

## Milestone 1: Foundry CLI Contract Before Appliance Code

**Objective:** Define the CLI/artifact contract that bootstrap will invoke. Implementation of the CLI belongs in Foundry, not bootstrap.

**Files:**
- Create: `docs/foundry-cli-contract.md`
- Modify: `docs/agent-evolution-foundry.md`
- Do not create bootstrap evidence/queue/dossier renderer scripts

### Task 1.1: Document the required Foundry command

**Objective:** Give bootstrap a stable target without owning semantics.

Create `docs/foundry-cli-contract.md`:

```markdown
# Foundry CLI Contract for hermes-bootstrap

bootstrap expects a Foundry command shaped like:

```bash
foundry run action-routing-fixture \
  --input /path/to/traces.jsonl \
  --out /var/lib/hermes/reports/evolution/latest \
  --mode fixture \
  --no-network \
  --no-external-writes
```

On success, Foundry writes:

- `run_report.json`
- `action_queue.json`
- `promotion_dossier.md`
- `artifact_manifest.json`

On failure, Foundry exits nonzero and writes actionable stderr. bootstrap must not treat partial artifacts as success.
```

**Verification:**

```bash
grep -n "foundry run action-routing-fixture" docs/foundry-cli-contract.md
```

Expected: command is documented.

### Task 1.2: Document the minimal boundary validation

**Objective:** Keep bootstrap validation thin and mechanical.

Add this boundary-validation rule:

```markdown
bootstrap validates only:

- expected files exist after a successful service run
- JSON files parse
- `schema_version` is present and supported
- `external_writes_allowed` is false for fixture/dry-run mode when present
- `evidence_paths` point to local files under configured report roots
- no service timer is enabled by default

bootstrap does not validate metric meaning, candidate quality, queue priority, or dossier prose.
```

**Verification:**

```bash
grep -n "bootstrap validates only" docs/foundry-cli-contract.md docs/agent-evolution-foundry.md
```

Expected: rule appears in docs.

---

## Milestone 2: Manual Default-Off Foundry Dry-Run Service

**Objective:** Add only the appliance wrapper after Foundry exposes the dry-run command.

**Files:**
- Create: `system/nixos/hermes-evolution-foundry.nix`
- Modify: relevant NixOS module import list
- Create: `tests/foundry-service-contract.py` or shell equivalent

### Task 2.1: Write the service contract test first

**Objective:** Prove the appliance stays safe by default.

Test expectations:

```python
def test_foundry_service_has_no_default_timer(rendered_config):
    assert "hermes-evolution-foundry.timer" not in rendered_config.enabled_timers


def test_foundry_service_is_manual_oneshot(rendered_config):
    service = rendered_config.services["hermes-evolution-foundry-dry-run"]
    assert service.type == "oneshot"
    assert "--no-external-writes" in service.exec_start
    assert "--no-network" in service.exec_start
```

If the repo test harness cannot expose rendered config this way, use the existing static Nix/shell style in this repository and assert on the module text.

**Run:**

```bash
pytest tests/foundry-service-contract.py -q
```

Expected: FAIL until the module exists.

### Task 2.2: Add the disabled/manual service wrapper

**Objective:** Run Foundry locally without owning Foundry semantics.

Implementation constraints:

- `Type=oneshot`
- no timer by default
- configurable Foundry repo/binary path
- configurable input trace path
- configurable report output directory
- `DynamicUser` or dedicated least-privilege user where practical
- output directory created by systemd/Nix activation
- command includes fixture/dry-run safety flags
- service fails closed on nonzero Foundry exit

Do not add Python scripts that render `run_report.json`, `action_queue.json`, or `promotion_dossier.md` in bootstrap.

**Verification:**

```bash
nix flake check
pytest -q
```

Expected: existing suite passes and service contract tests pass.

---

## Milestone 3: Boundary Artifact Smoke Test

**Objective:** Prove bootstrap can invoke Foundry and detect the expected local files without interpreting them.

**Files:**
- Create: `tests/foundry-artifact-smoke.py`
- Modify: service docs only if needed

### Task 3.1: Add a fixture-output smoke test

**Objective:** Validate the wrapper/file boundary.

Test behavior:

1. Use a fake Foundry executable fixture that writes valid minimal files.
2. Run the bootstrap wrapper command against a temp output directory.
3. Assert the files exist.
4. Parse JSON files.
5. Assert `schema_version` exists.
6. Assert no external-write flag is true.

Do not assert queue ranking, metric correctness, candidate quality, or dossier wording.

**Verification:**

```bash
pytest tests/foundry-artifact-smoke.py -q
```

Expected: PASS.

---

## Milestone 4: Optional Scheduled Dry-Run, Still Default-Off

**Objective:** Add scheduling only after the manual wrapper and Foundry demo have value.

**Files:**
- Modify: `system/nixos/hermes-evolution-foundry.nix`
- Modify: tests that assert default-off behavior

### Task 4.1: Add opt-in timer configuration

**Objective:** Allow scheduling without enabling it by default.

Acceptance:

- timer option defaults to disabled
- tests prove disabled by default
- timer command is the same dry-run/fail-closed path
- no live sends
- no GitHub writes
- no production mutation

**Verification:**

```bash
nix flake check
pytest -q
```

Expected: pass.

---

## Foundry-Side Work Required Before Bootstrap Milestone 2

Create or update Foundry issues for:

1. `foundry run action-routing-fixture` deterministic local command.
2. Minimal schemas for `run_report.json`, `action_queue.json`, `promotion_dossier.md`, and `artifact_manifest.json`.
3. Baseline-vs-candidate action-router fixture where baseline fails and candidate passes.
4. Deterministic assertions:
   - exactly one action item for the fixture
   - `bucket` in `needsSteve|autonomous|blocked|stale`
   - `owner`
   - local `evidence_paths`
   - `next_prompt`
   - `expires_at`
   - hard length budget
   - no external writes
5. Promotion dossier renderer in Foundry, not bootstrap.

## Immediate Ready-to-Paste Prompts

### Prompt A — revise bootstrap PR #18 boundary plan

Work in `/home/steve/hermes-bootstrap`. Revise PR #18 so hermes-bootstrap is a thin appliance wrapper for Agent Evolution Foundry. Remove bootstrap-owned evidence renderers, queue ranking, dossier rendering, event-sourced control plane, and SQLite projections from the plan. Keep only NixOS wiring, default-off/manual service wrapper, local artifact storage, retention, and schema-version boundary validation. Run docs/status checks and push the PR branch.

### Prompt B — Foundry action-router fixture

Work in `/home/steve/repos/steezkelly-hermes-agent-self-evolution`. Add a deterministic Foundry demo command for the repeated failure “long briefing instead of concise action queue.” It should emit `run_report.json`, `action_queue.json`, `promotion_dossier.md`, and `artifact_manifest.json` locally with no network or external writes. Baseline action-router fixture must fail at least one assertion; candidate fixture must pass. Add tests and docs.

### Prompt C — bootstrap manual service after Foundry CLI exists

Work in `/home/steve/hermes-bootstrap`. After Foundry exposes the deterministic CLI, add a default-off/manual NixOS oneshot service that invokes it with fixture/dry-run safety flags and stores outputs under a configured local report directory. Add tests proving no timer is enabled by default and no service performs live sends, GitHub writes, or production mutation.
