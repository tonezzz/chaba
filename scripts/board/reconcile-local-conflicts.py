#!/usr/bin/env python3
"""reconcile-local-conflicts — merge .local-conflict-* card files back.

git-safe-pull.sh resolves rebase conflicts under generated paths
upstream-wins, preserving the dropped local side as
<path>.local-conflict-<ts>. For kanban cards that copy almost always
holds a board-api write that raced the pull (column move, action.status
change, request answer, appended comms). This script is the reconcile
half (card kanban-local-conflict-reconciler):

  for each docs/ssot/kanban/cards/*.yml.local-conflict-*:
    load conflict + canonical under the board write flock, merge the
    board-mutated fields, write the canonical card, delete the conflict
    file. On any failure the conflict file stays and the card is
    flagged in review — no card write is silently dropped.

Merge policy
------------
  * comms[]      — union, dedup on (at|ts, from, text), time-sorted
  * requests[]   — merged by id; per entry the more-resolved / newer
                   side wins key conflicts (open < answered)
  * ask{}        — same rule as a single requests[] entry
  * action{}     — per-key union; the newer side (by `updated`) wins
  * pipeline{}   — per-key union; stages deep-merged per stage `at`
  * board scalars (column, note, awaiting_action, claim, review_kind)
                 — newer side wins; keys only the older side has survive
  * updated      — max of the two
  * everything else — canonical (upstream) wins on conflict;
    conflict-only keys survive (they are local writes too)

"Newer" = the side with the later `updated` stamp; on a tie the
conflict side wins, since it holds the write the pull dropped.

Runs under the board write flock (/tmp/board-api.lock) so it never
races board-api.py / merge-sweep locked writes. Invoked as a post-pull
step by git-safe-pull.sh; also safe to run by hand anytime:

  reconcile-local-conflicts.py [--dry-run] [repo-dir]
  reconcile-local-conflicts.py --selftest
"""
from __future__ import annotations

import argparse
import fcntl
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARD_DIR_REL = Path("docs/ssot/kanban/cards")
GENERATED_REL = Path("docs/ssot")
LOCK = Path("/tmp/board-api.lock")
ALERT_CARD_ID = "ops-local-conflict-guard"
TZ = timezone(timedelta(hours=7))

CONFLICT_RE = re.compile(
    r"^(?P<base>.+)\.local-conflict-\d{8}-\d{6}(-\d+)?$")

# Scalar keys board-api mutates in place — the newer side wins these.
BOARD_SCALARS = ("column", "note", "awaiting_action", "claim",
                 "review_kind")
# Status progression for requests[]/ask entries.
STATUS_RANK = {"open": 0, "answered": 1, "closed": 2, "resolved": 2}


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def dump(p: Path, card: dict) -> None:
    p.write_text(yaml.safe_dump(card, allow_unicode=True,
                                sort_keys=False, width=110))


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]})


# ---------------------------------------------------------------- merge
def _entry_ts(e: dict) -> str:
    """Sortable timestamp for a comms/request entry — 'at' is the board
    format, 'ts' ISO appears on some older entries."""
    for k in ("answered_at", "at", "ts"):
        v = e.get(k)
        if v:
            return str(v)
    return ""


def _comms_key(e: dict) -> tuple:
    if not isinstance(e, dict):
        return ("", "", repr(e))
    return (str(e.get("at") or e.get("ts") or ""),
            str(e.get("from") or ""),
            str(e.get("text") or ""))


def merge_comms(a: list, b: list) -> list:
    seen, out = set(), []
    for e in list(a or []) + list(b or []):
        k = _comms_key(e)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    out.sort(key=lambda e: _entry_ts(e) if isinstance(e, dict) else "")
    return out


def _newer_entry(a: dict, b: dict) -> tuple[dict, dict]:
    """Order two same-id request/ask entries (loser, winner): higher
    status rank wins; ties break on the later timestamp."""
    ra = STATUS_RANK.get(str(a.get("status") or ""), 0)
    rb = STATUS_RANK.get(str(b.get("status") or ""), 0)
    if ra != rb:
        return (a, b) if rb > ra else (b, a)
    ta, tb = _entry_ts(a), _entry_ts(b)
    return (a, b) if tb >= ta else (b, a)


