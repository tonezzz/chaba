# dispatch-outcome — idc02-ambient-cpu-stt-latency

**Result: measured, fixed, recommended (a) CPU priority.** Quiet-vs-busy
RTF matrix run on idc02 as the card required, plus a production-truth
check that changes the card's framing.

## Premise correction (verified against live state)

- Production STT **already left idc02** on 2026-10-22 (OPS-0763):
  idc03 `ada-tg-relay` env has `TG_WHISPER_URL=http://100.72.146.39:8914`
  (con01); the other relay env uses `127.0.0.1:8914` = idc03's own
  ada-stt fallback. idc02:8914 has **no production consumers** — it is
  standby/eval only.
- con01 (the current prod) is itself saturated: load ~9–11 on 8 shared
  Contabo vCPU; measured RTF **2.1–2.6** ambient (10.2 cold-start) —
  worse than the idc02 numbers the card cites. There is **no quiet
  host** to move to (idc02 ~1–7/4, idc03 ~3–4/4, con01 ~10/8).

## What was measured (idc02, qwen3-asr-0.6b-q8, threads=4)

Second test instance on 127.0.0.1:8916; live :8914 untouched.
Synthetic load = 4 nice-0 CPU spinners (fair-share saturation, harsher
than real tenants). Full per-clip CSV: `idc02:~/stt-contention-test/`.

| scenario | load | RTF |
|---|---|---|
| ambient (quiet-ish) | ~1–3 | 0.41–1.21 |
| busy0 saturation | ~5–10 | **3.4–9.9** (TTT 17–178s) |
| busy0 + **nice -10** | ~7.5 | **0.69–1.39** ✅ |
| busy0 + threads=3 | ~7 | 2.0–11.1 ❌ |
| shield: taskset 2 cores | ~7 | 0.82–1.28 |
| CPUWeight=1000, in-slice stress | ~7 | 0.80–1.14 |
| CPUWeight=1000, session-scope stress | ~3–7 | 3.2–5.5 |
| real tenants only (~6 load) | ~6 | 0.80–1.06 |
| con01 ambient, before weight | ~9–11 | 2.1–2.6 |
| con01 ambient, after weight | ~10–11 | **1.29–1.7** |

## What was changed

- `CPUWeight=1000` applied via `systemctl --user set-property` on
  `ada-stt.service` on **idc02, con01, idc03** — persistent drop-in,
  rootless-safe, revert with `CPUWeight=100`. con01 (prod) improved
  ~1.7x immediately under load ~10–11.
- Coverage gap noted: cgroup weight arbitrates only inside `app.slice`;
  system.slice bursts (journalctl ~95%) and session scopes bypass it.
  Full protection = convert ada-stt to a system unit with `Nice=-10`
  (validated 0.69–1.39 under total saturation) or
  `systemctl set-property user-1000.slice CPUWeight=500` (broader blast
  radius). Left as a flagged option — it's a host-wide policy knob.

## Verdict for the card

- **(a) CPU priority — chosen and partially applied** (weight applied;
  Nice=-10 recommended as the stronger follow-up).
- (b) threads=3: rejected by measurement.
- (c) accept-as-batch: unnecessary — the fix is a one-line property.
- (d) move host: moot — already migrated, and every fleet host is loaded.

## Repo artifacts

- `docs/ssot/jobs/voice/2026-11-07-stt-cpu-contention-matrix.yml` —
  full report, method, verify commands.

## How to verify

1. `systemctl --user show ada-stt -p CPUWeight` on idc02/con01/idc03 → 1000
2. `curl -s http://100.72.146.39:8914/health` → ok (prod)
3. Re-run: `ssh idc02 'cd ~/stt-contention-test && ./run-matrix.sh'`
