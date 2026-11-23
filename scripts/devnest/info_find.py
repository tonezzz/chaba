#!/usr/bin/env python3
"""info_find.py — shared planner + source adapters for the portable
info-find capability (card devnest-info-find-skill / DEV-0230).

One stdlib-only module shared by every surface:

  - the portable Agent Skill (.agents/skills/info-find/) — a
    conversational agent runs `plan`, executes the agent-tool sources
    (mcp call, web, github precedent) with its own tools, and merges
    them over the local sources this module executes directly;
  - the read-only OpenCode lane profile
    (evals/opencode-lane/profiles/info-find/) — its bash allowlist
    permits ONLY this script;
  - a future queued research executor — import the same functions,
    never re-implement routing.

Contract:
  plan      query -> intent -> per-source use_* flags + search specs.
  run       execute the locally-runnable sources; emit one unified,
            ranked, cited result JSON. Sources that need agent tools
            are 'deferred' (a conversational agent merges them) or
            'unavailable' (--offline).
  isolation cache + audit under
            ~/.cache/devin/info-find/<project>/sessions/<session>/ —
            project from the checkout basename, session from
            --session / $DEVIN_SESSION_ID / pid; both are sanitized so
            no session can escape or share another's dir.
  fail-safe every adapter returns a status envelope; a source that
            raises, times out or is denied is reported in `sources`
            and never crashes the run or starves the other sources.

CLI:
    plan  --query Q [--session S] [--project P] [--root DIR]
          [--quick] [--web] [--max-results N]
    run   --query Q [same] [--sources a,b,c] [--offline]
    record --session S --result '<json>' [--project P] [--root DIR]
    mddb-health [--url U]
    mcp-policy [domain] [--root DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "devnest.info-find/v1"
REPO = Path(__file__).resolve().parents[2]

# all sources the capability knows; local = runnable inside this
# process, agent = need the invoking agent's own tools
SOURCES_LOCAL = ("ssot", "code", "health", "mddb", "mcp")
SOURCES_AGENT = ("web", "github")
SOURCES_ALL = SOURCES_LOCAL + SOURCES_AGENT

# rank order (SKILL step 12): semantic docs first, official web second,
# github precedent third, SSOT fourth, code last
RANK = {"mddb": 0, "web": 1, "github": 2, "ssot": 3, "health": 3,
        "mcp": 4, "code": 5}

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"       # planner did not route to it
STATUS_DEFERRED = "deferred"     # needs an agent tool the caller has
STATUS_UNAVAILABLE = "unavailable"  # reachable check failed / denied
STATUS_ERROR = "error"           # adapter raised

INTENTS = ("mcp", "service-health", "ssot", "code", "web", "explore",
           "general-doc")

DEFAULT_MDDB_URL = os.environ.get(
    "INFO_FIND_MDDB_URL", "http://100.102.134.91:11027").rstrip("/")
DEFAULT_MDDB_COLLECTIONS = [
    c for c in os.environ.get(
        "INFO_FIND_MDDB_COLLECTIONS",
        "infrastructure-ssot,chaba-docs,chaba-lessons,devin-kb"
    ).split(",") if c.strip()]

MDDB_HEALTH_TIMEOUT = 5
MDDB_SEARCH_TIMEOUT = 15
MAX_FILE_BYTES = 512 * 1024
MAX_RESULTS_PER_SOURCE = 8

# dirs never searched — keep local adapters cheap and inside the
# project tree
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
             "dist", "build", ".cache", ".next", ".idea", ".tox",
             "coverage", ".mypy_cache"}
SKIP_FILES_RE = re.compile(r"template.*\.yml$|\.min\.js$|package-lock"
                           r"|yarn\.lock|\.pyc$")

CODE_EXTS = (".mjs", ".js", ".ts", ".py", ".sh", ".yml", ".yaml")

_STOP = {"the", "a", "an", "and", "or", "for", "with", "what", "whats",
         "is", "are", "was", "were", "how", "do", "does", "did", "can",
         "we", "our", "you", "your", "to", "of", "in", "on", "at",
         "it", "its", "that", "this", "any", "all", "use", "used",
         "tell", "me", "about", "show", "find", "get", "list", "give",
         "where", "when", "which", "who", "why", "there", "here",
         "from", "into", "out", "up", "down", "have", "has", "had",
         "be", "been", "being", "not", "no", "yes", "if", "then",
         "than", "so", "such", "as", "by"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(s, default: str) -> str:
    """Sanitize a project/session id into a single safe path component.
    '..', separators and empty results collapse to the default — no
    session may land in or traverse into another's directory."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(s or "")).strip(".-")
    if not s or s == "..":
        s = default
    return s[:64]


