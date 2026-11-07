# Education maintenance — 2026-10-27

**92 lessons** · 26 flagged · 66 clean · compliance **0.9643** · verify **pass**

Reused components: `lessons-audit.py` (R1–R5), `lessons-drift.py` (source refs vs git), `lessons-due.py` (review buckets) — one /lesson fetch feeds all three. Read-only: fixes are a separate explicit /lesson upsert; deletion is human-gated.

## Policy flags (audit R1–R5)

| flag | n |
|---|---|
| `R1:overdue` | 5 |
| `R2:thin(24ch)` | 1 |
| `R2:thin(4ch)` | 1 |
| `R3:no-pointer` | 12 |
| `R4:orphan` | 2 |
| `R5:consider-thai` | 12 |

## Policy dimensions (lesson-polish 7-dim)

| dim | pass | fail |
|---|---|---|
| content | 90 | 2 |
| level | 92 | 0 |
| source | 92 | 0 |
| next_review | 87 | 5 |
| thai | 90 | 2 |
| hub_link | 90 | 2 |
| split_rule | 80 | 12 |

## Compliance trend

0.9643 now — first run · polish anchor 0.9307→0.9916 (2026-10-24)

## Source drift (lessons-drift)

drifted **3** · source-gone **40** · no-repo-source 47

