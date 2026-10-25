#!/usr/bin/env python3
"""lane-savings — monthly lane-usage / token-savings report.

Reads durable usage evidence and emits a per-lane accounting of which
work ran off the paid Devin lane. Card devnest-token-savings-lane-catalog
(OPS-0869). Catalog: docs/ssot/infrastructure/ssot.devnest-lanes.yml.

HARD RULE (from the card spec): never claim savings without usage
evidence. A lane use counts toward savings only when the run COMPLETED
and left evidence: an action.result string, a token-count JSON fragment
(opencode step-finish), a declared artifact, or a comms/job-doc
measurement. Unevidenced lane selections are reported as counts only —
never as dollars or avoided tokens.

Evidence sources (all in-repo / worktree-local):
  * docs/ssot/kanban/cards/*.yml  — action.{type,lane,model,status,
    runner,result,verified}, auto_close.at
  * dispatch-outcome-YYYYMMDD-*.md — merged dispatch session outcomes
    (repo root): the devin-lane baseline stream
  * reports/*.json + docs/reports/**/*.json — pack/bench artifacts in
    the bench-edu-manage shape (scores.<lane>.loop.{tokens_in,
    tokens_out,cost_usd,completed,total})

Usage:
  python3 scripts/board/lane-savings.py                    # current month -> stdout summary
  python3 scripts/board/lane-savings.py --month 2026-10 --out-dir docs/reports
  python3 scripts/board/lane-savings.py --month 2026-10 --json-out /tmp/x.json --md-out /tmp/x.md
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARDS_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"

# Lanes that represent work served off the paid Devin/frontier path.
# Lane ids follow ssot.devnest-lanes.yml; 'devin' and 'paid_frontier'
# are the paid baseline, 'manual' is neither.
CHEAP_LANES = {"deterministic", "codemod", "local-gpu-packs",
               "free-opencode", "free_lane"}
PAID_LANES = {"paid_frontier", "devin"}

TASK_DATE = re.compile(r"(?:devin-task|runner)-(?:[a-z0-9-]*?-)?(\d{8})-")
OUTCOME_DATE = re.compile(r"dispatch-outcome-(\d{8})-")
TOKENS_RE = re.compile(
    r'"tokens":\{"total":(\d+),"input":(\d+),"output":(\d+)')
OPENCODE_SIG = re.compile(r'"step-finish"|"tokens":\{')


def _month_of(*candidates) -> str | None:
    """First parseable YYYY-MM from a list of date-ish strings."""
    for c in candidates:
        if not c:
            continue
        s = str(c).strip()
        m = re.match(r"(\d{4})-(\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = re.match(r"(\d{4})(\d{2})\d{2}", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return None


def load_cards(cards_dir: Path) -> list[dict]:
    cards = []
    for p in sorted(cards_dir.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if isinstance(c, dict) and c.get("id"):
            c["_file"] = p.name
            cards.append(c)
    return cards


def card_month(card: dict) -> str | None:
    """Best evidence of WHEN the action ran: task-id date in result >
    auto_close.at > action.claim.since > card.updated."""
    a = card.get("action") or {}
    res = str(a.get("result") or "")
    m = TASK_DATE.search(res)
    if m:
        return _month_of(m.group(1))
    ac = card.get("auto_close") or {}
    return _month_of(ac.get("at"), (a.get("claim") or {}).get("since"),
                     card.get("updated"))


def card_lane(card: dict) -> str:
    """Attribute the execution lane. Explicit action.lane wins; then the
    opencode step-finish signature in action.result; then executor type."""
    a = card.get("action") or {}
    if a.get("lane"):
        return str(a["lane"])
    res = str(a.get("result") or "")
    if OPENCODE_SIG.search(res):
        return "free-opencode"
    t = a.get("type")
    if t in ("dispatch", "devin", "devin-dispatch", "self"):
        return "devin"
    if t in ("script", "container", "program"):
        return "deterministic"
    if t == "manual":
        return "manual"
    return "unclassified"


def card_evidence(card: dict) -> list[str]:
    """Which usage evidence the card carries."""
    a = card.get("action") or {}
    ev = []
    res = str(a.get("result") or "")
    if res.strip():
        ev.append("action.result")
    if TOKENS_RE.search(res):
        ev.append("tokens")
    if a.get("verified") or (card.get("auto_close") or {}).get("by"):
        ev.append("verified-close")
    if (card.get("comms") or []):
        ev.append("comms")
    return ev


def scan_pack_artifacts(repo: Path, month: str) -> list[dict]:
    """Bench/pack artifacts carrying per-lane token + cost evidence
    (bench-edu-manage shape: scores.<lane>.loop.tokens_in/out/cost_usd)."""
    hits = []
    pats = [str(repo / "reports" / "*.json"),
            str(repo / "docs" / "reports" / "**" / "*.json")]
    seen = set()
    for pat in pats:
        for f in glob.glob(pat, recursive=True):
            if f in seen:
                continue
            seen.add(f)
            try:
                d = json.loads(Path(f).read_text())
            except Exception:
                continue
            scores = d.get("scores") if isinstance(d, dict) else None
            if not isinstance(scores, dict):
                continue
            art_month = _month_of(d.get("at"), d.get("date"),
                                  Path(f).name)
            if art_month != month:
                continue
            for lane, runs in scores.items():
                for r in runs if isinstance(runs, list) else [runs]:
                    loop = (r or {}).get("loop") or {}
                    hits.append({
                        "artifact": str(Path(f).relative_to(repo)),
                        "lane": lane,
                        "tokens_in": loop.get("tokens_in"),
                        "tokens_out": loop.get("tokens_out"),
                        "cost_usd": loop.get("cost_usd"),
                        "tasks_completed": loop.get("completed"),
                        "tasks_total": loop.get("total"),
                        "lat_p50": loop.get("lat_p50"),
                    })
    return hits


def scan_dispatch_outcomes(repo: Path, month: str) -> dict:
    """Merged dispatch-outcome files per month — the devin-lane session
    stream. Filename carries the dispatch date."""
    per_month = {}
    for f in repo.glob("dispatch-outcome-*.md"):
        m = OUTCOME_DATE.match(f.name)
        if not m:
            continue
        mm = _month_of(m.group(1))
        per_month[mm] = per_month.get(mm, 0) + 1
    return {"by_month": per_month, "this_month": per_month.get(month, 0)}


def build(month: str, cards_dir: Path, repo: Path) -> dict:
    cards = load_cards(cards_dir)
    lanes: dict[str, dict] = {}
    monthly_cards = 0
    for c in cards:
        a = c.get("action") or {}
        if not a.get("type"):
            continue
        mm = card_month(c)
        if mm != month:
            continue
        monthly_cards += 1
        lane = card_lane(c)
        ent = lanes.setdefault(lane, {
            "cards": [], "completed": 0, "verified": 0,
            "tokens_total": 0, "tokens_in": 0, "tokens_out": 0,
            "token_evidenced": 0,
        })
        status = a.get("status")
        ev = card_evidence(c)
        ent["cards"].append({"id": c["id"], "status": status,
                             "runner": a.get("runner"), "evidence": ev})
        if status in ("done",):
            ent["completed"] += 1
            if a.get("verified") or (c.get("auto_close") or {}).get("by"):
                ent["verified"] += 1
        tm = TOKENS_RE.search(str(a.get("result") or ""))
        if tm:
            ent["token_evidenced"] += 1
            ent["tokens_total"] += int(tm.group(1))
            ent["tokens_in"] += int(tm.group(2))
            ent["tokens_out"] += int(tm.group(3))

    packs = scan_pack_artifacts(repo, month)
    outcomes = scan_dispatch_outcomes(repo, month)

    # Savings accounting — evidence-bound:
    # offload_sessions: completed cheap-lane runs WITH usage evidence.
    # tokens served off paid lane: only where the artifact recorded them.
    offloaded, unevidenced = [], []
    for lane, ent in lanes.items():
        if lane not in CHEAP_LANES:
            continue
        for c in ent["cards"]:
            (offloaded if c["status"] == "done" and c["evidence"]
             else unevidenced).append({"lane": lane, **c})
    pack_tokens = sum((h["tokens_in"] or 0) + (h["tokens_out"] or 0)
                      for h in packs)
    pack_cost = sum(h["cost_usd"] or 0.0 for h in packs)

    return {
        "month": month,
        "generated_at": datetime.datetime.now().astimezone()
                        .isoformat(timespec="seconds"),
        "policy": ("savings are claimed only for completed runs with "
                   "usage evidence; counts otherwise; no dollar figure "
                   "is emitted without measured tokens/cost"),
        "cards_in_month": monthly_cards,
        "lanes": lanes,
        "pack_lane_runs": packs,
        "pack_tokens": pack_tokens,
        "pack_cost_usd": round(pack_cost, 6),
        "dispatch_outcome_files": outcomes,
        "offloaded_sessions": offloaded,
        "unevidenced_lane_uses": unevidenced,
    }


def render_md(r: dict) -> str:
    L = []
    L.append(f"# Lane savings report — {r['month']}")
    L.append("")
    L.append(f"Generated {r['generated_at']} by `scripts/board/"
             "lane-savings.py`. Catalog: "
             "`docs/ssot/infrastructure/ssot.devnest-lanes.yml`.")
    L.append("")
    L.append(f"**Policy:** {r['policy']}.")
    L.append("")
    L.append("## Lane usage this month (board action evidence)")
    L.append("")
    L.append("| lane | cards | done | verified | token-evidenced | "
             "tokens (in/out) |")
    L.append("|---|---|---|---|---|---|")
    for lane in sorted(r["lanes"]):
        e = r["lanes"][lane]
        L.append(f"| {lane} | {len(e['cards'])} | {e['completed']} | "
                 f"{e['verified']} | {e['token_evidenced']} | "
                 f"{e['tokens_in']}/{e['tokens_out']} |")
    L.append("")
    L.append(f"Dispatch-outcome files merged for {r['month']}: "
             f"**{r['dispatch_outcome_files']['this_month']}** "
             "(devin-lane session stream).")
    L.append("")
    L.append("## Pack/bench artifacts (measured cheap-lane tokens)")
    L.append("")
    if r["pack_lane_runs"]:
        L.append("| artifact | lane | tasks | tokens in | tokens out | "
                 "cost_usd | p50 |")
        L.append("|---|---|---|---|---|---|---|")
        for h in r["pack_lane_runs"]:
            L.append(f"| {h['artifact']} | {h['lane']} | "
                     f"{h['tasks_completed']}/{h['tasks_total']} | "
                     f"{h['tokens_in']} | {h['tokens_out']} | "
                     f"{h['cost_usd']} | {h['lat_p50']} |")
        L.append("")
        L.append(f"Measured pack tokens: **{r['pack_tokens']:,}** "
                 f"(cost_usd {r['pack_cost_usd']}).")
    else:
        L.append("_No pack/bench artifacts with token evidence this "
                 "month._")
    L.append("")
    L.append("## Offloaded sessions (cheap lanes, evidence-bound)")
    L.append("")
    if r["offloaded_sessions"]:
        for s in r["offloaded_sessions"]:
            L.append(f"- `{s['id']}` lane={s['lane']} "
                     f"runner={s.get('runner')} "
                     f"evidence={','.join(s['evidence'])}")
    else:
        L.append("_None — no cheap-lane dispatch sessions with usage "
                 "evidence this month._")
    L.append("")
    if r["unevidenced_lane_uses"]:
        L.append("### Lane uses WITHOUT evidence (not claimed)")
        L.append("")
        for s in r["unevidenced_lane_uses"]:
            L.append(f"- `{s['id']}` lane={s['lane']} "
                     f"status={s['status']}")
        L.append("")
    L.append("## Honest bottom line")
    L.append("")
    n = len(r["offloaded_sessions"])
    tok = sum(e["tokens_total"] for l, e in r["lanes"].items()
              if l in CHEAP_LANES)
    if n == 0 and not r["pack_lane_runs"]:
        L.append("No measurable offloading this month — every dispatched "
                 "session ran the paid devin lane. Savings: **none "
                 "evidenced**.")
    else:
        L.append(f"{n} cheap-lane session(s) with usage evidence "
                 f"({tok:,} measured cheap-lane tokens) + "
                 f"{len(r['pack_lane_runs'])} measured pack run(s). "
                 "A dollar figure requires a measured paid-arm "
                 "comparison — see job docs for per-task reference "
                 "rates; do not extrapolate unmeasured sessions.")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--month", default=None,
                    help="YYYY-MM (default: current month)")
    ap.add_argument("--cards-dir", type=Path, default=CARDS_DIR)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="write lane-savings-<month>.{md,json} here "
                         "(durable doc, e.g. docs/reports)")
    ap.add_argument("--md-out", type=Path, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()
    month = args.month or datetime.date.today().strftime("%Y-%m")
    r = build(month, args.cards_dir, args.repo)
    md = render_md(r)
    if args.out_dir:
        args.md_out = args.out_dir / f"lane-savings-{month}.md"
        args.json_out = args.out_dir / f"lane-savings-{month}.json"
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(md)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(r, indent=1, default=str))
    # stdout summary always
    print(md)
    if args.md_out:
        print(f"\nwrote {args.md_out}", file=sys.stderr)
    if args.json_out:
        print(f"wrote {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
