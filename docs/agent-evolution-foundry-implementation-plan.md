# Agent Evolution Foundry Appliance Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a safe, reproducible appliance pipeline where hermes-bootstrap runs Hermes Agent as the self-owned runtime habitat and integrates Agent Evolution Foundry as the auditable evidence/evolution loop.

**Architecture:** Hermes Agent remains the runtime/organism. Agent Evolution Foundry remains the crucible that mines traces, builds evals, evolves artifacts, and gates promotion. hermes-bootstrap owns the appliance substrate: NixOS services, local-only evidence contracts, disabled-by-default timers, action queue surfaces, and opt-in promotion wiring.

**Tech Stack:** NixOS modules, systemd services/timers, Python harness scripts, SQLite/JSONL local evidence contracts, pytest + shell static tests, GitHub issues/PRs as promotion surfaces, Hermes Kanban/action queue as Steve-facing execution surface.

---

## Product North Star

Do not build another briefing system. Build a local action engine.

## External Inspiration: Hermes-Symbiosis

Magaav's Hermes-Symbiosis frames a useful adjacent vision: an operating system for humans and agents where coordination, visibility, and resilience merge into a living runtime. Its three-part arc maps cleanly onto this plan:

- Orchestrator coordinates: hermes-bootstrap should coordinate services, timers, evidence, and action queues.
- Space-UI reveals: our immediate equivalent is not a dashboard-heavy UI; it is a concise action queue plus local evidence artifacts that reveal what needs attention.
- Mythos persists: our equivalent is the event/evidence spine plus fail-closed repair/promotion loops that continue safely without pretending every failure is recoverable.

Difference in emphasis: Symbiosis leans toward a living runtime and spatial cockpit. Agent Evolution Foundry + hermes-bootstrap should lean toward auditable self-improvement: local evidence, deterministic contracts, disabled-by-default services, and reviewable promotion. The useful synthesis is **living system feel, appliance-grade safety**.

Reference: https://github.com/Magaav/hackathon-hermes-symbiosis


The successful system produces a concise queue like:

```json
{
  "generated_at": "2026-05-09T00:00:00Z",
  "buckets": {
    "needsSteve": [
      {
        "title": "Approve Foundry dry-run service promotion",
        "why": "Fixture evidence passed; external send remains disabled.",
        "prompt": "Work in /home/steve/hermes-bootstrap. Review the foundry dry-run report at ... and prepare the next gated PR."
      }
    ],
    "autonomous": [],
    "blocked": [],
    "stale": []
  }
}
```

Steve should receive recommended work + ready-to-paste Hermes prompts, not another long digest.

---

## Non-Negotiable Safety Rules

1. No live external sends in Phases 0-3.
2. No timers enabled by default.
3. No GitHub writes from appliance services.
4. No production skill/config mutation without explicit manual promotion.
5. Every generated artifact is local, deterministic, and testable first.
6. Every future PR body must include local evidence paths and commands.
7. Failure is fail-closed: nonzero exit + actionable log, no partial send.

---

## Milestone 0: Contract and Naming Alignment

**Objective:** Make the three-project architecture unambiguous before implementation.

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Create: `docs/agent-evolution-foundry.md`
- Reference: `docs/phase2-boundaries.md`
- Test: `tests/shell-syntax.sh` if touched shell appears; otherwise docs sanity only

### Task 0.1: Add the vocabulary contract

**Objective:** Define the durable mental model.

Add this language to `docs/agent-evolution-foundry.md`:

```markdown
# Agent Evolution Foundry in hermes-bootstrap

Hermes Agent is the runtime/organism: tools, skills, memory, cron, gateway, delegation.

Agent Evolution Foundry is the crucible/evidence loop: traces become evals, evals become experiments, experiments become gated upgrades.

hermes-bootstrap is the habitat/appliance substrate: reproducible NixOS services, local evidence spine, disabled timers, action queues, and opt-in promotion gates.
```

**Verification:**

