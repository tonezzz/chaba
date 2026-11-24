#!/usr/bin/env python3
"""code-decision-eval — bench Jev choice/gates vs human-verified verdicts
(OPS-0825 phase 2).

Corpus: scripts/jev/code-decision-corpus.jsonl — repo-grounded cases with
human verdicts (verdict_source: repo-convention | commit:<sha> |
hand-labeled). Two kinds:

  kind=choice — {task, code, constraints, candidates, expected}
                scores whether backend Choice picks the human verdict
  kind=gate   — same + winner + gate + expected(bool)
                scores whether the named Noul gate matches the label
                (gates are asked for the HUMAN winner, isolating gate
                quality from choice quality)

Backends (each scored independently — comparison is the point):
  jev-api    $JEV_API_URL+$JEV_API_KEY  (real Jev, both heads) — skipped w/o key
  jevos      $JEVOS_URL                 (choice-capable local, :8017)
  jev-student $JEV_STUDENT_URL          (noul-only; choice stub detected)

Flags:
  --corpus-only   validate corpus, no backend calls (exit 1 on malformed)
  --backend NAME  run only one backend (jev-api|jevos|jev-student)
  --out PATH      per-case records JSONL
  --limit N       first N cases only (smoke)
"""
import argparse, json, os, sys, time, urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
_cd = SourceFileLoader("code_decision", str(HERE / "code-decision.py")).load_module()

CORPUS = HERE / "code-decision-corpus.jsonl"
JEV_API_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai")
JEV_API_KEY = os.environ.get("JEV_API_KEY", "")
JEVOS_URL = os.environ.get("JEVOS_URL", "http://127.0.0.1:8017")
STUDENT_URL = os.environ.get("JEV_STUDENT_URL", "http://100.75.102.88:8780")
NOUL_THR = float(os.environ.get("JEV_NOUL_THR", "0.5"))
COST_PER_MTOK = 0.042   # real Jev API list price (design doc)


def load_corpus(path=CORPUS):
    cases = []
    for i, line in enumerate(open(path)):
        line = line.strip()
        if line:
            c = json.loads(line)
            c["_line"] = i + 1
            cases.append(c)
    return cases


def corpus_report(cases):
    """--corpus-only verifier: schema + label sanity."""
    errs, fams, kinds = [], {}, {}
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        errs.append("duplicate case ids")
    for c in cases:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        fams[c.get("family", "?")] = fams.get(c.get("family", "?"), 0) + 1
        for k in ("id", "kind", "task", "code", "candidates", "expected"):
            if k not in c:
                errs.append("%s:%d missing %s" % (c.get("id", "?"), c["_line"], k))
        if not c.get("candidates"):
            errs.append("%s: empty candidates" % c["id"])
        if c["kind"] == "choice":
            if c["expected"] not in c["candidates"]:
                errs.append("%s: expected %r not in candidates"
                            % (c["id"], c["expected"]))
        elif c["kind"] == "gate":
            if c.get("winner") not in c["candidates"]:
                errs.append("%s: winner %r not in candidates"
                            % (c["id"], c.get("winner")))
            if c.get("gate") not in _cd.GATE_QS:
                errs.append("%s: bad gate %r" % (c["id"], c.get("gate")))
            if not isinstance(c.get("expected"), bool):
                errs.append("%s: gate expected must be bool" % c["id"])
        else:
            errs.append("%s: unknown kind %r" % (c["id"], c["kind"]))
    return {"total": len(cases), "kinds": kinds, "families": fams,
            "errors": errs}


def _ctx(case):
    return {"task": case["task"], "code": case["code"],
            "candidates": case["candidates"],
            "constraints": case.get("constraints") or []}


def _post(base, state, questions, api_key="", timeout=60):
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(base.rstrip("/") + "/v1/systemone",
                                 data=json.dumps(payload).encode(),
                                 headers=headers)
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return r.get("answers", {}), round((time.time() - t0) * 1000), None
    except Exception as e:
        return {}, round((time.time() - t0) * 1000), str(e)[:120]


def _healthy(base, timeout=6):
    try:
        urllib.request.urlopen(base.rstrip("/") + "/health", timeout=timeout)
        return True
    except Exception:
        return False


def backends(only=None):
    """name -> (base, api_key, roles) for reachable backends."""
    out = {}
    if (only in (None, "jev-api")) and JEV_API_KEY:
        out["jev-api"] = (JEV_API_URL, JEV_API_KEY, ("choice", "noul"))
    elif only == "jev-api":
        print("jev-api requested but JEV_API_KEY unset — skipped")
    if only in (None, "jevos"):
        out["jevos"] = (JEVOS_URL, "", ("choice", "noul"))
    if only in (None, "jev-student"):
        out["jev-student"] = (STUDENT_URL, "", ("choice", "noul"))
    # reachability filter (skip dead backends fast)
    live = {}
    for name, (base, key, roles) in out.items():
        if _healthy(base):
            live[name] = (base, key, roles)
        else:
            print("%-12s down (%s) — skipped" % (name, base))
    return live


def eval_choice(case, base, key):
    ctx = _ctx(case)
    state = _cd._state(ctx, {"candidates": {k: str(v)[:500]
                                            for k, v in case["candidates"].items()}})
    q = {_cd.CHOICE_Q: _cd.build_choice_question(case["candidates"])}
    answers, ms, err = _post(base, state, q, api_key=key)
    a = answers.get(_cd.CHOICE_Q) or {}
    stub = _cd._is_choice_stub(a)
    got = a.get("choice")
    return {"got": got, "ok": (got == case["expected"] and not stub),
            "stub": stub, "ms": ms, "err": err,
            "confidence": a.get("confidence"), "raw": a}


