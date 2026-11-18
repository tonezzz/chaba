#!/usr/bin/env python3
"""memory-merge-proposals.py — weekly recommend-mode merge proposals for
Ada memory banks (card memory-extract-merge-proposals).

memory-distill.py dedups candidates at DEDUP_SCORE=0.82: a draft that
*updates* an existing canonical (vector score ~0.82-0.95 — same
subject/attribute, different or newer fact) is either skipped as "known"
or lands as a separate draft that never merges, so canonicals drift
stale. This job closes that gap in recommend mode only:

  propose (default): for every writable bank, list active canonicals +
    source=extract drafts from the last --draft-days (default 14). Each
    draft is vector-searched against its own collection; hits scoring
    MERGE_LO..MERGE_HI on the same subject/attribute become proposals
    {canonical_key, draft_key, fact delta, suggested action}. Output =
    ada-cms-pages/memory-merge-proposals (managed block) + a comment on
    the card. NO writes to canonicals — ever.

  resolve: a human applies a proposal by id —
      --resolve merge-ab12cd34 --action update-in-place|supersede|reject
    update-in-place / supersede perform the real supersede-link writes
    (supersedes/superseded_by, last_verified bump, draft marked
    status=superseded + merge_review=applied). reject stamps the draft
    merge_review=rejected so it is never re-proposed.

Metrics: every run logs proposals/pending/acceptance; state in
~/.cache/ada-memory-merge-proposals.json tracks per-pair outcomes so a
rolling acceptance rate lands in the report. If acceptance holds >80%
for ~4 weeks, a follow-up card may spec auto-apply — not this job.

Usage:
  memory-merge-proposals.py                 # propose + publish report
  memory-merge-proposals.py --dry-run       # print proposals, no writes
  memory-merge-proposals.py --list-pending  # show unresolved proposals
  memory-merge-proposals.py --resolve merge-xxxx --action reject
  memory-merge-proposals.py --resolve merge-xxxx --action supersede
  memory-merge-proposals.py --resolve merge-xxxx --action update-in-place \
      --text "approved wording"

Env: ADA_MEMORY_MDDB_URL (banks, default :11023), MDDB_BASE_URL
     (ada-cms-pages, default :11027), BOARD_API (card comments,
     default https://idc03.taila0626a.ts.net:10000),
     MERGE_PROPOSALS_CARD (default memory-extract-merge-proposals),
     MERGE_PROPOSALS_STATE (state file override).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import requests

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

import chaba_event

REPO = Path(__file__).resolve().parents[2]
MDDB_BANKS = os.environ.get(
    "ADA_MEMORY_MDDB_URL", "http://100.102.134.91:11023/v1").rstrip("/")
MDDB_CMS = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
CMS_COLLECTION = "ada-cms-pages"
PAGE = "memory-merge-proposals"
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
CARD_ID = os.environ.get("MERGE_PROPOSALS_CARD",
                         "memory-extract-merge-proposals")
STATE = Path(os.environ.get(
    "MERGE_PROPOSALS_STATE",
    Path.home() / ".cache/ada-memory-merge-proposals.json"))

# Same band the card defines: >=MERGE_LO means the draft is probably
# about the canonical; >=MERGE_HI means it's a restatement (dup), not an
# update. Only the band between them is "probable update/supersede".
MERGE_LO = 0.82
MERGE_HI = 0.95
DRAFT_DAYS = 14
MAX_PROPOSALS = 25
ACCEPT_WINDOW_D = 90
WRITTEN_BY = "memory-merge-proposals"

BLOCK_BEGIN = "<!-- merge-proposals:auto -->"
BLOCK_END = "<!-- /merge-proposals:auto -->"
BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" +
                      re.escape(BLOCK_END), re.S)

SEP_RE = re.compile(r"\n\s*---\s*\n")


# ------------------------------------------------------------------ docs

def mval(doc: dict, field: str) -> str:
    v = (doc.get("meta") or {}).get(field)
    if isinstance(v, list):
        return str(v[0]) if v and v[0] not in (None, "") else ""
    return str(v) if v not in (None, "") else ""


def draft_fact(doc: dict) -> str:
    """The extracted fact verbatim — distill drafts append a '---'
    provenance footer; everything before it is the fact."""
    body = (doc.get("contentMd") or "").strip()
    return SEP_RE.split(body, 1)[0].strip() or body


def doc_date(doc: dict) -> date | None:
    for f in ("last_verified", "valid_from"):
        try:
            return date.fromisoformat(mval(doc, f))
        except ValueError:
            continue
    ts = doc.get("addedAt") or doc.get("updatedAt")
    if ts:
        return datetime.fromtimestamp(ts, timezone.utc).date()
    return None


def is_candidate_draft(doc: dict, max_age: int) -> bool:
    meta = doc.get("meta") or {}
    if mval(doc, "status") != "draft" or mval(doc, "source") != "extract":
        return False
    if mval(doc, "merge_review"):   # resolved (applied/rejected) — done
        return False
    d = doc_date(doc)
    return d is not None and (date.today() - d).days <= max_age


def is_canonical(doc: dict) -> bool:
    return mval(doc, "status") == "active"


def same_slot(draft: dict, canon: dict) -> bool:
    """Same subject/attribute join: subject must match when both carry
    one; attribute must match when both carry one. Missing meta falls
    back to score-only (flagged weak_join in the proposal)."""
    ds, cs = mval(draft, "subject"), mval(canon, "subject")
    if ds and cs and ds != cs:
        return False
    da, ca = mval(draft, "attribute"), mval(canon, "attribute")
    if da and ca and da != ca:
        return False
    return True


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def suggest_action(draft: dict, canon: dict) -> str:
    """Deterministic suggestion — no LLM (v1 non-goal)."""
    dtxt, ctxt = draft_fact(draft), (canon.get("contentMd") or "")
    if dtxt.lower() in ctxt.lower() or jaccard(dtxt, ctxt) >= 0.9:
        return "reject"          # restatement — nothing new to merge
    ds, cs = mval(draft, "scope"), mval(canon, "scope")
    if ds and cs and ds != cs:
        return "supersede"       # re-scoped fact — new doc identity
    return "update-in-place"     # same slot, newer value


def proposal_id(collection: str, canon_key: str, draft_key: str) -> str:
    h = hashlib.sha1(
        f"{collection}:{canon_key}:{draft_key}".encode()).hexdigest()[:8]
    return f"merge-{h}"


def slug(text: str, max_words: int = 6) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:max_words]) or "item"


# ------------------------------------------------------------------ state

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")


def reconcile(state: dict, docs_by_coll: dict[str, dict[str, dict]]) -> None:
    """Refresh 'proposed' pairs against live doc state — picks up
    resolutions applied outside --resolve (consolidate flow, ada tools)."""
    today = date.today().isoformat()
    for pid, p in (state.get("pairs") or {}).items():
        if p.get("status") != "proposed":
            continue
        docs = docs_by_coll.get(p["collection"])
        if docs is None:
            continue  # collection not scanned this run (bank/instance filter)
        doc = docs.get(p["draft"])
        if doc is None:
            p["status"], p["resolved_at"] = "gone", today
            continue
        review = mval(doc, "merge_review")
        if review in ("applied", "merged"):
            p["status"], p["resolved_at"] = "applied", today
        elif review == "rejected":
            p["status"], p["resolved_at"] = "rejected", today
        elif mval(doc, "status") in ("superseded", "retracted"):
            p["status"], p["resolved_at"] = "applied", today


def acceptance(state: dict) -> dict:
    """Rolling acceptance over the last ACCEPT_WINDOW_D days + lifetime."""
    cutoff = date.today().toordinal() - ACCEPT_WINDOW_D
    win = {"applied": 0, "rejected": 0}
    life = {"applied": 0, "rejected": 0}
    pending = 0
    for p in (state.get("pairs") or {}).values():
        st = p.get("status")
        if st == "proposed":
            pending += 1
            continue
        if st not in ("applied", "rejected"):
            continue
        life[st] += 1
        try:
            if date.fromisoformat(p.get("resolved_at") or "").toordinal() \
                    >= cutoff:
                win[st] += 1
        except ValueError:
            pass
    wtot = win["applied"] + win["rejected"]
    ltot = life["applied"] + life["rejected"]
    return {
        "pending": pending,
        "window": win,
        "window_rate": round(win["applied"] / wtot, 3) if wtot else None,
        "lifetime": life,
        "lifetime_rate": round(life["applied"] / ltot, 3) if ltot else None,
    }


# ------------------------------------------------------------------ mddb

def _meta_applied(doc: dict | None, meta: dict) -> bool:
    """Subset check — every intended meta field already live on the doc."""
    if not isinstance(doc, dict):
        return False
    cur = doc.get("meta") or {}
    return all(cur.get(k) == v for k, v in meta.items())


def update_meta(mddb: "ada_sync.Mddb", collection: str, key: str,
                meta: dict, content: str) -> None:
    """Meta-only PATCH /update (no re-embed); fall back to full re-add.
    Under embed stress MDDB sometimes commits the PATCH but drops the
    response — so on a transport error we verify via /get before
    retrying instead of blindly re-patching / re-adding."""
    for attempt in range(3):
        try:
            r = mddb.s.patch(f"{mddb.base}/update",
                             json={"collection": collection, "key": key,
                                   "lang": "en", "meta": meta},
                             timeout=mddb.timeout)
            if r.status_code == 200:
                return
            break  # deterministic HTTP error -> fallback below
        except (requests.ConnectionError, requests.Timeout):
            if _meta_applied(get_doc(mddb, collection, key), meta):
                return  # committed despite the dropped response
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    mddb.add(collection, key, content, meta)


def get_doc(mddb: "ada_sync.Mddb", collection: str, key: str) -> dict | None:
    try:
        return mddb._post("/get", {"collection": collection, "key": key,
                                   "lang": "en"})
    except Exception:
        return None


def vector_hits(mddb: "ada_sync.Mddb", collection: str, text: str,
                top_k: int = 8) -> list[dict]:
    r = mddb._post("/vector-search", {
        "collection": collection, "query": text, "topK": top_k,
        "threshold": MERGE_LO, "includeContent": True})
    return list((r or {}).get("results") or [])


def hit_key(h: dict) -> str:
    doc = h.get("document") or h.get("doc") or {}
    return str(h.get("key") or doc.get("key") or "")


def hit_score(h: dict) -> float:
    try:
        return float(h.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ propose

def propose(mddb: "ada_sync.Mddb", args) -> tuple[
        list[dict], dict, dict[str, dict[str, dict]]]:
    """Scan writable banks; return (proposals, per-bank stats, docs)."""
    mappings = [m for m in ada_sync.load_bank_map() if m["writable"]]
    if args.instance:
        mappings = [m for m in mappings
                    if m["scope"] in ("shared", args.instance)]
    if args.bank:
        mappings = [m for m in mappings if m["bank"] in args.bank]
    seen_colls, proposals, stats = set(), [], {}
    docs_by_coll: dict[str, dict[str, dict]] = {}
    for m in mappings:
        coll = m["collection"]
        if coll in seen_colls:
            continue
        seen_colls.add(coll)
        try:
            docs = {d.get("key"): d for d in mddb.list_docs(coll)
                    if d.get("key")}
        except Exception as exc:
            print(f"  ! {coll}: list failed: {exc}", file=sys.stderr)
            continue
        docs_by_coll[coll] = docs
        drafts = [d for d in docs.values()
                  if is_candidate_draft(d, args.draft_days)]
        canons = {k: d for k, d in docs.items() if is_canonical(d)}
        stats[coll] = {"bank": m["bank"], "drafts": len(drafts),
                       "canonicals": len(canons), "search_errors": 0}
        for draft in sorted(drafts, key=lambda d: d.get("key") or ""):
            if len(proposals) >= args.max_proposals:
                break
            fact = draft_fact(draft)
            if not fact:
                continue  # nothing to embed — footer-only drafts
            try:
                hits = vector_hits(mddb, coll, fact)
            except Exception as exc:
                stats[coll]["search_errors"] += 1
                print(f"  ! {coll}: vector-search {draft['key']}: {exc}",
                      file=sys.stderr)
                continue
            for h in hits:
                score = hit_score(h)
                if not (MERGE_LO <= score < MERGE_HI):
                    continue
                canon = docs.get(hit_key(h))
                if canon is None or not is_canonical(canon):
                    continue
                if canon.get("key") == draft.get("key"):
                    continue
                if not same_slot(draft, canon):
                    continue
                proposals.append({
                    "id": proposal_id(coll, canon["key"], draft["key"]),
                    "collection": coll, "bank": m["bank"],
                    "canonical": canon["key"], "draft": draft["key"],
                    "score": round(score, 3),
                    "subject": mval(draft, "subject") or mval(canon, "subject"),
                    "attribute": mval(draft, "attribute")
                                 or mval(canon, "attribute"),
                    "action": suggest_action(draft, canon),
                    "weak_join": not (
                        mval(draft, "subject") and mval(canon, "subject")),
                    "canon_excerpt": (canon.get("contentMd") or "")
                                     .strip()[:400],
                    "draft_text": draft_fact(draft)[:400],
                })
                break  # top candidate per draft — one proposal each
    return proposals, stats, docs_by_coll


# ------------------------------------------------------------------ report

def _esc(s: str) -> str:
    return s.replace("|", "\\|")


def report_block(proposals: list[dict], stats: dict, acc: dict,
                 now: datetime, draft_days: int = DRAFT_DAYS) -> str:
    drafts = sum(s["drafts"] for s in stats.values())
    canons = sum(s["canonicals"] for s in stats.values())
    errors = sum(s.get("search_errors", 0) for s in stats.values())
    wr = (f"{acc['window_rate']:.0%}" if acc["window_rate"] is not None
          else "n/a")
    lr = (f"{acc['lifetime_rate']:.0%}" if acc["lifetime_rate"] is not None
          else "n/a")
    L = [
        BLOCK_BEGIN,
        f"## Latest run — {now:%Y-%m-%d %H:%M}Z",
        "",
        f"drafts scanned ({draft_days}d): **{drafts}** · active canonicals: "
        f"**{canons}** · open proposals: **{len(proposals)}** · "
        f"pending decisions: **{acc['pending']}**",
        f"acceptance ({ACCEPT_WINDOW_D}d): **{wr}** "
        f"({acc['window']['applied']} applied / "
        f"{acc['window']['rejected']} rejected) · lifetime: **{lr}**",
        "",
    ]
    if errors:
        L += [
            f"⚠ **{errors} vector-search call(s) failed this run** "
            "(embed providers down/capped) — proposal count is a lower "
            "bound; retry next run or when the embed chain recovers.",
            "",
        ]
    if not proposals:
        L.append("_No update candidates in the 0.82–0.95 band this run._")
    else:
        L.append("### Open proposals")
        L.append("")
        for p in proposals:
            slot = p["subject"] + (f"/{p['attribute']}"
                                   if p["attribute"] else "")
            L += [
                f"#### `{p['id']}` — {p['action']} "
                f"(score {p['score']:.2f})",
                f"- bank **{p['bank']}** · slot `{slot}`"
                + (" · weak subject join" if p["weak_join"] else ""),
                f"- canonical `{p['canonical']}` ← draft `{p['draft']}`",
                f"- canonical now: {_esc(p['canon_excerpt'][:280])}",
                f"- draft adds/changes: **{_esc(p['draft_text'][:280])}**",
                "",
            ]
    L += [
        "### How to resolve",
        "",
        "```",
        "scripts/ada/memory-merge-proposals.py --resolve <id> \\",
        "    --action update-in-place|supersede|reject [--text \"wording\"]",
        "```",
        "",
        "- `update-in-place` — draft fact becomes the canonical body "
        "(same key, last_verified bumped; MDDB revisions keep the old text)",
        "- `supersede` — new `<bank>/<slug>-<date>` doc quoting the draft "
        "verbatim, canonical -> status=superseded with link fields",
        "- `reject` — draft stamped merge_review=rejected; never re-proposed",
        "",
        f"_Generated by {WRITTEN_BY} — recommend mode only; no canonical "
        "writes without an explicit --resolve._",
        BLOCK_END,
    ]
    return "\n".join(L)


def _post_cms(path: str, payload: dict, timeout: int = 60):
    """CMS mddb POST with bounded retry — same commit-but-drop quirk as
    the banks store under embed stress; /add is key+lang idempotent so
    a replay is safe."""
    for attempt in range(3):
        req = urllib.request.Request(
            f"{MDDB_CMS}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError:
            raise  # deterministic — don't replay 4xx/5xx bodies
        except Exception as exc:
            if attempt == 2:
                raise
            print(f"  cms{path} failed ({exc}) — retrying",
                  file=sys.stderr)
            time.sleep(15 * (attempt + 1))


def publish_report(body: str, now: datetime, dry: bool) -> None:
    try:
        doc = _post_cms("/get", {"collection": CMS_COLLECTION,
                                 "key": PAGE, "lang": "en"})
    except urllib.error.HTTPError:
        doc = None
    old = (doc or {}).get("contentMd") or ""
    if BLOCK_RE.search(old):
        new_body = BLOCK_RE.sub(lambda m: body, old, count=1)
    else:
        title = "# Ada Memory — Merge Proposals\n\n"
        lead = ("Weekly recommend-mode report: extract drafts that "
                "probably *update* an existing canonical (vector score "
                "0.82–0.95, same subject/attribute) — surfaced for human "
                "decision, never auto-applied.\n\n")
        new_body = title + lead + body + "\n"
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in ((doc or {}).get("meta") or {}).items()}
    today = now.date().isoformat()
    meta.update({
        "bank": ["cms"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "written_by": [WRITTEN_BY],
        "subject": [PAGE], "attribute": ["report"],
        "kind": ["report"], "report_role": ["rollup"],
        "domain": ["monitoring"], "format": ["markdown"],
        "lang": ["en"], "slug": [PAGE],
        "title": ["Ada Memory Merge Proposals"],
        "summary": ["Weekly recommend-mode list of extract drafts that "
                    "probably update existing memory canonicals — approve "
                    "or reject each; nothing auto-applies."],
        "fresh_for": ["8d"], "confidence": ["high"],
        "valid_from": meta.get("valid_from") or [today],
        "last_verified": [today],
        "updated": [now.isoformat(timespec="seconds")],
    })
    tl = [x for x in meta.get("timeline", []) if isinstance(x, str)]
    tl.append(f"{now.isoformat(timespec='minutes')}: proposals run")
    meta["timeline"] = tl[-40:]
    if dry:
        print("(dry) would publish ada-cms-pages/" + PAGE)
        return
    try:
        _post_cms("/add", {"collection": CMS_COLLECTION, "key": PAGE,
                           "lang": "en", "contentMd": new_body,
                           "meta": meta}, timeout=120)
    except Exception:
        # commit-but-drop: verify the write actually landed before failing
        doc = _post_cms("/get", {"collection": CMS_COLLECTION,
                                 "key": PAGE, "lang": "en"})
        if (doc or {}).get("contentMd") != new_body:
            raise
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from lib.cms_index import regen_reports_index
        regen_reports_index(MDDB_CMS, written_by=WRITTEN_BY)
    except Exception as exc:
        print(f"  ! reports-index regen failed: {exc}", file=sys.stderr)
    print(f"published -> {CMS_COLLECTION}/{PAGE}")


# ------------------------------------------------------------------ comms

def card_comment(text: str) -> None:
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/comment",
            data=json.dumps({"id": CARD_ID, "from": "chaba",
                             "text": text[:1200]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        print("card comment posted")
    except Exception as exc:
        print(f"  ! card comment failed: {exc}", file=sys.stderr)


def emit_event(title: str, body: str, requires_response: bool) -> None:
    payload = json.dumps({
        "title": title, "category": "ada-memory",
        "source": WRITTEN_BY, "severity": "info",
        "body": body, "requires_response": requires_response,
        "confidence": 0.8})
    try:
        ok, via = chaba_event.send(payload)
        print(f"event: {'ok via ' + via if ok else 'failed: ' + via}")
    except Exception as exc:
        print(f"event emit failed: {exc}")


# ------------------------------------------------------------------ resolve

def resolve(mddb: "ada_sync.Mddb", state: dict, pid: str, action: str,
            text: str | None, actor: str, dry: bool) -> int:
    pair = (state.get("pairs") or {}).get(pid)
    if not pair:
        print(f"unknown proposal {pid} — run without --resolve first",
              file=sys.stderr)
        return 1
    if pair.get("status") != "proposed":
        print(f"{pid} already {pair.get('status')} — refusing",
              file=sys.stderr)
        return 1
    coll, ckey, dkey = pair["collection"], pair["canonical"], pair["draft"]
    canon, draft = get_doc(mddb, coll, ckey), get_doc(mddb, coll, dkey)
    if not canon or not draft:
        print(f"{pid}: canonical or draft doc missing in {coll}",
              file=sys.stderr)
        return 1
    today = date.today().isoformat()
    fact = (text or draft_fact(draft)).strip()
    bank = pair.get("bank") or mval(canon, "bank") or "general"

    if action == "reject":
        meta = dict(draft.get("meta") or {})
        meta["merge_review"] = ["rejected"]
        meta["merge_review_note"] = [f"{pid} rejected by {actor} {today}"]
        if not dry:
            update_meta(mddb, coll, dkey, meta,
                        draft.get("contentMd") or "")
        print(f"{pid}: draft {dkey} marked merge_review=rejected")
    elif action == "update-in-place":
        meta = dict(canon.get("meta") or {})
        meta["last_verified"] = [today]
        meta["updated_by"] = [WRITTEN_BY]
        meta["merged_from"] = [dkey]
        if not dry:
            mddb.add(coll, ckey, fact, meta)
            dmeta = dict(draft.get("meta") or {})
            dmeta["status"] = ["superseded"]
            dmeta["superseded_by"] = [ckey]
            dmeta["merge_review"] = ["applied"]
            update_meta(mddb, coll, dkey, dmeta,
                        draft.get("contentMd") or "")
        print(f"{pid}: canonical {ckey} updated in place; "
              f"draft {dkey} superseded")
    else:  # supersede
        subj = mval(draft, "subject") or slug(fact, 4)
        new_key = f"{bank}/{subj}-{today}"
        existing = get_doc(mddb, coll, new_key)
        if existing and mval(existing, "supersedes") == ckey:
            pass  # same-day retry of a partial apply — reuse the doc
        else:
            n = 2
            while get_doc(mddb, coll, new_key):
                new_key = f"{bank}/{subj}-{today}-{n}"
                n += 1
            meta = dict(draft.get("meta") or {})
            meta.update({
                "status": ["active"], "source": ["extract"],
                "written_by": [WRITTEN_BY],
                "supersedes": [ckey],
                "valid_from": [today], "last_verified": [today],
            })
            meta.pop("merge_review", None)
            body = (fact + f"\n\n---\n_supersedes `{ckey}` via {pid} "
                    f"(approved by {actor})_\n")
            if not dry:
                mddb.add(coll, new_key, body, meta)
        if not dry:
            cmeta = dict(canon.get("meta") or {})
            cmeta["status"] = ["superseded"]
            cmeta["superseded_by"] = [new_key]
            update_meta(mddb, coll, ckey, cmeta,
                        canon.get("contentMd") or "")
            dmeta = dict(draft.get("meta") or {})
            dmeta["status"] = ["superseded"]
            dmeta["superseded_by"] = [new_key]
            dmeta["merge_review"] = ["applied"]
            update_meta(mddb, coll, dkey, dmeta,
                        draft.get("contentMd") or "")
        print(f"{pid}: new canonical {new_key} supersedes {ckey}; "
              f"draft {dkey} superseded")

    pair["status"] = "rejected" if action == "reject" else "applied"
    pair["resolved_at"] = today
    pair["resolved_by"] = actor
    pair["resolution"] = action
    return 0


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=MDDB_BANKS)
    ap.add_argument("--instance", help="limit to banks visible to instance")
    ap.add_argument("--bank", action="append",
                    help="limit to bank name(s)")
    ap.add_argument("--draft-days", type=int, default=DRAFT_DAYS,
                    help="only extract drafts newer than N days")
    ap.add_argument("--max-proposals", type=int, default=MAX_PROPOSALS)
    ap.add_argument("--resolve", metavar="ID",
                    help="apply a decision to proposal merge-XXXXXXXX")
    ap.add_argument("--action",
                    choices=["update-in-place", "supersede", "reject"])
    ap.add_argument("--text", help="approved wording (update-in-place)")
    ap.add_argument("--actor", default=os.environ.get("USER") or "human",
                    help="who approved (stamped in provenance)")
    ap.add_argument("--list-pending", action="store_true")
    ap.add_argument("--no-publish", action="store_true",
                    help="skip CMS page + card comment")
    ap.add_argument("--emit", action="store_true",
                    help="chaba-event when proposals are open")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    state = load_state()
    mddb = ada_sync.Mddb(args.mddb, timeout=120)

    if args.list_pending:
        for pid, p in sorted((state.get("pairs") or {}).items()):
            if p.get("status") == "proposed":
                print(f"{pid}  {p.get('action', '?'):<15} "
                      f"{p['collection']}:{p['canonical']} <- {p['draft']}")
        return 0

    if args.resolve:
        if not args.action:
            ap.error("--resolve requires --action")
        rc = resolve(mddb, state, args.resolve, args.action, args.text,
                     args.actor, args.dry_run)
        if rc == 0 and not args.dry_run:
            save_state(state)
        return rc

    proposals, stats, docs_by_coll = propose(mddb, args)
    reconcile(state, docs_by_coll)

    today = date.today().isoformat()
    pairs = state.setdefault("pairs", {})
    new = 0
    for p in proposals:
        if p["id"] in pairs and pairs[p["id"]].get("status") == "proposed":
            continue  # already open
        if p["id"] in pairs and pairs[p["id"]].get("status") in (
                "applied", "rejected"):
            continue  # decided — never re-propose
        pairs[p["id"]] = {k: p[k] for k in
                          ("collection", "bank", "canonical", "draft",
                           "action", "score")}
        pairs[p["id"]].update({"proposed_at": today, "status": "proposed"})
        new += 1
    acc = acceptance(state)

    errors = sum(s.get("search_errors", 0) for s in stats.values())
    runs = state.setdefault("runs", [])
    runs.append({"ts": datetime.now(timezone.utc)
                 .isoformat(timespec="seconds"),
                 "proposals": len(proposals), "new": new,
                 "pending": acc["pending"], "search_errors": errors})
    state["runs"] = runs[-52:]

    metric = (f"merge-proposals: {len(proposals)} open "
              f"({new} new), pending={acc['pending']}, "
              f"acceptance90d={acc['window_rate']}, "
              f"lifetime={acc['lifetime']}, search_errors={errors}")
    print(metric)
    for coll, s in sorted(stats.items()):
        print(f"  {coll}: {s['drafts']} draft(s), "
              f"{s['canonicals']} canonical(s)"
              + (f", {s['search_errors']} search error(s)"
                 if s.get("search_errors") else ""))
    for p in proposals:
        print(f"  {p['id']} {p['action']:<15} {p['score']:.2f} "
              f"{p['collection']}:{p['canonical']} <- {p['draft']}")

    if not args.no_publish:
        now = datetime.now(timezone.utc)
        block = report_block(proposals, stats, acc, now,
                             draft_days=args.draft_days)
        publish_report(block, now, args.dry_run)
        summary = (
            f"weekly merge-proposals run: {len(proposals)} open "
            f"proposal(s) ({new} new) across {sum(s['drafts'] for s in stats.values())} "
            f"recent extract draft(s). Pending decisions: {acc['pending']}. "
            + (f"⚠ {errors} vector-search call(s) failed — embed chain "
               "degraded, proposals are a lower bound. " if errors else "")
            + f"Report: ada-cms-pages/{PAGE}. Resolve via "
            f"memory-merge-proposals.py --resolve <id> --action …"
            + (" [dry-run]" if args.dry_run else ""))
        if not args.dry_run:
            card_comment(summary)
    if args.dry_run:
        return 0
    if args.emit and proposals:
        emit_event(
            f"Ada memory: {len(proposals)} merge proposal(s) await review",
            f"{new} new proposal(s); {acc['pending']} pending decision(s). "
            f"See ada-cms-pages/{PAGE}.",
            requires_response=True)
    try:
        chaba_event.send({"kind": "job-result",
                          "job": "memory-merge-proposals",
                          "summary": metric})
    except Exception:
        pass
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