def merge_requests(a: list, b: list) -> list:
    """Union by id (falling back to the ask text); per id the more
    resolved / newer entry wins each key."""
    out: list[dict] = []
    index: dict[str, dict] = {}

    def key(e):
        return str(e.get("id") or e.get("ask") or "")

    for e in list(a or []) + list(b or []):
        if not isinstance(e, dict):
            if e not in out:
                out.append(e)
            continue
        k = key(e)
        if k in index:
            loser, winner = _newer_entry(index[k], e)
            merged_e = {**loser, **winner}  # before clear — winner may
            index[k].clear()                # be index[k] itself
            index[k].update(merged_e)
        else:
            index[k] = dict(e)
            out.append(index[k])
    return out


def merge_pipeline(older: dict, newer: dict) -> dict:
    out = {**(older or {}), **(newer or {})}
    if isinstance((older or {}).get("stages"), dict) and \
            isinstance((newer or {}).get("stages"), dict):
        stages = dict(older["stages"])
        for name, st in newer["stages"].items():
            cur = stages.get(name)
            if isinstance(cur, dict) and isinstance(st, dict):
                loser, winner = _newer_entry(cur, st)
                stages[name] = {**loser, **winner}
            else:
                stages[name] = st
        out["stages"] = stages
    return out


def merge_cards(canonical: dict, conflict: dict) -> tuple[dict, list]:
    """Return (merged, notes). Canonical is the upstream-wins side;
    conflict is the dropped local side."""
    notes = []
    c_newer = str(conflict.get("updated") or "") >= \
        str(canonical.get("updated") or "")
    older, newer = (canonical, conflict) if c_newer \
        else (conflict, canonical)
    side = "conflict" if c_newer else "canonical"

    merged = {**conflict, **canonical}   # generic keys: upstream wins

    for k in BOARD_SCALARS:
        if k in newer:
            if merged.get(k) != newer[k]:
                notes.append(f"{k}: {merged.get(k)!r} -> {newer[k]!r} ({side})")
            merged[k] = newer[k]
        # keys present only on the older side survive via merged above

    for k in ("action", "ask"):
        lo, hi = older.get(k), newer.get(k)
        if isinstance(lo, dict) and isinstance(hi, dict):
            v = {**lo, **hi}
            if merged.get(k) != v:
                notes.append(f"{k}: merged per-key ({side} wins)")
            merged[k] = v
        elif isinstance(hi, dict):
            merged[k] = hi

    if isinstance(canonical.get("pipeline"), dict) or \
            isinstance(conflict.get("pipeline"), dict):
        merged["pipeline"] = merge_pipeline(older.get("pipeline"),
                                            newer.get("pipeline"))

    reqs = merge_requests(conflict.get("requests"),
                          canonical.get("requests"))
    if reqs:
        merged["requests"] = reqs
    elif "requests" in merged:
        merged.pop("requests")

    com = merge_comms(conflict.get("comms"), canonical.get("comms"))
    if com:
        merged["comms"] = com
    elif "comms" in merged:
        merged.pop("comms")

    merged["updated"] = max(str(canonical.get("updated") or ""),
                            str(conflict.get("updated") or ""))
    return merged, notes


# ------------------------------------------------------------- flagging
def flag_card(card_dir: Path, cid: str | None, text: str,
              dry: bool) -> None:
    """Flag a failed reconcile: comms + column=review on the canonical
    card when it exists; otherwise upsert the ops alert card. Pattern
    mirrors kanban-commit.sh's alert_card."""
    if dry:
        print(f"  [dry] flag {cid or ALERT_CARD_ID}: {text[:120]}")
        return
    target = card_dir / f"{cid}.yml" if cid else \
        card_dir / f"{ALERT_CARD_ID}.yml"
    if cid and not target.exists():
        target = card_dir / f"{ALERT_CARD_ID}.yml"
    try:
        try:
            card = load(target) if target.exists() else {}
        except Exception:
            # canonical unreadable — flag the alert card instead
            target = card_dir / f"{ALERT_CARD_ID}.yml"
            card = load(target) if target.exists() else {}
        if not isinstance(card, dict):
            card = {}
        comms_add(card, "chaba", text)
        if target.stem == ALERT_CARD_ID:
            card.update(id=ALERT_CARD_ID,
                        title="local-conflict reconcile failed",
                        note=text[:500])
        if card.get("column") != "review":
            card["column"] = "review"
        card["updated"] = now()
        dump(target, card)
    except Exception as e:  # flagging must never crash the reconciler
        print(f"reconcile: flag write failed for {target.name}: {e}",
              file=sys.stderr)


