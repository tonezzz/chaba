#!/usr/bin/env python3
"""Assess GitHub repos: score owned repos for health/drift/relevance,
discover candidate repos worth adopting, and publish the results to:

  docs/reports/github-assessment-<date>.md   (human review)
  docs/reports/github-assessment-latest.json (machine snapshot)
  MDDB collection ada-ha-bank-github         (Ada bank='github' recall)

Data source is the `gh` CLI (auth already configured). Forks get extra
upstream-drift checks via the compare API. Scoring rubric (0-100):

  relevance        30  repo -> active-project map + heuristics
  freshness/drift  25  own pushedAt age; fork penalty for commits behind
  upstream health  20  upstream stars/activity (forks); own activity (non-fork)
  maintenance risk 15  archived/disabled/issue load
  actionability    10  referenced by chaba SSOT/docs/apps

Bands: >=75 act-now, 50-74 review, 25-49 watch, <25 archive-candidate.

Usage:
  github-repo-assess.py                 # full run: collect, score, report, MDDB
  github-repo-assess.py --dry-run       # report only, no MDDB writes
  github-repo-assess.py --repos a,b,c   # subset
  github-repo-assess.py --no-discover   # skip the gh search discovery arm
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "docs" / "reports"
COLLECTION = "ada-ha-bank-github"
WRITER = "github-repo-assess"

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).parent / "ada" / "sync-ada-memory-to-mddb.py"
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

# Repo -> (relevance 0-30, why). Repos not listed fall back to heuristics.
PROJECT_MAP = {
    "chaba": (30, "main infra/SSOT repo"),
    "ada-pi": (30, "Ada voice assistant core"),
    "sunsynk-power-flow-card": (28, "HA dashboard card in production"),
    "trade": (24, "trading project"),
    "trading-terminal": (24, "trading project (fork)"),
    "devin-kb": (20, "chaba/devin knowledge"),
    "chaba_weaviate": (18, "chaba vector stack"),
    "chaba0": (15, "chaba predecessor"),
    "ans-fleet": (15, "host provisioning"),
    "ada": (18, "ada predecessor"),
    "personaplex": (18, "voice/persona experiment"),
    "voyant": (15, "travel agent experiment"),
    "voice_chat": (16, "voice stack reference"),
    "voicechat2": (16, "voice stack reference"),
    "llm-voice-bot": (14, "voice stack reference"),
    "mcp_yolo": (12, "MCP experiment"),
    "awesome-mcp-servers": (14, "MCP reference"),
    "fastapi_colab": (10, "colab/fastapi reference"),
    "fastapi_ollama": (10, "ollama reference"),
    "fastapi_yolo": (10, "vision service reference"),
    "yolo_rag_identification": (12, "vision/RAG project"),
    "Text-Recognition-ESP32-CAM": (8, "esp32 cam experiment"),
    "esp32": (22, "esp32 firmware project"),
    "llamaindex": (10, "LLM framework reference (fork)"),
    "pythainlp": (8, "thai NLP reference (fork)"),
    "docker-redsocks-proxy": (8, "networking reference"),
    "osbox": (8, "container OS experiment"),
    "SuperCoder": (8, "autonomous-dev reference"),
    "gpt4all": (8, "local-LLM reference"),
}

# Discovery queries for the 'new repos' arm (gh search syntax).
DISCOVER_QUERIES = [
    "topic:home-assistant-custom-card pushed:>2026-01-01 stars:>100",
    "gemini live voice assistant stars:>50 pushed:>2026-03-01",
    "topic:mcp-server home assistant stars:>30",
    "esphome dashboard stars:>50 pushed:>2026-01-01",
    "sunsynk inverter home assistant stars:>20",
]

BANDS = [(75, "act-now"), (50, "review"), (25, "watch"), (0, "archive-candidate")]


def band_for(score: float) -> str:
    for threshold, band in BANDS:
        if score >= threshold:
            return band
    return "archive-candidate"


def gh_json(args: list[str], retries: int = 2):
    """Run a gh command, return parsed JSON (None on failure)."""
    for attempt in range(retries + 1):
        r = subprocess.run(["gh"] + args, capture_output=True, text=True)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return None
        if r.returncode != 0 and "404" in r.stderr:
            return None
        time.sleep(1 + attempt)
    return None


def days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days


def freshness_points(days: int | None) -> float:
    if days is None:
        return 5.0
    for limit, pts in ((14, 25), (45, 20), (90, 15), (180, 10), (365, 6)):
        if days <= limit:
            return float(pts)
    return 2.0


def drift_penalty(behind: int | None) -> float:
    if not behind:
        return 0.0
    if behind <= 20:
        return 3.0
    if behind <= 100:
        return 6.0
    return 10.0


def upstream_health(up: dict | None, upstream_days: int | None) -> float:
    if not up:
        return 8.0  # non-fork or unknown upstream — neutral
    stars = up.get("stargazerCount") or 0
    pts = min(14.0, math.log10(stars + 1) * 3.5) if stars else 4.0
    if upstream_days is not None and upstream_days <= 90:
        pts += 4.0
    elif upstream_days is not None and upstream_days <= 365:
        pts += 2.0
    if up.get("isArchived"):
        pts -= 6.0
    return max(0.0, min(20.0, pts))


def risk_points(repo: dict, upstream: dict | None) -> tuple[float, list[str]]:
    flags: list[str] = []
    pts = 15.0
    if repo.get("isArchived"):
        pts -= 15.0
        flags.append("archived")
    if upstream and upstream.get("isArchived"):
        pts -= 8.0
        flags.append("upstream archived")
    issues = repo.get("openIssues") or {}
    n = issues.get("totalCount", 0) if isinstance(issues, dict) else 0
    if n > 50:
        pts -= 3.0
        flags.append(f"{n} open issues")
    return max(0.0, pts), flags


def relevance_points(name: str, repo: dict, ref_hits: int) -> tuple[float, str]:
    if name in PROJECT_MAP:
        pts, why = PROJECT_MAP[name]
        return float(pts), why
    pts = 5.0
    why = "heuristic"
    text = f"{name} {repo.get('description') or ''}".lower()
    for kw, bonus in (
        ("home-assistant", 8), ("homeassistant", 8), ("mcp", 6),
        ("voice", 5), ("gemini", 5), ("fastapi", 4), ("esphome", 6),
        ("esp32", 6), ("ollama", 4), ("llm", 4),
    ):
        if kw in text:
            pts += bonus
    if ref_hits:
        pts += 4
    return min(30.0, pts), why


def referenced(name: str) -> int:
    """Count of files referencing the repo name in SSOT/stacks/AGENTS."""
    r = subprocess.run(
        ["rg", "-li", "--fixed-strings", name,
         "docs/ssot", "stacks", "AGENTS.md"],
        capture_output=True, text=True, cwd=REPO,
    )
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def collect(repos: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(repos, 1):
        name = r["name"]
        print(f"[{i}/{len(repos)}] {name}", flush=True)
        detail = gh_json(["api", f"repos/{{owner}}/{name}"]) or {}
        repo = {**r, **{
            "isArchived": detail.get("archived", r.get("isArchived", False)),
            "openIssues": {"totalCount": detail.get("open_issues_count", 0)},
            "defaultBranch": detail.get("default_branch", "main"),
            "homepage": detail.get("homepage") or "",
            "topics": detail.get("topics") or [],
        }}
        upstream = None
        behind = ahead = None
        if r.get("isFork") and detail.get("parent"):
            parent = detail["parent"]["full_name"]
            repo["parent"] = parent
            upstream = gh_json(["api", f"repos/{parent}"]) or {}
            pb = (upstream or {}).get("defaultBranch") or \
                (detail.get("parent") or {}).get("default_branch") or "main"
            cmp_ = gh_json([
                "api",
                f"repos/{{owner}}/{name}/compare/"
                f"{parent.split('/')[0]}:{pb}...{repo['defaultBranch']}",
            ])
            if cmp_:
                behind = cmp_.get("behind_by")
                ahead = cmp_.get("ahead_by")
        repo["_upstream"] = upstream
        repo["_behind"] = behind
        repo["_ahead"] = ahead
        out.append(repo)
    return out


def score(repo: dict) -> dict:
    name = repo["name"]
    refs = referenced(name)
    own_days = days_since(repo.get("pushedAt"))
    up = repo.get("_upstream")
    up_days = days_since((up or {}).get("pushedAt"))
    behind = repo.get("_behind")

    rel, rel_why = relevance_points(name, repo, refs)
    fresh = max(0.0, freshness_points(own_days) - drift_penalty(behind))
    health = upstream_health(up, up_days) if repo.get("isFork") else \
        (14.0 if own_days is not None and own_days <= 90 else
         8.0 if own_days is not None and own_days <= 365 else 4.0)
    risk, flags = risk_points(repo, up)
    action = 10.0 if refs else (7.0 if name in PROJECT_MAP else 2.0)

    total = rel + fresh + health + risk + action
    band = band_for(total)
    # Overrides: dead repo not referenced anywhere -> archive candidate.
    if (own_days or 0) > 730 and not refs and band != "archive-candidate" \
            and total < 50:
        band = "archive-candidate"
    if repo.get("isArchived") or (up or {}).get("isArchived"):
        band = "archive-candidate" if not refs else band
    return {
        "name": name,
        "score": round(total, 1),
        "band": band,
        "components": {
            "relevance": rel, "freshness": fresh,
            "upstream_health": round(health, 1),
            "risk": risk, "actionability": action,
        },
        "pushedAt": repo.get("pushedAt"),
        "pushed_days": own_days,
        "isFork": bool(repo.get("isFork")),
        "parent": repo.get("parent"),
        "behind": behind,
        "ahead": repo.get("_ahead"),
        "upstream_stars": (up or {}).get("stargazerCount"),
        "upstream_pushed_days": up_days,
        "refs": refs,
        "flags": flags,
        "why": rel_why,
        "description": repo.get("description") or "",
        "language": (repo.get("primaryLanguage") or {}).get("name"),
        "url": f"https://github.com/{{owner}}/{name}",
    }


def discover(existing: set[str]) -> list[dict]:
    found: dict[str, dict] = {}
    for q in DISCOVER_QUERIES:
        print(f"  discover: {q}", flush=True)
        res = gh_json(["search", "repos", q, "--limit", "10", "--json",
                       "fullName,description,stargazersCount,pushedAt,url"])
        for item in res or []:
            fn = item.get("fullName") or ""
            if fn.split("/")[-1] in existing or fn in found:
                continue
            stars = item.get("stargazersCount") or 0
            d = days_since(item.get("pushedAt"))
            pts = min(60.0, math.log10(stars + 1) * 15.0)
            if d is not None and d <= 90:
                pts += 25
            elif d is not None and d <= 365:
                pts += 10
            found[fn] = {
                "full_name": fn, "stars": stars, "pushed_days": d,
                "score": round(pts, 1), "query": q, "url": item.get("url"),
                "description": item.get("description") or "",
            }
    return sorted(found.values(), key=lambda x: -x["score"])


def doc_body(s: dict) -> str:
    lines = [
        f"# {s['name']} — score {s['score']} ({s['band']})",
        "",
        f"- last push: {s['pushedAt'] or '?'} ({s['pushed_days']}d ago)",
        f"- language: {s['language'] or '-'}  fork: {s['isFork']}",
    ]
    if s["parent"]:
        lines.append(
            f"- upstream: {s['parent']} (★{s['upstream_stars']}, "
            f"last push {s['upstream_pushed_days']}d ago)")
        lines.append(f"- drift: {s['behind']} behind / {s['ahead']} ahead")
    lines += [
        f"- components: relevance {s['components']['relevance']}, "
        f"freshness {s['components']['freshness']}, "
        f"upstream {s['components']['upstream_health']}, "
        f"risk {s['components']['risk']}, action {s['components']['actionability']}",
        f"- why: {s['why']}; referenced in repo: {s['refs']} file(s)",
    ]
    if s["flags"]:
        lines.append(f"- flags: {', '.join(s['flags'])}")
    if s["description"]:
        lines.append(f"- description: {s['description']}")
    lines.append(f"- url: {s['url']}")
    return "\n".join(lines)


def doc_meta(s: dict, today: str, kind: str = "note") -> dict:
    return {
        "bank": ["github"], "scope": ["tony"], "kind": [kind],
        "status": ["active"], "source": ["import"], "written_by": [WRITER],
        "subject": [s["name"]], "attribute": [s["band"]],
        "valid_from": [today], "last_verified": [today],
    }


def write_report(scored: list[dict], discoveries: list[dict], today: str) -> Path:
    counts: dict[str, int] = {}
    for s in scored:
        counts[s["band"]] = counts.get(s["band"], 0) + 1
    md = [
        f"# GitHub repo assessment — {today}",
        "",
        f"{len(scored)} repos assessed. Bands: "
        + ", ".join(f"{b}: {counts.get(b, 0)}" for b, _ in
                    [(b, None) for _, b in BANDS]),
        "",
        "| score | band | repo | pushed | drift | notes |",
        "|---|---|---|---|---|---|",
    ]
    for s in sorted(scored, key=lambda x: -x["score"]):
        drift = ""
        if s["parent"]:
            drift = f"{s['behind']}↓/{s['ahead']}↑ {s['parent']}"
        notes = "; ".join([s["why"]] + s["flags"])
        md.append(
            f"| {s['score']} | {s['band']} | {s['name']} | "
            f"{s['pushed_days']}d | {drift} | {notes} |")
    if discoveries:
        md += ["", "## Discovery candidates", "",
               "| score | repo | ★ | pushed | description |",
               "|---|---|---|---|---|"]
        for d in discoveries[:15]:
            md.append(f"| {d['score']} | [{d['full_name']}]({d['url']}) | "
                      f"{d['stars']} | {d['pushed_days']}d | "
                      f"{d['description'][:70]} |")
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"github-assessment-{today}.md"
    path.write_text("\n".join(md) + "\n")
    return path


def _mddb_call(fn, *args, retries: int = 4, delay: float = 1.0):
    """MDDB drops connections under rapid add load (sync embedding);
    retry with backoff and pace writes."""
    for attempt in range(retries + 1):
        try:
            return fn(*args)
        except Exception as exc:
            if attempt == retries:
                raise
            wait = delay * (attempt + 1)
            print(f"    mddb retry {attempt + 1}/{retries} after {exc!r:.80}")
            time.sleep(wait)


def sync_mddb(scored: list[dict], discoveries: list[dict], today: str,
              dry: bool, prune: bool = True) -> None:
    # Long timeout: /add queues behind the server's serial embed worker,
    # which can be saturated by backlog retries after outages.
    mddb = ada_sync.Mddb(ada_sync.MDDB, timeout=300)
    remote = {d.get("key"): d for d in mddb.list_docs(COLLECTION)}
    wanted: dict[str, tuple[str, dict]] = {}

    for s in scored:
        wanted[f"repo/{s['name']}"] = (doc_body(s), doc_meta(s, today))
    for d in discoveries[:15]:
        slug = d["full_name"].split("/")[-1].lower()
        body = (f"# discovery: {d['full_name']} — score {d['score']}\n\n"
                f"- stars: {d['stars']}  last push: {d['pushed_days']}d ago\n"
                f"- url: {d['url']}\n- query: {d['query']}\n"
                f"- {d['description']}")
        meta = doc_meta({"name": d["full_name"], "band": "discovery"},
                        today)
        wanted[f"discovery/{slug}"] = (body, meta)

    if prune:  # full run only — a subset run must not rewrite the summary
        top = sorted(scored, key=lambda x: -x["score"])[:8]
        bottom = [s for s in scored if s["band"] == "archive-candidate"]
        summary = ["# GitHub repo assessment summary", "",
                   f"Generated {today}: {len(scored)} repos, "
                   f"{len(discoveries)} discovery candidates.", "",
                   "## Highest scores (act-now/review)"]
        summary += [f"- {s['name']}: {s['score']} ({s['band']}) — {s['why']}"
                    + (f"; {s['behind']} commits behind upstream"
                       if s["behind"] else "")
                    for s in top]
        summary += ["", f"## Archive candidates ({len(bottom)})"]
        summary += [f"- {s['name']}: {s['score']}, last push "
                    f"{s['pushed_days']}d ago"
                    for s in sorted(bottom, key=lambda x: x["score"])[:12]]
        if discoveries:
            summary += ["", "## New repos worth a look"]
            summary += [f"- {d['full_name']} (★{d['stars']}): "
                        f"{d['description'][:80]}"
                        for d in discoveries[:6]]
        wanted["summary/latest"] = (
            "\n".join(summary),
            doc_meta({"name": "github-assessment-summary",
                      "band": "summary"}, today))

    # Batch ingest with skipEmbeddings: /add queues behind the serial
    # embed worker, which stalls badly when the embedding provider is
    # rate-limited/down. Docs land instantly; POST /v1/vector-reindex
    # {"collection": ..., "force": false} embeds them later.
    changed = deleted = skipped = 0
    docs = []
    for key, (body, meta) in wanted.items():
        old = remote.get(key)
        if old and (old.get("contentMd") or "") == body:
            skipped += 1
            continue
        print(f"  {'(dry) ' if dry else ''}{'~' if old else '+'} {key}")
        docs.append({"key": key, "lang": "en", "contentMd": body,
                     "meta": meta})
    if docs and not dry:
        r = mddb.s.post(f"{mddb.base}/add-batch", timeout=120, json={
            "collection": COLLECTION, "documents": docs,
            "options": {"skipEmbeddings": True, "saveRevision": True},
        })
        r.raise_for_status()
        print(f"  batch: {r.json()}")
        changed = len(docs)
    for key, doc in remote.items():
        if not prune:
            break
        if key not in wanted and WRITER in (
                (doc.get("meta") or {}).get("written_by") or []):
            print(f"  {'(dry) ' if dry else ''}- {key} (stale)")
            if not dry:
                _mddb_call(mddb.delete, COLLECTION, key)
                time.sleep(0.4)
            deleted += 1
    print(f"mddb: {changed} written, {deleted} deleted, {skipped} unchanged")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", help="comma-separated subset")
    ap.add_argument("--no-discover", action="store_true")
    ap.add_argument("--no-mddb", action="store_true")
    ap.add_argument("--from-json", type=Path,
                    help="skip collection; reuse github-assessment-latest.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date.today().isoformat()
    if args.from_json:
        snap = json.loads(args.from_json.read_text())
        scored, discoveries = snap["repos"], snap.get("discoveries") or []
        print(f"loaded {len(scored)} scored repos from {args.from_json}")
    else:
        repos = gh_json(["repo", "list", "--limit", "200", "--json",
                         "name,description,pushedAt,stargazerCount,isPrivate,"
                         "isFork,isArchived,primaryLanguage"]) or []
        if args.repos:
            keep = set(args.repos.split(","))
            repos = [r for r in repos if r["name"] in keep]
        print(f"{len(repos)} repos to assess")

        collected = collect(repos)
        scored = [score(r) for r in collected]
        discoveries = [] if args.no_discover else \
            discover({r["name"] for r in repos})

        report = write_report(scored, discoveries, today)
        (REPORTS / "github-assessment-latest.json").write_text(
            json.dumps({"generated": today, "repos": scored,
                        "discoveries": discoveries}, indent=2) + "\n")
        print(f"report: {report}")

    for s in sorted(scored, key=lambda x: -x["score"])[:10]:
        print(f"  {s['score']:>5}  {s['band']:<18} {s['name']}")

    if not args.no_mddb:
        # Stale-doc cleanup is only safe on a full run — a --repos subset
        # would otherwise delete every repo doc outside the subset.
        sync_mddb(scored, discoveries, today, args.dry_run,
                  prune=not args.repos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
