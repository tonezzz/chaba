#!/usr/bin/env python3
"""capture-apply.py -- gated, key-scoped writer for ONE capture proposal.

The harvester stays read-only. This script is the separate, explicit apply
door approved under OPS-0024 (2026-11-23). It writes at most ONE proposal
per invocation, only to an allowlisted sink, and only after every gate below
passes. There is deliberately no bulk mode: the proposal ledger already holds
thousands of already-filed candidates, so "apply everything" is not a thing.

First slice supports exactly one sink/action pair:

    kanban / create   -> board-api POST /card (via board-cli, --ssh idc03)

Sinks such as ssot, kb, lesson and oc-note are NOT supported yet. Refuse,
never improvise a write path for them.

Gates (all must pass, in order):
  1. --key is an exact dedupe_key present in the ledger.
  2. proposal is kanban/create (the allowlisted pair) and not already applied.
  3. --apply requires --confirm with the SAME key retyped. No inference.
  4. the source focus-inbox artifact still exists and is draft/pending.
  5. no card with that id or a matching title already exists on the board.
  6. the card is created via board-api with bounded retries (3 attempts).
  7. the created card is read back (GET) and the title verified.
  8. an audit record is appended to the ledger's `applied:` block AND
     mirrored as a comm on the created card — the ledger is regenerable
     runtime state, the board comm is the durable audit (OPS-1368).

Dry-run is the DEFAULT: no flags prints the exact card payload, the gate
results and the rollback command, and writes nothing.

Rollback for the supported sink:
  python3 scripts/board/board-cli.py --ssh idc03 comment <id> "<reason>" --from devin
  python3 scripts/board/board-cli.py --ssh idc03 action <id> close --from devin

Usage:
  capture-apply.py --key kanban:065d94f97e90            # dry-run, writes nothing
  capture-apply.py --key kanban:065d94f97e90 --apply --confirm kanban:065d94f97e90
  capture-apply.py --self-test
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
OUT = Path(os.environ.get("CHABA_CAPTURE_OUT")
           or Path.home() / ".local/share/chaba/capture")
LEDGER = OUT / "capture-ledger.yml"
BOARD_CLI = REPO / "scripts/board/board-cli.py"
BOARD_SSH = os.environ.get("CAPTURE_APPLY_SSH", "idc03")
BOARD_URL = "https://idc03.taila0626a.ts.net/apps/board2/?card="
ALLOWED = {("kanban", "create")}
TERMINAL_STATUS = {"processed", "archived", "done", "superseded"}
LIVE_STATUS = {"draft", "pending", "open", "backlog"}
MAX_ATTEMPTS = 3
CONFIRM_PHRASE = None  # intentionally not used; the key itself is the phrase


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def load_ledger(path: Path = LEDGER) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def find_entry(doc: dict[str, Any], key: str) -> dict[str, Any] | None:
    for e in doc.get("entries") or []:
        if isinstance(e, dict) and e.get("dedupe_key") == key:
            return e
    return None


def already_applied(doc: dict[str, Any], key: str) -> bool:
    return any(isinstance(a, dict) and a.get("dedupe_key") == key
               for a in doc.get("applied") or [])


def source_artifact(entry: dict[str, Any]) -> tuple[bool, str, str]:
    """Return (ok, reason, text) for the proposal's still-live source."""
    if entry.get("source") != "focus-inbox":
        return False, f"unsupported source {entry.get('source')!r} (first slice: focus-inbox)", ""
    stem = str(entry.get("source_id") or "")
    path = REPO / "docs/ssot/focus-inbox" / (stem + ".yml")
    if not path.exists():
        return False, f"source no longer exists: {path.relative_to(REPO)}", ""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return False, f"source unreadable: {exc}", ""
    focus = doc.get("focus") if isinstance(doc.get("focus"), dict) else {}
    status = str(focus.get("status") or doc.get("status") or "draft").lower()
    if status in TERMINAL_STATUS:
        return False, f"source status is terminal ({status}); already filed elsewhere", ""
    text = " ".join(filter(None, [doc.get("title"),
                                  focus.get("text") or doc.get("subtitle")]))
    if not text.strip():
        return False, "source has no title/text", ""
    return True, f"source live ({status})", text.strip()


