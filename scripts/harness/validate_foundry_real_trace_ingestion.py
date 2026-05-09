#!/usr/bin/env python3
"""Thin bootstrap boundary validator for Foundry real-trace ingestion output.

Validates ONLY mechanical file-existence, JSON parse, schema_version, and
external-writes safety. Does NOT evaluate detector accuracy, failure-class
correctness, or promotion-dossier prose — those belong to Foundry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_FILES: list[str] = [
    "run_report.json",
    "eval_examples.json",
    "promotion_dossier.md",
    "artifact_manifest.json",
]

JSON_FILES: set[str] = {
    "run_report.json",
    "eval_examples.json",
    "artifact_manifest.json",
}


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "Usage: validate_foundry_real_trace_ingestion.py <output-dir>",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(sys.argv[1])
    errors: list[str] = []

    # 1. All expected files must exist
    for fname in EXPECTED_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            errors.append(f"missing expected file: {fpath}")

    # 2. JSON files must parse
    parsed: dict[str, dict] = {}
    for fname in JSON_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            continue
        try:
            parsed[fname] = json.loads(fpath.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"invalid JSON in {fpath}: {exc}")

    # 3. schema_version must be a positive integer
    for fname, data in parsed.items():
        sv = data.get("schema_version")
        if not isinstance(sv, int) or sv < 1:
            fpath = out_dir / fname
            errors.append(f"{fpath}: schema_version must be a positive int, got {sv!r}")

    # 4. external_writes_allowed must be explicitly false
    for fname, data in parsed.items():
        ewa = data.get("external_writes_allowed")
        if ewa is not None and ewa is not False:
            errors.append(f"{fname}: external_writes_allowed is not false (got {ewa!r})")

    # 5. Safety block in run_report must deny network / writes
    rr = parsed.get("run_report.json", {})
    safety = rr.get("safety")
    if safety is not None:
        if not isinstance(safety, dict):
            errors.append("run_report.json: 'safety' must be a dict")
        else:
            for key in (
                "external_writes_allowed",
                "github_writes_allowed",
                "network_allowed",
                "production_mutation_allowed",
            ):
                val = safety.get(key)
                if val is not False:
                    errors.append(
                        f"run_report.json: safety.{key} is not false (got {val!r})"
                    )

    # 6. mode must be "real_trace" (not "fixture")
    mode = rr.get("mode")
    if mode != "real_trace":
        errors.append(f"run_report.json: mode must be 'real_trace', got {mode!r}")

    # 7. Must have source_trace field pointing to the ingested file
    source_trace = rr.get("source_trace")
    if not source_trace or not isinstance(source_trace, str):
        errors.append(f"run_report.json: source_trace missing or not a string")

    # 8. eval_examples.json must have total_examples >= 1
    ee = parsed.get("eval_examples.json", {})
    total = ee.get("total_examples")
    if total is not None:
        if not isinstance(total, int) or total < 1:
            errors.append(
                f"eval_examples.json: total_examples must be >= 1, got {total!r}"
            )

    if errors:
        print("BOUNDARY VALIDATION FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
