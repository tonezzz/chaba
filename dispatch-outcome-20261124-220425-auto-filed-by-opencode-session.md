# Dispatch outcome — audit-oc-mutating-command-1bbtyha8

## What the card flagged

Auto-filed by `opencode_session_audit.py` (2026-11-07): opencode session
`ses_e827708b4ffeNCHdk31bBtYHA8` ("Storage inventory and candidate
classification idc02", agent `storage-dryrun` — a read-only lane-eval
profile) recorded "mutations: writes".

## Verdict: benign — classifier false-positive, now fixed

Evidence chain:

- `evals/opencode-lane/reports/2026-11-07-session-audit.json` — the two
  "writes" were `python3 -c` output-dump commands, **both status=error
  with the permission-deny signature**. 5 denied calls total, 0 executed
  mutations, 0 deletes/commits/pushes.
- `evals/opencode-lane/runs/p1-storage-dryrun-idc02-20261027-202449/` —
  lane verdict **pass**, `artifact_landed: true`. The artifact landed
  because `artifact.mode: message`: the runner
  (`finish_opencode_lane` → `opencode_profiles.extract_artifact`)
  extracts the JSON from the agent's final message — the file-write
  attempts were unnecessary model noise, not an executed scope breach.
- The storage-dryrun profile denies `write`/`edit` tools and its bash
  allowlist has no `python3` — the gate worked exactly as designed.

Root cause: the audit counted every mutation-*classified* bash command
toward the cardable `mutating_command` finding regardless of status.
Permission-denied calls never ran. All three `mutating_command` cards
from that audit run (`1bbtyha8`, `0b3n5bce`, `aahmnvt5`) are this same
denied-only class.

## What changed (commit 20ef6d07527 on dispatch branch)

- `scripts/devnest/opencode_session_audit.py`
  - mutation entries (bash classes + non-completed write/edit) now carry
    `denied: true` when the call was permission-denied;
  - the cardable `mutating_command` finding and the "mutation outside
    profile scope" flag compute over executed calls only — non-denial
    errors still count (partial execution possible);
  - denied-only attempts emit a `severity: info` finding ("blocked by
    permission gate") — visible in reports, never carded;
  - denied bash write-classified commands no longer feed redirect
    targets into `write_paths`, so a denied `cmd > /path` can't mint a
    bogus `artifact_not_durable`/`missing` finding.
- `tests/devnest/test_opencode_session_audit.py` — 2 new tests
  (denied-only → info + no artifacts; mixed denied-write +
  completed-delete → high finding names only the executed class).
  **22/22 pass.**
- `docs/ssot/jobs/devnest/2026-11-24-opencode-audit-denied-mutations.yml`
  — verdict, root cause, fix, follow-ups trail.

## Follow-ups (not done here — sibling cards)

- `audit-oc-mutating-command-0b3n5bce` and `-aahmnvt5` are the same
  denied-only class (ops-readonly urllib/curl POST attempts) — safe to
  close as benign; this fix prevents recurrence.
- `audit-oc-denied-tool-muijr5b4` (113-denial storm) is a real
  friction/profile-allowlist signal — untouched, still valid.

## How to verify

- `python3 -m unittest tests.devnest.test_opencode_session_audit` → 22 OK
- `python3 scripts/devnest/opencode_session_audit.py --session
  ses_e827708b4ffeNCHdk31bBtYHA8` on idc02 → `mutating_command` finding
  now severity `info` ("denied mutation attempt(s) blocked by
  permission gate: writes"), no card would file.
- Merge state: upstream (origin/master, +56 commits) has not touched
  the audit script or its tests — clean merge expected.

lessons:
- opencode_session_audit.py counted permission-denied bash commands as mutations — denied calls never execute; check status+DENY_SIGNATURE before treating a classified command as a mutation.
- storage-dryrun/ops-readonly lane artifacts land via message-mode (runner extracts final-message JSON) — agents don't need, and must not, write files.
- All three mutating_command audit cards from 2026-11-07 were the same denied-only false-positive class; sibling cards 0b3n5bce/aahmnvt5 can close as benign.