def project_of(root: Path) -> str:
    """Project = repo name. In a linked worktree the `.git` pointer file
    names the main checkout (`<main>/.git/worktrees/<name>`), so all
    worktrees of one repo share the project's cache namespace while
    sessions stay isolated beneath it."""
    try:
        git = root / ".git"
        if git.is_file():
            for ln in git.read_text().splitlines():
                if ln.startswith("gitdir:"):
                    gd = Path(ln.split(":", 1)[1].strip())
                    if gd.parent.name == "worktrees" and \
                            gd.parents[1].name == ".git":
                        return _safe_name(gd.parents[2].name, "unknown")
    except (OSError, IndexError):
        pass
    return _safe_name(root.resolve().name, "unknown")


def session_of(cli_session: str | None) -> str:
    return _safe_name(
        cli_session or os.environ.get("DEVIN_SESSION_ID")
        or str(os.getpid()), "anon")


def cache_base(project: str) -> Path:
    return Path(os.environ.get(
        "INFO_FIND_CACHE",
        str(Path.home() / ".cache" / "devin" / "info-find"))) / project


def session_dir(project: str, session: str) -> Path:
    return cache_base(project) / "sessions" / session


def query_terms(query: str, limit: int = 8) -> list:
    terms, seen = [], set()
    for w in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", query.lower()):
        if len(w) < 3 or w in _STOP or w in seen:
            continue
        seen.add(w)
        terms.append(w)
        if len(terms) >= limit:
            break
    return terms or [query.lower()[:40]]


def _term_re(query: str):
    return re.compile("|".join(re.escape(t) for t in query_terms(query)),
                      re.IGNORECASE)


# ------------------------------------------------------------ intent

def classify(query: str) -> str:
    """query -> intent. Same routing table as the original
    .devin/skills/info-find planner plus the documented `explore`
    intent (feature/option expansion -> internal first, then the
    GitHub precedent rung, then generic web)."""
    q = query.lower()
    if re.search(r"(\b|^)(mcp|mcp-call|mcp-tool|mcp server)(\b|$)", q):
        return "mcp"
    if re.search(
        r"(\b|^)(service|down|restart|status|health|container|podman"
        r"|docker|systemctl|logs)(\b|$)", q):
        return "service-health"
    if re.search(
        r"(\b|^)(stock|swap|restructuring|corporate action|dividend"
        r"|split|amalgamation|settrade|price jump|news|current event"
        r"|google|web search|web|external)(\b|$)", q):
        return "web"
    if re.search(
        r"(\b|^)(ssot|config/ssot|docs/ssot|focus|jobs|infrastructure"
        r"|services|terminology|health|improvements|playlive|preset)"
        r"(\b|$)", q):
        return "ssot"
    if re.search(
        r"(what exists|what's out there|whats out there|any tool|"
        r"any library|any option|options? for|alternatives?|"
        r"standard procedure|precedent|who else|prior art|explore|"
        r"can we use|could we use|should we adopt|expand|extend)"
        , q):
        return "explore"
    if re.search(
        r"(\b|^)(file|function|class|script|code|where|grep|"
        r"search.*code|implementation|bug)(\b|$)", q):
        return "code"
    return "general-doc"


