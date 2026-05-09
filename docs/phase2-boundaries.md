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

The repo now has a fail-closed delivery abstraction in `scripts/harness/send_delivery_brief.py`. Its successful transports are `--transport dry-run` and explicitly configured `--transport ntfy`; `--transport email` exits non-zero with "email transport is not implemented" until an email credential plan exists.

NixOS also defines a disabled-by-default manual service named `hermes-phase2-delivery-brief-send`. It runs as `hermes-delivery`, has no timer, reads the local Phase 1 artifacts read-only, and currently invokes `send_delivery_brief.py --transport ntfy`. Without `/var/lib/hermes/delivery/ntfy.env` defining `HERMES_DELIVERY_NTFY_TOPIC` or `HERMES_DELIVERY_NTFY_URL`, it fails closed before sending.

For an accountless push path, ntfy is the preferred first provider: publishing is a simple HTTP POST and topics are created on the fly with no signup. The caveat is that public `ntfy.sh` topics are capability URLs/topics: choose a high-entropy topic and treat it as a delivery secret. Receiving still requires subscribing from a phone/desktop app, but does not require creating a provider account.

ntfy fail-closed live validation passed on the appliance at commit `e8fd44e`: `hermes-delivery` existed, `/var/lib/hermes/delivery` was `hermes-delivery:hermes` mode `2750`, the send service had `EnvironmentFile=-/var/lib/hermes/delivery/ntfy.env`, no Phase 2 timer existed, and removing `ntfy.env` made a manual start fail closed with `Result=exit-code`, `ExecMainCode=1`, `ExecMainStatus=2`, plus the journal text `ntfy transport requires HERMES_DELIVERY_NTFY_URL or HERMES_DELIVERY_NTFY_TOPIC. No message was sent.` Both `hermes-delivery` and `hermes-harness` remained unable to read `/var/lib/hermes/secrets/hermes.env`.

Fail-closed manual-send live validation passed on the appliance at commit `4b00cfd`: `hermes-delivery` existed, the service had no timer, `InaccessiblePaths=-/var/lib/hermes/secrets` was present, and a manual start failed closed with `Result=exit-code`, `ExecMainCode=1`, `ExecMainStatus=2`, plus the journal text `email transport is not implemented. No message was sent.` Both `hermes-delivery` and `hermes-harness` remained unable to read `/var/lib/hermes/secrets/hermes.env`.

The first actual delivery implementation should still be systemd-owned, not Hermes-cron-owned, and should remain disabled-by-default until one manual send is validated. Recommended choices before writing code:

- channel: email first if a local SMTP/Gmail path is already available; otherwise Telegram/Discord only with an explicit user-selected target
- credentials: a separate Phase 2 delivery env file, not `/var/lib/hermes/secrets/hermes.env` wholesale
- service identity: a separate least-privilege delivery user if credentials are required; do not grant `hermes-harness` secret access
- payload: the dry-run renderer output exactly, not raw events or journals
- live gate: one manual send succeeds once, then repeated sends are deduped/rate-limited before any timer is enabled

## First ntfy live-send gate

Before sending the first real notification:

1. Generate a high-entropy topic on the node or desktop, for example `python3 - <<'PY'` with `secrets.token_urlsafe(32)`.
2. Subscribe to `https://ntfy.sh/<topic>` in the ntfy phone app or web UI.
3. Write `/var/lib/hermes/delivery/ntfy.env` on the node as root with owner `hermes-delivery:hermes`, mode `0640`, and a single line `HERMES_DELIVERY_NTFY_TOPIC=<topic>`.
4. Start `hermes-phase2-delivery-brief-send.service` manually once.
5. Verify exactly one notification is received and the journal shows only delivery status/metadata, not the topic or payload secret.
6. Keep Phase 2 timers disabled until dedupe/rate-limit state is live-validated.

## Delivery dedupe/rate-limit state

The sender supports stateful safety gates for automation:

- `--state-dir /var/lib/hermes/delivery/state` stores `delivery-state.json` owned by `hermes-delivery`.
- `--once-per-date` skips an identical successful payload for the same date/transport.
- `--min-interval-seconds 82800` skips any send if the last success was less than 23 hours ago.
- Skips exit `0` and print a clear `Delivery skipped: ...` line; they do not contact ntfy.
- Successful ntfy sends record the resolved report date, transport, message SHA-256, and send epoch. The topic/url is not recorded.

The manual send service is now wired with those gates but still has no timer. Directory materialization is handled by `system.activationScripts.hermesHarnessDirectories`, not `systemd.tmpfiles.rules`, because live validation found `systemd-tmpfiles-resetup.service` can fail with status 73 unsafe path transitions when `/var/lib/hermes` is owned by `hermes` and child directories are owned by service users (`hermes-harness`/`hermes-delivery`). The activation script depends on the NixOS `users` activation step and explicitly creates `/var/lib/hermes/delivery/state` as `hermes-delivery:hermes` mode `2770` before service use.

