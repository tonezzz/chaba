#!/usr/bin/env python3
"""session_recall.py — hybrid T1/T2 session recall for the Devin
SessionStart hook (card distiller-enrich-productionize; bench evidence
reports/bench-recall-v2-20261022.md: T1 semantic alone = 66.7% hit@3,
hybrid T1 + T2 transcript keyword = 91.7%).

T1 (semantic): mddb /v1/vector-search over ada-ha-bank-devin-tony —
the enriched devin-session/* docs (summary + deterministic ## Artifacts
section written by sync-devin-summaries.py --enrich).

T2 (keyword): sqlite FTS5 (BM25) over locally grep-able transcript .md
archives — the T2 dumps sync-devin-summaries.py writes to
~/.local/share/devin/transcripts/, plus the existing CLI thread dumps
(~/.local/share/devin/cli/summaries/history_*.md) and desktop summaries
(~/.local/share/devin/summaries/*.md). The index is incremental
(mtime+size per file) and disk-backed — deliberately NOT the in-memory
BM25 bench-recall.py uses, which is what OOM-killed a dispatch host.

Fail-open everywhere: mddb unreachable, sessions.db locked, FTS5
missing, empty archives — whatever lanes answer, never raise into the
hook. Every lane is time-bounded.

Usage:
  session_recall.py "query"                  # context block on stdout
  session_recall.py --session ID "query"     # title from sessions.db
                                             # prepended to the query
  session_recall.py --project NAME "query"   # fallback query scope
  session_recall.py --json "query"           # {query, t1, t2} JSON
  session_recall.py --reindex                # rebuild stats, no recall

Env: MDDB_RECALL_URL (default http://100.102.134.91:11023/v1),
     MDDB_RECALL_TIMEOUT (default 8s),
     DEVIN_TRANSCRIPT_DIR (default ~/.local/share/devin/transcripts),
     DEVIN_RECALL_INDEX (default ~/.local/share/devin/session-recall/
     index.db), SESSION_RECALL_INDEX_BUDGET (seconds of indexing per
     call, default 45 — first run on a big archive catches up over
     successive hook fires).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

COLLECTION = "ada-ha-bank-devin-tony"
MDDB_URL = os.environ.get(
    "MDDB_RECALL_URL", "http://100.102.134.91:11023/v1").rstrip("/")
MDDB_TIMEOUT = float(os.environ.get("MDDB_RECALL_TIMEOUT", "8"))
HOME = Path.home()
SESSIONS_DB = Path(os.environ.get(
    "SESSIONS_DB", HOME / ".local/share/devin/cli/sessions.db"))
TRANSCRIPT_DIR = Path(os.environ.get(
    "DEVIN_TRANSCRIPT_DIR", HOME / ".local/share/devin/transcripts"))
ARCHIVE_DIRS = [
    TRANSCRIPT_DIR,
    HOME / ".local/share/devin/cli/summaries",
    HOME / ".local/share/devin/summaries",
]
INDEX_DB = Path(os.environ.get(
    "DEVIN_RECALL_INDEX",
    HOME / ".local/share/devin/session-recall/index.db"))
INDEX_BUDGET = float(os.environ.get("SESSION_RECALL_INDEX_BUDGET", "45"))

T1_TOPK = 6
T1_THRESHOLD = 0.45
T2_TOPK = 8
CHUNK = 1800
CHUNK_OVERLAP = 200
MAX_CHARS = 4000          # hybrid block cap inside the hook's context
T1_SNIPPET = 350
T2_TERMS = 16

_TOKEN_RE = re.compile(r"[a-z0-9_./:-]{2,}")
# FTS5 OR-query would let these match every chunk and just burn terms.
_STOP = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "had", "her", "was", "one", "our", "out", "has", "have", "with",
    "this", "that", "from", "they", "been", "were", "said", "each",
    "which", "their", "will", "about", "would", "there", "could",
    "other", "into", "than", "then", "them", "these", "when", "what",
    "your", "session", "devin", "https", "http", "www", "com",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower())
            if t not in _STOP]


def _chunks(text: str):
    i = 0
    while i < len(text):
        c = text[i:i + CHUNK]
        if c.strip():
            yield c
        i += CHUNK - CHUNK_OVERLAP


def _archive_files() -> list[Path]:
    files = []
    for d in ARCHIVE_DIRS:
        try:
            files.extend(sorted(d.glob("*.md")))
        except OSError:
            continue
    return files


def open_index() -> sqlite3.Connection:
    INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(INDEX_DB), timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS files("
        "path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
        "session UNINDEXED, path UNINDEXED, text, "
        "tokenize='porter unicode61')")
    return con


def index_archives(con: sqlite3.Connection,
                   budget: float = INDEX_BUDGET) -> dict:
    """Incremental FTS5 index over the archive dirs. Re-indexes only files
    whose (mtime, size) changed; drops rows for vanished files. Returns
    stats; stops early when `budget` seconds elapse (remaining files are
    picked up by the next call)."""
    t0 = time.time()
    stats = {"indexed": 0, "fresh": 0, "removed": 0, "pending": 0}
    all_files = _archive_files()
    seen = {str(p) for p in all_files}
    for path in all_files:
        if time.time() - t0 > budget:
            stats["pending"] += 1
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        row = con.execute(
            "SELECT mtime, size FROM files WHERE path=?", (key,)).fetchone()
        if row and row[0] == st.st_mtime and row[1] == st.st_size:
            stats["fresh"] += 1
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        session = path.stem
        try:
            con.execute("DELETE FROM chunks WHERE path=?", (key,))
            con.executemany(
                "INSERT INTO chunks(session, path, text) VALUES (?,?,?)",
                [(session, key, c) for c in _chunks(text)])
            con.execute(
                "INSERT OR REPLACE INTO files(path, mtime, size) "
                "VALUES (?,?,?)", (key, st.st_mtime, st.st_size))
            con.commit()
        except Exception:
            con.rollback()
            raise
        stats["indexed"] += 1
    # files deleted from disk lose their chunks — `seen` covers every
    # file on disk, including ones the budget skipped this call
    stale = [r[0] for r in con.execute("SELECT path FROM files")
             if r[0] not in seen]
    for p in stale:
        con.execute("DELETE FROM chunks WHERE path=?", (p,))
        con.execute("DELETE FROM files WHERE path=?", (p,))
        stats["removed"] += 1
    con.commit()
    return stats


def fts_query(query: str) -> str:
    """OR-query of quoted tokens for FTS5 MATCH; '' when nothing usable."""
    terms = tokenize(query)[:T2_TERMS]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


def recall_t2(con: sqlite3.Connection, query: str,
              top_k: int = T2_TOPK) -> list[dict]:
    """BM25-ranked chunk hits; [] on any failure (fail-open)."""
    mq = fts_query(query)
    if not mq:
        return []
    try:
        rows = con.execute(
            "SELECT session, path, "
            "snippet(chunks, 2, '<<', '>>', '…', 48) AS snip, "
            "bm25(chunks) AS rank "
            "FROM chunks WHERE chunks MATCH ? "
            "ORDER BY rank LIMIT ?", (mq, top_k)).fetchall()
    except sqlite3.Error:
        return []
    return [{"session": s, "path": p, "snippet": sn,
             "rank": round(r, 4)} for s, p, sn, r in rows]


def recall_t1(query: str, top_k: int = T1_TOPK) -> list[dict]:
    """mddb /v1/vector-search on the devin bank; [] on any failure."""
    payload = {"collection": COLLECTION, "query": query, "topK": top_k,
               "includeContent": True, "threshold": T1_THRESHOLD,
               "filterMeta": {"status": ["active"]}}
    req = urllib.request.Request(
        f"{MDDB_URL}/vector-search",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=MDDB_TIMEOUT) as r:
            results = json.loads(r.read()).get("results") or []
    except Exception:
        return []
    out = []
    for h in results:
        doc = h.get("document") or {}
        out.append({"key": doc.get("key"), "score": h.get("score"),
                    "content": doc.get("contentMd")
                    or doc.get("content_md") or ""})
    # devin-session/<name> distilled summaries read cleaner than devin/<hex>
    # raw transcript dumps — surface them first; the set is unchanged.
    out.sort(key=lambda h: 0 if (h.get("key") or "").startswith(
        "devin-session/") else 1)
    return out


def session_title(session_id: str) -> str:
    """Title of a sessions.db session — the best free recall query."""
    if not session_id or not SESSIONS_DB.exists():
        return ""
    try:
        db = sqlite3.connect(f"file:{SESSIONS_DB}?mode=ro", uri=True,
                             timeout=5)
        row = db.execute(
            "SELECT title FROM sessions WHERE id=?",
            (session_id,)).fetchone()
        db.close()
        return (row[0] or "") if row else ""
    except sqlite3.Error:
        return ""


def build_query(args) -> str:
    parts = []
    if args.session:
        title = session_title(args.session)
        if title:
            parts.append(title)
    if args.project:
        parts.append(args.project)
    if args.query:
        parts.append(args.query)
    return " ".join(p for p in parts if p).strip()


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def render(query: str, t1: list[dict], t2: list[dict],
           max_chars: int = MAX_CHARS) -> str:
    out = ["# Session recall — hybrid T1 semantic + T2 transcript keyword",
           "", f"_query: {_clip(query, 200)}_", ""]
    if t1:
        out.append("## T1 — mddb semantic (ada-ha-bank-devin-tony)")
        for h in t1:
            score = f"{h['score']:.2f}" if isinstance(h.get("score"),
                                                    (int, float)) else "?"
            out.append(f"- `{h.get('key')}` ({score}): "
                       f"{_clip(h.get('content'), T1_SNIPPET)}")
        out.append("")
    if t2:
        out.append("## T2 — transcript keyword hits")
        for h in t2:
            out.append(f"- `{h['session']}`: {_clip(h['snippet'], 300)}")
        out.append("")
    text = "\n".join(out).rstrip() + "\n"
    if len(text) > max_chars:
        # keep the header + T1, truncate T2 tail — T1 is the warm path
        text = text[:max_chars - 20].rstrip() + "\n\n[...truncated...]\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", default="",
                    help="recall query (free text)")
    ap.add_argument("--session", default="",
                    help="sessions.db session id — its title joins the "
                         "query (best free recall signal at SessionStart)")
    ap.add_argument("--project", default="",
                    help="project name appended to the query")
    ap.add_argument("--json", action="store_true",
                    help="emit {query, t1, t2} JSON instead of text")
    ap.add_argument("--reindex", action="store_true",
                    help="refresh the T2 index and print stats, no recall")
    ap.add_argument("--no-index", action="store_true",
                    help="query only — skip the incremental index pass")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    args = ap.parse_args()

    # T2 index is opened independently of T1 — a broken/missing FTS5
    # index must not take the mddb semantic lane down with it (and vice
    # versa: mddb being unreachable already degrades to T2-only).
    con = None
    stats = None
    index_err = None
    try:
        con = open_index()
        if not args.no_index:
            stats = index_archives(con)
    except Exception as exc:
        index_err = exc
        con = None
        print(f"session_recall: t2 index unavailable ({exc})",
              file=sys.stderr)

    try:
        if args.reindex:
            if con is None:
                print(json.dumps({"index": str(INDEX_DB),
                                  "error": str(index_err), "chunks": 0},
                                 indent=1))
                return 0
            total = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
            print(json.dumps({"index": str(INDEX_DB), **(stats or {}),
                              "chunks": total}, indent=1))
            return 0
        query = build_query(args)
        t1 = recall_t1(query) if query else []
        t2 = recall_t2(con, query) if (query and con is not None) else []
        if args.json:
            print(json.dumps({"query": query, "t1": t1, "t2": t2},
                             indent=1))
        elif t1 or t2:
            # no hits -> emit nothing; an empty header is pure context noise
            sys.stdout.write(render(query, t1, t2, args.max_chars))
        if stats and (stats["indexed"] or stats["removed"]):
            print(f"# index: +{stats['indexed']} ~{stats['fresh']} "
                  f"-{stats['removed']} files", file=sys.stderr)
        return 0
    except Exception as exc:  # fail-open: the hook must never break
        print(f"session_recall: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
