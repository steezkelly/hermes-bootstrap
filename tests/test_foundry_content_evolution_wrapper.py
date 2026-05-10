"""Bootstrap tests for Foundry content evolution wrapper + validator.

Content evolution wraps evolution.skills.evolve_content, which rewrites weak
skill sections through an LLM. Bootstrap owns only the appliance wrapper,
mechanical output validation, and systemd/Nix boundaries.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_SCRIPT = REPO_ROOT / "scripts" / "harness" / "run_foundry_content_evolution.py"
VALIDATOR_SCRIPT = REPO_ROOT / "scripts" / "harness" / "validate_foundry_content_evolution.py"
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"
DOC_PATH = REPO_ROOT / "docs" / "foundry-dry-run-wrapper.md"


def _fake_foundry_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "foundry"
    (repo / "evolution" / "skills").mkdir(parents=True)
    (repo / "evolution" / "skills" / "evolve_content.py").write_text("# fake marker\n")
    return repo


def _fake_python_bin(tmp_path: Path, *, produce_output: bool = True) -> Path:
    script = tmp_path / "fake-python"
    producer = """
from pathlib import Path
import json
skill = sys.argv[sys.argv.index('--skill') + 1] if '--skill' in sys.argv else 'unknown'
if {produce_output!r} and '--dry-run' not in sys.argv:
    out = Path.cwd() / 'output' / skill / 'content_20000101_000000'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'evolved_skill.md').write_text('# evolved\\n')
    (out / 'baseline_skill.md').write_text('# baseline\\n')
    (out / 'metrics.json').write_text(json.dumps({{'improvement': 0.25, 'baseline_score': 0.5, 'candidate_score': 0.75}}))
