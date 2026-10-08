#!/usr/bin/env python3
"""bank-router-mine.py — mine ada_memory_search calls from ada-pi journals.

Pairs `function_call received` / `function_call result` lines for
ada_memory_search and emits one JSONL corpus row per completed call:

  {ts, session, latency_s, query, bank_arg, scope,
   hit_banks: [...], top_bank, top_score, hit_count}

Labels for the bank-router suite:
  query     — the model's search text (before "Conversation context:")
  utterance — the User: line inside Conversation context when present
  top_bank  — bank of the highest-scoring hit = the bank a router
              should have picked (free label from production)
  bank_arg  — the bank argument the model passed ('all' = fan-out)

Run over an SSH journal export or a local file:

  ssh idc03 'journalctl --user -u ada-ha-tony --since "-7 days" --no-pager' \
    | python3 scripts/ada/bank-router-mine.py \
        --corpus /tmp/bankq-corpus.jsonl --stats
"""
import argparse
import ast
import json
import os
import re
import statistics
import sys
from datetime import datetime

TS = r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
RE_RECV = re.compile(
    r".*" + TS + r".*function_call received id=(?P<cid>\S+) "
    r"name=ada_memory_search args=(?P<args>\{.*)$")
RE_RES = re.compile(
    r".*" + TS + r".*function_call result id=(?P<cid>\S+) "
    r"name=ada_memory_search result=(?P<res>\{.*)$")
RE_SESS = re.compile(r"session=(?P<sid>\w+)")
RE_CTX = re.compile(r"Conversation context:\s*\n?User:\s*(?P<u>.+)$", re.S)
# "INFO tools: tool ada_memory_search args={...}" — a second log of the same
# call whose query text carries 'Conversation context: User: <utterance>'.
RE_TOOL = re.compile(
    r".*" + TS + r".*tools: tool ada_memory_search args=(?P<args>\{.*)$")


RE_BANK_TIMING = re.compile(
    r".*" + TS + r".*memory_search timing bank=(?P<bank>\S+) "
    r"banks=(?P<nb>\d+) total_ms=(?P<tot>[\d.]+) "
    r"per_bank_ms=(?P<pbm>\{.*?\}) hits=(?P<hits>\d+) "
    r"top_bank=(?P<top>\S+) degraded=(?P<deg>\S+)")
RE_TOOL_TIMING = re.compile(
    r".*" + TS + r".*memory_search tool timing scope=(?P<scope>\S+) "
    r"bank=(?P<bank>\S+) total_ms=(?P<tot>\d+) banks_ms=(?P<bms>-?\d+) "
    r"sessions_ms=(?P<sms>-?\d+) guest_ms=(?P<gms>-?\d+) "
    r"hits_pre_cap=(?P<hits>\d+)")
RE_VERDICT = re.compile(
    r".*" + TS + r".*memory_search router verdict mode=(?P<mode>\S+) "
    r"predicted=(?P<pred>\S+) conf=(?P<conf>[\d.]+) set=(?P<set>\S+) "
    r"actual_top=(?P<top>\S+) hits=(?P<hits>\d+) "
    r"captured=(?P<cap>\S+) skip_regret=(?P<reg>\S+) "
    r"router_ms=(?P<rms>-?\d+)")


def telemetry_rows(lines):
    """Parse the Phase-0/Phase-3 instrumented lines (deployed
    2026-10-08, commits d74675c + bankq-student branch):
      'memory_search timing'        — per-bank wall split (memory_ops)
      'memory_search tool timing'   — per-scope wall split (tool layer)
      'memory_search router verdict'— shadow router vs actual outcome
    Yields dicts with kind: bank_timing|tool_timing|verdict."""
    for line in lines:
        if "memory_search" not in line:
            continue
        m = RE_VERDICT.match(line)
        if m:
            yield {
                "kind": "verdict", "ts": m.group("ts"),
                "mode": m.group("mode"), "predicted": m.group("pred"),
                "confidence": float(m.group("conf")),
                "bank_set": [] if m.group("set") == "-"
                else m.group("set").split(","),
                "actual_top": None if m.group("top") == "None"
                else m.group("top"),
                "hits": int(m.group("hits")),
                "captured": m.group("cap") == "True",
                "skip_regret": m.group("reg") == "True",
                "router_ms": int(m.group("rms")),
            }
            continue
        m = RE_BANK_TIMING.match(line)
        if m:
            yield {
                "kind": "bank_timing", "ts": m.group("ts"),
                "bank_arg": m.group("bank"), "n_banks": int(m.group("nb")),
                "total_ms": float(m.group("tot")),
                "per_bank_ms": json.loads(m.group("pbm")),
                "hits": int(m.group("hits")),
                "top_bank": None if m.group("top") == "None"
                else m.group("top"),
                "degraded": m.group("deg") == "True",
            }
            continue
        m = RE_TOOL_TIMING.match(line)
        if m:
            yield {
                "kind": "tool_timing", "ts": m.group("ts"),
                "scope": m.group("scope"), "bank_arg": m.group("bank"),
                "total_ms": int(m.group("tot")),
                "banks_ms": int(m.group("bms")),
                "sessions_ms": int(m.group("sms")),
                "guest_ms": int(m.group("gms")),
                "hits": int(m.group("hits")),
            }


