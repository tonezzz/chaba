# Dispatch prompt-budget measurement — 2026-11-25

Card `dispatch-prompt-budget-measure` (parent `devin-usage-reduction`,
DEV-0044 lever 4). Read-only measurement: no dispatch-path code changed.

## Dataset

`python3 scripts/devin/devin-usage.py --fleet --days 30 --json` run
2026-11-25 ~09:35 +07. Per-session rows joined to
`~/.local/share/devin-dispatch/tasks/<id>/` on each host (prompt.txt,
meta.json, transcript.json, exit_code, run.N.log).

- **494 sessions** with transcript+meta in window (2026-10-26 →
  2026-11-25): idc02 186, tony-omen 175, tony-dell 98, mn01 35.
- **idc01 unreachable** — `ssh: connect to host 100.74.146.0 port 22:
  Connection timed out` (warm-DR VPS down or tailscale path dead).
- **idc03 contributed 0 in-window sessions** — reachable, 165 task dirs,
  but its 145 transcripted sessions all ended ≤2026-10-16; every
  2026-11-23 dispatch died on free-model rate limits before writing a
  transcript (exit_code=1, run.1-3.log = rate-limit retries). Usage
  accounting correctly shows ~0 burn, but those attempts are invisible
  to token metrics.
- **62/494 (12.6%) sessions have transcript.json but empty
  final_metrics** (prompt=0) — mostly rate-limit/early-crash deaths
  (tony-omen exit-1 ×25, tony-dell unstamped ×27, mn01 ×4). They count
  as sessions but burn ~0 tokens.
- 432 sessions carry metrics: **1,890,710,440 prompt tokens**,
  1,714,763,584 cached (**90.7%**), 12,602,040 completion,
  **26,276 total steps** → avg 71,956 prompt tokens/step.

## Headline distributions (n=432)

| metric | p10 | p50 | p90 | p99 | max | mean |
|---|---|---|---|---|---|---|
| prompt tokens | 790,949 | 3,453,675 | 9,073,025 | ~16.1M | 19,807,212 | 4,376,645 |
| steps | 24 | 57 | 96 | ~155 | 206 | 61 |
| prompt/step | 27.7k | 61.7k | 96.9k | — | 126.2k | 61.5k |
| prompt.txt bytes | 2,749 | 6,563 | 8,113 | — | 11,182 | 5,556 |
| spec bytes (pre-rails) | 1,722 | 2,114 | 3,080 | 5,257 | 5,802 | 2,310 |
| primer lines | 0 | 6 | 12 | — | 12 | 5 |
| primer bytes | 0 | 2,440 | 3,190 | — | 3,322 | 1,554 |

Top decile (prompt ≥ p90, n=44): steps p50=112 (vs 57 median),
prompt_bytes p50=6.1KB — **the whales are long sessions, not big
prompts**.

## Driver correlations (Pearson / Spearman vs total prompt tokens)

| driver | n | pearson | spearman |
|---|---|---|---|
| **steps** | 432 | **+0.957** | **+0.968** |
| completion tokens | 432 | +0.874 | +0.923 |
| cached tokens | 432 | +0.988 | +0.990 |
| wall time (transcript span) | 432 | +0.30 | +0.15 |
| prompt.txt bytes | 432 | +0.070 | +0.128 |
| spec bytes | 432 | +0.063 | +0.152 |
| primer bytes | 432 | +0.065 | +0.075 |
| attempt_n (retry rail) | 103 | +0.069 | +0.101 |

`completion`/`cached` are mechanical co-variates, not drivers. **Step
count is effectively the whole story** — every inference call resends
the full context, so prompt tokens ≈ steps × context-size.

Initial-prompt size is *not* a driver: spec p50=2.1KB, p99=5.3KB,
max=5.8KB; r(spec, prompt)=0.06, r(spec, steps)=0.08. Even a 6KB spec
adds ~1.6k tokens to a ~62k-token step context (~2.6%), and it is
resent every step — but the measured spread is too small to matter.

## Fixed per-step context floor (the real lever)

Measured on 5 transcripts across 4 hosts (system messages +
tool_definitions chars ÷ ~3.7 chars/token):

| host/task | system chars | tooldef chars | est. floor/step |
|---|---|---|---|
| tony-dell chaba ×2 | 64–73KB | 37KB | ~27–30k tok |
| idc02 | 44KB | 36KB | ~22k tok |
| tony-omen | 81KB | 37KB | ~32k tok |
| mn01 | 44KB | 37KB | ~22k tok |

Cross-check: prompt/step p10 = 27.7k — early-session steps ≈ floor.
Fleet-wide at ~26k/step × 26,276 steps ≈ **683M tokens = ~36% of all
prompt tokens is fixed context resent every step** (range 31–40% at
22–29k/step). Composition: Devin system prompt + injected rules
(AGENTS.md is 80.7KB source, injection capped ~16KB/rule; windsurf
common 24.4KB) + skills list + ~20 MCP server descriptions +
tool_definitions (~37KB ≈ 10k tok/step alone).

Repo-controllable trims inside that floor: **every 1KB of fixed-context
reduction saves ~7.1M tokens/30d fleet-wide; every 10KB ≈ 71M (3.7%)**.

## Outcome join (top decile n=44 + median-band sample n=40)

