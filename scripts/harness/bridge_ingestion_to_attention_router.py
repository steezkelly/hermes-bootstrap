#!/usr/bin/env python3
"""Chain session-end ingest → attention-router bridge in one safe invocation.

Reads the real-trace ingestion output and feeds it through the
attention_router_bridge, producing action items from detected failures.
Default-off, manual-only, local files only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    rendered = " ".join(command)
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"command not found while running {rendered!r}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"command failed with exit {exc.returncode}: {rendered}") from exc


def bridge_ingestion(
    *,
    python_bin: str,
    foundry_repo: Path,
    ingestion_output_dir: Path,
    bridge_output_dir: Path,
) -> Path:
    """Run attention_router_bridge against a real-trace ingestion output."""
    _run(
        [
            python_bin,
            "-m",
            "evolution.core.attention_router_bridge",
            "--input",
            str(ingestion_output_dir),
            "--out",
            str(bridge_output_dir),
            "--mode",
            "attention_router_bridge",
            "--no-network",
            "--no-external-writes",
        ],
        cwd=foundry_repo,
    )
    return bridge_output_dir / "action_queue.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chain session-end ingest through attention-router bridge."
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python interpreter used to run Foundry modules.",
    )
    parser.add_argument(
        "--foundry-repo",
        type=Path,
        default=Path("/var/lib/hermes/foundry/hermes-agent-self-evolution"),
        help="Local Foundry checkout.",
    )
    parser.add_argument(
        "--ingestion-output-dir",
        type=Path,
        required=True,
        help="Directory containing real-trace ingestion output (run_report.json, etc.).",
    )
    parser.add_argument(
        "--bridge-output-dir",
        type=Path,
        default=Path("/var/lib/hermes/reports/evolution/attention-router-bridge"),
        help="Output directory for the attention-router bridge artifacts.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        default=False,
        help="Print action item summary to stdout and exit without writing bridge artifacts.",
    )
    return parser.parse_args(argv)


def validate_bridge_chain(
    ingestion_dir: Path,
    bridge_dir: Path,
) -> list[str]:
    """Validate the full chain: ingestion artifacts exist + bridge passed."""
    errors: list[str] = []

    # Ingestion side
    ingestion_report = ingestion_dir / "run_report.json"
    if not ingestion_report.is_file():
        errors.append(f"ingestion run_report.json not found: {ingestion_report}")
        return errors

    try:
        report = json.loads(ingestion_report.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid ingestion report: {exc}")
        return errors

    if report.get("mode") != "real_trace":
        errors.append(f"ingestion mode must be real_trace, got {report.get('mode')!r}")

    if report.get("verdict") != "pass":
        errors.append(f"ingestion verdict is {report.get('verdict')!r}, expected pass")

    # Bridge side
    bridge_report = bridge_dir / "run_report.json"
    if not bridge_report.is_file():
        errors.append(f"bridge run_report.json not found: {bridge_report}")
        return errors

    try:
        bridge = json.loads(bridge_report.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid bridge report: {exc}")
        return errors

    if bridge.get("mode") not in {"attention_router_bridge", "fixture"}:
        errors.append(f"bridge mode unexpected: {bridge.get('mode')!r}")

    safety = bridge.get("safety", {})
    if isinstance(safety, dict):
        for key in ("network_allowed", "external_writes_allowed", "github_writes_allowed"):
            if safety.get(key) is not False:
                errors.append(f"bridge safety.{key} is not false")

    # Action queue
    queue = bridge_dir / "action_queue.json"
    if not queue.is_file():
        errors.append(f"action_queue.json not found: {queue}")

    return errors


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    ingestion_dir = Path(args.ingestion_output_dir).resolve()
    bridge_dir = Path(args.bridge_output_dir).resolve()

    if not ingestion_dir.is_dir():
        print(f"ingestion output directory not found: {ingestion_dir}", file=sys.stderr)
        return 1

    try:
        queue_path = bridge_ingestion(
            python_bin=args.python_bin,
            foundry_repo=args.foundry_repo,
            ingestion_output_dir=ingestion_dir,
            bridge_output_dir=bridge_dir,
        )

        errors = validate_bridge_chain(ingestion_dir, bridge_dir)
        if errors:
            print("BRIDGE CHAIN VALIDATION FAILED", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1

        if args.summary_only and queue_path.is_file():
            queue = json.loads(queue_path.read_text())
            items = queue.get("items", [])
            print(f"{len(items)} action item(s) from detected failures:")
            for i, item in enumerate(items, 1):
                print(f"  {i}. [{item.get('bucket', '?')}] {item.get('title', '?')}")
                print(f"     owner: {item.get('owner', '?')}")
                if item.get("failure_class"):
                    print(f"     failure_class: {item['failure_class']}")
            return 0

    except RuntimeError as exc:
        print(f"BRIDGE CHAIN FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"Bridge chain complete: {bridge_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