# ------------------------------------------------------------ reconcile
def reconcile_one(conflict_path: Path, dry: bool) -> bool:
    """Merge one .local-conflict file into its canonical card.
    Returns True when the conflict file was consumed."""
    m = CONFLICT_RE.match(conflict_path.name)
    if not m:
        print(f"reconcile: unrecognised suffix: {conflict_path.name}",
              file=sys.stderr)
        return False
    canonical_path = conflict_path.with_name(m.group("base"))
    card_dir = conflict_path.parent
    cid = canonical_path.stem

    if not canonical_path.exists():
        flag_card(card_dir, None,
                  f"orphan {conflict_path.name}: canonical card "
                  f"{canonical_path.name} missing (deleted upstream?) — "
                  f"conflict file kept for manual review", dry)
        print(f"reconcile: {conflict_path.name}: no canonical — flagged",
              file=sys.stderr)
        return False
    try:
        canonical, conflict = load(canonical_path), load(conflict_path)
        if not isinstance(canonical, dict) or \
                not isinstance(conflict, dict):
            raise ValueError("card YAML is not a mapping")
    except Exception as e:
        flag_card(card_dir, cid if canonical_path.exists() else None,
                  f"unresolved {conflict_path.name}: YAML load failed "
                  f"({e}) — conflict file kept", dry)
        print(f"reconcile: {conflict_path.name}: load failed: {e}",
              file=sys.stderr)
        return False

    try:
        merged, notes = merge_cards(canonical, conflict)
    except Exception as e:
        flag_card(card_dir, cid,
                  f"unresolved {conflict_path.name}: merge failed "
                  f"({e}) — conflict file kept", dry)
        print(f"reconcile: {conflict_path.name}: merge failed: {e}",
              file=sys.stderr)
        return False

    gained = len(merged.get("comms") or []) - \
        len(canonical.get("comms") or [])
    summary = f"auto-reconciled {conflict_path.name}"
    if notes:
        summary += ": " + "; ".join(notes[:6])
    if gained > 0:
        summary += f"; +{gained} comms"

    if merged == canonical:
        # nothing unique on the dropped side — no card write needed
        if dry:
            print(f"  [dry] {conflict_path.name}: identical — dropped")
            return True
        try:
            conflict_path.unlink()
        except OSError as e:
            print(f"reconcile: {conflict_path.name}: unlink failed: {e}",
                  file=sys.stderr)
            return False
        print(f"reconcile: {conflict_path.name}: identical — dropped")
        return True

    if dry:
        print(f"  [dry] {conflict_path.name}: {summary}")
        return True
    try:
        merged.setdefault("id", cid)
        comms_add(merged, "chaba", summary)
        dump(canonical_path, merged)
        conflict_path.unlink()
    except Exception as e:
        flag_card(card_dir, cid,
                  f"unresolved {conflict_path.name}: write failed "
                  f"({e}) — conflict file kept", dry)
        print(f"reconcile: {conflict_path.name}: write failed: {e}",
              file=sys.stderr)
        return False
    print(f"reconcile: {conflict_path.name} -> {canonical_path.name}: "
          f"{summary}")
    return True


def run(repo: Path, dry: bool) -> int:
    card_dir = repo / CARD_DIR_REL
    leftovers = 0
    if card_dir.is_dir():
        for p in sorted(card_dir.glob("*.local-conflict-*")):
            if not reconcile_one(p, dry):
                leftovers += 1
    # non-card generated conflicts: never silently dropped either —
    # surfaced on the alert card, merged by hand.
    ssot = repo / GENERATED_REL
    if ssot.is_dir():
        stray = [p for p in ssot.rglob("*.local-conflict-*")
                 if card_dir not in p.parents and p.parent != card_dir]
        for p in stray:
            flag_card(card_dir, None,
                      f"non-card local-conflict {p.relative_to(repo)} "
                      f"needs manual reconcile — file kept", dry)
            print(f"reconcile: non-card conflict kept: "
                  f"{p.relative_to(repo)}", file=sys.stderr)
            leftovers += 1
    return 1 if leftovers else 0


