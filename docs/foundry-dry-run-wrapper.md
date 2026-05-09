# Foundry Action-Routing Fixture Wrapper

hermes-bootstrap provides a thin, manual systemd wrapper for the Foundry action-router fixture. The semantic loop remains in Agent Evolution Foundry; bootstrap only invokes it and stores local outputs.

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

Do not add bootstrap-side renderers for evidence, queue items, gate verdicts, or promotion dossiers.
