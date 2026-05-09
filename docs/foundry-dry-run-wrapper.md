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

## Manual promotion path

After reviewing a fixture's evidence, generate a ready-to-paste gh command:

```bash
hermes-promote-foundry-fixture /var/lib/hermes/reports/evolution/action-routing-fixture
```

This reads the artifact_manifest.json and promotion_dossier.md, validates safety gates, and outputs a gh pr create command. It never executes — the operator must copy and paste explicitly.

Do not add bootstrap-side renderers for evidence, queue items, gate verdicts, or promotion dossiers.
