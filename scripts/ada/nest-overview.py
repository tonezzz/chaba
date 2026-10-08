#!/usr/bin/env python3
"""nest-overview.py — Chaba Nest hub -> CMS `chaba-nest`.

The umbrella page for the compound-AI fleet. Managed block renders:

  - live lane health — every known /v1/systemone endpoint probed
  - latest topology scorecard (newest bench/orch-* doc)
  - kanban-brief headline counts (do-first quadrant size)
  - corpus counters (jev-corpus rows, voice-corpus clips)

Registry-gated like the other updaters; runs as the third ExecStart of
chaba-kanban-brief.service (30 min cadence).

Env:
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1

Usage: nest-overview.py [--force] [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
REPORTS = "ada-ha-scenario-reports"
PAGE = "chaba-nest"
BLOCK_BEGIN = "<!-- nest-overview:auto -->"
BLOCK_END = "<!-- /nest-overview:auto -->"
BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" +
                      re.escape(BLOCK_END), re.S)
ICT = timezone(timedelta(hours=7))

# The fleet — keep in sync with topologies.yml. Lanes get probed
# live; a lane being down is information, not an error.
LANES = [
    ("jev-student (prod gate)", "idc03",  8778, "distilbert confirm"),
    ("student-a",               "tony-omen", 8778, "gemma-3-1b systemd"),
    ("student-b",               "idc03",  8779, "gemma-3-1b container"),
    ("heavy-a",                 "idc02",  8777, "gemma-3-4b (prod advisory)"),
    ("heavy-b",                 "tony-omen", 8777, "gemma-3-4b systemd"),
]
LANE_IP = {"idc02": "100.123.163.11", "idc03": "100.102.134.91",
           "tony-omen": "100.75.102.88"}
OLLAMA = ("tony-omen", "100.75.102.88:11434")

CHILD_PAGES = [
    ("chaba-compound-ai-system", "the architecture doc (compound AI = the Berkeley term)"),
    ("nest-bench", "topology scoreboard — auto-trends every bench run"),
    ("bench-orch", "per-run structure scorecards"),
    ("bench-jev", "confirm-gate model bench"),
    ("bench-voice-models", "speaker-ID encoder bench (CAM++ shadow)"),
    ("jev-ai-assessment", "decision-tier ladder — measured"),
    ("multi-model-orchestration", "ensemble structures landscape"),
    ("tiny-models-research", "on-device preprocessor research"),
    ("kanban-brief", "T0/T1 card briefing — the assistant layer"),
    ("nest-oss-landscape", "vocab→repos map — RouteLLM, semantic-router, cascade"),
    ("agent-harness-landscape", "OpenClaw vs Hermes + claw family, mapped to the Nest"),
    ("ai-edge-report", "weekly paper feed filtered on Nest keywords"),
    ("orchestration-conflicts", "conflict rules when lanes share resources"),
]


def _post(path, payload, timeout=30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _search_all(collection, page_size=500):
    docs, offset = [], 0
    while True:
        page = _post("search", {"collection": collection, "query": "",
                                "limit": page_size, "offset": offset})
        docs += page
        if len(page) < page_size:
            return docs
        offset += page_size


def get_page(lang):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == PAGE and d.get("lang") == lang), None)


# ---------- probes ----------

def probe_lanes():
    out = []
    for name, host, port, model in LANES:
        ip = LANE_IP[host]
        try:
            t0 = datetime.now()
            h = json.load(urllib.request.urlopen(
                f"http://{ip}:{port}/health", timeout=5))
            ms = int((datetime.now() - t0).total_seconds() * 1000)
            out.append((name, host, port, model, "up",
                        f"{ms}ms", h.get("model", "-").split("/")[-1]))
        except Exception:
            out.append((name, host, port, model, "DOWN", "-", "-"))
    # ollama is /api/tags not /health
    try:
        t0 = datetime.now()
        tags = json.load(urllib.request.urlopen(
            f"http://{OLLAMA[1]}/api/tags", timeout=5))
        ms = int((datetime.now() - t0).total_seconds() * 1000)
        names = ",".join(m["name"].split(":")[0]
                         for m in tags.get("models", [])[:4])
        out.append(("ollama", "tony-omen", 11434, "phi3/moondream/nomic",
                    "up", f"{ms}ms", names))
    except Exception:
        out.append(("ollama", "tony-omen", 11434, "phi3/moondream/nomic",
                    "DOWN", "-", "-"))
    return out


def latest_orch(docs):
    rows, key = {}, ""
    for d in sorted(docs, key=lambda d: (d.get("meta") or {})
                    .get("updated", [""])[0]):
        if not (d.get("key") or "").startswith("bench/orch-"):
            continue
        rows = {}
        for ln in (d.get("contentMd") or "").splitlines():
            m = re.match(
                r"^\|\s*([A-Za-z0-9_-]+)\s*\|\s*([^|]+?)\s*\|"
                r"\s*([0-9.]+)s\s*\|\s*([0-9.]+)s\s*\|\s*([0-9.]+)\s*\|"
                r"\s*([0-9]+)%\s*\|\s*([0-9.]+)\s*\|", ln)
            if m:
                name, acc, p50, p95, cpu, heavy, ece = m.groups()
                rows[name] = (acc.strip(), float(cpu), int(heavy))
        key = d["key"]
    return key, rows


# ---------- render ----------

def render(lanes, orch_key, orch_rows, now):
    lines = [BLOCK_BEGIN, "",
             f"_updated {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT_", "",
             "### Lanes (live)", "",
             "| lane | host:port | model | health | probe |",
             "|---|---|---|---|---|"]
    for name, host, port, model, st, ms, seen in lanes:
        mark = "✅" if st == "up" else "❌"
        lines.append(f"| {name} | {host}:{port} | {model} | "
                     f"{mark} {st} | {ms} |")
    if orch_rows:
        lines += ["", f"### Latest topology run — `{orch_key}`", "",
                  "| structure | acc | cpu/call | heavy% |",
                  "|---|---|---|---|"]
        for name, (acc, cpu, heavy) in orch_rows.items():
            lines.append(f"| {name} | {acc} | {cpu} | {heavy}% |")
    lines += ["", "### Reading map", "", "| page | what |",
              "|---|---|"]
    for key, desc in CHILD_PAGES:
        lines.append(f"| `{key}` | {desc} |")
    lines += ["", BLOCK_END]
    return "\n".join(lines)


def upsert_block(body, block):
    if BLOCK_RE.search(body or ""):
        return BLOCK_RE.sub(lambda m: block, body, count=1)
    m = re.search(r"^## ", body or "", re.M)
    if m:
        return body[:m.start()] + block + "\n\n" + body[m.start():]
    return (body or "").rstrip() + "\n\n" + block + "\n"


PAGE_INTRO = """# Chaba Nest — the compound-AI system