def build_plan(query: str, session: str, project: str, *,
               quick: bool = False, force_web: bool = False,
               max_results: int = 5) -> dict:
    intent = "web" if force_web else classify(query)
    use = {
        "use_mddb": not quick and intent in ("ssot", "general-doc",
                                             "code", "explore"),
        "use_ssot": intent in ("ssot", "general-doc", "service-health",
                               "code", "explore"),
        "use_grep": intent in ("code", "general-doc", "service-health",
                               "explore"),
        "use_health": intent == "service-health",
        "use_mcp": intent == "mcp",
        # explore adds the GitHub precedent rung between internal
        # sources and generic web (SKILL step 4a)
        "use_github": intent == "explore" and not quick,
        "use_web": intent in ("web", "explore") and not quick,
    }
    return {
        "schema": SCHEMA,
        "query": query,
        "session": session,
        "project": project,
        "intent": intent,
        **use,
        "web_query": query,
        "quick": quick,
        "max_results": max_results,
        "cache_dir": str(session_dir(project, session)),
        "audit_path": str(session_dir(project, session)
                          / "audit.ndjson"),
        "ssot_glob": "**/ssot/**/*.yml",
        "code_glob": "**/*.{" + ",".join(e.lstrip(".")
                                        for e in CODE_EXTS) + "}",
        "health_glob": "**/ssot*health*.yml",
        "mcp_policy_glob": "**/ssot.mcp-tools.yml",
        "mddb_url": DEFAULT_MDDB_URL,
        "mddb_collections": list(DEFAULT_MDDB_COLLECTIONS),
    }


# --------------------------------------------------------- adapters

def _env(source: str, status: str, **kw) -> dict:
    return {"source": source, "status": status, "results": [], **kw}


def _walk_files(root: Path, want) -> "list[Path]":
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if SKIP_FILES_RE.search(fn):
                continue
            p = Path(dirpath) / fn
            if want(p):
                out.append(p)
    return out


