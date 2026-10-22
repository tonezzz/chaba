#!/usr/bin/env python3
"""bench-recall.py — card session-mddb-recall-benchmark: is the per-session
distilled MDDB doc enough for team recall, so devin sessions.db can be
pruned to active sessions only?

Three lanes answer the same golden questions (fixture:
fixtures/bench-recall-fixtures.json — sessions that have BOTH a
devin-session/<name> T1 doc in ada-ha-bank-devin-tony AND a raw
transcript in ~/.local/share/devin/cli/sessions.db):

  a) mddb      semantic_search over the bank, status=active filter —
               mirrors backend/memory_ops.memory_search (topK, threshold,
               active-only).
  b) transcript BM25/keyword retrieval over chunked raw transcripts of
               the fixture sessions (no external deps).
  c) surface   the current recall surface: session-memory.md tail +
               notebook-summaries/compactions grep — same chunk+BM25
               retrieval over those files.

Judge: one fixed gemini flash-lite with a strict answer-present rubric —
"does this retrieved item contain the information needed to give the
golden answer?" scored per retrieved item; hit@1 = top item passes,
hit@3 = any of top 3 passes.

Usage:
  python3 scripts/bench-recall.py                      # run all lanes
  python3 scripts/bench-recall.py --lanes mddb --limit 10
  python3 scripts/bench-recall.py --reps 2 --json reports/bench-recall.json
  python3 scripts/bench-recall.py --gen-fixture        # rebuild fixture
  python3 scripts/bench-recall.py --gen-fixture --limit 5 --fixture /tmp/f.json

Env: GEMINI_API_KEY / GOOGLE_API_KEY (else read from
~/.config/secrets/{mddb-gemini.env,gemini-keys.env,gemini-api-key.env}),
GEMINI_BASE_URL (LiteLLM gateway override), BENCH_JUDGE_MODEL
(default gemini-3.5-flash-lite), SESSIONS_DB, NOTEBOOK_DIR.
MDDB endpoint + X-API-Key are read at runtime from
~/.config/devin/mcp_config.json 'mddb' entry — never printed.
"""
import argparse
import concurrent.futures
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "ada"))
import gemini_rest  # noqa: E402

COLLECTION = "ada-ha-bank-devin-tony"
JUDGE_MODEL = os.environ.get("BENCH_JUDGE_MODEL", "gemini-3.5-flash-lite")
SESSIONS_DB = Path(os.environ.get(
    "SESSIONS_DB", Path.home() / ".local/share/devin/cli/sessions.db"))
NOTEBOOK_DIR = Path(os.environ.get(
    "NOTEBOOK_DIR", Path.home() / ".local/share/devin/notebook-summaries"))
MCP_CFG = Path.home() / ".config/devin/mcp_config.json"
DEFAULT_FIXTURE = REPO / "fixtures" / "bench-recall-fixtures.json"

RECALL_TOPK = 15        # mirror memory_ops.memory_search
RECALL_THRESHOLD = 0.45
JUDGE_K = 3             # items judged per question for hit@1/hit@3
CHUNK = 1800            # transcript/surface chunk size (chars)
CHUNK_OVERLAP = 200
MSG_CAP = 8000          # per-message cap building transcript text
SESS_CAP = 600_000      # per-session transcript cap


