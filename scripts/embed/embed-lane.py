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
           realized "MDDB bank reindex" lane; incremental and
           throttled on the target's embed-queue depth so bulk copies
           can't overflow its 4000-chunk queue. Each run copies a
           bounded slice (--budget wall clock / --max-docs per bank)
           and resumes from a persisted per-bank cursor
           (<dir>/banks-state.json + banks-have/<coll>.keys) — a
           112k-doc collection drains over successive runs instead of
           dying on TimeoutStartSec (card
           embed-lane-banks-incremental-copy-fix).
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
  MDDB_EMBED_URL              banks target (default 100.123.163.11:11028)

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
    "MDDB_EMBED_URL", "http://100.123.163.11:11028")
EMBED_DIR = os.environ.get(
    "EMBED_LANE_DIR", os.path.expanduser("~/.local/share/embed-lane"))

MODEL = "ollama-nomic-embed"      # litellm deployment — nomic LB lane
SPACE = "nomic-embed-text"        # the vector space tag stored per line
DOC_PREFIX = "search_document: "
QRY_PREFIX = "search_query: "
CHUNK = 1500                      # mddb chunk size — same granularity
PAGE = 1000                       # /v1/search server page cap
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
def _docs_pages(base, coll, include_content, start=0):
    """Yield successive /v1/search pages for a collection, beginning at
    row offset `start`. /v1/search caps a page at PAGE docs regardless
    of the requested limit, so a single big-limit call silently
    truncates larger collections (card embed-lane-banks-search-pagination).
    Page by offset until a short page — same loop shape as
    mddb_probe.cmd_expired. NOTE: the server ignores include_content
    and always returns contentMd — pages are the only bulk content
    channel, which is why the banks cursor scans with content and
    resumes mid-collection instead of re-fetching."""
    offset, seen = start, set()
    while True:
        d = _post(f"{base}/v1/search",
                  {"collection": coll, "limit": PAGE, "offset": offset,
                   "include_content": include_content}, timeout=120)
        page = d if isinstance(d, list) else (
            d.get("results") or d.get("documents") or [])
        fresh = [x for x in page if x.get("key") not in seen]
        if page and not fresh:
            return               # offset ignored — same page again
        seen.update(x.get("key") for x in page)
        yield page
        offset += len(page)
        if len(page) < PAGE:
            return
        time.sleep(0.05)


def _docs(base, coll, include_content):
    """All docs in a collection (see _docs_pages)."""
    out = []
    for page in _docs_pages(base, coll, include_content):
        out.extend(page)
    return out


def _queue_depth():
    try:
        d = _post(f"{MDDB_EMBED}/v1/vector-stats", {}, timeout=30)
        q = d.get("queue") or {}
        return int(q.get("depth") or 0), int(q.get("dropped") or 0)
    except Exception:
        return -1, -1


# ------------------------------------------------------- banks cursor
# Resumable/incremental bank sync (card embed-lane-banks-incremental-
# copy-fix). A one-shot 112k-doc collection cannot finish inside one
# timer window, so each run copies a bounded slice and the next run
# resumes. State lives under --dir:
#   banks-state.json        per-collection cursor/pass/counters + the
#                           round-robin start index (atomic tmp+rename)
#   banks-have/<coll>.keys  append-only set of target keys this lane has
#                           confirmed — rebuilt from /v1/search every
#                           --have-refresh runs so external target
#                           writes/deletes reconcile; between refreshes
#                           confirmed copies are appended, which keeps
#                           hourly runs from re-downloading the whole
#                           target collection (search always returns
#                           contentMd — there is no key-only page mode).
#
# Cursor semantics: `offset` is the next unscanned /v1/search row
# offset. Rows are bolt key-order (stable for a static set); inserts
# can shift offsets by a row or two, which costs at most a skipped or
# repeated doc per pass — repeated docs are idempotent /v1/add upserts
# and skipped docs are caught when the cursor wraps to 0. A "pass" is
# one full 0->end->0 sweep; it completes clean (no copy failures,
# quarantined bad_keys aside) -> synced_at is stamped and the
# collection is skipped until --rescan-hours or a have-refresh forces
# a verification pass.
BANKS_STATE = "banks-state.json"
BANKS_HAVE_DIR = "banks-have"
HAVE_REFRESH_DEFAULT = 24     # runs between full target-key refreshes
RESCAN_HOURS_DEFAULT = 6.0    # synced collections re-verify this often
BAD_KEY_FAILS = 2             # add failures before a key is quarantined
BAD_KEYS_CAP = 500
SCAN_FAIL_ALERT = 3           # consecutive src-scan errors before rc=1


