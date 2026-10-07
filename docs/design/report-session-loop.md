# Report → Devin session loop — design

**Status:** designed (kanban: `report-session-loop`, umbrella — e2e tracking)
**Ask (2026-10-07, Tony):** from a CMS report page, kick off a work session
that tracks itself on a card, keeps the report updated, and lets Tony follow
up via the card AND via Ada — including "ask Ada's opinion", which must land
on the card for Devin to weigh alongside Tony's.

Four deliverables: **SPAWN** (button → card → dispatch), **LINK** (card ↔
report stay in sync by convention), **ADA-IN-THE-LOOP** (Ada's opinion lands
in the session thread), **TRAIN+BENCH** (live scenario + bench domain).

## 0. What already exists

| Piece | Where | State |
|---|---|---|
| `POST /card` create | `scripts/board/board-api.py` (`do_create`) | live — but accepts only `{id?, title, column, note, help, text}` — **no spec/action/report** |
| `POST /action do=queue` | board-api | live — armed cards dispatch via kanban-dispatch |
| `POST /comment` (from=ada ok) | board-api | live — `ada` whitelisted actor |
| `POST /respond` → `$TASK_DIR/answers.jsonl` | board-api `deliver_answer` | live — board-answer-live-session |
| Dispatch rails | `kanban-dispatch.py` `TASK_RAILS` | live — appended to every queued card's task |
| Ada board tools | ada-pi `tools.d/ada_board_write.py` | live — comment/respond/read/create (request gap noted) |
| Ada CMS tools | ada-pi `cms_get_page`/`cms_note_update`/`cms_publish_page` | live |
| `devin_dispatch` | ada-pi tool → `devin-dispatch start` | live — voice spawn precedent |
| CMS viewer | ada-pi `pwa/cms/`, `/api/cms/*`, `/cms/` edge | live — api_key auth (`cms-viewer` shared key), iframed in `chaba-admin/chaba-cms*` |
| Report standard | `docs/ssot/apps/ssot.apps.cms-reports.yml` | live — meta_contract incl. `timeline`, writer_contract, `<!-- X:auto -->` managed blocks |
| CMS writes from repo | `scripts/ada/kanban-cms.py`, `cms-report-reflect.py`, `scripts/lib/cms_index.py` | live — MDDB `POST /v1/add` into `ada-cms-pages` + index regen |
| Ada participation tiers | `docs/ssot/infrastructure/ssot.ada-participation.yml` | live — T1 comment is the right tier for opinions |

Nothing about the loop requires a new *channel* — it's three small
extensions on existing ones plus conventions.

## 1. SPAWN — "Start session" on a CMS report page

**Flow:** CMS page → button → ada-pi backend route → board-api → card
{title, spec, report:<slug>, action:dispatch queued} → kanban-dispatch
claims it like any queued card. Same effect as Ada saying "start a Devin
session on this report" via `devin_dispatch`, but card-first so the board
tracks it.

### 1a. board-api `POST /card` extension (chaba)

Extend `do_create` to accept the fields an armed card needs:

- `spec` (str) — if absent and `report` is given, compose from a
  server-side `REPORT_SPAWN_TEMPLATE` (keeps every spawn — UI, Ada,
  curl — producing identical cards).
- `report` (slug, `[a-z0-9-]{1,80}`) — stored verbatim on the card.
- `action` — `{type: dispatch, repo: chaba}` only; `repo` validated
  against the dispatch whitelist (dispatch_repos knows repos.conf).
- `queue: true` — sets `action.status: queued` inside the same locked
  write (no create+queue two-call race).
- `brief`, `priority`, `tags`, `program`, `blocked_by` — optional
  pass-throughs (brief is now required convention for new cards).
