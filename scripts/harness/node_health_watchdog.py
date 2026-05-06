#!/usr/bin/env python3
"""Phase 1 systemd-owned Hermes node health watchdog."""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from harness_common import atomic_write_json, append_jsonl, load_json, parse_utc, redact, status_max, utc_now

RATE_LIMIT = timedelta(hours=2)


def _default_sensors(base: Path) -> list[Callable[[], dict[str, Any]]]:
    import hermes_health_sensor
    import network_health_sensor
    import release_policy_sensor
    import system_health_sensor

    return [
        system_health_sensor.collect,
        network_health_sensor.collect,
        lambda: hermes_health_sensor.collect(base),
        release_policy_sensor.collect,
    ]


def _paths(base: Path) -> dict[str, Path]:
    return {
        "harness": base / "harness",
        "events": base / "events",
        "reports": base / "reports",
        "latest": base / "harness" / "latest-sensors.json",
        "state": base / "harness" / "state.json",
        "jsonl": base / "events" / "events.jsonl",
    }


def _prepare_paths(paths: dict[str, Path]) -> None:
    for key in ("harness", "events", "reports"):
        paths[key].mkdir(parents=True, exist_ok=True)


def _collect_sensors(sensor_fns: list[Callable[[], dict[str, Any]]]) -> list[dict[str, Any]]:
    results = []
    for fn in sensor_fns:
        try:
            result = fn()
            if not isinstance(result, dict):
                raise TypeError(f"sensor returned {type(result).__name__}")
            result.setdefault("sensor", getattr(fn, "__name__", "unknown"))
            result.setdefault("status", "critical")
            result.setdefault("checks", [])
            results.append(redact(result))
        except Exception as exc:  # observed sensor failure, not watchdog plumbing failure
            name = getattr(fn, "__name__", "sensor")
            results.append(
                {
                    "sensor": name,
                    "status": "critical",
                    "checks": [
                        {
                            "id": f"sensor.{name}.crash",
                            "status": "critical",
                            "summary": f"Sensor {name} crashed",
                            "detail": str(redact(str(exc))),
                        }
                    ],
                }
            )
    return results


def _event_reason(previous: dict[str, Any] | None, status: str, now: str) -> str | None:
    if previous is None:
        return "first_seen"
    previous_status = previous.get("last_status")
    if status == "ok" and previous_status != "ok":
        return "recovered"
    if status != previous_status:
        return "severity_changed"
    next_emit_after = previous.get("next_emit_after")
    if status != "ok" and next_emit_after and parse_utc(now) >= parse_utc(next_emit_after):
        return "rate_limit_expired"
    return None


def _next_emit_after(now: str, status: str) -> str | None:
    if status == "ok":
        return None
    return (parse_utc(now) + RATE_LIMIT).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _update_state_and_events(paths: dict[str, Path], snapshot: dict[str, Any], state: dict[str, Any], now: str) -> dict[str, Any]:
    dedupe = state.setdefault("dedupe", {})
    emitted = 0

    for sensor in snapshot["sensors"]:
        for item in sensor.get("checks", []):
            event_id = item.get("id")
            status = item.get("status", "critical")
            if not event_id:
                continue
            previous = dedupe.get(event_id)
            if status == "ok" and previous is None:
                continue
            reason = _event_reason(previous, status, now)
            record = {
                "first_seen": (previous or {}).get("first_seen", now),
                "last_seen": now,
                "seen_count": int((previous or {}).get("seen_count", 0)) + 1,
                "last_status": status,
                "last_emitted": (previous or {}).get("last_emitted"),
                "next_emit_after": (previous or {}).get("next_emit_after"),
            }
            if reason:
                event = {
                    "time": now,
                    "id": event_id,
                    "sensor": sensor.get("sensor", "unknown"),
                    "status": status,
                    "summary": item.get("summary", ""),
                    "detail": item.get("detail"),
                    "reason": reason,
                }
                append_jsonl(paths["jsonl"], event)
                emitted += 1
                record["last_emitted"] = now
                record["next_emit_after"] = _next_emit_after(now, status)
            dedupe[event_id] = record

    state["last_run"] = now
    state["last_overall_status"] = snapshot["overall_status"]
    state["last_emitted_events"] = emitted
    return state


def run_once(base: str | Path = "/var/lib/hermes", sensor_fns: list[Callable[[], dict[str, Any]]] | None = None, now: str | None = None) -> int:
    base = Path(base)
    now = now or utc_now()
    paths = _paths(base)
    try:
        _prepare_paths(paths)
        if sensor_fns is None:
            sensor_fns = _default_sensors(base)
        sensors = _collect_sensors(sensor_fns)
        snapshot = {
            "generated_at": now,
            "overall_status": status_max(sensor.get("status", "critical") for sensor in sensors),
            "sensors": sensors,
        }
        atomic_write_json(paths["latest"], snapshot)
        state = load_json(paths["state"], {"dedupe": {}})
        state = _update_state_and_events(paths, snapshot, state, now)
        atomic_write_json(paths["state"], state)
        return 0
    except Exception as exc:  # watchdog plumbing failure
        sys.stderr.write(f"Hermes harness plumbing failure: {exc}\n")
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Hermes node Phase 1 health watchdog once.")
    parser.add_argument("--base", default="/var/lib/hermes", help="Harness base directory")
    args = parser.parse_args()
    return run_once(args.base)


if __name__ == "__main__":
    raise SystemExit(main())
