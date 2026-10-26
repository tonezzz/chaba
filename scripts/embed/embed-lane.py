#!/usr/bin/env python3
"""embed-lane — the nomic backfill lane (card embedding-backfill-lanes).

Rides the LiteLLM `ollama-nomic-embed` deployment — nomic-embed-text
load-balanced across idc02+idc03 ollama — so bursty embed work lands on
idle cores instead of prod quota. The lane is SPACE-PINNED: it only ever
asks for ollama-nomic-embed and fails rather than falling back — nomic
vectors must never leak into the gemini-embedding-2 retrieval space
(card note, embed-space-eval verdict).

Subcommands:
  lessons  WP lesson CPT -> nomic vectors (search_document: prefix,
           ~1500c chunks) -> <dir>/lessons-nomic.jsonl. Read path is
           board-api /lesson op=list+get — no WP creds needed.
  news     WP news CPT titles -> nomic vectors with NO prefix, exactly
           the norm(title) string news-digest.py clusters — the store is
           a drop-in cache for the hourly digest run
           (NEWS_VEC_CACHE). Public REST, no creds.
  banks    Copy vector-searched collections from the mddb leader +
           cms plane into mddb-embed :11028 — the self-owned local bank
           (bge-m3 space via embed-pool-shim, MEM-0788/MEM-0805). The
           realized "MDDB bank reindex" lane; resume-safe and throttled
           on the target's embed-queue depth so bulk copies can't
           overflow its 4000-chunk queue.
  recall   search_query:-prefix a question and rank a store file —
           the edu-review recall probe for the lessons space.
  stats    store line counts + mddb-embed queue/vector state.

Stores are append-only JSONL: one line per vector
{"key","space","model","prefix","hash","text","meta","v"} — `v` is
base64 little-endian f32. Resume-safe: a key whose `hash` is unchanged
is skipped, so refreshes only embed new/changed docs.

Env:
  LITELLM_URL / LITELLM_KEY   else parsed from
    ~/.config/secrets/litellm-chaba.env then mddb-gemini.env
  EMBED_LANE_DIR              store dir (default ~/.local/share/embed-lane)
  BOARD_API                   lesson read door (default tailnet board-api)
  MDDB_EMBED_URL              banks target (default 100.102.134.91:11028)

Run where the store is consumed: news-digest + edu surfaces live on
idc03 — declared jobs write ~/var/embed-lane there; ad-hoc runs write
locally and can scp the file (it is a plain artifact).
"""
import argparse
import ast
import base64
import hashlib
import html
import json
import math
import os
import re
import struct
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SECRET_ENV_FILES = [os.path.expanduser("~/.config/secrets/litellm-chaba.env"),
                    os.path.expanduser("~/.config/secrets/mddb-gemini.env")]
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000")
WP_PUBLIC = os.environ.get(
    "WP_PUBLIC", "https://boards.surf-thailand.com/wp")
MDDB_EMBED = os.environ.get(
    "MDDB_EMBED_URL", "http://100.102.134.91:11028")
EMBED_DIR = os.environ.get(
    "EMBED_LANE_DIR", os.path.expanduser("~/.local/share/embed-lane"))

MODEL = "ollama-nomic-embed"      # litellm deployment — nomic LB lane
SPACE = "nomic-embed-text"        # the vector space tag stored per line
DOC_PREFIX = "search_document: "
QRY_PREFIX = "search_query: "
CHUNK = 1500                      # mddb chunk size — same granularity
TAG_RE = re.compile(r"<[^>]+>")

# Vector-searched tony collections (embed-space-eval BANK_COLLS) — the
# retrieval surface. Ops-routed collections (recall-summary, scenario-
# reports) are keyword-ranked, not embedded — intentionally absent.
BANK_COLLS = {
    "chaba-archive": "chaba-archive",
    "chaba-docs": "chaba-docs",
    "cms": "ada-cms-pages",
    "developer": "ada-ha-bank-developer-tony",
    "devin": "ada-ha-bank-devin-tony",
    "devin-handoff": "ada-ha-bank-devin-handoff",
    "devin-kb": "devin-kb",
    "documents": "documents",
    "general": "ada-ha-bank-general",
    "github": "ada-ha-bank-github",
    "home": "ada-ha-bank-home",
    "ideas": "ada-ha-bank-ideas-tony",
    "infrastructure-ssot": "infrastructure-ssot",
    "kb-development": "kb-development",
    "kb-features": "kb-features",
    "kb-operations": "kb-operations",
    "kb-system": "kb-system",
    "note": "ada-ha-bank-note-tony",
    "people": "ada-ha-bank-people",
    "personal": "ada-ha-bank-personal-tony",
    "personal-kk": "ada-ha-bank-personal-kk",
    "personal-testo": "ada-ha-bank-personal-testo",
    "purchase": "ada-ha-bank-purchase",
    "tony-projects": "ada-ha-bank-projects-tony",
}
CMS_PREFIX = ("ada-cms-", "chaba-", "kb-")
CMS_EXACT = {"documents", "infrastructure-ssot", "devin-kb", "ada-tools",
             "ada-scenario", "ada-session-audit", "ada-tool-profile",
             "ssot"}
