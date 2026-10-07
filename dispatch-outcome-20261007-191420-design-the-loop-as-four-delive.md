# Outcome — report-session-loop design session (2026-10-07)

## What was done

Designed the report→Devin-session loop end-to-end (card `report-session-loop`,
`action.status: design`). The full design is in
`docs/design/report-session-loop.md`; the job trail is
`docs/ssot/jobs/kanban/2026-10-07-report-session-loop-design.yml`.

Key finding: every channel already exists — the loop is three small
extensions plus conventions, not new plumbing. Gaps found while surveying:

- `POST /card` can only file bare cards (title/note/help) — no
  spec/action/report, so nothing can spawn an *armed* dispatch card yet.
- The shared `cms-viewer` key is read-only — spawn needs a new `dispatch`
  capability on the key `apps` metadata.
- Only `/respond` reaches a running session (`answers.jsonl`) — comments
  don't, which is what `[opinion]` delivery extends.
- Ada has no instruction for "form an opinion on a report and post it".

## Deliverables produced

- `docs/design/report-session-loop.md` — the design (4 deliverables,
  interfaces, spawn spec template, REPORT_RAILS text, delivery filters,
  non-goals).
- SSOT updates (all additive):
  - `ssot.kanban.yml` — `report:` card field declared.
  - `ssot.nest-bench.yml` — `report-opinion` domain (status: spec; corpus
    = real `[opinion]` comms on report-linked cards).
  - `ssot.ada-participation.yml` — `t1_comment.opinion_convention`.
- Sub-cards filed (all `action.status: idle` — Start queues each;
  repo-split because dispatch sessions get one worktree):
  - `report-loop-spawn-api` (chaba) — /card fields + queue + on_exists
  - `report-loop-spawn-ui` (ada-pi) — CMS button + /api/cms/spawn +
    `dispatch` key capability — blocked_by spawn-api
  - `report-loop-session-rails` (chaba) — REPORT_RAILS +
    scripts/ada/cms-report-note.py + board report badge
  - `report-loop-comment-delivery` (chaba) — /comment → answers.jsonl
    for running cards (from ∈ {ada,tony}, kind:"comment")
  - `report-loop-ada-opinion` (ada-pi) — opinion instructions +
    card-by-report lookup — blocked_by comment-delivery
  - `report-loop-bench` (ada-pi) — install scenario, corpus accrues —
    blocked_by ada-opinion
  - `scenario-report-opinion` — probe card fixture (report: dev-kanban)
- `stacks/services/ada-scenario-runner/scenarios-staging/report_opinion_loop.yaml`
  — staged live scenario (smoke tier), per the cms_first_answer.yaml
  staging convention.

## Verification

- `node scripts/ssot-validate-all.mjs` → 1639/1639 valid, 0 errors
  (1 pre-existing-trend bloat warning on ssot.kanban.yml).
- All new/edited YAML parse clean.
- E2E proof is by construction once sub-cards run: spawn a card off a
  report page → session runs with report rails → Ada's `[opinion]` lands
  in answers.jsonl mid-run.

## Notes for the reviewer

- Sub-cards intentionally have no queued status — Tony presses ▶ Start.
  Dependency order is recorded on each card (`blocked_by` + spec).
- The `?page=` CMS deep-link param is marked "confirm during
  implementation" — the ada-pi viewer source wasn't readable from this
  worktree.
- The umbrella card stays in e2e tracking role per the task.