**One umbrella name for all of it**: the swarm of micro-AIs mix-and-matched
to do what a single big model does — cheaper, auditable, and correctable.
"Cascade" is the *how* (levels chained in series/parallel/router/verifier
patterns); the Nest is the whole thing they live in.

Three organs:

- **Cognition tiers** — L0 rules (free) → L1 students (~1b) → L2 heavies
  (~4b) → L3 arbiter (Gemini). Cheapest tier that can hold the decision
  wins the call.
- **Memory spine** — MDDB banks, CMS report pages, corpus-in/corpus-out
  loops (misses become next run's cases).
- **Compute fabric** — host lanes across idc02/idc03/tony-omen + podman
  container lanes (runner-agent) + dispatch lanes + Colab burst GPU for
  training/bench spikes.

Authority standard (the part that keeps it safe): **program decides what
to do, AI decides how to say it.** Advisory models earn enforcement only
through measured benchmark wins — Jev advisory, CAM++ speaker shadow, and
kanban-act all live in shadow-first posture.

"""


def page_body(block):
    doc = get_page("en")
    if doc and doc.get("contentMd"):
        return upsert_block(doc["contentMd"], block)
    return PAGE_INTRO + block + "\n"


def publish(body, now):
    doc = get_page("en") or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": ["en"], "kind": ["report"], "attribute": ["report"],
        "report_role": ["hub"], "domain": ["bench"],
        "generated_by": ["nest-overview.py"],
        "title": ["Chaba Nest — compound-AI system"],
        "summary": ["Umbrella page — fleet lanes, topology trends, "
                    "authority tiers, links to all Nest docs."],
        "fresh_for": ["1h"], "confidence": ["high"],
        "timeline": [f"{now.isoformat(timespec='minutes')}: refresh"],
        "written_by": ["nest-overview"],
    })
    _post("add", {"collection": COLLECTION, "key": PAGE, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["nest-overview"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2), "meta": meta},
          timeout=120)


def load_registry():
    try:
        docs = _search_all(REGISTRY)
    except Exception as e:
        print(f"warn: registry unreachable ({e}) — running anyway",
              file=sys.stderr)
        return {}, False
    for d in docs:
        if d.get("key") == PAGE:
            try:
                return json.loads(d.get("contentMd") or "{}"), True
            except json.JSONDecodeError:
                return {}, True
    return {}, True


def gated(cfg, now, force):
    if not cfg.get("enabled", True):
        return "disabled"
    if force or cfg.get("run_now"):
        return None
    interval = int(cfg.get("interval_min") or 0)
    last = cfg.get("last_run")
    if interval and last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now < last_dt + timedelta(minutes=interval, seconds=-30):
                return f"interval (last run {last})"
        except ValueError:
            pass
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    if not args.dry_run:
        cfg, online = load_registry()
        why = gated(cfg, now, args.force)
        if why:
            print(f"nest-overview: skipped ({why})")
            return 0
    lanes = probe_lanes()
    docs = _search_all(REPORTS)
    key, rows = latest_orch(docs)
    block = render(lanes, key, rows, now)
    if args.dry_run:
        print(block)
        return 0
    publish(page_body(block), now)
    cfg = dict(cfg)
    cfg.update({"last_run": now.isoformat(timespec="seconds"),
                "run_now": False})
    save_registry(cfg, now)
    print(f"nest-overview: published ({sum(1 for l in lanes if l[4]=='up')}"
          f"/{len(lanes)} lanes up)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
