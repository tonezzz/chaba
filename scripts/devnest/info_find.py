#!/usr/bin/env python3
"""info_find.py — portable DevNest info-finding planner + source adapters
(card devnest-info-find-skill, Phase 1 conversational skill).

One bounded read-only entry point for the info-find workflow: a query is
classified into an intent, fanned out across the source adapters below,
and merged into ranked results that always carry a source citation.
Every adapter fails safe — an unavailable source is reported, never
raised — and all cache/audit state is isolated per project and per
session so concurrent lanes never share files.

Sources:
    ssot    project SSOT YAML (docs/ssot/**, config/ssot/**) via rg or a
            stdlib fallback walker
    code    repo source files (py/sh/mjs/js/ts/yml), same grep backend
    health  ssot*health*.yml lookup; --probe-health also GETs the URLs
            declared by the matching health files (bounded, read-only)
    mddb    /health preflight then POST /v1/vector-search per collection
            over the tailnet bank (or INFO_FIND_MDDB_URLS override)
    mcp     policy read from **/ssot.mcp-tools.yml — the script never
            calls MCP itself; it emits `deferred` steps describing which
            policy domains the agent layer may invoke
    web     `deferred` by default — an agent layer runs web_search; an
            executable in INFO_FIND_WEB_CMD may also serve as a pluggable
            adapter. --web-json <file> merges external web hits into the
            ranker.

Usage:
    info_find.py plan   --query Q [--session S] [--quick] [--web]
                        [--max-results N] [--project P]
    info_find.py run    --query Q [same] [--format json|md]
                        [--collection C]* [--web-json FILE]
                        [--probe-health]
    info_find.py record --session S --result '<json>'

Layout (isolated per project + session, outside any git tree):
    $INFO_FIND_CACHE_BASE or ~/.cache/devin/info-find/<project>/
        sessions/<session>/<query-hash>.json       plan cache
        sessions/<session>/<query-hash>-result.json merged results
        sessions/<session>/audit.ndjson            audit trail
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CODE_GLOBS = ("*.py", "*.sh", "*.mjs", "*.js", "*.ts", "*.yml")
SSOT_GLOB_PARTS = ("ssot", ".yml")          # path must contain both
SKIP_DIR_PARTS = (".git", "node_modules", ".venv", "out", "runs")

DEFAULT_MDDB_URLS = (
    "http://127.0.0.1:11027,"               # local cms bank, if any
    "http://100.102.134.91:11027"           # idc03 cms bank (tailnet)
)
HEALTH_TIMEOUT = 4
SEARCH_TIMEOUT = 30
MAX_PROBE_URLS = 5

# rank order mirrors the legacy skill: semantic docs, then web, then
# project sources, then code
RANK_ORDER = {"mddb": 0, "web": 1, "ssot": 2, "health": 3,
              "mcp": 4, "code": 5}


# ---------------------------------------------------------------- model

def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _detect_repo_root(cwd: Path) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=str(cwd),
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return cwd


def _detect_project(root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("INFO_FIND_PROJECT")
    if env:
        return env
    try:                                    # worktree-safe: remote name
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=str(root),
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            name = Path(out.stdout.strip().rstrip("/")).stem
            if name:
                return name
    except Exception:
        pass
    return root.name


def _default_session() -> str:
    if os.environ.get("DEVIN_SESSION_ID"):
        return os.environ["DEVIN_SESSION_ID"]
    task = os.environ.get("TASK_DIR")       # devin-dispatch task dir
    if task:
        return Path(task.rstrip("/")).name
    return str(os.getpid())


def _cache_base(project: str) -> Path:
    base = os.environ.get("INFO_FIND_CACHE_BASE")
    root = Path(base) if base else (
        Path(os.environ.get("HOME", "/tmp")) / ".cache" / "devin"
        / "info-find")
    return root / project


# ------------------------------------------------------------- planner

_INTENT_RULES = (
    ("mcp", re.compile(
        r"\b(mcp|mcp-call|mcp-tool|mcp server)\b", re.I)),
    ("service-health", re.compile(
        r"\b(service|down|restart|status|health|container|podman|docker|"
        r"systemctl|logs)\b", re.I)),
    ("ssot", re.compile(
        r"\b(ssot|config/ssot|docs/ssot|focus|jobs|infrastructure|"
        r"services|terminology|improvements|playlive|preset)\b", re.I)),
    ("code", re.compile(
        r"\b(file|function|class|script|code|where|grep|search.*code|"
        r"implementation|bug)\b", re.I)),
    ("web", re.compile(
        r"\b(stock|swap|restructuring|corporate action|dividend|split|"
        r"amalgamation|banpu|settrade|ptt|price jump|jump|news|"
        r"current event|google|web search|web|external)\b", re.I)),
    ("explore", re.compile(
        r"\b(expand|explore|what('| i)s out there|what exists|any tool|"
        r"precedent|alternatives?|options for|compare)\b", re.I)),
)


def classify(query: str) -> str:
    for intent, rx in _INTENT_RULES:
        if rx.search(query):
            return intent
    return "general-doc"


def build_plan(query: str, *, session: str, project: str, quick: bool,
               force_web: bool, max_results: int,
               mddb_collections: list[str]) -> dict:
    intent = "web" if force_web else classify(query)
    plan = {
        "query": query, "session": session, "project": project,
        "intent": intent, "quick": quick, "max_results": max_results,
        "use_mddb": (not quick
                     and intent in ("ssot", "general-doc", "code",
                                    "explore")),
        "use_ssot": intent in ("ssot", "general-doc", "service-health",
                               "code", "explore"),
        "use_grep": intent in ("code", "general-doc", "service-health",
                               "explore"),
        "use_health": intent == "service-health",
        "use_mcp": intent == "mcp",
        "use_web": intent == "web" or (
            intent in ("general-doc", "explore") and force_web)
                or intent == "explore",
        "web_query": (f"{query} github" if intent == "explore"
                      else query),
        "mddb_collections": mddb_collections,
        "ssot_glob": "**/ssot/**/*.yml",
        "code_glob": "**/*.{mjs,js,ts,py,sh,yml}",
        "health_glob": "**/ssot*health*.yml",
        "mcp_policy_glob": "**/ssot.mcp-tools.yml",
    }
    return plan


# --------------------------------------------------------------- grep

def _rg() -> str | None:
    exe = os.environ.get("INFO_FIND_RG", "rg")
    try:
        subprocess.run([exe, "--version"], capture_output=True,
                       timeout=5)
        return exe
    except Exception:
        return None


def _iter_files(root: Path, want, max_files: int = 4000):
    """stdlib fallback file iterator: yield (relpath, Path) matching
    `want(name, rel)`; skips VCS/cache dirs."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIR_PARTS]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(root)
            if want(fn, str(rel)):
                n += 1
                if n > max_files:
                    return
                yield str(rel), p


