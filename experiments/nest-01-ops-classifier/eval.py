#!/usr/bin/env python3
"""nest-01 eval — test-set accuracy of model.npz, zero dependencies.

Pure stdlib (zipfile + struct): loads the .npy members out of model.npz,
rebuilds the exact feature pipeline from train.py (temporal 80/20 split),
runs one forward pass, prints test_accuracy.

This is the brain's continuity check (manifest resume.verify): after a
cross-host restore, `python3 eval.py --expect 0.507` proves the hydrated
weights + corpus reproduce the checkpoint bench — no numpy required, so it
runs on bare hosts (mn01) that can't train.

  python3 eval.py                    → prints accuracy, exit 0
  python3 eval.py --expect 0.507     → exit 1 if |acc - expect| > --tol
"""
import argparse
import ast
import collections
import datetime
import json
import math
import struct
import sys
import zipfile

DATA = "ops-events.jsonl"
MODEL = "model.npz"
TOP_TOOLS = 16


def load_npy_member(zf, name):
    raw = zf.read(name)
    assert raw[:6] == b"\x93NUMPY", f"{name}: bad magic"
    major = raw[6]
    if major == 1:
        hlen = struct.unpack("<H", raw[8:10])[0]
        hstart = 10
    else:
        hlen = struct.unpack("<I", raw[8:12])[0]
        hstart = 12
    header = ast.literal_eval(raw[hstart : hstart + hlen].decode("latin1"))
    assert header["descr"] == "<f8", f"{name}: dtype {header['descr']} unsupported"
    assert not header["fortran_order"]
    shape = header["shape"]
    n = 1
    for d in shape:
        n *= d
    flat = list(struct.unpack(f"<{n}d", raw[hstart + hlen : hstart + hlen + 8 * n]))
    return flat, shape


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
        v = [0.0] * (TOP_TOOLS + 1 + 2 + 7 + 1)
        v[tool_ix[r["tool"]] if r["tool"] in tool_ix else TOP_TOOLS] = 1
        try:
            dt = datetime.datetime.fromisoformat(r["ts"])
        except ValueError:
            dt = datetime.datetime.utcfromtimestamp(0)
        ang = 2 * math.pi * dt.hour / 24
        v[TOP_TOOLS + 1] = math.sin(ang)
        v[TOP_TOOLS + 2] = math.cos(ang)
        v[TOP_TOOLS + 3 + dt.weekday()] = 1
        v[TOP_TOOLS + 10] = math.log1p(r["content_len"]) / 10
        X.append(v)
        Y.append(type_ix[r["type"]])
    return X, Y, types


def forward(x, W1, b1, W2, b2, hidden, dout):
    h = [max(0.0, sum(x[k] * W1[k * hidden + j] for k in range(len(x))) + b1[j]) for j in range(hidden)]
    z = [sum(h[j] * W2[j * dout + c] for j in range(hidden)) + b2[c] for c in range(dout)]
    return max(range(dout), key=lambda c: z[c])  # argmax (first max wins)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", type=float, default=None)
    ap.add_argument("--tol", type=float, default=0.03)
    a = ap.parse_args()

    X, y, types = load()
    cut = int(len(X) * 0.8)
    Xte, yte = X[cut:], y[cut:]

    with zipfile.ZipFile(MODEL) as zf:
        W1, s1 = load_npy_member(zf, "W1.npy")
        b1, _ = load_npy_member(zf, "b1.npy")
        W2, s2 = load_npy_member(zf, "W2.npy")
        b2, _ = load_npy_member(zf, "b2.npy")
    din, hidden = s1
    _, dout = s2

    correct = sum(forward(x, W1, b1, W2, b2, hidden, dout) == t for x, t in zip(Xte, yte))
    acc = correct / len(yte)
    print(f"test_accuracy: {acc:.3f} ({correct}/{len(yte)}) classes={dout} host-eval")

    if a.expect is not None:
        diff = abs(acc - a.expect)
        if diff > a.tol:
            print(f"FAIL: |{acc:.3f} - {a.expect}| = {diff:.3f} > tol {a.tol}")
            return 1
        print(f"OK: within {a.tol} of checkpoint score {a.expect}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