def _bank_state_path(args):
    return os.path.join(args.dir, BANKS_STATE)


def _load_bank_state(path):
    try:
        with open(path) as f:
            st = json.load(f)
        if isinstance(st, dict) and isinstance(st.get("collections"), dict):
            st.setdefault("next_idx", 0)
            return st
    except Exception:
        pass
    return {"version": 1, "next_idx": 0, "collections": {}}


def _save_bank_state(path, st):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as e:
        print(f"  warn: banks state save failed: {e}", file=sys.stderr)


def _have_path(args, coll):
    return os.path.join(args.dir, BANKS_HAVE_DIR, f"{coll}.keys")


def _load_have(path):
    try:
        with open(path) as f:
            return {ln.strip() for ln in f if ln.strip()}
    except OSError:
        return None


def _write_have(path, keys):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            for k in sorted(keys):
                f.write(k + "\n")
        os.replace(tmp, path)
    except OSError as e:
        print(f"  warn: banks have write failed: {e}", file=sys.stderr)


def _append_have(path, keys):
    if not keys:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for k in keys:
                f.write(k + "\n")
    except OSError as e:
        print(f"  warn: banks have append failed: {e}", file=sys.stderr)


def _bank_add(coll, d):
    """One doc -> target /v1/add. meta may arrive as a python-repr str
    (older writers) — normalize to dict."""
    meta = d.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = ast.literal_eval(meta)
        except Exception:
            meta = {}
    return _post(f"{MDDB_EMBED}/v1/add",
                 {"collection": coll, "key": d["key"],
                  "lang": d.get("lang") or "en",
                  "contentMd": d["contentMd"], "meta": meta},
                 timeout=60)


def _bank_fetch_have(args, coll, cs, over_budget):
    """Target key set for skip-decisions. Returns (have, budget_stop):
    have is the persisted banks-have file while fresh, else a full
    paged /v1/search refresh (rewrites the file); under --force it is
    empty so every src doc re-adds. budget_stop=True means the wall
    clock died mid-refresh — caller ends the run without touching
    cursor state (the partial set is discarded)."""
    have_path = _have_path(args, coll)
    if args.force:
        return set(), False
    file_keys = _load_have(have_path)
    if file_keys is not None and int(cs.get("have_refresh_in") or 0) > 0:
        cs["have_refresh_in"] = int(cs["have_refresh_in"]) - 1
        return file_keys, False
    have = set()
    try:
        for page in _docs_pages(MDDB_EMBED, coll, False):
            if over_budget():
                return None, True
            have.update(x.get("key") for x in page if x.get("key"))
    except Exception as e:
        raise RuntimeError(f"have fetch failed: {e}")
    _write_have(have_path, have)
    cs["have_refresh_in"] = args.have_refresh
    return have, False