MDDB_LEADER = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023")
MDDB_CMS = os.environ.get("MDDB_CMS_URL", "http://100.102.134.91:11027")


def mddb_base(coll: str) -> str:
    return (MDDB_CMS if coll.startswith(CMS_PREFIX) or coll in CMS_EXACT
            else MDDB_LEADER)


# ------------------------------------------------------------------ http
def _post(url, payload, timeout=60, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _get(url, timeout=45, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _load_env(path):
    env = {}
    try:
        for line in open(path):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def litellm_creds():
    url, key = (os.environ.get("LITELLM_URL"),
                os.environ.get("LITELLM_KEY"))
    if url and key:
        return url.rstrip("/"), key
    for f in SECRET_ENV_FILES:
        env = _load_env(f)
        if env.get("LITELLM_URL") and env.get("LITELLM_KEY"):
            return env["LITELLM_URL"].rstrip("/"), env["LITELLM_KEY"]
    raise SystemExit("no LITELLM_URL/LITELLM_KEY — set env or "
                     "litellm-chaba.env / mddb-gemini.env")


def embed(texts, url, key, tries=5):
    """nomic vectors via the litellm lane — pinned model, never a
    fallback. Retries ride the LB; a dead lane fails the run."""
    err = None
    for attempt in range(tries):
        try:
            d = _post(url.rstrip("/") + "/embeddings",
                      {"model": MODEL, "input": texts},
                      timeout=180,
                      headers={"Authorization": f"Bearer {key}"})
            return [x["embedding"] for x in d["data"]]
        except Exception as e:
            err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"embed lane failed after {tries} tries: {err}")


# ----------------------------------------------------------------- store
def b64e(v):
    return base64.b64encode(struct.pack(f"<{len(v)}f", *v)).decode()


def b64d(s):
    raw = base64.b64decode(s)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def jlines(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def load_hashes(path):
    return {r["key"]: r.get("hash") for r in jlines(path)}


def append_rows(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def norm(s):
    """news-digest.py's title normalizer — byte-identical so cached
    vectors match what the digest would compute."""
    return re.sub(r"\s+", " ", TAG_RE.sub(" ",
                  html.unescape(s or ""))).strip().lower()


def strip_html(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(s or ""))
                  ).strip()


def sha(text):
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def chunk_text(title, text, size=CHUNK):
    """~1500c windows on paragraph-ish boundaries, title on chunk 0."""
    text = text.strip()
    if not text:
        return []
    chunks, cur = [], (title + "\n\n" if title else "")
    for para in re.split(r"\n{2,}|(?<=[.!?])\s{2,}", text):
        if cur and len(cur) + len(para) > size:
            chunks.append(cur.strip())
            cur = para
        else:
            cur += ("\n\n" if cur else "") + para
        while len(cur) > size:
            chunks.append(cur[:size].strip())
            cur = cur[size:]
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if len(c) > 20]


def embed_into_store(items, path, url, key, batch=32, dry=False):
    """items: [{key, text(raw, unprefixed), meta}] — embeds text with the
    caller's prefix baked into meta['prefix'] / item['prefix']."""
    have = load_hashes(path)
    todo = [it for it in items if have.get(it["key"]) != sha(it["text"])]
    print(f"  store {os.path.basename(path)}: {len(have)} present, "
          f"{len(todo)} to embed", flush=True)
    if dry:
        return len(todo)
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        vs = embed([c["prefix"] + c["text"] for c in chunk], url, key)
        append_rows(path, [{"key": c["key"], "space": SPACE,
                            "model": MODEL, "prefix": c["prefix"],
                            "hash": sha(c["text"]),
                            "text": c["text"][:400],
                            "meta": c.get("meta") or {},
                            "v": b64e(v)}
                           for c, v in zip(chunk, vs)])
        done += len(chunk)
        if done % 256 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)} embedded", flush=True)
        time.sleep(0.05)
    return len(todo)


# --------------------------------------------------------------- lessons
def board_lesson(body):
    return _post(f"{BOARD_API}/lesson", body, timeout=60)


