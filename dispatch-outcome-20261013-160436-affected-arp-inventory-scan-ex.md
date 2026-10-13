# Dispatch outcome — timer-finding-reporter-semantics (OPS-0581)

## Decision: Option A — exit code = "did the run complete?"

~10 fleet jobs exited 1 to mean "I found something", so every finding
fired a red `timer-alert-*` card from the sentinel — indistinguishable
from a crash. Standardized on **exit 0 on a completed run regardless of
findings**; findings stay on their own channels (report file,
focus-inbox, ops-event, CMS page). Nonzero is now reserved for runs that
did not complete. Documented in `docs/kb/timer-expectations.md` ("Exit-
code contract") + `docs/ssot/jobs/infrastructure/2026-10-13-timer-exit-
code-contract.yml`. Option B (kind: finding-reporter in ssot.audit.hosts)
was rejected — rationale in the KB doc.

## mddb-memory-standard investigation (asked for specifically)

**Real breach, not a silent fire or a bug.** idc03 journal (06:37 and
12:37 runs, 2026-10-13) shows `memory-standard VIOLATION` with 12
violations: draft_ratio developer-tony 17.0x, devin-handoff 2.8x,
personal-nhong 9.0x; oldest-draft >7d on general/people/personal-tony/
personal-kk/purchase/projects-tony/developer-tony/devin-handoff; plus
one transient `vector-search probe failed: HTTP 400` (re-verified the
probe returns 200 today — momentary API error). The "no breach text in
journal tail" was **output ordering**: violations print at the top of
the report and ~30 stat lines push them out of a tail view. The script
now tail-echoes `verdict: VIOLATION (N violation(s))` as its last line.

## Changes (branch dispatch/20261013-160436-affected-arp-inventory-scan-ex, commit a3fa229e)

| Job | Fix |
|---|---|
| `arp-inventory-scan` (tony-omen) | `scripts/arp-inventory-scan.py` — dropped exit 1/2 finding exits |
| `chaba-audit-watchdog` (tony-omen) | `scripts/audit-watchdog.mjs` — finding paths exit 0 (focus-inbox alert + chaba-event are the signal) |
| `chaba-audit` + `chaba-audit-full` (idc02) | `scripts/audits/run.mjs` — audit-failure path exits 0; crash path still exits 1 |
| `mddb-memory-standard` (idc03) | `scripts/ada/memory-standard.py` — exit 0 on completed sweep + trailing verdict line; exit 1 only when every bank read fails (no verdict, e.g. MDDB down) |
| `ada-recall-canary` (idc03) | `scripts/ada/recall-canary.py` — exit 0 on completed run; misses now emit an ops-event doc to `ada-ha-events-<instance>` (was journal-only); exit 1 when zero canaries verifiable + search errors |
| `ada-scenario-{research,cms,memory,reports,tools,casting}` (idc03) | `stacks/services/ada-scenario-runner/scenario-suite-run.sh` — translates benchmark exit-1-with-final-report (`**Score:` marker) to 0; exit 1 without marker stays a real crash |

Also: `known_failed` reasons in `ssot.audit.hosts.yml` updated (converted
jobs annotated as rollout cover — a fresh failure is a real crash;
`ada-scenario-smoke`/`ada-scenario-full`, `ada-memory-sync`,
`mddb-vector-reindex` marked RESIDUAL finding-reporters to migrate when
next touched). `ssot.procedures.yml` trigger + scenario-runner README
updated. Job record: `docs/ssot/jobs/infrastructure/2026-10-13-timer-
exit-code-contract.yml`.

## Verify

- `recall-canary.py` live run here: 9/12 pass, 3 misses → ops-event doc
  emitted to `ada-ha-events-tony`, exit 0.
- `memory-standard.py` live run: VIOLATION (11) → ops-event + verdict
  line, exit 0.
- Wrapper stub tests: exit1+marker→0, exit1-no-marker→1, exit0→0.
- `node --check` / `py_compile` clean; `ssot-validate-all.mjs` 2242/0 errors.

## Deploy notes

- Script changes reach hosts via `chaba-repo-sync` after merge — no unit
  changes needed anywhere.
- **idc03 wrapper exception:** `scenario-suite-run.sh` runs from
  `~/.local/share/ada-scenario-runner/` (self-contained by design) —
  deploy it with `install.sh` on idc03 or copy the file over.
- The 10 open `timer-alert-*` cards for these jobs got a triage comment;
  verify next run is green, then close.