# ---------------------------------------------------------------- MDDB
class Mddb:
    """Minimal StreamableHTTP JSON-RPC client for mddbd (mirrors
    ~/.config/devin/mcp-scripts/mddb-bridge.py: initialize -> capture
    Mcp-Session-Id -> tools/call)."""

    def __init__(self):
        cfg = json.load(open(MCP_CFG))["mcpServers"]["mddb"]
        self.url, self.key = cfg["url"], cfg["headers"]["X-API-Key"]
        self.sid = None
        self._id = 0
        self.call("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "bench-recall", "version": "1"}})
        self.call("notifications/initialized", {})

    def call(self, method, params):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id,
                           "method": method, "params": params}).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "X-API-Key": self.key})
        if self.sid:
            req.add_header("Mcp-Session-Id", self.sid)
        with urllib.request.urlopen(req, timeout=90) as r:
            sid = r.getheader("Mcp-Session-Id")
            if sid:
                self.sid = sid
            raw = r.read().decode()
        if "data:" in raw[:400]:  # SSE framing
            for line in raw.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return {}
        return json.loads(raw) if raw else {}

    def tool(self, name, arguments):
        r = self.call("tools/call", {"name": name, "arguments": arguments})
        res = r.get("result") or {}
        cont = res.get("content") or []
        if not cont:
            raise RuntimeError(f"mddb {name}: empty result "
                               f"{json.dumps(r)[:200]}")
        return json.loads(cont[0]["text"])

    def semantic(self, query, top_k=RECALL_TOPK, threshold=RECALL_THRESHOLD,
                 status_active=True):
        args = {"collection": COLLECTION, "query": query, "top_k": top_k,
                "threshold": threshold, "include_content": True,
                "retrieval_mode": "parent"}
        if status_active:
            args["filter_meta"] = {"status": ["active"]}
        out = self.tool("semantic_search", args)
        results = []
        for h in out.get("results", []):
            doc = h.get("document") or {}
            results.append({"key": doc.get("key"), "score": h.get("score"),
                            "meta": doc.get("meta") or {},
                            "content": doc.get("content_md") or ""})
        return results

    def doc_by_session(self, session_name):
        out = self.tool("search_documents", {
            "collection": COLLECTION,
            "filter_meta": {"session_name": [session_name]},
            "include_content": True, "limit": 5})
        for d in out.get("documents", []):
            if d.get("key") == f"devin-session/{session_name}":
                return d
        return (out.get("documents") or [None])[0]


# ---------------------------------------------------------------- data
def session_names_in_bank(mddb):
    names, off = set(), 0
    while True:
        out = mddb.tool("search_documents", {
            "collection": COLLECTION, "limit": 200, "offset": off,
            "include_content": False})
        docs = out.get("documents", [])
        for d in docs:
            if d["key"].startswith("devin-session/"):
                names.add(d["key"].split("/", 1)[1])
        off += len(docs)
        if len(docs) < 200 or off >= out.get("total", 0):
            break
    return names


def extract_transcript(db, session_id):
    """user+assistant text the way the FTS trigger indexes it; returns
    (text, raw_bytes) where raw_bytes counts every chat_message."""
    rows = db.execute(
        "select chat_message from message_nodes where session_id=? "
        "order by node_id", (session_id,)).fetchall()
    parts, raw = [], 0
    for (cm,) in rows:
        raw += len(cm)
        try:
            m = json.loads(cm)
        except Exception:
            continue
        role, meta = m.get("role"), m.get("metadata") or {}
        if role == "assistant" or (
                role == "user" and meta.get("is_user_input") in (1, True)):
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                parts.append(f"### {role}\n{c[:MSG_CAP]}")
    text = "\n\n".join(parts)
    if len(text) > SESS_CAP:  # keep head+tail — outcomes land at the end
        half = SESS_CAP // 2
        text = text[:half] + "\n\n[...middle truncated...]\n\n" + text[-half:]
    return text, raw


def chunk_text(text, size=CHUNK, overlap=CHUNK_OVERLAP):
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return [c for c in out if c.strip()]


# ------------------------------------------------------------- BM25-ish
def tokenize(t):
    return re.findall(r"[a-z0-9_./:-]{2,}", t.lower())


