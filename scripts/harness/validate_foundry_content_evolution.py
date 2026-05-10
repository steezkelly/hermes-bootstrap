#!/usr/bin/env python3
"""Validate Bootstrap output for Foundry content evolution.

This validator is intentionally mechanical. It checks wrapper_report.json,
JSON parseability, expected copied artifacts, schema_version, and safety flags.
It does NOT judge whether the evolved skill is better; that belongs to Foundry.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_REAL_ARTIFACTS = [
    "evolved_skill.md",
    "baseline_skill.md",
    "metrics.json",
]

SAFETY_KEYS = [
    "network_allowed",
    "external_writes_allowed",
    "github_writes_allowed",
    "production_mutation_allowed",
]


def _load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path.name}: {exc}")
        return None
    except OSError as exc:
        errors.append(f"cannot read {path.name}: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"{path.name} must contain a JSON object")
        return None
    return data


def validate(output_dir: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not output_dir.is_dir():
        return False, [f"output directory not found: {output_dir}"]

    report_path = output_dir / "wrapper_report.json"
    if not report_path.is_file():
        return False, ["missing expected file: wrapper_report.json"]

    report = _load_json(report_path, errors)
    if report is None:
        return False, errors

    if report.get("schema_version") != 1:
        errors.append(f"schema_version is {report.get('schema_version')}, expected 1")
    if report.get("mode") != "content_evolution":
        errors.append(f"mode is {report.get('mode')}, expected content_evolution")
    if not isinstance(report.get("skill"), str) or not report.get("skill"):
        errors.append("skill must be a non-empty string")
    if report.get("eval_source") not in {"synthetic", "golden", "sessiondb"}:
        errors.append(f"eval_source is {report.get('eval_source')}, expected synthetic|golden|sessiondb")
    if not isinstance(report.get("rewrite_budget"), int) or report.get("rewrite_budget") < 0:
        errors.append("rewrite_budget must be a non-negative int")
    if not isinstance(report.get("weak_fraction"), (int, float)):
        errors.append("weak_fraction must be numeric")

    dry_run = report.get("dry_run") is True
    process = report.get("process", {})
    if not isinstance(process, dict):
        errors.append("process must be a dict")
    elif process.get("returncode") != 0:
        errors.append(f"process.returncode is {process.get('returncode')}, expected 0")

    safety = report.get("safety", {})
    if not isinstance(safety, dict):
        errors.append("safety must be a dict")
    else:
        for key in SAFETY_KEYS:
            if key not in safety:
                errors.append(f"safety.{key} missing")
        expected_network = False if dry_run else True
        if safety.get("network_allowed") is not expected_network:
            errors.append(
                f"safety.network_allowed is {safety.get('network_allowed')}, expected {expected_network}"
            )
        for key in ["external_writes_allowed", "github_writes_allowed", "production_mutation_allowed"]:
            if safety.get(key) is not False:
                errors.append(f"safety.{key} is {safety.get(key)}, expected False")

    if not dry_run:
        for filename in EXPECTED_REAL_ARTIFACTS:
            fp = output_dir / filename
            if not fp.is_file():
                errors.append(f"missing expected file: {filename}")
                continue
            if filename.endswith(".json"):
                _load_json(fp, errors)
            elif fp.read_text().strip() == "":
                errors.append(f"{filename} must not be empty")

        artifacts = report.get("artifacts")
        if not isinstance(artifacts, dict):
            errors.append("artifacts must be a dict for real runs")
        else:
            for expected in EXPECTED_REAL_ARTIFACTS:
                if expected not in artifacts.values():
                    errors.append(f"artifacts missing reference to {expected}")

    return len(errors) == 0, errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_foundry_content_evolution.py <output_dir>", file=sys.stderr)
        return 1

    output_dir = Path(sys.argv[1]).resolve()
    valid, errors = validate(output_dir)
    if not valid:
        print("BOUNDARY VALIDATION FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Boundary validation passed for: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
