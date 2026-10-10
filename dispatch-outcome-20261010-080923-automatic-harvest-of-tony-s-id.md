# dispatch outcome — tony-ideas auto-harvester

**Card:** `tony-ideas-harvest` · **Runner:** tony-omen · **Result:** shipped + live

## What changed (commit 2690dfb4 on `dispatch/20261010-080923-automatic-harvest-of-tony-s-id`)

- `scripts/ada/tony-ideas-update.py` — deterministic harvester (no model
  calls), same contract as `kanban-brief.py`: `ada-cms-automation`
  registry gate, `--force`/`--dry-run`, full cms-page-standard meta.
  Mines four sources and tags each row `adopted` / `pending` /
  `superseded`:
  - card comms `from:tony` — ops-verb regex v0 drops closed/moved/
    queued-for-processing/retry/status/commit/merge/capture noise;
    `answered <slug>: <ack>` unwraps and drops bare acks
    (yes/proceed/approve/continue/close/c), keeps decisions
    (618 → 61 substantive, 557 filtered);
  - `docs/ssot/focus-inbox/*.yml` — drafts/pending → pending, processed/
    linked → adopted, `archived/` → superseded; watcher families
    (gh-run/report-watch/ha-auth/SSOT-optimize/ARP/binlog) collapse to a
    count; `processed/` (880) counts only;
  - `ssot.focus.decisions.yml` — routed requests, continuation cues
    dropped (12 kept);
  - `dispatch-outcome-*.md` — adopted session rows (66); the
    `ada-ha-bank-devin-tony` bank (~2000 docs) is reachability-probed
    only — full-text mining + Ada transcripts deferred per card.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new `chaba-tony-ideas` job:
  tony_dell, `*:0/30`, `REPO=chaba-tony-dell` (served checkout),
  separate timer from chaba-kanban-brief for an independent failure
  domain.
- `systemd/generated/tony_dell/chaba-tony-ideas.{service,timer}` —
  rendered via `render-jobs.py` (`--check` clean: 45 jobs, 7 hosts).
- `docs/ssot/jobs/ada/2026-10-10-tony-ideas-harvester.yml` — trail.

## Page mechanics

Two managed blocks — `tony-ideas:head` (status line + Latest + section
links) and `tony-ideas:auto` (Pending/Adopted/Superseded tables +
Sources & gaps + provenance) — wrap the hand-curated *Standing
directions* section, which is re-extracted from the live page verbatim
each run with stray markers stripped. Curation survives regeneration.

## Result

Two live publishes verified idempotent: 250 mined lines — **127
adopted · 96 pending · 27 superseded**; markers balanced, single
`## Latest`, standing table intact. First publish hit a transient MDDB
`RemoteDisconnected` on `/add`; `_post` now retries 3× with backoff.

## How to verify

- `python3 scripts/ada/tony-ideas-update.py --dry-run` — renders the
  full page.
- Live page: `ada-cms-pages/tony-ideas` (en) via MDDB or the CMS UI.
- `python3 scripts/render-jobs.py --check` — manifest valid.

## Not done (needs operator/production path)

- The generated units are not installed on tony_dell — that is a
  production enable: `render-jobs.py --host tony_dell --install` (or the
  next deploy sweep) after this branch merges.
- Follow-ups per card: ops-filter → classifier, Ada transcript mining,
  devin-bank full-text mining, trend chart per report-graph-standard.
