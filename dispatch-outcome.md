# Dispatch outcome — 2026-10-04 (gev-map handoff + operator add-ons)

## 1. GEV map zoom (devin-handoff/gev-map)

**Root cause:** `adjust_camera_zoom` (fn `OY` in the deployed bundle) executed a
single instantaneous `camera.zoomIn/zoomOut(d)` per call — a discrete jump that
never participated in the per-tick camera-motion system (`zt` state + `x5` tick
on `viewer.clock.onTick`, which already drives once/continuous orbit, pan, tilt,
rotate, and route motions). There was no continuous-height path at all, and a
second zoom command could not accumulate onto an in-flight zoom.

**Fix (applied to `stacks/web/public/apps/gev/assets/index-D8kXv0di.js`):**
- `adjust_camera_zoom` now creates a `zt` zoom motion (`mode:"once"`, distance
  budget `remainingM`) — smooth continuous dolly instead of an instant step.
- Consecutive commands queue properly: same direction adds to `remainingM`
  (extends the zoom); opposite direction subtracts, and fully countering starts
  the new direction cleanly.
- `x5` gained `kind:"zoom"` (distance-proportional rate slow .15 / normal .4 /
  fast .85 per sec, 25 m min-target clamp, 60,000 km out cap) and `kind:"fly"`
  — flight mode: travels along heading (forward/back/left/right) while pinning
  `positionCartographic.height` to the altitude captured at start, i.e. the
  camera maintains its current height during flight.
- `move_camera` accepts `zoom` (in/out, optional `amount`) and `fly` motions;
  `fly` is blocked while tracking (follow camera owns the view); non-orbit
  motions cancel in-flight camera tweens on start.
- The shared once-mode 0.9 s timer now skips zoom/fly — they complete on their
  own budgets so a "lot" zoom isn't truncated.
- `stacks/tony-dell/gev-gemini/tools.json` updated (new motion/direction enums
  + `amount`, descriptions steer the model to fly/zoom for sustained motion).

**Verified:** `node --input-type=module --check` parses clean. NOT deployed —
the live site still serves the previous bundle; a source-level port to
`/home/tony/gods-eye-view` + rebuild is required (outside this worktree). Full
record: `docs/ssot/jobs/gev/2026-10-04-gev-map-zoom-flight.yml`.

## 2. Recent Ada sessions → new scenarios

Reviewed session summaries 2026-10-02/03 (`ada-ha-recall-summary-tony`).
Findings:
- Ada answered in **Filipino** mid English/Thai conversation (visible in the
  10-03 `education-correction` report too) → staged `language_lock` scenario.
- Multiple consecutive "didn't hear clearly" sessions on 10-03 (audio path
  issue, noted for the record).
- Flood questions WERE answered from CMS correctly (positive — matches the new
  CMS-first directive) → staged `cms_first_answer` scenario asserting
  cms_get_page/memory-search before web_search, plus save-back to CMS.

Staged (install into ada-pi `tests/scenarios-live/`):
- `stacks/services/ada-scenario-runner/scenarios-staging/cms_first_answer.yaml`
- `stacks/services/ada-scenario-runner/scenarios-staging/language_lock.yaml`

## 3. Scenario benchmark status ("cmp report" = `benchmark-cms` page)

| suite | latest | score |
|---|---|---|
| jev-decision (hourly) | 2026-10-04 08:00 | 0.61 (11/18) — flat for days |
| chaba audit | 2026-10-04 05:00 | 0.83 pass |
| casting | 2026-10-01 02:00 | **0.0 — all 30 FAIL; service outage** (`ada-scenario-casting.service` down on idc01 per chaba audit) |
| cms | 2026-09-27 | 0.9 — stale |
| reports | 2026-09-27 | 0.667 — stale |

`benchmark-cms` CMS page updated in place: staleness banner, last-run table,
cross-suite snapshot, meta-contract fields (summary/domain/fresh_for/
confidence/timeline) added. `auto-report` already reflects the casting outage.
Biggest live problem: `education-correction` still failing (incl. the Filipino
reply regression) and the casting-suite service outage on idc01.

## 4. Kanban (docs/ssot/kanban/cards/, board re-rendered — 17 cards)

- `ada-cms-first-answers` — Ada must answer from CMS/reports-index before
  searching elsewhere and save new findings back to CMS.
- `ada-report-quality` — raise Ada-made reports to the meta-contract standard
  (summary, domain, fresh_for, confidence, timeline, time-of-event, honest
  staleness); several benchmark pages currently stale.

## Files changed

- `stacks/web/public/apps/gev/assets/index-D8kXv0di.js` — zoom queue + fly mode
- `stacks/tony-dell/gev-gemini/tools.json` — move_camera/adjust_camera_zoom decls
- `docs/ssot/jobs/gev/2026-10-04-gev-map-zoom-flight.yml` — new
- `docs/ssot/kanban/cards/ada-cms-first-answers.yml`, `ada-report-quality.yml` — new
- `stacks/services/ada-scenario-runner/scenarios-staging/*.yaml` — new
- `stacks/web/public/apps/board/index.html` — re-rendered
- MDDB `ada-cms-pages/benchmark-cms` — refreshed