| slug | topic | flags |
|---|---|---|
| `lesson-cec1225f6869` | DevNest voice readiness and Telegram group policy | `source-gone:docs/kb/telegram-conversation-standard.md`<br>`source-gone:docs/tools/devnest-continuous-improvement-standard.md` |
| `lesson-d5f4ea8e2f2d` | devnest-continuous-improvement-standard | `source-gone:docs/tools/devnest-continuous-improvement-standard.md` |
| `lesson-b8e17de59152` | mcp-fleet-audit-procedure | `source-gone:docs/tools/mcp-fleet-audit.md` |
| `lesson-fb34c14f3a28` | DevNest performance, caching, tokenization, and pa | `source-gone:docs/tools/inference-provider-market.md`<br>`source-gone:docs/kb/devnest-performance-and-research-procedure.md` |
| `lesson-b15cd9f285f6` | AI model efficiency and morning news procedure | `source-gone:docs/hub/release_notes.html`<br>`source-gone:docs/kb/ai-news-to-education-procedure.md` |
| `lesson-1e4c0dfd3d5c` | devnest-opencode-web-sample | `drift:README.md(2026-10-26>2026-10-25)` |
| `lesson-33e213efcf13` | self-hosted-llm-inference-homelab | `drift:README.md(2026-10-26>2026-10-25)`<br>`source-gone:docs/function-calling.md` |
| `lesson-ff5781755354` | ada-nest 2026-10-23/24 wrap — the distributed fact | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-b45ff3156418` | LLM caching for agent loops — what helps, what doe | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-c21650c0efda` | claude-fable-5-1 | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-373f8c0c816e` | Jev for coding — the verifier/judge layer | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-0fc3f17762aa` | ai-lane-delegation-procedure | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-299755d6d6fa` | ada-nest doc-pilot rough cut v1 retrospective | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-95610f8e4c00` | ada-nest doc-pilot v2 follow-up | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-7f41f956e119` | voice-600ms-turn-taking | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-78d39e02d2fd` | local-voice-full-landscape | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-b41cf57e2899` | cheap-agent-cascade | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-263eef1b54f3` | pattern-match-coding | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-1e0a833ba9a6` | colab-gpu-worker | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-f429ea4f886c` | trade-map | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-e997ed032520` | platform-nodebb-vs-wordpress | `source-gone:docs/tools/agentic-ai-coding-ides.md` |
| `lesson-2d0b2c9e8b5b` | ai-workforce-eval | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-601ae55c3bba` | ada-nest-tts-eval | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-0e26056ed2dd` | ada-nest-iphone-webgpu | `source-gone:apps/webgpu-bench/job.json`<br>`source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-9091f396bb74` | education-manager-benchmark | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-7988868998ad` | 3d-models-from-map-data | `source-gone:docs/tools/agentic-ai-coding-ides.md`<br>`source-gone:docs/tools/3d-models-from-map-data.md` |
| `lesson-9bc73936498c` | Ada Nest — NCM report | `drift:README.md(2026-10-26>2026-10-24)`<br>`source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-48e4a2fba780` | rclone vs Drive REST API — storage transport choic | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-c0dba8521398` | ada-nest-video | `source-gone:scripts/ops/video-qc.py` |
| `lesson-feaeaddd9feb` | rogue DHCP server hunt on LAN | `source-gone:docs/devin-macbook-ipv4-outage.md` |
| `lesson-dffe269a27c5` | ada-nest-hardware | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-d495eb326d86` | cloning my voice — corpus, lanes, and gates | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-9559d7a3e16e` | Thai voice cloning — bench + blind listen | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-e5b8a63af847` | openmausbot-assessment | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-ba44b7fd57e7` | Ada Nest — architecture map | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-51569f4faa8f` | Next-Concept Modeling (NCM) — parallel coarse-to-f | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-e7eb7afd1278` | voice-sample corpus — TG voice notes + STT benchma | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-398b702f3770` | Embedding space eval: gemini-embedding-2 vs nomic  | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-9109800579c2` | Grok (xAI) vs Gemini for our lanes — pricing cheat | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-d06f878368fb` | Embedding migration economics — translate-first co | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-fe9ce7525b69` | Cloud object storage: S3 vs R2 vs B2 + Chaba hybri | `source-gone:docs/tools/ai-workforce-eval.md` |

## Review queue (lessons-due)

due **14** · upcoming **78** · learned 0

| due | slug | topic |
|---|---|---|
| 2026-10-24 | `lesson-9024b9ffa2ce` | telegram voice stt backends qwen vs gemini |
| 2026-10-24 | `lesson-8b0f5fd70485` | household persona naming convention |
| 2026-10-25 | `lesson-4865e5f26c60` | Ada lanes — outbound delivery surfaces (TG/LINE/HA/webchat/v |
| 2026-10-26 | `lesson-eaf7a735623e` | rika-rk600-michael-site |
| 2026-10-26 | `lesson-cdf16adca87b` | MacBook SMC reset — CPU throttle latch / post-battery-swap f |
| 2026-10-27 | `lesson-9559d7a3e16e` | Thai voice cloning — bench + blind listen |
| 2026-10-27 | `lesson-e5b8a63af847` | openmausbot-assessment |
| 2026-10-27 | `lesson-ba44b7fd57e7` | Ada Nest — architecture map |
| 2026-10-27 | `lesson-89c3c98aecb3` | Ada Nest — corpus and speaker identity |
| 2026-10-27 | `lesson-b9ab7c03e1d3` | Ada Nest — gate cascades and adaptive depth |
| 2026-10-27 | `lesson-51569f4faa8f` | Next-Concept Modeling (NCM) — parallel coarse-to-fine text g |
| 2026-10-27 | `lesson-e6dd80bb9a87` | Thai voice-dub video catalog — playable links |
| 2026-10-27 | `lesson-e7eb7afd1278` | voice-sample corpus — TG voice notes + STT benchmark |
| 2026-10-27 | `lesson-59eee13a46b6` | local audio runtimes — single-binary STT/TTS landscape (Phon |

## Intentional no_th exceptions

**10** exempt (10 would otherwise flag R5)

- `lesson-00750611bace` devnest-host-assessment — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-1e4c0dfd3d5c` devnest-opencode-web-sample — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-395598f2d76d` SSOT and WordPress lesson CPT relationship — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-57b4db08c3a2` ada-nest-golden-hour-catch — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-5fcc4a0a6015` devnest-layered-reports — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-8afd171c8dd5` groq-free-tier-fit — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-8d451125b029` devnest-devin-replay-benchmark — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-d5f4ea8e2f2d` devnest-continuous-improvement-standard — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-dd11e3146f15` node-red-devnest-visual-map — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)
- `lesson-fa3704d7af02` devnest-news-watch-procedure — via exceptions (baseline-2026-10-27 Thai-free; treated as legit no_th by the polish pass)

## Human review pending

| slug | topic | why |
|---|---|---|
| `lesson-0e26056ed2dd` | ada-nest-iphone-webgpu | referenced source doc gone — re-point the lesson or commit the doc [source-gone:apps/webgpu-bench/job.json]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-0fc3f17762aa` | ai-lane-delegation-procedure | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-1e0a833ba9a6` | colab-gpu-worker | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-263eef1b54f3` | pattern-match-coding | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-299755d6d6fa` | ada-nest doc-pilot rough cut v1 retrospective | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-2d0b2c9e8b5b` | ai-workforce-eval | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-33e213efcf13` | self-hosted-llm-inference-homelab | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/function-calling.md] |
| `lesson-373f8c0c816e` | Jev for coding — the verifier/judge layer | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-398b702f3770` | Embedding space eval: gemini-embedding-2 vs n | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-4865e5f26c60` | Ada lanes — outbound delivery surfaces (TG/LI | spaced review due 2026-10-25 — Tony's review queue |
| `lesson-48e4a2fba780` | rclone vs Drive REST API — storage transport  | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-51569f4faa8f` | Next-Concept Modeling (NCM) — parallel coarse | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-27 — Tony's review queue |
| `lesson-59eee13a46b6` | local audio runtimes — single-binary STT/TTS  | spaced review due 2026-10-27 — Tony's review queue |
| `lesson-601ae55c3bba` | ada-nest-tts-eval | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-78d39e02d2fd` | local-voice-full-landscape | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-7988868998ad` | 3d-models-from-map-data | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/3d-models-from-map-data.md]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/agentic-ai-coding-ides.md] |
| `lesson-7f41f956e119` | voice-600ms-turn-taking | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-89c3c98aecb3` | Ada Nest — corpus and speaker identity | spaced review due 2026-10-27 — Tony's review queue |
| `lesson-8b0f5fd70485` | household persona naming convention | spaced review due 2026-10-24 — Tony's review queue |
| `lesson-9024b9ffa2ce` | telegram voice stt backends qwen vs gemini | spaced review due 2026-10-24 — Tony's review queue |
| `lesson-9091f396bb74` | education-manager-benchmark | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-9109800579c2` | Grok (xAI) vs Gemini for our lanes — pricing  | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-9559d7a3e16e` | Thai voice cloning — bench + blind listen | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-27 — Tony's review queue |
| `lesson-95610f8e4c00` | ada-nest doc-pilot v2 follow-up | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-9bc73936498c` | Ada Nest — NCM report | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-b15cd9f285f6` | AI model efficiency and morning news procedur | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/hub/release_notes.html]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/kb/ai-news-to-education-procedure.md] |
| `lesson-b41cf57e2899` | cheap-agent-cascade | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-b45ff3156418` | LLM caching for agent loops — what helps, wha | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-b8e17de59152` | mcp-fleet-audit-procedure | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/mcp-fleet-audit.md] |
| `lesson-b9ab7c03e1d3` | Ada Nest — gate cascades and adaptive depth | spaced review due 2026-10-27 — Tony's review queue |
| `lesson-ba44b7fd57e7` | Ada Nest — architecture map | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-27 — Tony's review queue |
| `lesson-c0dba8521398` | ada-nest-video | referenced source doc gone — re-point the lesson or commit the doc [source-gone:scripts/ops/video-qc.py] |
| `lesson-c21650c0efda` | claude-fable-5-1 | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-cdf16adca87b` | MacBook SMC reset — CPU throttle latch / post | spaced review due 2026-10-26 — Tony's review queue |
| `lesson-cec1225f6869` | DevNest voice readiness and Telegram group po | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/kb/telegram-conversation-standard.md]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/devnest-continuous-improvement-standard.md] |
| `lesson-d06f878368fb` | Embedding migration economics — translate-fir | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-d495eb326d86` | cloning my voice — corpus, lanes, and gates | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-d5f4ea8e2f2d` | devnest-continuous-improvement-standard | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/devnest-continuous-improvement-standard.md] |
| `lesson-df2515c1a5fd` | speed-probe | thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(4ch)] |
| `lesson-dffe269a27c5` | ada-nest-hardware | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-e5b8a63af847` | openmausbot-assessment | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-27 — Tony's review queue |
| `lesson-e6dd80bb9a87` | Thai voice-dub video catalog — playable links | spaced review due 2026-10-27 — Tony's review queue |
| `lesson-e7eb7afd1278` | voice-sample corpus — TG voice notes + STT be | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-27 — Tony's review queue |
| `lesson-e997ed032520` | platform-nodebb-vs-wordpress | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/agentic-ai-coding-ides.md] |
| `lesson-eaf7a735623e` | rika-rk600-michael-site | spaced review due 2026-10-26 — Tony's review queue |
| `lesson-f429ea4f886c` | trade-map | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-f68da2aab485` | speed-probe-lesson | thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(24ch)] |
| `lesson-fb34c14f3a28` | DevNest performance, caching, tokenization, a | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/kb/devnest-performance-and-research-procedure.md]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/inference-provider-market.md] |
| `lesson-fe9ce7525b69` | Cloud object storage: S3 vs R2 vs B2 + Chaba  | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |
| `lesson-feaeaddd9feb` | rogue DHCP server hunt on LAN | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/devin-macbook-ipv4-outage.md] |
| `lesson-ff5781755354` | ada-nest 2026-10-23/24 wrap — the distributed | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md] |

## Verify

status **pass** · digest `b4e31b30c8d97884`
- ✓ total_matches_list rows=92 list=92 count=92
- ✓ buckets_sum 14+78+0
- ✓ due_rows_match 
- ✓ dimensions_sum 
- ✓ flag_counts_match 
- ✓ drift_counts_match 
- ✓ exempt_subset exempt=10

## Refs

- card: `education-maintenance-consolidated-report` · education-due page: private WP page slug education-due (post 354)
- member index: https://boards.surf-thailand.com/wp/lesson/
- runbook: `docs/ssot/jobs/education/2026-10-27-education-maintenance-report.yml` · exceptions: `scripts/lesson-thai-exceptions.yml`
- artifacts: `latest.json`/`latest.md` + `history.jsonl` in this dir · generated 2026-10-27T06:40:34+00:00
