# Hermes-Symbiosis assimilation notes

This document records what is worth borrowing from `Magaav/hackathon-hermes-symbiosis` and `Magaav/hermes-orchestrator` without changing the safety boundary of this bootstrap appliance.

The useful idea is not to copy a UI or fleet manager into this repository. The useful idea is the operating pattern:

```text
Coordinate -> reveal -> persist
```

Hermes-Symbiosis phrases the loop as Orchestrator coordinates, Space-UI reveals, and Mythos/Exhaust persists. In `hermes-bootstrap`, the same shape should stay smaller, local, and appliance-safe.

## Translation for hermes-bootstrap

| Symbiosis layer | Bootstrap equivalent | Current safe artifact | Next safe artifact |
| --- | --- | --- | --- |
| Orchestrator coordinates | systemd/NixOS coordinates local services | Phase 1 timers, daily report renderer, default-off delivery timer | explicit service graph docs and rollback probes |
| Space-UI reveals | local renderers reveal operator attention | `render_delivery_brief.py`, `render_critical_alerts.py`, service journals | short action cards derived from local reports/events |
| Mythos/Exhaust persists | local state prevents repeated failure loops | delivery state and event ids | critical alert acknowledgement state |

## Hard boundaries

Do not import external orchestration code into this appliance just because the naming overlaps.

Do not add a visual cockpit dependency to the node before the boring local control plane is complete.

Do not add retry/exhaust behavior that mutates the host. Bootstrap persistence means bounded acknowledgement, dedupe, and evidence trails; it does not mean autonomous self-repair.

No automatic delivery should be added as part of Symbiosis assimilation. Any recurring external send remains controlled by the existing explicit opt-in timer policy.

## Concrete next step

The highest-value next implementation is critical alert acknowledgement state:

```text
local critical events -> critical alert candidate renderer -> acknowledgement/dedupe state -> manual proof -> optional live alert decision
```

Acceptance criteria before any live critical-alert sender:

1. Acknowledgement state is stored under a delivery/alerts state directory owned by the least-privilege service identity.
2. Repeated critical events with the same stable event id are collapsed and marked as known until the acknowledgement window expires or the event changes materially.
3. State never records secrets, topics, raw journal lines, or full payloads.
4. Dry-run output can explain whether an alert is new, known-unacknowledged, acknowledged, or expired.
5. Tests prove warnings do not become urgent alerts and no timer/send path is introduced.
6. Live validation starts only the dry-run service and confirms no `hermes-phase2*` timer and no ntfy/email send marker.

## Why this belongs here

`hermes-bootstrap` is the reproducible habitat for a single Hermes Agent node. It should not become the whole Hermes-Symbiosis stack. It should, however, make the single-node substrate ready for that stack by producing reliable local artifacts, bounded operator messages, and durable local state that a future orchestrator or UI can consume safely.
