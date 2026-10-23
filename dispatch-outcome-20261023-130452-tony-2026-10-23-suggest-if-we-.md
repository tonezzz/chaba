# Dispatch outcome — nest-api-unified-mutation-service

**Task:** Tony 2026-10-23 — "suggest if we need a single point of
service? how?" — approved: extend board-api rather than a new daemon.
Done-condition: `/job` + `/lesson` live on board-api with tests;
lesson-add.py refactored to call `/lesson`; docs/kb updated; no agent
writes bypass the door.

## What changed (commit `cdecf8cca` + baseline `01a1a6d06`, branch
`dispatch/20261023-130452-tony-2026-10-23-suggest-if-we-`)

**board-api.py** — the unified mutation door. New endpoints after prefix
strip, all behind the existing write-identity gate:

- `POST /lesson` `{topic, content, level?, source?, next_review?,
  status?, no_th?}` — WP `lesson` CPT upsert by slug
  `lesson-<md5(topic)>`; Thai section appended via gemini flash-lite
  (best-effort, degrades to EN-only); `learned_at`/`next_review`/`status`
  preserved on re-file — identical semantics to old lesson-add.py.
- `POST /job` `{slug, title?, status?, comms?|note?, parent?, kind?,
  host?, pack?, runner?, result_ref?, error?, meta?}` — `nest_job` CPT
  upsert for the ada-nest Drive-queue mirror. `status` ∈ queued|claimed|
  running|done|failed|stalled|cancelled; comms appends `{at,from,text}`
  to a JSON log in `meta.comms` (cap 200); `parent` accepts a post id or
  sibling slug (job trees); `from` allows daemon/host names (queue-mgr).
- `POST /report` — report-integration duty: `{query}` → ada-cms-pages
  candidate slugs; `{slug, note, lang?}` → session-log append reusing
  cms-report-note.py logic (managed block + writer-contract meta merge +
  index regen); `{title|slug, content_md, meta?}` → create page.
- `POST /inbox` `{text, label?, priority?, tags?, missing_info?,
  subtasks?, session?, owner?}` — focus-inbox YAML in TEMPLATE shape
  under the card flock with atomic write + immediate commit.

Design: remote-backed endpoints (`/lesson`, `/job`, `/report`) serialize
under a separate flock `/tmp/board-api-wp.lock` — a slow WP/mddb call
never stalls `/comment`. Errors: 400 validation / 502 UpstreamError
naming the failing upstream route / 500 unexpected. WP creds
(`wp-boards.env`) load lazily — absent creds fail only WP-backed
endpoints, not the service.

**integrations/wp-boards/chaba-boards.php v0.9.0** — `nest_job` CPT
registered: hierarchical (`page-attributes`) for job trees, has_archive
(`/wp/nest_job/`), meta kind/status/host/pack/runner/result_ref/error/
comms/updated + admin columns. **Pending WP deploy** — `/job` will 502
until the plugin zip lands.

**scripts/lesson-add.py** — rewritten as a thin `/lesson` client
(`dispatch_repos.board_api_base()` → `BOARD_API` env → tailnet URL).
Same CLI flags; callers need tailnet, not wp-boards.env.

## Tests

- `tests/board/test_board_api_mutations.py` — 17 tests across the four
  endpoints with faked `wp_api`/`_gemini_thai`/`_mddb_post`/`_crn` seams.
- `--selftest` extended to cover all four endpoints (create/update/
  provenance/comms-append/parent/heal/inbox-shape/report modes).
- Existing board tests (queue starvation, dispatch close-out, dispatch
  rails — 41 tests) still pass.

## Live verification (this worktree, port 18787)

`/health` 200; `POST /inbox` → 200, correct file + shape (smoke file
removed after check); `POST /lesson` → 502 `wp creds unavailable` —
correct on a host without wp-boards.env.

## Docs

`docs/kb/board-api-write-door.md` (runbook — endpoints, locks, auth,
callers, deploy dependency); AGENTS.md "Unified mutation door" bullet;
ssot.procedures.yml `board-write` entry widened; ssot.wp-boards.yml
nest_job + v0.9.0 note; colab-mcp-jobs.md queue-mgr mirror note;
`systemd/chaba-board-api.service` + `stacks/tony-dell/board-api/stack.yml`
descriptions; trail `docs/ssot/jobs/infrastructure/
2026-10-23-board-api-unified-mutations.yml`.

## Follow-ups (not this session's scope)

- **Deploy chaba-boards v0.9.0** to WP (wp-admin zip upload via
  `scripts/wp-boards/deploy-plugin-zip.sh` from tony-omen — Tony-approved
  per bump) — required before `/job` can write.
- Redeploy board-api on idc03 (served-checkout merge + unit restart).
- queue-mgr (dell) is the next build-order item on OPS-0759 — it becomes
  the `/job` caller mirroring `gdrive:ada-nest` queue/packs → CPT.
- Pre-commit accepted the wp-boards.yml bloat warning (391→413, review
  threshold 350) into `reports/SSOT_OPTIMIZATION_WARNINGS.json` — the
  file was already over threshold before this change.

## How to verify

```
python3 scripts/board/board-api.py --selftest
cd tests && python3 -m unittest board.test_board_api_mutations
curl -s http://127.0.0.1:8787/health            # on idc03 post-deploy
curl -sX POST <board-api>/inbox -d '{"text":"x","from":"devin"}'
```