def cmd_lessons(args, url, key):
    lst = board_lesson({"op": "list", "from": "devin"})
    lessons = lst.get("lessons") or []
    print(f"lessons: {len(lessons)} posts")
    items = []
    for lsn in lessons:
        slug = lsn.get("slug")
        try:
            full = board_lesson({"op": "get", "slug": slug,
                                 "from": "devin"})
        except Exception as e:
            print(f"  warn: get {slug}: {e}", file=sys.stderr)
            continue
        title = strip_html(full.get("title") or lsn.get("topic") or slug)
        text = strip_html(full.get("content") or "")
        meta = {"slug": slug, "topic": (full.get("meta") or {}).get("topic")
                or lsn.get("topic"), "level": lsn.get("level"),
                "modified": full.get("modified") or lsn.get("modified")}
        for i, c in enumerate(chunk_text(title, text)):
            items.append({"key": f"{slug}#{i}", "prefix": DOC_PREFIX,
                          "text": c, "meta": {**meta, "chunk": i}})
        time.sleep(0.05)
    path = os.path.join(args.dir, "lessons-nomic.jsonl")
    n = embed_into_store(items, path, url, key, dry=args.dry_run)
    print(f"lessons: {len(items)} chunks, {n} embedded -> {path}")


# ------------------------------------------------------------------ news
def wp_news_pages(after=None, before=None):
    """All published news items via the public REST route (no creds —
    the archive is public). Optional bounded window for refresh runs."""
    page, out = 1, []
    while True:
        q = (f"/wp/v2/news&per_page=100&page={page}"
             "&_fields=slug,title,date,link,parent,status")
        if after:
            q += f"&after={after}"
        if before:
            q += f"&before={before}"
        u = (f"{WP_PUBLIC}/index.php?rest_route="
             f"{urllib.parse.quote(q, safe='/&=?')}")
        rows = None
        for attempt in range(4):
            try:
                rows = _get(u, headers={
                    "User-Agent": "chaba-embed-lane/1.0"})
                break
            except urllib.error.HTTPError as e:
                if e.code == 400:      # past last page
                    return out
                if e.code in (403, 429, 503) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        if rows is None:
            break
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        page += 1
        time.sleep(0.1)
    return out


def cmd_news(args, url, key):
    since = None
    if args.hours:
        from datetime import timedelta
        since = (datetime.now(timezone.utc)
                 - timedelta(hours=args.hours)).isoformat(timespec="seconds")
    posts = wp_news_pages(after=since)
    print(f"news: {len(posts)} published items"
          + (f" since {since}" if since else ""))
    items = []
    for p in posts:
        title = norm((p.get("title") or {}).get("rendered"))
        if not title:
            continue
        items.append({"key": p["slug"], "prefix": "", "text": title,
                      "meta": {"date": p.get("date"),
                               "link": p.get("link"),
                               "parent": p.get("parent") or 0,
                               "digest": p["slug"].startswith("d-")}})
    path = os.path.join(args.dir, "news-nomic.jsonl")
    n = embed_into_store(items, path, url, key, dry=args.dry_run)
    print(f"news: {len(items)} titles, {n} embedded -> {path}")


# ----------------------------------------------------------------- banks
def _docs(base, coll, include_content):
    d = _post(f"{base}/v1/search",
              {"collection": coll, "limit": 10000,
               "include_content": include_content}, timeout=120)
    return d if isinstance(d, list) else (
        d.get("results") or d.get("documents") or [])


def _queue_depth():
    try:
        d = _post(f"{MDDB_EMBED}/v1/vector-stats", {}, timeout=30)
        q = d.get("queue") or {}
        return int(q.get("depth") or 0), int(q.get("dropped") or 0)
    except Exception:
        return -1, -1