# ------------------------------------------------------------- selftest
def _selftest() -> None:
    def card(**kw):
        c = {"id": "t", "title": "t", "column": "backlog",
             "updated": "2026-10-10 08:00", "comms": []}
        c.update(kw)
        return c

    # comms union + dedup + sort
    a = card(comms=[{"at": "2026-10-10 08:00", "from": "tony", "text": "x"},
                    {"at": "2026-10-10 08:05", "from": "ada", "text": "y"}])
    b = card(comms=[{"at": "2026-10-10 08:05", "from": "ada", "text": "y"},
                    {"at": "2026-10-10 07:59", "from": "devin", "text": "z"}])
    m, _ = merge_cards(a, b)
    assert [c["text"] for c in m["comms"]] == ["z", "x", "y"]

    # column: conflict newer wins; canonical-newer keeps upstream move
    c_new = card(column="done", updated="2026-10-10 09:00")
    m, n = merge_cards(card(column="doing", updated="2026-10-10 08:00"),
                       c_new)
    assert m["column"] == "done" and n
    m, _ = merge_cards(card(column="done", updated="2026-10-10 09:00"),
                       card(column="doing", updated="2026-10-10 08:00"))
    assert m["column"] == "done"

    # requests merge by id — answer survives, open side filled
    canon = card(requests=[{"id": "r1", "ask": "q", "status": "open"},
                           {"id": "r2", "ask": "q2", "status": "open"}])
    conf = card(requests=[{"id": "r1", "ask": "q", "status": "answered",
                           "answer": "yes",
                           "answered_at": "2026-10-10 09:01"}],
                updated="2026-10-10 09:01")
    m, _ = merge_cards(canon, conf)
    r1 = [r for r in m["requests"] if r["id"] == "r1"][0]
    assert r1["status"] == "answered" and r1["answer"] == "yes"
    assert any(r["id"] == "r2" for r in m["requests"])

    # action per-key union, newer wins status
    m, _ = merge_cards(
        card(action={"type": "dispatch", "repo": "chaba",
                     "status": "done"},
             updated="2026-10-10 07:00"),
        card(action={"type": "dispatch", "repo": "chaba",
                     "status": "queued", "runner": "idc02"},
             updated="2026-10-10 09:00"))
    assert m["action"] == {"type": "dispatch", "repo": "chaba",
                           "status": "queued", "runner": "idc02"}

    # ask block: answered side wins
    m, _ = merge_cards(
        card(ask={"status": "open", "question": "q?"},
             updated="2026-10-10 07:00"),
        card(ask={"status": "answered", "question": "q?", "answer": "a"},
             updated="2026-10-10 09:00"))
    assert m["ask"]["status"] == "answered"

    # conflict-only generic keys survive; canonical wins shared keys
    m, _ = merge_cards(card(spec="up", tags=["a"]),
                       card(spec="local", priority="high",
                            updated="2026-10-10 09:00"))
    assert m["spec"] == "up" and m["priority"] == "high"

    # end-to-end: file consumed, canonical merged
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / CARD_DIR_REL
        d.mkdir(parents=True)
        (d / "t.yml").write_text(yaml.safe_dump(
            card(column="backlog", updated="2026-10-10 08:00")))
        (d / "t.yml.local-conflict-20261010-090000").write_text(
            yaml.safe_dump(card(column="done",
                                updated="2026-10-10 09:00",
                                comms=[{"at": "2026-10-10 09:00",
                                        "from": "tony",
                                        "text": "close it"}])))
        assert run(Path(td), dry=False) == 0
        out = load(d / "t.yml")
        assert out["column"] == "done"
        assert not list(d.glob("*.local-conflict-*"))
        assert any("auto-reconciled" in c["text"]
                   for c in out["comms"])

    # orphan conflict: file stays, alert card flagged in review
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / CARD_DIR_REL
        d.mkdir(parents=True)
        (d / "gone.yml.local-conflict-20261010-090000").write_text(
            yaml.safe_dump(card()))
        assert run(Path(td), dry=False) == 1
        assert (d / "gone.yml.local-conflict-20261010-090000").exists()
        alert = load(d / f"{ALERT_CARD_ID}.yml")
        assert alert["column"] == "review" and alert["comms"]

    # unparseable conflict: stays, canonical flagged
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / CARD_DIR_REL
        d.mkdir(parents=True)
        (d / "t.yml").write_text(yaml.safe_dump(card(column="doing")))
        (d / "t.yml.local-conflict-20261010-090000").write_text(
            "a: [unclosed\n")
        assert run(Path(td), dry=False) == 1
        assert (d / "t.yml.local-conflict-20261010-090000").exists()
        out = load(d / "t.yml")
        assert out["column"] == "review" and \
            any("unresolved" in c["text"] for c in out["comms"])

    print("reconcile-local-conflicts: selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=str(REPO))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return 0
    repo = Path(args.repo).resolve()
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        return run(repo, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
