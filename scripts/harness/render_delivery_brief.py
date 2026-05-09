#!/usr/bin/env python3
"""Render a bounded Phase 2 delivery brief from local Phase 1 artifacts.

This script deliberately performs no network send. It is the deterministic
"local artifact -> push message" renderer that a future least-privilege delivery
service can call after Phase 1 live validation passes.
"""

from __future__ import annotations

import argparse
from datetime import date as date_type
from pathlib import Path
from typing import Any

from harness_common import iter_jsonl, load_json, redact
from render_critical_alerts import _critical_events, _events_for_date, _summarize_by_id, classify_readonly
from render_daily_report import DISPLAY_STATUS

DEFAULT_MAX_CHARS = 1800


def _report_path(base: Path, date: str) -> Path:
    return base / "reports" / "daily" / f"{date}.md"


def _status_from_snapshot(base: Path) -> str:
    snapshot = load_json(base / "harness" / "latest-sensors.json", {"overall_status": "critical"})
    return str(snapshot.get("overall_status", "critical"))


def _events_for_date(base: Path, date: str) -> list[dict[str, Any]]:
    return [event for event in iter_jsonl(base / "events" / "events.jsonl") if str(event.get("time", "")).startswith(date)]


def _critical_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("status") == "critical"]


def _first_report_lines(report_text: str, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for line in report_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lines.append(stripped)
        if len(lines) >= limit:
            break
    return lines


def render(base: str | Path = "/var/lib/hermes", date: str | None = None, max_chars: int = DEFAULT_MAX_CHARS, alert_state_dir: str | Path | None = None) -> str:
    """Build a short operator-facing message from local redacted artifacts only.

    When alert_state_dir is provided, critical events are labeled with
    classification tags ([new], [repeated/known], [acknowledged]) from the
    read-only alert state. The state is never mutated by this function.
    """
    if date is None:
        date = date_type.today().isoformat()
    base = Path(base)
    report = _report_path(base, date)
    events = _events_for_date(base, date)
    critical = _critical_events(events)
    status = _status_from_snapshot(base)

    lines: list[str] = []
    lines.append(f"Hermes node brief — {date}")
    lines.append(f"Status: {DISPLAY_STATUS.get(status, 'Critical')}")
    lines.append(f"Source: {report}")
    lines.append("")

    if report.exists():
        report_text = redact(report.read_text(encoding="utf-8", errors="replace"))
        lines.append("Local report excerpt:")
        for line in _first_report_lines(str(report_text)):
            lines.append(f"{line}")
    else:
        lines.append("Local report excerpt:")
        lines.append("Daily local report is missing; inspect the renderer service locally.")

    lines.append("")
    lines.append("Critical events today:")
    if critical:
        summarized = _summarize_by_id(critical)
        classified = classify_readonly(summarized, alert_state_dir)
        for latest, label in classified[:5]:
            label_prefix = f"[{label}] " if label else ""
            lines.append(f"- {label_prefix}{latest.get('time')}: {latest.get('id')} — {latest.get('summary', '')}")
        if len(classified) > 5:
            lines.append(f"- … {len(classified) - 5} more critical event(s) in local events.jsonl")
    else:
        lines.append("None.")

    lines.append("")
    lines.append("Inspect locally:")
    lines.append("sudo sed -n '1,160p' " + str(report))
    lines.append("sudo tail -n 50 /var/lib/hermes/events/events.jsonl")

    text = str(redact("\n".join(lines))).strip() + "\n"
    if max_chars > 0 and len(text) > max_chars:
        suffix = "\n… truncated; inspect the local source paths above.\n"
        text = text[: max(0, max_chars - len(suffix))].rstrip() + suffix
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a bounded Phase 2 delivery brief from local artifacts.")
    parser.add_argument("--base", default="/var/lib/hermes", help="Harness base directory")
    parser.add_argument("--date", default=None, help="Report date YYYY-MM-DD")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="Maximum rendered message length")
    parser.add_argument("--dry-run", action="store_true", help="Print the message; network delivery is intentionally not implemented")
    args = parser.parse_args()

    # Dry-run is currently the only mode. Keep the flag for operator clarity and
    # future tests, but do not add send behavior until a live delivery channel is
    # explicitly chosen and reviewed.
    print(render(args.base, args.date, args.max_chars), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
