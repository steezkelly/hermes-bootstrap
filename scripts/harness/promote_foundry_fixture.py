#!/usr/bin/env python3
"""
Manual promotion path: create a GitHub PR from a Foundry promotion dossier.

Reads the promotion_dossier.md from a fixture output directory, opens a PR
against the Foundry repo, and posts the dossier as the PR body.

This is manual/default-off — no automatic PR creation. Requires the user to
explicitly invoke this service after reviewing the dossier.

The promotion path:
  1. Reads artifact_manifest.json from <fixture-dir>
  2. Reads promotion_dossier.md from <fixture-dir>
  3. Creates a draft PR in steezkelly/hermes-agent-self-evolution
  4. No automatic merge — review required
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FOUNDRY_REPO = "steezkelly/hermes-agent-self-evolution"
BRANCH_PREFIX = "promotion/dry-run"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: promote_foundry_fixture.py <fixture-output-dir>", file=sys.stderr)
        return 2

    fixture_dir = Path(sys.argv[1]).resolve()
    manifest_path = fixture_dir / "artifact_manifest.json"
    dossier_path = fixture_dir / "promotion_dossier.md"

    if not manifest_path.is_file():
        print(f"artifact_manifest.json not found in {fixture_dir}", file=sys.stderr)
        return 1

    if not dossier_path.is_file():
        print(f"promotion_dossier.md not found in {fixture_dir}", file=sys.stderr)
        return 1

    # Validate manifest
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Failed to read manifest: {exc}", file=sys.stderr)
        return 1

    if manifest.get("external_writes_allowed") is not False:
        print(
            f"Refusing promotion: external_writes_allowed={manifest.get('external_writes_allowed')}",
            file=sys.stderr,
        )
        return 1

    if not manifest.get("review_required"):
        print(
            "Refusing promotion: review_required is not true in manifest",
            file=sys.stderr,
        )
        return 1

    dossier_text = dossier_path.read_text()
    if not dossier_text.strip():
        print("Empty dossier — nothing to promote.", file=sys.stderr)
        return 1

    # Generate safe branch name from the fixture directory name
    fixture_name = fixture_dir.name.replace(" ", "-").replace("/", "-")
    branch_name = f"{BRANCH_PREFIX}/{fixture_name}"

    # Determine candidate artifact name from manifest for the PR title
    candidate_version = manifest.get("artifact_versions", {}).get(
        "candidate", "artifact"
    )

    # Output a ready-to-paste gh command so the operator reviews before
    # any GitHub write occurs. The operator must have a branch checked out.
    gh_cmd = (
        f"gh pr create --repo {FOUNDRY_REPO} "
        f"--title 'Promotion: {candidate_version} (from {fixture_name})' "
        f"--body '{dossier_path}' "
        f"--head $(git branch --show-current) "
        f"--base main --draft"
    )
    print(gh_cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