class KeywordIndex:
    """chunk index with BM25 scoring over the whole fixture corpus."""

    def __init__(self):
        self.chunks = []   # (source, text, tokens)
        self.df = {}
        self.avg = 1.0

    def add(self, source, text):
        for c in chunk_text(text):
            self.chunks.append((source, c, tokenize(c)))

    def build(self):
        df = {}
        total = 0
        for _, _, toks in self.chunks:
            total += len(toks)
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        self.df = df
        self.avg = total / max(len(self.chunks), 1)

    def search(self, query, top_k=JUDGE_K):
        q = tokenize(query)
        n_docs = max(len(self.chunks), 1)
        scored = []
        for src, text, toks in self.chunks:
            if not toks:
                continue
            tf = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for t in set(q):
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n_docs - self.df.get(t, 0) + 0.5)
                               / (self.df.get(t, 0) + 0.5))
                score += idf * (f * 2.2) / (f + 1.2 * (1 - 0.75 + 0.75
                                            * len(toks) / self.avg))
            if score > 0:
                scored.append((score, src, text))
        scored.sort(key=lambda x: -x[0])
        return [{"score": s, "key": src, "content": t}
                for s, src, t in scored[:top_k]]


# ---------------------------------------------------------------- judge
JUDGE_PROMPT = """You are a strict recall-benchmark judge.

QUESTION: {q}

REFERENCE ANSWER: {a}

RETRIEVED CONTEXT:
{ctx}

Does the retrieved context contain the information needed to give the
reference answer (or a correct equivalent answer to the question)?
Judge only whether the information is present in the context — not
whether the context words match the reference. Reply with exactly YES or
NO."""

GEN_PROMPT = """You are building a recall benchmark. Below is a raw Devin
agent session transcript for session "{name}" (title: {title}).

Write {n} question/answer pairs a TEAMMATE would later ask about this
session — e.g. the outcome of a task, the root cause of an error, which
card/file/host was touched, or where a decision was recorded. Rules:
- every answer must be directly supported by the transcript
- answers are short (one sentence or a name/path/list)
- questions must stand alone (no "this session") — include the concrete
  subject so retrieval can find it
- prefer facts a distilled summary might plausibly drop (specific paths,
  commands, error strings, card ids)

Reply with ONLY a JSON array: [{{"question": "...", "answer": "..."}}]

TRANSCRIPT (truncated):
{transcript}"""

GROUND_PROMPT = """You are a strict fact checker.

CLAIM: {a}
(about: {q})

TRANSCRIPT EXCERPT:
{ctx}

Is the claim directly supported by the transcript excerpt? Reply with
exactly YES or NO."""


def _read_env_file(path):
    out = {}
    if path.exists():
        for ln in path.read_text().splitlines():
            m = re.match(r"^([A-Z_]+)=(.*)$", ln.strip())
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def load_gemini_key():
    """Repo convention: bench lanes ride the LiteLLM gateway
    (ssot.llm-gateway.yml — virtual keys, per-key budgets); direct Google
    keys are the fallback. Returns the key; sets GEMINI_BASE_URL when
    routing via the gateway."""
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(env):
            return os.environ[env]
    lite = _read_env_file(Path.home() / ".config/secrets/litellm-chaba.env")
    if lite.get("LITELLM_KEY"):
        base = (lite.get("LITELLM_URL") or "http://100.102.134.91:4000"
                ).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        os.environ["GEMINI_BASE_URL"] = base
        return lite["LITELLM_KEY"]
    for f in ("mddb-gemini.env", "gemini-keys.env", "gemini-api-key.env"):
        vals = _read_env_file(Path.home() / ".config/secrets" / f)
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_FREE",
                  "LITELLM_KEY"):
            if vals.get(k):
                if k == "LITELLM_KEY":
                    os.environ["GEMINI_BASE_URL"] = (
                        vals.get("LITELLM_URL") or
                        "http://100.102.134.91:4000")
                return vals[k]
    return None


def judge(question, answer, context, key):
    prompt = JUDGE_PROMPT.format(q=question, a=answer,
                                 ctx=context[:12_000] or "(empty)")
    out = gemini_rest.generate(prompt, JUDGE_MODEL, key=key,
                               generation_config={"temperature": 0.0,
                                                  "maxOutputTokens": 8},
                               label="judge")
    return (out or "").strip().upper().startswith("YES")


