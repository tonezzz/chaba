# Dispatch outcome — pack lesson-polish (lesson-polish-nest-pack)

## What was done

Ran the lesson-polish pack end-to-end against the WP `lesson` CPT via the
board-api `/lesson` door (no WP creds held):

1. **Prep/query** — `op:list` + `op:get` pulled all **68 lessons** (full
   content + meta) to a local snapshot.
2. **Agent classify** — each post scored on the 7 policy dimensions:
   content (non-thin/junk), level, source, next_review (present & not
   overdue), Thai (`<h3>ไทย</h3>` section or Thai-native body), hub_link
   (declared-family members reference their hub/sibling in the EN body),
   split_rule (verdict/decision content carries an SSOT/KB pointer).
3. **Fixes via `/lesson` upsert** — 26 upserts, all additive:
   - 14 Thai backfills (EN verbatim re-file, door regenerated Thai).
   - 11 family-pointer lines inserted after the h2 (7 ada-nest members →
     ada-nest-map; 4 trade members → trade-map), Thai regenerated.
   - ada-nest-map hub inventory updated with 6 missing members
     (tts-eval, iphone-webgpu, drive-store, doc-pilot retro/v2, wrap).
   - 4 lessons' `SSOT/KB pointer:` blocks re-attached inside the EN body —
     an earlier pass had appended them AFTER the Thai section, and my
     Thai-strip re-file initially dropped them; caught by re-audit and
     repaired.
   - `ada-nest-hardware` Thai regen failed 3× on gemini (largest lesson);
     its old Thai section was preserved verbatim via `no_th`.

## Benchmark

Policy-compliance score (passed checks / lessons × 7 dimensions):

| phase | clean lessons | score |
|---|---|---|
| before | 41/68 | 0.9307 |
| final  | 66/68 | 0.9916 |

Per-dimension after: level 68, source 68, next_review 68, split_rule 68,
hub_link 68, thai 66, content 66 — the only remaining fails are the two
junk posts below. Human review pass rate: pending Tony (all writes were
additive; noted on card).

## Bug found + fixed (door)

`op:delete` on `/lesson` 404'd at WP with `rest_no_route`. Root cause:
`wp_api()` embeds the route inside `rest_route=`, so `?force=true` was
%-encoded into the route path — `?` must be `&`. Fixed in
`scripts/board/board-api.py` (committed on this dispatch branch). Junk
deletion (`lesson-df2515c1a5fd` 'test', `lesson-f68da2aab485` 'test lesson
write timing') unblocks when the fix deploys to idc03 — until then those
2 posts are the only non-compliant entries.

## Artifacts

- `docs/reports/lesson-polish-2026-10-24/audit.md` + `audit-{before,after,final}.json`
- `docs/ssot/jobs/education/2026-10-24-lesson-polish.yml` (trail)
- Commit `3d67312e` on `dispatch/20261024-125107-pack-lesson-polish-prep-query-`
- Card comment posted with the result.

## Follow-ups surfaced

- Door doesn't persist `no_th` opt-out in lesson meta — audit can't
  distinguish deliberate skip from missing Thai (worth a `meta.no_th`).
- `ada-nest-video` meta status `active` vs `open` norm (cosmetic; status
  is sticky on re-file, door has no override).

## Verify

`curl -sX POST https://idc03.taila0626a.ts.net:10000/lesson -d '{"op":"get","slug":"lesson-ff5781755354"}'`
— family-pointer line after the h2 + `<h3>ไทย</h3>` section present.
