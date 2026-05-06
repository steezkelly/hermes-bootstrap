#!/usr/bin/env python3
"""Phase 2 delivery abstraction for Hermes node briefs.

The implemented transports are dry-run and ntfy. Email is intentionally rejected until
channel discovery and credential placement are explicitly reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from render_delivery_brief import DEFAULT_MAX_CHARS, render


SUPPORTED_TRANSPORTS = {"dry-run", "email", "ntfy"}


def _dry_run(message: str) -> int:
    print("Transport: dry-run")
    print("No message was sent.")
    print("")
    print(message, end="")
    return 0


def _ntfy_url_from_env() -> str | None:
    explicit_url = os.environ.get("HERMES_DELIVERY_NTFY_URL", "").strip()
    if explicit_url:
        return explicit_url

    topic = os.environ.get("HERMES_DELIVERY_NTFY_TOPIC", "").strip()
    if not topic:
        return None
    return "https://ntfy.sh/" + urllib.parse.quote(topic, safe="")


def _ntfy(message: str) -> int:
    url = _ntfy_url_from_env()
    if not url:
        print(
            "ntfy transport requires HERMES_DELIVERY_NTFY_URL or HERMES_DELIVERY_NTFY_TOPIC. No message was sent.",
            file=sys.stderr,
        )
        return 2

    request = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Title": "Hermes node brief",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(f"Transport: ntfy")
            print(f"Delivery status: HTTP {response.status}")
            if message_id := response.headers.get("X-Message-Id"):
                print(f"Message id: {message_id}")
        return 0
    except urllib.error.URLError as exc:
        print(f"ntfy transport failed: {exc}. No retry attempted.", file=sys.stderr)
        return 1


def _state_path(state_dir: str | None) -> Path | None:
    if not state_dir:
        return None
    return Path(state_dir) / "delivery-state.json"


def _read_state(state_file: Path | None) -> dict[str, Any]:
    if state_file is None or not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state_file: Path | None, state: dict[str, Any]) -> None:
    if state_file is None:
        return
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    tmp.replace(state_file)


def _message_sha256(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _skip_reason(
    state: dict[str, Any],
    *,
    date: str | None,
    transport: str,
    message_sha256: str,
    once_per_date: bool,
    min_interval_seconds: int,
    now_epoch: int,
) -> str | None:
    last = state.get("last_success")
    if not isinstance(last, dict):
        return None

    if min_interval_seconds > 0:
        last_sent = last.get("sent_at_epoch")
        if isinstance(last_sent, int):
            age = now_epoch - last_sent
            if 0 <= age < min_interval_seconds:
                return f"Delivery skipped: last successful send was {age} seconds ago"

    if once_per_date and last.get("date") == date and last.get("transport") == transport:
        if last.get("message_sha256") == message_sha256:
            return f"Delivery skipped: already sent {transport} brief for {date}"

    return None


def send(
    base: str,
    date: str | None,
    transport: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    state_dir: str | None = None,
    once_per_date: bool = False,
    min_interval_seconds: int = 0,
    now_epoch: int | None = None,
) -> int:
    """Render and dispatch a delivery brief through a selected transport."""
    if transport == "dry-run":
        return _dry_run(render(base=base, date=date, max_chars=max_chars))

    message = render(base=base, date=date, max_chars=max_chars)
    state_file = _state_path(state_dir)
    state = _read_state(state_file)
    now = int(time.time() if now_epoch is None else now_epoch)
    message_sha256 = _message_sha256(message)
    if reason := _skip_reason(
        state,
        date=date,
        transport=transport,
        message_sha256=message_sha256,
        once_per_date=once_per_date,
        min_interval_seconds=min_interval_seconds,
        now_epoch=now,
    ):
        print(reason)
        return 0

    if transport == "ntfy":
        exit_code = _ntfy(message)
        if exit_code == 0:
            state["last_success"] = {
                "date": date,
                "transport": transport,
                "message_sha256": message_sha256,
                "sent_at_epoch": now,
            }
            _write_state(state_file, state)
        return exit_code

    if transport == "email":
        print("email transport is not implemented. No message was sent.", file=sys.stderr)
        return 2

    print(f"unsupported transport: {transport}. No message was sent.", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send or dry-run a Hermes Phase 2 delivery brief.")
    parser.add_argument("--base", default="/var/lib/hermes", help="Harness base directory")
    parser.add_argument("--date", default=None, help="Report date YYYY-MM-DD")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="Maximum rendered message length")
    parser.add_argument("--state-dir", default=None, help="Optional directory for delivery dedupe/rate-limit state")
    parser.add_argument("--once-per-date", action="store_true", help="Skip duplicate successful sends for the same date/payload")
    parser.add_argument(
        "--min-interval-seconds",
        type=int,
        default=0,
        help="Skip sends if a previous success happened within this many seconds",
    )
    parser.add_argument("--now-epoch", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--transport",
        choices=sorted(SUPPORTED_TRANSPORTS),
        default="dry-run",
        help="Delivery transport. dry-run sends nothing; ntfy requires an explicit topic/url; email currently fails closed.",
    )
    args = parser.parse_args(argv)
    return send(
        base=args.base,
        date=args.date,
        transport=args.transport,
        max_chars=args.max_chars,
        state_dir=args.state_dir,
        once_per_date=args.once_per_date,
        min_interval_seconds=args.min_interval_seconds,
        now_epoch=args.now_epoch,
    )


if __name__ == "__main__":
    raise SystemExit(main())
