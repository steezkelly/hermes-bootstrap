#!/usr/bin/env python3
"""Static local release-policy sensor for Phase 1."""

from __future__ import annotations

from pathlib import Path

from harness_common import check, sensor_result


UNSUPPORTED_NIXOS = {"24.05": "NixOS 24.05 is past bugfix/security support"}


def _read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def collect(os_release_path: Path = Path("/etc/os-release")) -> dict:
    release = _read_os_release(os_release_path)
    version = release.get("VERSION_ID", "unknown")
    if version in UNSUPPORTED_NIXOS:
        status = "warning"
        summary = UNSUPPORTED_NIXOS[version]
    elif version == "unknown":
        status = "warning"
        summary = "Could not determine NixOS release"
    else:
        status = "ok"
        summary = f"NixOS {version} release policy OK"
    return sensor_result("release_policy", [check(f"release.nixos{version.replace('.', '_')}.unsupported", status, summary)])


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), sort_keys=True, indent=2))
