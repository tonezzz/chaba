#!/usr/bin/env python3
"""cards_projection_soak — claim-poll soak for the projected /cards
read (AUD-1033 follow-up, card ops-manual-command-api-mcp-efficiency-
followups).

runner-agent's claim_pass + verdict_pass re-read the whole board every
pass. RUNNER_CARDS_PROJECTION=1 switches exactly those two reads to
GET /cards?fields=<claim set> (board-api card_query projection). This
script is the pre-flip evidence: it polls BOTH endpoints and proves,
poll over poll, that the projection carries every field the claim
surface reads — identical ids, identical values on the shared keys,
action dicts byte-equal — plus the byte savings that motivate it.

Read-only: two GETs per poll, no writes, no claims. Run it on a runner
host (or anywhere with API reachability) before setting
RUNNER_CARDS_PROJECTION=1 in the runner unit env; a clean soak plus
tests/board/test_runner_agent_projection.py is the enablement gate.

Usage:
    python3 scripts/board/cards_projection_soak.py [--api URL]
        [--polls N] [--interval S] [--fields a,b,c]

Exit 0 when every poll is parity-clean, 1 on any mismatch/error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "https://idc03.taila0626a.ts.net:10000"

# Keep in lockstep with runner-agent.CARDS_FIELDS — the claim/verdict
# field set. comms is deliberately absent (lazy /card/<id>?fields=comms
# covers retry_gate's re-arm count).
CARDS_FIELDS = ("id", "title", "column", "updated", "priority", "tags",
                "brief", "spec", "note", "blocked_by", "recoverability",
                "report", "auto_done_when", "requests", "ask", "pipeline",
                "action")
PAGE_LIMIT = 1000  # board-api CARDS_MAX_LIMIT


def _get(api: str, path: str, timeout: int = 60):
    req = urllib.request.Request(api.rstrip("/") + path)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(api: str, path: str, timeout: int = 60):
    return json.loads(_get(api, path, timeout=timeout))


def _full_cards(api: str):
    return (_get_json(api, "/cards") or {}).get("cards") or []


def _projected_cards(api: str, fields) -> list:
    out = []
    off = 0
    while True:
        q = urllib.parse.urlencode(
            {"fields": ",".join(fields), "limit": PAGE_LIMIT,
             "offset": off})
        resp = _get_json(api, f"/cards?{q}")
        page = (resp or {}).get("cards")
        if not isinstance(page, list):
            raise RuntimeError(f"bad page at offset {off}: {resp}")
        out.extend(page)
        if not (resp or {}).get("truncated") or not page:
            return out
        off += len(page)


def _confirm(api: str, cid: str, pc: dict, fields) -> str:
    """A batch mismatch is usually live-board churn — the full dump and
    the projected page are ~1s apart and cards mutate constantly. Fetch
    the card fresh and check the projected twin against ITS projection:
    'churn' when they agree now, 'mismatch' when they still differ."""
    try:
        fresh = (_get_json(api, f"/card/{cid}") or {}).get("card") or {}
    except Exception as e:
        return f"confirm-error: {e}"
    want = set(fields)
    expect = {k: fresh.get(k) for k in want if k in fresh}
    return "ok" if pc == expect else "mismatch"


def _parity(api: str, full: list, proj: list, fields) -> dict:
    """Compare the two card sets the way the claim path consumes them:
    same ids, and every projected card equals the field-projection of
    its full twin (which is exactly what board-api _project emits).
    Value diffs get a fresh /card/<id> confirm so live churn doesn't
    fail the soak — only persistent divergence does."""
    want = set(fields)
    f_by_id = {c.get("id"): c for c in full if isinstance(c, dict)}
    p_by_id = {c.get("id"): c for c in proj if isinstance(c, dict)}
    problems = []
    churn = []
    if set(f_by_id) != set(p_by_id):
        only_f = sorted(set(f_by_id) - set(p_by_id))[:5]
        only_p = sorted(set(p_by_id) - set(f_by_id))[:5]
        problems.append(f"id set differs: full-only={only_f} "
                        f"proj-only={only_p}")
    mismatched = []
    for cid, pc in p_by_id.items():
        fc = f_by_id.get(cid)
        if fc is None:
            continue
        expect = {k: fc.get(k) for k in want if k in fc}
        if pc != expect:
            verdict = _confirm(api, cid, pc, fields)
            (churn if verdict == "ok" else mismatched).append(
                (cid, verdict))
    if mismatched:
        problems.append(f"{len(mismatched)} card(s) still differ after "
                        f"fresh confirm: "
                        f"{[c for c, _ in mismatched[:5]]}")
    return {"ok": not problems, "problems": problems,
            "cards": len(p_by_id),
            "churn": [c for c, _ in churn]}


def soak(api: str, polls: int, interval: float,
         fields=CARDS_FIELDS) -> int:
    bad = 0
    for i in range(max(1, polls)):
        t0 = time.time()
        try:
            full_raw = _get(api, "/cards")
            proj = _projected_cards(api, fields)
            full = json.loads(full_raw).get("cards") or []
        except Exception as e:
            print(json.dumps({"poll": i, "ok": False,
                              "error": f"{type(e).__name__}: {e}"}))
            bad += 1
        else:
            par = _parity(api, full, proj, fields)
            row = {"poll": i, "ok": par["ok"],
                   "full_bytes": len(full_raw),
                   "proj_cards": len(proj),
                   "cards": par["cards"],
                   "wall_s": round(time.time() - t0, 2)}
            if par.get("churn"):
                row["churn_confirmed"] = par["churn"][:5]
            if not par["ok"]:
                row["problems"] = par["problems"]
                bad += 1
            print(json.dumps(row))
        if i + 1 < polls:
            time.sleep(interval)
    print(json.dumps({"done": True, "polls": polls, "bad": bad}))
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--polls", type=int, default=12)
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--fields", default=",".join(CARDS_FIELDS),
                    help="comma-separated projection fields")
    args = ap.parse_args(argv)
    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    return soak(args.api, args.polls, args.interval, fields)


if __name__ == "__main__":
    sys.exit(main())
