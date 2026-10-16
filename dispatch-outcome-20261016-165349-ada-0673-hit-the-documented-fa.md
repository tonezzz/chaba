# Dispatch outcome — runner-push-cred-gap (OPS-0682)

Task `20261016-165349-ada-0673-hit-the-documented-fa`, card
`runner-push-cred-gap`. Implemented the card's recommended (b)+(c) plus
the verify fix: runners can no longer claim dispatch repos they can't
push, a failed close-out push relays the work to dell as a git bundle,
and the `verified` stamp now requires the head to be provably on origin.

## What changed

**Claim guard (b)** — a dispatch card for `action.repo: X` is claimable
only when the host can push X:

- `runner-agent.py`: `push_capable()` — `push:<repo>` label in
  `RUNNER_LABELS` is the declared fast path; otherwise a live
  `git push --dry-run origin HEAD:refs/heads/__runner-push-probe` against
  the host's repos.conf checkout, cached `RUNNER_PUSH_PROBE_TTL=300s`.
  URL shape is deliberately not consulted — a `git@` remote with a
  chaba-only deploy key is the exact ADA-0673 bug. Failures leave the
  card queued with a debounced comms note (`{HOST} defers: push guard
  …`). `RUNNER_PUSH_GUARD=0` disables. Aliases share one credential
  (`ada-pi` == `ada-voice`).
- `kanban-dispatch.py`: same guard via `dr.push_probe()` for the
  dell-local drain (`KANBAN_PUSH_GUARD=0`, `KANBAN_PUSH_PROBE_TTL`).

**Patch-relay safety net (c)** — `dispatch_repos.close_out()` still
pushes first; on failure it now calls `relay_session()`: export the
session head as a `git bundle` (shas preserved — format-patch would
rewrite them), base64-POST to the new board-api `POST /patch-relay`,
which validates sha/ref/base64/bundle-header + 8MiB cap and lands
`$DISPATCH_DIR/patch-inbox/<card>-<head10>.bundle` + `.json` sidecar
(repo, branch, base, head, task_id, exit_code, host). Idempotent —
same card+head → same filename. Relay failure is reported alongside
the push failure, not instead of it. `KANBAN_PATCH_RELAY=0` /
`BOARD_API_RELAY_MAX_BYTES` knobs.

**Verify gate** — `merge-sweep.stamp_gate_result()` requires
`dr.head_on_origin()` before stamping verified: head must be an
ancestor of the just-fetched `origin/<base>` ref, or the session
branch ref must equal head on `ls-remote`. Otherwise a
`verify_no_origin` flag is posted and the stamp withheld — no more
done+verified on a stranded branch.

**Fetch fallback order in merge-sweep** — runner ssh session fetch →
origin session-branch ref (runner pushed then died) → patch-inbox
bundle (also when the session is gone entirely). Successful salvage
merges also push `refs/heads/<branch>` best-effort so the branch
literally exists on origin.

**Fleet audit** — `runner-fleet-health.py` probes
`git push --dry-run` per repos.conf checkout on each dispatch host;
judge raises `push-label-false` (declared label contradicts probe) and
`no-push-creds` (dispatch host can push nothing). Queue satisfiability
now also counts type-absent cards (dispatch is the default type).

**Latent bugs fixed along the way**
- `close_out()` returned push failures under `error` while
  `close_out_notes()` read `push_error` — the "branch push failed"
  comms note never fired; part of why ADA-0673 stayed invisible.
- `runner-fleet-health.py` REMOTE_PROBE used `re.search` without
  importing `re` — the `runner_env` (RUNNER_LABELS) probe silently
  died on every host.
- `board-api.py --selftest` expected `"suggested requires options"`
  for a tony-targeted ask, but tony asks auto-fill `[proceed, hold]` —
  the stale assertion now exercises the optionless path via
  `to: ada`.

**Docs** — `docs/kb/new-host-onboarding.md` §5 (probe before declaring
`push:<repo>`), `docs/ssot/kanban/ssot.kanban.yml` (labels field,
runner_hosts env, runner_fleet push-cred state), runbook
`docs/ssot/jobs/kanban/2026-10-16-runner-push-cred-gap.yml`.

## Verification

- `python3 -m unittest discover -s tests/board -p 'test_*.py'` —
  **161 passed** (new: `test_runner_push_guard.py` 8 tests —
  label fast-path, alias, probe pass/fail, missing checkout, guard
  off, non-dispatch exempt, chaba guarded; plus close-out relay,
  relay-unreachable, origin-gate, inbox-fallback, session-gone-no-
  relay, verify-withheld tests).
- `python3 scripts/board/board-api.py --selftest` — **ok**, incl.
  /patch-relay validation cases.
- `node scripts/ssot-validate-all.mjs` — 2541 files, 0 errors.
- `git diff --check` clean. Not committed/pushed — card said do not
  push; the branch lives on this worktree for merge-sweep to land.

## Follow-ups worth carding (not done — outside scope)

- Actually adding `push:<repo>` labels to each host's runner-agent
  drop-in after probing (ops step, needs live host ssh — documented
  in the runbook's `ops:` section).
- macbook/idc03 ada-voice: either grant a push-scoped deploy key or
  leave fetch-only and rely on the relay.

lessons:
  - A git@ remote + sshCommand prove connectivity, not authorization — deploy-key scope is only visible to a live `git push --dry-run`.
  - `git bundle` of a bare sha records no ref and is refused as "empty"; pass a refname (HEAD) or pin a transient ref first.
  - `verified` must mean "provably on origin" — local salvage merges are exactly what hid ADA-0673's stranded branch.
  - Name result dict keys to match what the notes renderer reads (`push_error` vs `error`) — a silent drop kept the incident invisible.
  - board-api `--selftest` had a stale assertion after the tony auto-options change — run it on HEAD before assuming your diff broke it.