def _scan(p: Path, rx, root: Path, hits: list) -> None:
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return
        with p.open("r", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if rx.search(line):
                    hits.append({"path": str(p.relative_to(root)),
                                 "line": i,
                                 "excerpt": line.strip()[:300]})
    except (OSError, UnicodeError):
        return


def _grep_results(root: Path, want, query: str, max_results: int) -> list:
    rx = _term_re(query)
    hits: list = []
    for p in _walk_files(root, want):
        _scan(p, rx, root, hits)
        if len(hits) >= 400:
            break
    # group by file: relevance = match count, keep first excerpt
    by_file: dict = {}
    for h in hits:
        d = by_file.setdefault(h["path"], {"path": h["path"],
                                           "excerpt": h["excerpt"],
                                           "lines": [], "count": 0})
        d["count"] += 1
        if len(d["lines"]) < 5:
            d["lines"].append(h["line"])
    ranked = sorted(by_file.values(), key=lambda d: -d["count"])
    return ranked[:max_results]


def ad_ssot(root: Path, query: str, plan: dict) -> dict:
    def want(p: Path) -> bool:
        rel = p.relative_to(root).as_posix()
        return p.suffix in (".yml", ".yaml") and "/ssot/" in "/" + rel
    res = _grep_results(root, want, query, plan["max_results"])
    for r in res:
        r["citation"] = {"path": r["path"], "lines": r.pop("lines")}
    return _env("ssot", STATUS_OK, results=res, count=len(res))


def ad_code(root: Path, query: str, plan: dict) -> dict:
    res = _grep_results(root, lambda p: p.suffix in CODE_EXTS, query,
                        plan["max_results"])
    for r in res:
        r["citation"] = {"path": r["path"], "lines": r.pop("lines")}
    return _env("code", STATUS_OK, results=res, count=len(res))


def ad_health(root: Path, query: str, plan: dict) -> dict:
    def want(p: Path) -> bool:
        n = p.name.lower()
        return p.suffix in (".yml", ".yaml") and "ssot" in n and (
            "health" in n or "services" in n)
    res = _grep_results(root, want, query, plan["max_results"])
    for r in res:
        r["citation"] = {"path": r["path"], "lines": r.pop("lines")}
    return _env("health", STATUS_OK, results=res, count=len(res))


def mddb_health(url: str = DEFAULT_MDDB_URL,
                timeout: int = MDDB_HEALTH_TIMEOUT) -> dict:
    try:
        with urllib.request.urlopen(f"{url}/health",
                                    timeout=timeout) as r:
            body = r.read()[:4096].decode("utf-8", "replace")
        return {"status": STATUS_OK, "http": 200, "body": body[:500]}
    except urllib.error.HTTPError as e:
        return {"status": STATUS_UNAVAILABLE,
                "reason": f"http {e.code}"}
    except Exception as e:
        return {"status": STATUS_UNAVAILABLE,
                "reason": f"{type(e).__name__}: {e}"}


def ad_mddb(root: Path, query: str, plan: dict) -> dict:
    h = mddb_health(plan["mddb_url"])
    if h["status"] != STATUS_OK:
        return _env("mddb", STATUS_UNAVAILABLE,
                    reason=h.get("reason", "health check failed"))
    results = []
    for coll in plan["mddb_collections"]:
        try:
            req = urllib.request.Request(
                f"{plan['mddb_url']}/v1/search",
                data=json.dumps({"collection": coll, "query": query,
                                 "limit": plan["max_results"]}).encode(),
                headers={"content-type": "application/json"},
                method="POST")
            with urllib.request.urlopen(
                    req, timeout=MDDB_SEARCH_TIMEOUT) as r:
                docs = json.loads(r.read())
        except urllib.error.HTTPError as e:
            # a missing collection is a skip, not a failure of the
            # source — the plane may simply not carry it
            if e.code in (400, 404):
                continue
            return _env("mddb", STATUS_UNAVAILABLE,
                        reason=f"http {e.code}", results=results,
                        count=len(results))
        except Exception as e:
            return _env("mddb", STATUS_UNAVAILABLE,
                        reason=f"{type(e).__name__}: {e}",
                        results=results, count=len(results))
        for d in docs or []:
            meta = d.get("meta") or {}

            def m1(k):   # meta values are single-element lists
                v = meta.get(k)
                return v[0] if isinstance(v, list) and v else v

            text = (d.get("contentMd") or d.get("text")
                    or d.get("content") or "")
            path = m1("original_path") or m1("path") or d.get("key")
            results.append({
                "path": path or coll,
                "title": m1("title"),
                "excerpt": str(text).strip().replace("\n", " ")[:300],
                "relevance": d.get("score") or d.get("distance"),
                "citation": {"collection": coll,
                             "id": d.get("id") or d.get("key"),
                             "path": path}})
    return _env("mddb", STATUS_OK, results=results, count=len(results))


def find_policy_file(root: Path) -> Path | None:
    for p in _walk_files(root, lambda p: p.name == "ssot.mcp-tools.yml"):
        return p
    return None


def mcp_policy_section(root: Path, domain: str | None) -> dict:
    """Extract policy.<domain> blocks from **/ssot.mcp-tools.yml with a
    structural slice (top-level `policy:` then `  <domain>:` keys) — no
    YAML dependency and no whole-file reads by callers."""
    p = find_policy_file(root)
    if not p:
        return _env("mcp", STATUS_UNAVAILABLE,
                    reason="no ssot.mcp-tools.yml under root")
    lines = p.read_text(errors="replace").splitlines()
    in_policy = False
    domains: dict = {}
    cur = None
    for ln in lines:
        if re.match(r"^policy:\s*$", ln):
            in_policy = True
            continue
        if in_policy:
            if ln and not ln.startswith((" ", "#")):
                break                      # left the policy block
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", ln)
            if m:
                cur = m.group(1)
                domains[cur] = []
                continue
            if cur:
                domains[cur].append(ln)
    rel = str(p.relative_to(root))
    if domain:
        if domain not in domains:
            return _env("mcp", STATUS_UNAVAILABLE,
                        reason=f"no policy.{domain} in {rel}",
                        known=sorted(domains))
        return {"source": "mcp", "status": STATUS_OK,
                "domain": domain,
                "citation": {"path": rel, "section":
                             f"policy.{domain}"},
                "policy": "\n".join(domains[domain]).strip()}
    return {"source": "mcp", "status": STATUS_OK,
            "citation": {"path": rel, "section": "policy"},
            "domains": sorted(domains)}


def ad_mcp(root: Path, query: str, plan: dict) -> dict:
    """MCP discovery is two-layer: local policy extraction (this
    adapter) + the tool list/call itself, which only the agent can do.
    The envelope reports the policy outcome and marks the live call
    deferred so the conversational layer merges it."""
    pol = mcp_policy_section(root, None)
    if pol["status"] != STATUS_OK:
        return _env("mcp", pol["status"], reason=pol.get("reason"))
    rx = _term_re(query)
    hits = [d for d in pol.get("domains", []) if rx.search(d)]
    if not hits:
        hits = pol.get("domains", [])[:3]
    res = [{"path": pol["citation"]["path"],
            "excerpt": f"policy.{d}",
            "citation": {"path": pol["citation"]["path"],
                         "section": f"policy.{d}"}}
           for d in hits]
    env = _env("mcp", STATUS_OK, results=res, count=len(res))
    env["call"] = {"status": STATUS_DEFERRED,
                   "tool": "mcp_list_tools + mcp_call_tool",
                   "note": "invoke the chosen server via the agent's "
                           "own MCP tools; policy domain(s) above are "
                           "the allowlist boundary"}
    return env


def _deferred(source: str, spec: dict) -> dict:
    return _env(source, STATUS_DEFERRED, spec=spec)


ADAPTERS = {
    "ssot": ad_ssot,
    "code": ad_code,
    "health": ad_health,
    "mddb": ad_mddb,
    "mcp": ad_mcp,
}

AGENT_SPECS = {
    "web": {"tool": "web_search", "args": ["query", "num_results"],
            "note": "cache raw JSON in the session dir; summarize top "
                    "3-5 with url citations"},
    "github": {"tool": "web_search/github MCP search_code+search_issues",
               "args": ["query"],
               "note": "explore precedent rung: per project collect "
                       "name/what/why/fit/maturity; findings go to the "
                       "card via board-api comment"},
}


def wanted_sources(plan: dict) -> list:
    flag = {"mddb": plan["use_mddb"], "ssot": plan["use_ssot"],
            "code": plan["use_grep"], "health": plan["use_health"],
            "mcp": plan["use_mcp"], "web": plan["use_web"],
            "github": plan["use_github"]}
    return [s for s in SOURCES_ALL if flag.get(s)]


def rank(envelopes: list, max_results: int) -> list:
    """Dedupe by citation path/id and order by source rank then the
    adapter's own relevance — the citation contract is what makes a
    result gradeable."""
    seen, out = set(), []
    for env in sorted(envelopes, key=lambda e: RANK[e["source"]]):
        for r in env.get("results") or []:
            cit = r.get("citation") or {}
            key = str(cit.get("path") or cit.get("id")
                      or r.get("path") or r.get("excerpt", "")[:60])
            if key in seen:
                continue
            seen.add(key)
            out.append({"source": env["source"], **r})
    return out[:max(10, max_results)]


def _resolved_ref(results: list) -> str | None:
    """Top ranked citation, used as the resolved_ref in the time-to-find audit."""
    if not results:
        return None
    top = results[0]
    cit = top.get("citation") or {}
    return (str(cit.get("path") or cit.get("id") or top.get("path")
                or top.get("excerpt", "")[:60]) or None)


def audit_append(audit_path: str, rec: dict) -> None:
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"t": now_iso(), **rec}) + "\n")