print(json.dumps({{'argv': sys.argv}}))
""".format(produce_output=produce_output)
    script.write_text("#!/usr/bin/env python3\nimport sys\n" + producer)
    script.chmod(0o755)
    return script


def _run_wrapper(tmp_path: Path, *, dry_run: bool = False, produce_output: bool = True) -> subprocess.CompletedProcess:
    foundry_repo = _fake_foundry_repo(tmp_path)
    fake_python = _fake_python_bin(tmp_path, produce_output=produce_output)
    out_dir = tmp_path / "content-evolution"
    cmd = [
        "/usr/bin/python3",
        str(WRAPPER_SCRIPT),
        "--foundry-repo", str(foundry_repo),
        "--python-bin", str(fake_python),
        "--skill", "github-code-review",
        "--output-dir", str(out_dir),
        "--eval-source", "synthetic",
        "--evaluator-model", "minimax/minimax-m2.7",
        "--rewrite-model", "minimax/minimax-m2.7",
        "--rewrite-budget", "2",
        "--weak-fraction", "0.5",
        "--hermes-repo", str(tmp_path / "hermes-home"),
    ]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15)


def _valid_report(*, dry_run: bool = False, network_allowed: bool = True) -> dict:
    return {
        "schema_version": 1,
        "mode": "content_evolution",
        "skill": "github-code-review",
        "eval_source": "synthetic",
        "evaluator_model": "minimax/minimax-m2.7",
        "rewrite_model": "minimax/minimax-m2.7",
        "rewrite_budget": 2,
        "weak_fraction": 0.5,
        "dry_run": dry_run,
        "safety": {
            "network_allowed": network_allowed,
            "external_writes_allowed": False,
            "github_writes_allowed": False,
            "production_mutation_allowed": False,
        },
        "process": {"returncode": 0},
        "artifacts": {
            "evolved_skill": "evolved_skill.md",
            "baseline_skill": "baseline_skill.md",
            "metrics": "metrics.json",
        } if not dry_run else {},
    }


def _run_validator(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/usr/bin/python3", str(VALIDATOR_SCRIPT), str(path)],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestContentEvolutionWrapper:
    def test_wrapper_script_exists(self):
        assert WRAPPER_SCRIPT.is_file()

    def test_wrapper_dry_run_writes_mechanical_report(self, tmp_path):
        result = _run_wrapper(tmp_path, dry_run=True)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((tmp_path / "content-evolution" / "wrapper_report.json").read_text())
        assert report["mode"] == "content_evolution"
        assert report["skill"] == "github-code-review"
        assert report["dry_run"] is True
        assert report["safety"]["network_allowed"] is False
        assert report["safety"]["external_writes_allowed"] is False
        assert report["safety"]["github_writes_allowed"] is False

    def test_wrapper_real_run_collects_evolve_content_artifacts(self, tmp_path):
        result = _run_wrapper(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        out_dir = tmp_path / "content-evolution"
        assert (out_dir / "evolved_skill.md").read_text() == "# evolved\n"
        assert (out_dir / "baseline_skill.md").read_text() == "# baseline\n"
        metrics = json.loads((out_dir / "metrics.json").read_text())
        assert metrics["improvement"] == 0.25
        report = json.loads((out_dir / "wrapper_report.json").read_text())
        assert report["safety"]["network_allowed"] is True
        assert report["artifacts"]["metrics"] == "metrics.json"
        assert "evolution.skills.evolve_content" in " ".join(report["invocation"]["argv"])

    def test_wrapper_fails_if_real_run_produces_no_artifact_directory(self, tmp_path):
        result = _run_wrapper(tmp_path, produce_output=False)
        assert result.returncode != 0
        report = json.loads((tmp_path / "content-evolution" / "wrapper_report.json").read_text())
        assert report["process"]["returncode"] == 0
        assert "no content output directory" in report["process"]["error"]


class TestContentEvolutionValidator:
    def test_validator_script_exists(self):
        assert VALIDATOR_SCRIPT.is_file()

    def test_valid_real_output_passes(self, tmp_path):
        (tmp_path / "wrapper_report.json").write_text(json.dumps(_valid_report()))
        (tmp_path / "evolved_skill.md").write_text("# evolved\n")
        (tmp_path / "baseline_skill.md").write_text("# baseline\n")
        (tmp_path / "metrics.json").write_text(json.dumps({"improvement": 0.25}))
        result = _run_validator(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_valid_dry_run_output_passes_without_evolved_artifacts(self, tmp_path):
        (tmp_path / "wrapper_report.json").write_text(json.dumps(_valid_report(dry_run=True, network_allowed=False)))
        result = _run_validator(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_missing_wrapper_report_fails(self, tmp_path):
        result = _run_validator(tmp_path)
        assert result.returncode == 1
        assert "wrapper_report.json" in result.stdout + result.stderr

    def test_invalid_metrics_json_fails(self, tmp_path):
        (tmp_path / "wrapper_report.json").write_text(json.dumps(_valid_report()))
        (tmp_path / "evolved_skill.md").write_text("# evolved\n")
        (tmp_path / "baseline_skill.md").write_text("# baseline\n")
        (tmp_path / "metrics.json").write_text("not json")
        result = _run_validator(tmp_path)
        assert result.returncode == 1
        assert "invalid JSON" in result.stdout + result.stderr

    def test_external_writes_are_rejected(self, tmp_path):
        report = _valid_report()
        report["safety"]["external_writes_allowed"] = True
        (tmp_path / "wrapper_report.json").write_text(json.dumps(report))
        (tmp_path / "evolved_skill.md").write_text("# evolved\n")
        (tmp_path / "baseline_skill.md").write_text("# baseline\n")
        (tmp_path / "metrics.json").write_text(json.dumps({"improvement": 0.25}))
        result = _run_validator(tmp_path)
        assert result.returncode == 1
        assert "external_writes_allowed" in result.stdout + result.stderr


class TestContentEvolutionNixContract:
    def test_nix_binding_and_validator_binding_exist(self):
        text = HARNESS_NIX.read_text()
        assert "foundryContentEvolution = pkgs.writeShellApplication" in text
        assert "name = \"hermes-evolution-foundry-content-evolution\"" in text
        assert "validateFoundryContentEvolution = pkgs.writeShellApplication" in text
        assert "name = \"hermes-validate-foundry-content-evolution\"" in text

    def test_nix_binding_invokes_evolve_content_cli_args(self):
        text = HARNESS_NIX.read_text()
        assert "run_foundry_content_evolution.py" in text
        assert "--foundry-repo /var/lib/hermes/foundry/hermes-agent-self-evolution" in text
        assert "--skill \"$skill\"" in text
        assert "--eval-source \"$eval_source\"" in text
        assert "--rewrite-budget \"$rewrite_budget\"" in text
        assert "--weak-fraction \"$weak_fraction\"" in text
        assert "--output-dir /var/lib/hermes/reports/evolution/content-evolution" in text

    def test_services_are_manual_default_off_and_no_timer(self):
        text = HARNESS_NIX.read_text()
        service_name = "hermes-evolution-foundry-content-evolution"
        validator_name = "hermes-validate-foundry-content-evolution"
        assert f"systemd.services.{service_name}" in text
        assert f"systemd.services.{validator_name}" in text
        assert f"systemd.timers.{service_name}" not in text
        assert f"systemd.timers.{validator_name}" not in text
        service_block = text[text.index(f"systemd.services.{service_name}"): text.index(f"systemd.services.{validator_name}")]
        validator_block = text[text.index(f"systemd.services.{validator_name}"):]
        validator_block = validator_block[: validator_block.find("systemd.", 1) if validator_block.find("systemd.", 1) != -1 else len(validator_block)]
        assert "wantedBy" not in service_block
        assert "wantedBy" not in validator_block

    def test_service_boundaries_are_explicit(self):
        text = HARNESS_NIX.read_text()
        start = text.index("systemd.services.hermes-evolution-foundry-content-evolution")
        end = text.index("systemd.services.hermes-validate-foundry-content-evolution")
        service_block = text[start:end]
        assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/content-evolution" ]' in service_block
        assert '"/var/lib/hermes/foundry"' in service_block
        assert '"/var/lib/hermes/.hermes"' in service_block
        assert '"-/var/lib/hermes/secrets"' in service_block
        assert '"-/var/lib/hermes/.hermes/.env"' in service_block
        assert "EnvironmentFile" not in service_block
        assert "GITHUB_TOKEN" not in service_block

        vstart = text.index("systemd.services.hermes-validate-foundry-content-evolution")
        vend = text.find("systemd.", vstart + 1)
        validator_block = text[vstart:] if vend == -1 else text[vstart:vend]
        assert "ReadWritePaths = lib.mkForce [ ];" in validator_block
        assert '"/var/lib/hermes/reports/evolution/content-evolution"' in validator_block

    def test_docs_include_manual_flow(self):
        doc = DOC_PATH.read_text()
        assert "hermes-evolution-foundry-content-evolution" in doc
        assert "hermes-validate-foundry-content-evolution" in doc
        assert "FOUNDRY_CONTENT_SKILL" in doc
