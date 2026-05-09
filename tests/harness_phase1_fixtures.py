#!/usr/bin/env python3
"""Phase 1 harness behavior tests.

These tests intentionally exercise the scripts as importable Python modules so
sensor behavior can stay deterministic without requiring a live NixOS system.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "scripts" / "harness"


def load_module(name: str) -> Any:
    path = HARNESS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_redaction_masks_token_like_values() -> None:
    common = load_module("harness_common")

    text = (
        "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789 "
        "token=secret-value "
        "Authorization: Bearer bearer-secret-value"
    )
    redacted = common.redact(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
    assert "secret-value" not in redacted
    assert "bearer-secret-value" not in redacted
    assert "OPENAI_API_KEY=[REDACTED]" in redacted
    assert "token=[REDACTED]" in redacted
    assert "Authorization: Bearer [REDACTED]" in redacted


def test_atomic_writes_create_group_readable_files(tmp_path: Path) -> None:
    common = load_module("harness_common")

    json_path = tmp_path / "state.json"
    text_path = tmp_path / "report.md"
    common.atomic_write_json(json_path, {"ok": True})
    common.write_text_atomic(text_path, "hello")

    assert json_path.stat().st_mode & 0o660 == 0o660
    assert text_path.stat().st_mode & 0o660 == 0o660


def test_watchdog_writes_latest_snapshot_and_no_event_for_ok_run(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")

    results = [
        {"sensor": "system", "status": "ok", "checks": []},
        {"sensor": "network", "status": "ok", "checks": []},
        {"sensor": "hermes", "status": "ok", "checks": []},
        {"sensor": "release_policy", "status": "ok", "checks": []},
    ]
    exit_code = watchdog.run_once(tmp_path, sensor_fns=[lambda r=r: r for r in results], now="2026-05-06T06:00:00Z")

    assert exit_code == 0
    latest = json.loads((tmp_path / "harness" / "latest-sensors.json").read_text())
    assert latest["overall_status"] == "ok"
    assert [s["sensor"] for s in latest["sensors"]] == ["system", "network", "hermes", "release_policy"]
    assert read_jsonl(tmp_path / "events" / "events.jsonl") == []


def test_watchdog_dedupes_repeated_warning_until_rate_window(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")

    warning = {
        "sensor": "release_policy",
        "status": "warning",
        "checks": [{"id": "release.nixos24_05.unsupported", "status": "warning", "summary": "NixOS 24.05 unsupported"}],
    }

    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: warning], now="2026-05-06T06:00:00Z") == 0
    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: warning], now="2026-05-06T06:30:00Z") == 0
    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: warning], now="2026-05-06T08:01:00Z") == 0

    events = read_jsonl(tmp_path / "events" / "events.jsonl")
    assert [e["id"] for e in events] == ["release.nixos24_05.unsupported", "release.nixos24_05.unsupported"]
    assert events[0]["reason"] == "first_seen"
    assert events[1]["reason"] == "rate_limit_expired"


def test_watchdog_emits_recovery_after_warning(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")

    warning = {
        "sensor": "hermes",
        "status": "warning",
        "checks": [{"id": "hermes.state.cron.permission-regression", "status": "warning", "summary": "Cron path not group-readable"}],
    }
    ok = {"sensor": "hermes", "status": "ok", "checks": [{"id": "hermes.state.cron.permission-regression", "status": "ok", "summary": "Cron path readable"}]}

    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: warning], now="2026-05-06T06:00:00Z") == 0
    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: ok], now="2026-05-06T06:30:00Z") == 0

    events = read_jsonl(tmp_path / "events" / "events.jsonl")
    assert [e["status"] for e in events] == ["warning", "ok"]
    assert events[1]["reason"] == "recovered"


def test_sensor_crash_is_critical_event_but_watchdog_exits_zero(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")

    def broken_sensor() -> dict[str, Any]:
        raise RuntimeError("boom sk-testsecret000000000000000000000000")

    assert watchdog.run_once(tmp_path, sensor_fns=[broken_sensor], now="2026-05-06T06:00:00Z") == 0
    events = read_jsonl(tmp_path / "events" / "events.jsonl")
    assert len(events) == 1
    assert events[0]["status"] == "critical"
    assert "sk-testsecret" not in json.dumps(events[0])


def test_unwritable_snapshot_path_fails_plumbing(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")

    (tmp_path / "harness").write_text("not-a-dir")
    ok = {"sensor": "system", "status": "ok", "checks": []}

    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: ok], now="2026-05-06T06:00:00Z") == 2


def test_unwritable_event_path_fails_plumbing(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")

    # A file where the events directory must be makes observability plumbing broken
    # even when running as root in CI.
    (tmp_path / "events").write_text("not-a-dir")
    ok = {"sensor": "system", "status": "ok", "checks": []}

    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: ok], now="2026-05-06T06:00:00Z") == 2


def test_daily_report_is_deterministic_and_short(tmp_path: Path) -> None:
    watchdog = load_module("node_health_watchdog")
    report = load_module("render_daily_report")

    warning = {
        "sensor": "release_policy",
        "status": "warning",
        "checks": [{"id": "release.nixos24_05.unsupported", "status": "warning", "summary": "NixOS 24.05 unsupported"}],
    }
    assert watchdog.run_once(tmp_path, sensor_fns=[lambda: warning], now="2026-05-06T06:00:00Z") == 0

    out = report.render(tmp_path, date="2026-05-06")

    assert out.startswith("# Hermes Node Daily Local Brief — 2026-05-06")
    assert "Status: Needs attention" in out
    assert "Decisions needed:\nNone." in out
    assert "/var/lib/hermes/harness/latest-sensors.json" in out
    assert "journalctl" not in out


def test_daily_report_ignores_corrupt_jsonl_lines(tmp_path: Path) -> None:
    report = load_module("render_daily_report")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "ok", "sensors": []}))
    (tmp_path / "events" / "events.jsonl").write_text('{"time":"2026-05-06T01:00:00Z","id":"ok","status":"warning","summary":"bounded"}\n{bad json\n')

    out = report.render(tmp_path, date="2026-05-06")

    assert "ok — bounded" in out
    assert "Status: OK" in out


def test_gateway_config_localhost_counts_ok_when_no_listener(tmp_path: Path) -> None:
    hermes_sensor = load_module("hermes_health_sensor")

    config_dir = tmp_path / ".hermes"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("gateway:\n  host: 127.0.0.1\n  port: 8080\n")

    result = hermes_sensor._gateway_locality_check(tmp_path, port="65000")

    assert result["status"] == "ok"
    assert "localhost" in result["summary"]


def test_hermes_status_success_has_no_detail(monkeypatch, tmp_path: Path) -> None:
    hermes_sensor = load_module("hermes_health_sensor")

    def fake_run_command(argv, timeout=5, env=None):
        if argv[:2] == ["systemctl", "is-active"]:
            return {"ok": True, "stdout": "active", "stderr": ""}
        if argv[0] == "hermes":
            return {"ok": True, "stdout": "MiniMax ✓ sk-c...4PzA", "stderr": ""}
        if argv[0] == "ss":
            return {"ok": True, "stdout": "", "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}

    monkeypatch.setattr(hermes_sensor, "run_command", fake_run_command)
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / "config.yaml").write_text("gateway:\n  host: 127.0.0.1\n")

    result = hermes_sensor.collect(tmp_path)
    cli_check = next(c for c in result["checks"] if c["id"] == "hermes.cli.status")

    assert cli_check["status"] == "ok"
    assert "detail" not in cli_check
    assert "sk-c" not in json.dumps(result)


def test_phase2_delivery_brief_uses_local_artifacts_only(tmp_path: Path) -> None:
    load_module("harness_common")
    report = load_module("render_daily_report")
    delivery = load_module("render_delivery_brief")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "reports" / "daily").mkdir(parents=True)
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "critical", "sensors": []}))
    (tmp_path / "events" / "events.jsonl").write_text(
        json.dumps(
            {
                "time": "2026-05-06T07:00:00Z",
                "id": "hermes.state.cron.permission-regression",
                "status": "critical",
                "summary": "Cron path regressed token=secret-value",
            }
        )
        + "\n"
    )
    report.write_report(tmp_path, date="2026-05-06")

    out = delivery.render(tmp_path, date="2026-05-06", max_chars=1200)

    assert out.startswith("Hermes node brief — 2026-05-06")
    assert "Status: Critical" in out
    assert str(tmp_path / "reports" / "daily" / "2026-05-06.md") in out
    assert "hermes.state.cron.permission-regression" in out
    assert "token=[REDACTED]" in out
    assert "secret-value" not in out
    assert "/var/lib/hermes/secrets/hermes.env" not in out
    assert "journalctl" not in out


def test_phase2_delivery_brief_is_bounded(tmp_path: Path) -> None:
    load_module("harness_common")
    delivery = load_module("render_delivery_brief")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "reports" / "daily").mkdir(parents=True)
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "warning", "sensors": []}))
    (tmp_path / "reports" / "daily" / "2026-05-06.md").write_text("# Report\n" + ("long line\n" * 200))

    out = delivery.render(tmp_path, date="2026-05-06", max_chars=240)

    assert len(out) <= 240
    assert "truncated" in out
    assert "inspect the local source paths" in out


def test_phase2_critical_alert_candidates_are_local_redacted_and_bounded(tmp_path: Path) -> None:
    load_module("harness_common")
    alerts = load_module("render_critical_alerts")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "reports" / "daily").mkdir(parents=True)
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "critical", "sensors": []}))
    (tmp_path / "events" / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-05-06T07:00:00Z",
                        "id": "hermes.state.cron.permission-regression",
                        "status": "critical",
                        "summary": "Cron path regressed token=secret-value",
                        "reason": "first_seen",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-05-06T07:30:00Z",
                        "id": "release.nixos24_05.unsupported",
                        "status": "warning",
                        "summary": "NixOS 24.05 unsupported",
                        "reason": "first_seen",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-05-06T08:00:00Z",
                        "id": "hermes.state.cron.permission-regression",
                        "status": "critical",
                        "summary": "Cron path still regressed token=secret-value",
                        "reason": "rate_limit_expired",
                    }
                ),
            ]
        )
        + "\n"
    )

    out = alerts.render(tmp_path, date="2026-05-06", max_chars=700)

    assert out.startswith("Hermes critical alert candidates — 2026-05-06")
    assert "No message was sent." in out
    assert "hermes.state.cron.permission-regression" in out
    assert "release.nixos24_05.unsupported" not in out
    assert "token=[REDACTED]" in out
    assert "secret-value" not in out
    assert "/var/lib/hermes/secrets/hermes.env" not in out
    assert "journalctl" not in out
    assert len(out) <= 700


def test_phase2_critical_alert_candidates_report_quiet_when_no_critical_events(tmp_path: Path) -> None:
    load_module("harness_common")
    alerts = load_module("render_critical_alerts")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "ok", "sensors": []}))
    (tmp_path / "events" / "events.jsonl").write_text(
        json.dumps(
            {
                "time": "2026-05-06T07:00:00Z",
                "id": "release.nixos24_05.unsupported",
                "status": "warning",
                "summary": "NixOS 24.05 unsupported",
            }
        )
        + "\n"
    )

    out = alerts.render(tmp_path, date="2026-05-06")

    assert "No critical events for 2026-05-06." in out
    assert "No message was sent." in out


def test_phase2_critical_alert_state_marks_new_then_repeated_without_secrets(tmp_path: Path) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    alerts = load_module("render_critical_alerts")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "critical", "sensors": []}))
    (tmp_path / "events" / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-05-06T07:00:00Z",
                        "id": "hermes.state.cron.permission-regression",
                        "status": "critical",
                        "summary": "Cron path regressed token=secret-value",
                        "detail": "raw journal line should not persist Authorization: Bearer bearer-secret-value",
                        "reason": "first_seen",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-05-06T07:30:00Z",
                        "id": "release.nixos24_05.unsupported",
                        "status": "warning",
                        "summary": "NixOS 24.05 unsupported",
                        "reason": "first_seen",
                    }
                ),
            ]
        )
        + "\n"
    )
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    first = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    second = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    state_text = (state_dir / "critical-alert-state.json").read_text()
    state = json.loads(state_text)

    assert "[new]" in first
    assert "[repeated/known]" in second
    assert "release.nixos24_05.unsupported" not in first
    assert "release.nixos24_05.unsupported" not in state_text
    assert "secret-value" not in state_text
    assert "Authorization" not in state_text
    assert "journal" not in state_text
    item = state["critical_alerts"]["hermes.state.cron.permission-regression"]
    assert item["event_id"] == "hermes.state.cron.permission-regression"
    assert item["severity"] == "critical"
    assert item["state"] == "known"
    assert item["condition_hash"]
    assert item["first_seen"] == "2026-05-06T07:00:00Z"
    assert item["last_seen"] == "2026-05-06T07:00:00Z"
    assert item["seen_count"] == 2
    assert "summary" not in item
    assert "detail" not in item


def test_phase2_critical_alert_state_marks_material_change_as_new_attention(tmp_path: Path) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    alerts = load_module("render_critical_alerts")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "critical", "sensors": []}))
    events_path = tmp_path / "events" / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "time": "2026-05-06T07:00:00Z",
                "id": "sensor.hermes.crash",
                "status": "critical",
                "summary": "Sensor crashed with timeout",
            }
        )
        + "\n"
    )
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    first = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    before = json.loads((state_dir / "critical-alert-state.json").read_text())
    events_path.write_text(
        json.dumps(
            {
                "time": "2026-05-06T08:00:00Z",
                "id": "sensor.hermes.crash",
                "status": "critical",
                "summary": "Sensor crashed with disk full",
            }
        )
        + "\n"
    )
    second = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    after = json.loads((state_dir / "critical-alert-state.json").read_text())

    assert "[new]" in first
    assert "[new: changed]" in second
    item = after["critical_alerts"]["sensor.hermes.crash"]
    assert item["condition_hash"] != before["critical_alerts"]["sensor.hermes.crash"]["condition_hash"]
    assert item["state"] == "known"
    assert item["last_seen"] == "2026-05-06T08:00:00Z"


def test_phase2_critical_alert_state_reports_acknowledged_and_expired(tmp_path: Path) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    alerts = load_module("render_critical_alerts")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "critical", "sensors": []}))
    events_path = tmp_path / "events" / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "time": "2026-05-06T07:00:00Z",
                "id": "hermes.gateway.down",
                "status": "critical",
                "summary": "Gateway service down",
            }
        )
        + "\n"
    )
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    state_path = state_dir / "critical-alert-state.json"
    state = json.loads(state_path.read_text())
    state["critical_alerts"]["hermes.gateway.down"]["state"] = "acknowledged"
    state["critical_alerts"]["hermes.gateway.down"]["acknowledged"] = True
    state["critical_alerts"]["hermes.gateway.down"]["acknowledged_at"] = "2026-05-06T07:05:00Z"
    state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")

    acknowledged = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    events_path.write_text(
        json.dumps(
            {
                "time": "2026-05-07T07:00:00Z",
                "id": "hermes.gateway.down",
                "status": "warning",
                "summary": "Gateway service degraded but not critical",
            }
        )
        + "\n"
    )
    expired = alerts.render(tmp_path, date="2026-05-07", state_dir=state_dir)
    final_state = json.loads(state_path.read_text())

    assert "[acknowledged]" in acknowledged
    assert "No critical events for 2026-05-07." in expired
    assert "Expired critical state:" in expired
    assert "hermes.gateway.down — expired" in expired
    assert final_state["critical_alerts"]["hermes.gateway.down"]["state"] == "expired"
    assert final_state["critical_alerts"]["hermes.gateway.down"]["expired_at"] == "2026-05-07"


def test_ack_critical_alert_marks_existing_state_without_payloads(tmp_path: Path, capsys: Any) -> None:
    load_module("harness_common")
    ack = load_module("ack_critical_alert")
    state_dir = tmp_path / "delivery" / "state" / "alerts"
    state_dir.mkdir(parents=True)
    state_path = state_dir / "critical-alert-state.json"
    state_path.write_text(json.dumps({
        "critical_alerts": {
            "hermes.gateway.down": {
                "event_id": "hermes.gateway.down",
                "condition_hash": "abc123",
                "severity": "critical",
                "last_status": "critical",
                "state": "known",
                "acknowledged": False,
                "first_seen": "2026-05-06T07:00:00Z",
                "last_seen": "2026-05-06T07:00:00Z",
                "seen_count": 1,
            }
        }
    }))

    exit_code = ack.main([
        "--state-dir", str(state_dir),
        "--event-id", "hermes.gateway.down",
        "--acknowledged-at", "2026-05-06T07:05:00Z",
        "--acknowledged-by", "local-operator",
    ])
    captured = capsys.readouterr()
    updated_text = state_path.read_text()
    updated = json.loads(updated_text)
    item = updated["critical_alerts"]["hermes.gateway.down"]

    assert exit_code == 0
    assert "Acknowledged critical alert hermes.gateway.down" in captured.out
    assert item["state"] == "acknowledged"
    assert item["acknowledged"] is True
    assert item["acknowledged_at"] == "2026-05-06T07:05:00Z"
    assert item["acknowledged_by"] == "local-operator"
    assert item["condition_hash"] == "abc123"
    assert "summary" not in item
    assert "detail" not in item
    assert "payload" not in updated_text
    assert "secret" not in updated_text.lower()


def test_ack_critical_alert_rejects_missing_event_without_mutation(tmp_path: Path, capsys: Any) -> None:
    load_module("harness_common")
    ack = load_module("ack_critical_alert")
    state_dir = tmp_path / "delivery" / "state" / "alerts"
    state_dir.mkdir(parents=True)
    state_path = state_dir / "critical-alert-state.json"
    before = {"critical_alerts": {}}
    state_path.write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")

    exit_code = ack.main([
        "--state-dir", str(state_dir),
        "--event-id", "missing.event",
        "--acknowledged-at", "2026-05-06T07:05:00Z",
    ])
    captured = capsys.readouterr()
    after = json.loads(state_path.read_text())

    assert exit_code == 2
    assert "not found" in captured.err
    assert after == before


def test_ack_critical_alert_makes_renderer_report_acknowledged(tmp_path: Path) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    alerts = load_module("render_critical_alerts")
    ack = load_module("ack_critical_alert")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "critical", "sensors": []}))
    (tmp_path / "events" / "events.jsonl").write_text(
        json.dumps({
            "time": "2026-05-06T07:00:00Z",
            "id": "hermes.gateway.down",
            "status": "critical",
            "summary": "Gateway service down",
        })
        + "\n"
    )
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    first = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)
    ack_exit = ack.main([
        "--state-dir", str(state_dir),
        "--event-id", "hermes.gateway.down",
        "--acknowledged-at", "2026-05-06T07:05:00Z",
    ])
    second = alerts.render(tmp_path, date="2026-05-06", state_dir=state_dir)

    assert "[new]" in first
    assert ack_exit == 0
    assert "[acknowledged]" in second


def _write_minimal_phase2_inputs(base: Path, date: str = "2026-05-06") -> None:
    (base / "harness").mkdir()
    (base / "events").mkdir()
    (base / "reports" / "daily").mkdir(parents=True)
    (base / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "ok", "sensors": []}))
    (base / "reports" / "daily" / f"{date}.md").write_text(f"# Hermes Node Daily Local Brief — {date}\nStatus: OK\n")


class _FakeNtfyResponse:
    status = 200
    headers = {"X-Message-Id": "test-message-id"}

    def __enter__(self) -> "_FakeNtfyResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def test_send_delivery_brief_records_state_and_skips_duplicate_ntfy(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    load_module("render_delivery_brief")
    sender = load_module("send_delivery_brief")
    _write_minimal_phase2_inputs(tmp_path)
    monkeypatch.setenv("HERMES_DELIVERY_NTFY_TOPIC", "test-topic")
    calls: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> _FakeNtfyResponse:
        calls.append((request, timeout))
        return _FakeNtfyResponse()

    monkeypatch.setattr(sender.urllib.request, "urlopen", fake_urlopen)
    state_dir = tmp_path / "delivery-state"

    first = sender.main([
        "--base", str(tmp_path),
        "--date", "2026-05-06",
        "--transport", "ntfy",
        "--state-dir", str(state_dir),
        "--once-per-date",
    ])
    second = sender.main([
        "--base", str(tmp_path),
        "--date", "2026-05-06",
        "--transport", "ntfy",
        "--state-dir", str(state_dir),
        "--once-per-date",
    ])
    captured = capsys.readouterr()

    assert first == 0
    assert second == 0
    assert len(calls) == 1
    assert "Delivery skipped: already sent ntfy brief for 2026-05-06" in captured.out
    state = json.loads((state_dir / "delivery-state.json").read_text())
    assert state["last_success"]["date"] == "2026-05-06"
    assert state["last_success"]["transport"] == "ntfy"
    assert state["last_success"]["message_sha256"]


def test_send_delivery_brief_records_resolved_default_date(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    load_module("render_delivery_brief")
    sender = load_module("send_delivery_brief")
    _write_minimal_phase2_inputs(tmp_path, date="2026-05-07")
    monkeypatch.setenv("HERMES_DELIVERY_NTFY_TOPIC", "test-topic")
    calls: list[Any] = []

    class FakeDate:
        @staticmethod
        def today() -> Any:
            class Today:
                def isoformat(self) -> str:
                    return "2026-05-07"

            return Today()

    def fake_urlopen(request: Any, timeout: int) -> _FakeNtfyResponse:
        calls.append((request, timeout))
        return _FakeNtfyResponse()

    monkeypatch.setattr(sender, "date_type", FakeDate)
    monkeypatch.setattr(sender.urllib.request, "urlopen", fake_urlopen)
    state_dir = tmp_path / "delivery-state"

    first = sender.main([
        "--base", str(tmp_path),
        "--transport", "ntfy",
        "--state-dir", str(state_dir),
        "--once-per-date",
    ])
    second = sender.main([
        "--base", str(tmp_path),
        "--transport", "ntfy",
        "--state-dir", str(state_dir),
        "--once-per-date",
    ])
    captured = capsys.readouterr()
    state = json.loads((state_dir / "delivery-state.json").read_text())

    assert first == 0
    assert second == 0
    assert len(calls) == 1
    assert state["last_success"]["date"] == "2026-05-07"
    assert "Delivery skipped: already sent ntfy brief for 2026-05-07" in captured.out


def test_send_delivery_brief_rate_limits_recent_success(tmp_path: Path, capsys: Any) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    load_module("render_delivery_brief")
    sender = load_module("send_delivery_brief")
    _write_minimal_phase2_inputs(tmp_path)
    state_dir = tmp_path / "delivery-state"
    state_dir.mkdir()
    (state_dir / "delivery-state.json").write_text(json.dumps({
        "last_success": {
            "date": "2026-05-06",
            "transport": "ntfy",
            "message_sha256": "previous",
            "sent_at_epoch": 1000,
        }
    }))

    exit_code = sender.main([
        "--base", str(tmp_path),
        "--date", "2026-05-06",
        "--transport", "ntfy",
        "--state-dir", str(state_dir),
        "--min-interval-seconds", "3600",
        "--now-epoch", "1200",
    ])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Delivery skipped: last successful send was 200 seconds ago" in captured.out


def test_send_delivery_brief_dry_run_uses_renderer_output(tmp_path: Path, capsys: Any) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    load_module("render_delivery_brief")
    sender = load_module("send_delivery_brief")

    (tmp_path / "harness").mkdir()
    (tmp_path / "events").mkdir()
    (tmp_path / "reports" / "daily").mkdir(parents=True)
    (tmp_path / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "ok", "sensors": []}))
    (tmp_path / "reports" / "daily" / "2026-05-06.md").write_text("# Hermes Node Daily Local Brief — 2026-05-06\nStatus: OK\n")

    exit_code = sender.main(["--base", str(tmp_path), "--date", "2026-05-06", "--transport", "dry-run"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Hermes node brief — 2026-05-06" in out
    assert "Transport: dry-run" in out
    assert "No message was sent." in out


def test_send_delivery_brief_rejects_email_until_transport_is_implemented(tmp_path: Path, capsys: Any) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    load_module("render_delivery_brief")
    sender = load_module("send_delivery_brief")

    exit_code = sender.main(["--base", str(tmp_path), "--date", "2026-05-06", "--transport", "email"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "email transport is not implemented" in captured.err
    assert "No message was sent." in captured.err


def test_send_delivery_brief_rejects_ntfy_without_topic(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    load_module("harness_common")
    load_module("render_daily_report")
    load_module("render_delivery_brief")
    sender = load_module("send_delivery_brief")
    monkeypatch.delenv("HERMES_DELIVERY_NTFY_URL", raising=False)
    monkeypatch.delenv("HERMES_DELIVERY_NTFY_TOPIC", raising=False)

    exit_code = sender.main(["--base", str(tmp_path), "--date", "2026-05-06", "--transport", "ntfy"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "ntfy transport requires" in captured.err
    assert "No message was sent." in captured.err


def test_static_phase2_delivery_contract() -> None:
    delivery_script = (REPO_ROOT / "scripts" / "harness" / "render_delivery_brief.py").read_text()
    critical_alert_script = (REPO_ROOT / "scripts" / "harness" / "render_critical_alerts.py").read_text()
    ack_alert_script = (REPO_ROOT / "scripts" / "harness" / "ack_critical_alert.py").read_text()
    sender_script = (REPO_ROOT / "scripts" / "harness" / "send_delivery_brief.py").read_text()
    phase2_doc = (REPO_ROOT / "docs" / "phase2-boundaries.md").read_text()

    assert "no network send" in delivery_script
    assert "events.jsonl" in delivery_script
    assert "reports" in delivery_script
    assert "/var/lib/hermes/secrets/hermes.env" not in delivery_script
    assert "/var/lib/hermes/secrets/hermes.env" not in sender_script
    assert "journalctl" not in delivery_script
    assert "journalctl" not in sender_script
    assert "transport == \"dry-run\"" in sender_script
    assert 'transport == "ntfy"' in sender_script
    assert "--state-dir" in sender_script
    assert "--once-per-date" in sender_script
    assert "--min-interval-seconds" in sender_script
    assert "delivery-state.json" in sender_script
    assert "message_sha256" in sender_script
    assert "HERMES_DELIVERY_NTFY_TOPIC" in sender_script
    assert "email transport is not implemented" in sender_script
    assert "No message was sent." in critical_alert_script
    assert "events.jsonl" in critical_alert_script
    assert "--state-dir" in critical_alert_script
    assert "critical-alert-state.json" in critical_alert_script
    assert "condition_hash" in critical_alert_script
    assert "HERMES_DELIVERY_NTFY_TOPIC" not in critical_alert_script
    assert "urllib" not in critical_alert_script
    assert "classify_readonly" in critical_alert_script
    assert "from render_critical_alerts import" in delivery_script
    assert "alert_state_dir" in delivery_script
    assert "Acknowledge" in ack_alert_script
    assert "No message was sent." in ack_alert_script
    assert "urllib" not in ack_alert_script
    assert "HERMES_DELIVERY_NTFY_TOPIC" not in ack_alert_script
    assert "smtplib" not in ack_alert_script
    assert "/var/lib/hermes/secrets/hermes.env" not in ack_alert_script
    assert "journalctl" not in ack_alert_script
    assert "/var/lib/hermes/secrets/hermes.env" not in critical_alert_script
    assert "journalctl" not in critical_alert_script
    assert "local report exists -> delivery renderer builds bounded message" in phase2_doc
    assert "critical alert candidate renderer" in phase2_doc


def test_static_nixos_harness_contract() -> None:
    harness_nix = (REPO_ROOT / "system" / "nixos" / "harness.nix").read_text()
    flake_nix = (REPO_ROOT / "system" / "nixos" / "flake.nix").read_text()
    deployment_nix = (REPO_ROOT / "system" / "nixos" / "deployment-options.nix").read_text()

    assert "users.users.hermes-harness" in harness_nix
    assert "isSystemUser = true;" in harness_nix
    assert "group = \"hermes\";" in harness_nix
    assert "User = \"hermes-harness\";" in harness_nix
    assert "Group = \"hermes\";" in harness_nix
    assert "ProtectSystem = \"strict\";" in harness_nix
    assert "ProtectHome = true;" in harness_nix
    assert "InaccessiblePaths = [ \"-/var/lib/hermes/secrets\" ];" in harness_nix
    assert "ReadWritePaths = [" in harness_nix
    assert "Persistent = true;" in harness_nix
    assert "OnUnitActiveSec = \"30min\";" in harness_nix
    assert "RemainAfterExit" not in harness_nix
    assert "Requires = [ \"hermes-agent.service\"" not in harness_nix
    assert "hermes-phase2-delivery-brief-dry-run" in harness_nix
    assert "Render Hermes Phase 2 delivery brief dry-run" in harness_nix
    assert "render_delivery_brief.py --base" in harness_nix
    assert "hermes-phase2-critical-alert-dry-run" in harness_nix
    assert "Render Hermes Phase 2 critical alert candidates dry-run" in harness_nix
    assert "render_critical_alerts.py --base" in harness_nix
    assert "--state-dir ${harnessBase}/delivery/state/alerts" in harness_nix
    assert "install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/delivery/state/alerts" in harness_nix
    assert 'ReadWritePaths = lib.mkForce [ "/var/lib/hermes/delivery/state/alerts" ];' in harness_nix
    assert "hermes-ack-critical-alert" in harness_nix
    assert "ack_critical_alert.py --state-dir" in harness_nix
    assert "environment.systemPackages = [ ackCriticalAlert ]" in harness_nix
    assert "systemd.timers.hermes-phase2-critical-alert" not in harness_nix
    assert "users.users.hermes-delivery" in harness_nix
    assert "system.activationScripts.hermesHarnessDirectories" in harness_nix
    assert 'deps = [ "users" ];' in harness_nix
    assert "install -d -o hermes-delivery -g hermes -m 2770 /var/lib/hermes/delivery/state" in harness_nix
    assert "systemd.tmpfiles.rules" not in harness_nix
    assert "Hermes Phase 2 delivery sender" in harness_nix
    assert "hermes-phase2-delivery-brief-send" in harness_nix
    assert "send_delivery_brief.py --base" in harness_nix
    assert "--transport ntfy" in harness_nix
    assert "--state-dir ${harnessBase}/delivery/state" in harness_nix
    assert "--once-per-date" in harness_nix
    assert "--min-interval-seconds 82800" in harness_nix
    assert "EnvironmentFile = \"-/var/lib/hermes/delivery/ntfy.env\";" in harness_nix
    assert "install -d -o hermes-delivery -g hermes -m 2750 /var/lib/hermes/delivery" in harness_nix
    assert "install -d -o hermes-delivery -g hermes -m 2770 /var/lib/hermes/delivery/state" in harness_nix
    assert "ReadWritePaths = lib.mkForce [ \"/var/lib/hermes/delivery/state\" ];" in harness_nix
    assert "User = \"hermes-delivery\";" in harness_nix
    assert "InaccessiblePaths = [ \"-/var/lib/hermes/secrets\" ];" in harness_nix
    assert 'phase2DeliveryTimerEnabled = false;' in deployment_nix
    assert 'phase2DeliveryTimerCalendar = "*-*-* 06:10:00";' in deployment_nix
    assert "deployment = import ./deployment-options.nix;" in harness_nix
    phase2_timer_start = harness_nix.index(
        "systemd.timers.hermes-phase2-delivery-brief-send = lib.mkIf deployment.phase2DeliveryTimerEnabled"
    )
    phase2_timer_block = harness_nix[phase2_timer_start:]
    assert "wantedBy = [ \"timers.target\" ];" in phase2_timer_block
    assert "OnCalendar = deployment.phase2DeliveryTimerCalendar;" in phase2_timer_block
    assert "Unit = \"hermes-phase2-delivery-brief-send.service\";" in phase2_timer_block
    assert "./harness.nix" in flake_nix
