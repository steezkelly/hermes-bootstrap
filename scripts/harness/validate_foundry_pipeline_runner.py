#!/usr/bin/env python3
"""Thin bootstrap boundary validator for Foundry pipeline-runner output.

Validates ONLY mechanical file existence, JSON parse, schema_version,
child-report aggregation shape, and external-write/network safety. Does NOT
judge pipeline verdict correctness, child verdict correctness, action item
quality, or fixture semantics — those belong to Foundry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_FILE = "pipeline_run.json"
SAFETY_FALSE_KEYS = (
    "external_writes_allowed",
    "github_writes_allowed",
    "network_allowed",
    "production_mutation_allowed",
)


def _load_pipeline_run(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid JSON in {path}: {exc}")
        return None
    if not isinstance(parsed, dict):
        errors.append(f"{path}: pipeline_run.json must be an object")
        return None
    return parsed


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_foundry_pipeline_runner.py <output-dir>", file=sys.stderr)
        return 2

    out_dir = Path(sys.argv[1])
    pipeline_run_path = out_dir / EXPECTED_FILE
    errors: list[str] = []

    if not pipeline_run_path.is_file():
        errors.append(f"missing expected file: {pipeline_run_path}")
        data: dict[str, Any] | None = None
    else:
        data = _load_pipeline_run(pipeline_run_path, errors)

    if data is not None:
        schema_version = data.get("schema_version")
        if not isinstance(schema_version, int) or schema_version < 1:
            errors.append(
                f"{pipeline_run_path}: schema_version must be a positive int, "
                f"got {schema_version!r}"
            )

        external_writes_allowed = data.get("external_writes_allowed")
        if external_writes_allowed is not False:
            errors.append(
                "pipeline_run.json: external_writes_allowed is not false "
                f"(got {external_writes_allowed!r})"
            )

        # Foundry #17 currently emits `reports`; accept it as the concrete
        # child-report array while still checking the requested child_reports
        # contract name if/when Foundry renames it.
        child_reports = data.get("child_reports", data.get("reports"))
        if not isinstance(child_reports, list):
            errors.append(
                "pipeline_run.json: child_reports must be an array "
                "(Foundry #17 reports alias accepted)"
            )

        safety = data.get("safety")
        if not isinstance(safety, dict):
            errors.append("pipeline_run.json: safety must be a dict")
        else:
            for key in SAFETY_FALSE_KEYS:
                value = safety.get(key)
                if value is not False:
                    errors.append(
                        f"pipeline_run.json: safety.{key} is not false "
                        f"(got {value!r})"
                    )

    if errors:
        print("BOUNDARY VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