def judge_items(question, answer, items, key, workers=4):
    """Judge each retrieved item -> (hit@1, hit@3, per-item verdicts)."""
    items = items[:JUDGE_K]
    if not items:
        return False, False, []
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        verdicts = list(ex.map(
            lambda it: judge(question, answer, it["content"], key), items))
    return verdicts[0], any(verdicts), verdicts


# ------------------------------------------------------------ fixture
def gen_fixture(args, log):
    key = load_gemini_key()
    if not key:
        sys.exit("no gemini key — set GEMINI_API_KEY or secrets file")
    mddb = Mddb()
    bank = session_names_in_bank(mddb)
    log(f"bank devin-session docs: {len(bank)}")
    db = sqlite3.connect(f"file:{SESSIONS_DB}?mode=ro", uri=True)
    ids = [r[0] for r in db.execute("select id from sessions order by id")]
    cands = [s for s in ids if s in bank]
    log(f"sessions.db: {len(ids)}; with T1 doc: {len(cands)}")
    if args.limit:
        cands = cands[:args.limit]

    fixture = {"collection": COLLECTION,
               "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
               "sessions": []}
    for name in cands:
        title = db.execute("select title from sessions where id=?",
                           (name,)).fetchone()[0]
        transcript, raw_bytes = extract_transcript(db, name)
        doc = mddb.doc_by_session(name)
        t1 = (doc or {}).get("content_md") or ""
        log(f"[{name}] transcript={len(transcript):,}B raw={raw_bytes:,}B "
            f"t1={len(t1):,}B")
        prompt = GEN_PROMPT.format(name=name, title=title or "",
                                   n=args.per_session,
                                   transcript=transcript[:48_000])
        out = gemini_rest.generate(
            prompt, JUDGE_MODEL, key=key,
            generation_config={"response_mime_type": "application/json",
                               "temperature": 0.4},
            label="gen")
        try:
            pairs = json.loads(out or "[]")
        except json.JSONDecodeError:
            m = re.search(r"\[.*\]", out or "", flags=re.S)
            pairs = json.loads(m.group(0)) if m else []
        goldens = []
        for p in pairs[:args.per_session]:
            q, a = (p.get("question") or "").strip(), (p.get("answer") or "").strip()
            if not q or not a:
                continue
            # ground-check against the transcript (head+tail excerpt)
            ok = judge(q, a, transcript[:40_000] + "\n...\n" + transcript[-20_000:],
                       key) if len(transcript) > 60_000 else judge(
                           q, a, transcript, key)
            goldens.append({"question": q, "answer": a, "grounded": ok})
            log(f"    {'ok ' if ok else 'DROP'} {q[:80]}")
        fixture["sessions"].append({
            "name": name, "title": title, "t1_key": f"devin-session/{name}",
            "t1_bytes": len(t1.encode()), "transcript_bytes": raw_bytes,
            "transcript_text_bytes": len(transcript.encode()),
            "goldens": goldens})
    fixture["sessions"] = [s for s in fixture["sessions"] if s["goldens"]]
    args.fixture.parent.mkdir(parents=True, exist_ok=True)
    args.fixture.write_text(json.dumps(fixture, indent=1))
    n_q = sum(len(s["goldens"]) for s in fixture["sessions"])
    log(f"wrote {args.fixture}: {len(fixture['sessions'])} sessions, {n_q} goldens")


# ---------------------------------------------------------------- run
def run_lane_mddb(mddb, questions, key, log):
    recs, lats = [], []
    for q in questions:
        t0 = time.time()
        try:
            items = mddb.semantic(q["question"])
        except Exception as e:
            items = []
            log(f"    mddb error: {e}")
        lats.append(time.time() - t0)
        h1, h3, v = judge_items(q["question"], q["answer"], items, key)
        recs.append({"qid": q["qid"], "hit1": h1, "hit3": h3,
                     "top_key": items[0]["key"] if items else None,
                     "top_score": items[0]["score"] if items else None,
                     "verdicts": v})
    return recs, lats


