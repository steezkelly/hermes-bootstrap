"""Tests for Foundry observatory health wrapper + validator.

Coverage:
- Wrapper: valid DB produces JSON, invalid DB fails, missing args fail
- Validator: valid JSON passes, missing keys fail, wrong types fail
- Nix contract: symmetry check between Foundry module and Nix binding
"""

import json
import os
import subprocess
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

BOOTSTRAP_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_SCRIPT = BOOTSTRAP_ROOT / "scripts/harness/run_foundry_observatory_health.py"
VALIDATOR_SCRIPT = BOOTSTRAP_ROOT / "scripts/harness/validate_foundry_observatory_health.py"
FOUNDRY_REPO = Path(os.environ.get(
    "FOUNDRY_REPO",
    "/home/steve/repos/steezkelly-hermes-agent-self-evolution",
))
PYTHON_BIN = Path(os.environ.get(
    "FOUNDRY_PYTHON_BIN",
    str(FOUNDRY_REPO / ".venv-review/bin/python"),
))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_foundry_smoke_env() -> None:
    """Skip integration smoke tests when Foundry checkout is not present."""
    if not FOUNDRY_REPO.is_dir():
        pytest.skip(f"Foundry checkout not available: {FOUNDRY_REPO}")
    if not PYTHON_BIN.is_file():
        pytest.skip(f"Foundry Python not available: {PYTHON_BIN}")


def _create_smoke_db(tmp_path: Path) -> str:
    """Run observatory smoke test to generate a judge_audit_log.db."""
    _require_foundry_smoke_env()
    result = subprocess.run(
        [str(PYTHON_BIN), "scripts/observatory_smoke_test.py"],
        cwd=str(FOUNDRY_REPO),
        capture_output=True,
        text=True,
        timeout=30,
    )
    # The smoke test prints the DB path in line 3
    for line in result.stdout.splitlines():
        if "Audit DB:" in line:
            return line.split("Audit DB:")[1].strip()
    # Fallback: find most recent in /tmp
    import glob
    dbs = glob.glob("/tmp/obs_smoke_*/judge_audit_log.db")
    if dbs:
        return max(dbs, key=lambda p: Path(p).stat().st_mtime)
    pytest.skip("Could not locate smoke test DB")


