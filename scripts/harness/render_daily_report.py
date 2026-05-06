#!/usr/bin/env python3
"""Render a deterministic local daily report for the Hermes node."""

from __future__ import annotations

import argparse
from datetime import date as date_type
from pathlib import Path
from typing import Any

from harness_common import iter_jsonl, load_json, write_text_atomic

DISPLAY_STATUS = {"ok": "OK", "warning": "Needs attention", "critical": "Critical"}


def _recent_events(base: Path, date: str) -> list[dict[str, Any]]:
    events = iter_jsonl(base / "events" / "events.jsonl")
    return [event for event in events if str(event.get("time", "")).startswith(date)]


def render(base: str | Path = "/var/lib/hermes", date: str | None = None) -> str:
    base = Path(base)
    if date is None:
        date = date_type.today().isoformat()
    snapshot = load_json(base / "harness" / "latest-sensors.json", {"overall_status": "critical", "sensors": []})
    events = _recent_events(base, date)
    overall = snapshot.get("overall_status", "critical")
    lines: list[str] = []
    lines.append(f"# Hermes Node Daily Local Brief — {date}")
    lines.append("")
    lines.append(f"Status: {DISPLAY_STATUS.get(overall, 'Critical')}")
    lines.append("")
    lines.append("Decisions needed:")
    lines.append("None.")
    lines.append("")
    lines.append("Current health:")
    if snapshot.get("sensors"):
        for sensor in snapshot["sensors"]:
            name = str(sensor.get("sensor", "unknown")).replace("_", " ").title()
            lines.append(f"- {name}: {DISPLAY_STATUS.get(sensor.get('status', 'critical'), 'Critical')}")
    else:
        lines.append("- Snapshot: Critical, latest-sensors.json missing or unreadable")
    lines.append("")
    lines.append("New events:")
    if events:
        for event in events:
            lines.append(f"- {event.get('time')}: {event.get('status')} {event.get('id')} — {event.get('summary')}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("Suppressed/recovered:")
    recovered = [event for event in events if event.get("reason") == "recovered"]
    if recovered:
        for event in recovered:
            lines.append(f"- {event.get('id')} recovered at {event.get('time')}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("Evidence:")
    lines.append("- /var/lib/hermes/harness/latest-sensors.json")
    lines.append("- /var/lib/hermes/events/events.jsonl")
    lines.append("")
    return "\n".join(lines)


def write_report(base: str | Path = "/var/lib/hermes", date: str | None = None) -> Path:
    if date is None:
        date = date_type.today().isoformat()
    base = Path(base)
    path = base / "reports" / "daily" / f"{date}.md"
    write_text_atomic(path, render(base, date))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Hermes node Phase 1 daily local report.")
    parser.add_argument("--base", default="/var/lib/hermes", help="Harness base directory")
    parser.add_argument("--date", default=None, help="Report date YYYY-MM-DD")
    args = parser.parse_args()
    path = write_report(args.base, args.date)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