def _pct(vals, x):
    vals = sorted(vals)
    return vals[min(int(len(vals) * x), len(vals) - 1)] if vals \
        else float("nan")


def telemetry_stats(data: list[dict]) -> None:
    bt = [r for r in data if r["kind"] == "bank_timing"]
    tt = [r for r in data if r["kind"] == "tool_timing"]
    vd = [r for r in data if r["kind"] == "verdict"]
    e = sys.stderr
    print(f"\ntelemetry: bank_timing={len(bt)} tool_timing={len(tt)} "
          f"verdicts={len(vd)}", file=e)
    for name, rows_ in (("bank_timing", bt), ("tool_timing", tt)):
        tot = [r["total_ms"] for r in rows_]
        print(f"{name}: total_ms p50={_pct(tot,.5):.0f} "
              f"p90={_pct(tot,.9):.0f} p95={_pct(tot,.95):.0f} "
              f"p99={_pct(tot,.99):.0f}", file=e)
    if bt:
        # Per-bank ms that saturates near total_ms means the wall is the
        # remote embed inside mddb (parallel calls share the proxy).
        sat = [r for r in bt if r["per_bank_ms"] and
               max(r["per_bank_ms"].values()) >= 0.8 * r["total_ms"]]
        print(f"bank_timing: {len(sat)}/{len(bt)} calls have a bank "
              f"within 20% of total_ms (embed-bound marker)", file=e)
        all_b = [r for r in bt if r["n_banks"] > 1]
        one_b = [r for r in bt if r["n_banks"] == 1]
        print(f"fan-out p50={_pct([r['total_ms'] for r in all_b],.5):.0f} "
              f"vs single-bank p50="
              f"{_pct([r['total_ms'] for r in one_b],.5):.0f}", file=e)
    if tt:
        banks = [r["banks_ms"] for r in tt if r["banks_ms"] >= 0]
        sess = [r["sessions_ms"] for r in tt if r["sessions_ms"] >= 0]
        print(f"tool_timing split p50: banks={_pct(banks,.5):.0f} "
              f"sessions={_pct(sess,.5):.0f}", file=e)
    if vd:
        routed = [r for r in vd if r["predicted"] != "skip"]
        cap = sum(r["captured"] for r in routed)
        regret = sum(r["skip_regret"] for r in vd)
        n_sk = sum(1 for r in vd if r["predicted"] == "skip")
        print(f"verdicts: routed={len(routed)} captured={cap} "
              f"({cap/max(1,len(routed)):.0%}) skip={n_sk} "
              f"skip_regret={regret}", file=e)


def _parse_ts(s: str) -> datetime:
    # ada-pi log timestamp inside the journal line: "2026-10-06 10:00:06,779"
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S,%f")


def _literal(text: str):
    """Parse the python-dict-shaped payload; tolerate trailing log junk."""
    text = text.strip()
    depth, end = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return ast.literal_eval(text[:end] if end else text)
    except Exception:
        return None


def _split_query(q: str) -> tuple[str, str | None]:
    """Strip 'Conversation context:' — returns (query, utterance|None)."""
    ctx = RE_CTX.search(q)
    if not ctx:
        return q.strip(), None
    return q[: ctx.start()].strip(), ctx.group("u").strip()[:400]


def rows(lines):
    pending: dict[str, dict] = {}
    tool_q: list[tuple[datetime, str, str | None]] = []  # (ts, query, utter)
    emitted: list[dict] = []
    for line in lines:
        if "ada_memory_search" not in line:
            continue
        m = RE_TOOL.match(line)
        if m:
            args = _literal(m.group("args")) or {}
            q, utter = _split_query(str(args.get("query") or ""))
            tool_q.append((_parse_ts(m.group("ts")), q, utter))
            continue
        m = RE_RECV.match(line)
        if m:
            sid = RE_SESS.search(line)
            pending[m.group("cid")] = {
                "ts": m.group("ts").strip(),
                "t0": _parse_ts(m.group("ts")),
                "session": sid.group("sid") if sid else None,
                "args": _literal(m.group("args")) or {},
            }
            continue
        m = RE_RES.match(line)
        if m and m.group("cid") in pending:
            rec = pending.pop(m.group("cid"))
            res = _literal(m.group("res")) or {}
            out = res.get("output") or res
            hits = out.get("hits") or []
            banks = [h.get("bank") for h in hits if h.get("bank")]
            top = hits[0] if hits else {}
            q, utter = _split_query(str(rec["args"].get("query") or ""))
            t1 = _parse_ts(m.group("ts"))
            emitted.append({
                "ts": rec["ts"],
                "session": rec["session"],
                "latency_s": round((t1 - rec["t0"]).total_seconds(), 3),
                "query": q,
                "utterance": utter,
                "bank_arg": rec["args"].get("bank", "all"),
                "scope": out.get("scope"),
                "hit_count": out.get("count", len(hits)),
                "hit_banks": banks,
                "top_bank": top.get("bank"),
                "top_score": top.get("score"),
                "degraded": out.get("degraded"),
            })
    # Fill utterance from the tools-args line nearest in time (in-call-order).
    qi = 0
    for r in emitted:
        if r["utterance"]:
            continue
        t0 = _parse_ts(r["ts"])
        while qi < len(tool_q) and tool_q[qi][0] < t0:
            qi += 1
        # nearest tools-line within 3s, prefer same query text
        best = None
        for j in range(max(0, qi - 2), min(len(tool_q), qi + 2)):
            if abs((tool_q[j][0] - t0).total_seconds()) <= 3:
                if best is None or tool_q[j][1] == r["query"]:
                    best = tool_q[j]
                    if tool_q[j][1] == r["query"]:
                        break
        if best and best[2]:
            r["utterance"] = best[2]
    yield from emitted


