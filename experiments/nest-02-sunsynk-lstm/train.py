#!/usr/bin/env python3
"""nest-02: LSTM on sunsynk hourly series — pure numpy, gates visible.

Task: last 24h of [pv, load, soc, grid] -> next-hour PV power (W).
The cell IS the lesson:
    f = sigmoid(W_f z)    forget gate  — what to erase from memory
    i = sigmoid(W_i z)    input gate   — what new info to accept
    g = tanh(W_g z)       candidate    — the new info itself
    o = sigmoid(W_o z)    output gate  — what to expose
    c = f*c + i*g         cell state   — the conveyor belt that survives
    h = o*tanh(c)         hidden       — what the world sees
(z = [x_t, h_{t-1}] concatenated)

Dense/nest-01 couldn't do this: order isn't a feature, it's the substrate.
Baselines: persistence (t-1) and seasonal-naive (same hour yesterday).

  python3 train.py [--epochs 30]
"""
import json
import sys

import numpy as np

rng = np.random.default_rng(7)
DATA = "sunsynk-hourly.json"
CH = ["sensor.solis_s6_eh3p10k_h_zp_total_pv_power",
      "sensor.solis_s6_eh3p10k_h_zp_household_load_power",
      "sensor.solis_s6_eh3p10k_h_zp_battery_soc",
      "sensor.solis_s6_eh3p10k_h_zp_meter_active_power"]
WINDOW = 24       # hours of context
HID = 24          # hidden units — micro scale on purpose
EPOCHS = 30
LR = 0.01
CLIP = 5.0