def _terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]{3,}", query.lower())]


def grep_source(root: Path, query: str, *, glob_pred, limit: int,
                context: int = 0) -> list[dict]:
    """Return [{ref: path:line, excerpt, file}] — rg when present, else a
    stdlib line scan. Whole-phrase match first, then OR of terms."""
    results: list[dict] = []
    exe = _rg()
    phrase = re.escape(query.strip())
    terms = _terms(query)
    or_pat = "|".join(re.escape(t) for t in terms) or phrase
    if exe:
        for pat in (phrase, or_pat):
            try:
                out = subprocess.run(
                    [exe, "-n", "-i", "--no-heading",
                     *(["-C", str(context)] if context else []),
                     "-e", pat, str(root)],
                    capture_output=True, text=True, timeout=30)
            except Exception:
                break
            hits = []
            for line in out.stdout.splitlines():
                m = re.match(r"^(.+?):(\d+):(.*)$", line)
                if not m:
                    continue
                f, ln, txt = m.groups()
                rel = os.path.relpath(f, root)
                if not glob_pred(Path(f).name, rel):
                    continue
                hits.append({"file": rel, "line": int(ln),
                             "text": txt.strip()[:300]})
            if hits:
                break
        results = hits[:limit]
    else:
        rxs = [re.compile(phrase, re.I)]
        if or_pat != phrase:
            rxs.append(re.compile(or_pat, re.I))
        hits = []
        for rel, p in _iter_files(root, glob_pred):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if any(r.search(line) for r in rxs):
                            hits.append({"file": rel, "line": i,
                                         "text": line.strip()[:300]})
                            break
            except OSError:
                continue
            if len(hits) >= limit:
                break
        results = hits
    return [{"ref": f"{h['file']}:{h['line']}", "file": h["file"],
             "excerpt": h["text"], "score": 1.0} for h in results]


