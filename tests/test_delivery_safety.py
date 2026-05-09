from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

import send_delivery_brief  # noqa: E402


def _write_base(base: Path, date: str = "2026-05-08") -> None:
    (base / "reports" / "daily").mkdir(parents=True)
    (base / "reports" / "daily" / f"{date}.md").write_text("# Daily report\nAll clear.\n")
    (base / "harness").mkdir(parents=True)
    (base / "harness" / "latest-sensors.json").write_text(json.dumps({"overall_status": "ok"}))
    (base / "events").mkdir(parents=True)
    (base / "events" / "events.jsonl").write_text("")


def test_once_per_date_second_start_skips_before_ntfy(tmp_path, monkeypatch, capsys):
    base = tmp_path / "base"
    state_dir = tmp_path / "state"
    _write_base(base)
    calls: list[str] = []

    def fake_ntfy(message: str) -> int:
        calls.append(message)
        return 0

    monkeypatch.setattr(send_delivery_brief, "_ntfy", fake_ntfy)

    first = send_delivery_brief.send(
        base=str(base),
        date="2026-05-08",
        transport="ntfy",
        state_dir=str(state_dir),
        once_per_date=True,
        min_interval_seconds=82800,
        now_epoch=1000,
    )
    second = send_delivery_brief.send(
        base=str(base),
        date="2026-05-08",
        transport="ntfy",
        state_dir=str(state_dir),
        once_per_date=True,
        min_interval_seconds=82800,
        now_epoch=1001,
    )

    assert first == 0
    assert second == 0
    assert len(calls) == 1
    out = capsys.readouterr().out
    assert "Delivery skipped:" in out
    state = json.loads((state_dir / "delivery-state.json").read_text())
    assert state["last_success"]["date"] == "2026-05-08"
    assert state["last_success"]["transport"] == "ntfy"
    assert "message_sha256" in state["last_success"]
    assert "topic" not in json.dumps(state).lower()
    assert "url" not in json.dumps(state).lower()


def test_min_interval_blocks_changed_payload_before_ntfy(tmp_path, monkeypatch):
    base = tmp_path / "base"
    state_dir = tmp_path / "state"
    _write_base(base)
    calls: list[str] = []

    def fake_ntfy(message: str) -> int:
        calls.append(message)
        return 0

    monkeypatch.setattr(send_delivery_brief, "_ntfy", fake_ntfy)

    assert send_delivery_brief.send(
        base=str(base),
        date="2026-05-08",
        transport="ntfy",
        state_dir=str(state_dir),
        once_per_date=True,
        min_interval_seconds=82800,
        now_epoch=2000,
    ) == 0

    # Mutate the local report so once-per-date would not match by payload hash.
    # The min-interval gate still blocks before any network transport call.
    (base / "reports" / "daily" / "2026-05-08.md").write_text("# Daily report\nChanged.\n")

    assert send_delivery_brief.send(
        base=str(base),
        date="2026-05-08",
        transport="ntfy",
        state_dir=str(state_dir),
        once_per_date=True,
        min_interval_seconds=82800,
        now_epoch=2001,
    ) == 0
    assert len(calls) == 1


def test_failed_real_transport_does_not_write_success_state(tmp_path, monkeypatch):
    base = tmp_path / "base"
    state_dir = tmp_path / "state"
    _write_base(base)

    monkeypatch.setattr(send_delivery_brief, "_ntfy", lambda message: 1)

    assert send_delivery_brief.send(
        base=str(base),
        date="2026-05-08",
        transport="ntfy",
        state_dir=str(state_dir),
        once_per_date=True,
        min_interval_seconds=82800,
        now_epoch=3000,
    ) == 1
    assert not (state_dir / "delivery-state.json").exists()
