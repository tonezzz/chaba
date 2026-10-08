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
    ap.add_argument("--transcripts", nargs="*", default=[],
                    help="dirs of ada transcript .md files for utterance join")
    args = ap.parse_args()

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
