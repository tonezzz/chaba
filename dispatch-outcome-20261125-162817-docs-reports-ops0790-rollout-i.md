# Dispatch outcome — audit-miss-claimed-docs-never-landed

Card: `audit-miss-claimed-docs-never-landed` (AUD-0032)
Branch: `dispatch/20261125-162817-docs-reports-ops0790-rollout-i`
Commit: `b7d75781ff4` — 3 files, +267 lines. Not pushed (per dispatch rules).

## What was found

All three paths were genuinely absent from master, every branch, and disk —
confirmed by the audit and re-verified in this worktree (`git log --all`
on each path: empty).

1. **`docs/kb/edge-add-public-host.md`** — the registry entry in
   `ssot.procedures.yml` (`edge-add-host`, status:verified, last_run
   2026-10-09) was **correct**; the KB body was simply never committed.
   Card `ha-public-urls-cf-access` comms (2026-10-08) literally say
   "Recipe for future public hosts captured in docs/kb/edge-add-public-host.md"
   — the capture step was claimed but never landed. → **Wrote the doc**,
   reconstructed from that card's executed run: CF proxied CNAME
   (`cf-dns-upsert.sh`, Zone.DNS token on idc02) → caddy-edge vhost with
   mandatory `tls internal` (proxied records can't do origin ACME) →
   CF Access app/policy → ssot.routes.yml + health registration →
   dual verify (edge-direct SNI + public 302→Access). No registry change
   needed — the pointer now resolves.

2. **`docs/reports/ops0790-rollout-idc03.md`** — the rollout itself
   **did happen** (card `ops0790-rollout-idc03`, done 2026-11-07 via
   direct ssh after dispatch stuck queued): `render-jobs --ids
   embed-lane-news,embed-lane-lessons,yomi-update-active --install`
   armed exactly those 3 timers on idc03; `list-timers` verified;
   embed-lane-news first-run succeeded, the other two were still
   running (real jobs, per spec = data not blocker). Spec step (4)
   required this note; it was never committed. → **Wrote the note**,
   explicitly marked as reconstructed from card comms + ssot.jobs.yml.

3. **`docs/reports/plan-route-checklist.md`** — this was the *nominal
   destination* inside the opencode-lane `plan-route-docs-only` eval
   fixture (`evals/opencode-lane/jobs/plan-route-docs-only.yml`), not a
   doc an executed session claimed to produce. The eval produces a plan
   JSON (`artifact.out`), not the checklist file — so this is arguably a
   false-positive miss. → **Wrote it anyway** as a genuine reusable
   docs-only rollout checklist mirroring the `verify.py` contract
   fields, so the referenced path now holds real content either way.

## How to verify

- `git show b7d75781ff4 --stat` — three new files.
- `ls docs/kb/edge-add-public-host.md docs/reports/ops0790-rollout-idc03.md docs/reports/plan-route-checklist.md`
- `grep edge-add-host docs/ssot/ssot.procedures.yml` — `where:` pointer
  now resolves to a real file.
- Card comms on `audit-miss-claimed-docs-never-landed` has the DONE entry.

## Notes / follow-ups (not done here)

- `cloudflare.env` token drift across hosts (idc02 has Zone.DNS,
  tony-dell doesn't) is noted inside the new KB doc; a dedicated fix
  card may already exist — not created here to avoid duplicating.
- `ops0790-rollout-idc02` / `ops0790-rollout-tony-dell` rollout notes
  were not in this card's scope; if the audit flags them later, same
  reconstruction applies (their card comms carry the results).

lessons:
- "Captured in <file>" comms claims need the file-landing check — this is
  the third instance of a procedure/runbook body that was described as
  written but never committed; the procedures registry `status:verified`
  only proves the *run* happened, not that the doc exists.
- Eval fixture `allowed_paths`/`artifact.path` values look like claimed
  artifacts to an artifact-landing audit but are really hypothetical
  destinations — check the eval job's `artifact:` block before treating
  a missing path as a miss.
- `git log --all -- <path>` (no --follow with multiple paths) is the
  fast way to prove a file never existed anywhere.