def _pred_ssot(fn: str, rel: str) -> bool:
    r = rel.replace("\\", "/")
    return fn.endswith(".yml") and "ssot" in r \
        and "template" not in fn.lower()


def _pred_code(fn: str, rel: str) -> bool:
    return any(fn.endswith(g[1:]) for g in CODE_GLOBS)


def _pred_health(fn: str, rel: str) -> bool:
    return fn.startswith("ssot") and "health" in fn \
        and fn.endswith(".yml")


# ------------------------------------------------------------ adapters

def src_ssot(root: Path, plan: dict) -> dict:
    hits = grep_source(root, plan["query"], glob_pred=_pred_ssot,
                       limit=plan["max_results"] * 3)
    files: dict[str, int] = {}
    for h in hits:
        files[h["file"]] = files.get(h["file"], 0) + 1
    for h in hits:
        h["score"] = 0.5 + min(files[h["file"]], 5) * 0.1
    return {"source": "ssot", "status": "ok",
            "results": hits[:plan["max_results"]]}


def src_code(root: Path, plan: dict) -> dict:
    hits = grep_source(root, plan["query"], glob_pred=_pred_code,
                       limit=plan["max_results"])
    for h in hits:
        h["score"] = 0.4
    return {"source": "code", "status": "ok", "results": hits}


def src_health(root: Path, plan: dict, probe: bool) -> dict:
    hits = grep_source(root, plan["query"], glob_pred=_pred_health,
                       limit=plan["max_results"])
    for h in hits:
        h["score"] = 0.45
    out = {"source": "health", "status": "ok", "results": hits,
           "probes": []}
    if not probe:
        return out
    urls: list[str] = []
    for h in hits:
        f = root / h["file"]
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for u in re.findall(r"https?://[^\s'\"]+", text):
            if u not in urls:
                urls.append(u)
        if len(urls) >= MAX_PROBE_URLS:
            break
    for u in urls[:MAX_PROBE_URLS]:
        try:
            t0 = time.monotonic()
            with urllib.request.urlopen(u, timeout=HEALTH_TIMEOUT) as r:
                code = r.status
            out["probes"].append(
                {"url": u, "status": code,
                 "ms": int((time.monotonic() - t0) * 1000)})
        except urllib.error.HTTPError as e:
            out["probes"].append({"url": u, "status": e.code})
        except Exception as e:
            out["probes"].append({"url": u, "status": "unreachable",
                                  "error": str(e)[:120]})
    return out


def _http_json(url: str, *, body=None, timeout: int):
    if body is None:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _mddb_bases() -> list[str]:
    env = os.environ.get("INFO_FIND_MDDB_URLS") \
        or os.environ.get("MDDB_REST_URLS")
    if env:
        return [b.rstrip("/") for b in env.split(",") if b.strip()]
    single = os.environ.get("MDDB_REST_URL")
    if single:
        return [single.rstrip("/").removesuffix("/v1")]
    return [b.strip().rstrip("/")
            for b in DEFAULT_MDDB_URLS.split(",") if b.strip()]


