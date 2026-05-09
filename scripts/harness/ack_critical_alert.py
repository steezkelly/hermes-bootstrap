#!/usr/bin/env python3
"""Acknowledge a local Phase 2 critical alert state record.

This command mutates only the local critical-alert acknowledgement state file. It
has no network transport and does not read delivery credentials, journals, or raw
payloads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from harness_common import atomic_write_json, load_json, redact, utc_now

STATE_FILE_NAME = "critical-alert-state.json"


def _state_file(state_dir: str | Path) -> Path:
    return Path(state_dir) / STATE_FILE_NAME


def acknowledge(
    state_dir: str | Path,
    event_id: str,
    acknowledged_at: str | None = None,
    acknowledged_by: str = "local-operator",
) -> int:
    """Mark an existing critical alert state record as acknowledged."""
    event_id = str(redact(event_id)).strip()
    if not event_id:
        print("critical alert event id is required", file=sys.stderr)
        return 2

    state_path = _state_file(state_dir)
    state = load_json(state_path, {"critical_alerts": {}})
    records = state.get("critical_alerts")
    if not isinstance(records, dict):
        print(f"critical alert state is malformed: {state_path}", file=sys.stderr)
        return 2

    record = records.get(event_id)
    if not isinstance(record, dict):
        print(f"critical alert event id not found: {event_id}", file=sys.stderr)
        return 2

    record["event_id"] = event_id
    record["state"] = "acknowledged"
    record["acknowledged"] = True
    record["acknowledged_at"] = acknowledged_at or utc_now()
    record["acknowledged_by"] = str(redact(acknowledged_by or "local-operator"))
    state["last_acknowledged_event_id"] = event_id
    state["last_acknowledged_at"] = record["acknowledged_at"]
    atomic_write_json(state_path, state)
    print(f"Acknowledged critical alert {event_id}")
    print("No message was sent.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acknowledge an existing local Hermes critical alert state record.")
    parser.add_argument("--state-dir", default="/var/lib/hermes/delivery/state/alerts", help="Critical alert state directory")
    parser.add_argument("--event-id", required=True, help="Existing critical alert event id to acknowledge")
    parser.add_argument("--acknowledged-at", default=None, help="Acknowledgement timestamp; defaults to current UTC time")
    parser.add_argument("--acknowledged-by", default="local-operator", help="Safe local operator label")
    args = parser.parse_args(argv)
    return acknowledge(
        state_dir=args.state_dir,
        event_id=args.event_id,
        acknowledged_at=args.acknowledged_at,
        acknowledged_by=args.acknowledged_by,
    )


if __name__ == "__main__":
    raise SystemExit(main())