def title_from_text(text: str) -> str:
    """First clause of the trigger text, not a truncated wall of prose."""
    first = (text or "").strip().splitlines()[0].strip()
    cuts = [i for i in (first.find(":"), first.find(" — "), first.find(". "))
            if i > 20]
    title = (first[:min(cuts)] if cuts else first).strip(" -:;—")
    if len(title) > 80:
        title = title[:77].rsplit(" ", 1)[0] + "..."
    return title or "Untitled capture"


def build_card(entry: dict[str, Any], text: str) -> dict[str, str]:
    card_id = str(entry.get("source_id") or "").strip()
    spec = "\n".join([
        "Provenance (capture-apply, OPS-0024):",
        f"- source: {entry.get('source')} / {entry.get('source_id')}",
        f"- dedupe_key: {entry.get('dedupe_key')}",
        f"- rule: {entry.get('rule') or 'n/a'} | confidence: {entry.get('confidence')}",
        f"- proposal run: {entry.get('run_id')}",
        "",
        "Trigger from focus-inbox:",
        text[:4000],
    ])
    return {
        "id": card_id,
        "title": title_from_text(text),
        "column": "backlog",
        "priority": "medium",
        "brief": text[:300].replace("\n", " "),
        "spec": spec,
        "tag": "capture-harvester",
    }


