#!/usr/bin/env python3
"""nest-01: dense MLP classifies ada ops-event type — pure numpy.

The "control group" experiment: one hidden layer, softmax output, SGD.
No torch/keras — the point is seeing forward/backward pass mechanics.
Temporal split (last 20% by ts = test) because real ops data drifts.

  python3 train.py              → trains, reports, saves model.npz
"""
import collections
import datetime
import json
import sys

import numpy as np

DATA = "ops-events.jsonl"
HIDDEN = 32
EPOCHS = 60
LR = 0.05
TOP_TOOLS = 16
rng = np.random.default_rng(42)


def load():
    rows = [json.loads(l) for l in open(DATA)]
    rows = [r for r in rows if r["type"] != "?" and r["ts"]]
    rows.sort(key=lambda r: r["ts"])

    tools = collections.Counter(r["tool"] for r in rows).most_common(TOP_TOOLS)
    tool_ix = {t: i for i, (t, _) in enumerate(tools)}
    types = sorted(set(r["type"] for r in rows))
    type_ix = {t: i for i, t in enumerate(types)}

    X, Y = [], []
    for r in rows:
        v = np.zeros(TOP_TOOLS + 1 + 2 + 7 + 1)  # tool-oh + hour-sc + dow-oh + len
        if r["tool"] in tool_ix:
            v[tool_ix[r["tool"]]] = 1
        else:
            v[TOP_TOOLS] = 1  # "other tool" bucket
        try:
            dt = datetime.datetime.fromisoformat(r["ts"])
        except ValueError:
            dt = datetime.datetime.utcfromtimestamp(0)
        ang = 2 * np.pi * dt.hour / 24
        v[TOP_TOOLS + 1] = np.sin(ang)
        v[TOP_TOOLS + 2] = np.cos(ang)
        v[TOP_TOOLS + 3 + dt.weekday()] = 1
        v[TOP_TOOLS + 10] = np.log1p(r["content_len"]) / 10
        X.append(v)
        Y.append(type_ix[r["type"]])
    return np.array(X), np.array(Y), types


def softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def main():
    X, y, types = load()
    n, din, dout = len(X), X.shape[1], len(types)
    cut = int(n * 0.8)  # temporal split
    Xtr, Xte, ytr, yte = X[:cut], X[cut:], y[:cut], y[cut:]
    print(f"n={n} din={din} classes={dout} train={len(Xtr)} test={len(Xte)}")
    print("classes:", types)

    W1 = rng.normal(0, 0.1, (din, HIDDEN)); b1 = np.zeros(HIDDEN)
    W2 = rng.normal(0, 0.1, (HIDDEN, dout)); b2 = np.zeros(dout)

    # class weights — inverse frequency, or the net just learns "majority"
    cnt = np.bincount(ytr, minlength=dout).astype(float)
    cw = np.minimum(len(ytr) / (dout * np.maximum(cnt, 1)), 8.0)

    for ep in range(EPOCHS):
        ix = rng.permutation(len(Xtr))
        loss = 0.0
        for i in ix:
            x, t = Xtr[i:i+1], ytr[i]
            h = np.maximum(0, x @ W1 + b1)          # relu hidden
            p = softmax(h @ W2 + b2)                 # softmax out
            loss += cw[t] * -np.log(p[0, t] + 1e-9)
            dz = p.copy(); dz[0, t] -= 1             # dL/dlogits
            dz *= cw[t]                              # weight the gradient
            dW2, db2 = h.T @ dz, dz[0]
            dh = dz @ W2.T; dh[h <= 0] = 0           # relu'
            dW1, db1 = x.T @ dh, dh[0]
            W2 -= LR * dW2; b2 -= LR * db2
            W1 -= LR * dW1; b1 -= LR * db1
        if ep % 15 == 0 or ep == EPOCHS - 1:
            print(f"  epoch {ep:3d} loss={loss/len(Xtr):.4f}")

    pred = np.argmax(softmax(np.maximum(0, Xte @ W1 + b1) @ W2 + b2), axis=1)
    acc = (pred == yte).mean()
    print(f"\ntest accuracy: {acc:.3f} ({(pred == yte).sum()}/{len(yte)})")
    base = collections.Counter(yte).most_common(1)[0][1] / len(yte)
    print(f"baseline (most-frequent): {base:.3f}")

    conf = np.zeros((dout, dout), int)
    for t, p in zip(yte, pred):
        conf[t, p] += 1
    print("\nconfusion (rows=true):")
    hdr = "          " + " ".join(f"{t[:7]:>8}" for t in types)
    print(hdr)
    for i, row in enumerate(conf):
        print(f"{types[i][:8]:>8}  " + " ".join(f"{v:8d}" for v in row))

    np.savez("model.npz", W1=W1, b1=b1, W2=W2, b2=b2,
             classes=np.array(types))
    print("\nsaved model.npz —", f"{(W1.size+W2.size)*8/1024:.0f}KB weights")


if __name__ == "__main__":
    sys.exit(main())
