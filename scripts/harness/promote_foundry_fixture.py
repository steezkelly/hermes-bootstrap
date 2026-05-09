#!/usr/bin/env python3
"""
Manual promotion path: output a ready-to-paste gh pr create --draft command
from a Foundry fixture's promotion dossier.

This is manual/default-off — no automatic PR creation. Requires the operator
to explicitly invoke this, review the output, and paste the command.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FOUNDRY_REPO = "steezkelly/hermes-agent-self-evolution"


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

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Failed to read manifest: {exc}", file=sys.stderr)
        return 1

    if manifest.get("external_writes_allowed") is not False:
        print(
            f"Refusing: external_writes_allowed={manifest.get('external_writes_allowed')}",
            file=sys.stderr,
        )
        return 1

    if not manifest.get("review_required"):
        print("Refusing: review_required is not true", file=sys.stderr)
        return 1

    candidate_version = manifest.get("artifact_versions", {}).get("candidate", "artifact")
    fixture_name = fixture_dir.name
    dossier_body = dossier_path.read_text().replace("'", "'\"'\"'")

    gh_cmd = (
        f"gh pr create --repo {FOUNDRY_REPO} "
        f"--title 'Promotion: {candidate_version} (from {fixture_name})' "
        f"--body '$(cat {dossier_path})' "
        f"--base main --draft"
    )
    print(gh_cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