def _board(*args: str) -> tuple[int, str]:
    """Run board-cli against the writer host; never a direct HTTP call."""
    cmd = ["python3", str(BOARD_CLI), "--ssh", BOARD_SSH, *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, f"board-cli unavailable: {exc}"
    return p.returncode, (p.stdout.strip() or p.stderr.strip())


def existing_cards() -> list[dict[str, Any]] | None:
    """None = board-api unreadable; the duplicate gate must then FAIL, not pass."""
    rc, out = _board("get", "--limit", "2000")
    if rc:
        return None
    try:
        doc = json.loads(out)
        return [c for c in doc.get("cards") or [] if isinstance(c, dict)]
    except Exception:
        return None


def duplicate_reasons(card: dict[str, str], cards: list[dict[str, Any]]) -> list[str]:
    reasons = []
    want_id, want_title = card["id"], _norm(card["title"])
    for c in cards:
        if str(c.get("id") or "") == want_id:
            reasons.append(f"card id already exists: {want_id}")
        if _norm(str(c.get("title") or "")) == want_title:
            reasons.append(f"title already exists: {str(c.get('title') or '')[:80]}")
    return reasons


def check_gates(key: str, do_apply: bool, confirm: str | None,
                doc: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None, list[str], str]:
    """Return (failures, entry, card, source_reason). No writes."""
    failures: list[str] = []
    entry = find_entry(doc, key)
    if entry is None:
        return ["dedupe_key not found in ledger"], None, None, ""
    if (entry.get("proposed_sink"), entry.get("action")) not in ALLOWED:
        failures.append(
            f"sink/action not allowed: {entry.get('proposed_sink')}/{entry.get('action')} "
            f"(first slice supports {sorted(ALLOWED)})")
    if already_applied(doc, key):
        failures.append("already applied; ledger audit record present (idempotence gate)")
    if do_apply and confirm != key:
        failures.append("--confirm must retype the exact --key (no inferred approval)")
    ok, reason, text = source_artifact(entry)
    if not ok:
        failures.append(reason)
    card = build_card(entry, text) if ok else None
    if card:
        cards = existing_cards()
        if cards is None:
            failures.append("board-api unreadable: duplicate gate could not be verified")
        else:
            failures.extend(duplicate_reasons(card, cards)[:3])
    return failures, entry, card, reason


def render_dry_run(key: str, entry: dict[str, Any], card: dict[str, str],
                   failures: list[str], reason: str) -> str:
    lines = [
        f"# capture-apply dry-run — {key}", "",
        f"- proposal: {entry.get('proposed_sink')}/{entry.get('action')} "
        f"(rule {entry.get('rule')}, confidence {entry.get('confidence')})",
        f"- source: {reason}",
        f"- gates: {'PASS' if not failures else 'BLOCK'}",
    ]
    for f in failures:
        lines.append(f"  - BLOCK: {f}")
    lines += ["", "## Card payload (would be POSTed via board-api)", "",
              "```json", json.dumps(card, indent=2, ensure_ascii=False), "```", "",
              "## Apply command (only when gates PASS)", "",
              f"  python3 scripts/chaba/capture-apply.py --key {key} "
              f"--apply --confirm {key}", "",
              "## Rollback (after apply)", "",
              f"  python3 scripts/board/board-cli.py --ssh {BOARD_SSH} comment {card['id']} "
              "'capture-apply rollback: duplicate or low-value proposal' --from devin",
              f"  python3 scripts/board/board-cli.py --ssh {BOARD_SSH} action {card['id']} close "
              "--from devin", ""]
    return "\n".join(lines)


def append_applied(path: Path, entry: dict[str, Any], card: dict[str, str],
                   artifact: str) -> None:
    doc = load_ledger(path)
    applied = list(doc.get("applied") or [])
    applied.append({
        "dedupe_key": entry["dedupe_key"],
        "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_id": entry.get("run_id"),
        "sink": entry.get("proposed_sink"),
        "action": entry.get("action"),
        "source_id": entry.get("source_id"),
        "artifact_ref": artifact,
        "verification": "get-ok",
        "actor": "opencode",
    })
    payload = {
        "matrix_version": doc.get("matrix_version"),
        "entries": doc.get("entries") or [],
        "applied": applied,
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cap-apply-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply_one(key: str, entry: dict[str, Any], card: dict[str, str]) -> int:
    args = ["card", "--id", card["id"], "--title", card["title"],
            "--column", card["column"], "--priority", card["priority"],
            "--brief", card["brief"], "--spec", card["spec"],
            "--tag", card["tag"]]
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        rc, out = _board(*args)
        if rc == 0 and '"ok": true' in out:
            break
        last = out[:200]
        print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {last}", file=sys.stderr)
        if attempt < MAX_ATTEMPTS:
            time.sleep(attempt)
    else:
        print(f"error: card create failed after {MAX_ATTEMPTS} attempts: {last}", file=sys.stderr)
        return 2

    rc, out = _board("get", card["id"])
    verified = False
    try:
        doc = json.loads(out)
        verified = any(str(c.get("id") or "") == card["id"]
                       and str(c.get("title") or "") == card["title"]
                       for c in doc.get("cards") or [])
    except Exception:
        pass
    if not verified:
        print(f"error: card created but GET verification failed for {card['id']}; "
              f"ledger NOT marked applied — reconcile manually before retry", file=sys.stderr)
        return 3

    artifact = BOARD_URL + card["id"]
    append_applied(LEDGER, entry, card, artifact)
    # Durable audit mirror (OPS-1368): capture-ledger.yml is regenerable
    # runtime state — a fresh harvest drops the applied: block. The card
    # comm survives any ledger loss and is the board-native audit record.
    applied_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    audit_text = (
        f"capture-apply audit: dedupe_key={entry.get('dedupe_key')} "
        f"applied_at={applied_at} sink={entry.get('proposed_sink')}/"
        f"{entry.get('action')} source={entry.get('source')}/"
        f"{entry.get('source_id')} run_id={entry.get('run_id')} "
        f"artifact={artifact}")
    rc2, out2 = _board("comment", card["id"], audit_text, "--from", "devin")
    if rc2:
        print(f"warning: applied audit comm failed ({out2[:160]}); "
              f"ledger record stands — mirror the audit manually",
              file=sys.stderr)
    comm_note = " + card comm" if rc2 == 0 else ""
    print(f"applied: {key} -> {artifact} (verified GET, audit appended{comm_note})")
    print(f"rollback: board-cli --ssh {BOARD_SSH} action {card['id']} close --from devin")
    return 0


def self_test() -> int:
    ok = 0
    total = 0
    global REPO
    real_repo = REPO
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        REPO = root
        inbox = root / "docs/ssot/focus-inbox"
        inbox.mkdir(parents=True)
        (inbox / "2026-11-12-wiki.yml").write_text(
            "title: Wiki login polish\nfocus:\n  status: draft\n  text: Fix the Google button label.\n",
            encoding="utf-8")
        (inbox / "2026-11-11-done.yml").write_text(
            "title: Already filed\nfocus:\n  status: processed\n  text: This was filed already.\n",
            encoding="utf-8")
        ledger = {"entries": [
            {"dedupe_key": "kanban:a", "proposed_sink": "kanban", "action": "create",
             "source": "focus-inbox", "source_id": "2026-11-12-wiki", "run_id": "r1",
             "confidence": 0.8, "rule": "actionable-work"},
            {"dedupe_key": "lesson:b", "proposed_sink": "lesson", "action": "create",
             "source": "focus-inbox", "source_id": "2026-11-12-wiki"},
            {"dedupe_key": "kanban:c", "proposed_sink": "kanban", "action": "create",
             "source": "focus-inbox", "source_id": "2026-11-11-done"},
            {"dedupe_key": "kanban:done", "proposed_sink": "kanban", "action": "create",
             "source": "focus-inbox", "source_id": "2026-11-12-wiki", "run_id": "r0"},
        ], "applied": [{"dedupe_key": "kanban:done"}]}
        # source gates
        good = source_artifact(ledger["entries"][0])[0]
        bad = not source_artifact(ledger["entries"][2])[0]
        print(f"[{'OK' if good else 'FAIL'}] live source accepted")
        ok += good; total += 1
        print(f"[{'OK' if bad else 'FAIL'}] terminal source rejected")
        ok += bad; total += 1
        # allowlist + idempotence + confirm gates (no board calls: monkeypatch)
        global existing_cards
        real = existing_cards
        existing_cards = lambda: []
        try:
            f, e, c, _ = check_gates("lesson:b", False, None, ledger)
            good = any("not allowed" in x for x in f)
            print(f"[{'OK' if good else 'FAIL'}] unallowlisted sink blocked")
            ok += good; total += 1
            f, e, c, _ = check_gates("kanban:a", True, "wrong", ledger)
            good = any("retype" in x for x in f)
            print(f"[{'OK' if good else 'FAIL'}] missing confirmation blocked")
            ok += good; total += 1
            f, e, c, _ = check_gates("kanban:a", False, None, ledger)
            good = (not f and c["id"] == "2026-11-12-wiki" and c["column"] == "backlog")
            print(f"[{'OK' if good else 'FAIL'}] allowed proposal builds card payload")
            ok += good; total += 1
            f2, *_ = check_gates("kanban:done", False, None, ledger)
            good = any("already applied" in x for x in f2)
            print(f"[{'OK' if good else 'FAIL'}] idempotence gate blocks re-apply")
            ok += good; total += 1
            # duplicate detection
            existing_cards = lambda: [{"id": "2026-11-12-wiki", "title": "Other"}]
            f3, *_ = check_gates("kanban:a", False, None, ledger)
            good = any("id already exists" in x for x in f3)
            print(f"[{'OK' if good else 'FAIL'}] duplicate card id blocked")
            ok += good; total += 1
        finally:
            existing_cards = real
        # audit append preserves entries + is idempotent-safe structurally
        lp = root / "ledger.yml"
        lp.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")
        append_applied(lp, {"dedupe_key": "kanban:new", "run_id": "r2",
                            "proposed_sink": "kanban", "action": "create",
                            "source_id": "s"}, {"id": "new"}, "ref")
        d2 = yaml.safe_load(lp.read_text())
        good = len(d2["entries"]) == 4 and len(d2["applied"]) == 2
        print(f"[{'OK' if good else 'FAIL'}] audit append preserves ledger")
        ok += good; total += 1
    REPO = real_repo
    print(f"self-test: {ok}/{total} passed")
    return 0 if ok == total else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", help="exact dedupe_key from capture-ledger.yml")
    ap.add_argument("--apply", action="store_true", help="commit the write (default: dry-run)")
    ap.add_argument("--confirm", help="must retype the exact --key when --apply is set")
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.key:
        ap.error("--key is required (there is deliberately no bulk mode)")

    doc = load_ledger(a.ledger)
    failures, entry, card, reason = check_gates(a.key, a.apply, a.confirm, doc)
    if not a.apply:
        if entry is None:
            print(f"error: dedupe_key not found: {a.key}", file=sys.stderr)
            return 2
        print(render_dry_run(a.key, entry, card or {}, failures, reason))
        print("\nDRY-RUN: nothing was written.")
        return 0
    if failures:
        for f in failures:
            print(f"gate blocked: {f}", file=sys.stderr)
        return 2
    return apply_one(a.key, entry, card)


if __name__ == "__main__":
    raise SystemExit(main())