```bash
grep -R "Hermes Agent is the runtime" README.md SPEC.md docs/agent-evolution-foundry.md
```

Expected: at least one match in docs and a concise pointer from README/SPEC.

**Commit:**

```bash
git add README.md SPEC.md docs/agent-evolution-foundry.md
git commit -m "docs: define Agent Evolution Foundry appliance contract"
```

### Task 0.2: Document explicit out-of-scope claims

**Objective:** Prevent hype drift.

Add an "Out of scope until proven" section:

```markdown
## Out of scope until proven

- Autonomous production mutation
- Live delivery from evolution services
- Claims of general agent self-improvement without holdout evidence
- Reinforcement learning claims for GEPA/prompt optimization
- Automatic upstream PR creation
```

**Verification:**

```bash
grep -n "Out of scope until proven" docs/agent-evolution-foundry.md
```

Expected: section exists.

---

## Milestone 1: Local Evidence Spine

**Objective:** Add deterministic local evidence artifacts that can later feed Foundry without requiring live Hermes, credentials, external sends, or GitHub writes.

**Files:**
- Create: `scripts/harness/render_evolution_evidence.py`
- Create: `tests/test_evolution_evidence.py`
- Create: `docs/evolution-evidence-contract.md`

### Task 1.1: Write fixture evidence schema test

**Objective:** Specify the local evidence contract first.

Create `tests/test_evolution_evidence.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "harness" / "render_evolution_evidence.py"


def run_script(tmp_path):
    output = tmp_path / "evolution-evidence.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output), "--fixture"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return output, result


def test_fixture_evidence_contract(tmp_path):
    output, result = run_script(tmp_path)
    assert result.stdout == ""
    data = json.loads(output.read_text())
    assert data["schema_version"] == 1
    assert data["mode"] == "fixture"
    assert data["external_sends"] == []
    assert data["github_writes"] == []
    assert data["promotion_allowed"] is False
    assert data["source_events"]
    assert data["candidate_actions"]


def test_fixture_evidence_is_deterministic(tmp_path):
    a, _ = run_script(tmp_path / "a")
    b, _ = run_script(tmp_path / "b")
    assert a.read_text() == b.read_text()
```

**Run:**

```bash
pytest tests/test_evolution_evidence.py -q
```

Expected: FAIL because script does not exist.

### Task 1.2: Implement fixture evidence renderer

**Objective:** Produce deterministic fixture output with no stdout on success.

Create `scripts/harness/render_evolution_evidence.py`:

```python
#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def build_fixture_evidence():
    return {
        "schema_version": 1,
        "mode": "fixture",
        "generated_at": "1970-01-01T00:00:00Z",
        "external_sends": [],
        "github_writes": [],
        "promotion_allowed": False,
        "source_events": [
            {
                "event_id": "fixture-session-001",
                "event_type": "hermes.session.completed",
                "summary": "Hermes completed a task and produced a reusable correction.",
            }
        ],
        "candidate_actions": [
            {
                "bucket": "autonomous",
                "title": "Generate eval fixture from completed session",
                "prompt": "Work in Agent Evolution Foundry. Convert fixture-session-001 into a minimal eval example and run local gates only.",
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()

    if not args.fixture:
        raise SystemExit("only --fixture mode is implemented")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_fixture_evidence(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
```

**Run:**

```bash
pytest tests/test_evolution_evidence.py -q
python3 scripts/harness/render_evolution_evidence.py --fixture --output /tmp/evolution-evidence.json
python3 -m json.tool /tmp/evolution-evidence.json >/dev/null
```

Expected: tests pass; command is quiet on success.

**Commit:**

```bash
git add scripts/harness/render_evolution_evidence.py tests/test_evolution_evidence.py docs/evolution-evidence-contract.md
git commit -m "feat: add local evolution evidence contract"
```

---

## Milestone 2: Action Queue Projection

**Objective:** Convert evidence into Steve's preferred output: ranked action queue with ready-to-paste Hermes prompts.

