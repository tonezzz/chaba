#!/usr/bin/env python3
"""nest-overview.py — Chaba Nest hub -> CMS `chaba-nest`.

The umbrella page for the compound-AI fleet. Managed block renders:

  - live lane health — every known /v1/systemone endpoint probed
    (/health + /metrics; lanes without /metrics render "no metrics")
  - lane activity — decisions + escalation % since the previous run
  - portable brains — entity/tier/status/bench from ssot.nest-brains.yml
  - latest topology scorecard (newest bench/orch-* doc)
  - kanban-brief headline counts (do-first quadrant size)
  - corpus counters (jev-corpus rows, voice-corpus clips)

Registry-gated like the other updaters; runs as the third ExecStart of
chaba-kanban-brief.service (30 min cadence).

Layered reporting (ssot.reports.yml): this generator owns the
`chaba-nest` L2 node plus its L1 children — nest-lanes/*, nest-brains/*,
nest-bench/orch. Each run writes reports/nest/nest-overview.yml
(rolling artifact), meta.<child>.yml per child, meta.chaba-nest.yml, and
appends one timeline event — staleness is observable by L3.

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

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from lib.report import (  # noqa: E402
    append_timeline, now_iso, write_meta,
)

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

NODE = "chaba-nest"
LAYER = "L2-domain"
GENERATED_BY = ("scripts/ada/nest-overview.py "
                "via chaba-kanban-brief.service (30 min)")
NEST_OUT = REPO / "reports" / "nest"
NEST_ARTIFACT = NEST_OUT / "nest-overview.yml"
NEST_META = NEST_OUT / "meta.chaba-nest.yml"
BRAINS_SSOT = (REPO / "docs" / "ssot" / "infrastructure"
               / "ssot.nest-brains.yml")
# brain entity.status -> report status (status_enum): packed-verified =
# respawn coverage in place; candidate = declared but never packed (a
# standing finding); future = entity does not exist yet.
BRAIN_STATUS = {"packed-verified": "ok", "candidate": "delta",
                "future": "planned"}

# The fleet — keep in sync with topologies.yml. First element is the
# L1 node slug (nest-lanes/<slug>). Lanes get probed live; a lane being
# down is information, not an error.
LANES = [
    ("jev-student", "jev-student (prod gate)", "idc03", 8778,
     "distilbert confirm"),
    ("student-a",   "student-a",               "tony-omen", 8778,
     "gemma-3-1b systemd"),
    ("student-b",   "student-b",               "idc03", 8779,
     "gemma-3-1b container"),
    ("heavy-a",     "heavy-a",                 "idc02", 8777,
     "gemma-3-4b (prod advisory)"),
    ("heavy-b",     "heavy-b",                 "tony-omen", 8777,
     "gemma-3-4b systemd"),
]
LANE_IP = {"idc02": "100.123.163.11", "idc03": "100.102.134.91",
           "tony-omen": "100.75.102.88"}
OLLAMA = ("ollama", "tony-omen", "100.75.102.88:11434")

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


CARDS_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"


def _linked_cards(link_key="chaba-nest"):
    """Kanban cards whose links: name this report node — the program's
    live worklist on the hub page (ideas stay updated as they move)."""
    out = []
    if not CARDS_DIR.is_dir():
        return out
    for f in sorted(CARDS_DIR.glob("*.yml")):
        try:
            d = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        links = d.get("links") or []
        if link_key not in links:
            continue
        out.append({"id": d.get("id") or f.stem,
                    "title": str(d.get("title") or "")[:70],
                    "column": d.get("column") or "?",
                    "updated": str(d.get("updated") or "-")})
    order = {"doing": 0, "review": 1, "ready": 2, "backlog": 3}
    out.sort(key=lambda c: (order.get(c["column"], 4), c["id"]))
    return out


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

def _get_json(url, timeout=5):
    t0 = datetime.now()
    data = json.load(urllib.request.urlopen(url, timeout=timeout))
    return data, int((datetime.now() - t0).total_seconds() * 1000)


def probe_lanes():
    """Probe /health (+ /metrics when the lane exposes it) for every
    systemone lane, then ollama. Returns a list of row dicts."""
    out = []
    for slug, name, host, port, model in LANES:
        ip = LANE_IP[host]
        row = {"id": slug, "name": name, "host": host, "port": port,
               "model": model, "status": "DOWN", "probe_ms": None,
               "seen": "-", "metrics": None}
        try:
            h, ms = _get_json(f"http://{ip}:{port}/health")
            row.update(status="up", probe_ms=ms,
                       seen=(h.get("model") or "-").split("/")[-1])
        except Exception:
            out.append(row)
            continue
        try:
            row["metrics"], _ = _get_json(f"http://{ip}:{port}/metrics",
                                          timeout=3)
        except Exception:
            pass  # lane predates /metrics — renders "no metrics"
        out.append(row)
    # ollama is /api/tags not /health — not our server, no /metrics
    slug, host, base = OLLAMA
    row = {"id": slug, "name": "ollama", "host": host, "port": 11434,
           "model": "phi3/moondream/nomic", "status": "DOWN",
           "probe_ms": None, "seen": "-", "metrics": None}
    try:
        tags, ms = _get_json(f"http://{base}/api/tags")
        row.update(
            status="up", probe_ms=ms,
            seen=",".join(m["name"].split(":")[0]
                          for m in tags.get("models", [])[:4]))
    except Exception:
        pass
    out.append(row)
    return out


def load_prev_artifact():
    """Previous rolling artifact — source of last interval's counters."""
    try:
        return yaml.safe_load(NEST_ARTIFACT.read_text()) or {}
    except Exception:
        return {}