def cmd_banks(args, url, key):
    del url, key  # banks ride the target's own embed queue, not litellm
    colls = args.collection or sorted(set(BANK_COLLS.values()))
    hi = args.queue_hi
    total_copied = total_fail = 0
    for coll in colls:
        src = mddb_base(coll)
        try:
            have = {d.get("key") for d in _docs(MDDB_EMBED, coll, False)}
            src_docs = _docs(src, coll, True)
        except Exception as e:
            print(f"banks {coll}: fetch failed {e}", file=sys.stderr)
            continue
        todo = [d for d in src_docs
                if (args.force or d.get("key") not in have)
                and d.get("contentMd")]
        if args.limit:
            todo = todo[:args.limit]
        print(f"banks {coll}: src={len(src_docs)} have={len(have)} "
              f"todo={len(todo)}", flush=True)
        if args.dry_run:
            continue
        copied = fail = 0
        for i, d in enumerate(todo):
            # throttle: never let the target's embed queue near its cap
            depth, dropped = _queue_depth()
            while depth >= hi:
                print(f"  queue depth {depth} (dropped {dropped}) — "
                      f"waiting for drain < {hi}", flush=True)
                time.sleep(30)
                depth, dropped = _queue_depth()
            meta = d.get("meta") or {}
            if isinstance(meta, str):
                try:
                    meta = ast.literal_eval(meta)
                except Exception:
                    meta = {}
            try:
                _post(f"{MDDB_EMBED}/v1/add",
                      {"collection": coll, "key": d["key"],
                       "lang": d.get("lang") or "en",
                       "contentMd": d["contentMd"], "meta": meta},
                      timeout=60)
                copied += 1
            except Exception as e:
                fail += 1
                print(f"  FAIL {d.get('key')}: {e}", file=sys.stderr)
            if (i + 1) % 50 == 0:
                print(f"  {coll}: {i+1}/{len(todo)} copied", flush=True)
            time.sleep(0.03)
        total_copied += copied
        total_fail += fail
        print(f"banks {coll}: copied={copied} failed={fail}", flush=True)
    depth, dropped = _queue_depth()
    print(f"banks: {total_copied} docs delivered, {total_fail} failed; "
          f"embed queue depth={depth} dropped={dropped} "
          f"(drains async via embed-pool)")


# ---------------------------------------------------------------- recall
def cos(a, b):
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def cmd_recall(args, url, key):
    path = (args.store if os.path.sep in args.store or args.store.endswith(".jsonl")
            else os.path.join(args.dir, f"{args.store}-nomic.jsonl"))
    rows = jlines(path)
    if not rows:
        raise SystemExit(f"empty store: {path}")
    qv = embed([QRY_PREFIX + args.query], url, key)[0]
    scored = sorted(((cos(qv, b64d(r["v"])), r) for r in rows),
                    key=lambda t: -t[0])[:args.top]
    for s, r in scored:
        m = r.get("meta") or {}
        label = m.get("topic") or m.get("slug") or r["key"]
        print(f"{s:.3f}  {label[:70]}  [{r['key']}]")
        print(f"      {r.get('text','')[:110]}")


# ----------------------------------------------------------------- stats
def cmd_stats(args, url, key):
    del url, key
    for name in ("lessons", "news"):
        path = os.path.join(args.dir, f"{name}-nomic.jsonl")
        rows = jlines(path)
        keys = {r["key"].split("#")[0] for r in rows}
        print(f"{name:8s} {len(rows):>5} vectors / {len(keys)} docs  {path}")
    try:
        d = _post(f"{MDDB_EMBED}/v1/vector-stats", {}, timeout=30)
        q = d.get("queue") or {}
        print(f"mddb-embed :11028 model={d.get('model')} "
              f"dims={d.get('dimensions')} "
              f"queue depth={q.get('depth')} dropped={q.get('dropped')}")
        for c, st in sorted((d.get("collections") or {}).items()):
            print(f"  {c}: {st.get('embedded_documents')}/"
                  f"{st.get('total_documents')} embedded "
                  f"({st.get('total_chunks')} chunks)")
    except Exception as e:
        print(f"mddb-embed stats: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def base(p):
        p.add_argument("--dir", default=EMBED_DIR)
        p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("lessons", help="lesson CPT -> nomic store")
    base(p)
    p = sub.add_parser("news", help="news titles -> nomic store")
    base(p)
    p.add_argument("--hours", type=float, default=0,
                   help="only items newer than N hours (default: all)")
    p = sub.add_parser("banks", help="collections -> mddb-embed :11028")
    base(p)
    p.add_argument("--collection", action="append",
                   help="one collection (repeatable); default BANK_COLLS")
    p.add_argument("--limit", type=int, default=0,
                   help="cap docs per collection")
    p.add_argument("--force", action="store_true",
                   help="re-add docs already on target (repair drops)")
    p.add_argument("--queue-hi", type=int, default=3000,
                   help="pause /add calls while the target embed queue "
                        "is this deep (cap 4000)")
    p = sub.add_parser("recall", help="query a store")
    base(p)
    p.add_argument("--store", default="lessons")
    p.add_argument("--query", required=True)
    p.add_argument("--top", type=int, default=5)
    p = sub.add_parser("stats")
    base(p)

    args = ap.parse_args()
    url, key = (litellm_creds() if args.cmd != "banks"
                else (None, None))
    {"lessons": cmd_lessons, "news": cmd_news, "banks": cmd_banks,
     "recall": cmd_recall, "stats": cmd_stats}[args.cmd](args, url, key)


if __name__ == "__main__":
    main()
