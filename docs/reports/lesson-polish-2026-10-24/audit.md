# lesson-polish audit — 2026-10-24 (dispatch: pack-lesson-polish-prep-query)

Policy dimensions checked per WP `lesson` CPT post: **content** (non-thin, not junk),
**level** (intro|working|deep), **source** (chat|voice|link), **next_review** (present, not overdue),
**thai** (`<h3>ไทย</h3>` section or Thai-native body), **hub_link** (declared family members
reference hub/sibling in EN body), **split_rule** (verdict/decision content carries an SSOT/KB pointer).

## Score

| phase | lessons | clean | content | level | source | next_review | thai | hub_link | split_rule | score |
|---|---|---|---|---|---|---|---|---|---|---|
| before | 68 | 41 | 66 | 68 | 68 | 68 | 48 | 57 | 68 | 0.9307 |
| final | 68 | 66 | 66 | 68 | 68 | 68 | 66 | 68 | 68 | 0.9916 |

Score = passed checks / (lessons × 7 dimensions). `final` = after this run's fixes.

## Per-post fixes applied this run (via board-api /lesson upsert)

| slug | topic | fix |
|---|---|---|
| lesson-1f77c851401e | lesson-polish-procedure | Thai section regenerated |
| lesson-b45ff3156418 | LLM caching for agent loops — what helps, what doesn | Thai section regenerated |
| lesson-c21650c0efda | claude-fable-5-1 | Thai section regenerated |
| lesson-373f8c0c816e | Jev for coding — the verifier/judge layer | Thai section regenerated |
| lesson-0fc3f17762aa | ai-lane-delegation-procedure | Thai section regenerated |
| lesson-7f41f956e119 | voice-600ms-turn-taking | Thai section regenerated |
| lesson-78d39e02d2fd | local-voice-full-landscape | Thai section regenerated |
| lesson-f718fee5f04a | local-voice-assistants | Thai section regenerated |
| lesson-e0afa84ce953 | t1-breakthrough-paid-lane | Thai section regenerated |
| lesson-263eef1b54f3 | pattern-match-coding | Thai section regenerated |
| lesson-1e0a833ba9a6 | colab-gpu-worker | Thai section regenerated |
| lesson-7988868998ad | 3d-models-from-map-data | Thai section regenerated |
| lesson-feaeaddd9feb | rogue DHCP server hunt on LAN | Thai section regenerated |
| lesson-9109800579c2 | Grok (xAI) vs Gemini for our lanes — pricing cheat-s | Thai section regenerated |
| lesson-ff5781755354 | ada-nest 2026-10-23/24 wrap — the distributed factor | family line → ada-nest-map hub + Thai regen |
| lesson-299755d6d6fa | ada-nest doc-pilot rough cut v1 retrospective | family line → ada-nest-map hub + Thai regen |
| lesson-95610f8e4c00 | ada-nest doc-pilot v2 follow-up | family line → ada-nest-map hub + Thai regen |
| lesson-99edeab4a986 | ada-nest drive-store design | family line → ada-nest-map hub + Thai regen |
| lesson-601ae55c3bba | ada-nest-tts-eval | family line → ada-nest-map hub + Thai regen |
| lesson-0e26056ed2dd | ada-nest-iphone-webgpu | family line → ada-nest-map hub + Thai regen |
| lesson-dffe269a27c5 | ada-nest-hardware | family line → ada-nest-map hub + Thai preserved (regen failed 3× — old Thai kept via no_th; EN pointer line untranslated) |
| lesson-af0d0f5afc28 | trade-gold-thb | family line → trade-map hub + Thai regen |
| lesson-7a6008c91bfd | trade-signals-backtest | family line → trade-map hub + Thai regen |
| lesson-31699555790b | trade-data-sources | family line → trade-map hub + Thai regen |
| lesson-9f0e2e9c9fc3 | trade-architecture | family line → trade-map hub + Thai regen |
| lesson-ba44b7fd57e7 | Ada Nest — architecture map | hub inventory: added 6 missing members (tts-eval, iphone-webgpu, drive-store, doc-pilot retro/v2, 10-23/24 wrap) + Thai regen |

## Still failing

| slug | topic | fails | blocker |
|---|---|---|---|
| lesson-df2515c1a5fd | speed-probe | content, thai | junk test posts — door `op:delete` had a URL-encoding bug (`?force=true` inside rest_route → WP `rest_no_route`); fixed in `scripts/board/board-api.py` (this branch), delete unblocks when the fix deploys to idc03 |
| lesson-f68da2aab485 | speed-probe-lesson | content, thai | junk test posts — door `op:delete` had a URL-encoding bug (`?force=true` inside rest_route → WP `rest_no_route`); fixed in `scripts/board/board-api.py` (this branch), delete unblocks when the fix deploys to idc03 |

## Notes for human review

- All writes were additive: appended/translated sections, one-line family pointers, hub inventory rows. No body content was rewritten or removed.
- `ada-nest-hardware` Thai regen failed 3× on gemini (largest lesson, ~8k EN chars); its previous Thai section was preserved verbatim via `no_th` — the two new EN lines (family pointer + re-attached SSOT/KB pointer) are not yet translated.
- During fixes, 4 lessons' `SSOT/KB pointer:` blocks were found appended AFTER the Thai section (earlier polish pass tail-appends); they were re-attached inside the EN body so the structure is canonical (EN → `<hr>` → Thai).
- Policy gap surfaced: the door does not persist a `no_th` opt-out flag in lesson meta, so the audit cannot distinguish deliberate skip from missing translation. This run treats absent-Thai as non-compliant (18 lessons re-filed).
- One nit left: `ada-nest-video` has meta status `active` (norm is `open`); status is sticky on re-file and the door offers no override — cosmetic only.