**Files:**
- Create: `scripts/harness/render_evolution_action_queue.py`
- Create: `tests/test_evolution_action_queue.py`
- Update: `docs/evolution-evidence-contract.md`

### Task 2.1: Write action queue schema test

**Objective:** Lock the bucket contract.

Create `tests/test_evolution_action_queue.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "scripts" / "harness" / "render_evolution_evidence.py"
QUEUE = ROOT / "scripts" / "harness" / "render_evolution_action_queue.py"


def test_action_queue_contract(tmp_path):
    evidence = tmp_path / "evidence.json"
    queue = tmp_path / "queue.json"
    subprocess.run([sys.executable, str(EVIDENCE), "--fixture", "--output", str(evidence)], check=True)
    subprocess.run([sys.executable, str(QUEUE), "--input", str(evidence), "--output", str(queue)], check=True)
    data = json.loads(queue.read_text())
    assert data["schema_version"] == 1
    assert set(data["buckets"]) == {"needsSteve", "blocked", "stale", "autonomous"}
    assert data["buckets"]["autonomous"]
    item = data["buckets"]["autonomous"][0]
    assert item["prompt"].startswith("Work in")
    assert data["external_sends"] == []
```

**Run:**

```bash
pytest tests/test_evolution_action_queue.py -q
```

Expected: FAIL because renderer does not exist.

### Task 2.2: Implement action queue renderer

**Objective:** Map candidate actions into stable buckets.

Create minimal renderer that:

- reads evidence JSON
- initializes buckets: `needsSteve`, `blocked`, `stale`, `autonomous`
- copies candidate actions into their bucket
- includes `external_sends: []`
- writes sorted deterministic JSON
- prints nothing on success

**Run:**

```bash
pytest tests/test_evolution_action_queue.py tests/test_evolution_evidence.py -q
```

Expected: pass.

**Commit:**

```bash
git add scripts/harness/render_evolution_action_queue.py tests/test_evolution_action_queue.py docs/evolution-evidence-contract.md
git commit -m "feat: project evolution evidence into action queue"
```

---

## Milestone 3: Default-Off NixOS Dry-Run Service

**Objective:** Package the fixture/evidence/action-queue path as a manual, disabled-by-default NixOS service.

**Files:**
- Modify: `system/nixos/harness.nix` or create `system/nixos/evolution-foundry.nix`
- Modify: `system/nixos/flake.nix` if needed
- Create: `tests/evolution-foundry-static.sh`
- Update: `docs/agent-evolution-foundry.md`

### Task 3.1: Add static test proving no timer exists by default

**Objective:** Preserve delivery-safety pattern.

Create `tests/evolution-foundry-static.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if grep -R "evolution-foundry.*timer" system/nixos; then
  echo "Evolution Foundry timer must not exist in default config" >&2
  exit 1
fi

if ! grep -R "hermes-evolution-foundry-dry-run" system/nixos >/dev/null; then
  echo "Expected dry-run service declaration" >&2
  exit 1
fi
```

**Run:**

```bash
bash tests/evolution-foundry-static.sh
```

Expected: FAIL until service declaration exists.

### Task 3.2: Add manual dry-run service declaration

**Objective:** Service exists, no timer, no credentials.

Add service that roughly executes:

```bash
python3 /path/to/render_evolution_evidence.py --fixture --output /var/lib/hermes/reports/evolution/evidence.json
python3 /path/to/render_evolution_action_queue.py --input /var/lib/hermes/reports/evolution/evidence.json --output /var/lib/hermes/reports/evolution/action-queue.json
```

Constraints:

- `Type=oneshot`
- no `WantedBy=timers.target`
- no secret env files
- creates report directory
- fail-closed on command failure

**Run:**

```bash
bash tests/evolution-foundry-static.sh
bash tests/shell-syntax.sh
pytest -q
```

Expected: all pass.

**Commit:**

```bash
git add system/nixos tests/evolution-foundry-static.sh docs/agent-evolution-foundry.md
git commit -m "feat: add default-off evolution foundry dry-run service"
```

---

