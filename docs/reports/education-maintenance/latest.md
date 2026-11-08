# Education maintenance — 2026-11-07

**100 lessons** · 94 flagged · 6 clean · compliance **0.7700** · verify **pass** · holds: get_failures=11 — degraded fetch; audit only

Reused components: `lessons-audit.py` (R1–R5), `lessons-drift.py` (source refs vs git), `lessons-due.py` (review buckets) — one /lesson fetch feeds all three. Read-only: fixes are a separate explicit /lesson upsert; deletion is human-gated.

## Policy flags (audit R1–R5)

| flag | n |
|---|---|
| `R1:overdue` | 84 |
| `R2:thin(0ch)` | 11 |
| `R3:no-pointer` | 25 |
| `R4:orphan` | 4 |
| `R5:consider-thai` | 35 |
| `get-failed:HTTP Error 502: Bad Gateway` | 11 |

## Policy dimensions (lesson-polish 7-dim)

| dim | pass | fail |
|---|---|---|
| content | 89 | 11 |
| level | 100 | 0 |
| source | 89 | 11 |
| next_review | 16 | 84 |
| thai | 74 | 26 |
| hub_link | 96 | 4 |
| split_rule | 75 | 25 |

## Compliance trend

0.7700 now vs 0.9643 on 2026-10-27 (Δ-0.1943, flagged Δ+68) · polish anchor 0.9307→0.9916 (2026-10-24)

## Source drift (lessons-drift)

drifted **6** · source-gone **32** · no-repo-source 60

| slug | topic | flags |
|---|---|---|
| `lesson-37b6ef0a2561` | Kornia for Gaussian splat capture evaluation | `source-gone:scripts/gs/image_set_eval.py`<br>`source-gone:mcp-servers/mcp-kornia/server.py` |
| `lesson-2f962413593c` | NCM plus JEV plus Nest benchmark | `source-gone:docs/kb/ncm-jev-nest-exploration-procedure.md` |
| `lesson-549066365c71` | Telegram and LINE messenger control planes | `source-gone:docs/ssot/apps/ssot.messaging-lanes.yml` |
| `lesson-8102ea768518` | github-pages-as-news-publishing-system | `drift:scripts/board/publication.py(2026-11-06>2026-10-27)`<br>`drift:scripts/board/board-api.py(2026-11-06>2026-10-27)` |
| `lesson-bf6ce090216d` | Cline Kanban vs WordPress board apps | `source-gone:apps/board/index.html` |
| `lesson-cec1225f6869` | DevNest voice readiness and Telegram group policy | `drift:docs/kb/telegram-conversation-standard.md(2026-11-07>2026-10-31)`<br>`source-gone:docs/tools/devnest-continuous-improvement-standard.md` |
| `lesson-d5f4ea8e2f2d` | devnest-continuous-improvement-standard | `source-gone:docs/tools/devnest-continuous-improvement-standard.md` |
| `lesson-b8e17de59152` | mcp-fleet-audit-procedure | `source-gone:docs/tools/mcp-fleet-audit.md` |
| `lesson-fb34c14f3a28` | DevNest performance, caching, tokenization, and pa | `source-gone:docs/tools/inference-provider-market.md`<br>`drift:docs/kb/devnest-performance-and-research-procedure.md(2026-11-07>2026-10-26)` |
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
| `lesson-f429ea4f886c` | trade-map | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-e997ed032520` | platform-nodebb-vs-wordpress | `source-gone:docs/tools/agentic-ai-coding-ides.md` |
| `lesson-2d0b2c9e8b5b` | ai-workforce-eval | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-601ae55c3bba` | ada-nest-tts-eval | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-0e26056ed2dd` | ada-nest-iphone-webgpu | `source-gone:apps/webgpu-bench/job.json`<br>`source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-9091f396bb74` | education-manager-benchmark | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-7988868998ad` | 3d-models-from-map-data | `source-gone:docs/tools/agentic-ai-coding-ides.md`<br>`source-gone:docs/tools/3d-models-from-map-data.md` |
| `lesson-9bc73936498c` | Ada Nest — NCM report | `source-gone:docs/tools/ai-workforce-eval.md`<br>`source-gone:docs/kb/ncm-jev-nest-exploration-procedure.md` |
| `lesson-48e4a2fba780` | rclone vs Drive REST API — storage transport choic | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-c0dba8521398` | ada-nest-video | `drift:scripts/ops/video-qc.py(2026-11-07>2026-11-02)` |
| `lesson-feaeaddd9feb` | rogue DHCP server hunt on LAN | `source-gone:docs/devin-macbook-ipv4-outage.md` |
| `lesson-dffe269a27c5` | ada-nest-hardware | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-d495eb326d86` | cloning my voice — corpus, lanes, and gates | `source-gone:docs/tools/ai-workforce-eval.md` |
| `lesson-9559d7a3e16e` | Thai voice cloning — bench + blind listen | `source-gone:docs/tools/ai-workforce-eval.md` |

