"""Tests: compose critical-alert classification labels into delivery brief."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))


def _load(name: str) -> Any:
    import importlib.util

    path = HARNESS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _setup_base(base: Path, *, critical_events: bool = True) -> None:
    (base / "harness").mkdir(parents=True)
    (base / "events").mkdir(parents=True)
    (base / "reports" / "daily").mkdir(parents=True)
    (base / "harness" / "latest-sensors.json").write_text(
        json.dumps({"overall_status": "critical", "sensors": []})
    )
    (base / "reports" / "daily" / "2026-05-06.md").write_text(
        "# Hermes Node Daily Local Brief — 2026-05-06\nStatus: Critical\n"
    )
    if critical_events:
        (base / "events" / "events.jsonl").write_text(
            json.dumps(
                {
                    "time": "2026-05-06T07:00:00Z",
                    "id": "hermes.state.cron.permission-regression",
                    "status": "critical",
                    "summary": "Cron path regressed",
                    "reason": "first_seen",
                }
            )
            + "\n"
        )


def test_delivery_brief_shows_classified_labels_with_alert_state_dir(
    tmp_path: Path,
) -> None:
    """Daily brief shows [new]/[repeated/known]/[acknowledged] when alert_state_dir is given."""
    _load("harness_common")
    _load("render_daily_report")
    alerts = _load("render_critical_alerts")
    delivery = _load("render_delivery_brief")

    _setup_base(tmp_path)
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    # RED: Without alert_state_dir, no classification labels appear
    out_no_state = delivery.render(str(tmp_path), date="2026-05-06")
    assert "[new]" not in out_no_state
    assert "[repeated/known]" not in out_no_state
    assert "Critical events today:" in out_no_state

    # Seed alert state by running critical alert renderer first (new → known)
    alerts.render(str(tmp_path), date="2026-05-06", state_dir=str(state_dir))

    # RED: With alert_state_dir, classified labels appear
    out_with_state = delivery.render(
        str(tmp_path), date="2026-05-06", alert_state_dir=str(state_dir)
    )
    assert "[repeated/known]" in out_with_state, (
        "Expected [repeated/known] label since state was already seeded"
    )
    assert "Critical events today:" in out_with_state


def test_delivery_brief_does_not_mutate_alert_state(tmp_path: Path) -> None:
    """Delivery brief renderer reads alert state but never writes to it."""
    _load("harness_common")
    _load("render_daily_report")
    alerts = _load("render_critical_alerts")
    delivery = _load("render_delivery_brief")

    _setup_base(tmp_path)
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    # Seed state and capture it
    alerts.render(str(tmp_path), date="2026-05-06", state_dir=str(state_dir))
    state_path = state_dir / "critical-alert-state.json"
    state_before = state_path.read_text()

    # Render delivery brief with alert_state_dir
    delivery.render(str(tmp_path), date="2026-05-06", alert_state_dir=str(state_dir))

    # State must be unchanged
    state_after = state_path.read_text()
    assert state_before == state_after, (
        "delivery brief renderer must not mutate alert state"
    )

    state = json.loads(state_before)
    item = state["critical_alerts"]["hermes.state.cron.permission-regression"]
    assert item["state"] == "known"
    assert "secret" not in state_before.lower()


def test_delivery_brief_shows_acknowledged_label(tmp_path: Path) -> None:
    """Acknowledged alert state produces [acknowledged] in delivery brief."""
    _load("harness_common")
    _load("render_daily_report")
    alerts = _load("render_critical_alerts")
    delivery = _load("render_delivery_brief")

    _setup_base(tmp_path)
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    # Seed state
    alerts.render(str(tmp_path), date="2026-05-06", state_dir=str(state_dir))

    # Mark as acknowledged
    state_path = state_dir / "critical-alert-state.json"
    state = json.loads(state_path.read_text())
    state["critical_alerts"]["hermes.state.cron.permission-regression"][
        "state"
    ] = "acknowledged"
    state["critical_alerts"]["hermes.state.cron.permission-regression"][
        "acknowledged"
    ] = True
    state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")

    out = delivery.render(
        str(tmp_path), date="2026-05-06", alert_state_dir=str(state_dir)
    )
    assert "[acknowledged]" in out, (
        "Acknowledged event should show [acknowledged] label"
    )


def test_delivery_brief_skips_warning_events_from_alert_state(tmp_path: Path) -> None:
    """Warning-events in events.jsonl must not appear as critical alerts in the brief."""
    _load("harness_common")
    _load("render_daily_report")
    delivery = _load("render_delivery_brief")

    _setup_base(tmp_path, critical_events=False)
    state_dir = tmp_path / "delivery" / "state" / "alerts"

    # Write a WARNING event — should never show as critical
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

    # Seed alert state with a different critical event so state exists
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
        + json.dumps(
            {
                "time": "2026-05-06T07:30:00Z",
                "id": "hermes.critical.check",
                "status": "critical",
                "summary": "Something broke",
            }
        )
        + "\n"
    )

    _load("render_critical_alerts").render(
        str(tmp_path), date="2026-05-06", state_dir=str(state_dir)
    )

    # Brief: only critical events, not warnings
    out = delivery.render(
        str(tmp_path), date="2026-05-06", alert_state_dir=str(state_dir)
    )
    assert "release.nixos24_05.unsupported" not in out, (
        "Warning events must not be listed as critical in the delivery brief"
    )
    assert "hermes.critical.check" in out


def test_delivery_brief_alert_labels_are_redacted(tmp_path: Path) -> None:
    """Alert classification output is redacted — no raw secrets leak."""
    _load("harness_common")
    _load("render_daily_report")
    alerts = _load("render_critical_alerts")
    delivery = _load("render_delivery_brief")

    _setup_base(tmp_path, critical_events=False)
    (tmp_path / "events" / "events.jsonl").write_text(
        json.dumps(
            {
                "time": "2026-05-06T07:00:00Z",
                "id": "hermes.state.cron.permission-regression",
                "status": "critical",
                "summary": "Cron path regressed token=secret-value",
                "detail": "Authorization: Bearer bearer...ue",
            }
        )
        + "\n"
    )
    state_dir = tmp_path / "delivery" / "state" / "alerts"
    alerts.render(str(tmp_path), date="2026-05-06", state_dir=str(state_dir))

    out = delivery.render(
        str(tmp_path), date="2026-05-06", alert_state_dir=str(state_dir)
    )
    assert "secret-value" not in out
    assert "bearer...ue" not in out
    assert "token=[REDACTED]" in out
