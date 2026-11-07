# dispatch-outcome — img-gen-bench (BEN-0815) r2 + T4 arm staged

## What changed / was found

**Host gate (verified live):** the card's candidates fail the pack's
`needs.ram_gb: 18` — mn01 has 7 GB total, idc03 has 15 GB total (3 GB
avail); omen was loaded (LA ~37, card-judgment benches); tony-macbook
(runner) has 15 GB. **con01 (24 GB) is the only fleet host that fits** —
and it still had the colibri qwenimage server RESIDENT since the Oct 24
run (14.7 GB RSS, `/health` ok), so the >3h model-load cost was already
paid.

**R2 extension run on con01:** generated 4 more images through
`POST /v1/images/generations` — doc-pilot storyboard styles
(sun/saturn/mars, solar-system-kk style suffix) + generic-3:

| prompt | sec |
|---|---|
| doc-pilot-sun | 1329 |
| doc-pilot-saturn | 1358 |
| doc-pilot-mars | 1232 |
| generic-3 | 1262 |

Combined con01 baseline (r1+r2, n=8): mean ~1260s (21min)/img, p50 1247s,
p95 1354s, 0 failures in 10 scheduler admissions. Engine RSS constant
14.7 GB; mem-avail dipped to ~4 GB mid-gen — the 18 GB floor is real.
QC: generic-3 excellent, sun/mars good, **saturn near-black** — "deep
black space" under-exposes dim subjects.

**NEW pack staged:** `img-gen-bench-t4` (the card's GPU arm, job4 of
`docs/ssot/jobs/nest/2026-10-25-ada-nest-real-job-seq.yml`) — T4 CUDA,
10 prompts x2 samples, VRAM + p50/p95 + con01 comparison row + contact
sheet; `requires` the 3 done T4 packs. Staged to
`gdrive:ada-nest/packs/img-gen-bench-t4/` — claims automatically on the
next awake Colab runtime (heartbeat was ~9d stale; no runtime started).

## Result

CPU disk-streaming image gen confirmed: works, ~21 min/img, batch-only —
GPU remains the practical lane (unchanged verdict, now n=8 evidence).
The T4 arm is no longer a plan — it's a staged pack waiting for any
awake runtime.

## Files

- repo: `scripts/colab/packs/img-gen-bench-t4/pack.yml` (new),
  `scripts/colab/packs/img-gen-bench/pack.yml` (timeout 900→2400 fix),
  `docs/ssot/jobs/bench/2026-11-07-img-gen-bench-r2.yml` (trail)
- store: `gdrive:ada-nest/packs/img-gen-bench/out/` — 4 new PNGs +
  `img-gen-r2-report.md` + `r2-rows.json` + `metrics-{pre,post}.json`
- commit `d718c288a` on `dispatch/20261107-190909-...` (not pushed)

## How to verify

- `rclone lsf gdrive:ada-nest/packs/img-gen-bench/out/` → 8 PNGs, 2 reports
- `rclone cat gdrive:ada-nest/packs/img-gen-bench/out/img-gen-r2-report.md`
- `rclone lsf gdrive:ada-nest/packs/img-gen-bench-t4/` → pack.yml staged
- con01: `curl -s :8000/health` → scheduler completed 8

## Followups (in SSOT file)

- con01 server still resident — keep until t4 arm lands, then `coli stop`
- dark-scene prompts need exposure cue / more steps (saturn evidence)
