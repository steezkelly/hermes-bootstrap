#!/usr/bin/env python3
"""Run Foundry ContentEvolver through a bootstrap-safe wrapper.

This wrapper invokes evolution.skills.evolve_content, whose CLI is:
  --skill, --eval-source, --dataset-path, --evaluator-model,
  --rewrite-model, --rewrite-budget, --hermes-repo, --weak-fraction,
  --dry-run

Foundry owns section scoring/rewriting semantics. Bootstrap owns:
- explicit CLI/env adaptation for the NixOS appliance
- a single report directory under /var/lib/hermes/reports/evolution
- mechanical wrapper_report.json metadata
- copying generated artifacts out of evolve_content's timestamped output dir

Content evolution is LLM-backed when not --dry-run, so network_allowed is
truthfully recorded as true for real runs and false for dry runs. The wrapper
still performs no GitHub writes, no production mutation, and writes only under
--output-dir.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_ARTIFACTS = {
    "evolved_skill": "evolved_skill.md",
    "baseline_skill": "baseline_skill.md",
    "metrics": "metrics.json",
}


def _tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Foundry content evolution")
    parser.add_argument("--foundry-repo", required=True, help="Foundry repo root")
    parser.add_argument("--python-bin", default="/usr/bin/python3", help="Python binary")
    parser.add_argument("--skill", required=True, help="Skill name to evolve")
    parser.add_argument("--output-dir", required=True, help="Directory for wrapper output")
    parser.add_argument(
        "--eval-source",
        default="synthetic",
        choices=["synthetic", "golden", "sessiondb"],
        help="evolve_content.py --eval-source value",
    )
    parser.add_argument("--dataset-path", default=None, help="Optional eval dataset path")
    parser.add_argument(
        "--evaluator-model",
        default="minimax/minimax-m2.7",
        help="Model for section scoring",
    )
    parser.add_argument(
        "--rewrite-model",
        default="minimax/minimax-m2.7",
        help="Model for section rewriting",
    )
    parser.add_argument("--rewrite-budget", type=int, default=3)
    parser.add_argument("--hermes-repo", default=None, help="Hermes repo or .hermes root for skill discovery")
    parser.add_argument("--weak-fraction", type=float, default=1 / 3)
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without LLM rewriting")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    return parser


def _command(args: argparse.Namespace) -> list[str]:
    cmd = [
        args.python_bin,
        "-m",
        "evolution.skills.evolve_content",
        "--skill",
        args.skill,
        "--eval-source",
        args.eval_source,
        "--evaluator-model",
        args.evaluator_model,
        "--rewrite-model",
        args.rewrite_model,
        "--rewrite-budget",
        str(args.rewrite_budget),
        "--weak-fraction",
        str(args.weak_fraction),
    ]
    if args.dataset_path:
        cmd.extend(["--dataset-path", args.dataset_path])
    if args.hermes_repo:
        cmd.extend(["--hermes-repo", args.hermes_repo])
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def _base_report(args: argparse.Namespace, cmd: list[str], output_dir: Path, work_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "content_evolution",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "skill": args.skill,
        "eval_source": args.eval_source,
        "dataset_path": args.dataset_path,
        "evaluator_model": args.evaluator_model,
        "rewrite_model": args.rewrite_model,
        "rewrite_budget": args.rewrite_budget,
        "weak_fraction": args.weak_fraction,
        "dry_run": args.dry_run,
        "foundry_repo": str(Path(args.foundry_repo).resolve()),
        "hermes_repo": args.hermes_repo,
        "output_dir": str(output_dir),
        "work_dir": str(work_dir),
        "invocation": {
            "script": "run_foundry_content_evolution.py",
            "module": "evolution.skills.evolve_content",
            "argv": cmd,
        },
        "safety": {
            "network_allowed": not args.dry_run,
            "external_writes_allowed": False,
            "github_writes_allowed": False,
            "production_mutation_allowed": False,
        },
        "process": {
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
        },
        "artifacts": {},
    }


def _latest_content_output(work_dir: Path, skill: str) -> Path | None:
    root = work_dir / "output" / skill
    if not root.is_dir():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("content_")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _copy_artifacts(generated_dir: Path, output_dir: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    for logical_name, filename in EXPECTED_ARTIFACTS.items():
        src = generated_dir / filename
        if not src.is_file():
            raise FileNotFoundError(f"missing generated artifact: {src}")
        dst = output_dir / filename
        shutil.copy2(src, dst)
        copied[logical_name] = filename
    return copied


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    foundry_repo = Path(args.foundry_repo).resolve()
    evolve_content = foundry_repo / "evolution" / "skills" / "evolve_content.py"
    if not evolve_content.is_file():
        print(f"ERROR: evolve_content.py not found under Foundry repo: {evolve_content}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir).resolve()
    work_dir = output_dir / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = _command(args)
    report = _base_report(args, cmd, output_dir, work_dir)
    report_path = output_dir / "wrapper_report.json"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{foundry_repo}{os.pathsep}" + env.get("PYTHONPATH", "")
    # Let Foundry's Nous auth and skill fallback resolve /var/lib/hermes/.hermes
    # under systemd instead of the hermes-harness user's passwd home.
    env.setdefault("HOME", "/var/lib/hermes")
    env.setdefault("HERMES_HOME", "/var/lib/hermes/.hermes")
    if args.hermes_repo:
        env.setdefault("HERMES_AGENT_REPO", args.hermes_repo)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(work_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        report["process"].update(
            {
                "returncode": None,
                "stdout_tail": _tail(exc.stdout or ""),
                "stderr_tail": _tail(exc.stderr or ""),
                "error": f"timeout after {args.timeout_seconds}s",
            }
        )
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"ERROR: content evolution timed out after {args.timeout_seconds}s", file=sys.stderr)
        return 1

    report["process"].update(
        {
            "returncode": result.returncode,
            "stdout_tail": _tail(result.stdout),
            "stderr_tail": _tail(result.stderr),
        }
    )

    exit_code = result.returncode
    if result.returncode == 0 and not args.dry_run:
        generated_dir = _latest_content_output(work_dir, args.skill)
        if generated_dir is None:
            report["process"]["error"] = "no content output directory found under work/output/<skill>/content_*"
            exit_code = 1
        else:
            report["generated_output_dir"] = str(generated_dir)
            try:
                report["artifacts"] = _copy_artifacts(generated_dir, output_dir)
            except FileNotFoundError as exc:
                report["process"]["error"] = str(exc)
                exit_code = 1

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    if exit_code == 0:
        print(f"Content evolution wrapper report written to {report_path}")
        if not args.dry_run:
            print(f"Artifacts copied to {output_dir}")
    else:
        print(f"ERROR: content evolution failed; report written to {report_path}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