## Milestone 4: Cross-Repo Foundry Adapter

**Objective:** Let hermes-bootstrap call a checked-out Agent Evolution Foundry repo in fixture/dry-run mode without making the appliance own the optimizer implementation.

**Files:**
- Create: `scripts/harness/run_evolution_foundry_dry_run.py`
- Create: `tests/test_evolution_foundry_adapter.py`
- Update: `docs/agent-evolution-foundry.md`

### Task 4.1: Define adapter test with missing repo behavior

**Objective:** Missing Foundry repo should fail clearly, not silently.

Test behavior:

```bash
python3 scripts/harness/run_evolution_foundry_dry_run.py --foundry-repo /missing --output /tmp/report.json
```

Expected:

- nonzero exit
- stderr contains `Foundry repo not found`
- no output file

### Task 4.2: Define adapter fixture behavior

**Objective:** If Foundry repo path exists, fixture mode produces local report without network.

Contract:

```json
{
  "schema_version": 1,
  "mode": "fixture",
  "foundry_repo": "/path",
  "commands_run": [],
  "external_sends": [],
  "github_writes": [],
  "promotion_allowed": false
}
```

**Verification:**

```bash
pytest tests/test_evolution_foundry_adapter.py -q
```

**Commit:**

```bash
git add scripts/harness/run_evolution_foundry_dry_run.py tests/test_evolution_foundry_adapter.py docs/agent-evolution-foundry.md
git commit -m "feat: add Agent Evolution Foundry dry-run adapter"
```

---

## Milestone 5: Promotion Dossier, Not Auto-Promotion

**Objective:** Generate a review dossier that a human/agent can use to create PRs, but do not create PRs from the appliance service.

**Files:**
- Create: `scripts/harness/render_evolution_promotion_dossier.py`
- Create: `tests/test_evolution_promotion_dossier.py`
- Update: `docs/evolution-evidence-contract.md`

### Task 5.1: Write dossier test

**Objective:** Dossier includes evidence paths and explicit manual prompt.

Expected fields:

```json
{
  "schema_version": 1,
  "promotion_allowed": false,
  "manual_only": true,
  "evidence_paths": ["..."],
  "recommended_prompt": "Work in ...",
  "github_writes": []
}
```

### Task 5.2: Implement dossier renderer

**Objective:** Convert action queue + evidence into a manual promotion package.

The dossier is allowed to say:

- what changed
- what tests passed
- what prompt to paste into Hermes
- what files contain evidence

The dossier is not allowed to:

- run `gh pr create`
- send messages
- mutate production skills

**Verification:**

```bash
pytest tests/test_evolution_promotion_dossier.py tests/test_evolution_action_queue.py tests/test_evolution_evidence.py -q
```

**Commit:**

```bash
git add scripts/harness/render_evolution_promotion_dossier.py tests/test_evolution_promotion_dossier.py docs/evolution-evidence-contract.md
git commit -m "feat: render manual evolution promotion dossiers"
```

---

## Milestone 6: First Useful End-to-End Drill

**Objective:** Prove the appliance can generate a local action queue and promotion dossier from fixtures in one command.

**Files:**
- Create: `scripts/harness/evolution_foundry_drill.py`
- Create: `tests/test_evolution_foundry_drill.py`
- Update: `docs/agent-evolution-foundry.md`

### Task 6.1: Build one-command local drill

Command:

```bash
python3 scripts/harness/evolution_foundry_drill.py --output-dir /tmp/hermes-evolution-drill --fixture
```

Expected artifacts:

```text
/tmp/hermes-evolution-drill/evidence.json
/tmp/hermes-evolution-drill/action-queue.json
/tmp/hermes-evolution-drill/promotion-dossier.json
```

Expected behavior:

- quiet on success unless `--verbose`
- deterministic fixture output
- no external sends
- no GitHub writes
- nonzero if any artifact fails validation

### Task 6.2: Add final verification target

Run:

