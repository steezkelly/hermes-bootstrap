# Phase 2 boundaries

Phase 2 should turn the local Phase 1 harness into useful push-based operator delivery without weakening the appliance model.

Do not start Phase 2 until `docs/phase1-live-validation.md` passes on live hardware.

## Philosophy

The node should reduce attention fragmentation, not create another dashboard to babysit.

Phase 1 deliberately made the node boring:

```text
systemd timer -> deterministic sensors -> local JSON/report artifacts
```

Phase 2 may add delivery and synthesis, but the local artifacts remain the source of truth.

## Allowed additions

Phase 2 may add:

- one daily pushed brief from the latest local report
- bounded urgent alerts for critical events
- operator acknowledgement state for repeated critical conditions
- optional LLM summarization of already-redacted local reports
- optional Hermes cron/Kanban tasks that consume local artifacts
- local backoff/rate-limit state for delivery attempts

## Explicit non-goals

Phase 2 must not add:

- raw journal export
- provider-key or secret access from the harness identity
- self-repair actions
- public gateway exposure
- chatty per-sensor notifications
- dashboard-only workflows that require polling
- delivery paths that bypass the local report/event artifacts

## Source-of-truth rule

Push delivery must be derived from files under:

- `/var/lib/hermes/harness/`
- `/var/lib/hermes/events/`
- `/var/lib/hermes/reports/`

If an alert cannot be reconstructed from those files, it should not be sent.

## Identity rule

Keep identities separate:

- `hermes-harness`: deterministic local sensors and local reports only
- `hermes`: Hermes Agent runtime
- `hermes-admin`: interactive operator/debugging account

A Phase 2 delivery service may run as a separate least-privilege identity if it needs messaging credentials. It should read only the local reports/events it needs and its own delivery secret, not `/var/lib/hermes/secrets/hermes.env` wholesale.

## Delivery behavior

Default target should be one quiet daily brief.

Critical alerts should be bounded:

- dedupe by event id and severity
- use a minimum resend window
- include the source file path and timestamp
- include the exact operator command needed to inspect locally
- avoid raw command output unless it is already in the redacted local artifact

Warnings should normally wait for the daily brief unless they persist or escalate.

## LLM behavior

LLM use is optional and must be downstream of redaction.

Allowed:

- summarize a daily report
- group repeated events into a short operator narrative
- propose questions for the operator

Not allowed:

- inspect secrets
- read raw journals
- call tools to mutate the host
- decide repairs autonomously

The deterministic Markdown report must remain useful when LLM delivery is disabled.

## Suggested Phase 2 gate

A minimal Phase 2 gate should prove:

```text
local report exists -> delivery renderer builds bounded message -> dry-run output matches fixture -> live send succeeds once -> repeated send is deduped/rate-limited
```

Recommended test shape:

- fixture daily report with OK state
- fixture daily report with warning state
- fixture event JSONL with repeated critical state
- dry-run renderer test with no network
- static test proving no raw `/var/lib/hermes/secrets/hermes.env` dependency

## Minimal dry-run implementation boundary

The first checked-in Phase 2 artifact is intentionally not a sender. `scripts/harness/render_delivery_brief.py` proves the deterministic conversion step only:

```text
/var/lib/hermes/reports/daily/YYYY-MM-DD.md
+ /var/lib/hermes/harness/latest-sensors.json
+ /var/lib/hermes/events/events.jsonl
-> bounded operator message on stdout
```

Properties:

- reads only local Phase 1 artifacts
- performs no network delivery
- uses the existing harness redaction helper before output
- includes source paths and local inspect commands
- caps message length with an explicit truncation note
- keeps channel choice, credentials, live-send service, and acknowledgement state out of scope until live Phase 1 passes

NixOS wires this renderer as a manual, disabled-by-default oneshot service named `hermes-phase2-delivery-brief-dry-run`. It has no timer and no `wantedBy`; operators can start it explicitly to inspect the would-be push payload in the service journal before any delivery channel exists.

Live validation notes:

- When copying a desktop checkout to the appliance work directory with rsync, exclude generated boot image contents: `rsync -a --delete --exclude .git --exclude boot-image ...`. The `boot-image/rootfs` tree can contain root-owned shadow/crontab/apk lock files that are not readable by the desktop user and are not needed for refreshing `/etc/nixos` plus harness scripts.
- A completed successful oneshot normally becomes `inactive (dead)`. `systemctl status hermes-phase2-delivery-brief-dry-run.service` may therefore return shell exit code 3 even when the run succeeded. Verify the actual result with `systemctl show hermes-phase2-delivery-brief-dry-run.service -p ExecMainCode -p ExecMainStatus -p Result -p ActiveState --no-pager`; expected values are `Result=success`, `ExecMainCode=0`, `ExecMainStatus=0`, `ActiveState=inactive`.

This lets the repo test the source-of-truth and no-secret/no-raw-journal contract while the live node finishes Phase 1 validation.

## Recommended next live-send shape

The first actual delivery implementation should still be systemd-owned, not Hermes-cron-owned, and should remain disabled-by-default until one manual send is validated. Recommended choices before writing code:

- channel: email first if a local SMTP/Gmail path is already available; otherwise Telegram/Discord only with an explicit user-selected target
- credentials: a separate Phase 2 delivery env file, not `/var/lib/hermes/secrets/hermes.env` wholesale
- service identity: a separate least-privilege delivery user if credentials are required; do not grant `hermes-harness` secret access
- payload: the dry-run renderer output exactly, not raw events or journals
- live gate: one manual send succeeds once, then repeated sends are deduped/rate-limited before any timer is enabled

## Open design questions

Decide before implementation:

1. Delivery channel: email, Telegram, Discord, local mail, or Hermes-origin chat?
2. Credential location: separate Phase 2 delivery env file or Hermes Agent provider config?
3. Should the delivery service be systemd-owned or Hermes-cron-owned?
4. Should daily delivery include the full local report or a short summary plus path?
5. What counts as an urgent critical alert versus a daily-brief item?

Default recommendation: start with systemd-owned dry-run rendering and one explicit manual live send, then consider Hermes cron only after the local service has proven stable.
