# Hermes Node Harness Phase 1

Phase 1 is a boring, local-only observability loop for the Hermes node.

Gate condition:

```text
systemd timer -> deterministic sensors -> latest snapshot + event JSONL -> deterministic local report
```

## Scope

Phase 1 creates two systemd timers:

- `hermes-node-health-watchdog.timer`: runs every 30 minutes after a 5 minute boot grace period.
- `hermes-daily-local-brief.timer`: renders one deterministic local report at 06:00 UTC.

The watchdog writes:

- `/var/lib/hermes/harness/latest-sensors.json`
- `/var/lib/hermes/harness/state.json`
- `/var/lib/hermes/events/events.jsonl`

The report renderer writes:

- `/var/lib/hermes/reports/daily/YYYY-MM-DD.md`

## Non-goals

- No Hermes cron.
- No Kanban.
- No LLM calls.
- No messaging.
- No mutation or repair actions.
- No secrets access.
- No raw journal capture.
- No dashboards.
- No provider health probing.
- No repo-state automation.

## Service identity

The harness runs as the dedicated system user `hermes-harness` in group `hermes`.
It does not run as `root`, `hermes`, or `hermes-admin`.

The interactive admin can inspect reports through group-readable files.
The harness cannot read `/var/lib/hermes/secrets` under the systemd sandbox.

## Event policy

Healthy runs update `latest-sensors.json` and usually emit no event.
Observed warnings and critical states append bounded, redacted events and keep the unit successful.
Broken observability plumbing, such as an unwritable event/snapshot path, exits nonzero.

Repeated warnings are deduped in `state.json`. A new JSONL event is appended when an issue is first seen, severity changes, recovers, or its rate-limit window expires.