Live validation should prove both paths before enabling scheduled delivery: first one successful send creates state, then an immediate second manual start skips without emitting another ntfy request.

### Strict delivery validation doctrine

Use this doctrine for every future live delivery validation, even outside ntfy:

1. Resolve the report date and render/hash the payload before checking duplicate-send gates.
2. Materialize state directories before service use; do not rely on tmpfiles when parent/child ownership crosses service users.
3. Treat one real delivery as the maximum normal validation budget. Any second delivery attempt needs a new explicit reason, not just "the notification did not appear yet."
4. Diagnose provider receipt/client subscription separately from Hermes delivery. If the transport returned success, inspect provider history/subscription/client state before resending.
5. Keep timers disabled until both paths are proven: one successful manual send writes success state, then a second manual start skips before contacting the provider.
6. Never print capability topics, URLs, tokens, or payload secrets in handoff output. If a capability topic was surfaced, rotate before durable use.
7. Failed sends must not write `last_success`; skipped sends should exit 0 and make clear that no provider call was made.

First ntfy live-send validation at commit `f642acb` is PASS after corrected receipt diagnosis: one manual send returned `Result=success`, `ExecMainCode=0`, `ExecMainStatus=0`, and the service journal showed `Transport: ntfy` plus `Delivery status: HTTP 200`; no topic was printed and no Phase 2 timer existed. The message appeared in ntfy history/UI with the expected `Hermes node brief` title and the bounded daily-brief payload. The initial "not received" report was caused by manually copying a subscription URL from wrapped terminal output and truncating the final two topic characters, not by Hermes service code, node networking, or ntfy publish failure.

Because ntfy topics are capability secrets and the validation topic was surfaced in operator handoff output, continue treating the topic as secret and rotate to a fresh high-entropy topic before any durable delivery setup.

## ntfy receipt diagnostic gate

Diagnose receipt separately from Hermes delivery. If ntfy returns HTTP 200 but no notification appears, do not resend Hermes first. Safe checks before any resend:

1. Confirm the ntfy app/web subscription topic exactly matches `/var/lib/hermes/delivery/ntfy.env` without printing the topic into shared logs.
2. Avoid manually retyping or copying from wrapped terminal output; prefer copying from the node-side env file, or generate a QR/deep link for subscription.
3. Check browser/app notification permission, battery/background restrictions, and whether the web page/app is actively subscribed.
4. Poll/inspect ntfy history for the topic before resending; history can prove server-side receipt even when push display failed or the client subscribed to a mistyped topic.
5. If an additional controlled publish is authorized, send a short non-Hermes test message to the same topic or a freshly rotated topic, record whether web/app receives it, then stop again.

## Critical alert candidate renderer

The next bounded-alert step is a local, no-send critical alert candidate renderer, not an always-on urgent sender. `scripts/harness/render_critical_alerts.py` reads only `/var/lib/hermes/events/events.jsonl` and `/var/lib/hermes/harness/latest-sensors.json`, filters for critical events on the selected date, collapses repeated emissions by event id, redacts token-like values, caps output length, and prints explicit local inspect commands.

NixOS wires it as a manual disabled-by-default oneshot named `hermes-phase2-critical-alert-dry-run`. It has no timer, no `wantedBy`, no delivery credentials, no network transport, no raw journal export, and only writes local acknowledgement/dedupe metadata when `--state-dir` is configured. Operators can start it manually to inspect what would be considered an urgent alert candidate before adding any live critical-alert sender.

## Critical alert acknowledgement/dedupe state

The critical alert dry-run now supports local state at `/var/lib/hermes/delivery/state/alerts/critical-alert-state.json`. This remains a no-send dry-run path: the state file is local metadata only and does not introduce ntfy/email credentials, transport code, timers, or `wantedBy` wiring.

State records only safe metadata:

- stable event id, or a bounded `hash:<prefix>` key when no id exists
- `condition_hash` for the material critical condition
- severity/status fields such as `severity`, `last_status`, and `state`
- `first_seen`, `last_seen`, `seen_count`, and optional acknowledgement/expiry timestamps
- acknowledgement markers such as `acknowledged` and `acknowledged_at`

State must not store ntfy topics, URLs, tokens, raw journal lines, event details, summaries, or full payloads. Material comparison may hash redacted summary/detail in memory, but only the hash is persisted.

Dry-run output classifies critical candidates as `new, repeated/known, acknowledged, or expired`:

- `new`: first local sighting of a critical condition, or a previously expired condition that reappears.
- `repeated/known`: same stable event id/hash and same `condition_hash` after it is already in state.
- `acknowledged`: same condition has been manually marked acknowledged in the local state file.
- `expired`: a previously active critical state is absent from the selected date's critical events; warning events alone do not become urgent alerts.

