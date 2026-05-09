#!/usr/bin/env python3
"""
Thin bootstrap boundary validator for Foundry action-routing fixture output.

Validates ONLY mechanical file-existence, JSON parse, schema_version, and
external-writes safety. Does NOT evaluate gate verdicts, action-item ranking,
or promotion-dossier prose — those belong to Foundry, not bootstrap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_FILES: list[str] = [
    "run_report.json",
    "action_queue.json",
    "promotion_dossier.md",
    "artifact_manifest.json",
]

JSON_FILES: set[str] = {
    "run_report.json",
    "action_queue.json",
    "artifact_manifest.json",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_foundry_action_routing_fixture.py <output-dir>", file=sys.stderr)
        return 2

    out_dir = Path(sys.argv[1])
    errors: list[str] = []

    # ------------------------------------------------------------------
    # 1. All expected files must exist
    # ------------------------------------------------------------------
    for fname in EXPECTED_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            errors.append(f"missing expected file: {fpath}")

    # ------------------------------------------------------------------
    # 2. JSON files must parse
    # ------------------------------------------------------------------
    parsed: dict[str, dict] = {}
    for fname in JSON_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            continue  # already reported above
        try:
            parsed[fname] = json.loads(fpath.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"invalid JSON in {fpath}: {exc}")

    # ------------------------------------------------------------------
    # 3. schema_version must be a positive integer
    # ------------------------------------------------------------------
    for fname, data in parsed.items():
        sv = data.get("schema_version")
        if not isinstance(sv, int) or sv < 1:
            errors.append(f"{fpath}: schema_version must be a positive int, got {sv!r}")

    # ------------------------------------------------------------------
    # 4. external_writes_allowed must be explicitly false (where present)
    # ------------------------------------------------------------------
    for fname, data in parsed.items():
        ewa = data.get("external_writes_allowed")
        if ewa is not None and ewa is not False:
            errors.append(f"{fname}: external_writes_allowed is not false (got {ewa!r})")

    # ------------------------------------------------------------------
    # 5. Safety block in run_report must deny network / writes (if present)
    # ------------------------------------------------------------------
    rr = parsed.get("run_report.json", {})
    safety = rr.get("safety")
    if safety is not None:
        if not isinstance(safety, dict):
            errors.append("run_report.json: 'safety' must be a dict")
        else:
            for key in ("external_writes_allowed", "github_writes_allowed", "network_allowed", "production_mutation_allowed"):
                val = safety.get(key)
                if val is not False:
                    errors.append(
                        f"run_report.json: safety.{key} is not false (got {val!r})"
                    )

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    if errors:
        print("BOUNDARY VALIDATION FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