```bash
bash tests/shell-syntax.sh
bash tests/evolution-foundry-static.sh
pytest -q
python3 scripts/harness/evolution_foundry_drill.py --fixture --output-dir /tmp/hermes-evolution-drill
python3 -m json.tool /tmp/hermes-evolution-drill/action-queue.json >/dev/null
```

Expected: all pass.

**Commit:**

```bash
git add scripts/harness/evolution_foundry_drill.py tests/test_evolution_foundry_drill.py docs/agent-evolution-foundry.md
git commit -m "feat: add local Agent Evolution Foundry appliance drill"
```

---

## Parallel Track in Agent Evolution Foundry Repo

This hermes-bootstrap plan depends on a paired Foundry-side plan in `/home/steve/repos/steezkelly-hermes-agent-self-evolution`.

Recommended next Foundry PRs:

1. Rename public identity from Agent Evolution Lab to Agent Evolution Foundry.
   - `README.md`
   - `pyproject.toml` description if appropriate
   - `docs/philosophy.md`
   - issue #9 title/body

2. Add deterministic demo mode.
   - command emits run report with no live LLM calls
   - checks report schema
   - no GitHub writes

3. Split PR #1.
   - observatory core
   - content evolution mode
   - fitness hooks

4. Add appliance adapter output contract.
   - Foundry produces `evidence.json`, `run-report.json`, and `promotion-dossier.json` compatible with hermes-bootstrap.

---

## Ready-To-Paste Execution Prompts

### Prompt 1: docs-only contract PR

Work in `/home/steve/hermes-bootstrap`. Implement Milestone 0 from `docs/agent-evolution-foundry-implementation-plan.md`. Keep it docs-only. Define Hermes Agent as runtime/organism, Agent Evolution Foundry as crucible/evidence loop, and hermes-bootstrap as appliance habitat. Include out-of-scope claims and safety boundaries. Run available docs/static checks. Open a PR with local evidence.

### Prompt 2: local evidence spine PR

Work in `/home/steve/hermes-bootstrap`. Implement Milestone 1 from `docs/agent-evolution-foundry-implementation-plan.md`. Use TDD. Add deterministic fixture evidence renderer, tests, and evidence contract docs. It must be quiet on success, deterministic, and prove no external sends/GitHub writes. Run `pytest tests/test_evolution_evidence.py -q` and full `pytest -q`.

### Prompt 3: action queue PR

Work in `/home/steve/hermes-bootstrap`. Implement Milestone 2 from `docs/agent-evolution-foundry-implementation-plan.md`. Convert local evolution evidence into an action queue with buckets `needsSteve`, `blocked`, `stale`, `autonomous` and ready-to-paste Hermes prompts. Run focused tests and full pytest.

### Prompt 4: default-off NixOS service PR

Work in `/home/steve/hermes-bootstrap`. Implement Milestone 3 from `docs/agent-evolution-foundry-implementation-plan.md`. Add a manual/default-off NixOS dry-run service for Agent Evolution Foundry fixture reports. Add static tests proving no timer exists by default and no credentials/live sends are required. Run shell syntax tests and pytest.

### Prompt 5: Foundry-side identity/deterministic demo

Work in `/home/steve/repos/steezkelly-hermes-agent-self-evolution`. Rename public positioning from Agent Evolution Lab to Agent Evolution Foundry and add a deterministic demo/report mode that hermes-bootstrap can call without live LLMs. Keep claims falsifiable: artifact evolution, evidence, gates, reports. Run full pytest and update issue #9.

---

## Definition of Done for the First Valuable Slice

The first valuable slice is complete when all of this is true:

1. `hermes-bootstrap` has docs explaining the three-part architecture.
2. A fixture command creates local evolution evidence JSON.
3. A second command converts it into an action queue with ready-to-paste prompts.
4. A manual/default-off NixOS dry-run service can run the fixture path.
5. Tests prove no timers, sends, GitHub writes, or credentials are involved.
6. `Agent Evolution Foundry` has a deterministic demo/report mode compatible with the bootstrap artifact contract.

This is the minimum useful bridge from vision to appliance.