The NixOS dry-run service runs as `hermes-harness`, reads `/var/lib/hermes/harness` and `/var/lib/hermes/events`, and writes only `/var/lib/hermes/delivery/state/alerts`. The activation script creates that directory explicitly as `hermes-harness:hermes` mode `2770`.

Live validation remains manual and no-send: list Phase 2 timers, start only `hermes-phase2-critical-alert-dry-run.service`, inspect its result/journal, and confirm there are no ntfy/email send markers.

Live no-send validation passed on the mini-PC at commit `8f938d3`: after applying the config with `phase2DeliveryTimerEnabled = false`, `systemctl list-timers "hermes-phase2*" --all` returned `0 timers listed`; manual start of `hermes-phase2-critical-alert-dry-run.service` returned `Result=success`, `ExecMainCode=0`, `ExecMainStatus=0`, `ActiveState=inactive`; the journal printed `No message was sent.` and no ntfy/email send markers; `/var/lib/hermes/delivery/state/alerts/critical-alert-state.json` existed with only `critical_alerts` and `last_render_date` metadata.

Operators can acknowledge an existing local critical-alert state record without editing JSON by running:

```bash
sudo -u hermes-harness /run/current-system/sw/bin/python3 \
  /etc/nixos/harness-scripts/ack_critical_alert.py \
  --state-dir /var/lib/hermes/delivery/state/alerts \
  --event-id <existing-critical-event-id>
```

`ack_critical_alert.py` only mutates `critical-alert-state.json`. It rejects missing event ids by default, records `acknowledged=true`, `acknowledged_at`, `acknowledged_by`, and keeps summaries, details, comments, raw payloads, journals, topics, URLs, tokens, and delivery credentials out of state. A later renderer run reports the matching condition as `[acknowledged]`.

## Future critical-alert live-send design gate

Do not implement critical-alert live delivery until this design is explicitly accepted. The intended future gate is:

1. Dedupe key: stable event id or hash key plus `condition_hash`, not the rendered payload text.
2. Resend window: no repeated live alert for the same unacknowledged condition until a configured minimum interval has elapsed; acknowledged conditions should not send again unless the condition hash changes.
3. One-send validation budget: the first live critical alert validation may perform exactly one provider send, then an immediate second start must skip before provider contact.
4. Failure behavior: missing credentials, unsupported transports, corrupt state, or provider failure must fail closed and must not write success state.
5. State transitions: `new` -> live-send attempted/sent -> `known`; `known` -> `acknowledged` by local operator command; `known`/`acknowledged` -> `new: changed` when `condition_hash` changes; absent critical candidates -> `expired`.
6. Steve decision boundary: enabling any critical-alert sender, adding credentials, or enabling any recurring/timer path requires an explicit operator decision separate from this dry-run/acknowledgement state work.

This preserves the Phase 2 alert order:

```text
local events exist -> critical alert candidate renderer -> dry-run service -> acknowledgement/dedupe state -> explicit live alert decision -> optional scheduler
```

Do not wire critical candidates to ntfy/email automatically until there is local acknowledgement state that can distinguish a new unresolved critical condition from a repeated known condition.

## Credential/transport decision boundary

Discovery found no ready email transport on the desktop or node:

- no Himalaya config or binary usable for sending
- no Google Workspace/Gmail OAuth token/client secret
- no msmtp config
- node has `python3`, `curl`, and `hermes`, but no mailer CLI

The next code change should not add credentials directly to the existing Hermes secret env. If avoiding account creation is the priority, prefer ntfy first:

1. ntfy on the node: no provider account, no mailer package, HTTP POST via Python stdlib; requires only a high-entropy topic stored in `/var/lib/hermes/delivery/ntfy.env`.
2. Gmail API on the node: add a small Python/curl sender plus a dedicated credential file or systemd credential containing only Gmail send scope material.
3. SMTP on the node: add msmtp or equivalent plus a dedicated SMTP credential/config file.
4. Hermes gateway bridge: treat it as a platform-message path, not email, and design an explicit node-to-gateway API/auth boundary.

After ntfy receipt and dedupe/rate-limit state are live-validated, the scheduled delivery path may be represented in NixOS, but the timer must remain disabled by default. `deployment-options.nix` exposes `phase2DeliveryTimerEnabled = false` and `phase2DeliveryTimerCalendar = "*-*-* 06:10:00"`; flipping the boolean is an explicit operator decision because it creates an automatic external-send path.

## Open design questions

Decide before implementation:

1. Delivery channel: email, Telegram, Discord, local mail, or Hermes-origin chat?
2. Credential location: separate Phase 2 delivery env file or Hermes Agent provider config?
3. Should the delivery service be systemd-owned or Hermes-cron-owned?
4. Should daily delivery include the full local report or a short summary plus path?
5. What counts as an urgent critical alert versus a daily-brief item?

Default recommendation: start with systemd-owned dry-run rendering and one explicit manual live send, then consider Hermes cron only after the local service has proven stable.
