#!/usr/bin/env python3
"""Deterministic Hermes service sensor for Phase 1."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from harness_common import DEFAULT_BASE, check, run_command, sensor_result


def _cron_permission_check(base: Path) -> dict:
    cron = base / ".hermes" / "cron"
    if not cron.exists():
        return check("hermes.state.cron.permission-regression", "ok", "Hermes cron state path absent")
    try:
        mode = stat.S_IMODE(cron.stat().st_mode)
        group_readable = bool(mode & stat.S_IRGRP and mode & stat.S_IXGRP)
        return check(
            "hermes.state.cron.permission-regression",
            "ok" if group_readable else "warning",
            "Hermes cron path is group-readable" if group_readable else f"Hermes cron path mode is {mode:o}, not group-readable",
        )
    except OSError as exc:
        return check("hermes.state.cron.permission-regression", "warning", "Could not stat Hermes cron state path", str(exc))


def _secrets_inaccessible_check(base: Path) -> dict:
    secret = base / "secrets" / "hermes.env"
    try:
        with secret.open("r", encoding="utf-8") as fh:
            fh.read(1)
        return check("harness.secrets.inaccessible", "critical", "Harness can read Hermes secrets; sandbox is broken")
    except FileNotFoundError:
        return check("harness.secrets.inaccessible", "ok", "Hermes secrets file absent or hidden")
    except PermissionError:
        return check("harness.secrets.inaccessible", "ok", "Hermes secrets file is inaccessible")
    except OSError as exc:
        return check("harness.secrets.inaccessible", "ok", "Hermes secrets file is inaccessible", str(exc))


def _gateway_config_host(base: Path) -> str | None:
    config = base / ".hermes" / "config.yaml"
    if not config.exists():
        return None
    in_gateway = False
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped == "gateway:":
            in_gateway = True
            continue
        if in_gateway and line and not line.startswith(" ") and not line.startswith("\t"):
            in_gateway = False
        if in_gateway and stripped.startswith("host:"):
            return stripped.split(":", 1)[1].strip().strip('"\'')
    return None


def _gateway_locality_check(base: Path, port: str = "8080") -> dict:
    ss = run_command(["ss", "-ltn"], timeout=5)
    if not ss["ok"]:
        return check("hermes.gateway.localhost-only", "warning", "Could not inspect listening TCP sockets", ss["stderr"])
    bad = []
    found = False
    suffix = f":{port}"
    for line in ss["stdout"].splitlines():
        fields = line.split()
        local = fields[3] if len(fields) >= 4 else ""
        if local.endswith(suffix):
            found = True
            if not (local.startswith("127.0.0.1:") or local.startswith("[::1]:") or local.startswith("localhost:")):
                bad.append(local)
    if bad:
        return check("hermes.gateway.localhost-only", "critical", f"Gateway port {port} is not localhost-only", ", ".join(bad))
    if found:
        return check("hermes.gateway.localhost-only", "ok", "Gateway listener is localhost-only")
    configured_host = _gateway_config_host(base)
    if configured_host in {"127.0.0.1", "localhost", "::1"}:
        return check("hermes.gateway.localhost-only", "ok", f"Gateway configured for localhost ({configured_host}); no listener found")
    if configured_host:
        return check("hermes.gateway.localhost-only", "critical", f"Gateway configured for non-local host {configured_host}")
    return check("hermes.gateway.localhost-only", "warning", f"Gateway port {port} listener and config host not found")


def collect(base: Path | None = None) -> dict:
    if base is None:
        base = DEFAULT_BASE
    checks = []

    active = run_command(["systemctl", "is-active", "hermes-agent.service"], timeout=5)
    checks.append(check("hermes.service.active", "ok" if active["ok"] and active["stdout"] == "active" else "critical", "hermes-agent.service is active" if active["ok"] and active["stdout"] == "active" else "hermes-agent.service is not active", active.get("stdout") or active.get("stderr")))

    status_cmd = "/run/current-system/sw/bin/hermes" if Path("/run/current-system/sw/bin/hermes").exists() else "hermes"
    status = run_command(
        [status_cmd, "status"],
        timeout=10,
        env={"HERMES_HOME": str(base / ".hermes"), "HOME": str(base)},
    )
    status_detail = None if status["ok"] else (status.get("stderr") or status.get("stdout"))
    checks.append(check("hermes.cli.status", "ok" if status["ok"] else "warning", "hermes status exits 0" if status["ok"] else "hermes status failed", status_detail))

    checks.append(_cron_permission_check(base))
    checks.append(_secrets_inaccessible_check(base))
    checks.append(_gateway_locality_check(base, os.environ.get("HERMES_GATEWAY_PORT", "8080")))

    return sensor_result("hermes", checks)


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), sort_keys=True, indent=2))
