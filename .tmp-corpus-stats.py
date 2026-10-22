import json, datetime as dt
from collections import defaultdict
days = defaultdict(lambda: {"n": 0, "to": 0, "fast": 0, "ok_ms": [], "sess": set(), "surf": defaultdict(int)})
path = "/home/tony/.local/share/ada/command-lane-corpus.jsonl"
with open(path) as f:
    for ln in f:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        ts = r.get("ts", 0)
        d = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        ms = r.get("ms")
        dd = days[d]
        dd["n"] += 1
        dd["sess"].add(r.get("session", ""))
        dd["surf"][r.get("surface", "?")] += 1
        if ms is None:
            continue
        if ms >= 29000:
            dd["to"] += 1
        elif ms < 100:
            dd["fast"] += 1
        else:
            dd["ok_ms"].append(ms)
for d in sorted(days):
    dd = days[d]
    ok = dd["ok_ms"]
    med = sorted(ok)[len(ok) // 2] if ok else 0
    surf = ",".join(f"{k}:{v}" for k, v in dd["surf"].items())
    print("%s rows=%4d timeouts=%3d fastfail=%3d ok=%4d med_ok_ms=%5d sess=%d surf=%s"
          % (d, dd["n"], dd["to"], dd["fast"], len(ok), med, len(dd["sess"]), surf))

# drill into 2026-10-13 evening window: classify rows by ms bucket
print("\n--- 2026-10-13 20:00-23:00 per-hour ---")
hrs = defaultdict(lambda: {"to": 0, "fast": 0, "ok": 0})
with open(path) as f:
    for ln in f:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        t = dt.datetime.fromtimestamp(r.get("ts", 0))
        if t.date() != dt.date(2026, 10, 13) or not (20 <= t.hour <= 22):
            continue
        h = t.strftime("%H:00")
        ms = r.get("ms") or 0
        if ms >= 29000:
            hrs[h]["to"] += 1
        elif ms < 100:
            hrs[h]["fast"] += 1
        else:
            hrs[h]["ok"] += 1
for h in sorted(hrs):
    print(h, hrs[h])