def src_mddb(plan: dict) -> dict:
    """health preflight -> per-collection /v1/vector-search. Every bank
    or collection failure is recorded, never raised."""
    base = None
    errors = []
    for cand in _mddb_bases():
        try:
            with urllib.request.urlopen(f"{cand}/health",
                                        timeout=HEALTH_TIMEOUT) as r:
                if r.status == 200:
                    base = cand
                    break
        except Exception as e:
            errors.append(f"{cand}: {str(e)[:80]}")
    if not base:
        return {"source": "mddb", "status": "unavailable",
                "error": "; ".join(errors) or "no bank responded",
                "results": []}
    results, coll_errors = [], []
    for coll in plan["mddb_collections"]:
        try:
            out = _http_json(
                f"{base}/v1/vector-search",
                body={"collection": coll, "query": plan["query"],
                      "topK": plan["max_results"], "includeContent": True},
                timeout=SEARCH_TIMEOUT)
        except Exception as e:
            coll_errors.append(f"{coll}: {str(e)[:80]}")
            continue
        for h in out.get("results", []):
            doc = h.get("document") or {}
            meta = doc.get("meta") or {}
            title = (meta.get("title") or meta.get("topic")
                     or meta.get("rel_path") or [doc.get("key")])[0]
            results.append({
                "ref": f"mddb://{coll}/{doc.get('key')}",
                "file": str(title),
                "excerpt": (doc.get("contentMd") or "")[:300],
                "score": float(h.get("score") or 0),
                "meta": {"collection": coll,
                         **{k: v[0] for k, v in meta.items()
                            if isinstance(v, list) and v}},
            })
    results.sort(key=lambda r: -r["score"])
    status = "ok" if results or not coll_errors else "degraded"
    out = {"source": "mddb", "status": status, "bank": base,
           "results": results[:plan["max_results"]]}
    if coll_errors:
        out["errors"] = coll_errors
        if results:
            out["status"] = "degraded"
    return out


def src_mcp(root: Path, plan: dict) -> dict:
    """Parse the first **/ssot.mcp-tools.yml and emit deferred steps for
    the agent layer — the adapter never calls MCP itself."""
    policy_file = None
    for p in root.rglob("ssot.mcp-tools.yml"):
        policy_file = p
        break
    if not policy_file:
        return {"source": "mcp", "status": "unavailable",
                "error": "no ssot.mcp-tools.yml in checkout",
                "results": []}
    try:
        text = policy_file.read_text(encoding="utf-8",
                                     errors="replace")
    except OSError as e:
        return {"source": "mcp", "status": "unavailable",
                "error": str(e), "results": []}
    domains = []
    in_policy = False
    cur = None
    for line in text.splitlines():
        if re.match(r"^policy:\s*$", line):
            in_policy = True
            continue
        if in_policy and re.match(r"^\S", line):
            break                                  # left the block
        m = re.match(r"^  (\w[\w-]*):\s*$", line) if in_policy else None
        if m:
            cur = {"domain": m.group(1), "primary": None}
            domains.append(cur)
            continue
        m = (re.match(r"^\s+primary:\s*(\S+)\s*$", line)
             if in_policy and cur else None)
        if m and cur and cur["primary"] is None:
            cur["primary"] = m.group(1)
    q = plan["query"].lower()
    for d in domains:
        d["relevant"] = any(
            t in q for t in d["domain"].lower().split("_") if len(t) > 3)
    rel = str(policy_file.relative_to(root))
    steps = [{"rung": "mcp", "policy_file": rel,
              "instruction": "agent calls mcp_list_tools then "
                             "mcp_call_tool honoring policy.<domain>",
              "domains": domains}]
    return {"source": "mcp", "status": "deferred", "results": [],
            "deferred": steps,
            "note": "agent layer executes MCP calls; adapter is "
                    "policy-read only"}


