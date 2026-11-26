# Design — Kanban card-cycle control pane (KNB-0229)

**Status:** design → read-only pane implemented on the Board page (v1,
2026-11-19; evidence serving + source tags, v2, same day). The design card
included no live mutation; the pane is read-only (no `/action` calls). See
"Acceptance checklist" below.

**Ask (Tony, 2026-11-19):** Extend the Board page with a thin, evidence-first
operations pane over the card cycle. Read-only projection first; the phase-one
home is the Board page (`stacks/web/public/apps/board2/index.html`), kept
"beside the source of truth" — with links into OpenChamber sessions.

Scope: planning, schema, documentation, tests, examples only. No deployment,
no broad autonomous mutation.

---

## 1. Pane placement

- Home: **Board page** (`scripts/render-board2.py` →
  `stacks/web/public/apps/board2/index.html`). Its modal card view
  (`detailHtml`/`renderModal`) is the existing card detail surface; the pane is
  the read-only operations view over it.
- All writes stay Tony-side: `POST /apps/board-api` (`/action`, `/comment`).
  The pane itself issues **no** mutations in v1.
- Data entry point: the card JSON served by board-api
  (`GET /cards`, `GET /card/<id>`), plus the job/run evidence contracts below.

## 2. Pane sections (from the card spec, each with its data source)

| Pane section | Data source |
|---|---|
| **Lifecycle & timeline** — column, updated, transitions | Card record: `id, ref, title, column, priority, updated, brief, spec, comms[]` (board-api `GET /cards`); envelope lifecycle (`ada_job_envelope.LIFECYCLE` + `_TRANSITIONS`) once the card's job envelope exists; timeline = comms + envelope transitions |
| **Eligibility & claim reason** — why the card is (not) pickable | `scripts/board/card-pick.py` `is_actionable()` reasons (`finished`, `open request <id>`, `action claimed`); `card.action.status` (`idle`/`queued`/`running`/`done`); lane + `target_host` + `attempts` |
| **Executor / provider / model** | `action.executor` (`opencode`/`devin`/…), `action.lane` (runner-agent `LANE_MODELS`, e.g. `free_lane`→`litellm/gemini-3.5-flash-lite`), `action.model`, provider from DevNest ledger |
| **Host / session (cockpit)** | `action.target_host`; OpenChamber session linked from the host (session tool / ada-control MCP — the interactive cockpit) |
| **Queue & run duration** | Lane metric `queue_s`/`wall_s` via `board-api GET /jobs?card=<id>` (evidence read door, §4 — landed); claim time from `action.status` transitions |
| **Evidence: tokens & cost** | DevNest lane metrics via `board-api GET /jobs?card=<id>` (`input_tokens`, `output_tokens`, `provider_cost_usd`, `combined_cost_usd`…); runner taskdir `usage.json` merged into the same rows (`exit_code`, `verdict`, `artifact_landed`, audit lists) |
| **Artifact & verifier** | `action.artifact`, result bundle `result.json`/`summary.md`/`diff.patch`/`tests.json` (`ada_job_envelope.RESULT_ARTIFACTS`), `verdict.json`, `ada_job_envelope.receipt()` |
| **Attempts & failure** | `action.attempts`; DevNest `failure_reason`; board-api `action.result`/`action.failure` |
| **Suggested escalation, reason & confidence** | Derived at render: verifier verdict + `failure_reason` + attempt-cap state from `card-pick.py`/board-api; confidence = a pane-level derivation (`high` when a fail has artifact/verifier evidence, `medium` without, `low` when no evidence) — not a stored contract field |

## 3. Data sources (the read-only contracts read in this pass)

- **Board API** — `scripts/board/board-api.py`: `GET /cards`, `GET /card/<id>`,
  `GET /jobs?card=<id>` (read-only evidence rows — lane metric + usage.json +
  envelope, §4), `POST /action {id, do: queue|close|hold|retry|claim/move/
  finish}`, `POST /comment`; card JSON carries `id/ref/title/column/priority/
  updated/brief/spec/action/requests/comms/ask` (see `ada_card_pick` shape).
