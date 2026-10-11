#!/usr/bin/env python3
"""Render micro-bench results into reports/micro-polish/.

Reads scripts/micro-bench/results/*.json, writes:
  reports/micro-polish/LATEST.md   variant x metric table + adopt-gate verdict
  reports/micro-polish/trend.md    appended one summary row per new result

With --card <id>, posts a summary comment via board-api on tony-dell.
Safe to run with zero results: renders an empty table.

Adopt gate (from card micro-ai-input-polish): a polish variant is adopted
only if its tool-call match-rate >= the matching direct baseline AND
net tokens OR e2e latency is neutral-or-better AND fabricated calls do
not increase. If only noisy-input categories improve, the verdict is
"scope to those lanes" — not a universal layer.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import lib

REPORTS = Path(__file__).resolve().parents[2] / "reports" / "micro-polish"
LATEST = REPORTS / "LATEST.md"
TREND = REPORTS / "trend.md"
BOARD_API = "http://127.0.0.1:8787/comment"   # reached via ssh tony-dell
NOISY_CATS = ("asr_noise_en", "asr_noise_th", "thai_eng_mix", "typo",
              "fragment")
GUARD_CATS = ("clean", "chit_chat", "ambiguous", "gibberish")


def _fmt(v, suffix=""):
    return f"{v}{suffix}" if isinstance(v, (int, float)) else "—"


def _exact_rate(s):
    t = s.get("tool_call", {})
    wanted = t.get("exact", 0) + t.get("partial", 0) + t.get("none", 0)
    return round(t.get("exact", 0) / wanted, 3) if wanted else None


def _downstream_key(vdoc):
    ds = (vdoc.get("variant") or {}).get("downstream") or {}
    return (ds.get("provider"), ds.get("model"))


def collect_rows():
    newest = {}
    for path, doc in lib.iter_results():
        vid = (doc.get("variant") or {}).get("id", "?")
        if vid not in newest or doc.get("meta", {}).get("at", "") > \
                newest[vid][1].get("meta", {}).get("at", ""):
            newest[vid] = (path, doc)
    rows = []
    for vid, (path, doc) in sorted(newest.items()):
        v = doc.get("variant") or {}
        s = doc.get("summary") or {}
        t = s.get("tool_call", {})
        rows.append({
            "variant": vid,
            "polish": (v.get("polish") or {}).get("model") or "—",
            "downstream": (v.get("downstream") or {}).get("model", "?"),
            "n": s.get("n", 0), "ok": s.get("ok", 0),
            "exact": _exact_rate(s),
            "sim": s.get("mean_polish_sim"),
            "ent": s.get("mean_entities"),
            "polish_ms": s.get("mean_polish_ms"),
            "total_ms": s.get("mean_total_ms"),
            "net_tok": s.get("mean_net_tokens"),
            "ds_tok": s.get("mean_downstream_tokens"),
            "fab": t.get("fabricated", 0),
            "tally": f"{t.get('exact',0)}/{t.get('partial',0)}/"
                     f"{t.get('none',0)}/{t.get('fabricated',0)}",
            "per_cat": s.get("per_category", {}),
            "at": doc.get("meta", {}).get("at", "?"),
            "dry": doc.get("dry_run"),
            "path": path.name,
            "_key": _downstream_key(doc),
        })
    return rows


def verdicts(rows):
    """Pair each polish variant with the direct baseline on the same
    downstream; emit one verdict line per pair."""
    out = []
    for r in rows:
        if r["polish"] == "—" or r["dry"]:
            continue
        base = next((b for b in rows
                     if b["polish"] == "—" and b["_key"] == r["_key"]
                     and not b["dry"]), None)
        if not base or base["exact"] is None or r["exact"] is None:
            out.append(f"- **{r['variant']}**: no matching direct baseline "
                       f"(same downstream) — cannot gate yet.")
            continue
        ex_gain = r["exact"] - base["exact"]
        tok_ok = (r["net_tok"] is not None and base["ds_tok"] is not None
                  and r["net_tok"] <= base["ds_tok"] * 1.05)
        lat_ok = (r["total_ms"] is not None and base["total_ms"] is not None
                  and r["total_ms"] <= base["total_ms"] * 1.2)
        fab_ok = r["fab"] <= base["fab"]

        if r["exact"] >= base["exact"] and (tok_ok or lat_ok) and fab_ok:
            verdict = "ADOPT"
        elif ex_gain <= 0:
            verdict = "REJECT (no match-rate gain)"
        else:
            noisy_base = sum(base["per_cat"].get(c, {}).get("n", 0)
                             for c in NOISY_CATS)
            noisy_gain = 0
            for c in NOISY_CATS:
                rb = base["per_cat"].get(c, {})
                rp = r["per_cat"].get(c, {})
                if rb.get("n"):
                    noisy_gain += (rp.get("exact", 0) - rb.get("exact", 0))
            guard_loss = any(
                r["per_cat"].get(c, {}).get("exact", 0)
                < base["per_cat"].get(c, {}).get("exact", 0)
                or r["per_cat"].get(c, {}).get("fabricated", 0)
                > base["per_cat"].get(c, {}).get("fabricated", 0)
                for c in GUARD_CATS)
            if noisy_gain > 0 and not guard_loss:
                verdict = f"SCOPE — helps noisy lanes only (+{noisy_gain} " \
                          f"exact on {noisy_base} noisy fixtures), " \
                          f"clean/ambiguous lanes unharmed"
            else:
                verdict = "REJECT (noisy gain but clean-lane regression)"
        out.append(
            f"- **{r['variant']}** vs `{base['variant']}` → **{verdict}**\n"
            f"  exact {base['exact']} → {r['exact']}, "
            f"downstream-tok {_fmt(base['ds_tok'])} → net-tok {_fmt(r['net_tok'])}, "
            f"total {_fmt(base['total_ms'])}ms → {_fmt(r['total_ms'])}ms, "
            f"fabricated {base['fab']} → {r['fab']}")
    return out or ["- no polish variants benched yet — run bench.py on a "
                   "polish-* variant plus its direct-* baseline"]


def render(rows, now):
    head = ("| variant | polish | downstream | n | ok | exact% | sim | ent% | "
            "polish ms | total ms | net tok | fab | tool e/p/n/f |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    body = "".join(
        f"| {r['variant']} | {r['polish']} | {r['downstream']} | {r['n']} | "
        f"{r['ok']} | {_fmt(r['exact'])} | {_fmt(r['sim'])} | {_fmt(r['ent'])} | "
        f"{_fmt(r['polish_ms'])} | {_fmt(r['total_ms'])} | {_fmt(r['net_tok'])} | "
        f"{r['fab']} | {r['tally']} |\n"
        for r in rows)
    cats = sorted({c for r in rows for c in r["per_cat"]})
    cat_tbl = ""
    if cats:
        cat_tbl = ("\n## Per-category exact-match (polish-lane scoping signal)\n\n"
                   "| variant | " + " | ".join(cats) + " |\n"
                   "|---|" + "---|" * len(cats) + "\n")
        for r in rows:
            cells = []
            for c in cats:
                pc = r["per_cat"].get(c, {})
                cells.append(f"{pc.get('exact', 0)}/{pc.get('n', 0)}"
                             if pc.get("n") else "—")
            cat_tbl += f"| {r['variant']} | " + " | ".join(cells) + " |\n"
    return (
        "# micro-polish benchmark — latest results\n\n"
        f"Rendered {now} by `scripts/micro-bench/report.py` "
        f"(card `micro-ai-input-polish`).\n\n"
        "Tool column is exact/partial/none/**fabricated** — fabricated = a "
        "tool call emitted where none was expected (invention signal).\n\n"
        + head + body
        + ("\n_No results yet — run `bench.py --variant <id>`._\n"
           if not rows else "")
        + cat_tbl
        + "\n## Adopt gate\n\n"
        + "\n".join(verdicts(rows)) + "\n")


def append_trend(rows):
    TREND.parent.mkdir(parents=True, exist_ok=True)
    if not TREND.exists():
        TREND.write_text(
            "# micro-polish trend\n\n"
            "| at | variant | n | ok | exact% | ent% | total ms | net tok | fab | dry |\n"
            "|---|---|---|---|---|---|---|---|---|---|\n")
    with TREND.open("a") as f:
        for r in rows:
            f.write(f"| {r['at']} | {r['variant']} | {r['n']} | {r['ok']} | "
                    f"{_fmt(r['exact'])} | {_fmt(r['ent'])} | "
                    f"{_fmt(r['total_ms'])} | {_fmt(r['net_tok'])} | "
                    f"{r['fab']} | {'yes' if r['dry'] else 'no'} |\n")


def post_card_comment(card_id, text):
    payload = json.dumps({"id": card_id, "from": "devin",
                          "text": "micro-bench: " + text})
    # payload goes over stdin — the verdict text can contain shell-active
    # chars (backticks around variant ids) that -d would expose to the
    # remote shell
    r = subprocess.run(
        ["ssh", "tony-dell",
         "curl", "-s", "-X", "POST", BOARD_API,
         "-H", "Content-Type: application/json", "-d", "@-"],
        input=payload, capture_output=True, text=True, timeout=20)
    if '"ok": true' not in r.stdout and '"ok":true' not in r.stdout:
        print(f"warn: board-api comment failed: rc={r.returncode} "
              f"{r.stdout[:120]} {r.stderr.strip()}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", help="kanban card id to post the summary to")
    ap.add_argument("--no-trend", action="store_true")
    args = ap.parse_args()

    rows = collect_rows()
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    LATEST.write_text(render(rows, now))
    if rows and not args.no_trend:
        append_trend(rows)
    print(f"wrote {LATEST}" + (" + trend" if rows and not args.no_trend else ""))

    if args.card:
        if rows:
            lines = [f"micro-bench report ({now}): "
                     f"{len(rows)} variant(s) benched"]
            lines.extend(verdicts(rows))
            lines.append("table: reports/micro-polish/LATEST.md")
            post_card_comment(args.card, "\n".join(lines))
        else:
            post_card_comment(args.card,
                              f"micro-bench report ({now}): no results yet.")


if __name__ == "__main__":
    try:
        main()
    except lib.HarnessError as e:
        sys.exit(f"report: {e}")
