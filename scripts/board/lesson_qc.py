#!/usr/bin/env python3
"""lesson_qc — advisory QC sweep over the self-reported lesson corpus.

Card lesson-qc-sweep (OPS-1275): self-reported lessons are unverified and
never retire — the dispatch feedback loop (lesson_primer's KNOWN_PITFALLS)
has no damping. This script is the report-only damping layer: it never
deletes, never edits the corpus; humans/agents retire lessons deliberately.

Passes over the same corpus lesson_primer harvests — minus the kb-runbook
source, which is query-dependent pointer lines, not lesson text:

  1. dispatch-outcome-*.md ``lessons:`` lists (self-seeded by TASK_RAILS)
  2. docs/ssot/jobs/**/*.yml lesson-named fields (any depth)
  3. kanban card comms matching the primer's COMMS_RE

Checks:
  duplicates      normalize (lowercase, strip punctuation), cluster by
                  token-jaccard >= JACCARD_MIN — report only
  staleness       RETIRED_RE retired-infra refs + repo-path refs that no
                  longer exist + CascadeProjects/<name> checkouts not in
                  KNOWN_REPOS (renamed-repo hints)
  contradictions  lines sharing a top-3-content-token signature but
                  carrying opposing directive markers (never|do not|
                  must not vs must|always|required) — candidates only
  health          corpus size per source, growth vs last run (state
                  file), % outcome docs with a parseable lessons: list

Outputs:
  docs/ssot/jobs/kanban/<date>-lesson-qc.yml   machine record
  reports/lesson-qc-<date>.md                  human report
  ops-event (ada-ha-events-tony, same shape as kanban-dispatch.ops_event)
      when flag count > LESSON_QC_OPS_THRESHOLD — at most once per flag
      fingerprint per OPS_EVENT_MIN_INTERVAL so the 5-min watch cadence
      cannot spam the feed.

Invocation: best-effort tail step of devin-dispatch-watch.timer's script
(scripts/devin/devin-dispatch-watch.sh) — the SAME mechanism
render-handoff-inbox.py uses. Chosen over a standalone timer because the
corpus only grows when dispatches land outcomes — exactly what the
watcher polls — so QC rides a proven cadence with zero new units, and
its failure is warn-only by construction. Standalone runs also fine:

  python3 scripts/board/lesson_qc.py [--root PATH] [--state PATH]
      [--jobs-dir PATH] [--reports-dir PATH] [--date YYYY-MM-DD]
      [--dry-run] [--no-ops-event]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ICT = timezone(timedelta(hours=7))

STATE_PATH = Path(os.environ.get(
    "LESSON_QC_STATE",
    str(Path.home() / ".local/share/board/lesson-qc-state.json")))
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")

JACCARD_MIN = 0.8
LINE_CAP = 240
OPS_EVENT_THRESHOLD = int(os.environ.get("LESSON_QC_OPS_THRESHOLD", "10"))
OPS_EVENT_MIN_INTERVAL = 24 * 3600       # seconds between repeat emits
MAX_REPORT_ITEMS = 30                    # per-section listing cap

# TASK_RAILS gained the mandatory `lessons:` bullet on 2026-10-09 — docs
# older than that predate the self-seeding contract and don't count
# against compliance.
SELF_SEED_SINCE = "20261009"

# Retired-infra references worth flagging in lesson lines.
# NEEDS PERIODIC REVIEW — same module-constant convention as
# lesson_primer's RETIRED_RE (card lesson-primer-scoring-fixes).
#   idc01                          ada/mddb roles retired 2026-10-05..17
#                                  (host later returned as warm-DR/lab —
#                                  flags are review hints, not verdicts)
#   tony-dell.taila0626a.ts.net    retired as a service endpoint
#                                  2026-10-20 (OPS-0731 consumer-canary)
RETIRED_RE = re.compile(
    r"\bidc01\b|tony-dell\.taila0626a\.ts\.net", re.I)

# Checkout names still valid under ~/CascadeProjects/ — anything else a
# lesson names is a renamed-repo hint. dispatch-wt-* worktrees are
# transient and skipped separately.
KNOWN_REPOS = {
    "chaba", "chaba-tony-dell", "chaba-kbman", "chaba-vault",
    "chaba-kanban-sync", "ada-voice", "sunsynk-card",
}
REPO_PATH_RE = re.compile(r"CascadeProjects/([\w.-]+)/")

# Repo-relative file references inside lesson text. Home paths (~/) are
# excluded — existence is checked against the repo only.
FILE_PATH_RE = re.compile(
    r"(?:CascadeProjects/[\w.-]+/)?"
    r"((?:[\w.-]+/)+[\w.-]+\."
    r"(?:py|sh|yml|yaml|service|timer|md|mjs|js|json|toml|cfg|conf))\b")

NEG_DIRECTIVE_RE = re.compile(
    r"\b(?:never|do not|don't|must not|mustn't|avoid|cannot|no longer)\b",
    re.I)
POS_DIRECTIVE_RE = re.compile(
    r"\b(?:must|always|required|require[sd]?|have to|shall)\b", re.I)
DIRECTIVE_WORDS = {
    "never", "not", "don't", "must", "mustn't", "avoid", "cannot",
    "always", "required", "require", "requires", "shall", "longer",
}
STOPWORDS = {
    "this", "that", "with", "from", "into", "when", "then", "than",
    "have", "been", "will", "would", "should", "could", "about", "after",
    "before", "the", "and", "for", "are", "was", "were", "all", "any",
    "each", "card", "task", "work", "spec", "your", "them", "they",
    "their", "there", "here", "what", "which", "while",
}


# ---------------------------------------------------------------- harvest
# Same corpus as lesson_primer. Import the primer's harvest primitives so
# QC cannot drift from what the primer actually ingests; anything missing
# (e.g. mid-refactor) falls back to a local copy — QC must never die on
# a sibling module.

def _load_primer():
    path = Path(__file__).resolve().with_name("lesson_primer.py")
    try:
        spec = importlib.util.spec_from_file_location("lesson_primer", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_lp = _load_primer()

SIGNAL_RE = getattr(_lp, "SIGNAL_RE", None) or re.compile(
    r"gotcha|fail(?:ed|ure|s)?\b|lesson|pitfall|never\b|do not\b|"
    r"don't\b|must not|beware|careful|broken|stall|race\b|workaround|"
    r"watch out|avoid\b|tripped|bit us", re.I)
COMMS_RE = getattr(_lp, "COMMS_RE", None) or re.compile(
    r"gotcha|failed|lesson|do not|never", re.I)
LESSON_KEYS = getattr(_lp, "LESSON_KEYS", None) or {
    "method_notes", "side_findings", "gotchas", "lessons", "pitfalls",
    "lesson", "gotcha"}
KEY_RE = getattr(_lp, "KEY_RE", None) or re.compile(
    r"gotcha|lesson|pitfall|fail", re.I)


def _clip(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" -•\t")
    return (line[:LINE_CAP - 1] + "…") if len(line) > LINE_CAP else line


def _lesson_lines(text: str) -> list:
    """Same split rule as the primer: signal-bearing lines only."""
    out = []
    for raw in str(text).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        pieces = [raw] if len(raw) <= LINE_CAP else re.split(
            r"(?<=[.!?])\s+|(?=GOTCHA:|NOTE:|WARNING:)", raw)
        for p in pieces:
            if SIGNAL_RE.search(p):
                out.append(_clip(p))
    return [l for l in out if l]


def _walk_fields(node):
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if kl in LESSON_KEYS or KEY_RE.search(kl):
                yield from _texts(v)
            else:
                yield from _walk_fields(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_fields(v)


def _texts(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for item in v:
            yield from _texts(item)
    elif isinstance(v, dict):
        yield from _walk_fields(v)


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return p.name


def harvest(root: Path) -> list:
    """Corpus records: {text, src, kind} — tolerates str comms entries
    (kraut-rain-events/kraut-weather-bakeoff carry one; the primer
    crashes there, QC must not)."""
    out = []

    outcome_docs = 0
    outcome_docs_with_lessons = 0
    outcome_docs_since_seed = 0
    outcome_seeded_since = 0
    for p in sorted(root.glob("dispatch-outcome-*.md")):
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        outcome_docs += 1
        m = re.match(r"dispatch-outcome-(\d{8})", p.name)
        recent = bool(m and m.group(1) >= SELF_SEED_SINCE)
        if recent:
            outcome_docs_since_seed += 1
        found = False
        for i, ln in enumerate(lines):
            if re.match(r"^\s*lessons:\s*\[", ln):
                found = True          # lessons: [] — explicit empty
                break
            if not re.match(r"^\s*lessons:\s*$", ln):
                continue
            found = True
            for item in lines[i + 1:]:
                it = re.match(r"^\s*-\s+(.+)$", item)
                if not it:
                    break
                out.append({"text": _clip(it.group(1)),
                            "src": _rel(root, p), "kind": "outcome"})
            break
        if found:
            outcome_docs_with_lessons += 1
            if recent:
                outcome_seeded_since += 1

    job_files = 0
    for p in sorted(root.glob("docs/ssot/jobs/**/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        job_files += 1
        for text in _walk_fields(doc):
            for line in _lesson_lines(text):
                out.append({"text": line, "src": _rel(root, p),
                            "kind": "job"})

    card_files = 0
    for p in sorted(root.glob("docs/ssot/kanban/cards/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        card_files += 1
        action = doc.get("action") or {}
        card_repo = (action.get("repo") if isinstance(action, dict)
                     else None)
        for c in (doc.get("comms") or []):
            if isinstance(c, dict):
                text = str(c.get("text") or "")
            else:
                text = str(c or "")
            if COMMS_RE.search(text):
                out.append({"text": _clip(f"[{p.stem}] {text}"),
                            "src": _rel(root, p), "kind": "comms",
                            "repo": card_repo})

    meta = {
        "outcome": {"docs": outcome_docs,
                    "docs_with_lessons": outcome_docs_with_lessons,
                    "docs_since_seed_rule": outcome_docs_since_seed,
                    "docs_seeded_since_rule": outcome_seeded_since,
                    "lines": sum(1 for r in out if r["kind"] == "outcome")},
        "jobs": {"docs": job_files,
                 "lines": sum(1 for r in out if r["kind"] == "job")},
        "comms": {"docs": card_files,
                  "lines": sum(1 for r in out if r["kind"] == "comms")},
    }
    return out, meta


# ------------------------------------------------------------------ utils

def _tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", (s or "").lower()))


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _content_tokens(s: str) -> set:
    return {t for t in _tokens(s)
            if len(t) >= 4 and t not in STOPWORDS
            and t not in DIRECTIVE_WORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------- check 1

def dup_clusters(recs: list) -> list:
    """Greedy single-linkage clusters over token-jaccard >= JACCARD_MIN.
    Exact-normalized duplicates collapse first (count preserved)."""
    groups = {}                    # norm_key -> {text, count, sources}
    for r in recs:
        key = _norm_key(r["text"])
        if not key:
            continue
        g = groups.setdefault(key, {"text": r["text"], "count": 0,
                                    "sources": set()})
        g["count"] += 1
        g["sources"].add(r["src"])

    items = []                     # (tokens, key)
    for key, g in groups.items():
        items.append((_tokens(g["text"]), key))
    n = len(items)

    # candidate pairs: only lines sharing >=1 token, and only when
    # size ratio can still reach JACCARD_MIN (J <= min/max).
    index = {}
    for i, (toks, _) in enumerate(items):
        for t in toks:
            index.setdefault(t, []).append(i)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    seen_pairs = set()
    for postings in index.values():
        if len(postings) > 800:
            continue   # ubiquitous token: pairs sharing ONLY it can
                       # never reach JACCARD_MIN anyway
        for x in range(len(postings)):
            for y in range(x + 1, len(postings)):
                i, j = postings[x], postings[y]
                if (i, j) in seen_pairs:
                    continue
                seen_pairs.add((i, j))
                ti, tj = items[i][0], items[j][0]
                if min(len(ti), len(tj)) / max(len(ti), len(tj)) \
                        < JACCARD_MIN:
                    continue
                if _jaccard(ti, tj) >= JACCARD_MIN:
                    union(i, j)

    clusters = {}
    for i, (_, key) in enumerate(items):
        clusters.setdefault(find(i), []).append(key)

    out = []
    for keys in clusters.values():
        total = sum(groups[k]["count"] for k in keys)
        if total < 2:
            continue
        rep_key = max(keys, key=lambda k: groups[k]["count"])
        rep = groups[rep_key]
        out.append({
            "count": total,
            "variants": len(keys),
            "representative": rep["text"],
            "sources": sorted({s for k in keys
                               for s in groups[k]["sources"]})[:6],
        })
    out.sort(key=lambda c: -c["count"])
    return out


# --------------------------------------------------------------- check 2

def stale_flags(recs: list, root: Path) -> list:
    out = []
    for r in recs:
        text = r["text"]
        hits = []
        for m in RETIRED_RE.finditer(text):
            hits.append(f"retired-ref:{m.group(0).lower()}")
        for m in REPO_PATH_RE.finditer(text):
            name = m.group(1)
            if name.startswith("dispatch-wt-"):
                continue            # transient worktree names
            if name not in KNOWN_REPOS:
                hits.append(f"renamed-repo:{name}")
        # missing-path is only checkable for this repo: card comms on a
        # card declared for another repo carry that repo's paths.
        check_paths = (r.get("repo") or "chaba") == "chaba"
        for m in FILE_PATH_RE.finditer(text):
            rel = m.group(1)
            if m.start() > 0 and text[m.start() - 1] in "/~":
                continue            # absolute/home path, not repo-rel
            if rel.split("/", 1)[0] in KNOWN_REPOS:
                rel = rel.split("/", 1)[1]   # strip leading repo name
            first = rel.split("/", 1)[0]
            if first.startswith(".") or not (root / first).exists():
                continue            # other repo / data store / home
            if check_paths and not (root / rel).exists():
                hits.append(f"missing-path:{rel}")
        if hits:
            out.append({"text": text, "src": r["src"],
                        "kind": r["kind"], "hits": sorted(set(hits))})
    return out


# --------------------------------------------------------------- check 3

def contradiction_candidates(recs: list) -> list:
    """Group by top-3 content tokens (rarest first — discriminating
    signature), then report neg-only vs pos-only line pairs."""
    df = Counter()
    toks_per = []
    for r in recs:
        toks = _content_tokens(r["text"])
        toks_per.append(toks)
        for t in toks:
            df[t] += 1

    groups = {}
    for i, r in enumerate(recs):
        toks = toks_per[i]
        if len(toks) < 2:
            continue
        sig = tuple(sorted(
            sorted(toks, key=lambda t: (df[t], t))[:3]))
        groups.setdefault(sig, []).append(i)

    pairs = []
    for sig, idxs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(idxs) < 2:
            continue
        neg, pos = [], []
        for i in idxs:
            t = recs[i]["text"]
            n = bool(NEG_DIRECTIVE_RE.search(t))
            p = bool(POS_DIRECTIVE_RE.search(t))
            if n and not p:
                neg.append(i)
            elif p and not n:
                pos.append(i)
        for ni in neg[:3]:
            for pi in pos[:3]:
                pairs.append({
                    "signature": list(sig),
                    "negative": {"text": recs[ni]["text"],
                                 "src": recs[ni]["src"]},
                    "positive": {"text": recs[pi]["text"],
                                 "src": recs[pi]["src"]},
                })
                if len(pairs) >= 60:
                    return pairs
    return pairs


# ------------------------------------------------------------- reporting

def _fingerprint(dups: list, stale: list, contra: list) -> str:
    h = hashlib.sha256()
    for c in dups:
        h.update(_norm_key(c["representative"]).encode())
    for f in stale:
        h.update(_norm_key(f["text"]).encode())
    for p in contra:
        h.update(_norm_key(p["negative"]["text"]).encode())
        h.update(_norm_key(p["positive"]["text"]).encode())
    return h.hexdigest()[:16]


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1) + "\n")
    except Exception as e:
        print(f"warn: state write failed: {e}", file=sys.stderr)


def ops_event(detail: str) -> None:
    """Same shape as kanban-dispatch.ops_event — ada-ha-events-tony
    doc, kind ops-event; lands in the ada ops digest."""
    try:
        now = datetime.now(timezone.utc)
        req = urllib.request.Request(
            f"{MDDB}/add",
            data=json.dumps({
                "collection": "ada-ha-events-tony",
                "key": f"ops-lesson-qc-{now:%Y%m%d%H%M%S%f}",
                "lang": "en", "contentMd": detail,
                "meta": {"kind": ["ops-event"], "type": ["lesson_qc"],
                         "instance": ["tony"],
                         "ts": [now.isoformat(timespec="seconds")],
                         "written_by": ["lesson-qc"]}}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"warn: ops event failed: {e}", file=sys.stderr)


def _write_if_changed(path: Path, content: str, dry: bool) -> str:
    if path.exists() and path.read_text(errors="replace") == content:
        return "unchanged"
    if dry:
        return "would-write"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return "written"


def _cap_listing(items: list) -> tuple:
    return items[:MAX_REPORT_ITEMS], max(0, len(items) - MAX_REPORT_ITEMS)


def render_markdown(day: str, meta: dict, growth: dict, dups: list,
                    stale: list, contra: list, flag_count: int) -> str:
    L = []
    a = L.append
    a(f"# Lesson corpus QC — {day}")
    a("")
    a("Advisory sweep over the self-reported lesson corpus "
      "(dispatch-outcome `lessons:` lists, job-doc lesson fields, card "
      "comms). Report-only — nothing here deletes or edits the corpus; "
      "retire lessons deliberately.")
    a("")
    a("## Health")
    a("")
    a("| source | docs | lines |")
    a("|---|---|---|")
    for k in ("outcome", "jobs", "comms"):
        s = meta[k]
        a(f"| {k} | {s['docs']} | {s['lines']} |")
    total = sum(meta[k]["lines"] for k in meta)
    a(f"| **total** | — | **{total}** |")
    a("")
    a(f"Growth since last run: {growth.get('delta', 'n/a')} lines "
      f"(prev total {growth.get('prev', 'n/a')}).")
    od = meta["outcome"]
    pct = (100 * od["docs_with_lessons"] / od["docs"]) if od["docs"] else 0
    pct2 = (100 * od["docs_seeded_since_rule"]
            / od["docs_since_seed_rule"]) if od["docs_since_seed_rule"] else 0
    a(f"Self-seeding compliance: {od['docs_with_lessons']}/{od['docs']} "
      f"outcome docs carry a parseable `lessons:` list ({pct:.0f}%); "
      f"since the {SELF_SEED_SINCE} TASK_RAILS rule: "
      f"{od['docs_seeded_since_rule']}/{od['docs_since_seed_rule']} "
      f"({pct2:.0f}%).")
    a("")
    a(f"**Flag count: {flag_count}** "
      f"({len(dups)} dup clusters, {len(stale)} stale lines, "
      f"{len(contra)} contradiction-candidate pairs).")
    a("")

    a(f"## Duplicates ({len(dups)} clusters, token-jaccard >= "
      f"{JACCARD_MIN})")
    a("")
    shown, more = _cap_listing(dups)
    for c in shown:
        a(f"- **x{c['count']}** ({c['variants']} variants) "
          f"{c['representative']}")
        a(f"  - sources: {', '.join(c['sources'])}")
    if more:
        a(f"- … {more} more clusters")
    a("")

    a(f"## Stale references ({len(stale)} lines)")
    a("")
    a("`retired-ref` = retired infra mention (idc01 ada/mddb roles, "
      "dell tailnet endpoint — review hints, not verdicts: idc01 "
      "returned as warm-DR); `missing-path` = repo path no longer "
      "exists; `renamed-repo` = unknown CascadeProjects checkout.")
    a("")
    shown, more = _cap_listing(stale)
    for f in shown:
        a(f"- [{f['kind']}] {f['text']}")
        a(f"  - {f['src']} — {', '.join(f['hits'])}")
    if more:
        a(f"- … {more} more stale lines")
    a("")

    a(f"## Contradiction candidates ({len(contra)} pairs)")
    a("")
    a("Lines sharing a top-3-token signature but carrying opposing "
      "directive markers (never/do-not vs must/always).")
    a("")
    shown, more = _cap_listing(contra)
    for p in shown:
        a(f"- signature `{'+'.join(p['signature'])}`")
        a(f"  - NEG ({p['negative']['src']}): {p['negative']['text']}")
        a(f"  - POS ({p['positive']['src']}): {p['positive']['text']}")
    if more:
        a(f"- … {more} more pairs")
    a("")
    return "\n".join(L)


def render_job_yml(day: str, meta: dict, growth: dict, dups: list,
                   stale: list, contra: list, flag_count: int,
                   fingerprint: str) -> str:
    # Field names deliberately avoid the primer's lesson-key regex
    # (gotcha|lesson|pitfall|fail) so this record doesn't re-ingest
    # itself into the corpus it measures.
    doc = {
        "title": f"lesson-qc sweep {day} — {flag_count} flags "
                 f"({len(dups)} dup, {len(stale)} stale, "
                 f"{len(contra)} contradiction)",
        "subtitle": "advisory QC over the self-reported lesson corpus "
                    "— report-only damping layer, never deletes",
        "icon": "🧹",
        "id": f"{day}-lesson-qc",
        "status": "done",
        "owner": "lesson-qc",
        "project": "chaba",
        "card": "lesson-qc-sweep",
        "started": day,
        "completed": day,
        "corpus": {
            "outcome": meta["outcome"],
            "jobs": meta["jobs"],
            "comms": meta["comms"],
            "total_lines": sum(meta[k]["lines"] for k in meta),
        },
        # prev_at lives in the .md report only — volatile timestamps in
        # the yml would defeat unchanged-write convergence.
        "growth": {"delta": growth["delta"], "prev": growth["prev"]},
        "findings": {
            "dup_clusters": len(dups),
            "dup_cluster_top": [
                {"count": c["count"], "representative": c["representative"]}
                for c in dups[:10]],
            "stale_lines": len(stale),
            "stale_sample": [
                {"src": f["src"], "hits": f["hits"],
                 "text": f["text"][:160]}
                for f in stale[:10]],
            "contradiction_pairs": len(contra),
            "contradiction_sample": [
                {"signature": p["signature"],
                 "negative": p["negative"]["text"][:140],
                 "positive": p["positive"]["text"][:140]}
                for p in contra[:5]],
        },
        "flag_count": flag_count,
        "flag_fingerprint": fingerprint,
        "ops_event_threshold": OPS_EVENT_THRESHOLD,
        "report": f"reports/lesson-qc-{day}.md",
        "invocation": "best-effort tail of devin-dispatch-watch.sh — "
                      "same mechanism render-handoff-inbox.py uses; "
                      "chosen over a standalone timer because the "
                      "corpus grows exactly when dispatches land, "
                      "which is what the watcher already polls",
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          width=100)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--state", type=Path, default=STATE_PATH)
    ap.add_argument("--jobs-dir", type=Path, default=None)
    ap.add_argument("--reports-dir", type=Path, default=None)
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD label (default: today, ICT)")
    ap.add_argument("--dry-run", action="store_true",
                    help="analyze + print; write nothing")
    ap.add_argument("--no-ops-event", action="store_true",
                    help="skip the ada-ha-events-tony ops-event emit")
    args = ap.parse_args()

    root = args.root.resolve()
    day = args.date or datetime.now(ICT).strftime("%Y-%m-%d")
    jobs_dir = args.jobs_dir or root / "docs/ssot/jobs/kanban"
    reports_dir = args.reports_dir or root / "reports"

    recs, meta = harvest(root)
    total = sum(meta[k]["lines"] for k in meta)

    state = _load_state(args.state)
    prev = (state.get("corpus") or {}).get("total_lines")
    growth = {
        "delta": (total - prev) if prev is not None else None,
        "prev": prev,
        "prev_at": state.get("last_run"),
    }

    dups = dup_clusters(recs)
    stale = stale_flags(recs, root)
    contra = contradiction_candidates(recs)
    flag_count = len(dups) + len(stale) + len(contra)
    fingerprint = _fingerprint(dups, stale, contra)

    md = render_markdown(day, meta, growth, dups, stale, contra,
                         flag_count)
    yml = render_job_yml(day, meta, growth, dups, stale, contra,
                         flag_count, fingerprint)

    if args.dry_run:
        print(md[:4000])
        print(f"---\ndry-run: {len(recs)} lines, {flag_count} flags, "
              f"fingerprint {fingerprint}")
        return 0

    y_status = _write_if_changed(jobs_dir / f"{day}-lesson-qc.yml", yml,
                                 dry=False)
    m_status = _write_if_changed(reports_dir / f"lesson-qc-{day}.md", md,
                                 dry=False)

    new_state = {
        "last_run": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "corpus": {"total_lines": total,
                   **{k: meta[k]["lines"] for k in meta}},
        "last_flags": flag_count,
        "last_fingerprint": fingerprint,
        "last_ops_event": state.get("last_ops_event"),
    }

    # Ops event: flag count over threshold, deduped by fingerprint with
    # a min-interval floor so the 5-min watch cadence can't spam.
    emitted = False
    if (not args.no_ops_event
            and os.environ.get("LESSON_QC_OPS_EVENT", "1") != "0"
            and flag_count > OPS_EVENT_THRESHOLD):
        last = state.get("last_ops_event") or {}
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(last["at"])).total_seconds()
        except Exception:
            age = OPS_EVENT_MIN_INTERVAL + 1
        if last.get("fingerprint") != fingerprint \
                or age > OPS_EVENT_MIN_INTERVAL:
            detail = (
                f"lesson-qc {day}: {flag_count} flags on {total} corpus "
                f"lines — {len(dups)} dup clusters, {len(stale)} stale "
                f"refs, {len(contra)} contradiction candidates. "
                f"self-seed compliance {meta['outcome']['docs_with_lessons']}"
                f"/{meta['outcome']['docs']} outcome docs. "
                f"report: reports/lesson-qc-{day}.md")
            ops_event(detail)
            emitted = True
            new_state["last_ops_event"] = {
                "at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"),
                "fingerprint": fingerprint, "flags": flag_count}

    _save_state(args.state, new_state)

    print(f"lesson-qc {day}: {total} lines "
          f"({meta['outcome']['lines']} outcome / {meta['jobs']['lines']} "
          f"jobs / {meta['comms']['lines']} comms), "
          f"flags={flag_count} [{len(dups)} dup, {len(stale)} stale, "
          f"{len(contra)} contra], job-yml={y_status}, report={m_status}"
          f"{', ops-event' if emitted else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
