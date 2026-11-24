# Dispatch outcome — ansible-benchmark-ssot-duplicate-action-430

Card: `ansible-benchmark-ssot-duplicate-action-430` — SSOT hygiene: duplicate
`action` key in `ssot.audit.hosts.yml` (~:430).

## What changed

- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — removed the duplicate
  `action: investigate` line on the tony-dell `known_failed` entry for
  `focus-dispatcher-overnight.service`, keeping `action: verify-next-run`.
- `docs/ssot/jobs/infrastructure/2026-11-24-audit-hosts-duplicate-action-fix.yml`
  — new job doc recording the finding, the decision, rationale, and a
  side observation (below).

## Decision

Kept `verify-next-run`, dropped `investigate`. The entry's own `reason`
ends "next scheduled run verifies"; the failure was already diagnosed
(ExecStartPre `git pull` exit 128, script verified clean manually
2026-10-09) so nothing remains to investigate; and the tony-omen entry for
the same unit uses `verify-next-run` with an analogous reason. Git blame
shows both `action:` lines were written in the same bulk commit
(962fc698331, 2026-11-09) — a same-edit artifact, not staged intent. Note
the field is documentation-only: `audit-hosts.py` and the ansible
delta template consume only `name`, so the bug had zero runtime effect —
it was a latent correctness/trap issue for the next human reader.

## Side observation (not fixed — out of scope)

`focus-dispatcher-overnight.{service,timer}` on tony-dell are `.parked`
and the unit is absent from systemd; the timer migrated to idc03
2026-10-16/19 (OPS-0725). The whole tony-dell `known_failed` entry is
likely stale — flagged in the job doc for a hygiene pass.

## Verification

- Custom dup-key YAML loader over the file: parses clean, 0 duplicate
  keys (previously exactly 1).
- `node scripts/ssot-validate-all.mjs`: 6282 files, 0 errors;
  `infrastructure/ssot.audit.hosts.yml` explicitly Valid (346 pre-existing
  bloat warnings, unrelated).
- `python3 scripts/ssot-validate-refs.py`: 6287 files parsed, no broken
  refs.
- `python3 scripts/audit-hosts.py --host tony-dell --no-ssh`: ran
  end-to-end against the edited SSOT; normal pre-existing drift deltas
  only (the `action` field is not consumed by the differ).

## How to verify

`git show` the diff on `ssot.audit.hosts.yml` (one line removed), or
re-run the dup-key loader snippet from the job doc. Card comms posted.

lessons:
- SSOT `known_failed[].action` is documentation-only — audit-hosts.py and the ansible port read only `name`; duplicate `action:` keys parse silently (SafeLoader last-wins) with zero runtime signal. A dup-key YAML loader is the only detector.
- When a duplicated mapping key appears, `git blame` on both lines distinguishes same-edit artifact (identical commit) from staged intent — here it was one bulk board-api snapshot commit.
- `audit-hosts.py --host <h> --no-ssh` validates an edited ssot.audit.hosts.yml end-to-end from the host itself — cheap consumer-side proof without touching other hosts.
- known_failed entries can go stale when units are .parked/migrated (OPS-0725 moved focus-dispatcher-overnight to idc03) — parked units never fail so the entry suppresses nothing; worth a hygiene sweep.