- **Job envelope** — `scripts/board/ada_job_envelope.py` (ADA-1010 contract,
  tests pass: `tests/board/test_ada_job_envelope.py`):
  - `REQUIRED` envelope keys; `EXECUTORS = {opencode, devin, script, manual,
    kk_mac_local}`; `LIFECYCLE` (`draft→ready→claimed→running→verifying→
    review→approved→merged→done` + `failed/stalled/cancelled`);
    `_TRANSITIONS` map; `validate_envelope`, `validate_transition`,
    `transition_record`, `validate_result`, `receipt()`.
  - Result bundle: `result.json`, `summary.md`, `diff.patch`, `tests.json`;
    status `pass|fail|held`; `verifier` + `evidence` required.
- **Executor** — `scripts/board/runner-agent.py`: lanes + keyword
  classification (`classify_lane`), `usage.json` evidence per run
  (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`,
  `exit_code`, `verdict`, `artifact_landed`, tool/verifier audit),
  attempt/stall semantics (`attempts` reset on retry, stall at cap).
- **DevNest (durable bounded execution)** — `scripts/devnest/lane_gate.py`:
  `METRIC_FIELDS` (tokens, `wall_s`, `queue_s`, `retries`, `tool_denials`,
  `human_minutes`, `verifier_pass`, `artifact_landed`, `escalated`,
  `provider_cost_usd`, `combined_cost_usd`, `devin_equiv_tokens`,
  `failure_reason`), `price()`/`finalize_cost()`, `metrics.jsonl` ledger.
  `scripts/devnest/opencode_profiles.py`: task-scoped profiles (artifact/
  verifier policy, e.g. `free_lane`→`ops-readonly`).
- **Card helpers** — `scripts/board/card-context.py` (context pack an agent
  starts from), `scripts/board/card-pick.py` (eligibility + strategies).
- **Board page** — `scripts/render-board2.py` (modal `detailHtml`/
  `renderModal`, write paths `POST /apps/board-api`).

## 4. Read-only projection + evidence serving (landed 2026-11-19)

- The pane reads only `GET`s (card JSON, lane metric + usage.json + envelope).
  No `/action` from the pane.
- **Evidence serving landed:** `board-api GET /jobs?card=<id>` (also
  `?job_id=`) is the read door the pane uses — `scripts/board/board-api.py`:
  `_lane_evidence()` returns per job the DevNest lane metric
  (`metrics.jsonl`, `METRIC_FIELDS` — `input_tokens`, `output_tokens`,
  `provider_cost_usd`, `combined_cost_usd`, `wall_s`, `queue_s`,
  `verifier_pass`, `artifact_landed`, `failure_reason`…), the runner taskdir
  `usage.json` (merged keys: `exit_code`, `verdict`, `artifact_landed`,
  audit lists), and the committed envelope
  (`evals/opencode-lane/jobs/<job_id>.yaml`); newest first. The pane fills
  "Queue & run duration", "Evidence: tokens & cost" from it (a gap message
  remains when no ledger row/usage exists). Unit-tested in
  `tests/board/test_board_api_jobs_evidence.py`.

## 5. Tests & examples (stage 4 — no live changes)

- New test: `tests/board/test_control_pane_projection.py` — reads the live
  card record (the card YAML is the board's source of truth; mutations go
  through board-api) and asserts every pane-section source the design maps is
  present and shaped as promised (incl. the §4 `/jobs?card=` evidence read,
  §6.3 source tags); plus the envelope/metric contracts above (validate an
  example envelope, assert ledger fields).
- New test: `tests/board/test_board_api_jobs_evidence.py` — unit + loopback
  route tests for the new `GET /jobs` read door (§4): ledger filter/order,
  usage.json merge, envelope read, route 200/400.
- Existing examples: envelope/result fixtures in
  `tests/board/test_ada_job_envelope.py`; committed envelopes under
  `evals/opencode-lane/jobs/*.yaml`; card context pack via
  `scripts/card-context.py`.

## 6. Acceptance checklist

1. [x] Board page offers a control-pane entry per active-cycle card — the
   "Card cycle control" section lists doing/review + queued/running cards;
   the pane opens read-only — no `/action` calls (v1 implemented 2026-11-19).
2. [x] Pane shows, per card: lifecycle & timeline (card record), eligibility
   & claim reason (card-pick reasons + live action), executor/provider/model
   (live `/apps/board-api/cards?id=` overlay), host/session (target_host),
   tokens & cost ("not served — design gap" today), artifact/verifier
   (artifact, verified, result), attempts/failure (attempts, failure),
   suggested escalation with reason + confidence (derived).
3. [x] Each displayed value cites its source — `from: <source>` per row
   (`SRC_CARD` / `SRC_LIVE` / `SRC_METRIC` / `SRC_USAGE`; "derived" for the
   escalation suggestion).
4. [x] `pytest tests/board/test_ada_job_envelope.py
   tests/board/test_control_pane_projection.py
   tests/board/test_board_api_jobs_evidence.py` passes (24 tests, 2026-11-19).
5. [x] Evidence serving (§4): `board-api GET /jobs?card=` — DevNest lane
   metric + runner `usage.json` + committed envelope; the pane reads it.
6. [x] Card note: v2 progress note posted to the card via board-api
   (2026-11-19 — evidence serving + source tags).

## Operational lessons (recorded 2026-11-20, while processing this card)

- **The Board Tony sees:** `https://idc02.taila0626a.ts.net/apps/board2/` —
  the idc02 public edge proxies `/apps/board2/*` to the `:8099` web
  (`rootlessport`, serving `/home/tony/web-srv/public/`). The sync chain:
  Tony's Mac served checkout (`~/CascadeProjects/chaba-tony-dell`) →
  idc03's copy → `web-sr-sync.timer` (idc02, every :00/15/30/45) →
  `/home/tony/web-srv/public/` (the `:8099` web root).
- **The page render (the form Tony asked for):**
  `ssh tony-dell` → `cd ~/CascadeProjects/chaba-tony-dell && python3
  scripts/render-board2.py` (force, no `--if-changed` — it skips on a stale
  state file). Verify the page itself (grep + stat mtime), not just one
  host's copy: during the saga, tony-dell's copy was old while the web-sr
  copy was new (and vice versa).
- **After a fresh render, re-sync to idc03** (the web-sr-sync reads idc03):
  `ssh tony-dell "scp -r ~/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/board2/
  idc03:~/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/board2/"` —
  then `systemctl --user start web-sr-sync.service` on idc02, or wait ≤15
  min for the timer. Verify:
  `curl -s https://idc02.taila0626a.ts.net/apps/board2/index.html |
  grep -c "Card cycle control — read-only (v1)"` → `1`.
- **The edge caches:** the idc02 edge caches responses (`Cache-Control:
  public, max-age=3600` on some routes) — the edge's `cards.json` can show
  the old board (KNB-0229 in `done`) while the served page is new —
  hard-refresh (Cmd+Shift+R) to see fresh data.
- **Verify in a browser, not just curl:** curl `http://127.0.0.1:8099/apps/board2/index.html`
  for the server side is not enough for Tony's view — use playwright on
  `https://idc02.taila0626a.ts.net/apps/board2/` (currently: `hasControl:
  true`, `cpSecs: 9`, the KNB-0229 row visible).
- **board-api /jobs not yet served:** `curl -sk https://idc03.taila0626a.ts.net:10000/jobs?card=kanban-card-cycle-control-pane`
  → `{"error": "not found"}` — the running board-api predates the new
  route (its worker code predates the route) — the pane's tokens/cost/queue
  columns need a board-api restart on idc03.
