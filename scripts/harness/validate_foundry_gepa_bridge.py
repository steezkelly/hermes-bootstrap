#!/usr/bin/env python3
"""Thin bootstrap boundary validator for Foundry GEPA trace bridge output.

Validates ONLY mechanical file-existence, JSON parse, schema_version, and
safety flags. Does NOT evaluate dataset quality or manifest correctness —
those belong to Foundry.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_FILES: list[str] = [
    "run_report.json",
    "gepa_manifest.json",
]

JSON_FILES: set[str] = {
    "run_report.json",
    "gepa_manifest.json",
}

SAFETY_KEYS: list[str] = [
    "network_allowed",
    "external_writes_allowed",
    "github_writes_allowed",
]


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_foundry_gepa_bridge.py <output_dir>", file=sys.stderr)
        return 1

    output_dir = Path(sys.argv[1]).resolve()

    if not output_dir.is_dir():
        print(f"Directory not found: {output_dir}", file=sys.stderr)
        return 1

    errors: list[str] = []

    for fname in EXPECTED_FILES:
        fp = output_dir / fname
        if not fp.is_file():
            errors.append(f"missing expected file: {fname}")
            continue
        if fname in JSON_FILES:
            try:
                json.loads(fp.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"invalid JSON in {fname}: {exc}")

    run_report = output_dir / "run_report.json"
    if run_report.is_file():
        try:
            report = json.loads(run_report.read_text())
        except (json.JSONDecodeError, OSError):
            report = {}

        if report.get("schema_version") != 1:
            errors.append(f"schema_version is {report.get('schema_version')}, expected 1")

        if report.get("mode") != "gepa_bridge":
            errors.append(f"mode is {report.get('mode')}, expected gepa_bridge")

        safety = report.get("safety", {})
        if isinstance(safety, dict):
            for key in SAFETY_KEYS:
                if safety.get(key) is not False:
                    errors.append(f"safety.{key} is {safety.get(key)}, expected False")

    # Verify manifest datasets reference real directories
    manifest_path = output_dir / "gepa_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            manifest = {}

        datasets = manifest.get("datasets", [])
        if isinstance(datasets, list):
            for ds in datasets:
                if isinstance(ds, dict):
                    ds_path = ds.get("dataset_path", "")
                    if ds_path and not Path(ds_path).is_dir():
                        errors.append(f"dataset path does not exist: {ds_path}")

    if errors:
        print("BOUNDARY VALIDATION FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
