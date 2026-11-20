# Dispatch outcome — finish artifact-landing verification (devin-session-audit-2026-10-29 / AUD-0973)

## What was done

Completed the artifact-landing QC audit for the 304 Devin session summaries newer
than the 2026-10-17T16:02:03 marker. Reused the preserved `audit-scratch` claim
corpus from the prior rate-limited tony-omen run (431 summary files, ~4,400 unique
claims across 13 classes) and finished the verification it could not.

Verified per class:

- **PRs**: all 24 claimed `tonezzz/chaba` PRs (#35–63, #128) exist; merged where
  claimed (#57, #58, #189 confirmed). External-repo PR refs are references only.
- **Drive**: all 39 claimed `drive_url` IDs verified present via `rclone lsf
  gdrive:`; every real `drive_path` claim resolves — apparent misses were
  consolidation moves into canonical roots (`ada-nest`, `archive`, `backups`,
  `colab-cache`, `nest`, `notebooklm`) or never-produced/ephemeral items.
- **CMS/MDDB**: all claimed `ada-cms-pages` keys verified via `POST /v1/get` —
  one genuine miss (below); `llm-gateway-bench` is a `--publish` flag reference,
  not a produced page. `cms_coll` claims were reference-only.
- **Cards**: 64/66 `card_created` claims absent from the live compact board are
  archived card files on master (durable). Two created cards vanished entirely.
- **Lessons**: all claimed lesson topics verified in the Education store
  (`/lesson` op:list, 192 topics live).
- **Repo paths**: 594 never-on-master paths triaged — most are generated/ignored
  `reports/*` outputs, extraction fragments, or path prefixes. Genuine unlanded
  artifacts carded below.
- **post_id** comms references were verified at class level (lesson store live);
  individual WP post fetches were not performed — noted in the report.

## Misses filed (all new, deduped against live AUD-*/audit-miss-*/OPS-09xx cards)

- **AUD-0029** `audit-miss-uncommitted-worktree-job-artifacts` — job-record YAMLs
  + evals/opencode-lane additions uncommitted in live worktrees
  (kk-mac-video-render-probe, kk-pdf-image-audit, sacred-father-panel-procedure,
  opencode-first-eval, ops1037, kk-mac-capacity-atomic).
- **AUD-0030** `audit-miss-remote-eval-results-not-landed` —
  `evals/results/devnest-host-tony-omen.json`, `devnest-replay-candidates.json`,
  `evals/kk-mac-lane/out/kk-mac-live-jev-probe-idc03-20261030.json` produced on
  remote hosts, not on master or this host.
- **AUD-0031** `audit-miss-ada-voice-job-records` —
  `2026-10-10-voice-session-churn-context-billing.yml` (nowhere) and
  `2026-10-13-line-file-doc-ingest.yml` (stale chaba worktrees only) missing from
  ada-voice `origin/main`.
- **AUD-0032** `audit-miss-claimed-docs-never-landed` —
  `docs/reports/ops0790-rollout-idc03.md`, `docs/reports/plan-route-checklist.md`,
  `docs/kb/edge-add-public-host.md` (registry `status:verified` but file never
  existed).
- **AUD-0033** `audit-miss-cms-page-devin-session-audit-2026-10-17` — CMS page
  published with documented `add_document` success on 10-17, now 404.
- **AUD-0034** `audit-miss-vanished-board-cards` — board-api returned ok:true for
  AUD-0734 (`dispatch-worktree-debt-audit`) and KNB-0733
  (`session-report-jsondecodeerror-in-daily-d0662a`) but no card exists on the
  live board, in cards/, archive, or git history.

Existing cards already covering related misses were not duplicated: AUD-0020
(oct6 artifacts, in review, PR #196 pending), AUD-0021 (oct17 cards, done),
AUD-0972, AUD-0974, AUD-1123, OPS-0922, OPS-0941, OPS-1288.

## Result

Audit complete. Report `ada-cms-pages/devin-session-audit-2026-10-29` updated
with the final reconciliation timeline entry. Marker advanced
`2026-10-17T16:02:03` → `2026-11-20T18:50:37`. 6 new miss cards filed
(AUD-0029..0034).

## How to verify

- Report timeline tail: `python3 scripts/ada/cms-report-note.py
  devin-session-audit-2026-10-29 --read`
- Marker: `cat ~/.local/share/devin/session-audit-marker`
- New cards: live board ids `audit-miss-uncommitted-worktree-job-artifacts`,
  `audit-miss-remote-eval-results-not-landed`, `audit-miss-ada-voice-job-records`,
  `audit-miss-claimed-docs-never-landed`,
  `audit-miss-cms-page-devin-session-audit-2026-10-17`,
  `audit-miss-vanished-board-cards`
- Evidence corpus: `audit-scratch/` in this worktree (claims.jsonl,
  claims2.jsonl, master-files-fresh.txt, drive-ok.txt, card-refmap.json,
  gh-prs.json, mddb-cms.json).

lessons:
- The full `/cards` board response can exceed JSON parse limits (~7MB) — query narrowly or shell-filter instead of piping the whole response into Python.
- `reports/*` is gitignored by design; audit-hosts outputs live on producing hosts, not misses.
- Card `card_created` claims need a three-way check: live board, master archive, git history — board-api can return ok:true yet the card later vanishes.
- ada-voice uses `origin/main` not `origin/master`; a master-only check false-flags all ada job records.
- Drive claim verification must be consolidation-aware — obsolete root-folder absence is not artifact loss.
