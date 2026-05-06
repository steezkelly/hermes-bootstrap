#!/usr/bin/env python3
"""Deterministic network health sensor for Phase 1."""

from __future__ import annotations

import socket

from harness_common import check, run_command, sensor_result


def collect() -> dict:
    checks = []

    ip = run_command(["ip", "-4", "addr", "show", "scope", "global"], timeout=5)
    checks.append(check("network.lan-ip", "ok" if ip["ok"] and ip["stdout"] else "warning", "LAN IPv4 address present" if ip["ok"] and ip["stdout"] else "No LAN IPv4 address detected"))

    route = run_command(["ip", "route", "show", "default"], timeout=5)
    checks.append(check("network.default-route", "ok" if route["ok"] and route["stdout"] else "warning", "Default route present" if route["ok"] and route["stdout"] else "No default route detected"))

    try:
        socket.getaddrinfo("nixos.org", 443, proto=socket.IPPROTO_TCP)
        checks.append(check("network.dns", "ok", "DNS resolution works"))
    except OSError as exc:
        checks.append(check("network.dns", "warning", "DNS resolution failed", str(exc)))

    https = run_command(["python3", "-c", "import urllib.request; urllib.request.urlopen('https://nixos.org', timeout=5).read(1)"], timeout=8)
    checks.append(check("network.internet-https", "ok" if https["ok"] else "warning", "Internet HTTPS probe works" if https["ok"] else "Internet HTTPS probe failed", https.get("stderr") or None))

    return sensor_result("network", checks)


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), sort_keys=True, indent=2))
