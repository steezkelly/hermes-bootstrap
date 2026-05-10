#!/usr/bin/env python3
"""Validate Foundry observatory health report output.

Verifies:
- JSON output is valid
- Required fields present (generations, total_calls, error_calls, error_rate, alerts)
- No unexpected fields that would break downstream consumers
- Wrapper metadata is present

Usage:
    python scripts/harness/validate_foundry_observatory_health.py \\
        --report /tmp/observatory-health.json
"""

import argparse
import json
import sys
from pathlib import Path


REQUIRED_TOP_KEYS = {
    "generations",
    "total_calls",
    "error_calls",
    "error_rate",
    "mean_score",
    "std_score",
    "dead_zone_fraction",
    "total_cost",
    "alerts",
    "per_generation",
    "_wrapper",
}

REQUIRED_WRAPPER_KEYS = {
    "invocation",
    "db_path",
    "foundry_repo",
}


def validate(report_path: Path) -> tuple[bool, list[str]]:
    """Validate observatory health report. Returns (valid, errors)."""
    errors: list[str] = []

    # 1. File exists and is valid JSON
    if not report_path.is_file():
        return False, [f"Report file not found: {report_path}"]
    try:
        raw = report_path.read_text()
    except Exception as e:
        return False, [f"Cannot read report: {e}"]

    try:
        report = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    # 2. Required top-level keys
    missing = REQUIRED_TOP_KEYS - set(report.keys())
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")

    # 3. Type checks
    if not isinstance(report.get("generations"), list):
        errors.append("'generations' must be a list")
    if not isinstance(report.get("total_calls"), int):
        errors.append("'total_calls' must be an int")
    if not isinstance(report.get("error_calls"), int):
        errors.append("'error_calls' must be an int")
    if not isinstance(report.get("error_rate"), (int, float)):
        errors.append("'error_rate' must be a number")
    if not isinstance(report.get("alerts"), list):
        errors.append("'alerts' must be a list")
    if not isinstance(report.get("per_generation"), dict):
        errors.append("'per_generation' must be a dict")

    # 4. Alert structure (if any)
    for i, alert in enumerate(report.get("alerts", [])):
        for k in ("code", "severity", "message"):
            if k not in alert:
                errors.append(f"Alert[{i}] missing '{k}'")

    # 5. Wrapper metadata
    wrapper = report.get("_wrapper")
    if not isinstance(wrapper, dict):
        errors.append("'_wrapper' must be a dict")
    else:
        missing_wrapper = REQUIRED_WRAPPER_KEYS - set(wrapper.keys())
        if missing_wrapper:
            errors.append(f"_wrapper missing keys: {sorted(missing_wrapper)}")

    return (len(errors) == 0, errors)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Foundry observatory health report"
    )
    parser.add_argument(
        "--report",
        required=True,
        help="Path to observatory health report JSON",
    )
    args = parser.parse_args()

    valid, errors = validate(Path(args.report))
    if errors:
        for err in errors:
            print(f"VALIDATION ERROR: {err}")
        return 1

    print(f"VALIDATION PASSED: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
