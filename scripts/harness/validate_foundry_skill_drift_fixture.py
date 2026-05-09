#!/usr/bin/env python3
"""Thin bootstrap boundary validator for Foundry skill-drift fixture output.

Validates ONLY mechanical file-existence, JSON parse, schema_version, and
external-writes safety. Does NOT evaluate diff contents or recommendations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_FILES: list[str] = [
    "run_report.json",
    "skill_diff.txt",
    "promotion_dossier.md",
    "artifact_manifest.json",
]
JSON_FILES = {"run_report.json", "artifact_manifest.json"}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_foundry_skill_drift_fixture.py <output-dir>", file=sys.stderr)
        return 2

    out_dir = Path(sys.argv[1])
    errors: list[str] = []

    for fname in EXPECTED_FILES:
        if not (out_dir / fname).is_file():
            errors.append(f"missing expected file: {out_dir / fname}")

    parsed: dict[str, dict] = {}
    for fname in JSON_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            continue
        try:
            parsed[fname] = json.loads(fpath.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"invalid JSON in {fpath}: {exc}")

    for fname, data in parsed.items():
        sv = data.get("schema_version")
        if not isinstance(sv, int) or sv < 1:
            errors.append(f"{out_dir / fname}: schema_version must be positive int, got {sv!r}")

    for fname, data in parsed.items():
        ewa = data.get("external_writes_allowed")
        if ewa is not None and ewa is not False:
            errors.append(f"{fname}: external_writes_allowed is not false (got {ewa!r})")

    rr = parsed.get("run_report.json", {})
    safety = rr.get("safety")
    if safety is not None:
        if not isinstance(safety, dict):
            errors.append("run_report.json: 'safety' must be a dict")
        else:
            for key in ("external_writes_allowed", "github_writes_allowed", "network_allowed", "production_mutation_allowed"):
                val = safety.get(key)
                if val is not False:
                    errors.append(f"run_report.json: safety.{key} is not false (got {val!r})")

    if errors:
        print("BOUNDARY VALIDATION FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