def lane_delta(prev: dict, row: dict) -> dict | None:
    """Decisions + escalations since the previous run for one lane.

    None when the lane has no /metrics (either run). A counter reset
    (lane restart — current < previous, or uptime went backwards)
    reports the current counters as the interval's totals."""
    cur = row.get("metrics")
    if not cur:
        return None
    prev_m = ((prev.get("lanes") or {}).get(row["id"]) or {}).get(
        "metrics") or {}
    req = (cur.get("requests_total") or 0) - (prev_m.get(
        "requests_total") or 0)
    esc = (cur.get("escalations_total") or 0) - (prev_m.get(
        "escalations_total") or 0)
    reset = (not prev_m) or req < 0 or esc < 0 or (
        (cur.get("uptime_s") or 0) < (prev_m.get("uptime_s") or 0))
    if reset:
        # no baseline (first run after upgrade) or lane restart —
        # the counters are since-process-start, not interval-scoped
        req = cur.get("requests_total") or 0
        esc = cur.get("escalations_total") or 0
    interval_s = None
    try:
        prev_ts = datetime.fromisoformat(str(prev.get("generated_at")))
        interval_s = max(0, int(
            (datetime.now(timezone.utc) - prev_ts).total_seconds()))
    except Exception:
        pass
    return {"requests": max(0, req), "escalations": max(0, esc),
            "reset": reset, "interval_s": interval_s}


def load_brains() -> list:
    try:
        doc = yaml.safe_load(BRAINS_SSOT.read_text()) or {}
    except Exception:
        return []
    return doc.get("entities") or []


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

def _fmt_interval(interval_s):
    if interval_s is None:
        return "?"
    if interval_s < 3600:
        return f"{interval_s // 60}m"
    return f"{interval_s // 3600}h{(interval_s % 3600) // 60}m"