Method: per-session outcome from (a) git merge-state probed on the
origin host (worktree HEAD vs origin/<default>, first-parent empty
check), (b) card comms sliced from the comm naming the task's
`YYYYMMDD-HHMMSS` anchor to the next task's comms (archive-aware card
index, 1,844 cards incl. cards/archive/), (c) meta.result/exit_code.
Precedence: verified > merged > zero-commit > merge-blocked > failed >
unmerged > unknown. Comms `at` is +07:00 minute-precision; multi-attempt
cards are attributed by task-id anchor, not wall-clock window.

| outcome | top (n=44) | mid (n=40) | all (n=84) | mean prompt |
|---|---|---|---|---|
| verified | 24 | 16 | 40 | 9.18M |
| merged (unverified stamp) | 3 | 4 | 7 | 6.61M |
| card done, no git/comms evidence | 8 | 8 | 16 | 7.57M |
| merge_blocked (held/conflicts/test-gate) | 4 | 8 | 12 | 5.42M |
| unmerged_work (branch ahead, not landed) | 3 | 2 | 5 | 7.63M |
| zero_commit | 1 | 0 | 1 | 11.33M |
| failed_early (rate-limit/crash) | 1 | 2 | 3 | 5.75M |

Non-landing outcomes (merge_blocked + unmerged + zero_commit +
failed_early) = 21/84 sessions ≈ **131M of 693M sampled prompt tokens
(~19%) burned without a clean landing**. Caveat: classification is
best-effort; remote `origin/*` refs may be stale where the worktree
was GC'd, and merge-sweep can land work hours after the session —
a few "unmerged"/"card_done" rows may have landed later.

## Other observations

- **Host**: mn01 highest mean (5.95M, steps p50=69); idc02 lowest
  prompt.txt p50 (3.8KB — ~2/3 of its sessions predate primer coverage,
  which only reached ~94% in the last week: 180/192 primed vs 0/223
  before 2026-11-16).
- **Model**: swe-2-flash-high prompt/step 70.2k vs swe-2-high 55.2k
  (+27%) — likely task-mix confound (flash lanes get different card
  shapes); all models here are free-tier so the difference is
  allowance tokens, not dollars.
- **Retry**: attempt_n≥2 sessions n=58, 231.8M tokens (12.3% of valid
  total). Only 2 sessions reached attempt 3 — the 2-attempt cap is
  nearly binding already. attempt_n parsed only when RETRY_RAILS fired
  (103/432 rows).
- **Primer**: median 6 lines/2.4KB ≈ ~650 tok/step ≈ ~40k tokens per
  median session (~1.2%). Already hard-capped (KNOWN_PITFALLS 8 lines/
  5.5KB + KNOWN_GOOD 4 lines/1.2KB). Presence correlates with *higher*
  usage (4.64M vs 4.11M mean) — confounded: primer fires on cards with
  matching failure history = harder cards. **No further primer cap is
  warranted by this data.**
- **Spec size**: dead hypothesis — specs are already terse; a
  spec-length gate would save ~0 measured tokens.

## Cap proposals (evidence-backed)

1. **Session step-budget / compaction gate** — *strongest direct
   evidence.* Steps>100: 37 sessions, ~84.7M tokens (4.5% of fleet
   prompt burn) beyond step-100 at each session's average context;
   steps>80: 107 sessions, ~215.6M (11.4%); steps>120: 16 sessions,
   ~36M. Proposal: dispatch-side watchdog — at ~80 steps inject a
   "wrap up: commit deliverable + write dispatch-outcome" rail, hard
   ceiling ~150 with partial-outcome salvage. Realistic capture
   ~40–100M tokens/30d (2–5%); the excess estimate is conservative
   because late-session steps cost *more* than the session average
   (context grows monotonically).
2. **Fixed-context diet for dispatch sessions** — ~36% of burn is
   fixed per-step resend. A "dispatch-lite" profile trimming
   tool_definitions (~37KB≈10k tok/step) and rules/MCP descriptions
   toward −20KB fixed context saves **~140M tokens/30d (~7.4%)**;
   −10KB ≈ 71M (3.7%). Cheapest concrete cuts: drop unused MCP
   servers from the dispatch toolset, slim AGENTS.md sections
   irrelevant to unattended runs (the file is 80.7KB; only ~16KB/rule
   injects anyway — audit what actually lands in system messages).
3. **Deliverable-checkpoint rail for long sessions** — non-landing
   outcomes ≈19% of sampled tokens (~360M/30d extrapolated, rough).
   A prompt rail nudging "commit dispatch-outcome skeleton + push
   branch by mid-session" converts zero_commit/merge_blocked waste
   into salvageable partial work. Weaker causal claim — label as
   estimate, measure after landing.
4. **Retry ceiling at 2 attempts → escalate to scoping** — attempt≥2
   already only 58 sessions/231.8M; the marginal saving is small but
   the *shape* is right: third attempts nearly don't exist, so formalize
   "attempt 3 requires a human/ scoping pass" rather than another blind
   re-burn.
5. **Explicitly NOT recommended**: spec-length caps (r≈0.06, specs
   already ≤5.8KB), tighter primer budgets (≈1% of burn, already
   capped), per-host token quotas (host effect is steps/task-mix, not
   host behavior).

## Reproduce

```bash
python3 scripts/devin/devin-usage.py --fleet --days 30 --json
# per-host task detail: for each task dir read prompt.txt (bytes,
# spec = bytes before the TASK_RAILS marker, KNOWN_PITFALLS/KNOWN_GOOD
# "- [" line counts), meta.json (started_at/finished_at/result/card/
# exit_code), transcript.json final_metrics + step timestamps.
# Fleet-wide join key: (host, task-dir basename).
```

idc01 was unreachable at measurement time; re-run picks it up when the
host is back.
