#!/usr/bin/env python3
"""primer_efficacy — prove or kill the lesson-primer compounding claim.

Card primer-efficacy-measurement (OPS-1270). Read-only offline analysis
over the card corpus + dispatch-outcome docs; runs anywhere with a chaba
checkout. Answers four questions:

  1. Coverage   — % of dispatches since primer launch (2026-10-09) that
                  logged "primer injected N lesson(s)" in card comms.
                  Dispatches come in two lanes: kanban-dispatch start
                  ("dispatched <task> on <repo>", primer-capable) and
                  runner-agent claims ("started devin-task-<id> on <host>
                  (dispatch)", never primed). Both are reported — the
                  runner lane is the structurally dead fraction.
  2. Repeat-failure — for failure events recorded AFTER a primer
                  injection on the same card, was the failure's topic
                  signature (primer-style tokens, MIN_SCORE=2 distinct
                  keyword hits) present in an injected lesson preview?
                  I.e. did we fail on something we were warned about?
  3. Success    — card-level verified/merge rate, pre-primer era vs
                  post-era (primed / unprimed / runner cohorts). Raw
                  numbers only; confounds are reported, never a causal
                  claim.
  4. Dead-primer — dispatches with no recorded injection, split by
                  lane, plus a live health probe: does lesson_primer
                  .build() still run on this corpus today?

Failure events are reconstructed from card comms (test gate failed,
auto-merge conflicts, merge held, parked, no delivered work, exit
failures, FALSE-VERIFIED, dispatch/start failed) plus action.last_failure
deduped by normalized text. Repo-sync noise (local-conflict churn) is
deliberately not a failure class.

Usage: primer_efficacy.py [--md|--json] [--root PATH] [--since DATE]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

LAUNCH = "2026-10-09"          # primer merged 15:46 ICT this day
MIN_SCORE = 2                  # mirrors lesson_primer.MIN_SCORE
LINE_PREVIEW_SPLIT = re.compile(r";\s+")

DISPATCH_RE = re.compile(r"^dispatched (\S+) on (\S+)")
RUNNER_RE = re.compile(r"^started devin-task-(\S+) on (\S+) \(dispatch\)")
PRIMER_RE = re.compile(r"^primer injected (\d+) lesson\(s\):\s*(.*)", re.S)
MERGE_RE = re.compile(
    r"auto-merged|already in \S+.*marked verified|merge-sweep:.*verified|"
    r"verified — auto-closed|doubly-verified", re.I)
FALSE_VERIFIED_RE = re.compile(r"false-?verified", re.I)

FAILURE_CLASSES = [
    ("test-gate", re.compile(r"test gate failed", re.I)),
    ("merge-conflict", re.compile(r"auto-merge conflicts|merge conflicts", re.I)),
    ("merge-held", re.compile(r"merge held|executor contract requires", re.I)),
    ("no-delivered-work", re.compile(r"no delivered work|nothing committed", re.I)),
    ("exit-failure", re.compile(
        r"did not exit|exit_code=[1-9]|Failed with result|"
        r"finished \(failed\)|exit=[1-9]", re.I)),
    ("parked", re.compile(r"dispatch parked after|parked — re-?queue", re.I)),
    ("start-failed", re.compile(r"dispatch failed|start failed", re.I)),
    ("false-verified", FALSE_VERIFIED_RE),
]

STOPWORDS = {
    "this", "that", "with", "from", "into", "when", "then", "than",
    "have", "been", "will", "would", "should", "could", "about", "after",
    "before", "the", "and", "for", "are", "was", "were", "not", "all",
    "any", "each", "card", "task", "work", "spec", "your", "them",
    "they", "their", "there", "here", "what", "which", "while",
}


def _tokens(s: str) -> list:
    """Same tokenization lesson_primer uses."""
    return re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", (s or "").lower())


def signature(text: str) -> set:
    return {t for t in _tokens(text) if len(t) >= 4 and t not in STOPWORDS}


def _score(text: str, kws: set) -> int:
    """Primer scoring: distinct keywords present as substrings."""
    tl = text.lower()
    return sum(1 for k in kws if k in tl)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()[:80]


def iter_cards(root: Path):
    """Yield (card_id, doc, path). cards/ wins over archive/ on a clash;
    comms are unioned when a card exists in both."""
    seen = {}
    for sub in ("", "archive"):
        for p in sorted((root / "docs/ssot/kanban/cards" / sub).glob("*.yml")):
            try:
                doc = yaml.safe_load(p.read_text(errors="replace")) or {}
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            cid = str(doc.get("id") or p.stem)
            if cid in seen:
                prev_doc, prev_p = seen[cid]
                if sub == "":  # live card wins; merge comms
                    prev = prev_doc.get("comms") or []
                    doc["comms"] = (doc.get("comms") or []) + [
                        c for c in prev if c not in (doc.get("comms") or [])]
                    seen[cid] = (doc, p)
                continue
            seen[cid] = (doc, p)
    for cid, (doc, p) in sorted(seen.items()):
        yield cid, doc, p


def comms_events(doc):
    """Chronological comms entries; non-dict entries tolerated."""
    out = []
    for i, c in enumerate(doc.get("comms") or []):
        if isinstance(c, dict):
            out.append({"at": str(c.get("at") or f"~{i:04d}"),
                        "from": str(c.get("from") or "?"),
                        "text": str(c.get("text") or "")})
        else:
            out.append({"at": f"~{i:04d}", "from": "?",
                        "text": str(c)})
    out.sort(key=lambda e: e["at"])
    return out


def classify_failure(text: str) -> str | None:
    for name, rx in FAILURE_CLASSES:
        if rx.search(text):
            return name
    return None


def analyze(root: Path, since: str = LAUNCH) -> dict:
    dispatches = []            # every dispatch event, both lanes
    failures_after_primer = [] # failure events attributable to an injection
    primed_previews = {}       # card_id -> list of injected lesson texts
    cards = {}                 # card_id -> {doc, events, path}

    for cid, doc, path in iter_cards(root):
        events = comms_events(doc)
        cards[cid] = {"doc": doc, "events": events, "path": str(path)}
        last_primer = None     # (at, n, [previews])
        card_fail_norms = set()
        for e in events:
            t, at = e["text"], e["at"]
            m = DISPATCH_RE.match(t)
            if m:
                dispatches.append({
                    "card": cid, "at": at, "task": m.group(1),
                    "repo": m.group(2), "lane": "kanban-dispatch",
                    "primed": None, "n_lines": 0})
                last_primer = None
                continue
            m = RUNNER_RE.match(t)
            if m:
                dispatches.append({
                    "card": cid, "at": at, "task": m.group(1),
                    "repo": None, "lane": "runner-agent",
                    "primed": False, "n_lines": 0})
                continue
            m = PRIMER_RE.match(t)
            if m and dispatches:
                n = int(m.group(1))
                previews = [x.strip() for x in
                            LINE_PREVIEW_SPLIT.split(m.group(2)) if x.strip()]
                # attribute to the most recent kanban-lane dispatch
                for d in reversed(dispatches):
                    if d["card"] == cid and d["lane"] == "kanban-dispatch" \
                            and d["primed"] is None:
                        d["primed"], d["n_lines"] = True, n
                        break
                last_primer = (at, previews)
                primed_previews.setdefault(cid, []).extend(previews)
                continue
            cls = classify_failure(t)
            if cls:
                card_fail_norms.add(_norm(t))
                if last_primer:
                    sig = signature(t)
                    previews = last_primer[1]
                    warned = any(_score(p, sig) >= MIN_SCORE for p in previews)
                    failures_after_primer.append({
                        "card": cid, "at": at, "class": cls,
                        "warned": warned, "sig": sorted(sig)[:10],
                        "text": t[:160],
                        "matched": [p[:80] for p in previews
                                    if _score(p, sig) >= MIN_SCORE][:2]})

        # action.last_failure as a synthetic event if not already in comms
        a = doc.get("action") or {}
        lf = str(a.get("last_failure") or "")
        if lf and _norm(lf) not in card_fail_norms and last_primer:
            sig = signature(lf)
            previews = last_primer[1]
            failures_after_primer.append({
                "card": cid, "at": str(doc.get("updated") or "?"),
                "class": classify_failure(lf) or "other",
                "warned": any(_score(p, sig) >= MIN_SCORE for p in previews),
                "sig": sorted(sig)[:10], "text": lf[:160],
                "matched": [p[:80] for p in previews
                            if _score(p, sig) >= MIN_SCORE][:2]})

    # ---- metric 1+4: coverage / dead-primer ----------------------------------
    post = [d for d in dispatches if d["at"] >= since]
    pre = [d for d in dispatches if d["at"] < since]
    kpost = [d for d in post if d["lane"] == "kanban-dispatch"]
    for d in kpost:
        if d["primed"] is None:
            d["primed"] = False
    primed = [d for d in kpost if d["primed"]]
    n_dist = Counter(d["n_lines"] for d in primed)
    coverage = {
        "since": since,
        "kanban_lane_dispatches": len(kpost),
        "runner_lane_dispatches": len(post) - len(kpost),
        "pre_era_dispatches": len(pre),
        "primed": len(primed),
        "coverage_kanban_lane": (len(primed) / len(kpost)) if kpost else None,
        "coverage_all_lanes": (len(primed) / len(post)) if post else None,
        "n_lines_distribution": dict(sorted(n_dist.items())),
        "dead_kanban_dispatches": [
            {"card": d["card"], "at": d["at"], "task": d["task"]}
            for d in kpost if not d["primed"]],
        # earliest/latest injection for the "when did it die" line
        "last_injection_at": max((d["at"] for d in primed), default=None),
    }

    # ---- metric 2: repeat-failure --------------------------------------------
    warned = [f for f in failures_after_primer if f["warned"]]
    repeat = {
        "failures_after_injection": len(failures_after_primer),
        "warned": len(warned),
        "unwarned": len(failures_after_primer) - len(warned),
        "warned_rate": (len(warned) / len(failures_after_primer))
                       if failures_after_primer else None,
        "by_class": dict(Counter(f["class"]
                                 for f in failures_after_primer)),
        "events": failures_after_primer,
    }

    # ---- metric 3: success comparison (card level, first dispatch sets era) --
    cohorts = defaultdict(lambda: {"cards": set(), "verified": set(),
                                   "merged": set(), "attempts": []})
    card_cohort = {}
    for d in dispatches:
        cid = d["card"]
        if cid in card_cohort:
            continue
        if d["at"] < since:
            cohort = "pre-era"
        elif d["lane"] == "runner-agent":
            cohort = "post-runner"
        else:
            cohort = "post-kanban"  # primed flag set later; split below
        card_cohort[cid] = cohort
    # refine post-kanban into primed/unprimed
    primed_cards = {d["card"] for d in primed}
    for cid, c in card_cohort.items():
        if c == "post-kanban":
            card_cohort[cid] = "post-primed" if cid in primed_cards \
                else "post-unprimed"
    for cid, cohort in card_cohort.items():
        doc = cards[cid]["doc"]
        a = doc.get("action") or {}
        evs = cards[cid]["events"]
        c_bucket = cohorts[cohort]
        c_bucket["cards"].add(cid)
        if a.get("verified") is True:
            c_bucket["verified"].add(cid)
        if any(MERGE_RE.search(e["text"]) for e in evs):
            c_bucket["merged"].add(cid)
        att = a.get("attempts")
        if isinstance(att, int) and att:
            c_bucket["attempts"].append(att)
    success = {}
    for name, b in cohorts.items():
        n = len(b["cards"])
        success[name] = {
            "cards": n,
            "verified": len(b["verified"]),
            "verified_rate": len(b["verified"]) / n if n else None,
            "merged": len(b["merged"]),
            "merged_rate": len(b["merged"]) / n if n else None,
            "mean_attempts": (sum(b["attempts"]) / len(b["attempts"]))
                             if b["attempts"] else None,
        }

    # ---- primer health probe: does build() still work on THIS corpus? --------
    health = {"importable": None, "build_ok": None, "error": None}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import lesson_primer as lp
        health["importable"] = True
        try:
            sample_card = {"id": "primer-efficacy-measurement",
                           "title": "primer efficacy measurement",
                           "spec": "kanban dispatch primer"}
            lines = lp.build(sample_card, "idc03", "chaba", root)
            health["build_ok"] = True
            health["sample_lines"] = len(lines)
        except Exception as e:  # the fail-open path kanban-dispatch hits
            health["build_ok"] = False
            health["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        health["importable"] = False
        health["error"] = f"{type(e).__name__}: {e}"

    # ---- self-seeding: are outcome docs still growing the corpus? ------------
    outcome_docs = sorted(root.glob("dispatch-outcome-*.md"))
    post_docs = [p for p in outcome_docs
                 if p.name[17:25] >= since.replace("-", "")]
    with_lessons = 0
    for p in post_docs:
        try:
            if re.search(r"^\s*lessons:", p.read_text(errors="replace"),
                         re.M):
                with_lessons += 1
        except Exception:
            pass
    seeding = {"outcome_docs_total": len(outcome_docs),
               "outcome_docs_post_launch": len(post_docs),
               "with_lessons_block": with_lessons}

    # ---- verdict --------------------------------------------------------------
    cov_all = coverage["coverage_all_lanes"] or 0
    if health["build_ok"] is False or cov_all < 0.15:
        verdict = "contradicted"
        basis = ("the compounding mechanism is not running: primer "
                 "injection is effectively dead "
                 f"(coverage {cov_all:.0%} of post-launch dispatches; "
                 f"build() probe: {health['error'] or 'ok'}). With no "
                 "injections there is nothing to compound — efficacy "
                 "itself is untestable on n="
                 f"{len(primed)} primed dispatches.")
    elif len(primed) < 30 or repeat["failures_after_injection"] < 10:
        verdict = "inconclusive"
        basis = ("primer runs but the primed sample is too small to "
                 "support or refute compounding.")
    else:
        pre_v = (success.get("pre-era") or {}).get("verified_rate")
        post_v = (success.get("post-primed") or {}).get("verified_rate")
        if pre_v is not None and post_v is not None and post_v >= pre_v:
            verdict = "supported"
            basis = (f"post-era primed verified rate {post_v:.0%} >= "
                     f"pre-era {pre_v:.0%} (observational, not causal).")
        else:
            verdict = "contradicted"
            basis = (f"post-era primed verified rate {post_v} < "
                     f"pre-era {pre_v} (observational, not causal).")

    # ---- spot-check handles ---------------------------------------------------
    spot = []
    if primed:
        d = primed[0]
        spot.append({"kind": "primed-dispatch", **{k: d[k] for k in
                     ("card", "at", "task", "n_lines")}})
    dead = coverage["dead_kanban_dispatches"]
    if dead:
        spot.append({"kind": "dead-dispatch", **dead[0]})
    for f in failures_after_primer:
        if not f["warned"]:
            spot.append({"kind": "unwarned-failure",
                         "card": f["card"], "at": f["at"],
                         "class": f["class"], "text": f["text"]})
            break
    for f in failures_after_primer:
        if f["warned"]:
            spot.append({"kind": "warned-failure",
                         "card": f["card"], "at": f["at"],
                         "class": f["class"], "text": f["text"],
                         "matched": f["matched"]})
            break

    return {"generated_from": str(root), "since": since,
            "cards_scanned": len(cards), "verdict": verdict,
            "verdict_basis": basis, "coverage": coverage,
            "repeat_failure": repeat, "success": success,
            "primer_health": health, "self_seeding": seeding,
            "spot_check": spot}


def render_md(r: dict) -> str:
    c, rep, s, h, seed = (r["coverage"], r["repeat_failure"],
                          r["success"], r["primer_health"],
                          r["self_seeding"])
    L = []
    L.append(f"# Primer efficacy — {r['since']} corpus scan\n")
    L.append(f"**Verdict: {r['verdict'].upper()}** — {r['verdict_basis']}\n")
    L.append("\n## Coverage / dead-primer\n")
    L.append("| lane | dispatches | primed | coverage |")
    L.append("|---|---|---|---|")
    kc = c["coverage_kanban_lane"]
    L.append(f"| kanban-dispatch | {c['kanban_lane_dispatches']} | "
             f"{c['primed']} | {(f'{kc:.0%}' if kc is not None else 'n/a')} |")
    L.append(f"| runner-agent | {c['runner_lane_dispatches']} | 0 | 0% "
             "(no primer code path) |")
    allc = c["coverage_all_lanes"]
    L.append(f"| **all post-launch** | {c['kanban_lane_dispatches'] + c['runner_lane_dispatches']} | "
             f"{c['primed']} | {(f'{allc:.1%}' if allc is not None else 'n/a')} |")
    L.append(f"\nPre-era dispatches (context): {c['pre_era_dispatches']}. "
             f"Last recorded injection: {c['last_injection_at']}. "
             f"Line-count distribution: {c['n_lines_distribution']}.\n")
    L.append("\n## Primer health probe (live corpus)\n")
    L.append(f"- importable: `{h['importable']}`, build_ok: `{h['build_ok']}`"
             + (f", sample lines: {h.get('sample_lines')}"
                if h.get("build_ok") else f", error: `{h['error']}`"))
    L.append("\n## Repeat-failure (did we fail on warned topics?)\n")
    L.append(f"- failures recorded after an injection: "
             f"{rep['failures_after_injection']} "
             f"(warned {rep['warned']}, unwarned {rep['unwarned']})")
    L.append(f"- by class: {rep['by_class']}")
    if rep["events"]:
        L.append("\n| at | card | class | warned? | failure |")
        L.append("|---|---|---|---|---|")
        for f in rep["events"]:
            L.append(f"| {f['at']} | {f['card']} | {f['class']} | "
                     f"{'yes' if f['warned'] else 'no'} | "
                     f"{f['text'][:90].replace('|', '/')} |")
    L.append("\n## Success by cohort (card level, first dispatch sets era)\n")
    L.append("| cohort | cards | verified | merged | mean attempts |")
    L.append("|---|---|---|---|---|")
    for name in ("pre-era", "post-primed", "post-unprimed", "post-runner"):
        b = s.get(name)
        if not b:
            continue
        fmt = lambda v: f"{v:.0%}" if v is not None else "n/a"
        L.append(f"| {name} | {b['cards']} | {b['verified']} "
                 f"({fmt(b['verified_rate'])}) | {b['merged']} "
                 f"({fmt(b['merged_rate'])}) | "
                 f"{b['mean_attempts'] if b['mean_attempts'] else 'n/a'} |")
    L.append("\n## Self-seeding\n")
    L.append(f"- outcome docs total {seed['outcome_docs_total']}, "
             f"post-launch {seed['outcome_docs_post_launch']}, "
             f"with `lessons:` block {seed['with_lessons_block']} "
             f"({(seed['with_lessons_block'] / seed['outcome_docs_post_launch'] * 100 if seed['outcome_docs_post_launch'] else 0):.0f}%)")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=Path(__file__).resolve().parents[2],
                    type=Path, help="chaba checkout root")
    ap.add_argument("--since", default=LAUNCH)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--out", type=Path, help="write rendered output here")
    args = ap.parse_args(argv)

    r = analyze(args.root, args.since)
    if args.json:
        out = json.dumps(r, indent=2, default=str)
    else:
        out = render_md(r)
    if args.out:
        args.out.write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