def run(query: str, session: str, project: str, root: Path, *,
        quick: bool = False, force_web: bool = False,
        max_results: int = 5, sources: list | None = None,
        offline: bool = False) -> dict:
    plan = build_plan(query, session, project, quick=quick,
                      force_web=force_web, max_results=max_results)
    want = sources or wanted_sources(plan)
    routed = set(wanted_sources(plan))
    envelopes, statuses = [], {}
    for s in SOURCES_ALL:
        if s not in want:
            statuses[s] = {"status": STATUS_SKIPPED,
                           "reason": "not in --sources"
                           if s in routed else "not routed by planner"}
            continue
        t0 = time.time()
        if s in ADAPTERS:
            try:
                env = ADAPTERS[s](root, query, plan)
            except Exception as e:   # fail-safe: never let one source
                env = _env(s, STATUS_ERROR,          # kill the run
                           reason=f"{type(e).__name__}: {e}")
            envelopes.append(env)
            statuses[s] = {"status": env["status"],
                           "count": env.get("count", 0),
                           **({"reason": env["reason"]}
                              if env.get("reason") else {})}
        else:
            st = STATUS_UNAVAILABLE if offline else STATUS_DEFERRED
            statuses[s] = {"status": st,
                           "spec": AGENT_SPECS[s]}
            if not offline:
                envelopes.append(_deferred(s, AGENT_SPECS[s]))
        statuses[s]["elapsed_ms"] = int((time.time() - t0) * 1000)
    results = rank(envelopes, max_results)
    Path(plan["cache_dir"]).mkdir(parents=True, exist_ok=True)
    out = {"schema": SCHEMA, "query": query, "intent": plan["intent"],
           "project": project, "session": session,
           "read_only": True, "plan": plan, "sources": statuses,
           "results": results, "cache_dir": plan["cache_dir"],
           "audit_path": plan["audit_path"]}
    key = hashlib.sha256(query.encode()).hexdigest()[:16]
    (Path(plan["cache_dir"]) / f"{key}-result.json").write_text(
        json.dumps(out, indent=1))
    # Phase D time-to-find telemetry: the per-source elapsed_ms already lived
    # in the result cache; surface the totals + resolved citation in the audit
    # so capture-metrics.py can aggregate without a second telemetry path.
    audit_append(plan["audit_path"],
                 {"kind": "run", "query": query,
                  "intent": plan["intent"],
                  "statuses": {s: v.get("status")
                               for s, v in statuses.items()},
                  "result_count": len(results),
                  "total_elapsed_ms": sum(v.get("elapsed_ms", 0)
                                          for v in statuses.values()),
                  "elapsed_by_source": {
                      s: v["elapsed_ms"] for s, v in statuses.items()
                      if "elapsed_ms" in v},
                  "source_sequence": [s for s in SOURCES_ALL
                                      if statuses.get(s, {}).get("status")
                                      != STATUS_SKIPPED],
                  "resolved_ref": _resolved_ref(results)})
    return out