def src_web(plan: dict) -> dict:
    """Web rung: a pluggable INFO_FIND_WEB_CMD adapter, else deferred to
    the agent layer's web_search tool."""
    cmd = os.environ.get("INFO_FIND_WEB_CMD")
    if cmd:
        try:
            out = subprocess.run(
                [cmd, plan["web_query"]], capture_output=True,
                text=True, timeout=60)
            hits = []
            for line in out.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    h = json.loads(line)
                except json.JSONDecodeError:
                    h = {"title": line[:200], "url": ""}
                hits.append({"ref": h.get("url") or h.get("title"),
                             "file": h.get("title", "")[:120],
                             "excerpt": (h.get("excerpt")
                                         or h.get("snippet") or "")[:300],
                             "score": float(h.get("score") or 0.6)})
            return {"source": "web",
                    "status": "ok" if out.returncode == 0 else "degraded",
                    "results": hits[:plan["max_results"]]}
        except Exception as e:
            return {"source": "web", "status": "unavailable",
                    "error": str(e)[:120], "results": []}
    return {"source": "web", "status": "deferred", "results": [],
            "deferred": [{
                "rung": "web", "query": plan["web_query"],
                "num_results": plan["max_results"],
                "instruction": "agent runs web_search; for explore "
                               "intents run the GitHub precedent query "
                               "first, then the bare query"}],
            "note": "no INFO_FIND_WEB_CMD configured"}


# ------------------------------------------------------------- merger

def merge_results(source_outs: list[dict], max_results: int,
                  extra: list[dict] | None = None) -> list[dict]:
    """Dedupe by (source, ref); rank by RANK_ORDER then score desc."""
    seen, merged = set(), []
    outs = list(source_outs)
    if extra:
        outs.append({"source": "web", "status": "ok", "results": extra})
    for out in outs:
        src = out.get("source", "?")
        for r in out.get("results") or []:
            key = (src, r.get("ref"))
            if key in seen or not r.get("ref"):
                continue
            seen.add(key)
            merged.append({
                "source": src, "ref": r["ref"],
                "excerpt": r.get("excerpt", ""),
                "score": r.get("score", 0),
                **({"meta": r["meta"]} if r.get("meta") else {}),
            })
    merged.sort(key=lambda r: (RANK_ORDER.get(r["source"], 9),
                               -r["score"]))
    for i, r in enumerate(merged, 1):
        r["rank"] = i
    return merged[: max_results * 4]


def run_plan(root: Path, plan: dict, *, probe_health: bool,
             web_extra: list[dict] | None) -> dict:
    outs: list[dict] = []
    for flag, fn in (
        ("use_mddb", lambda: src_mddb(plan)),
        ("use_ssot", lambda: src_ssot(root, plan)),
        ("use_health", lambda: src_health(root, plan, probe_health)),
        ("use_grep", lambda: src_code(root, plan)),
        ("use_mcp", lambda: src_mcp(root, plan)),
        ("use_web", lambda: src_web(plan)),
    ):
        if not plan.get(flag):
            continue
        name = fn.__name__ if hasattr(fn, "__name__") else flag
        try:
            outs.append(fn())
        except Exception as e:                     # belt + suspenders
            outs.append({"source": flag.removeprefix("use_"),
                         "status": "unavailable",
                         "error": f"{name}: {str(e)[:120]}",
                         "results": []})
    results = merge_results(outs, plan["max_results"], web_extra)
    sources = {o["source"]: {
        "status": o.get("status"), "count": len(o.get("results") or []),
        **({"error": o["error"]} if o.get("error") else {}),
        **({"deferred": o["deferred"]} if o.get("deferred") else {}),
        **({"note": o["note"]} if o.get("note") else {}),
    } for o in outs}
    return {"plan": plan, "results": results, "sources": sources,
            "unavailable": [o["source"] for o in outs
                            if o.get("status") == "unavailable"],
            "deferred": [o["source"] for o in outs
                         if o.get("status") == "deferred"]}


# --------------------------------------------------------------- audit