def run_lane_index(idx, questions, key, log, lane):
    recs, lats = [], []
    for q in questions:
        t0 = time.time()
        items = idx.search(q["question"])
        lats.append(time.time() - t0)
        h1, h3, v = judge_items(q["question"], q["answer"], items, key)
        recs.append({"qid": q["qid"], "hit1": h1, "hit3": h3,
                     "top_key": items[0]["key"] if items else None,
                     "verdicts": v})
    return recs, lats


def run_lane_t1doc(mddb, questions, key, log):
    """Oracle lane: judge the question's OWN session T1 doc. Measures the
    distillation ceiling — a miss here means the distiller dropped the
    fact, not that retrieval failed."""
    cache = {}
    recs, lats = [], []
    for q in questions:
        name = q["session"]
        t0 = time.time()
        if name not in cache:
            try:
                doc = mddb.doc_by_session(name)
            except Exception as e:
                doc = None
                log(f"    t1doc fetch error {name}: {e}")
            cache[name] = (doc or {}).get("content_md") or ""
        lats.append(time.time() - t0)
        item = {"key": f"devin-session/{name}", "content": cache[name],
                "score": None}
        h1, h3, v = judge_items(q["question"], q["answer"], [item], key)
        recs.append({"qid": q["qid"], "hit1": h1, "hit3": h3,
                     "top_key": item["key"], "verdicts": v})
    return recs, lats


