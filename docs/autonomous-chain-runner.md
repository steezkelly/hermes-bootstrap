# Autonomous Chain Runner

The always-on mini-PC service `hermes-autonomous-evolution-chain` executes a promoted Bootstrap script at:

- Bootstrap source: `scripts/harness/autonomous/chain_runner.py`
- Runtime path: `/var/lib/hermes/harness/autonomous/chain_runner.py`
- Systemd unit: `hermes-autonomous-evolution-chain.service`
- Timer: `hermes-autonomous-evolution-chain.timer` (`OnBootSec=2min`, `OnUnitActiveSec=30min`)

## Purpose

The runner is Bootstrap-side orchestration only. It exports local Hermes session JSON files into JSONL, then invokes Foundry modules in order. Foundry owns the semantic behavior of each stage.

Default stage order:

1. `real_trace_ingestion`
2. `attention_router_bridge`
3. `trace_optimizer`
4. `gepa_bridge` (optional; skipped when DSPy Python or candidate artifacts are missing)
5. `observatory_health` (optional; skipped when the judge audit DB is missing)

Default required stages: `real_trace_ingestion`, `attention_router_bridge`, `trace_optimizer`.

## Configuration surface

Configuration can come from CLI flags, a JSON config file, or environment variables. The environment variable prefix is `HERMES_AUTONOMOUS_`.

CLI flags:

- `--config <path>`: optional JSON object with the same snake_case keys listed below.
- `--base <path>`: appliance base directory; default `/var/lib/hermes`.
- `--foundry-repo <path>` / `HERMES_AUTONOMOUS_FOUNDRY_REPO`: default `/var/lib/hermes/foundry/hermes-agent-self-evolution`.
- `--sessions-dir <path>` / `HERMES_AUTONOMOUS_SESSIONS_DIR`: default `/var/lib/hermes/.hermes/sessions`.
- `--reports-dir <path>` / `HERMES_AUTONOMOUS_REPORTS_DIR`: default `/var/lib/hermes/reports/evolution`.
- `--state-file <path>` / `HERMES_AUTONOMOUS_STATE_FILE`: default `<reports-dir>/autonomous-state.json`.
- `--log-file <path>` / `HERMES_AUTONOMOUS_LOG_FILE`: default `<reports-dir>/autonomous-chain.jsonl`.
- `--trace-file <path>` / `HERMES_AUTONOMOUS_TRACE_FILE`: default `<reports-dir>/autonomous-trace.jsonl`.
- `--python-bin <path>` / `HERMES_AUTONOMOUS_PYTHON_BIN`: interpreter for required Foundry stages; systemd uses the `pythonFoundry` Nix environment.
- `--dspy-python <path>` / `HERMES_AUTONOMOUS_DSPY_PYTHON`: interpreter for `gepa_bridge`; default `/var/lib/hermes/foundry-venv/bin/python`.
- `--observatory-db <path>` / `HERMES_AUTONOMOUS_OBSERVATORY_DB`: default `<reports-dir>/observatory/judge_audit_log.db`.
- `--steps <csv>` / `HERMES_AUTONOMOUS_STEPS`: comma-separated subset/order of valid steps.
- `--required-steps <csv>` / `HERMES_AUTONOMOUS_REQUIRED_STEPS`: steps whose failure causes exit 1.
- `--force` / `HERMES_AUTONOMOUS_FORCE=true`: run even when the session count did not increase.
- `--timeout-seconds <n>` / `HERMES_AUTONOMOUS_TIMEOUT_SECONDS`: per-step subprocess timeout; default 600.

JSON config keys use snake_case, for example:

```json
{
  "base": "/var/lib/hermes",
  "reports_dir": "/var/lib/hermes/reports/evolution",
  "steps": ["real_trace_ingestion", "attention_router_bridge", "trace_optimizer"],
  "required_steps": ["real_trace_ingestion", "attention_router_bridge", "trace_optimizer"],
  "timeout_seconds": 600
}
```

## Log output format

The runner emits JSON Lines to stdout and to `--log-file`. Every record includes:

- `ts`: UTC ISO-8601 timestamp.
- `level`: `info`, `warning`, or `error`.
- `event`: event name.
- `run_id`: short random run identifier.

Common events:

- `run_started`: resolved paths, session counts, configured steps, interpreters.
- `idle`: no new sessions or no session files.
- `trace_exported`: JSONL path, session file count, message count.
- `session_parse_failed`: bad session JSON was skipped.
- `step_started`: step name, cwd, argv, required flag.
- `step_finished`: step name, return code, duration, argv, stdout/stderr tails.
- `step_skipped`: optional dependency missing, such as DSPy Python or observatory DB.
- `optional_step_failed`: optional stage failed but required stages may still succeed.
- `artifact_written`: currently used for observatory health JSON output.
- `run_finished`: final `success` or `failed` status.
- `runner_exception`: fail-closed structured exception record.

Example:

```json
{"event":"step_finished","level":"info","returncode":0,"run_id":"abc123","status":"success","step":"trace_optimizer","duration_ms":421,"ts":"2026-05-10T05:00:00Z"}
```

## Nix-side deployment

`system/nixos/harness.nix` keeps the existing `autonomousEvolutionChain` binding pointing at `/var/lib/hermes/harness/autonomous/chain_runner.py` and uses `pythonFoundry`.

Activation now installs the promoted source file into that runtime path:

```nix
install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/harness/autonomous
install -o hermes-harness -g hermes -m 0755 ${harnessDir}/autonomous/chain_runner.py /var/lib/hermes/harness/autonomous/chain_runner.py
```

No new network, GitHub, or secret access is added. The service remains local-only: it can write `/var/lib/hermes/reports/evolution`, read Foundry and local session JSON, and cannot access `/var/lib/hermes/secrets` or `/var/lib/hermes/.hermes/.env`.
