#!/usr/bin/env python3
"""Deterministic system health sensor for Phase 1."""

from __future__ import annotations

from harness_common import check, run_command, sensor_result


def collect() -> dict:
    checks = []

    df = run_command(["df", "-P", "/"], timeout=5)
    if df["ok"]:
        lines = df["stdout"].splitlines()
        pct = 0
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 5:
                pct = int(parts[4].rstrip("%"))
        status = "critical" if pct >= 95 else "warning" if pct >= 85 else "ok"
        checks.append(check("system.disk.root", status, f"Root filesystem {pct}% used"))
    else:
        checks.append(check("system.disk.root", "critical", "Could not read root filesystem usage", df["stderr"]))

    free = run_command(["free", "-m"], timeout=5)
    if free["ok"]:
        checks.append(check("system.memory", "ok", "Memory command completed"))
    else:
        checks.append(check("system.memory", "warning", "Could not read memory usage", free["stderr"]))

    failed = run_command(["systemctl", "--failed", "--no-legend", "--plain"], timeout=5)
    if failed["ok"] and not failed["stdout"].strip():
        checks.append(check("system.systemd.failed-units", "ok", "No failed systemd units"))
    elif failed["ok"]:
        count = len([line for line in failed["stdout"].splitlines() if line.strip()])
        checks.append(check("system.systemd.failed-units", "warning", f"{count} failed systemd unit(s)"))
    else:
        checks.append(check("system.systemd.failed-units", "warning", "Could not query failed systemd units", failed["stderr"]))

    timedate = run_command(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=5)
    if timedate["ok"]:
        synced = timedate["stdout"].strip().lower() == "yes"
        checks.append(check("system.time.ntp", "ok" if synced else "warning", "NTP synchronized" if synced else "NTP not synchronized"))
    else:
        checks.append(check("system.time.ntp", "warning", "Could not query time sync", timedate["stderr"]))

    return sensor_result("system", checks)


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), sort_keys=True, indent=2))