def summarize(recs, lats):
    n = len(recs)
    return {
        "n": n,
        "hit_at_1": round(100 * sum(r["hit1"] for r in recs) / max(n, 1), 1),
        "hit_at_3": round(100 * sum(r["hit3"] for r in recs) / max(n, 1), 1),
        "lat_p50_s": round(statistics.median(lats), 3) if lats else None,
        "lat_mean_s": round(statistics.mean(lats), 3) if lats else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--gen-fixture", action="store_true")
    ap.add_argument("--per-session", type=int, default=2)
    ap.add_argument("--lanes", nargs="+",
                    default=["mddb", "transcript", "surface", "t1doc"],
                    choices=["mddb", "transcript", "surface", "t1doc"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    if args.gen_fixture:
        gen_fixture(args, print)
        return

    fx = json.loads(args.fixture.read_text())
    key = load_gemini_key()
    if not key:
        sys.exit("no gemini key — set GEMINI_API_KEY or secrets file")

    questions = []
    for s in fx["sessions"]:
        for i, g in enumerate(s["goldens"]):
            if not g.get("grounded", True):
                continue
            questions.append({"qid": f"{s['name']}#{i}", "session": s["name"],
                              "question": g["question"], "answer": g["answer"]})
    if args.limit:
        questions = questions[:args.limit]
    print(f"fixture: {len(fx['sessions'])} sessions, {len(questions)} goldens")

    db = sqlite3.connect(f"file:{SESSIONS_DB}?mode=ro", uri=True)
    out = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "fixture": str(args.fixture), "judge": JUDGE_MODEL,
           "questions": len(questions), "lanes": {}}

    # ---- lane (a): mddb semantic_search, status=active like memory_ops
    if "mddb" in args.lanes:
        mddb = Mddb()
        for rep in range(args.reps):
            recs, lats = run_lane_mddb(mddb, questions, key, print)
            out["lanes"].setdefault("mddb", []).append(
                {"summary": summarize(recs, lats), "records": recs})
            s = out["lanes"]["mddb"][-1]["summary"]
            print(f"  mddb  rep{rep} hit@1={s['hit_at_1']}% hit@3={s['hit_at_3']}% "
                  f"p50={s['lat_p50_s']}s")

    # ---- lane (b): BM25 over raw transcripts of fixture sessions
    if "transcript" in args.lanes:
        idx = KeywordIndex()
        t_bytes = {}
        for s in fx["sessions"]:
            text, raw = extract_transcript(db, s["name"])
            t_bytes[s["name"]] = raw
            idx.add(f"transcript/{s['name']}", text)
        idx.build()
        print(f"  transcript index: {len(idx.chunks)} chunks")
        for rep in range(args.reps):
            recs, lats = run_lane_index(idx, questions, key, print, "transcript")
            out["lanes"].setdefault("transcript", []).append(
                {"summary": summarize(recs, lats), "records": recs})
            s = out["lanes"]["transcript"][-1]["summary"]
            print(f"  trans rep{rep} hit@1={s['hit_at_1']}% hit@3={s['hit_at_3']}% "
                  f"p50={s['lat_p50_s']}s")

    # ---- lane t1doc: oracle — does the session's own T1 doc hold it?
    if "t1doc" in args.lanes:
        mddb_t1 = mddb if "mddb" in args.lanes else Mddb()
        for rep in range(args.reps):
            recs, lats = run_lane_t1doc(mddb_t1, questions, key, print)
            out["lanes"].setdefault("t1doc", []).append(
                {"summary": summarize(recs, lats), "records": recs})
            s = out["lanes"]["t1doc"][-1]["summary"]
            print(f"  t1doc rep{rep} hit@1={s['hit_at_1']}% p50={s['lat_p50_s']}s")

    # ---- lane (c): current recall surface = session-memory.md + compactions
    if "surface" in args.lanes:
        idx = KeywordIndex()
        sm = NOTEBOOK_DIR / "session-memory.md"
        if sm.exists():
            idx.add("surface/session-memory.md", sm.read_text(errors="replace"))
        for f in sorted((NOTEBOOK_DIR / "compactions").glob("*.md")):
            idx.add(f"surface/{f.name}", f.read_text(errors="replace"))
        idx.build()
        print(f"  surface index: {len(idx.chunks)} chunks")
        for rep in range(args.reps):
            recs, lats = run_lane_index(idx, questions, key, print, "surface")
            out["lanes"].setdefault("surface", []).append(
                {"summary": summarize(recs, lats), "records": recs})
            s = out["lanes"]["surface"][-1]["summary"]
            print(f"  surf  rep{rep} hit@1={s['hit_at_1']}% hit@3={s['hit_at_3']}% "
                  f"p50={s['lat_p50_s']}s")

    # ---- coverage + bytes/session
    ids = [r[0] for r in db.execute("select id, hidden from sessions")]
    hidden = {r[0] for r in db.execute("select id from sessions where hidden=1")}
    try:
        mddb2 = mddb if "mddb" in args.lanes else Mddb()
        bank = session_names_in_bank(mddb2)
    except Exception as e:
        bank = set()
        print(f"  coverage skipped: {e}")
    cov = {s for s in ids if s in bank}
    t1 = [s["t1_bytes"] for s in fx["sessions"]]
    tr = [s["transcript_bytes"] for s in fx["sessions"]]
    out["coverage"] = {
        "db_sessions": len(ids), "with_t1_doc": len(cov),
        "pct": round(100 * len(cov) / max(len(ids), 1), 1),
        "hidden_sessions": len(hidden),
        "hidden_with_t1": len(cov & hidden),
        "hidden_pct": round(100 * len(cov & hidden) / max(len(hidden), 1), 1),
        "bank_t1_docs_total": len(bank)}
    out["bytes_per_session"] = {
        "t1_mean": round(statistics.mean(t1)) if t1 else None,
        "t1_median": round(statistics.median(t1)) if t1 else None,
        "transcript_mean": round(statistics.mean(tr)) if tr else None,
        "transcript_median": round(statistics.median(tr)) if tr else None,
        "shrink_median": round(statistics.median(tr) / statistics.median(t1), 1)
        if t1 and tr else None}

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
