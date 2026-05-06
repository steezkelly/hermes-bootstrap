#!/usr/bin/env python3
"""Phase 2 delivery abstraction for Hermes node briefs.

The only implemented transport is dry-run. Email is intentionally rejected until
channel discovery and credential placement are explicitly reviewed.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from render_delivery_brief import DEFAULT_MAX_CHARS, render


SUPPORTED_TRANSPORTS = {"dry-run", "email"}


def _dry_run(message: str) -> int:
    print("Transport: dry-run")
    print("No message was sent.")
    print("")
    print(message, end="")
    return 0


def send(base: str, date: str | None, transport: str, max_chars: int = DEFAULT_MAX_CHARS) -> int:
    """Render and dispatch a delivery brief through a selected transport."""
    if transport == "dry-run":
        return _dry_run(render(base=base, date=date, max_chars=max_chars))

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
        help="Delivery transport. Only dry-run sends nothing; email currently fails closed.",
    )
    args = parser.parse_args(argv)
    return send(base=args.base, date=args.date, transport=args.transport, max_chars=args.max_chars)


if __name__ == "__main__":
    raise SystemExit(main())
