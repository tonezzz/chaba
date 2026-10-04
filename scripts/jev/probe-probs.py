#!/usr/bin/env python3
"""Score a labeled jsonl through every candidate backend, dump per-model probs.

  probe-probs.py cases.jsonl --out probs.json \
      --http v5=http://100.74.146.0:8778 \
      --http g1b=http://127.0.0.1:8780 \
      --minilm minilm=minilm-clf \
      --hf g270m=g270m-clf

Output: {"cases":[{text,label,thai,embedded}], "probs":{name:[p,...]}}
All backends must expose a single positive-class probability per text.
"""
import argparse, json, time

import numpy as np


def thai(t):
    return any("฀" <= c <= "๿" for c in t)


def embedded(t):
    tl = t.lower()
    return any(w in tl for w in ("confirm", "ต่อไป", "ยืนยัน", "ok ", " ok"))


CONFIRM_STATE = (
    'Ada, a voice assistant, asked the user to confirm a memory write. '
    'The user turn was: "{turn}"'
)
CONFIRM_Q = {
    "type": "noul",
    "instructions": (
        "Did the user explicitly affirm or confirm? The turn counts as "
        "affirmation only when it is a standalone short affirmation (like "
        "yes, ok, confirm, go ahead, ยืนยัน) or begins with an affirmation. "
        "An approval word embedded inside a longer request does NOT count."),
    "criteria": {
        "true": "the whole turn is a short affirmation, or it leads with one",
        "false": "no affirmation present, or an affirmative word is buried inside a longer request",
    },
}


def http_probs(base, texts, tag):
    import urllib.request
    out, lat = [], []
    for t in texts:
        payload = {"state": CONFIRM_STATE.format(turn=t),
                   "questions": {"q": CONFIRM_Q}}
        req = urllib.request.Request(
            base + "/v1/systemone", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        lat.append(time.time() - t0)
        out.append(float(r["answers"]["q"]["noul"]))
    return np.array(out), {"p50": float(np.median(lat)),
                           "p90": float(np.percentile(lat, 90))}


def minilm_probs(d, texts, tag):
    import torch
    import torch.nn as nn
    from transformers import AutoModel, AutoTokenizer
    z = np.load(f"{d}/head.npz", allow_pickle=True)
    kind = str(z["kind"])
    tok = AutoTokenizer.from_pretrained(f"{d}/encoder")
    model = AutoModel.from_pretrained(f"{d}/encoder").eval()
    H = model.config.hidden_size
    mlp = None
    if kind == "mlp":
        mlp = nn.Sequential(nn.Linear(H, 128), nn.GELU(), nn.Dropout(0.0),
                            nn.Linear(128, 1))
        mlp.load_state_dict({k[4:]: torch.tensor(z[k]) for k in z.files
                             if k.startswith("mlp.")})
        mlp.eval()
    out, lat = [], []
    for s in range(0, len(texts), 64):
        enc = tok(texts[s:s + 64], truncation=True, max_length=96,
                  padding=True, return_tensors="pt")
        t0 = time.time()
        with torch.no_grad():
            h = model(**enc).last_hidden_state
        m = enc["attention_mask"][..., None].float()
        emb = (h * m).sum(1) / m.sum(1)
        if mlp is not None:
            with torch.no_grad():
                p = torch.sigmoid(mlp(emb.float()))[:, 0]
        else:
            x = emb.float().numpy()
            p = torch.tensor(1 / (1 + np.exp(-(x @ z["W"].T + z["b"])))[:, 0])
        lat.append((time.time() - t0) / len(enc["input_ids"]))
        out.append(p.numpy())
    lat = lat[1:] or lat  # drop warm-up batch
    return np.concatenate(out), {"p50": float(np.median(lat)),
                                 "p90": float(np.percentile(lat, 90))}


def hf_probs(d, texts, tag):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(d)
    model = AutoModelForSequenceClassification.from_pretrained(
        d, dtype=torch.float32).eval()
    out, lat = [], []
    for s in range(0, len(texts), 32):
        enc = tok(texts[s:s + 32], truncation=True, max_length=96,
                  padding=True, return_tensors="pt")
        t0 = time.time()
        with torch.no_grad():
            lg = model(**enc).logits.float()
        out.append(torch.softmax(lg, -1)[:, 1].numpy())
        lat.append((time.time() - t0) / len(enc["input_ids"]))
    return np.concatenate(out), {"p50": float(np.median(lat)),
                                 "p90": float(np.percentile(lat, 90))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--out", required=True)
    ap.add_argument("--http", action="append", default=[],
                    help="name=base-url (serves /v1/systemone)")
    ap.add_argument("--minilm", action="append", default=[],
                    help="name=minilm-clf dir")
    ap.add_argument("--hf", action="append", default=[],
                    help="name=hf seq-cls dir")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.cases) if l.strip()]
    texts = [r["text"] for r in rows]
    probs, meta = {}, {}
    for spec in args.http:
        name, base = spec.split("=", 1)
        probs[name], meta[name] = http_probs(base.rstrip("/"), texts, name)
        print(f"  {name}: p50={meta[name]['p50']*1e3:.0f}ms")
    for spec in args.minilm:
        name, d = spec.split("=", 1)
        probs[name], meta[name] = minilm_probs(d, texts, name)
        print(f"  {name}: p50={meta[name]['p50']*1e3:.0f}ms")
    for spec in args.hf:
        name, d = spec.split("=", 1)
        probs[name], meta[name] = hf_probs(d, texts, name)
        print(f"  {name}: p50={meta[name]['p50']*1e3:.0f}ms")

    json.dump({
        "cases": [{"text": r["text"], "label": bool(r["label"]),
                   "thai": thai(r["text"]), "embedded": embedded(r["text"])}
                  for r in rows],
        "probs": {k: [float(x) for x in v] for k, v in probs.items()},
        "latency": meta,
    }, open(args.out, "w"), ensure_ascii=False, indent=1)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
