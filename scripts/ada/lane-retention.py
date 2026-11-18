#!/usr/bin/env python3
"""lane-retention.py — weekly per-lane Ada retention job.

Card ada-transcript-archive-retention. Three duties for one Ada lane:

1. Transcript deep-archive — raw voice transcripts
   (~/.local/share/ada/transcripts/*.md on the lane's host(s)) are pushed
   to the lane's NotebookLM notebook, the append-only deep-archive tier
   (docs/ada-memory/README.md tier 3), before the implicit ~5d source
   loss can drop them. Per-session uploads used to run inside ada-voice
   but died with the notebooklm-rest service; this job is the durable
   replacement. Lane attribution: filename <date>-<sid>.md -> journalctl
   --user 'session=<sid>' on that host. Sessions with no lane attribution
   remain local and are skipped rather than assigned to another person's
   notebook. Dedup is a local state file + a deterministic title scan of
   the notebook — re-runs never re-upload.

2. Ops TTL — ada-ha-events-<lane> / ada-ha-snapshots-<lane> swept at 30d
   on BOTH the ada-ops store (mddb-ops :11025) and the leader (:11023);
   kk/dev lanes still emit on the leader. Implemented via
   prune-old-docs.sweep() so the paging/chunking safeguards are shared.

3. Extract supersede-merge — extract-* docs (status draft|active) in the
   writable bank collections, claimed by meta.scope, are grouped by
   subject and merged by Gemini into a canonical <bank>/<slug> doc
   (distill-devin-bank.py conventions: sources get status=superseded +
   superseded_by=<canonical key>, canonical carries source_keys
   provenance). Merging into an existing canonical keeps its status; a
   NEW canonical is active only when every merged extract was already
   active (otherwise draft — preserves the human-review gate; board
   request 4-policy-defaults-686e16).

Usage:
  lane-retention.py --lane tony --include-shared   # weekly, all duties
  lane-retention.py --lane kk --dry-run
  lane-retention.py --lane tony --transcripts-only | --ops-only | --extracts-only

Env: GEMINI_API_KEY (extract merge; job env_file provides it, or the
     LiteLLM gateway via GEMINI_BASE_URL), ADA_SUMMARY_MODEL,
     MDDB_ADA_OPS_URL (ops sweep, via prune-old-docs), ADA_MEMORY_MDDB_URL
     (banks + lane sid maps), NLM_HOST/NLM_CONTAINER (default mn01 /
     notebooklm-mcp), BOARD_API (card comment base),
     ADA_TRANSCRIPT_DIR (default $HOME/.local/share/ada/transcripts),
     LANE_RETENTION_STATE (dedup state file).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ada_sync = _load("ada_sync", HERE / "sync-ada-memory-to-mddb.py")
prune = _load("prune_old_docs", HERE / "prune-old-docs.py")
import chaba_event  # noqa: E402
import gemini_rest  # noqa: E402

MDDB = os.environ.get("ADA_MEMORY_MDDB_URL",
                      "http://100.102.134.91:11023/v1").rstrip("/")
NLM_HOST = os.environ.get("NLM_HOST", "mn01")
NLM_CONTAINER = os.environ.get("NLM_CONTAINER", "notebooklm-mcp")
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
CARD_ID = "ada-transcript-archive-retention"
STATE = Path(os.environ.get(
    "LANE_RETENTION_STATE",
    Path.home() / ".cache/ada-lane-retention.json"))
MODEL = os.environ.get("ADA_SUMMARY_MODEL", "gemini-3.5-flash-lite")
# used inside double quotes on the remote so $HOME still expands —
# single-quoting '~' would pass it literally and find would miss
TRANSCRIPT_DIR = os.environ.get(
    "ADA_TRANSCRIPT_DIR", "$HOME/.local/share/ada/transcripts")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]

# Tony — Memory (shared household archive). Lane→notebook follows the
# same mapping ada-voice's per-session upload used (lane env
# NOTEBOOKLM_MEMORY_NOTEBOOK_ID); michael keeps his own notebook.
NB_MEMORY = "663ef269-4513-4241-9775-bb220e22535a"
NB_MICHAEL = "1c12d5c8-cd31-47ef-841b-528b0a89ba09"

# lane -> transcript hosts + the journald units and MDDB collections
# that attribute session ids to it. sid attribution is the ONLY lane
# signal on multi-lane hosts (one shared transcript dir): a file's
# <date>-<sid>.md stem matches meta.session_id in the lane's
# recall-summary/actions collections (journald 'session=' lines are a
# sparse bonus). Sessions without a reliable lane claim are skipped.
LANES = {
    "tony": {
        "hosts": ["idc03", "mn01"],
        "units": {"idc03": ["ada-ha-tony"], "mn01": ["ada-ha-tony"]},
        "sid_collections": ["ada-ha-recall-summary-tony",
                            "ada-ha-actions-tony"],
        "notebook": NB_MEMORY,
        "scopes": {"tony"},
        "collections": ["ada-ha-events-tony", "ada-ha-snapshots-tony"],
    },
    "kk": {
        "hosts": ["idc03"],
        "units": {"idc03": ["ada-kk"]},
        "sid_collections": ["ada-ha-recall-summary-kk",
                            "ada-ha-actions-kk"],
        "notebook": NB_MEMORY,
        "scopes": {"kk"},
        "collections": ["ada-ha-events-kk", "ada-ha-snapshots-kk"],
    },
    "michael": {
        "hosts": ["idc03", "mn01"],
        "units": {"idc03": ["ada-ai-kraut"], "mn01": ["ada-ha-michael"]},
        "sid_collections": ["ada-ha-recall-summary-michael",
                            "ada-ha-actions-michael"],
        "notebook": NB_MICHAEL,
        "scopes": {"michael"},
        "collections": ["ada-ha-events-michael",
                        "ada-ha-snapshots-michael"],
    },
    "chaba": {
        "hosts": ["idc03"],
        "units": {"idc03": ["ada-chaba"]},
        "sid_collections": ["ada-ha-recall-summary-chaba",
                            "ada-ha-actions-chaba"],
        "notebook": NB_MEMORY,
        "scopes": set(),  # no bank scope — transcripts + ops only
        "collections": ["ada-ha-events-chaba", "ada-ha-snapshots-chaba"],
    },
    "dev": {
        # Confirmed dev lanes + ada-pi-pwa — Tony classified pi-pwa as dev
        # 2026-11-18 (supersedes the earlier 'exclude' answer). pi-pwa ran
        # with ADA_INSTANCE_ID=tony so its recall sids live in tony's
        # collections; the unit's journald is the ONLY dev-attributing
        # signal, which is why the dev timer runs BEFORE tony's — a sid
        # visible to both claims dev, matching the decision.
        "hosts": ["idc03"],
        "units": {"idc03": ["ada-dev", "ada-kk-dev", "ada-pi-pwa"]},
        "sid_collections": ["ada-ha-recall-summary-dev",
                            "ada-ha-actions-dev",
                            "ada-ha-recall-summary-kk-dev"],
        "notebook": NB_MEMORY,
        "scopes": set(),  # dev extract noise isn't canonical memory
        "collections": ["ada-ha-events-dev", "ada-ha-snapshots-dev",
                        "ada-ha-events-kk-dev", "ada-ha-snapshots-kk-dev"],
    },
}

# 'shared' / unset / 'instance' scopes are claimed by whichever lane runs
# with --include-shared (tony, owner of the shared banks' review flow).
SHARED_SCOPES = {"shared", "instance", ""}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"transcripts": {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(STATE)


def mval(doc: dict, key: str) -> str:
    v = (doc.get("meta") or {}).get(key)
    return (v[0] if isinstance(v, list) and v else v) or ""


# ---------------------------------------------------------------- transcripts

FN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{6,})\.md$")


def journal_sids(host: str, units: list[str],
                 since_days: int = 150) -> set[str]:
    """session=<hex> ids emitted by this lane's units on a host.
    Sparse in practice (the backends barely log the id) — a bonus
    signal on top of lane_sids, not the primary map."""
    sids: set[str] = set()
    for unit in units:
        try:
            r = subprocess.run(
                SSH + [host, "journalctl", "--user", "-u", unit,
                       "--since", f"{since_days} days ago",
                       "-o", "cat", "--no-pager"],
                capture_output=True, text=True, timeout=180)
            sids.update(re.findall(r"session=([0-9a-f]{6,})", r.stdout))
        except subprocess.TimeoutExpired:
            log(f"  ! journalctl {unit}@{host} timed out")
    return sids


def mddb_search(collection: str, limit: int = 5000,
                base: str = MDDB) -> list[dict]:
    req = urllib.request.Request(
        f"{base}/search",
        data=json.dumps({"collection": collection,
                         "limit": limit}).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def lane_sids(cfg: dict) -> set[str]:
    """Session ids attributed to this lane via its MDDB
    recall-summary/actions collections — the durable lane->sid map."""
    sids: set[str] = set()
    for coll in cfg.get("sid_collections") or []:
        try:
            for d in mddb_search(coll):
                sid = mval(d, "session_id")
                if sid:
                    sids.add(sid)
        except Exception as e:
            log(f"  ! {coll}: sid list failed — {e}")
    return sids


def list_transcripts(host: str) -> list[tuple[str, str]]:
    """[(filename, date)] for *.md in the transcript dir on a host."""
    try:
        r = subprocess.run(
            SSH + [host, f'find "{TRANSCRIPT_DIR}" -maxdepth 1 '
                         "-name '*.md' -printf '%f\\n' 2>/dev/null"],
            capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        log(f"  ! ls {host} timed out")
        return []
    if r.returncode != 0:
        log(f"  ! ls {host}: {r.stderr.strip()[:150]}")
        return []
    out = []
    for name in r.stdout.split():
        m = FN_RE.match(name)
        if m:
            out.append((name, m.group(1)))
    return out


def fetch_transcript(host: str, fname: str) -> str | None:
    try:
        r = subprocess.run(
            SSH + [host, f'cat "{TRANSCRIPT_DIR}/{fname}"'],
            capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def nlm_remote(args: list[str], timeout: int = 360) -> subprocess.CompletedProcess:
    return subprocess.run(
        SSH + [NLM_HOST, "podman exec -i "
               f"{shlex.quote(NLM_CONTAINER)} nlm "
               + " ".join(shlex.quote(a) for a in args)],
        capture_output=True, text=True, timeout=timeout)


def notebook_titles(notebook: str) -> set[str]:
    try:
        r = nlm_remote(["source", "list", notebook, "--json"], timeout=120)
        return {s.get("title", "") for s in json.loads(r.stdout)}
    except Exception as e:
        log(f"  ! nlm source list failed ({e}) — dedup falls back to state")
        return set()


def nlm_add_text(notebook: str, title: str, text: str) -> str | None:
    """Upload; returns source id (or '?' when --json parse fails)."""
    r = nlm_remote(["source", "add", notebook, "--text", text,
                    "--title", title, "--wait", "--wait-timeout", "300",
                    "--json"], timeout=360)
    if r.returncode != 0:
        log(f"  ! nlm add {title}: rc={r.returncode} "
            f"{(r.stderr or r.stdout).strip()[:200]}")
        return None
    try:
        d = json.loads(r.stdout)
        return str(d.get("id") or "?")
    except Exception:
        return "?"


def archive_transcripts(lane: str, cfg: dict, args,
                        state: dict) -> tuple[int, int]:
    """Returns (uploaded, skipped)."""
    done = state.setdefault("transcripts", {})
    cutoff = (datetime.now(timezone.utc) -
              timedelta(days=args.min_age_days)).date().isoformat()
    titles = notebook_titles(cfg["notebook"]) if not args.dry_run else set()
    # union of MDDB session ids + the sparse journald signal
    sids = lane_sids(cfg)
    for host, units in (cfg.get("units") or {}).items():
        sids |= journal_sids(host, units)
    uploaded = skipped = 0
    for host in cfg["hosts"]:
        for fname, fdate in sorted(list_transcripts(host)):
            if fdate > cutoff:
                continue
            sid = FN_RE.match(fname).group(2)
            claimed = sid in sids
            tag = f"{host}/{fname}"
            if not claimed:
                skipped += 1
                log(f"  ~ skip {tag} (no lane attribution; remains local)")
                continue
            title = f"Ada transcript {fdate} {sid} ({lane})"
            if tag in done or title in titles:
                skipped += 1
                continue
            if args.dry_run:
                log(f"  ~ archive {tag} -> '{title}'")
                uploaded += 1
                continue
            text = fetch_transcript(host, fname)
            if not text or not text.strip():
                log(f"  ! {tag}: unreadable, skipping")
                continue
            sha = hashlib.sha256(text.encode()).hexdigest()[:12]
            src_id = nlm_add_text(cfg["notebook"], title, text)
            if src_id is None:
                continue  # retry next week; nothing recorded
            done[tag] = {"notebook": cfg["notebook"], "title": title,
                         "source_id": src_id, "sha": sha,
                         "at": datetime.now(timezone.utc).isoformat(
                             timespec="seconds")}
            save_state(state)
            titles.add(title)
            uploaded += 1
            log(f"  + archived {tag} -> {title} ({len(text)}b)")
            if uploaded >= args.max_per_run:
                log(f"  ! cap --max-per-run={args.max_per_run} reached")
                return uploaded, skipped
    return uploaded, skipped


# ------------------------------------------------------------------- ops TTL

def sweep_ops(cfg: dict, dry: bool) -> list[str]:
    out = []
    for coll in cfg["collections"]:
        if coll not in prune.POLICY:
            continue
        ts_key, days = prune.POLICY[coll]
        for base in prune.collection_bases(coll):
            out.append(prune.sweep(coll, ts_key, days, dry, base))
    return out


# -------------------------------------------------------------- extract merge

def slugify(s: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    # non-latin subjects slug to '' — hash keeps them unique instead of
    # collapsing every Thai subject onto bank/misc
    return slug[:60] or "s-" + hashlib.sha1(s.encode()).hexdigest()[:8]


def llm_slug(subject: str) -> str | None:
    """Ask the merge model for an ASCII slug (Thai subjects included)."""
    try:
        d = gemini_rest.generate_json(
            "Return {\"slug\": \"<short-ascii-kebab-slug>\"} for this Ada "
            f"memory subject: {subject!r}", MODEL,
            tags="job=lane-retention,step=slug")
        slug = re.sub(r"[^a-z0-9]+", "-",
                      str(d.get("slug") or "").lower()).strip("-")
        return slug[:60] or None
    except Exception:
        return None


def merge_prompt(subject: str, members: list[dict],
                 canonical: dict | None) -> str:
    parts = [
        "You consolidate memory notes for Ada, a voice assistant. Merge "
        "the extracted candidate notes below about subject "
        f'"{subject}" into ONE canonical markdown fact sheet.',
        "Rules: keep the source languages verbatim (Thai stays Thai); "
        "deduplicate; on conflict the NEWEST dated note wins; keep "
        "concrete details (names, dates, plates, amounts, model names); "
        "output ONLY the merged markdown body — no preamble, no "
        "frontmatter, no explanation.",
    ]
    if canonical is not None:
        parts += ["", "EXISTING CANONICAL DOC (extend it, keep its voice):",
                  (canonical.get("contentMd") or "")[:6000]]
    parts += ["", "EXTRACTED NOTES:"]
    for d in members:
        parts += [f"--- {d['key']} (valid_from "
                  f"{mval(d, 'valid_from') or '?'}, "
                  f"status {mval(d, 'status')}) ---",
                  (d.get("contentMd") or "")[:3000]]
    return "\n".join(parts)


def base_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def merge_extracts(cfg: dict, scopes: set[str], args) -> tuple[int, int]:
    """Returns (groups_merged, docs_superseded)."""
    mddb = ada_sync.Mddb(MDDB)
    merged = superseded = 0
    seen_colls: set[str] = set()
    for entry in ada_sync.load_bank_map():
        if not entry["writable"] or not entry["collection"]:
            continue
        coll = entry["collection"]
        # the bank map lists ada-ha-bank-personal-<i> twice (once via
        # multi-instance 'personal', once via 'personal-<i>' person
        # bank) — one pass per collection
        if coll in seen_colls:
            continue
        seen_colls.add(coll)
        try:
            docs = mddb.list_docs(coll)
        except Exception as e:
            log(f"  ! {coll}: list failed — {e}")
            continue
        candidates = defaultdict(list)
        canon_by_subject, canon_by_key = {}, {}
        for d in docs:
            key = d.get("key", "")
            if key.startswith("extract-"):
                if (mval(d, "status") in ("draft", "active")
                        and mval(d, "scope") in scopes):
                    # group by normalized subject so 'language
                    # preference' and 'language-preference' merge; Thai
                    # subjects have no slug so they group verbatim
                    subj = mval(d, "subject") or key
                    candidates[base_slug(subj) or subj].append(d)
            else:
                subj = mval(d, "subject")
                if subj:
                    norm = base_slug(subj) or subj
                    # several docs can share a subject slug — prefer an
                    # explicitly-active one over draft/legacy entries
                    cur = canon_by_subject.get(norm)
                    if cur is None or (mval(cur, "status") != "active"
                                       and mval(d, "status") == "active"):
                        canon_by_subject[norm] = d
                canon_by_key[key] = d
        groups = sorted(candidates.items(),
                        key=lambda kv: -len(kv[1]))[:args.max_groups]
        for gkey, members in groups:
            # bank comes from the docs themselves (registry maps
            # personal-* collections under both 'personal' and
            # 'personal-<i>' — meta.bank is authoritative)
            bank = Counter(mval(m, "bank") or entry["bank"]
                           for m in members).most_common(1)[0][0]
            subject = Counter(mval(m, "subject") for m in members
                              ).most_common(1)[0][0] or gkey
            member_scope = Counter(mval(m, "scope") for m in members
                                   ).most_common(1)[0][0] or "shared"
            def live(doc):
                """doc -> doc, its superseded_by target, or None.
                Only an explicit superseded/retracted status kills a
                canonical — authored docs often carry no status field."""
                for _ in range(2):      # one hop is enough in practice
                    if doc is None:
                        return None
                    if mval(doc, "status") not in ("superseded",
                                                   "retracted"):
                        return doc
                    doc = canon_by_key.get(mval(doc, "superseded_by"))
                return None

            canon = (live(canon_by_subject.get(gkey))
                     or live(canon_by_key.get(f"{bank}/{gkey}")))
            # scope gate: folding lane-scoped extracts into a shared
            # canonical would leak one lane's facts to every lane —
            # those groups wait for human review instead
            if canon is not None:
                cs = mval(canon, "scope") or "shared"
                sharedish = member_scope in SHARED_SCOPES
                if cs != member_scope and not (cs == "shared"
                                             and sharedish):
                    log(f"  ~ {coll} {subject!r}: canon scope {cs} != "
                        f"{member_scope} — skipped for review")
                    continue
            # a lone extract keeps waiting for siblings unless a
            # canonical already exists to fold it into
            if len(members) < 2 and canon is None \
                    and not args.merge_singletons:
                continue
            if canon is not None:
                canon_key = canon["key"]
                new_status = mval(canon, "status")
            else:
                slug = base_slug(subject)
                if not slug:            # non-latin subject — ask the model
                    slug = llm_slug(subject) or slugify(subject)
                    if f"{bank}/{slug}" in canon_by_key:
                        slug = slugify(subject)   # hashed fallback is free
                canon_key = f"{bank}/{slug}"
                new_status = ("active" if all(
                    mval(m, "status") == "active" for m in members)
                    else "draft")
            if args.dry_run:
                log(f"  ~ {coll}: {subject!r} — merge "
                    f"{len(members)} extract(s) -> {canon_key} "
                    f"({'update' if canon else 'create'}, {new_status})")
                merged += 1
                continue
            body = gemini_rest.generate(
                merge_prompt(subject, members, canon), MODEL,
                tags=f"job=lane-retention,lane={args.lane}",
                litellm_metadata={"job": "lane-retention",
                                  "lane": args.lane, "bank": bank})
            if not body or len(body.strip()) < 10:
                log(f"  ! {coll} {subject!r}: LLM merge empty — skipped "
                    f"(sources kept)")
                continue
            src_keys = [m["key"] for m in members]
            if canon is not None:
                meta = dict(canon.get("meta") or {})
                prev = meta.get("source_keys") or []
                meta["source_keys"] = sorted(set(prev) | set(src_keys))
                meta["last_verified"] = [datetime.now(
                    timezone.utc).date().isoformat()]
                mddb.add(coll, canon_key, body.strip(), meta)
                canon["meta"] = meta           # next group sees fresh
                canon["contentMd"] = body.strip()
            else:
                kinds = Counter(mval(m, "kind") or "fact"
                                for m in members)
                today = datetime.now(timezone.utc).date().isoformat()
                meta = {
                    "bank": [bank], "key": [canon_key],
                    "kind": [kinds.most_common(1)[0][0]],
                    "scope": [member_scope],
                    "subject": [subject], "status": [new_status],
                    "source": ["extract"],
                    "origin_source": ["extract"],
                    "written_by": ["lane-retention"],
                    "valid_from": [min(
                        (v for m in members
                         if (v := mval(m, "valid_from"))), default=today)],
                    "last_verified": [today],
                    "source_keys": sorted(src_keys),
                }
                mddb.add(coll, canon_key, body.strip(), meta)
                # later groups normalizing to the same slug must update
                # this doc, not overwrite it with their own merge
                canon_by_key[canon_key] = {
                    "key": canon_key, "meta": meta,
                    "contentMd": body.strip()}
                canon_by_subject[gkey] = canon_by_key[canon_key]
            fails = 0
            for m in members:
                try:
                    meta = dict(m.get("meta") or {})
                    meta["status"] = ["superseded"]
                    meta["superseded_by"] = [canon_key]
                    r = mddb.s.patch(
                        f"{mddb.base}/update",
                        json={"collection": coll, "key": m["key"],
                              "lang": m.get("lang", "en"), "meta": meta},
                        timeout=mddb.timeout)
                    if r.status_code != 200:
                        mddb.add(coll, m["key"],
                                 m.get("contentMd") or "", meta)
                except Exception as exc:
                    fails += 1
                    log(f"    ! supersede {m['key']} failed: {exc}")
            superseded += len(members) - fails
            merged += 1
            log(f"  + {coll} {subject!r}: {len(members)} extract(s) -> "
                f"{canon_key} ({new_status})")
            if merged >= args.max_groups:
                log(f"  ! --max-groups={args.max_groups} reached — "
                    f"remainder waits for next week")
                return merged, superseded
    return merged, superseded


# ------------------------------------------------------------------- comms

def ops_event(lane: str, detail: str) -> None:
    """kanban-dispatch-shaped ops-event into ada-ha-events-<lane>."""
    now = datetime.now(timezone.utc)
    try:
        req = urllib.request.Request(
            f"{prune.ADA_OPS_MDB}/add",
            data=json.dumps({
                "collection": f"ada-ha-events-{lane}",
                "key": f"ops-lane-retention-{now:%Y%m%d%H%M%S%f}",
                "lang": "en", "contentMd": detail,
                "meta": {"kind": ["ops-event"], "type": ["lane_retention"],
                         "instance": [lane],
                         "ts": [now.isoformat(timespec="seconds")],
                         "written_by": ["lane-retention"]}}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log(f"  ! ops event failed: {e}")


def card_comment(text: str) -> None:
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/comment",
            data=json.dumps({"id": CARD_ID, "from": "chaba",
                             "text": text[:900]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        log(f"  ! card comment failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lane", required=True, choices=sorted(LANES))
    ap.add_argument("--include-shared", action="store_true",
                    help="also claim shared/instance/unset extract scopes")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-age-days", type=int, default=2,
                    help="archive transcripts older than this (default 2d "
                         "— weekly cadence keeps worst case < ~9d)")
    ap.add_argument("--max-per-run", type=int, default=500,
                    help="cap transcript uploads per run (500 covers the "
                         "one-time backlog; steady state is ~7/wk)")
    ap.add_argument("--max-groups", type=int, default=25,
                    help="cap extract merge groups per run (LLM budget)")
    ap.add_argument("--merge-singletons", action="store_true",
                    help="merge single-extract subjects too")
    only = ap.add_mutually_exclusive_group()
    only.add_argument("--transcripts-only", action="store_true")
    only.add_argument("--ops-only", action="store_true")
    only.add_argument("--extracts-only", action="store_true")
    args = ap.parse_args()

    cfg = LANES[args.lane]
    lane = args.lane
    state = load_state()
    dry_tag = "DRY " if args.dry_run else ""
    log(f"lane-retention {dry_tag}lane={lane} at "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}")

    up = skip = merged = sup = 0
    sweeps: list[str] = []

    if not (args.ops_only or args.extracts_only):
        log("== transcripts -> NotebookLM ==")
        try:
            up, skip = archive_transcripts(lane, cfg, args, state)
        except Exception as e:
            log(f"  ! transcript phase failed: {e}")

    if not (args.transcripts_only or args.extracts_only):
        log("== ops TTL sweep ==")
        try:
            sweeps = sweep_ops(cfg, args.dry_run)
            for line in sweeps:
                log(f"  {line}")
        except Exception as e:
            log(f"  ! ops sweep failed: {e}")

    scopes = set(cfg["scopes"])
    if args.include_shared:
        scopes |= SHARED_SCOPES
    if scopes and not (args.transcripts_only or args.ops_only):
        log(f"== extract merge (scopes {sorted(scopes)}) ==")
        try:
            merged, sup = merge_extracts(cfg, scopes, args)
        except Exception as e:
            log(f"  ! extract merge failed: {e}")

    pruned = sum(int(m.group(1)) for line in sweeps
                 if (m := re.search(r"deleted (\d+)/", line)))
    summary = (f"weekly lane-retention {lane}: {up} transcript(s) -> NLM "
               f"({skip} skipped), {pruned} ops docs swept (30d), "
               f"{merged} extract group(s) -> canonical, {sup} superseded"
               f"{' [dry-run]' if args.dry_run else ''}")
    log("== " + summary)
    if not args.dry_run:
        card_comment(summary)
        ops_event(lane, summary)
        chaba_event.send({"kind": "job-result", "job": "lane-retention",
                          "lane": lane, "summary": summary})
    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