- `on_exists`: `error` (default, today's behavior) | `queue` — a second
  click on the same report re-queues the existing card instead of
  duplicating; if it's already running/queued, return its status so the
  UI can say "session already running → card".

Generated spec template (server-side):

```
Work on the CMS report '<slug>' — "<page title>".
Report: ada-cms-pages/<slug> · https://idc03.taila0626a.ts.net/cms/?page=<slug>
This card is report-linked (report: <slug>) — read the report first,
keep it updated per the report rails below, and post progress to this card.
```

Plus the standard `TASK_RAILS` (kanban-dispatch appends those).

### 1b. CMS affordance (ada-pi)

- `pwa/cms/index.html` — a "▶ Devin session" button in the report-page
  toolbar (next to Regenerate). Every CMS page gets it; report pages are
  the intended target but it degrades fine on any slug.
- New backend route `POST /api/cms/spawn {slug}` in `pwa_server.py`:
  reads the page (title → card title), calls board-api
  `POST /card {title, report: slug, queue: true, on_exists: queue}`
  reusing the same board-api client path `ada_board_write` uses, returns
  `{card_id, status, board_url}`; UI toasts and links to
  `https://tony-ha.surf-thailand.com/chaba-admin/board` (or `/apps/board/`).
- **Auth — the one real decision:** the shared `cms-viewer` key is a
  read key embedded in iframes/QR links — it must NOT gain dispatch
  power. Reuse the key `apps` metadata (voice|chat|view) with a new
  `dispatch` capability: `POST /api/cms/spawn` rejects keys whose `apps`
  lacks it. Tony's devices re-issue their CMS key with `apps:
  [view, dispatch]` via the existing pair flow; `chaba-admin` is already
  `require_admin` so carrying a dispatch-capable key there is fine.

## 2. LINK — `report:` field + session rails

### 2a. Card schema

`report: <cms-slug>` — optional field in `ssot.kanban.yml` card_schema.
`render-board.py` shows a small 📄 badge on the card linking to the
tailnet CMS URL (`/cms/?page=<slug>`; browsers with a stored key open
straight in — never put keys in repo data).

### 2b. Dispatch rails

`kanban-dispatch.py`: when `card.report` is set, append `REPORT_RAILS`
after `TASK_RAILS`:

```
This card is report-linked: ada-cms-pages/<slug>.
- Read the report FIRST: python3 scripts/ada/cms-report-note.py <slug> --read
- As you work, mirror progress into the report's session log:
    python3 scripts/ada/cms-report-note.py <slug> --note "<what changed>"
  (appends meta.timeline + the <!-- session-log:auto --> managed block;
   merges meta per the writer contract — never bare-replace a page)
- Before finishing: the report must reflect the outcome. The report is
  the long-lived artifact; this card is the tracking surface.
```

### 2c. `scripts/ada/cms-report-note.py` (new helper, chaba)

Thin MDDB writer so sessions don't hand-roll page edits:

- `--read` — print title/meta/body (what the session reads first).
- `--note "<text>"` — GET page, append `* {ts} — {text} (session
  <task_id>)` to `<!-- session-log:auto -->` block (create before the
  provenance footer if absent), append `meta.timeline`, merge old meta
  per writer_contract, `POST /v1/add`, regen `reports-index` via
  `scripts/lib/cms_index.py`, stamp `updated`.
- `--section` (later) — replace a named managed block for sessions that
  regenerate real content.

Report↔card sync is by *convention* (rails), verified by the session's
final comms naming what it changed in the report — matching how every
other rail is enforced today. Stricter verification can come later via
`expected_goals` (`command cms-report-note.py <slug> --fresh 24h`).

## 3. ADA-IN-THE-LOOP — `[opinion]` comms that reach running sessions

**Flow:** Tony says "Ada, what's your take on the flood report?" →
Ada `cms_get_page(<slug>)` (must read before opining — evidence_rule) →
finds the card carrying `report: <slug>` via `ada_board_write
action=read` (board payload carries the field) → `action=comment` with
`text: "[opinion] <assessment> — read <slug> @<updated>; basis: …"` →
board-api delivers it into the running session. Tony's `/respond`
answers land in the same file — one thread, both voices.

### 3a. Comms → session delivery (chaba)

Today only `/respond` reaches `answers.jsonl`. Extend: after a `/comment`
lands on a card whose `action.status == 'running'` **and** `from ∈
{ada, tony}`, append `{at, card, from, kind: "comment", text}` to the
task's `answers.jsonl` — same local-write/ssh machinery as
`deliver_answer` (refactor into a shared `_deliver_to_session(card,
record)`).

Filters: `devin`/`chaba` comments are excluded — a session must not get
its own progress notes echoed back, and chaba system notes are noise.
Best-effort, never blocks the write — same contract as `deliver_answer`.

### 3b. Ada opinion path (ada-pi)

Instructions stanza (CMS/board block in realtime_provider / instructions
file): when asked for an opinion on a report —

1. `cms_get_page(slug)` — read before opining (educate_standard:
   evidence inline, `read <slug> @<updated>` cited).
2. Locate the thread: `ada_board_write action=read` → card where
   `report == slug`, prefer not-done. None → answer aloud + offer to
   file the card (`action=create` is live, T1-legal). Several → pick the
   open one, or ask.
3. `ada_board_write action=comment`, text prefixed `[opinion]`.
4. Also speak the summary — voice-first stays.

`[opinion]` is a comms-tag convention, not schema: sessions treat it as
advisory review input to weigh alongside Tony's direction; renderers may
style it later. T1 covers it — no tier change needed.

### 3c. Session side

`TASK_RAILS` gains one line: answers.jsonl may carry `kind: "comment"`
lines — Tony's comments and Ada's `[opinion]`-tagged takes are review
input, not instructions; `request_id`/`answer` lines remain the
authoritative answer channel. `GET /cards` comms stay the fallback read.

## 4. TRAIN+BENCH

### 4a. Live scenario `report_opinion_loop` (ada-pi `tests/scenarios-live/`)

Staged in this repo at
`stacks/services/ada-scenario-runner/scenarios-staging/report_opinion_loop.yaml`
(cms_first_answer.yaml precedent — install step copies it into ada-pi).

- Probe report: `dev-kanban` (always exists, regenerated by kanban-sync)
  — no seeding needed. Probe card: `scenario-report-opinion`
  (`report: dev-kanban`) committed alongside as the comms sink —
  scenario `[opinion]` posts accumulate there, visibly a fixture.
- Asserts: opinion ask → `cms_get_page` fires (read-before-opine) →
  `ada_board_write` fires (opinion posted); response non-empty.
- Card-side verification (comms landed on probe card) is manual/`GET
  /cards` — the scenario runner asserts tool calls, not board state.
- Tier: `smoke` — same cadence as `education_correction` so a regression
  in the loop shows in the hourly bench.

### 4b. Bench domain `report-opinion` (ssot.nest-bench.yml)

New domain, `status: spec` — corpus accrues as real `[opinion]` comms
land on report-linked cards (opinion text + the report it read + whether
Tony/the session acted on it = the label). Metrics: evidence_grounding
(cited the read), actionability, appropriate_deference. orch-bench/nest
topologies for the opinion-forming step wait on that corpus — per the
card, and per the domain rule "a scorer with no corpus is dead code".

## 5. Sub-cards (implementation split — repo boundaries force it)

Dispatch sessions get one worktree of one repo; cross-repo deliverables
split. All under umbrella `report-session-loop`, tagged
`report-session-loop`, `program: ada-tools`.

| card | repo | deliverable | blocked_by |
|---|---|---|---|
| `report-loop-spawn-api` | chaba | §1a — /card fields + queue + on_exists + selftest/tests + write_path doc | — |
| `report-loop-spawn-ui` | ada-pi | §1b — CMS button + /api/cms/spawn + `dispatch` key capability | report-loop-spawn-api |
| `report-loop-session-rails` | chaba | §2 — REPORT_RAILS + cms-report-note.py + render badge | — |
| `report-loop-comment-delivery` | chaba | §3a — /comment → answers.jsonl for running cards + rails line | — |
| `report-loop-ada-opinion` | ada-pi | §3b — opinion instructions + card-by-report lookup | report-loop-comment-delivery |
| `report-loop-bench` | ada-pi | §4a — install staged scenario + probe wiring; §4b corpus starts accruing | report-loop-ada-opinion |

Order matters only as listed; 1a/2/3a are independent and parallel-safe
(different files: board-api.py, kanban-dispatch.py, render-board.py —
3a touches board-api.py too, so 1a then 3a if run serially).

## 6. Non-goals

- No card ↔ report schema-level backlink (report→card link is by the
  `report:` field + comms convention; an MDDB meta backlink is easy later).
- No Ada-initiated dispatch — spawn is Tony/UI-initiated; Ada filing a
  card via `action=create` then queueing stays T3-gated.
- No auto-refresh of the report on a timer — sessions refresh it as part
  of the work; generators keep their own schedules.
- `kanban_opinion` as a separate tool — rejected: `action=comment` with
  the `[opinion]` tag is the same channel, already whitelisted, already
  audited. New tools are for new capabilities, not new labels.
