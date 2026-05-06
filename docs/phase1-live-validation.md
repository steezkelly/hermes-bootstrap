# Phase 1 live-node validation

Phase 1 is considered live-ready only after the deployed node proves the same boring path the repo tests enforce:

```text
systemd timer/service -> deterministic sensors -> latest snapshot + JSONL events -> deterministic local report
```

Use this checklist after install, repair, or rebuild. It is intentionally one-command-at-a-time friendly for console or SSH sessions.

## Scope

Validate only the local observability harness:

- `hermes-node-health-watchdog.service`
- `hermes-node-health-watchdog.timer`
- `hermes-daily-local-brief.service`
- `hermes-daily-local-brief.timer`
- `/var/lib/hermes/harness/latest-sensors.json`
- `/var/lib/hermes/harness/state.json`
- `/var/lib/hermes/events/events.jsonl`
- `/var/lib/hermes/reports/daily/*.md`

Do not use Hermes cron, Kanban, LLM calls, messaging, dashboards, or repair automation as part of this validation.

## 1. Reachability and service baseline

```bash
hostname
systemctl is-active hermes-agent
systemctl is-enabled hermes-node-health-watchdog.timer hermes-daily-local-brief.timer
systemctl list-timers 'hermes-*' --no-pager
```

Expected:

- `hermes-agent` is `active`.
- Both harness timers are enabled or otherwise scheduled by the NixOS generation.
- The watchdog timer has a next run and the daily brief timer has a next 06:00 UTC run.

## 2. Identity and permissions

```bash
getent passwd hermes-harness
id hermes-harness
sudo stat -c '%U:%G %a %n' /var/lib/hermes/harness /var/lib/hermes/events /var/lib/hermes/reports /var/lib/hermes/reports/daily
```

Expected:

- `hermes-harness` exists as a system account.
- `hermes-harness` is in group `hermes`.
- Harness directories are owned by `hermes-harness:hermes` and mode `2770`.

Verify the harness cannot read secrets:

```bash
sudo -u hermes-harness test ! -r /var/lib/hermes/secrets/hermes.env; echo $?
```

Expected: `0`.

A result of `1` means the harness can read the secrets file and the deployment is not acceptable.

## 3. Run watchdog once

```bash
sudo systemctl start hermes-node-health-watchdog.service
systemctl status hermes-node-health-watchdog.service --no-pager
sudo stat -c '%U:%G %a %n' /var/lib/hermes/harness/latest-sensors.json /var/lib/hermes/harness/state.json /var/lib/hermes/events/events.jsonl
```

Expected:

- The service exits successfully.
- Snapshot/state/event files are group-readable and not world-readable.
- Healthy runs may leave `events.jsonl` empty or absent until the first warning; a missing file is acceptable only if the service status shows success and `latest-sensors.json` exists.

Inspect bounded output without exposing secrets:

```bash
sudo python3 -m json.tool /var/lib/hermes/harness/latest-sensors.json | sed -n '1,120p'
sudo tail -n 20 /var/lib/hermes/events/events.jsonl 2>/dev/null || true
```

Expected:

- JSON parses.
- `overall_status` is `ok`, `warning`, or `critical`.
- Events, if present, are bounded summaries and do not contain provider keys, bearer tokens, passwords, or raw journal dumps.

## 4. Render daily report once

```bash
sudo systemctl start hermes-daily-local-brief.service
systemctl status hermes-daily-local-brief.service --no-pager
sudo find /var/lib/hermes/reports/daily -maxdepth 1 -type f -name '*.md' -printf '%TY-%Tm-%Td %TH:%TM %u:%g %m %p\n' | sort | tail -n 5
```

Expected:

- The service exits successfully.
- A dated Markdown report exists under `/var/lib/hermes/reports/daily/`.
- Report mode is group-readable and not world-readable.

Inspect the newest report:

```bash
sudo sh -c 'latest=$(find /var/lib/hermes/reports/daily -maxdepth 1 -type f -name "*.md" | sort | tail -n 1); test -n "$latest" && sed -n "1,160p" "$latest"'
```

Expected:

- The report starts with `# Hermes Node Daily Local Brief`.
- The report includes status, recent events, and source paths.
- The report does not include raw `journalctl` output or secrets.

## 5. Admin readability regression check

The console admin must be able to inspect Hermes status without tripping over service-created state files:

```bash
sudo -u hermes-admin HERMES_HOME=/var/lib/hermes/.hermes hermes status
```

Expected: command exits successfully.

If it fails with `PermissionError` under `/var/lib/hermes/.hermes/cron/`, the installed Hermes Agent source is still enforcing upstream cron state permissions (`0700` directories / `0600` files). Re-run `scripts/repair-installed-hermes.sh --no-reboot` from a refreshed bootstrap checkout and rebuild/restart. The repair path patches staged `/etc/nixos/hermes-agent-src/cron/jobs.py` so Hermes cron uses group-readable appliance permissions (`2770` directories / `0660` files) instead of repeatedly undoing the NixOS-level `UMask=0007` and `ExecStartPost` repair.

## Exit criteria

Phase 1 live validation passes when:

- Both harness timers are present.
- The `hermes-harness` account exists and cannot read `/var/lib/hermes/secrets/hermes.env`.
- The watchdog can write `latest-sensors.json` and maintain bounded events.
- The daily report renderer can write a Markdown report.
- Outputs are group-readable for admins, not world-readable.
- `hermes-admin` can still run `hermes status`.

Only after this is stable should Phase 2 add push delivery, Hermes cron/Kanban integration, LLM summaries, or repair actions.