def _bank_scan_coll(args, coll, cs, have, state, state_path,
                    over_budget, max_docs):
    """Scan src pages from cs['offset'], /v1/add every doc missing from
    `have`. Returns (copied, failed, stop_reason) where stop_reason is
    None | 'budget' | 'cap' | 'error'. Mutates cs; caller persists the
    full `state`."""
    src = mddb_base(coll)
    bad = cs.setdefault("bad_keys", {})
    copied = fail = 0
    base = int(cs.get("offset") or 0)
    pass_fail = int(cs.get("pass_failures") or 0)
    wrapped = False
    added_have = []
    stop = None

    def checkpoint():
        _append_have(_have_path(args, coll), added_have)
        added_have.clear()
        _save_bank_state(state_path, state)

    try:
        for page in _docs_pages(src, coll, True, start=base):
            if over_budget() or (max_docs and copied >= max_docs):
                stop = "budget" if over_budget() else "cap"
                break
            for i, d in enumerate(page):
                if over_budget() or (max_docs and copied >= max_docs):
                    cs["offset"] = base + i
                    stop = "budget" if over_budget() else "cap"
                    break
                key = d.get("key")
                if not key or key in have:
                    continue
                if int(bad.get(key) or 0) >= BAD_KEY_FAILS:
                    continue
                if not (d.get("contentMd") or "").strip():
                    continue
                # throttle: never let the target's embed queue near cap
                depth, dropped = _queue_depth()
                while depth >= args.queue_hi:
                    if over_budget() or (max_docs and copied >= max_docs):
                        cs["offset"] = base + i
                        stop = "budget" if over_budget() else "cap"
                        break
                    print(f"  {coll}: queue depth {depth} (dropped "
                          f"{dropped}) — waiting for drain < "
                          f"{args.queue_hi}", flush=True)
                    time.sleep(30)
                    depth, dropped = _queue_depth()
                if stop:
                    break
                try:
                    _bank_add(coll, d)
                except Exception:
                    try:
                        time.sleep(2)
                        _bank_add(coll, d)
                    except Exception as e:
                        fail += 1
                        pass_fail += 1
                        bad[key] = int(bad.get(key) or 0) + 1
                        if len(bad) > BAD_KEYS_CAP:
                            bad.pop(next(iter(bad)), None)
                        print(f"  FAIL {key}: {e}", file=sys.stderr)
                        continue
                have.add(key)
                added_have.append(key)
                copied += 1
                cs["copied_total"] = int(cs.get("copied_total") or 0) + 1
                if copied % 250 == 0:
                    print(f"  {coll}: +{copied} copied "
                          f"(row {base + i + 1})", flush=True)
                if len(added_have) >= 200:
                    checkpoint()
                time.sleep(0.03)
            if stop:
                break
            base += len(page)
            cs["offset"] = base
            if len(page) < PAGE:
                # reached end of collection — close the pass
                cs["src_total"] = base
                cs["offset"] = 0
                cs["pass"] = int(cs.get("pass") or 0) + 1
                wrapped = True
                cs["synced_at"] = (datetime.now(timezone.utc)
                                   .isoformat(timespec="seconds")
                                   if pass_fail == 0 else None)
                break
            checkpoint()
    except Exception as e:
        if over_budget():
            stop = "budget"
        else:
            stop = "error"
            cs["last_error"] = str(e)
            # transient transport drops ("Remote end closed") self-heal
            # via the cursor — only count consecutive failures so one
            # blip doesn't fail the whole run / flap the alert card.
            cs["scan_failures"] = int(
                cs.get("scan_failures") or 0) + 1
    else:
        cs["scan_failures"] = 0
    if wrapped:
        cs["pass_failures"] = 0
    else:
        cs["pass_failures"] = pass_fail
    cs["updated"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    checkpoint()
    return copied, fail, stop


def cmd_banks(args, url, key):
    del url, key  # banks ride the target's own embed queue, not litellm
    colls = args.collection or sorted(set(BANK_COLLS.values()))
    max_docs = args.max_docs or args.limit or 0
    rescan_s = max(0.0, args.rescan_hours) * 3600.0
    t0 = time.monotonic()
    state_path = _bank_state_path(args)
    state = _load_bank_state(state_path)
    colls_state = state["collections"]

    def over_budget():
        return bool(args.budget) and time.monotonic() - t0 > args.budget

    def save():
        _save_bank_state(state_path, state)

    now = datetime.now(timezone.utc)
    total_copied = total_fail = 0
    run_errors = []
    n = len(colls)
    start_idx = int(state.get("next_idx") or 0) % n if n else 0
    next_idx = start_idx
    budget_stop = False

    for i in range(n):
        idx = (start_idx + i) % n
        coll = colls[idx]
        if over_budget():
            next_idx = idx
            budget_stop = True
            break
        cs = colls_state.setdefault(coll, {
            "offset": 0, "pass": 0, "src_total": 0, "copied_total": 0,
            "fail_total": 0, "pass_failures": 0, "have_refresh_in": 0,
            "synced_at": None, "bad_keys": {}, "updated": None})
        if args.force:
            cs["bad_keys"] = {}      # retry quarantined docs this pass

        # synced collections skip entirely until rescan/refresh is due —
        # keeps hourly runs near-free once a bank is caught up.
        synced_at = cs.get("synced_at")
        if not args.force and synced_at and rescan_s \
                and int(cs.get("have_refresh_in") or 0) > 0:
            try:
                age = (now - datetime.fromisoformat(synced_at)
                       ).total_seconds()
            except Exception:
                age = rescan_s + 1
            if age < rescan_s:
                print(f"banks {coll}: synced (clean pass at {synced_at})"
                      f" — skip, re-verify in {(rescan_s - age) / 3600:.1f}h",
                      flush=True)
                continue

        print(f"banks {coll}: pass={cs.get('pass') or 0} "
              f"offset={cs.get('offset') or 0}/"
              f"{cs.get('src_total') or '?'} "
              f"copied_total={cs.get('copied_total') or 0} "
              f"bad={len(cs.get('bad_keys') or {})}", flush=True)

        if args.dry_run:
            # diagnostic only: count src rows missing from the target
            # have-set; no copies, no cursor/state mutation.
            try:
                have, bstop = _bank_fetch_have(args, coll, cs, over_budget)
                if bstop or have is None:
                    next_idx = idx
                    budget_stop = True
                    break
                missing = scanned = 0
                for page in _docs_pages(mddb_base(coll), coll, True):
                    if over_budget():
                        break
                    for d in page:
                        scanned += 1
                        k = d.get("key")
                        if k and k not in have and (d.get("contentMd")
                                                    or "").strip():
                            missing += 1
                print(f"banks {coll}: dry-run {missing} missing of "
                      f"{scanned} scanned", flush=True)
            except Exception as e:
                run_errors.append(f"{coll}: dry-run failed: {e}")
                print(f"banks {coll}: dry-run failed {e}",
                      file=sys.stderr)
            continue

        try:
            have, bstop = _bank_fetch_have(args, coll, cs, over_budget)
        except Exception as e:
            run_errors.append(f"{coll}: {e}")
            print(f"banks {coll}: {e}", file=sys.stderr)
            continue
        if bstop or have is None:
            next_idx = idx
            budget_stop = True
            break

        copied, fail, stop = _bank_scan_coll(
            args, coll, cs, have, state, state_path, over_budget,
            max_docs)
        total_copied += copied
        total_fail += fail
        if stop == "error":
            scan_fails = int(cs.get("scan_failures") or 0)
            if scan_fails >= SCAN_FAIL_ALERT:
                run_errors.append(
                    f"{coll}: scan failed {scan_fails}x consecutively: "
                    f"{cs.get('last_error')}")
            print(f"banks {coll}: scan failed "
                  f"{cs.get('last_error')} ({scan_fails}/"
                  f"{SCAN_FAIL_ALERT})", file=sys.stderr)
            continue
        if fail and not copied:
            run_errors.append(
                f"{coll}: {fail} add failures, 0 copied — target "
                f"likely unhealthy")
        synced_now = bool(cs.get("synced_at")) and \
            int(cs.get("pass") or 0) > 0
        print(f"banks {coll}: +{copied} copied, {fail} failed "
              f"(offset={cs.get('offset') or 0}/"
              f"{cs.get('src_total') or '?'}, "
              f"pass={cs.get('pass') or 0}"
              f"{', synced' if synced_now else ''})", flush=True)
        if stop == "budget":
            next_idx = (idx + 1) % n
            budget_stop = True
            break
        # 'cap' or clean finish — move on to the next collection
        save()

    state["next_idx"] = next_idx
    save()

    depth, dropped = _queue_depth()
    note = ("; run budget exhausted — cursors persisted, next run "
            "resumes" if budget_stop or over_budget() else "")
    print(f"banks: {total_copied} docs delivered, {total_fail} failed; "
          f"embed queue depth={depth} dropped={dropped} "
          f"(drains async via embed-pool){note}", flush=True)
    for e in run_errors:
        print(f"banks ERROR: {e}", file=sys.stderr)
    return 1 if run_errors else 0


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
                   help="cap docs copied per collection this run "
                        "(alias for --max-docs)")
    p.add_argument("--max-docs", type=int, default=0,
                   help="cap docs copied per collection this run — "
                        "the bounded slice; the per-bank cursor resumes "
                        "the rest next run (0 = unlimited)")
    p.add_argument("--budget", type=int, default=0,
                   help="wall-clock seconds for the whole run — stop "
                        "copying cleanly (exit 0) once exceeded so the "
                        "service finishes inside TimeoutStartSec; the "
                        "per-bank cursor resumes next run")
    p.add_argument("--rescan-hours", type=float,
                   default=RESCAN_HOURS_DEFAULT,
                   help="synced collections re-verify after this many "
                        "hours (default %(default)s)")
    p.add_argument("--have-refresh", type=int,
                   default=HAVE_REFRESH_DEFAULT,
                   help="runs between full target-key-set refreshes "
                        "(default %(default)s)")
    p.add_argument("--force", action="store_true",
                   help="re-add docs already on target (repair drops) "
                        "— ignores the have-set and quarantined "
                        "bad_keys; the cursor still bounds each pass")
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
    rc = {"lessons": cmd_lessons, "news": cmd_news, "banks": cmd_banks,
          "recall": cmd_recall, "stats": cmd_stats}[args.cmd](
              args, url, key)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
