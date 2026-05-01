#!/usr/bin/env python3
"""
backup-memories.py — SQLite live backup using sqlite3.backup() API.

This script safely backs up a live WAL-mode SQLite database without
copying the WAL file directly. Uses sqlite3.backup() which was added
in Python 3.7 / SQLite 3.22.

Usage:
    python3 backup-memories.py <source_db> <backup_dir>

Example:
    python3 backup-memories.py /var/lib/hermes/.hermes/memories.db /var/lib/hermes/backups
"""
import sqlite3
import sys
import os
import time
import gzip
from pathlib import Path
from datetime import datetime

def backup_sqlite(src_path: Path, backup_dir: Path) -> Path:
    """
    Safely copy a live WAL-mode SQLite database using sqlite3.backup().
    This is the only safe way to back up a live database — copying the
    .db file directly or the WAL file will produce a corrupted snapshot.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dst_name = f"memories_{ts}.db.gz"
    dst_path = backup_dir / dst_name

    backup_dir.mkdir(parents=True, exist_ok=True)

    # Open source in read-only mode — no writer lock needed
    src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dst_path)
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    return dst_path


def prune_old_backups(backup_dir: Path, keep: int = 30) -> list[Path]:
    """Remove oldest backups beyond `keep` count, by modification time."""
    backups = sorted(backup_dir.glob("memories_*.db.gz"), key=lambda p: p.stat().st_mtime)
    removed = []
    for old in backups[:-keep]:
        old.unlink()
        removed.append(old)
    return removed


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <source_db> <backup_dir>", file=sys.stderr)
        sys.exit(1)

    src_path = Path(sys.argv[1])
    backup_dir = Path(sys.argv[2])

    if not src_path.exists():
        print(f"Source DB not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    try:
        dst = backup_sqlite(src_path, backup_dir)
        print(f"Backed up {src_path} → {dst}")

        removed = prune_old_backups(backup_dir, keep=30)
        if removed:
            print(f"Pruned {len(removed)} old backup(s)")
    except Exception as e:
        print(f"Backup failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
