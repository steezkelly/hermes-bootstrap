#!/usr/bin/env python3
"""Boundary validator for the manual Hermes session-end Foundry ingest.

Checks only bootstrap-owned mechanical boundaries:
- exported Hermes JSONL parses as JSONL
- Foundry ingestion report exists and parses
- external_writes_allowed is effectively false

It does not judge detector quality, generated examples, or dossier text.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def validate_jsonl(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"exported JSONL not found: {path}"]

    records = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{path}:{line_no}: invalid JSONL: {exc}")
                    continue
                if not isinstance(parsed, dict):
                    errors.append(f"{path}:{line_no}: JSONL record must be an object")
                records += 1
    except OSError as exc:
        return [f"failed to read exported JSONL {path}: {exc}"]

    if records < 1:
        errors.append(f"exported JSONL has no records: {path}")
    return errors


def _load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.is_file():
        return None, [f"ingestion report not found: {path}"]
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, [f"invalid ingestion report JSON {path}: {exc}"]
    if not isinstance(parsed, dict):
        return None, [f"ingestion report must be a JSON object: {path}"]
    return parsed, []


def _external_writes_effectively_false(report: dict[str, Any]) -> bool:
    top_level = report.get("external_writes_allowed")
    if top_level is True:
        return False
    if top_level is False:
        return True

    safety = report.get("safety")
    if isinstance(safety, dict):
        return safety.get("external_writes_allowed") is False
    return False


def validate(exported_jsonl: Path, output_dir: Path) -> list[str]:
    errors = validate_jsonl(exported_jsonl)

    report, report_errors = _load_json(output_dir / "run_report.json")
    errors.extend(report_errors)
    if report is None:
        return errors

    schema_version = report.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        errors.append(
            f"run_report.json: schema_version must be a positive int, got {schema_version!r}"
        )

    if report.get("mode") != "real_trace":
        errors.append(f"run_report.json: mode must be 'real_trace', got {report.get('mode')!r}")

    if not _external_writes_effectively_false(report):
        errors.append("run_report.json: external_writes_allowed is not false")

    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "Usage: validate_session_end_ingest.py <exported-jsonl> <output-dir>",
            file=sys.stderr,
        )
        return 2

    errors = validate(Path(args[0]), Path(args[1]))
    if errors:
        print("SESSION-END INGEST BOUNDARY VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Session-end ingest boundary validation passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