RE_TURN = re.compile(r"^## (User|Ada) \[(\d{2}):(\d{2}):(\d{2})\]\s*$")


def load_transcripts(dirs: list[str]) -> dict[str, list[tuple[int, str]]]:
    """session -> [(seconds-into-day, utterance)] user turns, in order."""
    import glob
    out: dict[str, list[tuple[int, str]]] = {}
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.md")):
            sid = os.path.basename(path).rsplit("-", 1)[-1].removesuffix(".md")
            turns: list[tuple[int, str]] = []
            cur_t, who, buf = None, None, []
            for line in open(path, encoding="utf-8", errors="replace"):
                m = RE_TURN.match(line.strip())
                if m:
                    if who == "User" and buf:
                        turns.append((cur_t, " ".join(buf).strip()))
                    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4))
                    cur_t, who, buf = h * 3600 + mi * 60 + s, m.group(1), []
                elif who and line.strip() and not line.startswith(("#", "<!--")):
                    buf.append(line.strip())
            if who == "User" and buf:
                turns.append((cur_t, " ".join(buf).strip()))
            if turns:
                out.setdefault(sid, []).extend(turns)
    for v in out.values():
        v.sort()
    return out


def attach_utterances(data: list[dict], sessions) -> int:
    """Fill r['utterance'] from the last User turn before the call."""
    import bisect
    n = 0
    for r in data:
        turns = sessions.get(r["session"])
        if not turns or r["utterance"]:
            continue
        t = _parse_ts(r["ts"])
        sec = t.hour * 3600 + t.minute * 60 + t.second
        times = [x[0] for x in turns]
        i = bisect.bisect_right(times, sec + 1) - 1
        if i >= 0:
            r["utterance"] = turns[i][1][:400]
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", help="write JSONL corpus rows here")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--telemetry", action="store_true",
                    help="ingest 'memory_search timing/tool timing/"
                         "router verdict' lines instead of "
                         "function_call pairing")
    ap.add_argument("--transcripts", nargs="*", default=[],
                    help="dirs of ada transcript .md files for utterance join")
    args = ap.parse_args()

    if args.telemetry:
        data = list(telemetry_rows(sys.stdin))
        f = open(args.corpus, "w") if args.corpus else sys.stdout
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if args.corpus:
            f.close()
        if args.stats or True:
            telemetry_stats(data)
        return

    data = list(rows(sys.stdin))
    if args.transcripts:
        n = attach_utterances(data, load_transcripts(args.transcripts))
        print(f"utterances attached: {n}/{len(data)}", file=sys.stderr)
    f = open(args.corpus, "w") if args.corpus else sys.stdout
    for r in data:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if args.corpus:
        f.close()

    if args.stats:
        lat = sorted(r["latency_s"] for r in data)
        n = len(lat)
        def p(x):
            return lat[min(int(n * x), n - 1)] if n else float("nan")
        from collections import Counter
        tops = Counter(r["top_bank"] for r in data)
        barg = Counter(str(r["bank_arg"]) for r in data)
        print(f"\ncalls={n}  window={data[0]['ts'][:19]}..{data[-1]['ts'][:19]}"
              if n else "\ncalls=0", file=sys.stderr)
        print(f"latency_s p50={p(.5):.3f} p90={p(.9):.3f} "
              f"p95={p(.95):.3f} p99={p(.99):.3f} mean={statistics.mean(lat) if n else 0:.3f}",
              file=sys.stderr)
        print("bank_arg:", dict(barg.most_common(10)), file=sys.stderr)
        print("top_bank:", dict(tops.most_common(15)), file=sys.stderr)


if __name__ == "__main__":
    main()