# ---------------------------------------------------------------- cli

def _base_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--session")
    ap.add_argument("--project")
    ap.add_argument("--root", default=".")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--web", action="store_true")
    ap.add_argument("--max-results", type=int, default=5)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="info_find.py",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--query", required=True)
    _base_args(p)
    r = sub.add_parser("run")
    r.add_argument("--query", required=True)
    r.add_argument("--sources")
    r.add_argument("--offline", action="store_true")
    _base_args(r)
    rec = sub.add_parser("record")
    rec.add_argument("--session", required=True)
    rec.add_argument("--result", required=True)
    rec.add_argument("--project")
    rec.add_argument("--root", default=".")
    mh = sub.add_parser("mddb-health")
    mh.add_argument("--url", default=DEFAULT_MDDB_URL)
    mp = sub.add_parser("mcp-policy")
    mp.add_argument("domain", nargs="?")
    mp.add_argument("--root", default=".")
    args = ap.parse_args(argv)

    if args.cmd in ("plan", "run"):
        root = Path(args.root).resolve()
        project = _safe_name(
            args.project or os.environ.get("INFO_FIND_PROJECT"), "") \
            or project_of(root)
        session = session_of(args.session)
    if args.cmd == "plan":
        plan = build_plan(args.query, session, project,
                          quick=args.quick, force_web=args.web,
                          max_results=args.max_results)
        Path(plan["cache_dir"]).mkdir(parents=True, exist_ok=True)
        audit_append(plan["audit_path"],
                     {"kind": "plan", "query": args.query,
                      "intent": plan["intent"]})
        print(json.dumps(plan, indent=1))
        return 0
    if args.cmd == "run":
        srcs = [s.strip() for s in (args.sources or "").split(",")
                if s.strip()] or None
        bad = [s for s in (srcs or []) if s not in SOURCES_ALL]
        if bad:
            print(f"unknown source(s): {bad} — have {SOURCES_ALL}",
                  file=sys.stderr)
            return 2
        out = run(args.query, session, project, root,
                  quick=args.quick, force_web=args.web,
                  max_results=args.max_results, sources=srcs,
                  offline=args.offline)
        print(json.dumps(out, indent=1))
        return 0
    if args.cmd == "record":
        root = Path(args.root).resolve()
        project = _safe_name(
            args.project or os.environ.get("INFO_FIND_PROJECT"), "") \
            or project_of(root)
        session = session_of(args.session)
        d = session_dir(project, session)
        d.mkdir(parents=True, exist_ok=True)
        audit_append(str(d / "audit.ndjson"),
                     {"kind": "result", "result": args.result})
        print(str(d / "audit.ndjson"))
        return 0
    if args.cmd == "mddb-health":
        print(json.dumps(mddb_health(args.url), indent=1))
        return 0
    if args.cmd == "mcp-policy":
        print(json.dumps(
            mcp_policy_section(Path(args.root).resolve(), args.domain),
            indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
