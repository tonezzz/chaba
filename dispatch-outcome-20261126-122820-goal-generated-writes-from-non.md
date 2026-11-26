# Dispatch outcome — exec-checkout-generated-writes-focus-inb-da698a

## What changed

Generated focus-inbox writes from non-writer chaba checkouts now route
through board-api `POST /inbox` (the unified write door) instead of
dying as uncommitted files in exec working trees.

New shared lib:

- `scripts/lib/checkout_role.py` — reads `<gitdir>/chaba-role`
  (served|exec|readonly|job|branch|experiment).
- `scripts/lib/inbox_door.py` — `local_writable(repo)` (True only for
  served or unstamped checkouts) + `post_inbox()` / `emit()` /
  `emit_doc()`. `emit_doc` posts a whole focus-inbox YAML doc's focus
  fields and dedupes on sha256(session|label|text) in
  `~/.local/state/inbox-door-posted.json` — needed because the remote
  inbox has no local open_item view to glob.

Guarded producers (file write kept for served/unstamped; API post on
stamped non-writer):

- `scripts/audits/gh-runs-watch.py` — `--api` mode + auto-fallback when
  `--git` runs off-writer.
- `scripts/audits/ha-auth-watch.py` — emit_doc; local-glob dedupe only
  on writable checkouts.
- `scripts/mcp-health-to-inbox.py`, `scripts/mcp-health-snapshot.mjs`
  (also fixed hardcoded `chaba-tony-dell` paths + 6h alert throttle),
  `scripts/ssot-optimize-to-inbox.mjs` (was hardcoded to dell served
  path — now resolves own checkout + api mode),
  `scripts/mcp-link-monitor.py` (link-down + drift alerts),
  `scripts/arp-inventory-scan.py`, `scripts/check-serve-config.py`,
  `scripts/board/board-invariants.py`, `scripts/ada/session-audit.py`,
  `scripts/devin/render-handoff-inbox.py` (API mode + sha dedupe state,
  GC disabled remotely), `scripts/worktree-sync.py`,
  `scripts/overnight/promote-reports.py`,
  `scripts/mddb-binlog-canary.py`.
- Non-writer skips rather than posts (lifecycle/GC semantics the door
  can't express): `scripts/report/report-watch.py` exits early
  (`REPORT_WATCH_FORCE=1` override), `scripts/focus_dispatcher/cli.py`
  suggest-only, `scripts/ada/backup-mddb-banks.py --git` no-ops.

Already-OK producers verified (already post via /inbox): netdata alarm
notify, ops/netdata-nodes-watch, retry-storm-watch,
scenario-runner-drift-check, served-checkout-watchdog,
system-report-watchdog, job-dispatcher, host-ready-check.

SSOT trail: `docs/ssot/jobs/board/2026-11-26-exec-checkout-inbox-door.yml`.

## Exec-checkout audit

- omen `~/CascadeProjects/chaba` = exec; 194 dirty entries / ~2918 dead
  focus-inbox files accumulated. mn01 ssh is sftp-only (no shell).
- idc03 `~/CascadeProjects/chaba` = exec (~194 untracked inbox files);
  `chaba-tony-dell` = served writer.
- dell `~/CascadeProjects/chaba` = exec (497 untracked focus-inbox +
  modified `backups/ada-memory/*.json`); `chaba-tony-dell` = readonly
  mirror — producers hardcoding that path (mcp-health-snapshot,
  ssot-optimize-to-inbox, session-audit default) now resolve their own
  checkout instead.

## Verification

- `post_inbox`/`emit_doc` round-trip from this worktree: True.
- Fired test alert **on tony-omen** via the new lib against
  `~/CascadeProjects/chaba` (role=exec → local_writable False → API):
  `emit: api`. File
  `2026-11-26-125957-omen-exec-checkout-test-alert.yml` confirmed in
  idc03 `~/CascadeProjects/chaba-tony-dell/docs/ssot/focus-inbox/`
  (kanban-commit picks it up). Omen tree untouched (wrote only /tmp).
- All touched Python files `py_compile` clean.

## Caveats / follow-ups

- Changes are committed on the dispatch branch only (no push per dispatch
  rules). Exec checkouts pick them up via chaba-repo-sync after merge —
  until then omen still runs old file-writing code.
- mcp-health-snapshot.mjs / ssot-optimize-to-inbox.mjs are .mjs — no
  node on this host to syntax-check; reviewed manually.
- focus_dispatcher `state.py` still moves inbox files to processed/ but
  only runs when dispatching, which is already gated off non-served.
- mn01/idc02 exec checkouts not shell-audited (mn01 sftp-only); same
  code paths apply once synced.

lessons:
- board-api /inbox has no open_item/dedup view — producers that deduped
  by globbing local inbox files need a local state-file sha dedupe
  (inbox_door.emit_doc) when routed remotely.
- Several .mjs producers hardcoded `/home/tony/CascadeProjects/
  chaba-tony-dell` — dead writes off idc03; resolve repo root from
  import.meta.url instead.
- `continue` inside `if reasons:` (not a loop) broke mddb-binlog-canary
  compile — restructure to if/else when injecting an early API branch.