## Review queue (lessons-due)

due **87** · upcoming **13** · learned 0

| due | slug | topic |
|---|---|---|
| 2026-10-27 | `lesson-9559d7a3e16e` | Thai voice cloning — bench + blind listen |
| 2026-10-28 | `lesson-dffe269a27c5` | ada-nest-hardware |
| 2026-10-28 | `lesson-bab732f3fa0b` | vps-fleet-placement-and-providers |
| 2026-10-28 | `lesson-6f7d676186f6` | clevious-vs-contabo-vps |
| 2026-10-28 | `lesson-d495eb326d86` | cloning my voice — corpus, lanes, and gates |
| 2026-10-29 | `lesson-7988868998ad` | 3d-models-from-map-data |
| 2026-10-29 | `lesson-9bc73936498c` | Ada Nest — NCM report |
| 2026-10-29 | `lesson-48e4a2fba780` | rclone vs Drive REST API — storage transport choice |
| 2026-10-29 | `lesson-c0dba8521398` | ada-nest-video |
| 2026-10-29 | `lesson-feaeaddd9feb` | rogue DHCP server hunt on LAN |
| 2026-10-30 | `lesson-fca335970c52` | ai-ide-surfaces |
| 2026-10-30 | `lesson-af0d0f5afc28` | trade-gold-thb |
| 2026-10-30 | `lesson-7a6008c91bfd` | trade-signals-backtest |
| 2026-10-30 | `lesson-31699555790b` | trade-data-sources |
| 2026-10-30 | `lesson-9f0e2e9c9fc3` | trade-architecture |
| 2026-10-30 | `lesson-f429ea4f886c` | trade-map |
| 2026-10-30 | `lesson-e997ed032520` | platform-nodebb-vs-wordpress |
| 2026-10-30 | `lesson-1fa6858c7a4d` | AI short-documentary pipeline — idea to final cut |
| 2026-10-30 | `lesson-2d0b2c9e8b5b` | ai-workforce-eval |
| 2026-10-30 | `lesson-601ae55c3bba` | ada-nest-tts-eval |
| 2026-10-30 | `lesson-0e26056ed2dd` | ada-nest-iphone-webgpu |
| 2026-10-30 | `lesson-30dfafda7e23` | chaba-line-architecture |
| 2026-10-30 | `lesson-9091f396bb74` | education-manager-benchmark |
| 2026-10-31 | `lesson-ff5781755354` | ada-nest 2026-10-23/24 wrap — the distributed factory ledger |
| 2026-10-31 | `lesson-1f77c851401e` | lesson-polish-procedure |
| 2026-10-31 | `lesson-b45ff3156418` | LLM caching for agent loops — what helps, what doesn't |
| 2026-10-31 | `lesson-03b1c122702c` | ai-lane-delegation |
| 2026-10-31 | `lesson-c21650c0efda` | claude-fable-5-1 |
| 2026-10-31 | `lesson-373f8c0c816e` | Jev for coding — the verifier/judge layer |
| 2026-10-31 | `lesson-0fc3f17762aa` | ai-lane-delegation-procedure |
| 2026-10-31 | `lesson-299755d6d6fa` | ada-nest doc-pilot rough cut v1 retrospective |
| 2026-10-31 | `lesson-95610f8e4c00` | ada-nest doc-pilot v2 follow-up |
| 2026-10-31 | `lesson-7f41f956e119` | voice-600ms-turn-taking |
| 2026-10-31 | `lesson-78d39e02d2fd` | local-voice-full-landscape |
| 2026-10-31 | `lesson-f718fee5f04a` | local-voice-assistants |
| 2026-10-31 | `lesson-e0afa84ce953` | t1-breakthrough-paid-lane |
| 2026-10-31 | `lesson-f68da2aab485` | speed-probe-lesson |
| 2026-10-31 | `lesson-df2515c1a5fd` | speed-probe |
| 2026-10-31 | `lesson-b41cf57e2899` | cheap-agent-cascade |
| 2026-10-31 | `lesson-263eef1b54f3` | pattern-match-coding |
| 2026-10-31 | `lesson-99edeab4a986` | ada-nest drive-store design |
| 2026-11-01 | `lesson-8afd171c8dd5` | groq-free-tier-fit |
| 2026-11-01 | `lesson-792a931a869d` | Using free Gemini from anywhere |
| 2026-11-01 | `lesson-173c159f44a3` | Omen storage repartition: capacity gains, rollback risk, and |
| 2026-11-01 | `lesson-dd11e3146f15` | node-red-devnest-visual-map |
| 2026-11-01 | `lesson-00750611bace` | devnest-host-assessment |
| 2026-11-01 | `lesson-8d451125b029` | devnest-devin-replay-benchmark |
| 2026-11-01 | `lesson-b22f053b4f18` | Gaussian splatting for Ada Nest video generation |
| 2026-11-01 | `lesson-1e4c0dfd3d5c` | devnest-opencode-web-sample |
| 2026-11-01 | `lesson-33e213efcf13` | self-hosted-llm-inference-homelab |
| 2026-11-02 | `lesson-dd409f633687` | KK to DevNest short-video project procedure |
| 2026-11-02 | `lesson-cec1225f6869` | DevNest voice readiness and Telegram group policy |
| 2026-11-02 | `lesson-5fcc4a0a6015` | devnest-layered-reports |
| 2026-11-02 | `lesson-fa3704d7af02` | devnest-news-watch-procedure |
| 2026-11-02 | `lesson-d5f4ea8e2f2d` | devnest-continuous-improvement-standard |
| 2026-11-02 | `lesson-8633440a0c45` | ada-nest-golden-hour-catch-review-cut |
| 2026-11-02 | `lesson-57b4db08c3a2` | ada-nest-golden-hour-catch |
| 2026-11-02 | `lesson-b8e17de59152` | mcp-fleet-audit-procedure |
| 2026-11-02 | `lesson-fb34c14f3a28` | DevNest performance, caching, tokenization, and parallel res |
| 2026-11-02 | `lesson-384a0f4fe5f6` | AI video quality architecture: story, assets, controls, scen |
| 2026-11-02 | `lesson-b15cd9f285f6` | AI model efficiency and morning news procedure |
| 2026-11-02 | `lesson-8a595342ffa9` | Recursive Flint for Chaba agent cascades |
| 2026-11-02 | `lesson-1e0a833ba9a6` | colab-gpu-worker |
| 2026-11-03 | `lesson-7d5485d750c0` | OpenCode as a DevNest coding lane |
| 2026-11-03 | `lesson-b1ae05d0856f` | Jack's isolated Podman OpenCode IDE |
| 2026-11-03 | `lesson-8102ea768518` | github-pages-as-news-publishing-system |
| 2026-11-03 | `lesson-91c9501b4ba5` | OpenCode web access and Cline test lane |
| 2026-11-03 | `lesson-bf6ce090216d` | Cline Kanban vs WordPress board apps |
| 2026-11-03 | `lesson-395598f2d76d` | SSOT and WordPress lesson CPT relationship |
| 2026-11-04 | `lesson-2f962413593c` | NCM plus JEV plus Nest benchmark |
| 2026-11-04 | `lesson-cfe5df8fea0c` | kk-video-page-selection-render-gate |
| 2026-11-04 | `lesson-7512e0146ad5` | OpenCode for bounded standard procedures |
| 2026-11-04 | `lesson-549066365c71` | Telegram and LINE messenger control planes |
| 2026-11-04 | `lesson-a6431bf5ce42` | mcp-structured-files-tools |
| 2026-11-05 | `lesson-af5f57a1b73b` | devnest-model-cache |
| 2026-11-06 | `lesson-91d988129256` | devnest-kk-mac-overnight-fallback |
| 2026-11-06 | `lesson-0dbbc42cf1d1` | kk-mac-ollama-lane |
| 2026-11-06 | `lesson-f16f13e54382` | Sacred Father storyboard and story flow |
| 2026-11-06 | `lesson-f3fb77621c5a` | jack-llm-stack-agent-evaluation |
| 2026-11-06 | `lesson-917eb0e3a423` | Using Ada as a development control plane with Node-RED, Open |
| 2026-11-06 | `lesson-3374bd94986e` | devnest-capacity-aware-dispatch |
| 2026-11-06 | `lesson-ad209dd0ef19` | jevteam-jevnest-kk-mac-capacity-procedure |
| 2026-11-06 | `lesson-75f15ceb5c18` | Gaussian splat training on KK Mac Apple Silicon |
| 2026-11-06 | `lesson-1fcb6a9bee5d` | repo-choice-decision-policy |
| 2026-11-07 | `lesson-f9068ebe2181` | KK-Mac local inference for household bots |
| 2026-11-07 | `lesson-e3ca7f942dc9` | jevnest-kk-mac-capacity-procedure |
| 2026-11-07 | `lesson-4375871f0c42` | Chaba Colab Pro GPU setup — NCM & batch jobs |

