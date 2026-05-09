#!/usr/bin/env python3
"""Thin bootstrap boundary validator for Foundry attention-router bridge output.

Validates ONLY mechanical file-existence, JSON parse, schema_version, and
external-writes safety. Does NOT evaluate action-item quality, routing bucket
correctness, prompt wording, or promotion-dossier prose — those belong to
Foundry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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


def _load_json_file(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid JSON in {path}: {exc}")
        return None
    if not isinstance(parsed, dict):
        errors.append(f"{path}: JSON artifact must be an object")
        return None
    return parsed


def _validate_schema_version(fname: str, fpath: Path, data: dict[str, Any], errors: list[str]) -> None:
    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        errors.append(
            f"{fpath}: schema_version must be a positive int, got {schema_version!r}"
        )


def _validate_external_writes(fname: str, data: dict[str, Any], errors: list[str]) -> None:
    external_writes_allowed = data.get("external_writes_allowed")
    if external_writes_allowed is not None and external_writes_allowed is not False:
        errors.append(
            f"{fname}: external_writes_allowed is not false "
            f"(got {external_writes_allowed!r})"
        )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "Usage: validate_foundry_attention_router_bridge.py <output-dir>",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(sys.argv[1])
    errors: list[str] = []

    # 1. All expected files must exist. Markdown dossier existence is the only
    # bootstrap-owned check for the dossier; prose semantics belong to Foundry.
    for fname in EXPECTED_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            errors.append(f"missing expected file: {fpath}")

    # 2. JSON files must parse as objects.
    parsed: dict[str, dict[str, Any]] = {}
    for fname in JSON_FILES:
        fpath = out_dir / fname
        if not fpath.is_file():
            continue
        data = _load_json_file(fpath, errors)
        if data is not None:
            parsed[fname] = data

    # 3. schema_version must be a positive integer in every JSON artifact.
    for fname, data in parsed.items():
        _validate_schema_version(fname, out_dir / fname, data, errors)

    # 4. external_writes_allowed must be explicitly false when present.
    for fname, data in parsed.items():
        _validate_external_writes(fname, data, errors)

    # 5. Safety block in run_report must deny network / writes / GitHub.
    report = parsed.get("run_report.json", {})
    safety = report.get("safety")
    if not isinstance(safety, dict):
        errors.append("run_report.json: 'safety' must be a dict")
    else:
        for key in (
            "external_writes_allowed",
            "github_writes_allowed",
            "network_allowed",
            "production_mutation_allowed",
        ):
            value = safety.get(key)
            if value is not False:
                errors.append(f"run_report.json: safety.{key} is not false (got {value!r})")

    # 6. Mode must be the attention-router bridge mode.
    for fname, data in parsed.items():
        mode = data.get("mode")
        if mode != "attention_router_bridge":
            errors.append(f"{fname}: mode must be 'attention_router_bridge', got {mode!r}")

    if errors:
        print("BOUNDARY VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