def sig(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def load():
    raw = json.load(open(DATA))
    series = {}
    for ch in CH:
        pts = {r["start"]: float(r["mean"] or 0)
               for r in raw.get(ch, []) if r.get("mean") is not None}
        series[ch] = pts
    stamps = sorted(set.intersection(*[set(s) for s in series.values()]))
    X = np.array([[series[ch][t] for ch in CH] for t in stamps])
    # normalize per channel: log for power (heavy right tail), /100 for soc
    Xn = np.zeros_like(X)
    for i in range(X.shape[1]):
        col = X[:, i]
        Xn[:, i] = col / 100.0 if col.max() <= 100 else \
            np.log1p(np.maximum(col, 0)) / np.log1p(max(col.max(), 1))
    # samples: 24h window -> next pv
    xs, ys, ts = [], [], []
    for i in range(WINDOW, len(Xn) - 1):
        xs.append(Xn[i - WINDOW:i])
        ys.append(Xn[i + 1, 0])          # next-hour PV (normalized)
        ts.append(i)
    return np.array(xs), np.array(ys), np.array(ts), X


class LSTM:
    def __init__(self, din, hid):
        s = 0.1
        self.W = rng.normal(0, s, (4 * hid, din + hid))
        self.b = np.zeros(4 * hid)
        self.Wy = rng.normal(0, s, (1, hid))
        self.by = np.zeros(1)
        self.din, self.hid = din, hid

    def forward(self, xs):
        """xs: (T, din). Returns caches for BPTT."""
        h, c = np.zeros(self.hid), np.zeros(self.hid)
        cs = []
        for x in xs:
            z = np.concatenate([x, h])
            f = sig(self.W[0*self.hid:1*self.hid] @ z + self.b[0*self.hid:1*self.hid])
            i = sig(self.W[1*self.hid:2*self.hid] @ z + self.b[1*self.hid:2*self.hid])
            o = sig(self.W[2*self.hid:3*self.hid] @ z + self.b[2*self.hid:3*self.hid])
            g = np.tanh(self.W[3*self.hid:] @ z + self.b[3*self.hid:])
            c = f * c + i * g
            h = o * np.tanh(c)
            cs.append((z, f, i, o, g, c.copy(), h.copy()))
        return cs, h

    def backward(self, cs, dy):
        """BPTT: gradients through the conveyor. dy = dL/dy_pred."""
        dW = np.zeros_like(self.W)
        db = np.zeros_like(self.b)
        dWy = cs[-1][6][None, :] * dy          # h_T.T @ dy
        dby = np.array([dy])
        dh = (self.Wy[0] * dy).copy()
        dc = np.zeros(self.hid)
        dh_next = np.zeros(self.hid)
        for t in reversed(range(len(cs))):
            z, f, i, o, g, c, h = cs[t]
            c_prev = cs[t-1][5] if t > 0 else np.zeros(self.hid)
            dh_tot = dh + dh_next
            # gates, backwards through their nonlinearities
            do = dh_tot * np.tanh(c) * o * (1 - o)
            dc_tot = dc + dh_tot * o * (1 - np.tanh(c) ** 2)
            df = dc_tot * c_prev * f * (1 - f)
            di = dc_tot * g * i * (1 - i)
            dg = dc_tot * i * (1 - g ** 2)
            dW_gates = np.concatenate([df, di, do, dg])
            dW += np.outer(dW_gates, z)
            db += dW_gates
            dz = self.W.T @ dW_gates            # back into [x, h_prev]
            dh_next = dz[self.din:]
            dc = dc_tot * f                     # through the conveyor!
            dh = np.zeros(self.hid)
        return dW, db, dWy, dby


def main():
    epochs = int(sys.argv[sys.argv.index("--epochs") + 1]) \
        if "--epochs" in sys.argv else EPOCHS
    xs, ys, ts, X_raw = load()
    n = len(xs)
    cut = int(n * 0.8)                          # temporal split again
    print(f"samples={n} window={WINDOW}h hid={HID} "
          f"train={cut} test={n-cut}")

    net = LSTM(xs.shape[2], HID)
    for ep in range(epochs):
        order = rng.permutation(cut)
        loss = 0.0
        for idx in order:
            cs, h = net.forward(xs[idx])
            y = float(net.Wy @ h + net.by)
            err = y - ys[idx]
            loss += err ** 2
            dW, db, dWy, dby = net.backward(cs, 2 * err)
            for g in (dW, db, dWy, dby):
                np.clip(g, -CLIP, CLIP, out=g)
            net.W -= LR * dW; net.b -= LR * db
            net.Wy -= LR * dWy; net.by -= LR * dby
        if ep % 5 == 0 or ep == epochs - 1:
            print(f"  epoch {ep:3d} mse={loss/cut:.5f}")

    # eval — normalized MSE back to watts for readability
    pv_max = X_raw[:, 0].max()
    def denorm(v):
        return np.expm1(v * np.log1p(max(pv_max, 1)))

    errs, naive, persist = [], [], []
    for idx in range(cut, n):
        cs, h = net.forward(xs[idx])
        yhat = float(net.Wy @ h + net.by)
        errs.append((denorm(yhat) - denorm(ys[idx])) ** 2)
        naive.append((denorm(xs[idx][-1, 0]) - denorm(ys[idx])) ** 2)
        # same-hour-yesterday = the value 24 rows back in the series
        i24 = ts[idx] - 24 + 1
        ref = X_raw[i24 - 1, 0] if 0 <= i24 - 1 < len(X_raw) else 0
        persist.append((ref - denorm(ys[idx])) ** 2)
    rmse = lambda e: float(np.sqrt(np.mean(e)))
    print(f"\ntest RMSE: LSTM {rmse(errs):.0f}W | "
          f"seasonal-naive {rmse(persist):.0f}W | "
          f"persistence {rmse(naive):.0f}W")
    w = sum(v.size for v in (net.W, net.b, net.Wy, net.by)) * 8
    print(f"weights: {w/1024:.1f}KB — nest-node scale")
    np.savez("model-lstm.npz", W=net.W, b=net.b, Wy=net.Wy, by=net.by)


if __name__ == "__main__":
    main()