## Intentional no_th exceptions

**10** exempt (9 would otherwise flag R5)

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
| `lesson-00750611bace` | devnest-host-assessment | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-03b1c122702c` | ai-lane-delegation | spaced review due 2026-10-31 — Tony's review queue |
| `lesson-0dbbc42cf1d1` | kk-mac-ollama-lane | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-0e26056ed2dd` | ada-nest-iphone-webgpu | referenced source doc gone — re-point the lesson or commit the doc [source-gone:apps/webgpu-bench/job.json]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-30 — Tony's review queue |
| `lesson-0fc3f17762aa` | ai-lane-delegation-procedure | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-173c159f44a3` | Omen storage repartition: capacity gains, rol | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-1e0a833ba9a6` | colab-gpu-worker | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-11-02 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-1e4c0dfd3d5c` | devnest-opencode-web-sample | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-1f77c851401e` | lesson-polish-procedure | spaced review due 2026-10-31 — Tony's review queue |
| `lesson-1fa6858c7a4d` | AI short-documentary pipeline — idea to final | spaced review due 2026-10-30 — Tony's review queue |
| `lesson-1fcb6a9bee5d` | repo-choice-decision-policy | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-263eef1b54f3` | pattern-match-coding | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-299755d6d6fa` | ada-nest doc-pilot rough cut v1 retrospective | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-2d0b2c9e8b5b` | ai-workforce-eval | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-30 — Tony's review queue |
| `lesson-2f962413593c` | NCM plus JEV plus Nest benchmark | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/kb/ncm-jev-nest-exploration-procedure.md]<br>spaced review due 2026-11-04 — Tony's review queue |
| `lesson-30dfafda7e23` | chaba-line-architecture | spaced review due 2026-10-30 — Tony's review queue |
| `lesson-31699555790b` | trade-data-sources | spaced review due 2026-10-30 — Tony's review queue |
| `lesson-3374bd94986e` | devnest-capacity-aware-dispatch | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-33e213efcf13` | self-hosted-llm-inference-homelab | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/function-calling.md]<br>spaced review due 2026-11-01 — Tony's review queue |
| `lesson-373f8c0c816e` | Jev for coding — the verifier/judge layer | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-37b6ef0a2561` | Kornia for Gaussian splat capture evaluation | referenced source doc gone — re-point the lesson or commit the doc [source-gone:mcp-servers/mcp-kornia/server.py]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:scripts/gs/image_set_eval.py] |
| `lesson-384a0f4fe5f6` | AI video quality architecture: story, assets, | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-395598f2d76d` | SSOT and WordPress lesson CPT relationship | spaced review due 2026-11-03 — Tony's review queue |
| `lesson-4375871f0c42` | Chaba Colab Pro GPU setup — NCM & batch jobs | spaced review due 2026-11-07 — Tony's review queue |
| `lesson-48e4a2fba780` | rclone vs Drive REST API — storage transport  | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-29 — Tony's review queue |
| `lesson-549066365c71` | Telegram and LINE messenger control planes | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/ssot/apps/ssot.messaging-lanes.yml]<br>spaced review due 2026-11-04 — Tony's review queue |
| `lesson-57b4db08c3a2` | ada-nest-golden-hour-catch | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-5fcc4a0a6015` | devnest-layered-reports | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-601ae55c3bba` | ada-nest-tts-eval | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-30 — Tony's review queue |
| `lesson-6f7d676186f6` | clevious-vs-contabo-vps | spaced review due 2026-10-28 — Tony's review queue |
| `lesson-7512e0146ad5` | OpenCode for bounded standard procedures | spaced review due 2026-11-04 — Tony's review queue |
| `lesson-75f15ceb5c18` | Gaussian splat training on KK Mac Apple Silic | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-78d39e02d2fd` | local-voice-full-landscape | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-792a931a869d` | Using free Gemini from anywhere | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-7988868998ad` | 3d-models-from-map-data | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/3d-models-from-map-data.md]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/agentic-ai-coding-ides.md]<br>spaced review due 2026-10-29 — Tony's review queue |
| `lesson-7a6008c91bfd` | trade-signals-backtest | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-30 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-7d5485d750c0` | OpenCode as a DevNest coding lane | spaced review due 2026-11-03 — Tony's review queue |
| `lesson-7f41f956e119` | voice-600ms-turn-taking | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-8102ea768518` | github-pages-as-news-publishing-system | spaced review due 2026-11-03 — Tony's review queue |
| `lesson-8633440a0c45` | ada-nest-golden-hour-catch-review-cut | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-8a595342ffa9` | Recursive Flint for Chaba agent cascades | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-8afd171c8dd5` | groq-free-tier-fit | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-8d451125b029` | devnest-devin-replay-benchmark | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-9091f396bb74` | education-manager-benchmark | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-30 — Tony's review queue |
| `lesson-917eb0e3a423` | Using Ada as a development control plane with | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-91c9501b4ba5` | OpenCode web access and Cline test lane | spaced review due 2026-11-03 — Tony's review queue |
| `lesson-91d988129256` | devnest-kk-mac-overnight-fallback | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-9559d7a3e16e` | Thai voice cloning — bench + blind listen | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-27 — Tony's review queue |
| `lesson-95610f8e4c00` | ada-nest doc-pilot v2 follow-up | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-99edeab4a986` | ada-nest drive-store design | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-9bc73936498c` | Ada Nest — NCM report | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/kb/ncm-jev-nest-exploration-procedure.md]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-29 — Tony's review queue |
| `lesson-9f0e2e9c9fc3` | trade-architecture | spaced review due 2026-10-30 — Tony's review queue |
| `lesson-a6431bf5ce42` | mcp-structured-files-tools | spaced review due 2026-11-04 — Tony's review queue |
| `lesson-ad209dd0ef19` | jevteam-jevnest-kk-mac-capacity-procedure | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-af0d0f5afc28` | trade-gold-thb | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-30 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-af5f57a1b73b` | devnest-model-cache | spaced review due 2026-11-05 — Tony's review queue |
| `lesson-b15cd9f285f6` | AI model efficiency and morning news procedur | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/hub/release_notes.html]<br>referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/kb/ai-news-to-education-procedure.md]<br>spaced review due 2026-11-02 — Tony's review queue |
| `lesson-b1ae05d0856f` | Jack's isolated Podman OpenCode IDE | spaced review due 2026-11-03 — Tony's review queue |
| `lesson-b22f053b4f18` | Gaussian splatting for Ada Nest video generat | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-b41cf57e2899` | cheap-agent-cascade | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-b45ff3156418` | LLM caching for agent loops — what helps, wha | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-b8e17de59152` | mcp-fleet-audit-procedure | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/mcp-fleet-audit.md]<br>spaced review due 2026-11-02 — Tony's review queue |
| `lesson-bab732f3fa0b` | vps-fleet-placement-and-providers | spaced review due 2026-10-28 — Tony's review queue |
| `lesson-bf6ce090216d` | Cline Kanban vs WordPress board apps | referenced source doc gone — re-point the lesson or commit the doc [source-gone:apps/board/index.html]<br>spaced review due 2026-11-03 — Tony's review queue |
| `lesson-c0dba8521398` | ada-nest-video | spaced review due 2026-10-29 — Tony's review queue |
| `lesson-c21650c0efda` | claude-fable-5-1 | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |
| `lesson-cec1225f6869` | DevNest voice readiness and Telegram group po | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/devnest-continuous-improvement-standard.md]<br>spaced review due 2026-11-02 — Tony's review queue |
| `lesson-cfe5df8fea0c` | kk-video-page-selection-render-gate | spaced review due 2026-11-04 — Tony's review queue |
| `lesson-d495eb326d86` | cloning my voice — corpus, lanes, and gates | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-28 — Tony's review queue |
| `lesson-d5f4ea8e2f2d` | devnest-continuous-improvement-standard | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/devnest-continuous-improvement-standard.md]<br>spaced review due 2026-11-02 — Tony's review queue |
| `lesson-dd11e3146f15` | node-red-devnest-visual-map | spaced review due 2026-11-01 — Tony's review queue |
| `lesson-dd409f633687` | KK to DevNest short-video project procedure | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-df2515c1a5fd` | speed-probe | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-dffe269a27c5` | ada-nest-hardware | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-28 — Tony's review queue |
| `lesson-e0afa84ce953` | t1-breakthrough-paid-lane | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-e3ca7f942dc9` | jevnest-kk-mac-capacity-procedure | spaced review due 2026-11-07 — Tony's review queue |
| `lesson-e997ed032520` | platform-nodebb-vs-wordpress | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/agentic-ai-coding-ides.md]<br>spaced review due 2026-10-30 — Tony's review queue |
| `lesson-f16f13e54382` | Sacred Father storyboard and story flow | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-f3fb77621c5a` | jack-llm-stack-agent-evaluation | spaced review due 2026-11-06 — Tony's review queue |
| `lesson-f429ea4f886c` | trade-map | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-30 — Tony's review queue |
| `lesson-f68da2aab485` | speed-probe-lesson | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-f718fee5f04a` | local-voice-assistants | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-31 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-f9068ebe2181` | KK-Mac local inference for household bots | spaced review due 2026-11-07 — Tony's review queue |
| `lesson-fa3704d7af02` | devnest-news-watch-procedure | spaced review due 2026-11-02 — Tony's review queue |
| `lesson-fb34c14f3a28` | DevNest performance, caching, tokenization, a | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/inference-provider-market.md]<br>spaced review due 2026-11-02 — Tony's review queue |
| `lesson-fca335970c52` | ai-ide-surfaces | content fetch failed — check the /lesson door [get-failed:HTTP Error 502: Bad Gateway]<br>spaced review due 2026-10-30 — Tony's review queue<br>thin body — junk-delete candidate; deletion is human-gated (KNB-0830) [R2:thin(0ch)] |
| `lesson-feaeaddd9feb` | rogue DHCP server hunt on LAN | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/devin-macbook-ipv4-outage.md]<br>spaced review due 2026-10-29 — Tony's review queue |
| `lesson-ff5781755354` | ada-nest 2026-10-23/24 wrap — the distributed | referenced source doc gone — re-point the lesson or commit the doc [source-gone:docs/tools/ai-workforce-eval.md]<br>spaced review due 2026-10-31 — Tony's review queue |

## Verify

status **pass** · digest `289fcfba2bb21f71`
- ✓ total_matches_list rows=100 list=100 count=100
- ✓ buckets_sum 87+13+0
- ✓ due_rows_match 
- ✓ dimensions_sum 
- ✓ flag_counts_match 
- ✓ drift_counts_match 
- ✓ exempt_subset exempt=10

**HOLDS** (notify suppressed):
- get_failures=11 — degraded fetch; audit only

## Refs

- card: `education-maintenance-consolidated-report` · education-due page: private WP page slug education-due (post 354)
- member index: https://boards.surf-thailand.com/wp/lesson/
- runbook: `docs/ssot/jobs/education/2026-10-27-education-maintenance-report.yml` · exceptions: `scripts/lesson-thai-exceptions.yml`
- artifacts: `latest.json`/`latest.md` + `history.jsonl` in this dir · generated 2026-11-07T04:24:38+00:00
