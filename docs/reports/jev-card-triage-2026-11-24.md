# Jev card-triage pilot — Phase 1 re-run (2026-11-24)

Card: `jev-pilot-decision-layer-for-card-triage-d47b53` (KNB-0822).
Script: `scripts/jev/card-triage.py`. Raw records:
`evals/results/jev/card-triage-2026-11-24.json`.

Second run of the pilot — the first (2026-10-25) covered jev-student
+ jevos on 10 backlog cards; this run uses today's live fleet and adds
the open-jev gemma students. Real Jev API still has no key (KNB-0822),
so all arms are self-hosted `$0`.

## Endpoint recon (live-probed 2026-11-24)

| arm | endpoint | model | status |
|---|---|---|---|
| jev-student | `http://100.75.102.88:8780` | jev-student-distilmulti | up — noul proven in-domain only |
| student-1b | `http://100.75.102.88:8778` | gemma-3-1b-it (openjev) | up — full choice/score/noul |
| student-1b-b | `http://100.75.102.88:8779` | gemma-3-1b-it (container) | up — same class, not run |
| heavy-4b | `http://100.75.102.88:8777` | gemma-3-4b-it (openjev) | up — ~75s/call |
| heavy-idc02 | `http://idc02.taila0626a.ts.net:8777` | gemma-3-4b-it | up — same class, not run |
| jev-student (spec'd) | idc03:8778 / :8779 | — | **dead** (curl timeout; disabled per OPS card, SSOT audit drift) |
| jevos | idc03:8017 | jevos-v5 | **down** (ad-hoc serve from 11-23 arena never persisted) |

## Wire format (dependency resolved)

`POST {base}/v1/systemone` `{"model","state","questions"}` — one call
carries all questions. `choice.criteria` = dict label→desc; `score.
criteria` = **list** of level descriptions (a dict 422s on openjev);
`noul.criteria` = dict true/false. Answer shapes differ per backend —
raw answers preserved in the JSON.

Questions per card: `lane` (choice over the 5 dispatch lanes, criteria
mirroring `dispatch_repos.classify_lane`), `priority` (score 1-5),
`ready` (noul — spec complete enough to dispatch). The production
keyword classifier's verdict is included as the reference column.

## Triage table — 10 real backlog cards

| card | prod lane (kw) | student-1b lane (conf) | student-1b prio | student-1b ready | jev-student lane | jev-student prio* | jev-student ready |
|---|---|---|---|---|---|---|---|
| board-cli-request-ask-field | devin (fallback) | devin (0.56) | high | 0.01 | answer@0.0 | degenerate | 0.005 |
| camwall-retire-to-wiki | **free_lane** (kw:documentation) | devin (0.56) | high | 0.001 | answer@0.0 | degenerate | 0.004 |
| audit-miss-ada-voice-job-records | free_lane (kw:docs/) | devin (0.72) | high | 0.006 | answer@0.0 | degenerate | 0.005 |
| ada-spend-guardrails-…-a376c3 | **free_lane** (kw:unit test) | devin (0.47) | high | 0.002 | answer@0.0 | degenerate | 0.004 |
| chore-excise-jules-lane-code | **free_lane** (kw:install) | devin (0.53) | high | 0.001 | answer@0.0 | degenerate | 0.004 |
| board-gantt-timeline-view | devin (fallback) | devin (0.81) | high | 0.32 | answer@0.0 | degenerate | 0.005 |
| audit-oc-mutating-command-0b3n5bce | devin (fallback) | devin (0.36) | high | 0.003 | answer@0.0 | degenerate | 0.006 |
| colab-offload-queue-pack-batch-gpu-jobs | devin (fallback) | devin (0.55) | high | 0.001 | answer@0.0 | degenerate | 0.005 |
| ada-kk-dance-party-video-longer | devin (fallback) | **paid_frontier** (0.53) | high | 0.44 | answer@0.0 | degenerate | 0.004 |
| apps-yml-host-url-still-tony-dell-x42 | devin (fallback) | devin (0.60) | high | 0.002 | answer@0.0 | degenerate | 0.004 |

\* jev-student "priority" is not a score — the head collapses to the
noul probability (~0.004); the earlier "trivial" label was a
0-4 index-mapping artifact of that raw value.

heavy-4b arm: **not viable for batch triage** — first card exceeded a
300s timeout even with the state trimmed to ~700 tokens (the ~75s
single-question noul probes don't scale to 3 questions × card-size
state on CPU). It remains usable for the single-question noul-gate
(Phase 2) where one call per gated op is affordable.

## Findings

1. **jev-student remains noul-only.** Choice head dead on all 10
   (`answer`@0.0 — a label not even in the criteria); score/noul
   collapse to one head probability. Consistent with decision-arena
   2026-11-23 (choice acc 0.062). Keep it for in-domain confirm-gates
   only.

2. **student-1b choice head works mechanically but collapses to the
   safe default.** Real probability distributions (e.g. board-cli:
   devin 0.53 vs paid_frontier 0.47 — a genuine close call), yet
   argmax = `devin` on 9/10 cards; only the paid-creative card broke
   to `paid_frontier`. Its implicit prior is "when unsure, devin" —
   same safe-default philosophy as the production fallback, so it adds
   little routing value over `classify_lane`'s jevos path.

3. **The production keyword classifier showed live false-positives on
   this sample.** Three cards routed `free_lane` on single broad
   keywords that are arguably wrong:
   - `camwall-retire-to-wiki` → free_lane via "documentation" — the
     card is a multi-host retirement (stop units, map consumers);
   - `ada-spend-guardrails` → free_lane via "unit test" — a feature
     build whose spec merely mentions running unit tests;
   - `chore-excise-jules-lane-code` → free_lane via "install" — a
     multi-file excision + redeploy.
   The student-1b's `devin` answers are arguably *more* correct on
   these three — a data point for the known keyword-layer weakness
   (broad single-keyword matches pre-empting the cheap-lane check).

4. **Priority score is degenerate on both cheap arms.** student-1b
   returned "high"@~0.96 confidence on all 10 (score ≈2.98/5 every
   time); jev-student returns the collapsed noul prob. Score-based
   prioritization needs the 4b arm or the real Jev API.

5. **ready-noul is weak but directionally sensible on student-1b.**
   The two highest scores (dance-party 0.44, gantt 0.32) are cards
   with concrete specs; thin auto-filed cards sit at ~0.001-0.006.
   Compressed dynamic range — usable as a hint, not a gate.

## Cost / latency

jev-student ~100-250ms/card; student-1b ~29-141s/card (CPU, state-size
sensitive); heavy-4b ~75s/card projected. All self-hosted, $0.
