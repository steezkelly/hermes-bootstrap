#!/usr/bin/env python3
"""Export the latest Hermes session and ingest it through Foundry real-trace.

This is the manual/default-off session-complete hook target.  It runs
`hermes sessions export` to a private temp JSONL, validates the export, invokes
Foundry's real-trace ingestion module with no-network/no-external-writes, then
validates the mechanical output boundary.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from validate_session_end_ingest import validate, validate_jsonl


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    rendered = " ".join(command)
    try:
        subprocess.run(command, cwd=cwd, env=env, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"command not found while running {rendered!r}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"command failed with exit {exc.returncode}: {rendered}") from exc


def export_last_session(hermes_bin: str, export_path: Path) -> None:
    # Keep this literal for static boundary tests: hermes sessions export
    _run([hermes_bin, "sessions", "export", str(export_path)])


def ingest_real_trace(
    *,
    python_bin: str,
    foundry_repo: Path,
    trace_path: Path,
    output_dir: Path,
) -> None:
    evolution_dir = foundry_repo / "evolution"
    if not evolution_dir.is_dir():
        raise RuntimeError(f"Foundry repo missing evolution package: {foundry_repo}")

    _run(
        [
            python_bin,
            "-m",
            "evolution.core.real_trace_ingestion",
            "--trace",
            str(trace_path),
            "--out",
            str(output_dir),
            "--mode",
            "real_trace",
            "--no-network",
            "--no-external-writes",
        ],
        cwd=foundry_repo,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the latest Hermes session and ingest it through Foundry real-trace."
    )
    parser.add_argument(
        "--hermes-bin",
        default=os.environ.get("HERMES_BIN", "hermes"),
        help="Hermes CLI executable used for 'hermes sessions export'.",
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
        help="Local Foundry checkout containing the evolution package.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/var/lib/hermes/reports/evolution/session-end-ingest"),
        help="Foundry output directory for this manual hook run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        with tempfile.TemporaryDirectory(prefix="hermes-session-end-ingest-") as tmpdir:
            export_path = Path(tmpdir) / "last-session.jsonl"
            export_last_session(args.hermes_bin, export_path)

            jsonl_errors = validate_jsonl(export_path)
            if jsonl_errors:
                raise RuntimeError("; ".join(jsonl_errors))

            ingest_real_trace(
                python_bin=args.python_bin,
                foundry_repo=args.foundry_repo,
                trace_path=export_path,
                output_dir=args.out,
            )

            errors = validate(export_path, args.out)
            if errors:
                raise RuntimeError("; ".join(errors))
    except RuntimeError as exc:
        print(f"SESSION-END INGEST FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"Session-end ingest completed: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
