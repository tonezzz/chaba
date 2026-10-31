#!/usr/bin/env python3
"""board_read_bench.py — manual-baseline vs read-projection benchmark
(card ops-manual-command-api-mcp-efficiency-audit, AUD-1033).

Runs the REAL board-api handler on a loopback ephemeral port against an
identical fixture for both lanes, and measures: response bytes (the
token-cost proxy — chars/4 + 60-char call envelope, same convention as
reports/mcp-files-bench-2026-10-28), median wall time, agent tool calls,
and evidence equality (verifier: does the answer set match the manual
result exactly?).

Scenarios:
  single-card-read    fetch whole board + local filter   vs  GET /card/<id>
  board-index         whole dump, keep slim fields       vs  GET /cards?compact=1
  claim-poll          runner-agent's /cards pull         vs  queued+fields projection
  status-check        whole dump for one status fact     vs  /cards?id&fields
  delta-sync          whole dump to catch changes        vs  /cards?since&fields

Fixture: --cards-json <path> uses a real rendered payload; default is a
deterministic synthetic board seeded to the live distribution measured
2026-10-31 (1136 cards, ~5.27MB, comms/spec as the heavy fields,
~40 queued).

    python3 scripts/board/board_read_bench.py --reps 15
    python3 scripts/board/board_read_bench.py --cards-json /tmp/cards.json --json out.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import string
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from time import perf_counter

REPO = Path(__file__).resolve().parents[2]
CALL_ENVELOPE_CHARS = 60  # per-call JSON-RPC/tool envelope, bench convention


def _load_board_api():
    spec = importlib.util.spec_from_file_location(
        "board_api_bench", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synth_cards(n: int = 1136, seed: int = 1033) -> list:
    """Deterministic board matching the 2026-10-31 live distribution:
    1136 cards / 5.27MB; comms on ~96% (heavy), spec on ~59% (heavy),
    ~40 action.status=queued, one ~170KB monster card."""
    rng = random.Random(seed)
    words = "".join(rng.choice(string.ascii_lowercase + " ")
                    for _ in range(400))
    cols = (["lab"] * 25 + ["backlog"] * 700 + ["doing"] * 60 +
            ["review"] * 60 + ["done"] * 291)
    rng.shuffle(cols)
    statuses = ["queued"] * 40 + ["running"] * 8 + ["claimed"] * 5
    cards = []
    qi = 0
    for i in range(n):
        col = cols[i]
        card = {
            "id": f"bench-card-{i:04d}",
            "title": f"bench card {i} {words[rng.randrange(300):][:60]}",
            "column": col,
            "updated": f"2026-10-{rng.randrange(1, 32):02d} "
                       f"{rng.randrange(0, 24):02d}:{rng.randrange(0, 60):02d}",
            "priority": rng.choice(["high", "medium", "low"]),
            "ref": f"OPS-{1000 + i}",
            "tags": rng.sample(["ops", "devnest", "mcp", "api", "audit"],
                               rng.randrange(1, 4)),
        }
        if rng.random() < 0.96:
            card["comms"] = [
                {"at": card["updated"], "from": rng.choice(
                    ["tony", "devin", "ada", "chaba", "idc02"]),
                 "text": words[rng.randrange(200):][:120]}
                for _ in range(rng.randrange(0, 14))]
        if rng.random() < 0.59:
            card["spec"] = (words + " ") * rng.randrange(2, 8)
        if rng.random() < 0.45:
            card["brief"] = words[rng.randrange(200):][:300]
        if rng.random() < 0.78:
            card["action"] = {"type": "dispatch", "repo": "chaba"}
            if col == "backlog" and qi < len(statuses):
                card["action"]["status"] = statuses[qi]
                qi += 1
            if rng.random() < 0.3:
                card["action"]["labels"] = rng.sample(
                    ["gpu", "idc", "mac", "colab"], rng.randrange(1, 3))
        if rng.random() < 0.06:
            card["blocked_by"] = f"bench-card-{rng.randrange(0, n):04d}"
        cards.append(card)
    # the monster card — live max was 172KB
    cards[0]["comms"] = [{"at": "2026-10-31", "from": "x",
                          "text": words * 5} for _ in range(300)]
    return cards


CLAIM_FIELDS = ("id", "title", "brief", "spec", "action",
                "blocked_by", "priority", "updated", "claim")

def pick_card(cards: list) -> str:
    """A representative read target: mid-size card carrying the heavy
    fields (spec+comms) so the projection delta is honest."""
    heavy = [c for c in cards if c.get("spec") and c.get("comms")]
    pool = heavy or cards
    pool = sorted(pool, key=lambda c: len(json.dumps(c)))
    return pool[len(pool) // 2].get("id") or ""


SCENARIOS = {
    "single-card-read": {
        "manual_path": "/cards",
        "manual_reduce": None,  # bound to picked target at runtime
        "manual_calls": 2,  # fetch + local filter/inspect
        "new_path": None,
        "new_calls": 1,
        "verify": lambda man, new: man == (new or {}).get("card"),
    },
    "board-index": {
        "manual_path": "/cards",
        # server drops absent keys; normalize manual the same way
        "manual_reduce": lambda cards: [
            {k: v for k, v in
             ((k, c.get(k)) for k in
              ("id", "title", "column", "updated", "priority", "ref"))
             if v is not None}
            for c in cards],
        "manual_calls": 2,
        "new_path": "/cards?compact=1",
        "new_calls": 1,
        "verify": lambda man, new: man == (new or {}).get("cards"),
    },
    "claim-poll": {
        "manual_path": "/cards",
        "manual_reduce": lambda cards: [
            c for c in cards
            if (c.get("action") or {}).get("status") == "queued"],
        "manual_calls": 1,
        "new_path": "/cards?action_status=queued&fields=" +
                    ",".join(CLAIM_FIELDS),
        "new_calls": 1,
        # server drops absent keys; normalize manual the same way
        "verify": lambda man, new: [
            {k: v for k, v in
             ((k, c.get(k)) for k in CLAIM_FIELDS) if v is not None}
            for c in man] == (new or {}).get("cards"),
    },
    "status-check": {
        "manual_path": "/cards",
        "manual_reduce": lambda cards: {
            c["id"]: c["column"] for c in cards},
        "manual_calls": 2,
        "new_path": "/cards?fields=id,column",
        "new_calls": 1,
        "verify": lambda man, new: man == {
            c["id"]: c["column"] for c in (new or {}).get("cards", [])},
    },
    "delta-sync": {
        "manual_path": "/cards",
        "manual_reduce": lambda cards: [
            c["id"] for c in cards
            if str(c.get("updated") or "") >= "2026-10-28"],
        "manual_calls": 2,
        "new_path": "/cards?since=2026-10-28&fields=id,updated",
        "new_calls": 1,
        "verify": lambda man, new:
            man == [c["id"] for c in (new or {}).get("cards", [])],
    },
}


def fetch(port: int, path: str) -> tuple:
    url = f"http://127.0.0.1:{port}{path}"
    t0 = perf_counter()
    with urllib.request.urlopen(url, timeout=30) as r:
        body = r.read()
    return body, (perf_counter() - t0) * 1000


def run_scenario(port: int, name: str, sc: dict, reps: int) -> dict:
    # manual lane: fetch the whole payload, reduce client-side
    man_body, _ = fetch(port, sc["manual_path"])
    man_data = json.loads(man_body)
    man_result = sc["manual_reduce"](man_data.get("cards") or [])
    # replacement lane
    new_body, _ = fetch(port, sc["new_path"])
    new_data = json.loads(new_body)
    verified = sc["verify"](man_result, new_data)
    man_ms, new_ms = [], []
    for _ in range(reps):
        _, t = fetch(port, sc["manual_path"])
        man_ms.append(t)
        _, t = fetch(port, sc["new_path"])
        new_ms.append(t)
    man_bytes, new_bytes = len(man_body), len(new_body)
    man_tok = man_bytes / 4 + sc["manual_calls"] * CALL_ENVELOPE_CHARS
    new_tok = new_bytes / 4 + sc["new_calls"] * CALL_ENVELOPE_CHARS
    return {
        "scenario": name,
        "manual": {"path": sc["manual_path"], "bytes": man_bytes,
                   "calls": sc["manual_calls"],
                   "tokens_est": round(man_tok),
                   "median_ms": round(statistics.median(man_ms), 1)},
        "replacement": {"path": sc["new_path"], "bytes": new_bytes,
                        "calls": sc["new_calls"],
                        "tokens_est": round(new_tok),
                        "median_ms": round(statistics.median(new_ms), 1)},
        "delta": {
            "bytes_pct": round(100 * (1 - new_bytes / man_bytes), 2),
            "tokens_pct": round(100 * (1 - new_tok / man_tok), 2),
            "calls": sc["manual_calls"] - sc["new_calls"],
            "median_ms_pct": round(
                100 * (1 - statistics.median(new_ms)
                       / statistics.median(man_ms)), 1)},
        "evidence_equal": verified,
    }


def render_md(results: list, meta: dict) -> str:
    lines = [
        "# board read-projection bench — manual baseline vs replacement",
        "",
        f"- date: {meta['date']}",
        "- card: ops-manual-command-api-mcp-efficiency-audit (AUD-1033)",
        f"- fixture: {meta['fixture_desc']}",
        f"- reps per lane: {meta['reps']} (median ms, loopback HTTP vs "
        "the real board-api handler)",
        "- token estimate: response chars/4 + 60-char call envelope "
        "(mcp-files-bench convention)",
        "",
        "| scenario | manual bytes | new bytes | Δbytes | manual calls | "
        "new calls | Δtok-est | median ms m→n | evidence equal |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m, n, d = r["manual"], r["replacement"], r["delta"]
        lines.append(
            f"| {r['scenario']} | {m['bytes']:,} | {n['bytes']:,} | "
            f"{d['bytes_pct']}% | {m['calls']} | {n['calls']} | "
            f"{d['tokens_pct']}% | {m['median_ms']}→{n['median_ms']} | "
            f"{'yes' if r['evidence_equal'] else 'NO'} |")
    lines += [
        "",
        "Notes: manual-lane token estimates assume the payload reaches "
        "the model context; when agents pre-filter client-side the "
        "wire bytes are unchanged but only call count differs. "
        "Evidence equality = the replacement returns exactly what the "
        "manual reduction produced over the same fixture.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cards-json", help="use a real rendered payload")
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1033)
    ap.add_argument("--json", help="write raw results JSON here")
    ap.add_argument("--md", help="write markdown table here")
    a = ap.parse_args()

    if a.cards_json:
        payload = json.loads(Path(a.cards_json).read_text())
        fixture_desc = (f"real cards.json ({a.cards_json}, "
                        f"{len(payload.get('cards') or [])} cards)")
    else:
        cards = synth_cards(seed=a.seed)
        payload = {"generated": "2026-10-31 08:00", "page_version": 1,
                   "columns": [], "cards": cards}
        fixture_desc = (f"synthetic seeded={a.seed} — live distribution "
                        f"(n={len(cards)})")

    target = pick_card(payload.get("cards") or [])
    SCENARIOS["single-card-read"]["manual_reduce"] = (
        lambda cards, t=target: next(
            c for c in cards if c["id"] == t))
    SCENARIOS["single-card-read"]["new_path"] = (
        "/card/" + urllib.parse.quote(target, safe=""))

    mod = _load_board_api()
    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False) as f:
        f.write(json.dumps(payload))
        fixture_path = Path(f.name)
    saved = mod.CARDS_JSON
    mod.CARDS_JSON = fixture_path
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        results = [run_scenario(port, name, sc, a.reps)
                   for name, sc in SCENARIOS.items()]
    finally:
        srv.shutdown()
        mod.CARDS_JSON = saved
        fixture_path.unlink(missing_ok=True)

    meta = {"date": "2026-10-31", "reps": a.reps,
            "fixture_desc": fixture_desc}
    out = {"meta": meta, "results": results}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    if a.md:
        Path(a.md).write_text(render_md(results, meta))
    print(render_md(results, meta))
    bad = [r["scenario"] for r in results if not r["evidence_equal"]]
    if bad:
        print(f"EVIDENCE MISMATCH: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