def render(lanes, deltas, brains, orch_key, orch_rows, now):
    lines = [BLOCK_BEGIN, "",
             f"_updated {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT_", "",
             "### Lanes (live)", "",
             "| lane | host:port | model | health | probe | decisions Δ "
             "| esc % |",
             "|---|---|---|---|---|---|---|"]
    for row in lanes:
        mark = "✅" if row["status"] == "up" else "❌"
        ms = f"{row['probe_ms']}ms" if row["probe_ms"] is not None else "-"
        d = deltas.get(row["id"])
        if row["metrics"] is None:
            decisions, esc = "no metrics", "-"
        elif d is None:
            decisions, esc = "-", "-"
        else:
            decisions = str(d["requests"]) + (" ↻" if d["reset"] else "")
            esc = (f"{100.0 * d['escalations'] / d['requests']:.0f}%"
                   if d["requests"] else "-")
        lines.append(f"| {row['name']} | {row['host']}:{row['port']} | "
                     f"{row['model']} | {mark} {row['status']} | {ms} | "
                     f"{decisions} | {esc} |")
    interval = next((d["interval_s"] for d in deltas.values()
                     if d and d.get("interval_s")), None)
    span = (f" ({_fmt_interval(interval)} ago)" if interval is not None
            else "")
    lines += ["",
              f"_Δ = decisions since the previous run{span}; ↻ marks "
              "no baseline (lane restart or first /metrics probe) — the "
              "count is since process start. `no metrics` = lane server "
              "not yet upgraded to /metrics._"]
    if brains:
        lines += ["", "### Portable brains — `ssot.nest-brains.yml`", "",
                  "| entity | tier | status | bench |",
                  "|---|---|---|---|"]
        for e in brains:
            b = e.get("bench") or {}
            bench = (f"{b['score']} {b['metric']}"
                     if b.get("score") is not None
                     else (b.get("metric") or "-"))
            lines.append(f"| `{e.get('entity')}` | {e.get('tier', '-')} | "
                         f"{e.get('status', '-')} | {bench} |")
    cards = _linked_cards()
    if cards:
        lines += ["", "### Program cards — `links: [chaba-nest]`", "",
                  "| card | column | updated |", "|---|---|---|"]
        for c in cards:
            lines.append(f"| {c['id']} — {c['title']} | {c['column']} | "
                         f"{c['updated']} |")
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


# ---------- layered reporting ----------

