# Foundry Action-Routing Fixture Wrapper

hermes-bootstrap provides a thin, manual systemd wrapper for the Foundry action-router fixture. The semantic loop remains in Agent Evolution Foundry; bootstrap only invokes it and stores local outputs.

## Provisioning the Foundry checkout

Before the wrapper can run, the Foundry repo must be placed at:

```text
/var/lib/hermes/foundry/hermes-agent-self-evolution
```

Use the provisioning service, which is manual/default-off:

```bash
FOUNDRY_CHECKOUT_SOURCE=/home/admin/steezkelly-hermes-agent-self-evolution \
  systemctl start hermes-provision-foundry-checkout.service
```

The provisioning script accepts:

- A local directory (must contain `evolution/` subdirectory): copies with rsync.
- A local tarball (.tar, .tar.gz): extracts into place.

The script refuses to provision from a network source. If `FOUNDRY_CHECKOUT_SOURCE` is unset, it prints usage and exits 1.

After provisioning, the wrapper service can run the fixture.

## Service

```bash
systemctl start hermes-evolution-foundry-action-routing-fixture.service
```

The service is manual/default-off:

- no timer is defined
- no `wantedBy` auto-start target is defined
- no network or external-write flag is allowed
- no GitHub write path is present
- no credentials or delivery environment file is read

## Expected Foundry checkout

The wrapper expects the Foundry repo at:

```text
/var/lib/hermes/foundry/hermes-agent-self-evolution
```

The command runs from that checkout:

```bash
python3 -m evolution.core.action_routing_demo \
  --out /var/lib/hermes/reports/evolution/action-routing-fixture \
  --mode fixture \
  --no-network \
  --no-external-writes
```

## Output directory

The service writes only under:

```text
/var/lib/hermes/reports/evolution/action-routing-fixture
```

Expected Foundry artifacts:

- `run_report.json`
- `action_queue.json`
- `promotion_dossier.md`
- `artifact_manifest.json`

## Boundary rule

Foundry owns:

- action queue semantics and wording
- gate verdicts
- evidence interpretation
- promotion dossier text

bootstrap owns:

- NixOS/systemd invocation
- users, permissions, and report directories
- disabled/default-off scheduling
- fail-closed local wrapper behavior
- mechanical boundary validation

## Boundary validation

After the fixture runs, validate the output mechanically:

```bash
systemctl start hermes-validate-foundry-action-routing-fixture.service
```

The validator is manual/default-off (no timer, no wantedBy). It checks only:

- All 4 expected files exist
- Each .json file parses as valid JSON
- `schema_version` is a positive integer in every JSON artifact
- `external_writes_allowed` (and safety block) are explicitly `false`

The validator does NOT evaluate:

- Action-item priority or bucket assignments
- Baseline vs. candidate pass/fail verdicts
- Promotion recommendations or dossier prose

Those remain Foundry's responsibility.

## End-to-end manual flow

```bash
# 1. Place the Foundry checkout
FOUNDRY_CHECKOUT_SOURCE=/home/admin/steezkelly-hermes-agent-self-evolution \
  systemctl start hermes-provision-foundry-checkout.service

# 2a. Run the action-routing fixture
systemctl start hermes-evolution-foundry-action-routing-fixture.service

# 2b. Validate the action-routing fixture
systemctl start hermes-validate-foundry-action-routing-fixture.service

# 3a. Run the session-import fixture
systemctl start hermes-evolution-foundry-session-import-fixture.service

# 3b. Validate the session-import fixture
systemctl start hermes-validate-foundry-session-import-fixture.service
```

See `foundry-dry-run-wrapper.md` for the action-routing fixture details.

Do not add bootstrap-side renderers for evidence, queue items, gate verdicts, or promotion dossiers.

## Manual promotion path

After reviewing a fixture's evidence, generate a ready-to-paste gh command:

```bash
hermes-promote-foundry-fixture /var/lib/hermes/reports/evolution/action-routing-fixture
```

Reads the manifest to validate safety gates (external_writes_allowed=false, review_required=true), then outputs a `gh pr create --draft` command. Never executes — operator must copy and paste explicitly.

## Attention-router bridge

After real-trace ingestion has generated a detection report, the manual
attention-router bridge converts detected failure classes into Steve-facing
action items. Bootstrap only invokes Foundry and validates file/safety
boundaries; Foundry owns routing semantics, bucket choice, prompt wording, and
promotion dossier content.

