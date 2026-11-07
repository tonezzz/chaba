# Dispatch outcome — KNB-0909 kanban-wide cleanup audit + Colab-ready queue

## What was done

Read-only triage of all 160 open kanban cards (114 backlog, 36 review, 9
doing, 1 lab — no `queued` column exists; queue state is `action.status`).
Each card was classified into: ready now / needs small spec / blocked on
Tony or external / likely done with evidence / duplicate-overlapping /
not dispatchable, plus a list of failed dispatches sitting in review.

The live Colab/Drive state was verified directly from idc02 via
`rclone gdrive:` — the queue is **drained** (last run 2026-10-27
04:54→05:42 ICT; 41/42 packs carry `done` markers). The only undone pack
is `kk-video-c9f99fee6146-preview`, which failed on a torchao
`FqnToConfig` ImportError (tracked as OPS-0929 /
`kk-video-preview-torchao-import-fix`). No managed runtime is live;
nothing currently waits on T4 time.

## Result

- Classification: ~50 ready-now (14 already armed by Tony's answers),
  ~17 need a small spec/fixture, ~20 blocked on Tony/external,
  ~35 likely-done-with-evidence (verified against Drive artifacts, live
  timers, and comms), ~8 duplicate/overlap groups, ~8 not-dispatchable
  (fixtures/epics/physical), 14 failed dispatches in review.
- Ranked fleet queue and a staged Colab T4 queue produced, with per-item
  GPU/RAM/disk needs, prep/cache cost, runtime, artifacts, verifier —
  posted as two board-api comments on the card and recorded durably in
  `docs/ssot/jobs/kanban/2026-10-27-kanban-triage-audit.yml` (commit
  1e5300d82 on this dispatch branch).
- Reconciled with existing cards rather than duplicating:
  answer-auto-verb-triage-impl, kanban-act-loop, boards-migration-cleanup,
  OPS-0880 (devnest-colab-assessment — delivered as the per-boot
  heldout assessment in JOBS.py), OPS-0881 (hf-pro — defer recommended,
  decision still Tony's).
- No card columns moved, nothing closed, nothing dispatched — per the
  read-only mandate. Suggested card actions are listed for Tony/board
  ops in the record and the board comments.

## How to verify

- Board comments: card `kanban-wide-cleanup-audit-and-colab-read-cfbc33`
  has two devin comms with the classification summary + Colab queue.
- Durable record: `docs/ssot/jobs/kanban/2026-10-27-kanban-triage-audit.yml`.
- Live state: `rclone lsf gdrive:ada-nest/packs/ -R --include done`
  reproduces the 41/42 done-marker count; `rclone cat
  gdrive:ada-nest/queue/run-20261027-0454.out.log | tail` shows the drain
  and the preview pack's torchao ImportError.
- Untracked scratch copy of the fuller markdown write-up:
  `reports/2026-10-27-kanban-triage-and-colab-queue.md` (reports/ is
  gitignored; the yml is the durable home).
