# Dispatch outcome — ansible-prep-plan-apply-verify (OPS-1424 step 4)

## What was done
Resumed the OPS-1424 pilot at step 4 (dry-run prep + plan `--check --diff` + verify) from the ansible controller (tony-dell `~/ocb-pilot` scratch copy of this worktree's `ansible/` + `ssot.audit.hosts.yml`, since the exec checkout only carries merged master).

Ran all four legs live:
- `ada-ocb-preflight.yml` — rc=4 (idc02 unreachable, tolerated per spec); wrote `summary.yml` + per-host reports, posted fp-deduped board comment.
- `ada-ocb-plan.yml` — rc=4; emitted the gated apply command, no mutation.
- `ada-ocb-upgrade.yml --check --diff -e card_ref=ansible-prep-plan-apply-verify` — DRY RUN verdict, rollback stated before write, 3A traceability assert correctly skipped (not approved), write play skipped, post-gate failed cleanly naming the blocker.
- `ada-ocb-verify.yml` — rc=4; assert failed on idc02, `always:` block still wrote benchmark reports + board comment.

## Bugs found by the pilot and fixed (commit a1c8e5530f on dispatch branch)
1. `benchmark_report_ts` used `lookup('pipe','date')` in play vars — re-templated every task, so the report dir and per-host template disagreed by a second and writes failed. Pinned once via `set_fact` in preflight + verify.
2. Unreachable hosts were reported `probed:true/unreachable:false` with all-`?` fail checks. Report builder now emits `probed:false, unreachable:true, rc:4`, empty checks, summary `unreachable (no probe data)`.
3. `tasks/ada-ocb-assert.yml` crashed templating `hostvars[h].ocb_probe` for unprobed hosts. Now defaults to `{}` and uses `.get()`; missing probe fails the gate with an explicit "(no probe data — host unreachable or probe failed)" suffix. Same hardening in upgrade playbook's preflight-state debug.
4. Added `ocb_report_hosts` extra-var override so `--limit` previews don't emit bogus unreachable rows (documented in playbook headers).

## Live finding needing attention
**idc02 (declared primary `ocb_pane`, 100.123.163.11) refuses SSH — connection refused port 22** (confirmed via alias and IP). tony-dell fallback is healthy (web=2.8.0, units active, edge 200/CSP ok). Approved apply is correctly blocked until idc02 is back; raised as a card request for Tony.

## Artifacts (canonical, on tony-dell controller)
- `~/CascadeProjects/chaba/reports/ansible-benchmark/ada-ocb-preflight/20261126T054143Z/`
- `~/CascadeProjects/chaba/reports/ansible-benchmark/ada-ocb-plan/20261126T054202Z/`
- `~/CascadeProjects/chaba/reports/ansible-benchmark/ada-ocb-verify/20261126T054329Z/`
(`reports/*` is gitignored — evidence lives on the controller; paths posted to card comms.)

## Trail
- `docs/ssot/jobs/infrastructure/2026-11-26-ansible-prep-plan-apply-verify-pilot.yml`
- Commit `a1c8e5530f` on `dispatch/20261126-123352-objective-define-and-pilot-an-` (not pushed, per dispatch rules).

## How to verify
- `git show a1c8e5530f` — the four playbook/task fixes.
- On tony-dell: `cat ~/CascadeProjects/chaba/reports/ansible-benchmark/ada-ocb-preflight/20261126T054143Z/summary.yml` — shows `unreachable=1 probed=1/2`, idc02 bucket=unreachable rc=4.
- Re-run any leg from `~/CascadeProjects/chaba/ansible` once the fixes merge to master.

lessons:
- lookup('pipe', ...) inside play vars re-templates on every use — pin run-identity values (timestamps, dirs) with set_fact first.
- Probe-based reports must treat "host produced no facts" as unreachable/rc=4, not all-fail drift, or scheduled audits page on ghosts.
- Shared assert includes must tolerate missing probe facts (default({}) + .get) — the gate is also the post-mortem path when the host is down.
- --limit does not shrink groups[...] or assert loops over the full group; report/assert scope needs its own override var.