def eval_gate(case, base, key):
    ctx = _ctx(case)
    gqs = _cd.build_gate_questions(ctx, case["winner"])
    state = _cd._state(ctx)
    answers, ms, err = _post(base, state, gqs, api_key=key)
    rec = {"ms": ms, "err": err, "gates": {}, "ok": False}
    ps = []
    for g in _cd.GATE_QS:
        a = answers.get(g) or {}
        p = a.get("noul")
        rec["gates"][g] = p
        if isinstance(p, (int, float)):
            ps.append(p)
    tgt = case["gate"]
    p = rec["gates"].get(tgt)
    if isinstance(p, (int, float)):
        rec["ok"] = ((p >= NOUL_THR) == case["expected"])
        rec["p"] = p
    # collapse detector (same rule as the door)
    rec["ood_suspect"] = (len(ps) == len(_cd.GATE_QS)
                          and max(ps) - min(ps) < 0.01 and max(ps) < 0.1)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--corpus-only", action="store_true")
    ap.add_argument("--backend", choices=["jev-api", "jevos", "jev-student"])
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    cases = load_corpus(args.corpus)
    if args.limit:
        cases = cases[:args.limit]
    if args.corpus_only:
        rep = corpus_report(cases)
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 1 if rep["errors"] else 0

    bks = backends(args.backend)
    if not bks:
        print("no live backends — nothing to score")
        return 1

    records = []
    results = {name: {"choice": [0, 0], "gate": [0, 0], "ms": []}
               for name in bks}
    fam_res = {}
    for case in cases:
        for name, (base, key, roles) in bks.items():
            if case["kind"] == "choice" and "choice" in roles:
                r = eval_choice(case, base, key)
                results[name]["choice"][1] += 1
                results[name]["choice"][0] += 1 if r["ok"] else 0
                results[name]["ms"].append(r["ms"])
                fam_res.setdefault((name, case.get("family", "?")), [0, 0])
                fam_res[(name, case["family"])][1] += 1
                fam_res[(name, case["family"])][0] += 1 if r["ok"] else 0
                records.append({"backend": name, "id": case["id"],
                                "kind": "choice", "expected": case["expected"],
                                "got": r["got"], "ok": r["ok"], "stub": r["stub"],
                                "ms": r["ms"], "err": r["err"],
                                "confidence": r.get("confidence")})
            elif case["kind"] == "gate" and "noul" in roles:
                r = eval_gate(case, base, key)
                results[name]["gate"][1] += 1
                results[name]["gate"][0] += 1 if r["ok"] else 0
                results[name]["ms"].append(r["ms"])
                fam_res.setdefault((name, "gate-" + case["gate"]), [0, 0])
                fam_res[(name, "gate-" + case["gate"])][1] += 1
                fam_res[(name, "gate-" + case["gate"])][0] += 1 if r["ok"] else 0
                records.append({"backend": name, "id": case["id"],
                                "kind": "gate", "gate": case["gate"],
                                "expected": case["expected"], "p": r.get("p"),
                                "ok": r["ok"], "ood_suspect": r["ood_suspect"],
                                "ms": r["ms"], "err": r["err"]})

    import statistics
    print("\n== code-decision-eval (%d cases) ==" % len(cases))
    print("%-12s %8s %8s %8s %10s" % ("backend", "choice", "gate", "n", "lat_p50"))
    summary = {}
    for name in bks:
        ch, gt = results[name]["choice"], results[name]["gate"]
        n = ch[1] + gt[1]
        lat = results[name]["ms"]
        p50 = round(statistics.median(lat), 1) if lat else 0
        acc_parts = []
        if ch[1]:
            acc_parts.append("choice %d/%d" % (ch[0], ch[1]))
        if gt[1]:
            acc_parts.append("gate %d/%d" % (gt[0], gt[1]))
        print("%-12s %8s %8s %8d %10.1f" % (name, ch[0] if ch[1] else "-",
              gt[0] if gt[1] else "-", n, p50))
        print("%-12s   %s" % ("", " | ".join(acc_parts)))
        summary[name] = {"choice": {"correct": ch[0], "total": ch[1]},
                         "gate": {"correct": gt[0], "total": gt[1]},
                         "lat_p50_ms": p50}
    # per-family table
    print("\nper-family accuracy:")
    for (name, fam), (ok, tot) in sorted(fam_res.items()):
        print("  %-12s %-16s %d/%d" % (name, fam, ok, tot))

    # rough cost estimate for the jev-api arm (chars/4 ~ tokens)
    if "jev-api" in bks:
        chars = sum(len(json.dumps(_ctx(c))) for c in cases) * 2
        est = chars / 4 / 1e6 * COST_PER_MTOK
        print("\njev-api est. cost this run: ~$%.4f (%d cases, ~%d tok in)"
              % (est, len(cases), chars // 4))

    out = {"corpus": str(args.corpus), "cases": len(cases),
           "noul_threshold": NOUL_THR, "backends": summary,
           "per_family": {"%s|%s" % k: {"correct": v[0], "total": v[1]}
                          for k, v in fam_res.items()}}
    if args.out:
        sum_path = args.out + ".summary.json"
        with open(sum_path, "w") as f:
            json.dump(out, f, indent=1)
        print("wrote summary:", sum_path)
        with open(args.out, "w") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("wrote per-case records:", args.out)
    else:
        out_path = os.path.expanduser("~/.cache/code-decision-eval.json")
        json.dump(out, open(out_path, "w"), indent=1)
        print("wrote", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
