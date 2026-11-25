# Dispatch outcome — system-report-18-missing-nodes (attempt 2)

## What happened

Attempt 1 (tony-omen, 09:37) completed the full triage and live fixes but
produced **no commits** — its 6 files sat staged-but-uncommitted in
`dispatch-wt-20261125-093709-...` when the checkpoint commit failed, so
merge-sweep counted it NOT verified and the card was re-dispatched.

This attempt **recovered attempt 1's work verbatim**: pulled
`git diff HEAD` from the still-dirty tony-omen worktree over ssh and
applied it here (278-line patch, applied clean). Then re-verified every
claim against live state before committing.

## Triage verdict (unchanged from attempt 1, re-verified)

**Zero of the 18 "missing" nodes are dead, decommissioned, or moved.**
All producers deliver fresh metas; the missing state was the pre-11-18
delivery gap fixed by `scripts/report/pull-report-metas.sh`
(`docs/ssot/jobs/infrastructure/2026-11-18-report-meta-pull.yml`).

`audit-hosts/{tony-omen,mn01}` unreachable entries were transient;
`audit-hosts/macbook` is `offline_ok: true` in `ssot.reports.yml`
(laptop sleeps/off-net) — a watchdog bug, not an outage.

## Real defects found + fixed (now committed on this branch)

1. **`scripts/report-system.py` crash (root cause of frozen report).**
   `mcp-inventory` emits status `no-config` (host reachable, no agent
   lane — informational). `_BADGE[k]` at render_markdown line ~217 does
   direct dict indexing → `KeyError: 'no-config'`. **Reproduced live
   this morning**: con01 `chaba-system-report.service` failed again at
   2026-11-25 06:48:15 CET with exactly that traceback; served
   system-report.yml still frozen at 2026-11-20T06:48. Fix: added
   `no-config` to `_BADGE` + `_WORST` (informational, worst=1 — matches
   report-watch's BAD_NOW/BAD_SUSTAINED which already ignore it).

2. **`scripts/report/system-report-watchdog.py` offline_ok gap.** The
   watchdog counted `audit-hosts/macbook unreachable` as red forever
   even though the registry declares `offline_ok: true`. Fix:
   `resolve_node()` (`scripts/lib/report.py`) now emits `offline_ok`
   per node into the rendered yml, and the watchdog exempts
   `unreachable + offline_ok`, with a registry fallback for yml
   rendered before the flag existed.

3. **`docs/ssot/infrastructure/ssot.health.home.datastore.yml`** —
   `ada-stt-con01` marked `disabled: true` with re-enable notes.
   con01's ada-stt was stopped+disabled 2026-11-23 (absorber shed);
   `http-health-audit.mjs` honors `disabled` (verified: skips
   `s.disabled`), which clears the last health_snapshot failure.

4. **Live fixes already applied by attempt 1 (verified still holding):**
   - `ha-live.service` on tony-omen: `active` + `enabled`,
     `https://tony-omen.taila0626a.ts.net:8444/` → **200** (was 502 in
     this morning's health snapshot).
   - telegram-mn-bot `TG_WHISPER_URL` on idc03 repointed to
     127.0.0.1:8914, relay restarted (mn-ha STT works).

## overnight-assessment `error` node — real producer signal, mostly transient

Fresh meta (2026-11-25T02:02+07) shows 2 failed steps:

- `ssot_validate`: 1 invalid file at run time. Re-ran
  `node scripts/ssot-validate-all.mjs` on the idc03 served checkout
  just now: **6484/6484 valid, 0 errors** — the bad file was fixed
  between 02:02 and now. Transient.
- `health_snapshot`: the two real failures were `ha-live` 502 (fixed —
  verified 200) and `ada-stt-con01` ECONNREFUSED (now `disabled: true`
  in this patch). Tonight's run should go green.

## Files in this commit

- `scripts/report-system.py` — `no-config` badge/worst
- `scripts/lib/report.py` — emit `offline_ok` in resolve_node
- `scripts/report/system-report-watchdog.py` — offline_ok exemption +
  registry fallback
- `docs/ssot/infrastructure/ssot.health.home.datastore.yml` —
  ada-stt-con01 disabled
- `docs/ssot/jobs/infrastructure/2026-11-25-system-report-missing-nodes-triage.yml`
  — full triage record (verdicts, evidence, verify steps)
- `dispatch-outcome-20261125-093709-...md` — attempt 1's outcome doc
  (recovered)
- `dispatch-outcome-20261125-054445-...md` — this doc

Full triage detail: `docs/ssot/jobs/infrastructure/2026-11-25-system-report-missing-nodes-triage.yml`

## How to verify after merge

1. con01 `chaba-repo-sync` picks up the merge → next
   `chaba-system-report.timer` run (daily 06:45) completes instead of
   KeyError; served `system-report.yml` `generated_at` goes fresh.
   Check: `ssh idc03 'ssh con01 journalctl --user -u
   chaba-system-report.service -n 30'`.
2. `system-report-watchdog --no-alert` on tony-dell: macbook drops out
   of the red set.
3. Tonight's overnight-assessment: health_snapshot + ssot_validate
   should pass (ha-live 200, ada-stt skipped, SSOT clean).

## Open items (not blocking, recorded in triage.yml)

- `pull-report-metas.sh` mn01 pull failed again this morning
  (rc=23) — meta still fresh via other roots; flaky, worth watching.
- idc01 stale meta residue on con01 reports/ — inert.
- con01's *installed* `chaba-system-report.service` unit has a stale
  host list (missing kk-mac vs generated unit) — render drift;
  `scripts/render-jobs.py --host con01` + redeploy would converge it.
- systemwide-assessment / model-bench metas stale (manual/cadence
  producers) — pre-existing, different class.

lessons:
- Dispatch checkpoint commits can fail silently leaving staged work unmerged — when a card is re-dispatched, FIRST check the previous worktree on the prior host (`ssh <host> 'cd <wt> && git status'`) and `git diff HEAD` to recover instead of redoing.
- `reports/*` is gitignored; verify producer liveness via `meta.*.yml` on the harvest host (con01 `~/CascadeProjects/chaba/reports/`), not the dispatch worktree.
- mn01 has no direct ssh to con01 — hop via `ssh idc03 'ssh con01 ...'`.
- systemd `Type=oneshot` + `TimeoutStartSec` still shows `Active: activating` mid-run; check `ExecMainExitTimestamp`/`ps` before declaring a job dead.