def write_report_outputs(lanes, deltas, brains, orch_key, orch_rows,
                         run_ts):
    """Rolling artifact + per-child metas + the chaba-nest L2 meta +
    one timeline event (ssot.reports.yml). Meta status follows the fleet
    convention: a child in delta/stale/missing/error/unreachable makes
    the parent delta."""
    NEST_OUT.mkdir(parents=True, exist_ok=True)
    artifact = {
        "generated_at": run_ts,
        "node": NODE,
        "lanes": {r["id"]: {"status": r["status"],
                            "probe_ms": r["probe_ms"],
                            "model_seen": r["seen"],
                            "metrics": r["metrics"]}
                  for r in lanes},
        "brains": [{"entity": e.get("entity"), "tier": e.get("tier"),
                    "status": e.get("status"), "bench": e.get("bench")}
                   for e in brains],
        "bench": {"latest_doc": orch_key or None,
                  "structures": len(orch_rows)},
    }
    NEST_ARTIFACT.write_text(yaml.safe_dump(
        artifact, sort_keys=False, allow_unicode=True))

    child_ids, inputs_at, child_states = [], {}, []

    def child(cid, meta_file, status, **kw):
        child_ids.append(cid)
        inputs_at[cid] = run_ts
        child_states.append(status)
        write_meta(NEST_OUT / meta_file, node=cid, layer="L1-producer",
                   generated_by=GENERATED_BY, generated_at=run_ts,
                   status=status, children=[], **kw)

    for row in lanes:
        cid = f"nest-lanes/{row['id']}"
        up = row["status"] == "up"
        d = deltas.get(row["id"])
        summary = (f"up — {row['probe_ms']}ms, model {row['seen']}"
                   if up else "DOWN — probe failed")
        if up and row["metrics"] is None:
            summary += "; no /metrics"
        elif up and d:
            summary += (f"; {d['requests']} req/"
                        f"{_fmt_interval(d['interval_s'])}")
        child(cid, f"meta.lane-{row['id']}.yml",
              status="ok" if up else "delta",
              purpose=(f"systemone lane {row['name']} "
                       f"({row['host']}:{row['port']})"),
              summary=summary,
              sources=[f"probe {LANE_IP.get(row['host'], row['host'])}:"
                       f"{row['port']}"],
              extra={"probe_ms": row["probe_ms"],
                     "model_seen": row["seen"],
                     "metrics": row["metrics"],
                     "interval": d})

    for e in brains:
        ent = e.get("entity")
        est = str(e.get("status") or "unknown")
        b = e.get("bench") or {}
        child(f"nest-brains/{ent}", f"meta.brain-{ent}.yml",
              status=BRAIN_STATUS.get(est, "delta"),
              purpose=f"portable brain {ent} — respawn state",
              summary=(f"{e.get('tier', '-')} brain: {est}"
                       + (f" — {b['metric']}={b['score']}"
                          if b.get("score") is not None else "")),
              sources=["docs/ssot/infrastructure/ssot.nest-brains.yml"],
              extra={"tier": e.get("tier"), "entity_status": est,
                     "bench": b or None, "path": e.get("path"),
                     "sensitivity": e.get("sensitivity")})

    child("nest-bench/orch", "meta.bench-orch.yml",
          status="ok" if orch_key else "delta",
          purpose="Topology scorecards — orch-bench -> MDDB bench/orch-*",
          summary=(f"{orch_key}: {len(orch_rows)} structures"
                   if orch_key else "no bench/orch-* docs found"),
          sources=[f"{REPORTS}:bench/orch-*"],
          extra={"latest_doc": orch_key or None,
                 "structures": len(orch_rows)})

    n_up = sum(1 for r in lanes if r["status"] == "up")
    brain_counts = {}
    for e in brains:
        s = str(e.get("status") or "unknown")
        brain_counts[s] = brain_counts.get(s, 0) + 1
    brain_str = ", ".join(f"{n} {s}" for s, n in sorted(brain_counts.items()))
    status = ("delta" if any(
        s in ("delta", "stale", "missing", "error", "unreachable")
        for s in child_states) else "ok")
    n_metrics = sum(1 for r in lanes if r["metrics"] is not None)
    summary = (f"{n_up}/{len(lanes)} lanes up ({n_metrics} with metrics); "
               f"{len(brains)} brains ({brain_str or 'none'}); "
               f"bench {orch_key or 'none'}")
    write_meta(
        NEST_META, node=NODE, layer=LAYER, generated_by=GENERATED_BY,
        status=status,
        purpose=("Nest compound-AI domain — lane health+activity, "
                 "portable-brain respawn state, bench scorecards"),
        summary=summary,
        sources=[str(NEST_ARTIFACT.relative_to(REPO)),
                 "docs/ssot/infrastructure/ssot.nest-brains.yml",
                 f"{REPORTS}:bench/orch-*", "CMS:ada-cms-pages/chaba-nest"],
        children=child_ids, inputs_at=inputs_at,
        extra={"lanes_up": n_up, "lanes_total": len(lanes),
               "lanes_with_metrics": n_metrics,
               "brain_status": brain_counts,
               "bench_doc": orch_key or None,
               "page": PAGE})
    append_timeline(NODE, LAYER, status, summary, ref=NEST_ARTIFACT)
    return status, summary


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
    prev = load_prev_artifact()
    lanes = probe_lanes()
    deltas = {r["id"]: lane_delta(prev, r) for r in lanes}
    brains = load_brains()
    try:
        docs = _search_all(REPORTS)
    except Exception as e:
        print(f"warn: MDDB unreachable ({e}) — bench section skipped",
              file=sys.stderr)
        docs = []
    key, rows = latest_orch(docs)
    block = render(lanes, deltas, brains, key, rows, now)
    if args.dry_run:
        print(block)
        return 0
    # Local reporting outputs first — a CMS/MDDB outage must not leave
    # the node without fresh meta (staleness is the L3 signal).
    rstatus, rsummary = write_report_outputs(
        lanes, deltas, brains, key, rows, now_iso())
    publish(page_body(block), now)
    cfg = dict(cfg)
    cfg.update({"last_run": now.isoformat(timespec="seconds"),
                "run_now": False})
    save_registry(cfg, now)
    print(f"nest-overview: published "
          f"({sum(1 for r in lanes if r['status'] == 'up')}"
          f"/{len(lanes)} lanes up) — report {rstatus}: {rsummary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