def _session_dir(project: str, session: str) -> Path:
    d = _cache_base(project) / "sessions" / session
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audit(project: str, session: str, rec: dict):
    d = _session_dir(project, session)
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **rec}
    with open(d / "audit.ndjson", "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def _fmt_md(out: dict) -> str:
    p = out["plan"]
    lines = [f"# info-find: {p['query']}",
             f"intent={p['intent']} project={p['project']} "
             f"session={p['session']}", ""]
    if out["unavailable"]:
        lines.append("unavailable: " + ", ".join(out["unavailable"]))
    if out["deferred"]:
        lines.append("deferred (agent rungs): "
                     + ", ".join(out["deferred"]))
    lines.append("")
    for r in out["results"]:
        lines.append(f"{r['rank']}. [{r['source']}] {r['ref']} "
                     f"(score {r['score']:.2f})")
        if r.get("excerpt"):
            lines.append(f"   {r['excerpt'][:160]}")
    lines.append("")
    lines.append("sources: " + json.dumps(
        {k: v["status"] for k, v in out["sources"].items()}))
    return "\n".join(lines)


# ---------------------------------------------------------------- cli

def _common(ap: argparse.ArgumentParser):
    ap.add_argument("--query")
    ap.add_argument("--session")
    ap.add_argument("--project")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--web", action="store_true")
    ap.add_argument("--max-results", type=int, default=5)
    ap.add_argument("--collection", action="append", default=[])
    ap.add_argument("--cache-base")


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="info_find.py",
                                 description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        _common(sub.add_parser(name))
    sub.choices["run"].add_argument("--format",
                                    choices=["json", "md"],
                                    default="json")
    sub.choices["run"].add_argument("--probe-health",
                                    action="store_true")
    sub.choices["run"].add_argument("--web-json")
    rec = sub.add_parser("record")
    rec.add_argument("--session", required=True)
    rec.add_argument("--project")
    rec.add_argument("--result", required=True)
    args = ap.parse_args(argv)

    if getattr(args, "cache_base", None):
        os.environ["INFO_FIND_CACHE_BASE"] = args.cache_base

    root = _detect_repo_root(Path.cwd())
    project = _detect_project(root, getattr(args, "project", None))

    if args.cmd == "record":
        _audit(project, args.session,
               {"kind": "result",
                "result": args.result})
        print(str(_session_dir(project, args.session)
                  / "audit.ndjson"))
        return 0

    if not args.query:
        ap.error("--query is required for plan/run")

    session = args.session or _default_session()
    colls = args.collection or [
        c.strip() for c in os.environ.get(
            "INFO_FIND_MDDB_COLLECTIONS",
            f"{project}-docs,{project}-lessons,infrastructure-ssot")
        .split(",") if c.strip()]
    plan = build_plan(args.query, session=session, project=project,
                      quick=args.quick, force_web=args.web,
                      max_results=args.max_results,
                      mddb_collections=colls)
    sdir = _session_dir(project, session)
    plan["cache_dir"] = str(sdir)
    plan["audit_path"] = str(sdir / "audit.ndjson")
    (sdir / f"{_sha(args.query)}.json").write_text(
        json.dumps(plan, indent=1))
    _audit(project, session,
           {"kind": "plan", "query": args.query,
            "intent": plan["intent"]})

    if args.cmd == "plan":
        print(json.dumps(plan, indent=1))
        return 0

    web_extra = None
    if args.web_json:
        try:
            web_extra = json.loads(Path(args.web_json).read_text())
            if isinstance(web_extra, dict):
                web_extra = web_extra.get("results") or []
        except Exception as e:
            web_extra = None
            print(f"warn: --web-json unreadable: {e}",
                  file=sys.stderr)

    out = run_plan(root, plan, probe_health=args.probe_health,
                   web_extra=web_extra)
    (sdir / f"{_sha(args.query)}-result.json").write_text(
        json.dumps(out, indent=1))
    _audit(project, session, {
        "kind": "run", "query": args.query, "intent": plan["intent"],
        "counts": {k: v["count"] for k, v in out["sources"].items()},
        "unavailable": out["unavailable"],
        "deferred": out["deferred"]})
    if args.format == "md":
        print(_fmt_md(out))
    else:
        print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
