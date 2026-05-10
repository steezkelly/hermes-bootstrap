#!/usr/bin/env python3
"""Run Foundry observatory health report against a judge_audit_log.db.

Usage:
    python scripts/harness/run_foundry_observatory_health.py \\
        --db-path /tmp/judge_audit_log.db \\
        --skill github-code-review \\
        --output /tmp/observatory-health.json

This wrapper invokes Foundry's observatory CLI in --json mode, producing
a machine-readable health report that downstream validators can consume.

Safety: no network, no external writes, no GitHub mutations.
Deterministic: reads only the supplied DB, writes only to --output.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Foundry observatory health report"
    )
    parser.add_argument(
        "--foundry-repo",
        required=True,
        help="Path to Foundry repo root (hermes-agent-self-evolution)",
    )
    parser.add_argument(
        "--python-bin",
        default="/usr/bin/python3",
        help="Python binary to use (default: /usr/bin/python3)",
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to judge_audit_log.db",
    )
    parser.add_argument(
        "--skill",
        default=None,
        help="Optional: filter by skill name",
    )
    parser.add_argument(
        "--generation",
        type=int,
        default=None,
        help="Optional: filter by generation number",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write JSON health report",
    )

    args = parser.parse_args()

    foundry_repo = Path(args.foundry_repo)
    if not foundry_repo.is_dir():
        print(f"ERROR: Foundry repo not found: {foundry_repo}")
        return 1

    cli_module = "evolution.core.observatory.cli"
    cmd = [
        args.python_bin,
        "-m", cli_module,
        "--db-path", str(args.db_path),
        "health",
        "--json",
    ]
    if args.skill:
        cmd.extend(["--skill", args.skill])
    if args.generation is not None:
        cmd.extend(["--generation", str(args.generation)])

    result = subprocess.run(
        cmd,
        cwd=str(foundry_repo),
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode not in (0, 1):
        # exit 1 = alerts found (still valid JSON output)
        print(f"ERROR: observatory health failed (exit {result.returncode})")
        print(f"stderr: {result.stderr[:500]}")
        return 1

    if not result.stdout.strip():
        print("ERROR: no JSON output from observatory health")
        print(f"stderr: {result.stderr[:500]}")
        return 1

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON from observatory: {e}")
        print(f"stdout: {result.stdout[:500]}")
        return 1

    # Tag the output with invocation metadata
    report["_wrapper"] = {
        "invocation": "run_foundry_observatory_health.py",
        "db_path": str(args.db_path),
        "skill": args.skill,
        "generation": args.generation,
        "foundry_repo": str(foundry_repo),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2))

    has_alerts = bool(report.get("alerts"))
    print(f"Observatory health report written to {output_path}")
    print(f"  Generations: {report.get('generations', [])}")
    print(f"  Total calls: {report.get('total_calls', 0)}")
    print(f"  Errors: {report.get('error_calls', 0)} ({report.get('error_rate', 0):.2%})")
    print(f"  Alerts: {len(report.get('alerts', []))}")
    if has_alerts:
        for alert in report.get("alerts", []):
            print(f"    [{alert['severity']}] {alert['code']}: {alert['message'][:80]}")

    return 1 if has_alerts else 0


if __name__ == "__main__":
    sys.exit(main())