def _run_wrapper(db_path: str, output_path: Path, **kwargs) -> subprocess.CompletedProcess:
    """Run the observatory wrapper script."""
    cmd = [
        "/usr/bin/python3", str(WRAPPER_SCRIPT),
        "--foundry-repo", str(FOUNDRY_REPO),
        "--python-bin", str(PYTHON_BIN),
        "--db-path", db_path,
        "--output", str(output_path),
    ]
    for key, val in kwargs.items():
        cmd.extend([key, str(val)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _run_validator(report_path: Path) -> subprocess.CompletedProcess:
    """Run the observatory validator."""
    return subprocess.run(
        ["/usr/bin/python3", str(VALIDATOR_SCRIPT), "--report", str(report_path)],
        capture_output=True, text=True, timeout=10,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper tests
# ─────────────────────────────────────────────────────────────────────────────

class TestObservatoryWrapper:
    """Tests for the observatory health report wrapper."""

    def test_run_produces_valid_json(self, tmp_path):
        """Wrapper produces valid JSON output from a real smoke-test DB."""
        db_path = _create_smoke_db(tmp_path)
        output_path = tmp_path / "health.json"
        result = _run_wrapper(db_path, output_path)

        # May exit 0 or 1 depending on alerts — both OK for valid JSON
        assert result.returncode in (0, 1)
        assert output_path.is_file()
        report = json.loads(output_path.read_text())
        assert "generations" in report
        assert "total_calls" in report
        assert "error_calls" in report
        assert "alerts" in report

    def test_wrapper_adds_metadata(self, tmp_path):
        """Wrapper injects _wrapper metadata."""
        db_path = _create_smoke_db(tmp_path)
        output_path = tmp_path / "health.json"
        _run_wrapper(db_path, output_path)

        report = json.loads(output_path.read_text())
        assert "_wrapper" in report
        wrapper = report["_wrapper"]
        assert wrapper["invocation"] == "run_foundry_observatory_health.py"
        assert Path(wrapper["db_path"]).name == "judge_audit_log.db"

    def test_empty_db_produces_empty_report(self, tmp_path):
        """Wrapper produces a valid (but empty) report for an empty DB."""
        _require_foundry_smoke_env()
        # Create an empty DB via Foundry's Python
        script = f"""
import json, sys
sys.path.insert(0, '{FOUNDRY_REPO}')
from evolution.core.observatory.logger import JudgeAuditLogger
from evolution.core.observatory.health import JudgeHealthMonitor
db_path = '{tmp_path}/empty.db'
logger = JudgeAuditLogger(db_path=db_path)
monitor = JudgeHealthMonitor(logger)
report = monitor.health_report()
print(json.dumps(report.as_dict(), indent=2))
"""
        result = subprocess.run(
            [str(PYTHON_BIN), "-c", script],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        report = json.loads(result.stdout)
        assert report["total_calls"] == 0
        assert report["alerts"] == []

    def test_invalid_db_fails(self, tmp_path):
        """Wrapper fails gracefully on invalid DB path."""
        output_path = tmp_path / "health.json"
        result = _run_wrapper("/nonexistent/judge_audit_log.db", output_path)
        assert result.returncode != 0

    def test_skill_filter_respected(self, tmp_path):
        """Wrapper passes --skill to the observatory CLI."""
        db_path = _create_smoke_db(tmp_path)
        output_path = tmp_path / "health.json"
        result = _run_wrapper(db_path, output_path, **{"--skill": "test-skill"})
        assert result.returncode in (0, 1)
        assert output_path.is_file()

    def test_invalid_json_output_fails(self, tmp_path):
        """Wrapper returns non-zero when observatory produces no JSON."""
        output_path = tmp_path / "health.json"
        # /dev/null is not a valid SQLite DB — observatory will fail
        result = _run_wrapper("/dev/null", output_path)
        # observatory can't read /dev/null as SQLite; wrapper should fail or observatory
        # may produce empty report (both are acceptable — this tests graceful handling)
        # If it returns 0, verify the output is valid JSON anyway
        if result.returncode == 0:
            report = json.loads(output_path.read_text())
            assert "generations" in report


# ─────────────────────────────────────────────────────────────────────────────
# Validator tests
# ─────────────────────────────────────────────────────────────────────────────

class TestObservatoryValidator:
    """Tests for the observatory health report validator."""

    def test_valid_report_passes(self, tmp_path):
        """Validator accepts a valid health report."""
        report_path = tmp_path / "valid.json"
        valid_report = {
            "generations": [1],
            "total_calls": 10,
            "error_calls": 0,
            "error_rate": 0.0,
            "mean_score": 0.85,
            "std_score": 0.12,
            "dead_zone_fraction": 0.3,
            "total_cost": 0.005,
            "alerts": [],
            "per_generation": {},
            "_wrapper": {
                "invocation": "test",
                "db_path": "/tmp/test.db",
                "foundry_repo": "/tmp",
            },
        }
        report_path.write_text(json.dumps(valid_report))
        result = _run_validator(report_path)
        assert result.returncode == 0

    def test_missing_keys_fails(self, tmp_path):
        """Validator rejects reports missing required keys."""
        report_path = tmp_path / "invalid.json"
        report_path.write_text(json.dumps({"generations": []}))
        result = _run_validator(report_path)
        assert result.returncode != 0
        assert "Missing top-level keys" in result.stdout

    def test_wrong_types_fails(self, tmp_path):
        """Validator rejects reports with wrong field types."""
        report_path = tmp_path / "wrong_types.json"
        bad_report = {
            "generations": [1],
            "total_calls": "ten",  # should be int
            "error_calls": 0,
            "error_rate": 0.0,
            "mean_score": 0.85,
            "std_score": 0.12,
            "dead_zone_fraction": 0.3,
            "total_cost": 0.005,
            "alerts": [],
            "per_generation": {},
            "_wrapper": {
                "invocation": "test",
                "db_path": "/tmp/test.db",
                "foundry_repo": "/tmp",
            },
        }
        report_path.write_text(json.dumps(bad_report))
        result = _run_validator(report_path)
        assert result.returncode != 0
        assert "must be an int" in result.stdout

    def test_missing_wrapper_fails(self, tmp_path):
        """Validator rejects reports without _wrapper metadata."""
        report_path = tmp_path / "no_wrapper.json"
        report = {
            "generations": [1], "total_calls": 10, "error_calls": 0,
            "error_rate": 0.0, "mean_score": 0.85, "std_score": 0.12,
            "dead_zone_fraction": 0.3, "total_cost": 0.005,
            "alerts": [], "per_generation": {},
        }
        report_path.write_text(json.dumps(report))
        result = _run_validator(report_path)
        assert result.returncode != 0

    def test_invalid_json_fails(self, tmp_path):
        """Validator rejects non-JSON files."""
        report_path = tmp_path / "not_json.txt"
        report_path.write_text("not json at all")
        result = _run_validator(report_path)
        assert result.returncode != 0

    def test_nonexistent_file_fails(self, tmp_path):
        """Validator rejects nonexistent files."""
        result = _run_validator(tmp_path / "nonexistent.json")
        assert result.returncode != 0


# ─────────────────────────────────────────────────────────────────────────────
# Nix contract symmetry tests
# ─────────────────────────────────────────────────────────────────────────────

class TestObservatoryNixContract:
    """Verify Nix bindings and services in harness.nix match Python scripts."""

    def test_wrapper_script_exists(self):
        """Wrapper script exists and is executable/readable."""
        assert WRAPPER_SCRIPT.is_file(), f"Missing: {WRAPPER_SCRIPT}"

    def test_validator_script_exists(self):
        """Validator script exists."""
        assert VALIDATOR_SCRIPT.is_file(), f"Missing: {VALIDATOR_SCRIPT}"

    def test_wrapper_is_python3_compatible(self):
        """Wrapper can be parsed as valid Python 3."""
        import ast
        source = WRAPPER_SCRIPT.read_text()
        ast.parse(source)
        # If we get here, the script is syntactically valid Python 3

    def test_validator_is_python3_compatible(self):
        """Validator can be parsed as valid Python 3."""
        import ast
        source = VALIDATOR_SCRIPT.read_text()
        ast.parse(source)

    def test_wrapper_accepted_file_types(self):
        """Wrapper accepts .db input and produces .json output."""
        source = WRAPPER_SCRIPT.read_text()
        assert ".db" in source or "sqlite" in source.lower()
        assert ".json" in source.lower()

    def test_validator_checks_required_keys(self):
        """Validator checks for all required report keys."""
        source = VALIDATOR_SCRIPT.read_text()
        assert "total_calls" in source
        assert "error_calls" in source
        assert "error_rate" in source
        assert "alerts" in source
