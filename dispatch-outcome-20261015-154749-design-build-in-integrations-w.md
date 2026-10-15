# Dispatch outcome — boards-error-post-type (2026-10-15)

## What changed

Committed on the dispatch branch (not pushed, not deployed):

- `integrations/wp-boards/chaba-boards.php` — v0.5.0 → **v0.6.0**. New
  private `ops_error` CPT (REST-writable, comments in supports), meta:
  `lane` (kk|tony|michael), `session_id`, `tool`, `error_type`
  (schema_error|runtime_error|silent_reconnect|stale_result|phantom_claim|
  degraded_result), `raw_result` (JSON, JSON-safe sanitizer so payloads
  aren't stripped), `transcript_ref`, `occurred_at`, plus review-loop meta
  `status` (open|explained|resolved)/`resolved_by`/`resolved_at`. Admin
  columns lane/tool/type/at/status and a single-view renderer that draws
  the error card (status badge, meta table, pretty-printed raw result,
  explain-in-comments prompt).
- `scripts/ada/ops-error-posts.py` — writer for idc03. Per-lane sources:
  `journalctl --user -u ada-kk|ada-ha-tony|ada-michael` (function_call
  received/result join, reconnect resumed=False lines) plus MDDB
  `ada-ha-events-<lane>` `kind=ops-event` (phantom_write_claim,
  stale_result, silent_reconnect). Classifies into the error_type enum;
  confirm-gate and ACL-denial results are skipped (expected behavior, not
  failures). Dedup = deterministic `err-<md5>` slug looked up via
  `?slug=`; silent_reconnect coalesces one post per session per day.
  Posts via app password to `origin_base` (boards.h3) with a browser UA
  (public edge 1010s script UAs). `comment_status: open` forced so the
  review thread can't be closed by site defaults. Cursor advances only on
  a fully successful **unfiltered** run — failed POSTs and `--session`/
  `--lane`/`--journal-file` backfills leave it so nothing is skipped.
  `--dry-run`, `--since`, `--selftest` supported.
- `docs/ssot/apps/ssot.wp-boards.yml` — ops_error post type, title
  standard `Err — {lane} {tool} {date}`, writers entry, v0.6.0 note.
- `docs/ssot/infrastructure/ssot.jobs.yml` — `ops-error-posts` job on
  idc03, every 15m, 5m timeout, `condition_path` guard.
- `systemd/generated/idc03/ops-error-posts.{service,timer}` — rendered
  via `scripts/render-jobs.py` (not hand-edited).
- `docs/ssot/jobs/ada/2026-10-15-ops-error-posts.yml` — job trail.
- `tests/ada/test_ops_error_posts.py` — 17 unittests (classifier, journal
  parsing, slug coalescing, title convention).
- `docs/ssot/jobs/ada/2026-10-15-wp-comment-sync.yml` — unrelated
  pre-existing YAML syntax fix (unquoted `+` scalar) that was breaking
  the repo-wide validator; one-line minimal repair.

## Result

The observability surface is built end-to-end: failures → private
ops_error posts → comment thread for the truthful explanation →
meta status flip for resolution. The three session-183e9c8d7e seeds
(enroll_speaker schema error, silent reconnect, web_search empty-args)
are covered by the `--session` backfill path — run on idc03 after deploy:

```
python3 scripts/ada/ops-error-posts.py \
  --since "2026-10-13 16:00" --session 183e9c8d7e
```

## Verification

- `python3 scripts/ada/ops-error-posts.py --selftest` → PASS (4
  deterministic slugs)
- `python3 -m unittest tests.ada.test_ops_error_posts` → 17/17 OK
- `php -l chaba-boards.php` → no syntax errors
- `python3 scripts/render-jobs.py --check` → OK 58 jobs, 7 hosts
- `node scripts/ssot-validate-all.mjs` → 2423 files, 0 errors,
  27 warnings (pre-existing)
- `git diff --check` → clean

## Not done (gates)

- Plugin **not deployed** — v0.6.0 must reach boards.h3 before live
  POSTs succeed (writer holds cursor on 404, nothing lost). Deploy via
  the normal card `chaba-boards-plugin-deploy`.
- Timer rendered but **not installed/enabled** on idc03 — merges with the
  served checkout when the dispatch branch lands.
- No live seed posts created (requires the deployed CPT).

## Follow-ups worth carding

- Optional nudge loop (board request when an ops_error sits unexplained
  >N hours) — deliberately deferred per card spec.
- `error_type=phantom_claim` depends on ada-voice emitting
  `phantom_write_claim` ops-events; verify that emitter exists on the KK
  lane during the first live week.
