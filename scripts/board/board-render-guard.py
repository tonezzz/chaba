#!/usr/bin/env python3
"""board-render-guard — ExecStart wrapper for chaba-board-render.service.

Runs render-board.py + render-board2.py --if-changed and tracks
consecutive failures in STATE (default /tmp/chaba-board-render-guard.json
— tmp so it never dirties the checkout; a reboot just recounts). Two
nonzero runs in a row upserts an ops-board-render-fail card, the
cms-auto pattern (card guard-card-yaml-syntax-validation-at-wri bonus):
stable id, review column, note = failing renderer + stderr tail so the
file that broke the parse is named on the board. While the same failure
persists the open card is left alone (no 60s comms spam); a changed
failure appends comms; on recovery the card auto-closes like
cms-auto-health's loop. Until then the timer kept retrying silently —
2026-10-11 the board served 2.5h-stale cards.json off a poisoned card.

Card writes hold the board flock (/tmp/board-api.lock — board-api.py
docstring: every direct card-YAML edit must hold it) and round-trip
through yaml.safe_load before landing, same contract as
board-api.save(). Alerting never raises — it must not crash the render
loop (kanban-commit alert_card precedent).

Exit: 0 when both renders succeed; 1 otherwise, so the unit still goes
failed in the journal — the card is the *visible* copy of that failure.
Smoke test: python3 scripts/board/board-render-guard.py --selftest
"""
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
RENDERS = [REPO / "scripts/render-board.py",
           REPO / "scripts/render-board2.py"]
CARD_DIR = REPO / "docs/ssot/kanban/cards"
CARD_ID = "ops-board-render-fail"
LOCK = Path("/tmp/board-api.lock")
STATE = Path(os.environ.get("RENDER_GUARD_STATE",
                            "/tmp/chaba-board-render-guard.json"))
THRESHOLD = 2


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        STATE.write_text(json.dumps(st))
    except OSError:
        pass


def _write_card(card: dict) -> None:
    """Verified atomic card write — same contract as board-api.save()."""
    text = yaml.safe_dump(card, allow_unicode=True, sort_keys=False,
                          width=110)
    if not isinstance(yaml.safe_load(text), dict):
        raise ValueError("dump did not re-parse as a card mapping")
    p = CARD_DIR / f"{CARD_ID}.yml"
    tmp = p.with_suffix(".yml.tmp")
    tmp.write_text(text)
    tmp.replace(p)


def upsert_card(note: str, healthy: bool) -> None:
    """Alert-card upsert under the board flock; never raises."""
    try:
        with LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            p = CARD_DIR / f"{CARD_ID}.yml"
            card = {}
            if p.exists():
                try:
                    card = yaml.safe_load(p.read_text()) or {}
                except Exception:
                    card = {}
            if not isinstance(card, dict):
                card = {}
            if healthy:
                # cms-auto-style auto-recover: an open alert card whose
                # renders now pass closes itself — the incident ends on
                # the board where it started.
                if card.get("column") and card.get("column") != "done":
                    card["column"] = "done"
                    card["note"] = (f"Auto-recovered {now()}: board "
                                    "render healthy again.")
                    card.setdefault("comms", []).append(
                        {"at": now(), "from": "chaba",
                         "text": "render healthy — auto-closing"})
                    card["updated"] = now()
                    _write_card(card)
                return
            note = note[:500]
            if card.get("column") not in (None, "done") \
                    and card.get("note") == note:
                return  # same failure still open — don't churn the file
            card.setdefault("comms", []).append(
                {"at": now(), "from": "chaba",
                 "text": f"render failing: {note}"[:500]})
            card.update(
                id=CARD_ID,
                title="chaba-board-render failing — board stale",
                column="review",
                generated="board-render-guard",
                priority="high",
                review_kind="triage",
                note=note,
                help=("journalctl --user -u chaba-board-render -n 50. "
                      "The note names the failing renderer + its last "
                      "stderr line — a poisoned card YAML is the usual "
                      "cause: fix or remove the file it names and the "
                      "next 60s tick re-renders + auto-closes this card."),
                updated=now())
            _write_card(card)
    except Exception as e:
        print(f"board-render-guard: alert card write failed: {e}",
              file=sys.stderr)


def main() -> int:
    fails = []
    for r in RENDERS:
        p = subprocess.run(
            [sys.executable, str(r), "--if-changed"],
            cwd=REPO, capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            tail = (p.stderr or p.stdout or "").strip().splitlines()
            fails.append(f"{r.name} rc={p.returncode}"
                         + (f" — {tail[-1][:200]}" if tail else ""))
    st = _load_state()
    if not fails:
        st["fails"] = 0
        _save_state(st)
        upsert_card("", healthy=True)
        return 0
    st["fails"] = int(st.get("fails") or 0) + 1
    _save_state(st)
    for f in fails:
        print(f"board-render-guard: {f}", file=sys.stderr)
    if st["fails"] >= THRESHOLD:
        upsert_card("; ".join(fails), healthy=False)
    return 1


def _selftest() -> None:
    """State-machine + card-upsert smoke test — temp dirs, no renders."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    cdir = tmp / "cards"
    cdir.mkdir()
    globals()["CARD_DIR"] = cdir
    globals()["LOCK"] = tmp / "board-api.lock"
    globals()["STATE"] = tmp / "state.json"

    p = cdir / f"{CARD_ID}.yml"

    upsert_card("render-board.py rc=1 — yaml.scanner.ScannerError: x.yml",
                healthy=False)
    card = yaml.safe_load(p.read_text())
    assert card["id"] == CARD_ID and card["column"] == "review"
    assert card["generated"] == "board-render-guard"
    assert "yaml.scanner" in card["note"] and card["priority"] == "high"
    assert len(card["comms"]) == 1
    first_updated = card["updated"]

    upsert_card("render-board.py rc=1 — yaml.scanner.ScannerError: x.yml",
                healthy=False)
    card2 = yaml.safe_load(p.read_text())
    assert len(card2["comms"]) == 1         # same failure: no churn
    assert card2["updated"] == first_updated

    upsert_card("render-board2.py rc=1 — different error", healthy=False)
    card3 = yaml.safe_load(p.read_text())
    assert len(card3["comms"]) == 2         # changed failure: new comms
    assert card3["note"].startswith("render-board2.py")

    upsert_card("", healthy=True)           # recovery -> auto-close
    card4 = yaml.safe_load(p.read_text())
    assert card4["column"] == "done"
    assert "Auto-recovered" in card4["note"]

    upsert_card("render-board.py rc=1 — broke again", healthy=False)
    card5 = yaml.safe_load(p.read_text())
    assert card5["column"] == "review"      # re-hit after close re-opens

    # state survives reload + counts
    _save_state({"fails": 2})
    assert _load_state()["fails"] == 2
    STATE.unlink()
    assert _load_state() == {}

    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    sys.exit(main())
