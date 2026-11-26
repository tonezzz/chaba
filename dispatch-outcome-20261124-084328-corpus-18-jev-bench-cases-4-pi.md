# dispatch outcome — decision-arena-benchmark-decision-models-72ab92 (attempt 5)

Card: `decision-arena-benchmark-decision-models-72ab92` (BEN-0826)
Date: 2026-11-24 · Host: tony-dell worktree · Prior session: devin-task-20261123-211710 (attempt 4)

## What happened

Attempt 4 actually **completed the benchmark** on idc03 at 2026-11-23 21:29 —
all 150 per-case records (3 backends × 50 corpus-v2 cases, 0 errors), computed
ECE/latency, wrote the report, and uploaded it to
`gdrive:ada-nest/reports/2026-11-23-decision-arena-50.md`. The Devin session
then died to a provider rate-limit ~4 min later, before committing anything to
its dispatch branch — so merge-sweep saw "unverified partial work" and the
card bounced.

This attempt did not re-run the benchmark. It verified attempt-4's artifacts
end-to-end and landed them on this branch:

## Verification performed

- `evals/results/jev/decision-arena-50-20261123.json` (150 records, md5
  `5b3ae775…`) is byte-identical to the source on `idc03:/tmp/`.
- All three backends still answer `/v1/systemone` pings (jev-student
  omen:8780 `jev-student-distilmulti`, jevos idc03:8017 `jevos-v5`, laya
  0.5.3 in `~/.venvs/laya-bench`).
- Recomputed every headline metric from the raw records — accuracy,
  per-family (confirm/tool/pipe/stag), noul ECE (raw `noul` probs),
  choice ECE (per-option `probabilities` of the chosen answer), p50
  latency — all match the report. jev-student emits no choice
  distribution → choice ECE correctly reported as undefined.
- Drive report is byte-identical to the repo copy.

## Results (corpus v2, 50 labeled cases)

| backend | acc | confirm | tool | pipe | stag | noul ECE | choice ECE | lat p50 |
|---------|-----|---------|------|------|------|----------|------------|---------|
| jev-student (omen:8780) | 0.480 | 1.000 | 0.062 | 0.600 | 0.417 | 0.325 | — | 40.5ms |
| jevos (idc03:8017) | 0.720 | 0.500 | 0.812 | 0.600 | 0.917 | 0.120 | 0.260 | 752.5ms |
| laya (in-process CPU) | 0.540 | 0.500 | 0.625 | 0.400 | 0.583 | 0.306 | 0.211 | 2959.5ms |

Verdict: no single backend wins — jevos owns tool-routing (0.812) and
stagnation (0.917) but fails the confirm-gate (0.500, under-detects
affirmations at p 0.17–0.42); jev-student is the only correct
confirm-gate (1.000) with a dead choice head; laya is middling with
mirror-image biases at 4–40× latency. Per-family routing is the read.
Real Jev API arm still blocked on key (KNB-0822). Cost $0 — all
self-hosted.

## Files landed

- `scripts/ops/decision-arena.py` — harness now records `raw` answer
  objects per case (enables ECE); laya writes per-case records like the
  HTTP backends. (md5 `c9d2cc7b…`, identical to what produced the run)
- `evals/results/jev/decision-arena-50-20261123.json` — 150 records w/ raw
- `reports/2026-11-23-decision-arena-50.md` — full report (also on Drive;
  force-added past `reports/*` gitignore, matching the 2026-10-25 sibling)
- `docs/ssot/jobs/bench/2026-11-23-decision-arena-3way.yml` — job trail:
  spec-drift resolutions, run config, verdict, follow-ups

## How to verify

- `python3 scripts/ops/decision-arena.py --corpus-only` → 50 cases, errors=[]
- `python3 -c "import json;print(len(json.load(open('evals/results/jev/decision-arena-50-20261123.json'))))"` → 150
- Drive: `rclone lsf gdrive:ada-nest/reports/2026-11-23-decision-arena-50.md`
- Reproduce on idc03: `~/.venvs/laya-bench/bin/python scripts/ops/decision-arena.py --out <path>`
  (defaults point at omen:8780 + 127.0.0.1:8017)

## Open follow-ups (on the card/job doc)

1. jevos `./jev serve` on idc03:8017 is an ad-hoc process, not a declared
   unit — host-hygiene gap; declare it or mark bench-only.
2. jevos confirm-gate threshold sweep before any routing use.
3. Real Jev API arm blocked on key (KNB-0822).
4. idc03 disk was at 100% (1.3G free) during this session — runner deferred
   on disk floor at 08:06; worth a cleanup card if not already carded.

lessons:
- A dispatch session dying to provider rate-limit can leave a COMPLETED run uncommitted in its worktree — before re-running, check sibling `dispatch-wt-*` dirs for the prior attempt's uncommitted artifacts and the remote /tmp outputs.
- `reports/*` is gitignored; report .md files need `git add -f` (65 precedents are tracked).
- The card spec's backend addresses go stale — jev-student moved idc03→omen:8780 on 2026-11-18; verify `systemone` model names in ping responses, not just ports.
- Choice-type raw answers carry per-option `probabilities`; ECE for choice = prob of the chosen option, not the scalar `confidence` field (they differ).
