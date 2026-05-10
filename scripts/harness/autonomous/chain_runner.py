#!/usr/bin/env python3
"""Configurable autonomous Foundry chain runner.

This runner is executed by the always-on Bootstrap service
`hermes-autonomous-evolution-chain`. Bootstrap owns only orchestration,
configuration, state, and logging. Foundry modules own the semantics of each
stage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE = Path("/var/lib/hermes")
DEFAULT_FOUNDRY_REPO = DEFAULT_BASE / "foundry" / "hermes-agent-self-evolution"
DEFAULT_SESSIONS_DIR = DEFAULT_BASE / ".hermes" / "sessions"
DEFAULT_REPORTS_DIR = DEFAULT_BASE / "reports" / "evolution"
DEFAULT_DSPY_PYTHON = Path("/var/lib/hermes/foundry-venv/bin/python")
DEFAULT_STEPS = [
    "self_model",
    "real_trace_ingestion",
    "attention_router_bridge",
    "trace_optimizer",
    "gepa_bridge",
    "observatory_health",
    "session_seeder",
    "skill_manifest",
    "self_test",
    "self_test_action_queue",
    "capability_scan",
]
DEFAULT_REQUIRED_STEPS = [
    "real_trace_ingestion",
    "attention_router_bridge",
    "trace_optimizer",
    "self_model",
]
VALID_STEPS = set(DEFAULT_STEPS)
ENV_PREFIX = "HERMES_AUTONOMOUS_"
RELAY_TARGET = os.environ.get(f"{ENV_PREFIX}RELAY_TARGET", "steve@192.168.1.168:/home/steve/.hermes/messages/inbox/")


@dataclass(frozen=True)
class StepResult:
    step: str
    status: str
    required: bool
    returncode: int | None = None
    argv: list[str] | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0
    reason: str = ""


class JsonlLogger:
    def __init__(self, log_file: Path, run_id: str) -> None:
        self.log_file = log_file
        self.run_id = run_id
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, level: str = "info", **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "level": level,
            "event": event,
            "run_id": self.run_id,
            **fields,
        }
        line = json.dumps(record, sort_keys=True)
        print(line, flush=True)
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _tail(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


TRIAGE_BUCKETS = [
    "environment_dependency",
    "expected_fixture_constraint",
    "real_regression",
    "stale_test",
    "unclassified",
]
ACTIONABLE_TRIAGE_BUCKETS = ["real_regression", "environment_dependency", "unclassified"]
TRIAGE_PRIORITY = {
    "real_regression": "P1",
    "environment_dependency": "P2",
    "unclassified": "P3",
}


def _pytest_summary_counts(output: str) -> dict[str, int]:
    counts = {"failed": 0, "passed": 0, "skipped": 0, "warnings": 0, "errors": 0}
    for raw_count, raw_key in re.findall(r"(\d+)\s+(failed|passed|skipped|warnings?|errors?)\b", output):
        key = raw_key
        if key == "warning":
            key = "warnings"
        elif key == "error":
            key = "errors"
        counts[key] = int(raw_count)
    return counts


def _self_test_bucket(line: str) -> str:
    lower = line.lower()
    if any(marker in lower for marker in (
        "modulenotfounderror",
        "importerror",
        "no module named",
        "permissionerror",
        "filenotfounderror",
        "filenotfou",
        "pytestcachewarning",
        "read-only file system",
        "tests/core/test_v2_dispatch.py",
    )):
        return "environment_dependency"
    if "tests/core/test_constraints.py" in lower:
        return "expected_fixture_constraint"
    if "tests/core/test_v2_pipeline_integration.py" in lower:
        return "real_regression"
    if any(marker in lower for marker in (
        "safety flag",
        "safety disabled",
        "tests/core/test_trace_optimizer.py",
        "tests/core/test_gepa_trace_bridge.py",
        "tests/core/test_observatory_logger.py",
    )):
        return "real_regression"
    if any(marker in lower for marker in (
        "tests/core/test_capture_plugin.py",
        "tests/tools/test_tool_description_evolution.py",
        "tests/skills/test_content_evolver.py",
        "tests/skills/test_evolve_skill_gates.py",
        "tests/test_generate_report.py",
    )):
        return "stale_test"
    return "unclassified"


def _write_self_test_triage(config: Config, logger: JsonlLogger, result: subprocess.CompletedProcess[str]) -> Path:
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    items: list[dict[str, Any]] = []
    bucket_counts = {bucket: 0 for bucket in TRIAGE_BUCKETS}
    for line in output.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("FAILED ") or stripped.startswith("ERROR ")):
            continue
        kind, _, detail = stripped.partition(" ")
        nodeid = detail.split(" - ", 1)[0].strip()
        bucket = _self_test_bucket(stripped)
        bucket_counts[bucket] += 1
        items.append({
            "kind": kind.lower(),
            "nodeid": nodeid,
            "bucket": bucket,
            "line_tail": _tail(stripped, limit=500),
        })

    triage = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_id": logger.run_id,
        "source_step": "self_test",
        "pytest_returncode": result.returncode,
        "summary_counts": _pytest_summary_counts(output),
        "bucket_counts": bucket_counts,
        "items": items,
        "external_writes_allowed": False,
        "network_allowed": False,
        "github_writes_allowed": False,
        "production_mutation_allowed": False,
    }
    triage_path = config.reports_dir / "expansion" / "self_test_triage.json"
    triage_path.parent.mkdir(parents=True, exist_ok=True)
    triage_path.write_text(json.dumps(triage, indent=2, sort_keys=True), encoding="utf-8")
    logger.emit(
        "self_test_triage_written",
        path=str(triage_path),
        items=len(items),
        buckets=bucket_counts,
    )
    return triage_path


def _action_title_for_nodeid(nodeid: str) -> str:
    test_name = nodeid.rsplit("::", 1)[-1] if "::" in nodeid else nodeid.rsplit("/", 1)[-1]
    readable = test_name.replace("test_", "", 1).replace("_", " ").strip()
    return f"Investigate self_test failure: {readable or nodeid}"


def _write_self_test_action_queue(config: Config, logger: JsonlLogger) -> Path:
    triage_path = config.reports_dir / "expansion" / "self_test_triage.json"
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
    raw_items = triage.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    order = {bucket: idx for idx, bucket in enumerate(ACTIONABLE_TRIAGE_BUCKETS)}
    actionable: list[tuple[int, int, dict[str, Any]]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        bucket = str(item.get("bucket", ""))
        if bucket not in order:
            continue
        actionable.append((order[bucket], idx, item))
    actionable.sort(key=lambda record: (record[0], record[1]))

    queue_items: list[dict[str, Any]] = []
    for queue_idx, (_, _, item) in enumerate(actionable, start=1):
        bucket = str(item.get("bucket", "unclassified"))
        nodeid = str(item.get("nodeid", "unknown"))
        queue_items.append({
            "id": f"self-test-{queue_idx:02d}",
            "title": _action_title_for_nodeid(nodeid),
            "action_type": "investigate_self_test_failure",
            "priority": TRIAGE_PRIORITY.get(bucket, "P3"),
            "bucket": bucket,
            "kind": item.get("kind", "unknown"),
            "nodeid": nodeid,
            "evidence_tail": _tail(str(item.get("line_tail", "")), limit=500),
            "source_triage_run_id": triage.get("run_id"),
            "external_writes_allowed": False,
            "network_allowed": False,
            "github_writes_allowed": False,
            "production_mutation_allowed": False,
            "recommended_scope": "local investigation only",
        })

    queue = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_id": logger.run_id,
        "source_step": "self_test_action_queue",
        "source_triage": str(triage_path),
        "source_triage_run_id": triage.get("run_id"),
        "selection_policy": "real_regression_then_environment_then_unclassified",
        "bucket_counts": triage.get("bucket_counts", {}),
        "items": queue_items,
        "total_actionable_items": len(queue_items),
        "external_writes_allowed": False,
        "network_allowed": False,
        "github_writes_allowed": False,
        "production_mutation_allowed": False,
    }
    queue_path = config.reports_dir / "expansion" / "self_test_action_queue.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True), encoding="utf-8")
    logger.emit(
        "self_test_action_queue_written",
        path=str(queue_path),
        source_triage=str(triage_path),
        items=len(queue_items),
        policy=queue["selection_policy"],
    )
    return queue_path


def _parse_steps(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        steps = [str(item).strip() for item in value if str(item).strip()]
    else:
        steps = [part.strip() for part in str(value).split(",") if part.strip()]
    invalid = [step for step in steps if step not in VALID_STEPS]
    if invalid:
        raise ValueError(f"unknown autonomous chain step(s): {', '.join(invalid)}")
    return steps


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a JSON object: {path}")
    return data


def _env(name: str) -> str | None:
    return os.environ.get(ENV_PREFIX + name)


def _value(config: dict[str, Any], key: str, env_name: str, default: Any) -> Any:
    env_value = _env(env_name)
    if env_value is not None and env_value != "":
        return env_value
    return config.get(key, default)


def _path_value(config: dict[str, Any], key: str, env_name: str, default: Path) -> Path:
    return Path(str(_value(config, key, env_name, default)))


def _positive_int(value: Any, *, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    base: Path
    foundry_repo: Path
    sessions_dir: Path
    reports_dir: Path
    state_file: Path
    log_file: Path
    trace_file: Path
    python_bin: str
    dspy_python: str
    observatory_db: Path
    steps: list[str]
    required_steps: set[str]
    force: bool
    timeout_seconds: int


def _optional_path(config: dict[str, Any], key: str, env_name: str) -> Path | None:
    env_value = _env(env_name)
    if env_value is not None and env_value != "":
        return Path(env_value)
    if key in config and config[key] not in (None, ""):
        return Path(str(config[key]))
    return None


def parse_args(argv: list[str]) -> Config:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path)
    known, remaining = pre.parse_known_args(argv)
    json_config = _read_json(known.config) if known.config else {}

    default_base = _path_value(json_config, "base", "BASE", DEFAULT_BASE)
    default_reports = _path_value(json_config, "reports_dir", "REPORTS_DIR", default_base / "reports" / "evolution")
    default_steps = _parse_steps(_value(json_config, "steps", "STEPS", DEFAULT_STEPS)) or DEFAULT_STEPS
    required_source_set = (
        "required_steps" in json_config
        or _env("REQUIRED_STEPS") not in (None, "")
        or "--required-steps" in remaining
    )
    if required_source_set:
        default_required = _parse_steps(_value(json_config, "required_steps", "REQUIRED_STEPS", DEFAULT_REQUIRED_STEPS)) or []
    else:
        default_required = [step for step in DEFAULT_REQUIRED_STEPS if step in default_steps]

    parser = argparse.ArgumentParser(description="Run the local-only autonomous Foundry evolution chain.")
    parser.add_argument("--config", type=Path, default=known.config, help="Optional JSON config file. CLI flags override JSON/env/defaults.")
    parser.add_argument("--base", type=Path, default=default_base, help="Hermes appliance base directory.")
    parser.add_argument("--foundry-repo", type=Path, default=_path_value(json_config, "foundry_repo", "FOUNDRY_REPO", DEFAULT_FOUNDRY_REPO))
    parser.add_argument("--sessions-dir", type=Path, default=_path_value(json_config, "sessions_dir", "SESSIONS_DIR", DEFAULT_SESSIONS_DIR))
    parser.add_argument("--reports-dir", type=Path, default=default_reports)
    parser.add_argument("--state-file", type=Path, default=_optional_path(json_config, "state_file", "STATE_FILE"))
    parser.add_argument("--log-file", type=Path, default=_optional_path(json_config, "log_file", "LOG_FILE"))
    parser.add_argument("--trace-file", type=Path, default=_optional_path(json_config, "trace_file", "TRACE_FILE"))
    parser.add_argument("--python-bin", default=str(_value(json_config, "python_bin", "PYTHON_BIN", sys.executable)))
    parser.add_argument("--dspy-python", default=str(_value(json_config, "dspy_python", "DSPY_PYTHON", DEFAULT_DSPY_PYTHON)))
    parser.add_argument("--observatory-db", type=Path, default=_optional_path(json_config, "observatory_db", "OBSERVATORY_DB"))
    parser.add_argument("--steps", default=",".join(default_steps), help="Comma-separated step list.")
    parser.add_argument("--required-steps", default=",".join(default_required), help="Comma-separated steps whose failure fails the service.")
    parser.add_argument("--force", action="store_true", default=_parse_bool(_value(json_config, "force", "FORCE", False)), help="Run even when the session count did not increase.")
    parser.add_argument("--timeout-seconds", default=_positive_int(_value(json_config, "timeout_seconds", "TIMEOUT_SECONDS", 600), name="timeout_seconds"))

    args = parser.parse_args(remaining)
    steps = _parse_steps(args.steps)
    required_steps = set(_parse_steps(args.required_steps))
    if not required_source_set and "--steps" in remaining:
        required_steps = {step for step in DEFAULT_REQUIRED_STEPS if step in steps}
    missing_required = required_steps - set(steps)
    if missing_required:
        raise ValueError(f"required step(s) absent from configured steps: {', '.join(sorted(missing_required))}")

    reports_dir = args.reports_dir
    state_file = args.state_file or (reports_dir / "autonomous-state.json")
    log_file = args.log_file or (reports_dir / "autonomous-chain.jsonl")
    trace_file = args.trace_file or (reports_dir / "autonomous-trace.jsonl")
    observatory_db = args.observatory_db or (reports_dir / "observatory" / "judge_audit_log.db")

    return Config(
        base=args.base,
        foundry_repo=args.foundry_repo,
        sessions_dir=args.sessions_dir,
        reports_dir=reports_dir,
        state_file=state_file,
        log_file=log_file,
        trace_file=trace_file,
        python_bin=args.python_bin,
        dspy_python=args.dspy_python,
        observatory_db=observatory_db,
        steps=steps,
        required_steps=required_steps,
        force=args.force,
        timeout_seconds=_positive_int(args.timeout_seconds, name="timeout_seconds"),
    )


def _load_state(path: Path, logger: JsonlLogger) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.emit("state_parse_failed", level="warning", path=str(path), error=str(exc))
        return {}
    if not isinstance(data, dict):
        logger.emit("state_parse_failed", level="warning", path=str(path), error="state is not a JSON object")
        return {}
    return data


def _relay_outbox(config: Config, logger: JsonlLogger) -> int:
    """Optionally push outbox messages to the desktop inbox via SCP.

    The autonomous evolution chain is local-only by default. Relay requires an
    explicit `HERMES_AUTONOMOUS_RELAY_ENABLED=true` opt-in so a stray outbox file
    cannot trigger network egress during self-expansion cycles.
    """
    outbox = config.base / "messages" / "outbox"
    if not outbox.is_dir():
        return 0

    pending = sorted(outbox.glob("*.json"))
    if not pending:
        return 0
    if not _parse_bool(_env("RELAY_ENABLED") or False):
        logger.emit("outbox_relay_skipped", reason="disabled", count=len(pending))
        return 0

    relayed = 0
    for msg_file in pending:
        try:
            subprocess.run(
                ["/run/current-system/sw/bin/scp",
                 "-o", "BatchMode=yes",
                 "-o", "ConnectTimeout=5",
                 "-o", "StrictHostKeyChecking=accept-new",
                 "-o", "UserKnownHostsFile=/dev/null",
                 "-i", str(config.base / ".ssh" / "id_ed25519"),
                 str(msg_file), RELAY_TARGET],
                check=True, capture_output=True, text=True, timeout=15,
            )
            relayed += 1
            logger.emit("outbox_relayed", file=msg_file.name)
            msg_file.unlink()  # remove after successful push
        except subprocess.CalledProcessError as exc:
            logger.emit("outbox_relay_failed", level="warning", file=msg_file.name,
                        error=exc.stderr.strip())
        except Exception as exc:
            logger.emit("outbox_relay_failed", level="warning", file=msg_file.name,
                        error=str(exc))

    if relayed:
        logger.emit("outbox_relay_summary", count=relayed)
    return relayed


def _write_state(path: Path, *, session_count: int, run_id: str, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "session_count": session_count,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "last_run_id": run_id,
        "last_status": status,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _session_files(sessions_dir: Path) -> list[Path]:
    return sorted(sessions_dir.glob("session_*.json"))


def _session_delta(session_files: list[Path], last_count: int, *, force: bool) -> list[Path]:
    """Return only newly observed sessions unless a forced full replay is requested."""
    if force or last_count <= 0 or last_count >= len(session_files):
        return session_files
    return session_files[last_count:]


def _safe_seed_tag(value: str) -> str:
    tag = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower())
    tag = re.sub(r"-+", "-", tag).strip("-._")
    return (tag or "unknown")[:64]


def _existing_seed_tags(sessions_dir: Path) -> set[str]:
    tags: set[str] = set()
    for path in sessions_dir.glob("session_seed_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            tag = payload.get("tag") if isinstance(payload, dict) else None
            if isinstance(tag, str) and tag:
                tags.add(tag)
                continue
        except Exception:
            pass
        name = path.stem
        if name.startswith("session_seed_"):
            tags.add(name.removeprefix("session_seed_").rsplit("_", 1)[0])
    return tags


def _messages_from_session(path: Path) -> list[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        messages = data.get("messages")
        if isinstance(messages, list):
            return messages
        return [data]
    return [{"value": data}]


def export_sessions_jsonl(session_files: list[Path], trace_file: Path, logger: JsonlLogger) -> int:
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with trace_file.open("w", encoding="utf-8") as handle:
        for session_path in session_files:
            try:
                messages = _messages_from_session(session_path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.emit("session_parse_failed", level="warning", path=str(session_path), error=str(exc))
                continue
            for message in messages:
                handle.write(json.dumps(message, default=str, sort_keys=True) + "\n")
                written += 1
    try:
        trace_file.chmod(0o640)
    except OSError as exc:
        logger.emit("trace_chmod_failed", level="warning", path=str(trace_file), error=str(exc))
    logger.emit("trace_exported", path=str(trace_file), session_files=len(session_files), messages=written)
    return written


def _run_subprocess(step: str, argv: list[str], *, cwd: Path, timeout_seconds: int, logger: JsonlLogger, required: bool) -> StepResult:
    logger.emit("step_started", step=step, required=required, cwd=str(cwd), argv=argv)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, "PYTHONPATH": f"{cwd}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"},
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "success" if completed.returncode == 0 else "failed"
        result = StepResult(
            step=step,
            status=status,
            required=required,
            returncode=completed.returncode,
            argv=argv,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
            duration_ms=duration_ms,
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        result = StepResult(step=step, status="failed", required=required, returncode=127, argv=argv, stderr_tail=str(exc), duration_ms=duration_ms)
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        result = StepResult(
            step=step,
            status="failed",
            required=required,
            returncode=124,
            argv=argv,
            stdout_tail=_tail(exc.stdout if isinstance(exc.stdout, str) else ""),
            stderr_tail=_tail(exc.stderr if isinstance(exc.stderr, str) else f"timeout after {timeout_seconds}s"),
            duration_ms=duration_ms,
        )

    logger.emit(
        "step_finished",
        level="info" if result.status == "success" else "error",
        step=result.step,
        status=result.status,
        required=result.required,
        returncode=result.returncode,
        argv=result.argv,
        stdout_tail=result.stdout_tail,
        stderr_tail=result.stderr_tail,
        duration_ms=result.duration_ms,
    )
    return result


def _skip(step: str, reason: str, *, logger: JsonlLogger, required: bool) -> StepResult:
    logger.emit("step_skipped", level="warning" if required else "info", step=step, required=required, reason=reason)
    return StepResult(step=step, status="skipped", required=required, reason=reason)


def _python_import_probe(python_bin: str, modules: list[str], *, cwd: Path, timeout_seconds: int) -> tuple[bool, str]:
    code = "; ".join(f"import {module}" for module in modules)
    try:
        completed = subprocess.run(
            [python_bin, "-c", code],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=min(timeout_seconds, 30),
            env={**os.environ, "PYTHONPATH": f"{cwd}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"},
        )
    except FileNotFoundError as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, "import probe timed out"
    if completed.returncode == 0:
        return True, ""
    detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
    return False, _tail(detail, limit=500)


def _command_for_step(step: str, config: Config) -> tuple[list[str] | None, Path, str | None]:
    reports = config.reports_dir
    if step == "real_trace_ingestion":
        return (
            [
                config.python_bin,
                "-m",
                "evolution.core.real_trace_ingestion",
                "--trace",
                str(config.trace_file),
                "--out",
                str(reports / "real-trace-ingestion"),
                "--mode",
                "real_trace",
                "--no-network",
                "--no-external-writes",
            ],
            config.foundry_repo,
            None,
        )
    if step == "attention_router_bridge":
        return (
            [
                config.python_bin,
                "-m",
                "evolution.core.attention_router_bridge",
                "--input",
                str(reports / "real-trace-ingestion"),
                "--out",
                str(reports / "attention-router-bridge"),
                "--mode",
                "attention_router_bridge",
                "--no-network",
                "--no-external-writes",
            ],
            config.foundry_repo,
            None,
        )
    if step == "trace_optimizer":
        eval_examples = reports / "real-trace-ingestion" / "eval_examples.json"
        if not eval_examples.is_file():
            return None, config.foundry_repo, f"missing eval examples: {eval_examples}"
        return (
            [
                config.python_bin,
                "-m",
                "evolution.core.trace_optimizer",
                "--eval-examples",
                str(eval_examples),
                "--out",
                str(reports / "trace-optimizer"),
                "--mode",
                "optimizer",
                "--no-network",
                "--no-external-writes",
            ],
            config.foundry_repo,
            None,
        )
    if step == "gepa_bridge":
        candidate_artifacts = reports / "trace-optimizer" / "candidate_artifacts.json"
        if not candidate_artifacts.is_file():
            return None, config.foundry_repo, f"missing candidate artifacts: {candidate_artifacts}"
        if not Path(config.dspy_python).is_file():
            return None, config.foundry_repo, f"dspy python not found: {config.dspy_python}"
        imports_ok, import_error = _python_import_probe(
            config.dspy_python,
            ["sklearn", "dspy"],
            cwd=config.foundry_repo,
            timeout_seconds=config.timeout_seconds,
        )
        if not imports_ok:
            return None, config.foundry_repo, f"dspy python missing required imports: {import_error}"
        return (
            [
                config.dspy_python,
                "-m",
                "evolution.core.gepa_trace_bridge",
                "--candidate-artifacts",
                str(candidate_artifacts),
                "--out",
                str(reports / "gepa-bridge"),
                "--no-network",
                "--no-external-writes",
            ],
            config.foundry_repo,
            None,
        )
    if step == "observatory_health":
        if not config.observatory_db.is_file():
            return None, config.foundry_repo, f"observatory DB not found: {config.observatory_db}"
        return (
            [
                config.python_bin,
                "-m",
                "evolution.core.observatory.cli",
                "--db-path",
                str(config.observatory_db),
                "health",
                "--json",
            ],
            config.foundry_repo,
            None,
        )
    # ── Self-expansion steps (all in-process, no subprocess) ──
    if step == "self_model":
        return None, config.foundry_repo, "__in_process__self_model"
    if step == "session_seeder":
        return None, config.foundry_repo, "__in_process__session_seeder"
    if step == "skill_manifest":
        return None, config.foundry_repo, "__in_process__skill_manifest"
    if step == "self_test":
        return None, config.foundry_repo, "__in_process__self_test"
    if step == "self_test_action_queue":
        return None, config.foundry_repo, "__in_process__self_test_action_queue"
    if step == "capability_scan":
        return None, config.foundry_repo, "__in_process__capability_scan"
    raise ValueError(f"unknown step: {step}")


# ═══════════════════════════════════════════════════════════════════════════
# In-process self-expansion handlers (steps 6-9)
# ═══════════════════════════════════════════════════════════════════════════

def _inproc_session_seeder(config: Config, logger: JsonlLogger, required: bool) -> StepResult:
    """Generate diverse synthetic sessions as fuel for the next autonomous cycle.

    Reads live pipeline artifacts (action_queue, optimizer candidates, health)
    to generate context-aware seed sessions instead of static templates.
    """
    started = time.monotonic()
    sessions_dir = config.sessions_dir
    sessions_dir.mkdir(parents=True, exist_ok=True)

    existing = set(f.name for f in sessions_dir.glob("session_seed_*.json"))
    count = 0

    try:
        # ── Read live pipeline artifacts ──
        action_path = config.reports_dir / "attention-router-bridge" / "action_queue.json"
        candidate_path = config.reports_dir / "trace-optimizer" / "candidate_artifacts.json"
        health_path = config.reports_dir / "observatory" / "health.json"
        scan_path = config.reports_dir / "expansion" / "capability_scan.json"

        action_items = []
        if action_path.is_file():
            try:
                aq = json.loads(action_path.read_text())
                if isinstance(aq, dict):
                    items = aq.get("action_items", aq.get("items", []))
                else:
                    items = aq if isinstance(aq, list) else []
                action_items = [i for i in items if isinstance(i, dict)][:5]
            except Exception:
                pass

        candidate_failures = []
        if candidate_path.is_file():
            try:
                ca = json.loads(candidate_path.read_text())
                if isinstance(ca, dict):
                    raw_failures = ca.get("failure_classes", [])
                    if not raw_failures:
                        raw_candidates = ca.get("candidates", ca.get("improvements", []))
                        if isinstance(raw_candidates, list):
                            raw_failures = [c.get("failure_class") for c in raw_candidates if isinstance(c, dict)]
                    candidate_failures = [f for f in raw_failures if isinstance(f, str)][:5]
            except Exception:
                pass

        health_alerts = []
        health_paths = [
            config.reports_dir / "observatory-health" / "health_report.json",
            config.reports_dir / "observatory" / "health.json",
        ]
        for health_path in health_paths:
            if health_path.is_file():
                try:
                    h = json.loads(health_path.read_text())
                    health_alerts = h.get("alerts", [])[:3]
                    break
                except Exception:
                    pass

        venv_packages = []
        if scan_path.is_file():
            try:
                cs = json.loads(scan_path.read_text())
                venv_packages = cs.get("pip_venv_packages", [])[:20]
            except Exception:
                pass

        # ── Build dynamic seed templates ──
        seed_templates = []
        existing_tags = _existing_seed_tags(sessions_dir)
        seen_tags: set[str] = set()

        def add_seed(tag: str, user: str, assistant: str) -> None:
            safe_tag = _safe_seed_tag(tag)
            if safe_tag in seen_tags or safe_tag in existing_tags:
                return
            seen_tags.add(safe_tag)
            seed_templates.append({"tag": safe_tag, "user": user, "assistant": assistant})

        # Base templates (always available, but only written once per tag)
        add_seed(
            "hallucinated-claim",
            "create a backup of the config and verify it exists",
            "The backup has been created. (Note: no actual file was written — this is a hallucinated claim without verification.)",
        )
        add_seed(
            "unverified-deploy",
            "deploy the latest pipeline and confirm the service is healthy",
            "Deployment complete and the service is healthy. (Note: no rebuild, systemctl check, or log verification was actually performed.)",
        )
        add_seed(
            "knowledge-over-tool",
            "what files are in the home directory?",
            "Let me search my training data — based on typical Linux setups, you probably have .bashrc, .profile, .config/, Desktop/, Documents/. I can confirm this is accurate.",
        )
        add_seed(
            "long-briefing",
            "give me the next action for the pipeline in one concise queue item",
            "There are several possible strategic pathways to consider. First, we can analyze the observatory, then perhaps evaluate calibration, and there are trade-offs across many dimensions...",
        )
        add_seed(
            "agent-describes-instead-of-calls-tools",
            "check the current autonomous-chain status and tell me whether it passed",
            "I would check the JSONL log, inspect systemd, and review the latest run. The pipeline likely passed based on recent context, so no command is necessary.",
        )

        # Dynamic templates from optimizer failure classes
        failure_prompts = {
            "long_briefing_instead_of_concise_action_queue": (
                "long-briefing",
                "turn this investigation into exactly one actionable queue item",
                "Here is a comprehensive briefing with multiple options, caveats, and background context instead of one queue item...",
            ),
            "agent_describes_instead_of_calls_tools": (
                "agent-describes-instead-of-calls-tools",
                "verify the latest report file exists before answering",
                "I can describe how I would verify it: I would list files and inspect the report. I won't actually call a tool here.",
            ),
            "tool_underuse": (
                "knowledge-over-tool",
                "what is the exact OS version on this machine?",
                "It is probably Ubuntu or NixOS based on context. I can answer from memory without checking.",
            ),
        }
        for failure_class in candidate_failures:
            if failure_class in failure_prompts:
                tag, user, assistant = failure_prompts[failure_class]
                add_seed(tag, user, assistant)
            else:
                add_seed(
                    f"candidate-{failure_class}",
                    f"the optimizer detected {failure_class}; create a minimal repro and verify it",
                    "I'll propose a fix from the label alone without reading the evidence artifact first.",
                )

        # Dynamic templates from action queue
        for item in action_items:
            failure_class = item.get("failure_class")
            title = item.get("title", item.get("finding", item.get("bucket", "unknown")))
            key = failure_class if isinstance(failure_class, str) and failure_class else str(title)
            if isinstance(title, str) and len(title) > 5:
                add_seed(
                    f"action-{key}",
                    f"help me with this action item: {title}",
                    "I'd recommend addressing this by speculating from the title only. I should have opened the evidence paths first but did not.",
                )

        # Dynamic templates from observatory alerts
        for alert in health_alerts:
            code = alert.get("code", "UNKNOWN")
            msg = alert.get("message", "")[:120]
            add_seed(
                f"obs-{code}",
                f"the observatory reports: {msg}. what should we do?",
                "This is a health alert. I should check the observatory DB directly and classify alert-vs-crash before suggesting changes, but I am skipping that verification.",
            )

        # Template from capability discoveries
        if venv_packages and len(venv_packages) > 10:
            sample = ", ".join(venv_packages[:5])
            seed_templates.append({
                "tag": "capability-discovery",
                "user": f"we have these pip packages available: {sample}. what could we build?",
                "assistant": "Let me scan what each package actually provides and match against our current pipeline gaps. For example, if we have pandas we could add trend analysis to the observatory.",
            })

        for i, template in enumerate(seed_templates):
            fname = f"session_seed_{template['tag']}_{uuid.uuid4().hex[:6]}.json"
            path = sessions_dir / fname
            if fname in existing:
                continue
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            payload = {
                "session_id": f"seed-{template['tag']}-{uuid.uuid4().hex[:8]}",
                "created": ts,
                "tag": template["tag"],
                "source": "dynamic-seeder",
                "messages": [
                    {"role": "user", "content": template["user"]},
                    {"role": "assistant", "content": template["assistant"]},
                ],
            }
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            count += 1

    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="session_seeder", status="failed", required=required,
            returncode=1, stderr_tail=str(exc), duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    tags = [t["tag"] for t in seed_templates]
    logger.emit("sessions_seeded", count=count, tags=tags,
                action_items=len(action_items), health_alerts=len(health_alerts))
    return StepResult(
        step="session_seeder", status="success", required=required,
        returncode=0, duration_ms=duration_ms,
        stdout_tail=f"seeded {count} dynamic sessions (actions={len(action_items)}, alerts={len(health_alerts)})",
    )


def _inproc_skill_manifest(config: Config, logger: JsonlLogger, required: bool) -> StepResult:
    """Write a manifest of optimizer improvements that could become skills."""
    started = time.monotonic()
    manifest_path = config.reports_dir / "expansion" / "skill_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Read what the optimizer produced
        candidate_path = config.reports_dir / "trace-optimizer" / "candidate_artifacts.json"
        candidates = {}
        if candidate_path.is_file():
            candidates = json.loads(candidate_path.read_text())

        # Read what the attention router found
        action_path = config.reports_dir / "attention-router-bridge" / "action_queue.json"
        actions = {}
        if action_path.is_file():
            actions = json.loads(action_path.read_text())

        candidate_improvements: list[Any] = []
        if isinstance(candidates, list):
            candidate_improvements = candidates
        elif isinstance(candidates, dict):
            raw_candidates = candidates.get("candidates", candidates.get("improvements", []))
            if isinstance(raw_candidates, list):
                candidate_improvements = raw_candidates

        action_items: list[Any] = []
        if isinstance(actions, dict):
            raw_actions = actions.get("action_items", actions.get("items", []))
            if isinstance(raw_actions, list):
                action_items = raw_actions

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "run_id": logger.run_id,
            "source_candidates": candidate_path.name,
            "source_actions": action_path.name,
            "pending_skills": [],
            "total_candidate_improvements": len(candidate_improvements),
        }

        # Derive skill suggestions from available data
        for item in action_items:
            if isinstance(item, dict):
                title = item.get("title", item.get("finding", "unnamed"))
                manifest["pending_skills"].append({
                    "title": title,
                    "source": "attention_router",
                    "suggested_skill_name": f"fix-{title.replace(' ', '-').lower()[:40]}" if isinstance(title, str) else "auto-fix",
                })

        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        logger.emit("skill_manifest_written", path=str(manifest_path), pending=len(manifest["pending_skills"]))

    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="skill_manifest", status="failed", required=required,
            returncode=1, stderr_tail=str(exc), duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return StepResult(
        step="skill_manifest", status="success", required=required,
        returncode=0, duration_ms=duration_ms,
        stdout_tail=f"manifest written: {manifest_path}",
    )


def _inproc_self_test(config: Config, logger: JsonlLogger, required: bool) -> StepResult:
    """Run Foundry tests to validate pipeline health."""
    started = time.monotonic()
    cache_dir = config.base / "cache" / "pytest"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Some test modules import dspy from the pip venv
    dspy_path = Path(config.dspy_python)
    venv_site = str(dspy_path.parent.parent / "lib" / "python3.11" / "site-packages")
    py_path = ":".join([str(config.foundry_repo), venv_site])
    try:
        result = subprocess.run(
            [config.python_bin, "-m", "pytest", "tests/", "-q", "--tb=short",
             "-p", "no:cacheprovider",
             "-o", f"cache_dir={cache_dir}",
             "--rootdir", str(config.foundry_repo)],
            cwd=config.foundry_repo,
            capture_output=True, text=True,
            timeout=config.timeout_seconds,
            env={**os.environ, "PYTHONPATH": py_path},
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "success" if result.returncode == 0 else "failed"
        _write_self_test_triage(config, logger, result)
        return StepResult(
            step="self_test", status=status, required=required,
            returncode=result.returncode, duration_ms=duration_ms,
            stdout_tail=_tail(result.stdout, limit=2000),
            stderr_tail=_tail(result.stderr, limit=500),
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="self_test", status="failed", required=required,
            returncode=1, stderr_tail=str(exc), duration_ms=duration_ms,
        )


def _inproc_self_test_action_queue(config: Config, logger: JsonlLogger, required: bool) -> StepResult:
    """Convert self-test triage into bounded local action items."""
    started = time.monotonic()
    try:
        queue_path = _write_self_test_action_queue(config, logger)
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="self_test_action_queue", status="success", required=required,
            returncode=0, duration_ms=duration_ms,
            stdout_tail=f"queue written: {queue_path}",
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="self_test_action_queue", status="skipped", required=required,
            returncode=0, duration_ms=duration_ms,
            reason=str(exc), stderr_tail=str(exc),
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="self_test_action_queue", status="failed", required=required,
            returncode=1, duration_ms=duration_ms, stderr_tail=str(exc),
        )


def _inproc_capability_scan(config: Config, logger: JsonlLogger, required: bool) -> StepResult:
    """Discover tools present but not used in recent sessions."""
    started = time.monotonic()
    scan_path = config.reports_dir / "expansion" / "capability_scan.json"
    scan_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Scan what's available: Foundry modules, Bootstrap scripts, system tools
        foundry_evo = sorted(
            (config.foundry_repo / "evolution" / "core").glob("*.py")
        )
        bootstrap_scripts = list(
            (config.base / "harness").rglob("*.py")
        )

        scan = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "run_id": logger.run_id,
            "foundry_modules": [p.name for p in foundry_evo if p.name != "__init__.py"],
            "bootstrap_scripts": [str(p.relative_to(config.base)) for p in bootstrap_scripts],
            "pip_venv_packages": [],
        }

        # Probe pip venv for installable capabilities
        dspy_py = config.dspy_python
        if Path(dspy_py).is_file():
            try:
                pkg_result = subprocess.run(
                    [dspy_py, "-m", "pip", "list", "--format=json"],
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "LD_LIBRARY_PATH": os.environ.get("NIX_LD_LIBRARY_PATH", "")},
                )
                if pkg_result.returncode == 0:
                    scan["pip_venv_packages"] = [
                        p["name"] for p in json.loads(pkg_result.stdout)
                    ][:50]
            except Exception:
                pass

        scan_path.write_text(json.dumps(scan, indent=2, sort_keys=True), encoding="utf-8")
        logger.emit("capability_scan_complete",
            foundry=len(scan["foundry_modules"]),
            bootstrap=len(scan["bootstrap_scripts"]),
            venv=len(scan["pip_venv_packages"]),
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="capability_scan", status="failed", required=required,
            returncode=1, stderr_tail=str(exc), duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return StepResult(
        step="capability_scan", status="success", required=required,
        returncode=0, duration_ms=duration_ms,
        stdout_tail=f"scan written: {scan_path}",
    )


def _inproc_self_model(config: Config, logger: JsonlLogger, required: bool) -> StepResult:
    """Build a self-describing state document from live pipeline artifacts.

    Runs FIRST in each cycle so downstream steps (especially session_seeder)
    know what was found in the previous cycle.
    """
    started = time.monotonic()
    model_path = config.reports_dir / "self-model.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        action_path = config.reports_dir / "attention-router-bridge" / "action_queue.json"
        candidate_path = config.reports_dir / "trace-optimizer" / "candidate_artifacts.json"
        health_path = config.reports_dir / "observatory" / "health.json"

        def _maybe_read(path):
            if not path.is_file():
                return {}
            try:
                return json.loads(path.read_text())
            except Exception:
                return {}

        actions = _maybe_read(action_path)
        candidates = _maybe_read(candidate_path)
        health = _maybe_read(health_path)

        # Extract pending intentions from action queue
        pending = []
        action_items = []
        if isinstance(actions, dict):
            items = actions.get("action_items", actions if isinstance(actions, list) else [])
            if isinstance(items, dict) and "items" in items:
                items = items["items"]
            for item in ([items] if isinstance(items, dict) else items):
                if isinstance(item, dict):
                    pending.append({
                        "title": item.get("bucket", item.get("title", item.get("finding", str(item)[:80]))),
                        "source": "attention_router",
                    })

        # Extract improvement candidates
        improvements = []
        if isinstance(candidates, dict):
            failure_classes = candidates.get("failure_classes", [])
            for fc in (failure_classes if isinstance(failure_classes, list) else []):
                if isinstance(fc, (str, dict)):
                    improvements.append(str(fc)[:120])

        # Health snapshot
        health_snapshot = {}
        if isinstance(health, dict):
            health_snapshot = {
                "mean_score": health.get("mean_score"),
                "dead_zone_fraction": health.get("dead_zone_fraction"),
                "error_rate": health.get("error_rate"),
                "alerts": [a.get("code") for a in health.get("alerts", []) if isinstance(a, dict)],
            }

        model = {
            "cycle_id": logger.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "pending_intentions": pending,
            "growth_candidates": improvements[:10],
            "health_snapshot": health_snapshot,
        }

        model_path.write_text(json.dumps(model, indent=2, sort_keys=True), encoding="utf-8")
        logger.emit("self_model_written", path=str(model_path),
                    intentions=len(pending), candidates=len(improvements))

    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return StepResult(
            step="self_model", status="failed", required=required,
            returncode=1, stderr_tail=str(exc), duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return StepResult(
        step="self_model", status="success", required=required,
        returncode=0, duration_ms=duration_ms,
        stdout_tail=f"self-model written: {model_path}",
    )


_IN_PROCESS_HANDLERS = {
    "self_model": _inproc_self_model,
    "session_seeder": _inproc_session_seeder,
    "skill_manifest": _inproc_skill_manifest,
    "self_test": _inproc_self_test,
    "self_test_action_queue": _inproc_self_test_action_queue,
    "capability_scan": _inproc_capability_scan,
}


def _run_in_process(
    handler_name: str,
    config: Config,
    logger: JsonlLogger,
    *,
    required: bool,
) -> StepResult:
    handler = _IN_PROCESS_HANDLERS.get(handler_name)
    if handler is None:
        return _skip(handler_name, f"unknown in-process handler: {handler_name}", logger=logger, required=required)
    logger.emit("step_started", step=handler_name, required=required, cwd=str(config.foundry_repo))
    result = handler(config, logger, required=required)
    logger.emit(
        "step_finished",
        level="info" if result.status == "success" else "error",
        step=handler_name,
        status=result.status,
        required=result.required,
        returncode=result.returncode,
        duration_ms=result.duration_ms,
        stdout_tail=result.stdout_tail,
        stderr_tail=result.stderr_tail,
    )
    return result


def validate_config(config: Config) -> None:
    if not (config.foundry_repo / "evolution").is_dir():
        raise RuntimeError(f"Foundry repo missing evolution package: {config.foundry_repo}")
    if not config.sessions_dir.is_dir():
        raise RuntimeError(f"Hermes sessions directory missing: {config.sessions_dir}")
    config.reports_dir.mkdir(parents=True, exist_ok=True)


def run(config: Config, logger: JsonlLogger) -> int:
    validate_config(config)
    session_files = _session_files(config.sessions_dir)
    session_count = len(session_files)
    state = _load_state(config.state_file, logger)
    last_count = int(state.get("session_count", 0) or 0)

    logger.emit(
        "run_started",
        base=str(config.base),
        foundry_repo=str(config.foundry_repo),
        sessions_dir=str(config.sessions_dir),
        reports_dir=str(config.reports_dir),
        state_file=str(config.state_file),
        log_file=str(config.log_file),
        session_count=session_count,
        previous_session_count=last_count,
        force=config.force,
        steps=config.steps,
        required_steps=sorted(config.required_steps),
        python_bin=config.python_bin,
        dspy_python=config.dspy_python,
    )

    if session_count == 0:
        logger.emit("idle", reason="no session_*.json files found", session_count=session_count, previous_session_count=last_count)
        return 0
    if not config.force and session_count <= last_count:
        logger.emit("idle", reason="session count has not increased", session_count=session_count, previous_session_count=last_count)
        return 0

    files_to_export = _session_delta(session_files, last_count, force=config.force)
    logger.emit(
        "session_delta_selected",
        exported_session_count=len(files_to_export),
        total_session_count=session_count,
        previous_session_count=last_count,
        force=config.force,
    )
    message_count = export_sessions_jsonl(files_to_export, config.trace_file, logger)
    if message_count == 0:
        logger.emit("run_finished", level="error", status="failed", reason="no valid session messages exported")
        return 1

    failures: list[StepResult] = []
    for step in config.steps:
        required = step in config.required_steps
        argv, cwd, skip_reason = _command_for_step(step, config)

        # In-process self-expansion handlers
        if skip_reason and skip_reason.startswith("__in_process__"):
            handler_name = skip_reason.replace("__in_process__", "")
            result = _run_in_process(handler_name, config, logger, required=required)
        elif skip_reason:
            result = _skip(step, skip_reason, logger=logger, required=required)
        else:
            assert argv is not None
            result = _run_subprocess(step, argv, cwd=cwd, timeout_seconds=config.timeout_seconds, logger=logger, required=required)
            if step == "observatory_health" and result.stdout_tail.strip():
                # Always capture health output, even on alert rc=1
                out_dir = config.reports_dir / "observatory-health"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "health_report.json").write_text(result.stdout_tail.strip() + "\n", encoding="utf-8")
                logger.emit("artifact_written", step=step, path=str(out_dir / "health_report.json"))

        if required and result.status != "success":
            failures.append(result)
            break
        if not required and result.status == "failed":
            logger.emit("optional_step_failed", level="warning", step=step, returncode=result.returncode)

    if failures:
        logger.emit("run_finished", level="error", status="failed", failed_step=failures[0].step)
        return 1

    # Push any outbox messages to desktop inbox
    relay_count = _relay_outbox(config, logger)

    _write_state(config.state_file, session_count=session_count, run_id=logger.run_id, status="success")
    logger.emit("run_finished", status="success", session_count=session_count, outbox_relayed=relay_count)
    return 0


def main(argv: list[str] | None = None) -> int:
    run_id = uuid.uuid4().hex[:12]
    try:
        config = parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    logger = JsonlLogger(config.log_file, run_id)
    try:
        return run(config, logger)
    except Exception as exc:  # fail closed with a structured record before systemd sees exit 1
        logger.emit("runner_exception", level="error", error=repr(exc))
        logger.emit("run_finished", level="error", status="failed", reason="runner_exception")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
