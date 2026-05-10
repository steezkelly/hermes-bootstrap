"""Tests for the always-on autonomous evolution chain runner.

Bootstrap owns the appliance runner here: path/config/logging/state handling and
mechanical subprocess orchestration. Foundry still owns step semantics.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "harness" / "autonomous" / "chain_runner.py"
HARNESS_NIX = REPO_ROOT / "system" / "nixos" / "harness.nix"


def _write_module(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))


def _fake_foundry_repo(tmp_path: Path, *, fail_bridge: bool = False, include_optional: bool = True) -> Path:
    repo = tmp_path / "foundry"
    core = repo / "evolution" / "core"
    core.mkdir(parents=True)
    (repo / "evolution" / "__init__.py").write_text("")
    (core / "__init__.py").write_text("")

    _write_module(
        core / "real_trace_ingestion.py",
        """
        from pathlib import Path
        import argparse, json
        p = argparse.ArgumentParser(); p.add_argument('--trace'); p.add_argument('--out'); p.add_argument('--mode'); p.add_argument('--no-network', action='store_true'); p.add_argument('--no-external-writes', action='store_true')
        a = p.parse_args()
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        (out / 'eval_examples.json').write_text(json.dumps({'schema_version': 1, 'examples': [{'detected_failure_classes': ['tool_underuse'], 'failure_count': 1}], 'external_writes_allowed': False}))
        (out / 'run_report.json').write_text(json.dumps({'schema_version': 1, 'mode': a.mode, 'verdict': 'pass', 'safety': {'network_allowed': False, 'external_writes_allowed': False, 'github_writes_allowed': False, 'production_mutation_allowed': False}}))
        print('ingested ' + a.trace)
        """,
    )
    _write_module(
        core / "attention_router_bridge.py",
        f"""
        from pathlib import Path
        import argparse, json, sys
        p = argparse.ArgumentParser(); p.add_argument('--input'); p.add_argument('--out'); p.add_argument('--mode'); p.add_argument('--no-network', action='store_true'); p.add_argument('--no-external-writes', action='store_true')
        a = p.parse_args()
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        if {fail_bridge!r}:
            print('bridge exploded', file=sys.stderr)
            raise SystemExit(7)
        (out / 'action_queue.json').write_text(json.dumps({{'schema_version': 1, 'items': [{{'title': 'x'}}], 'external_writes_allowed': False}}))
        (out / 'run_report.json').write_text(json.dumps({{'schema_version': 1, 'mode': a.mode, 'verdict': 'pass', 'safety': {{'network_allowed': False, 'external_writes_allowed': False, 'github_writes_allowed': False, 'production_mutation_allowed': False}}}}))
        print('bridged ' + a.input)
        """,
    )
    _write_module(
        core / "trace_optimizer.py",
        """
        from pathlib import Path
        import argparse, json
        p = argparse.ArgumentParser(); p.add_argument('--eval-examples'); p.add_argument('--out'); p.add_argument('--mode'); p.add_argument('--no-network', action='store_true'); p.add_argument('--no-external-writes', action='store_true')
        a = p.parse_args()
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        (out / 'candidate_artifacts.json').write_text(json.dumps({'schema_version': 1, 'improvements': [{'failure_class': 'tool_underuse'}], 'external_writes_allowed': False}))
        (out / 'run_report.json').write_text(json.dumps({'schema_version': 1, 'mode': a.mode, 'verdict': 'pass', 'safety': {'network_allowed': False, 'external_writes_allowed': False, 'github_writes_allowed': False, 'production_mutation_allowed': False}}))
        print('optimized ' + a.eval_examples)
        """,
    )
    if include_optional:
        _write_module(
            core / "gepa_trace_bridge.py",
            """
            from pathlib import Path
            import argparse, json
            p = argparse.ArgumentParser(); p.add_argument('--candidate-artifacts'); p.add_argument('--out'); p.add_argument('--no-network', action='store_true'); p.add_argument('--no-external-writes', action='store_true')
            a = p.parse_args()
            out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
            (out / 'run_report.json').write_text(json.dumps({'schema_version': 1, 'mode': 'gepa_bridge', 'verdict': 'pass'}))
            print('gepa ' + a.candidate_artifacts)
            """,
        )
        observatory = core / "observatory"
        observatory.mkdir(parents=True)
        (observatory / "__init__.py").write_text("")
        _write_module(
            observatory / "cli.py",
            """
            import argparse, json
            p = argparse.ArgumentParser(); p.add_argument('--db-path'); sub = p.add_subparsers(dest='cmd'); h = sub.add_parser('health'); h.add_argument('--json', action='store_true')
            a = p.parse_args()
            print(json.dumps({'alerts': [], 'db_path': a.db_path}))
            """,
        )
    return repo


def _write_sessions(base: Path, count: int = 1) -> Path:
    sessions = base / ".hermes" / "sessions"
    sessions.mkdir(parents=True)
    for idx in range(1, count + 1):
        (sessions / f"session_{idx}.json").write_text(json.dumps({"messages": [{"role": "user", "content": f"msg {idx}"}]}))
    return sessions


def _run_chain(tmp_path: Path, extra_args: list[str] | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    base = tmp_path / "base"
    reports = base / "reports" / "evolution"
    sessions = _write_sessions(base, count=2)
    foundry = _fake_foundry_repo(tmp_path)
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--base",
        str(base),
        "--foundry-repo",
        str(foundry),
        "--sessions-dir",
        str(sessions),
        "--reports-dir",
        str(reports),
        "--python-bin",
        sys.executable,
        "--dspy-python",
        sys.executable,
        "--force",
    ]
    if extra_args:
        cmd.extend(extra_args)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=merged_env)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestAutonomousChainRunnerScript:
    def test_script_exists(self):
        assert SCRIPT.is_file()

    def test_runs_configured_steps_in_order_and_writes_structured_logs(self, tmp_path):
        base = tmp_path / "base"
        log_file = tmp_path / "chain.jsonl"
        result = _run_chain(tmp_path, extra_args=["--log-file", str(log_file), "--steps", "real_trace_ingestion,attention_router_bridge,trace_optimizer,gepa_bridge"])
        assert result.returncode == 0, result.stdout + result.stderr

        events = _jsonl(log_file)
        step_finishes = [e for e in events if e.get("event") == "step_finished"]
        assert [e["step"] for e in step_finishes] == ["real_trace_ingestion", "attention_router_bridge", "trace_optimizer", "gepa_bridge"]
        assert all(e["returncode"] == 0 for e in step_finishes)
        assert all("duration_ms" in e for e in step_finishes)
        assert all("argv" in e for e in step_finishes)
        assert any(e.get("event") == "run_finished" and e.get("status") == "success" for e in events)

        reports = base / "reports" / "evolution"
        assert (reports / "real-trace-ingestion" / "eval_examples.json").is_file()
        assert (reports / "attention-router-bridge" / "action_queue.json").is_file()
        assert (reports / "trace-optimizer" / "candidate_artifacts.json").is_file()
        assert json.loads((reports / "autonomous-state.json").read_text())["session_count"] == 2

    def test_outbox_relay_is_disabled_by_default_for_local_only_chain(self, tmp_path):
        base = tmp_path / "base"
        outbox = base / "messages" / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "test.json").write_text('{"from":"hermes-node","to":"mint"}\n')
        log_file = tmp_path / "local-only-outbox.jsonl"

        result = _run_chain(
            tmp_path,
            extra_args=["--base", str(base), "--log-file", str(log_file), "--steps", "self_model"],
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert (outbox / "test.json").is_file()
        events = _jsonl(log_file)
        assert any(e.get("event") == "outbox_relay_skipped" and e.get("reason") == "disabled" for e in events)
        assert not any(e.get("event") in {"outbox_relayed", "outbox_relay_failed"} for e in events)
        assert any(e.get("event") == "run_finished" and e.get("outbox_relayed") == 0 for e in events)

    def test_json_config_and_env_override_paths(self, tmp_path):
        base = tmp_path / "base"
        sessions = _write_sessions(base, count=1)
        foundry = _fake_foundry_repo(tmp_path)
        reports = tmp_path / "custom-reports"
        log_file = tmp_path / "configured.jsonl"
        config = tmp_path / "chain-config.json"
        config.write_text(json.dumps({
            "base": str(base),
            "foundry_repo": str(foundry),
            "sessions_dir": str(sessions),
            "reports_dir": str(reports),
            "python_bin": sys.executable,
            "steps": ["real_trace_ingestion"],
        }))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(config), "--force"],
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "HERMES_AUTONOMOUS_LOG_FILE": str(log_file)},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        events = _jsonl(log_file)
        assert [e.get("step") for e in events if e.get("event") == "step_finished"] == ["real_trace_ingestion"]
        assert (reports / "real-trace-ingestion" / "run_report.json").is_file()

    def test_idle_when_session_count_has_not_changed(self, tmp_path):
        base = tmp_path / "base"
        sessions = _write_sessions(base, count=1)
        foundry = _fake_foundry_repo(tmp_path)
        reports = base / "reports" / "evolution"
        reports.mkdir(parents=True)
        (reports / "autonomous-state.json").write_text(json.dumps({"session_count": 1}))
        log_file = tmp_path / "idle.jsonl"
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--base", str(base),
                "--foundry-repo", str(foundry),
                "--sessions-dir", str(sessions),
                "--reports-dir", str(reports),
                "--python-bin", sys.executable,
                "--log-file", str(log_file),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        events = _jsonl(log_file)
        assert any(e.get("event") == "idle" and e.get("session_count") == 1 for e in events)
        assert not any(e.get("event") == "step_started" for e in events)

    def test_gepa_is_skipped_when_configured_python_lacks_imports(self, tmp_path):
        bad_python = tmp_path / "bad-dspy-python"
        bad_python.write_text("#!/bin/sh\necho 'missing sklearn' >&2\nexit 1\n")
        bad_python.chmod(0o755)
        log_file = tmp_path / "gepa-skip.jsonl"
        result = _run_chain(
            tmp_path,
            extra_args=[
                "--log-file", str(log_file),
                "--steps", "real_trace_ingestion,attention_router_bridge,trace_optimizer,gepa_bridge",
                "--dspy-python", str(bad_python),
            ],
        )
        assert result.returncode == 0, result.stdout + result.stderr
        events = _jsonl(log_file)
        skip = [e for e in events if e.get("event") == "step_skipped" and e.get("step") == "gepa_bridge"][0]
        assert "missing required imports" in skip["reason"]
        assert "missing sklearn" in skip["reason"]

    def test_mandatory_step_failure_is_logged_and_returns_nonzero(self, tmp_path):
        base = tmp_path / "base"
        sessions = _write_sessions(base, count=1)
        foundry = _fake_foundry_repo(tmp_path, fail_bridge=True)
        reports = base / "reports" / "evolution"
        log_file = tmp_path / "failed.jsonl"
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--base", str(base),
                "--foundry-repo", str(foundry),
                "--sessions-dir", str(sessions),
                "--reports-dir", str(reports),
                "--python-bin", sys.executable,
                "--log-file", str(log_file),
                "--steps", "real_trace_ingestion,attention_router_bridge,trace_optimizer",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 1
        events = _jsonl(log_file)
        bridge = [e for e in events if e.get("event") == "step_finished" and e.get("step") == "attention_router_bridge"][0]
        assert bridge["returncode"] == 7
        assert "bridge exploded" in bridge["stderr_tail"]
        assert any(e.get("event") == "run_finished" and e.get("status") == "failed" for e in events)

    def test_self_test_uses_dspy_python_path_object_without_runner_exception(self, tmp_path):
        base = tmp_path / "base"
        sessions = _write_sessions(base, count=1)
        foundry = _fake_foundry_repo(tmp_path, include_optional=False)
        tests_dir = foundry / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
        reports = base / "reports" / "evolution"
        log_file = tmp_path / "self-test.jsonl"

        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--base", str(base),
                "--foundry-repo", str(foundry),
                "--sessions-dir", str(sessions),
                "--reports-dir", str(reports),
                "--python-bin", sys.executable,
                "--dspy-python", sys.executable,
                "--log-file", str(log_file),
                "--steps", "self_test",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        events = _jsonl(log_file)
        assert not any(e.get("event") == "runner_exception" for e in events)
        self_test = [e for e in events if e.get("event") == "step_finished" and e.get("step") == "self_test"][0]
        assert self_test["status"] == "success"
        assert self_test["returncode"] == 0

    def test_self_test_writes_actionable_triage_artifact_for_failures(self, tmp_path):
        base = tmp_path / "base"
        sessions = _write_sessions(base, count=1)
        foundry = _fake_foundry_repo(tmp_path, include_optional=False)
        reports = base / "reports" / "evolution"
        log_file = tmp_path / "self-test-triage.jsonl"
        fake_pytest = tmp_path / "fake-pytest-python"
        fake_pytest.write_text(
            "#!/usr/bin/env python3\n"
            "print('FAILED tests/tools/test_tool_description_evolution.py::TestToolDatasetBuilder::test_tool_filter')\n"
            "print('ERROR tests/core/test_constraints.py::TestSizeConstraints::test_skill_under_limit')\n"
            "print('ERROR tests/core/test_v2_pipeline_integration.py::TestFullPipeline::test_pipeline_accepts_improvement')\n"
            "print('ERROR tests/core/test_bad_import.py::test_import - ModuleNotFoundError: No module named rich')\n"
            "print('FAILED tests/core/test_trace_optimizer.py::TestTraceOptimizerCliSafetyFlags::test_missing_safety_flag_fails_closed[--no-network-network safety disabled]')\n"
            "print('FAILED tests/core/test_capture_plugin.py::TestEndToEnd::test_deploy_updates_status')\n"
            "print('FAILED tests/core/test_observatory_logger.py::TestSingleton::test_singleton_same_db')\n"
            "print('FAILED tests/core/test_v2_dispatch.py::test_v2_dispatch_dry_run - FileNotFoundError: missing fixture')\n"
            "print('FAILED tests/core/test_v2_dispatch.py::test_v2_dispatch_returns_report_type')\n"
            "print('9 failed, 1 passed in 0.12s')\n"
            "raise SystemExit(1)\n"
        )
        fake_pytest.chmod(0o755)

        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--base", str(base),
                "--foundry-repo", str(foundry),
                "--sessions-dir", str(sessions),
                "--reports-dir", str(reports),
                "--python-bin", str(fake_pytest),
                "--dspy-python", sys.executable,
                "--log-file", str(log_file),
                "--steps", "self_test",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        triage_path = reports / "expansion" / "self_test_triage.json"
        assert triage_path.is_file()
        triage = json.loads(triage_path.read_text())
        assert triage["schema_version"] == 1
        assert triage["external_writes_allowed"] is False
        assert triage["source_step"] == "self_test"
        assert triage["pytest_returncode"] == 1
        assert triage["summary_counts"]["failed"] == 9
        assert triage["bucket_counts"] == {
            "environment_dependency": 3,
            "expected_fixture_constraint": 1,
            "real_regression": 3,
            "stale_test": 2,
            "unclassified": 0,
        }
        assert {item["bucket"] for item in triage["items"]} == {
            "environment_dependency",
            "expected_fixture_constraint",
            "real_regression",
            "stale_test",
        }
        assert any(
            e.get("event") == "self_test_triage_written" and e.get("items") == 9
            for e in _jsonl(log_file)
        )

    def test_skill_manifest_reads_optimizer_candidates_and_action_items(self, tmp_path):
        base = tmp_path / "base"
        sessions = _write_sessions(base, count=1)
        foundry = _fake_foundry_repo(tmp_path)
        reports = base / "reports" / "evolution"
        (reports / "trace-optimizer").mkdir(parents=True)
        (reports / "attention-router-bridge").mkdir(parents=True)
        (reports / "trace-optimizer" / "candidate_artifacts.json").write_text(json.dumps({
            "schema_version": 1,
            "candidates": [
                {"failure_class": "long_briefing_instead_of_concise_action_queue"},
                {"failure_class": "agent_describes_instead_of_calls_tools"},
            ],
            "external_writes_allowed": False,
        }))
        (reports / "attention-router-bridge" / "action_queue.json").write_text(json.dumps({
            "schema_version": 1,
            "items": [
                {"title": "Convert long briefing trace into one action item"},
                {"title": "Patch tool-underuse behavior from trace evidence"},
            ],
            "external_writes_allowed": False,
        }))
        log_file = tmp_path / "manifest.jsonl"

        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--base", str(base),
                "--foundry-repo", str(foundry),
                "--sessions-dir", str(sessions),
                "--reports-dir", str(reports),
                "--python-bin", sys.executable,
                "--log-file", str(log_file),
                "--steps", "skill_manifest",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        manifest = json.loads((reports / "expansion" / "skill_manifest.json").read_text())
        assert manifest["total_candidate_improvements"] == 2
        assert [item["source"] for item in manifest["pending_skills"]] == ["attention_router", "attention_router"]
        assert {item["title"] for item in manifest["pending_skills"]} == {
            "Convert long briefing trace into one action item",
            "Patch tool-underuse behavior from trace evidence",
        }


class TestAutonomousChainNixContract:
    def test_binding_points_at_runtime_script_and_uses_foundry_python(self):
        text = HARNESS_NIX.read_text()
        assert "autonomousEvolutionChain = pkgs.writeShellApplication" in text
        assert "name = \"hermes-autonomous-evolution-chain\"" in text
        assert "runtimeInputs = [ pythonFoundry pkgs.coreutils ]" in text
        assert "chain_runner=/var/lib/hermes/harness/autonomous/chain_runner.py" in text
        assert "exec ${pythonFoundry}/bin/python3 \"$chain_runner\"" in text

    def test_activation_installs_promoted_runner_to_runtime_path(self):
        text = HARNESS_NIX.read_text()
        assert "/var/lib/hermes/harness/autonomous" in text
        assert "${harnessDir}/autonomous/chain_runner.py" in text
        assert "/var/lib/hermes/harness/autonomous/chain_runner.py" in text
        assert "-m 0755" in text

    def test_service_boundary_and_timer_remain_local_only(self):
        text = HARNESS_NIX.read_text()
        start = text.index("systemd.services.hermes-autonomous-evolution-chain")
        end = text.index("systemd.timers.hermes-autonomous-evolution-chain")
        service = text[start:end]
        assert 'ReadWritePaths = lib.mkForce [' in service
        assert '"/var/lib/hermes/reports/evolution"' in service
        assert '"/var/lib/hermes/.hermes/sessions"' in service
        assert '"/var/lib/hermes/foundry"' in service
        assert '"/var/lib/hermes/foundry-venv"' in service
        readonly_start = service.index("ReadOnlyPaths = lib.mkForce [")
        inaccessible_start = service.index("InaccessiblePaths = lib.mkForce [")
        readonly_block = service[readonly_start:inaccessible_start]
        assert '"/var/lib/hermes/.hermes/sessions"' not in readonly_block
        assert '"-/var/lib/hermes/secrets"' in service
        assert '"-/var/lib/hermes/.hermes/.env"' in service
        assert "EnvironmentFile" not in service
        assert "GITHUB_TOKEN" not in service

        timer = text[end:]
        timer = timer[: timer.find("systemd.", 1) if timer.find("systemd.", 1) != -1 else len(timer)]
        assert "wantedBy = [ \"timers.target\" ]" in timer
        assert "OnBootSec = \"1min\"" in timer
        assert "OnUnitActiveSec = \"3min\"" in timer
