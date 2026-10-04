#!/usr/bin/env python3
"""Simulate cascade/ensemble structures over recorded per-model probs.

  cascade-sim.py probs.json --config structures.json

Structure config (list):
  {"name": "v5-only", "type": "serial",
   "members": [{"model": "v5", "hi": 0.75, "lo": 0.25}]}
  # serial: member decides POS if p>=hi, NEG if p<=lo, else escalate.
  #         last member always decides at (hi+lo)/2 default threshold.
  {"name": "vote3", "type": "vote",
   "members": [{"model": "v5", "thr": 0.7, "w": 2.0},
               {"model": "minilm", "thr": 0.65, "w": 1.0}]}
  # vote: weighted majority of per-model binary decisions.
  {"name": "veto", "type": "veto",
   "members": [{"model": "v5", "thr": 0.7},
               {"model": "g1b", "thr": 0.5, "veto_below": true}]}
  # veto: base member decides; each veto member can flip POS->NEG when
  #       its own p < thr (fires only when base says POS).

Expected latency = sum of member p50 * fraction of cases reaching it.
"""
import argparse, json

import numpy as np


def metrics(cases, pred):
    y = np.array([c["label"] for c in cases])
    pred = np.array(pred)
    def acc(m):
        m = np.array(m)
        return round(float((pred[m] == y[m]).mean()), 4) if m.any() else None
    tp = int((pred & y).sum()); fp = int((pred & ~y).sum())
    fn = int((~pred & y).sum())
    return {
        "acc": acc(np.ones(len(y), bool)),
        "acc_pos": acc(y), "acc_neg": acc(~y),
        "acc_thai": acc([c["thai"] for c in cases]),
        "acc_emb": acc([c["embedded"] for c in cases]),
        "prec": round(tp / max(1, tp + fp), 3),
        "rec": round(tp / max(1, tp + fn), 3),
        "f1": round(2 * tp / max(1, 2 * tp + fp + fn), 3),
    }


def run_serial(cases, P, lat, members):
    n = len(cases)
    pred = np.zeros(n, bool); reached = {m["model"]: np.zeros(n, bool)
                                         for m in members}
    undecided = np.ones(n, bool)
    for i, m in enumerate(members):
        p = np.array(P[m["model"]])
        last = i == len(members) - 1
        thr = m.get("thr", (m.get("hi", .75) + m.get("lo", .25)) / 2)
        if last:
            pred[undecided] = p[undecided] >= thr
            reached[m["model"]] |= undecided
            undecided[:] = False
        else:
            pos = undecided & (p >= m["hi"])
            neg = undecided & (p <= m["lo"])
            pred[pos] = True; pred[neg] = False
            reached[m["model"]] |= undecided
            undecided &= ~(pos | neg)
    exp_lat = sum(lat.get(m["model"], {}).get("p50", 0) *
                  reached[m["model"]].mean() for m in members)
    return pred, exp_lat


def run_vote(cases, P, lat, members):
    n = len(cases)
    votes = np.zeros(n); tot = sum(m.get("w", 1) for m in members)
    for m in members:
        votes += (np.array(P[m["model"]]) >= m["thr"]) * m.get("w", 1)
    pred = votes >= tot / 2
    exp_lat = max(lat.get(m["model"], {}).get("p50", 0) for m in members)
    return pred, exp_lat


def run_veto(cases, P, lat, members):
    base = members[0]
    pred = np.array(P[base["model"]]) >= base["thr"]
    exp_lat = lat.get(base["model"], {}).get("p50", 0)
    for m in members[1:]:
        fire = pred & (np.array(P[m["model"]]) < m["thr"])
        pred[fire] = False
        # veto member only consulted when base says POS
        exp_lat += lat.get(m["model"], {}).get("p50", 0) * float(
            (np.array(P[base["model"]]) >= base["thr"]).mean())
    return pred, exp_lat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("probs")
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    D = json.load(open(args.probs))
    cases, P, lat = D["cases"], D["probs"], D.get("latency", {})
    structs = json.load(open(args.config))
    out = []
    for s in structs:
        fn = {"serial": run_serial, "vote": run_vote,
              "veto": run_veto}[s["type"]]
        pred, exp_lat = fn(cases, P, lat, s["members"])
        r = {"name": s["name"], "type": s["type"],
             "exp_lat_ms": round(exp_lat * 1e3, 1), **metrics(cases, pred)}
        out.append(r)
        print(json.dumps(r))
    json.dump(out, open(args.probs.replace(".json", "-sim.json"), "w"),
              indent=1)


if __name__ == "__main__":
    main()