```bash
# 1. Ingest a real trace first
REAL_TRACE_SOURCE=/tmp/export.jsonl \
  systemctl start hermes-evolution-foundry-real-trace-ingestion.service
systemctl start hermes-validate-foundry-real-trace-ingestion.service

# 2. Convert the real-trace detections into action-router artifacts
systemctl start hermes-evolution-foundry-attention-router-bridge.service
systemctl start hermes-validate-foundry-attention-router-bridge.service
```

Output is written under:

```text
/var/lib/hermes/reports/evolution/attention-router-bridge
```

Expected artifacts:

- `run_report.json`
- `action_queue.json`
- `promotion_dossier.md`
- `artifact_manifest.json`

Safety boundary:

- no timer is defined
- no `wantedBy` auto-start target is defined
- no network, GitHub, or credential environment file is used
- `/var/lib/hermes/foundry` is read-only
- `/var/lib/hermes/reports/evolution/real-trace-ingestion` is read-only input
- `/var/lib/hermes/reports/evolution/attention-router-bridge` is the only persistent write path
- `/var/lib/hermes/secrets` is inaccessible

## Pipeline runner

The manual pipeline runner wraps Foundry's `evolution.core.pipeline_runner` and
aggregates fixture or real-trace child reports into one `pipeline_run.json`.
Bootstrap does not judge the pipeline verdict or child verdicts; it only invokes
Foundry with the local-only safety flags and validates the mechanical boundary.

Fixture mode is the default:

```bash
systemctl start hermes-evolution-foundry-pipeline-runner.service
systemctl start hermes-validate-foundry-pipeline-runner.service
```

Real-trace mode requires an operator-selected exported session JSONL:

```bash
hermes sessions export /tmp/export.jsonl
FOUNDRY_PIPELINE_MODE=real_trace \
FOUNDRY_PIPELINE_TRACE=/tmp/export.jsonl \
  systemctl start hermes-evolution-foundry-pipeline-runner.service
systemctl start hermes-validate-foundry-pipeline-runner.service
```

Output is written under:

```text
/var/lib/hermes/reports/evolution/pipeline-runner
```

Expected top-level artifact:

- `pipeline_run.json`

The validator checks that `pipeline_run.json` parses, `schema_version >= 1`,
`external_writes_allowed=false`, child reports are present as an array
(`child_reports`, with Foundry #17's `reports` accepted as the concrete alias),
and the safety block denies network, external writes, GitHub writes, and
production mutation. It does not evaluate verdict correctness.

Safety boundary:

- no timer is defined
- no `wantedBy` auto-start target is defined
- no network, GitHub, or credential environment file is used
- `/var/lib/hermes/foundry` and `/var/lib/hermes/.hermes/sessions` are read-only
- `/var/lib/hermes/reports/evolution/pipeline-runner` is the only persistent write path
- `/var/lib/hermes/secrets` and `/var/lib/hermes/.hermes/.env` are inaccessible

## Real-trace and session-end ingestion

Manual real-trace ingestion remains available for operator-selected exports:

```bash
hermes sessions export /tmp/export.jsonl
REAL_TRACE_SOURCE=/tmp/export.jsonl \
  systemctl start hermes-evolution-foundry-real-trace-ingestion.service
systemctl start hermes-validate-foundry-real-trace-ingestion.service
```

The session-complete hook target is also default-off/manual-only. It is a
single command/service that exports the latest Hermes session to a private temp
JSONL, validates that JSONL, invokes Foundry's real-trace ingestion path with
`--no-network --no-external-writes`, and validates that the generated
`run_report.json` keeps `external_writes_allowed=false`.

```bash
# Hook/command form, for a manually configured session-complete hook:
hermes-session-end-ingest

# Equivalent manual NixOS service invocation:
systemctl start hermes-session-end-ingest.service
```

Output is written under:

```text
/var/lib/hermes/reports/evolution/session-end-ingest
```

Safety boundary:

- no timer is defined
- no `wantedBy` auto-start target is defined
- no network, GitHub, or credential environment file is used
- `/var/lib/hermes/foundry` and `/var/lib/hermes/.hermes/sessions` are read-only
- `/var/lib/hermes/reports/evolution` is the only persistent write path
- `/var/lib/hermes/secrets` and `/var/lib/hermes/.hermes/.env` are inaccessible
