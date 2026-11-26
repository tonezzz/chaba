# Devin daily usage — 2026-11-26

Generated 2026-11-26T13:10:15.168922+00:00. Source: local task transcripts + Devin v3 session API + operator meter reading.

## Quota

- Daily remaining: not supplied (read app.devin.ai/settings/usage)
- Daily used at start: not supplied
- Allowance remaining is **not machine-readable on Pro** — consumption API is Enterprise-only, `devin` has no usage subcommand. The percentage above is the one manual input.

## Local dispatch burn

- Sessions: 7
- Prompt tokens: 34,599,519
- Cached tokens: 26,741,760
- Output tokens: 233,042
- Models: SWE-2 Flash High

| Task | Model | Prompt | Cached | Steps |
|---|---|---:|---:|---:|
| 20261126-084311-macbook-15g-ram-already-has-ru | SWE-2 Flash High | 5,068,020 | 3,945,344 | 61 |
| 20261126-084458-recurring-lesson-polish-pass-q | SWE-2 Flash High | 6,479,049 | 5,056,000 | 93 |
| 20261126-124709-evidence-2026-11-26-05-36-05-3 | SWE-2 Flash High | 7,786,918 | 5,994,624 | 85 |
| 20261126-151547-run-scripts-devnest-video-queu | SWE-2 Flash High | 1,937,857 | 1,215,872 | 44 |
| 20261126-152413-run-the-existing-read-only-vid | SWE-2 Flash High | 1,673,432 | 1,201,280 | 39 |
| 20261126-181728-bench-gemini-3-8-live-extended | SWE-2 Flash High | 1,966,441 | 1,519,744 | 20 |
| 20261126-193158-jevnest-is-a-devnest-sub-nest- | SWE-2 Flash High | 9,687,802 | 7,808,896 | 86 |

## Interactive local CLI sessions

- Sessions created: 9
- Sum of per-message num_tokens: 820,988 (approximate — no prompt/cache/output split in sessions.db)
- SWE-2 Flash is free in CLI/Desktop until 2026-12-04 18:00 UTC; after that these tokens bill at documented rates.

| Session | Model | num_tokens |
|---|---|---:|
| Benchmark Gemini 3.8 Live Extended Thinking Agai | swe-2-flash-high | 144,379 |
| Split runner claim capacity and load gates by ex | ? | 129,864 |
| Investigate Playlived and Postgres health monito | swe-2-flash-high | 117,516 |
| Enable MacBook as a daytime runner with suspend  | swe-2-flash-high | 114,039 |
| Implement JevNest KK-Mac Capacity-Aware Producer | swe-2-flash-high | 95,014 |
| Controlled Cline/Nest Model Benchmark After KNB- | ? | 94,968 |
| Recurring Lesson-Polish Pass and Audit Verificat | swe-2-flash-high | 72,848 |
| Read-Only Video Queue Audit and Status Report | swe-2-flash-high | 27,772 |
| Read-Only Video Queue Audit for Both Roots and D | swe-2-flash-high | 24,588 |

## Local model audit

Free-model window ends 2026-12-04 18:00 UTC; after that these models bill at documented rates.

| Host | agent.model | Verdict |
|---|---|---|
| idc02 | swe-2-flash-high | free-now |
| tony-omen | swe-2-flash-high | free-now |
| tony-dell | swe-2-flash-high | free-now |
| tony-macbook | swe-2-flash-high | free-now |
| con01 | swe-2-flash-high | free-now |

## Cloud handoffs

| Card | Session | Status | ACU | PRs | On-demand |
|---|---|---|---:|---|---|
| ADA-0062 | d8e3e0fc8d | suspended/inactivity | 0.0 | https://github.com/tonezzz/chaba/pull/240 | None |
| DEV-1209 | 6c6a00dd37 | running/waiting_for_user | 0.0 | https://github.com/tonezzz/chaba/pull/241 | None |

## Cost per useful task

No meter reading supplied; per-task quota cost cannot be derived here.

No new sessions were launched by this report.
