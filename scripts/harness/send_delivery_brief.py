#!/usr/bin/env python3
"""Phase 2 delivery abstraction for Hermes node briefs.

The implemented transports are dry-run and ntfy. Email is intentionally rejected until
channel discovery and credential placement are explicitly reviewed.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Sequence

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


def send(base: str, date: str | None, transport: str, max_chars: int = DEFAULT_MAX_CHARS) -> int:
    """Render and dispatch a delivery brief through a selected transport."""
    if transport == "dry-run":
        return _dry_run(render(base=base, date=date, max_chars=max_chars))

    if transport == "ntfy":
        return _ntfy(render(base=base, date=date, max_chars=max_chars))

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
    parser.add_argument(
        "--transport",
        choices=sorted(SUPPORTED_TRANSPORTS),
        default="dry-run",
        help="Delivery transport. dry-run sends nothing; ntfy requires an explicit topic/url; email currently fails closed.",
    )
    args = parser.parse_args(argv)
    return send(base=args.base, date=args.date, transport=args.transport, max_chars=args.max_chars)


if __name__ == "__main__":
    raise SystemExit(main())
