#!/usr/bin/env python3
"""Render bounded Phase 2 critical alert candidates from local events.

This script deliberately performs no network send. It is the deterministic
"local events -> urgent alert candidate" renderer that can be manually inspected
before any alert sender, timer, or automatic delivery is added. When a state
directory is supplied it may update local acknowledgement/dedupe metadata only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date as date_type
from pathlib import Path
from typing import Any

from harness_common import atomic_write_json, iter_jsonl, load_json, redact
from render_daily_report import DISPLAY_STATUS

DEFAULT_MAX_CHARS = 1200
STATE_FILE_NAME = "critical-alert-state.json"


def _events_for_date(base: Path, date: str) -> list[dict[str, Any]]:
    return [event for event in iter_jsonl(base / "events" / "events.jsonl") if str(event.get("time", "")).startswith(date)]


def _critical_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("status") == "critical"]


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _condition_hash(event: dict[str, Any]) -> str:
    """Return a stable material-condition hash without persisting raw payloads."""
    material = {
        "id": str(event.get("id") or ""),
        "sensor": str(event.get("sensor") or ""),
        "status": str(event.get("status") or ""),
        "summary": str(redact(event.get("summary") or "")),
        "detail": str(redact(event.get("detail") or "")),
    }
    return _hash_payload(material)


def _event_key(event: dict[str, Any]) -> str:
    event_id = str(event.get("id") or "").strip()
    if event_id:
        return str(redact(event_id))
    return "hash:" + _condition_hash(event)[:16]


def _summarize_by_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated critical emissions by stable event id/hash, preserving latest evidence."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        event_id = _event_key(event)
        if event_id not in by_id:
            by_id[event_id] = {"id": event_id, "count": 0, "latest": event}
            order.append(event_id)
        by_id[event_id]["count"] = int(by_id[event_id]["count"]) + 1
        by_id[event_id]["latest"] = event
    return [by_id[event_id] for event_id in order]


def _state_file(state_dir: str | Path | None) -> Path | None:
    if state_dir is None:
        return None
    return Path(state_dir) / STATE_FILE_NAME


def _read_alert_state(state_file: Path | None) -> dict[str, Any]:
    state = load_json(state_file, {"critical_alerts": {}}) if state_file is not None else {"critical_alerts": {}}
    alerts = state.get("critical_alerts")
    if not isinstance(alerts, dict):
        state["critical_alerts"] = {}
    return state


def _write_alert_state(state_file: Path | None, state: dict[str, Any]) -> None:
    if state_file is None:
        return
    atomic_write_json(state_file, state)


def _safe_time(event: dict[str, Any], fallback: str) -> str:
    value = str(event.get("time") or "").strip()
    return value or fallback


def _new_record(event_id: str, condition_hash: str, seen_at: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "condition_hash": condition_hash,
        "severity": "critical",
        "last_status": "critical",
        "state": "known",
        "acknowledged": False,
        "first_seen": seen_at,
        "last_seen": seen_at,
        "seen_count": 1,
    }


def classify_readonly(
    summarized: list[dict[str, Any]], state_dir: str | Path | None
) -> list[tuple[dict[str, Any], str]]:
    """Return (event, label) pairs without mutating alert state."""
    state_path = _state_file(state_dir)
    if state_path is None:
        return [(item["latest"], "") for item in summarized]
    state = _read_alert_state(state_path)
    records = state.setdefault("critical_alerts", {})
    if not isinstance(records, dict):
        records = {}
    classified: list[tuple[dict[str, Any], str]] = []
    for item in summarized:
        latest = item["latest"]
        event_id = str(item["id"])
        condition_hash = _condition_hash(latest)
        previous = records.get(event_id)
        if not isinstance(previous, dict):
            label = "new"
        elif previous.get("condition_hash") != condition_hash:
            label = "new: changed"
        elif previous.get("state") == "expired":
            label = "new"
        elif previous.get("state") == "acknowledged" or previous.get("acknowledged") is True:
            label = "acknowledged"
        else:
            label = "repeated/known"
        classified.append((latest, label))
    return classified


def _classify_and_update(
    summarized: list[dict[str, Any]], state: dict[str, Any], date: str
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    records = state.setdefault("critical_alerts", {})
    if not isinstance(records, dict):
        records = {}
        state["critical_alerts"] = records

    classified: list[tuple[dict[str, Any], str]] = []
    active_ids: set[str] = set()
    latest_seen_fallback = date

    for item in summarized:
        latest = item["latest"]
        event_id = str(item["id"])
        active_ids.add(event_id)
        condition_hash = _condition_hash(latest)
        seen_at = _safe_time(latest, date)
        latest_seen_fallback = seen_at
        previous = records.get(event_id)

        if not isinstance(previous, dict):
            label = "new"
            records[event_id] = _new_record(event_id, condition_hash, seen_at)
        elif previous.get("condition_hash") != condition_hash:
            label = "new: changed"
            records[event_id] = _new_record(event_id, condition_hash, seen_at)
        else:
            if previous.get("state") == "expired":
                label = "new"
                records[event_id] = _new_record(event_id, condition_hash, seen_at)
            elif previous.get("state") == "acknowledged" or previous.get("acknowledged") is True:
                label = "acknowledged"
                previous["state"] = "acknowledged"
                previous["acknowledged"] = True
                previous["last_seen"] = seen_at
                previous["seen_count"] = int(previous.get("seen_count", 0)) + 1
                previous["last_status"] = "critical"
                previous["severity"] = "critical"
            else:
                label = "repeated/known"
                previous["state"] = "known"
                previous["acknowledged"] = False
                previous["last_seen"] = seen_at
                previous["seen_count"] = int(previous.get("seen_count", 0)) + 1
                previous["last_status"] = "critical"
                previous["severity"] = "critical"
        classified.append((item, label))

    expired: list[dict[str, Any]] = []
    for event_id, record in list(records.items()):
        if event_id in active_ids or not isinstance(record, dict):
            continue
        if record.get("state") == "expired":
            continue
        record["state"] = "expired"
        record["last_status"] = "expired"
        record["expired_at"] = date
        record.setdefault("last_seen", latest_seen_fallback)
        expired.append(record)

    state["last_render_date"] = date
    return classified, expired


def render(
    base: str | Path = "/var/lib/hermes",
    date: str | None = None,
    max_events: int = 5,
    max_chars: int = DEFAULT_MAX_CHARS,
    state_dir: str | Path | None = None,
) -> str:
    """Build a short no-send urgent-alert candidate report from redacted local artifacts."""
    if date is None:
        date = date_type.today().isoformat()
    base = Path(base)
    events_path = base / "events" / "events.jsonl"
    snapshot_path = base / "harness" / "latest-sensors.json"
    snapshot = load_json(snapshot_path, {"overall_status": "critical"})
    status = str(snapshot.get("overall_status", "critical"))
    critical = _critical_events(_events_for_date(base, date))
    summarized = _summarize_by_id(critical)
    state_path = _state_file(state_dir)
    state = _read_alert_state(state_path)
    classified, expired = _classify_and_update(summarized, state, date) if state_path is not None else ([(item, "new") for item in summarized], [])
    _write_alert_state(state_path, state)

    lines: list[str] = []
    lines.append(f"Hermes critical alert candidates — {date}")
    lines.append("No message was sent.")
    lines.append(f"Status: {DISPLAY_STATUS.get(status, 'Critical')}")
    lines.append(f"Source: {events_path}")
    if state_path is not None:
        lines.append(f"State: {state_path}")
    else:
        lines.append("State: disabled; pass --state-dir for local acknowledgement/dedupe metadata")
    lines.append("")

    if classified:
        lines.append("Critical event candidates:")
        for item, label in classified[:max_events]:
            latest = item["latest"]
            suffix = f" ({item['count']} emissions)" if item["count"] != 1 else ""
            reason = latest.get("reason") or "unknown"
            lines.append(
                f"- [{label}] {latest.get('time')}: {item['id']} — {latest.get('summary', '')}"
                f" [reason: {reason}]{suffix}"
            )
        if len(classified) > max_events:
            lines.append(f"- … {len(classified) - max_events} more critical candidate(s) in local events.jsonl")
    else:
        lines.append(f"No critical events for {date}.")

    if expired:
        lines.append("")
        lines.append("Expired critical state:")
        for record in expired[:max_events]:
            lines.append(f"- {record.get('event_id')} — expired")
        if len(expired) > max_events:
            lines.append(f"- … {len(expired) - max_events} more expired critical state record(s)")

    lines.append("")
    lines.append("Inspect locally:")
    lines.append(f"sudo tail -n 80 {events_path}")
    lines.append(f"sudo sed -n '1,160p' {snapshot_path}")
    if state_path is not None:
        lines.append(f"sudo sed -n '1,160p' {state_path}")

    text = str(redact("\n".join(lines))).strip() + "\n"
    if max_chars > 0 and len(text) > max_chars:
        suffix = "\n… truncated; inspect the local source paths above.\n"
        text = text[: max(0, max_chars - len(suffix))].rstrip() + suffix
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Render bounded Hermes Phase 2 critical alert candidates from local events.")
    parser.add_argument("--base", default="/var/lib/hermes", help="Harness base directory")
    parser.add_argument("--date", default=None, help="Event date YYYY-MM-DD")
    parser.add_argument("--max-events", type=int, default=5, help="Maximum distinct critical event ids to include")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="Maximum rendered message length")
    parser.add_argument("--state-dir", default=None, help="Optional directory for local critical-alert acknowledgement/dedupe state")
    parser.add_argument("--dry-run", action="store_true", help="Print candidates; network delivery is intentionally not implemented")
    args = parser.parse_args()
    print(render(args.base, args.date, args.max_events, args.max_chars, args.state_dir), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
