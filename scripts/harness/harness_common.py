#!/usr/bin/env python3
"""Common helpers for the Hermes node Phase 1 harness."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_BASE = Path(os.environ.get("HERMES_HARNESS_BASE", "/var/lib/hermes"))
STATUS_RANK = {"ok": 0, "warning": 1, "critical": 2}
TOKEN_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_.\-]{6,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)=([^\s]+)"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s]+)"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    text = value
    for pattern in TOKEN_PATTERNS:
        if pattern.pattern.startswith("(?i)(api"):
            text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
        elif pattern.pattern.startswith("(?i)(authorization"):
            text = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def status_max(statuses: Iterable[str]) -> str:
    return max(statuses, key=lambda s: STATUS_RANK.get(s, 2), default="ok")


def check(check_id: str, status: str, summary: str, detail: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"id": check_id, "status": status, "summary": summary}
    if detail:
        item["detail"] = redact(detail)
    return item


def sensor_result(sensor: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sensor": sensor, "status": status_max(c.get("status", "critical") for c in checks), "checks": redact(checks)}


def run_command(argv: list[str], timeout: int = 5, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        completed = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False, env=command_env)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": redact(completed.stdout.strip()[:2000]),
            "stderr": redact(completed.stderr.strip()[:2000]),
        }
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": redact((exc.stdout or "")[:2000] if isinstance(exc.stdout, str) else ""),
            "stderr": "command timed out",
        }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    payload = json.dumps(redact(data), sort_keys=True, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, 0o660)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(redact(row), sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if default is None:
        default = {}
    if not path.exists():
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else dict(default)
    except (OSError, json.JSONDecodeError):
        return dict(default)


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_text_atomic(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(redact(text))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, 0o660)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
