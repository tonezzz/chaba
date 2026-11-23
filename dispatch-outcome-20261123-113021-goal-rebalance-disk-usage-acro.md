# dispatch 20261123-113021 — storage-rebalance-underused (attempt 2)

## What changed / was found

**Attempt-1 recovery:** the previous run's work sat unmerged on
`dispatch/20261123-110440-...` (commit `8c73817d45`). A straight
cherry-pick conflicted on all three edited files — the parallel
`disk-guard-ssot-enforce` checkpoint (`c9de6447b4`, 11:11) had already
landed an equivalent base underused implementation on master while
attempt 1 was running. Resolution: keep master's flag model, port
attempt 1's refinements on top.

**Landed on this branch:**
- `ansible/playbooks/disk-headroom.yml` + `templates/disk-headroom.j2`
  — `underused_min_size_gib: 10` floor added; `underused` flag now
  gated on `st == 'ok'` (a warn/crit mount can no longer carry the
  underused flag) and on filesystem size >= 10 GiB; underused mounts
  surfaced in the per-host `summary` line (`warn: /; underused:
  /dell-backup, /timeshift`) plus the `underused_mounts` list.
  Verified with a jinja2 mock-render covering crit/warn/ok/unreachable
  and the 1 GiB /boot/efi exclusion case.
- `scripts/ada/disk-trend-watch.py` — `DISK_TREND_UNDERUSED_MIN_SIZE_GIB`
  (10) env + size floor inside `is_underused()`; the per-mount
  `underused` flag is gated on `alert == "ok"` at the report build so
  alerting mounts never double-flag. Docstring/env list updated.
  `--selftest` PASS — fixture extended with a 1 GiB /boot/efi at 30%
  asserting the floor exclusion.
- `stacks/idc03/mddb/mddb-backup-offload.sh` (NEW, from attempt 1) —
  archives `~/mddb-backups` beyond newest-1-per-instance to
  `idc02:~/mddb-backups-idc03` via rsync; remote df guard
  (bytes + 20G), prunes local only after remote size match, flock,
  board-api alert on failure. bash -n clean; attempt 1 e2e-tested it.
- `docs/ssot/jobs/infrastructure/2026-11-23-storage-rebalance-plan.yml`
  (from attempt 1, updated) — live survey (idc03 91% +6.2 GiB/d →
  ~4.7d; dell 89% +8.3 GiB/d → ~2.9d), approval-gated delete/move
  batch, capacity verdict: rebalance, don't resize.
- `docs/ssot/jobs/infrastructure/2026-10-05-disk-trend-watch.yml` —
  env docs updated for the MIN_SIZE floor + ok-gate.

## Result / gate

Repo work complete and verified in-worktree. **No prod deletes, moves,
or deploys** — the board request
`approve-prod-delete-move-batch-a-idc03-r-0ceb11` raised in attempt 1
remains open (no answer in answers.jsonl at session end). The batch it
covers: (a) idc03 deletes ~66G, (b) offload deploy → ~40G, (c) dell
models → /dell-backup 34G, (d) chrome file-cache 40G clear.

## How to verify

- `python3 scripts/ada/disk-trend-watch.py --selftest` — PASS (incl.
  `/boot/efi` floor-exclusion assert).
- `cd ansible && ansible-playbook playbooks/disk-headroom.yml` —
  underused rows + `; underused:` in summaries.
- `bash -n stacks/idc03/mddb/mddb-backoff-load.sh` — syntax clean
  (deploy itself is part of the gated batch).
- Plan/survey: `docs/ssot/jobs/infrastructure/2026-11-23-storage-rebalance-plan.yml`.

lessons:
- Parallel dispatch lanes can land overlapping features mid-run:
  attempt 1's underused code conflicted because the
  disk-guard-ssot-enforce checkpoint landed the same feature on master
  at 11:11 — check `git log <file>` since the base before re-applying
  a prior attempt's commit.
- Keep the surviving implementation's model (per-mount flag) and port
  only the missing semantics (size floor, alert-ok gate, summary
  surfacing) — re-imposing the other branch's state model would have
  re-written freshly merged code for no gain.
- Underused needs BOTH a min-size floor and an alert-state gate:
  without them /boot-efi-scale mounts flag as underused and a warn/crit
  mount can carry contradictory flags.
