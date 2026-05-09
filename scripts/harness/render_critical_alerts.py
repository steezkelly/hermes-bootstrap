#!/usr/bin/env python3
"""Render bounded Phase 2 critical alert candidates from local events.

This script deliberately performs no network send. It is the deterministic
"local events -> urgent alert candidate" renderer that can be manually inspected
before any alert sender, acknowledgement state, or timer is added.
"""

from __future__ import annotations

import argparse
from datetime import date as date_type
from pathlib import Path
from typing import Any

from harness_common import iter_jsonl, load_json, redact
from render_daily_report import DISPLAY_STATUS

DEFAULT_MAX_CHARS = 1200


def _events_for_date(base: Path, date: str) -> list[dict[str, Any]]:
    return [event for event in iter_jsonl(base / "events" / "events.jsonl") if str(event.get("time", "")).startswith(date)]


def _critical_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("status") == "critical"]


def _summarize_by_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated critical emissions by event id, preserving latest evidence."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        event_id = str(event.get("id") or "unknown")
        if event_id not in by_id:
            by_id[event_id] = {"id": event_id, "count": 0, "latest": event}
            order.append(event_id)
        by_id[event_id]["count"] = int(by_id[event_id]["count"]) + 1
        by_id[event_id]["latest"] = event
    return [by_id[event_id] for event_id in order]


def render(
    base: str | Path = "/var/lib/hermes",
    date: str | None = None,
    max_events: int = 5,
    max_chars: int = DEFAULT_MAX_CHARS,
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

    lines: list[str] = []
    lines.append(f"Hermes critical alert candidates — {date}")
    lines.append("No message was sent.")
    lines.append(f"Status: {DISPLAY_STATUS.get(status, 'Critical')}")
    lines.append(f"Source: {events_path}")
    lines.append("")

    if summarized:
        lines.append("Critical event candidates:")
        for item in summarized[:max_events]:
            latest = item["latest"]
            suffix = f" ({item['count']} emissions)" if item["count"] != 1 else ""
            reason = latest.get("reason") or "unknown"
            lines.append(
                f"- {latest.get('time')}: {item['id']} — {latest.get('summary', '')}"
                f" [reason: {reason}]{suffix}"
            )
        if len(summarized) > max_events:
            lines.append(f"- … {len(summarized) - max_events} more critical candidate(s) in local events.jsonl")
    else:
        lines.append(f"No critical events for {date}.")

    lines.append("")
    lines.append("Inspect locally:")
    lines.append(f"sudo tail -n 80 {events_path}")
    lines.append(f"sudo sed -n '1,160p' {snapshot_path}")

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
    parser.add_argument("--dry-run", action="store_true", help="Print candidates; network delivery is intentionally not implemented")
    args = parser.parse_args()
    print(render(args.base, args.date, args.max_events, args.max_chars), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
