# Dispatch outcome — focus-dispatcher-overnight-promise-code-fix

## What was wrong

`focus-dispatcher-overnight.service` on tony-omen ended
`[overnight] completed with errors` / `Result=exit-code`. Journal showed
`TypeError [ERR_INVALID_ARG_TYPE]: The "code" argument must be of type
number. Received an instance of Promise` at
`scripts/ssot-optimize-to-inbox.mjs:188` after validation reported
`Total errors: 0`. All three defects trace to commit `857612a507`
(2026-11-26, "Route generated focus-inbox writes from non-writer
checkouts via board-api") — the first nightly run after it reached the
hosts is the one that failed:

1. **`scripts/ssot-optimize-to-inbox.mjs`** — `process.exit(main())`
   where `main` is `async`. On Node >= ~20 `process.exit` validates its
   argument and throws on a Promise (omen runs /usr/bin/node v24.22.3;
   Node 18 silently accepts it — verified locally: v22.22.1 throws,
   v18.19.1 exits 0). Fixed: `main().then(code => process.exit(code))
   .catch(err => { console.error(...); process.exit(1); })` — awaits the
   Promise, passes the resolved numeric code, rejections still exit 1.
2. **Same file, second bug** — `PROJECT_ROOT = join(dirname(...), "..",
   "..")` resolved one level too high (parent of the checkout, e.g.
   `/home/tony/CascadeProjects` on omen), so WARNINGS_FILE never existed
   ("no warnings file; nothing to do"), `checkoutRole()`'s
   `git -C <parent>` printed "fatal: not a git repository", and the
   warnings→inbox bridge was a silent no-op on every host since the
   commit. Fixed to `join(dirname(...), "..")`.
3. **`scripts/overnight-focus-review.py`** — `focus-dispatcher.py
   --advance` exits 1 on non-writer checkouts: the same commit made
   cli.py force `--dry-run` for stamped exec/readonly/job roles, and
   dry-run advance prints "requires a real run" → `sys.exit(1)`. The
   orchestrator now resolves `checkout_role(REPO)` and skips `--advance`
   when the role is stamped non-served (recorded in the status steps);
   unstamped checkouts keep legacy behavior, served still advances.
4. **`docs/ssot/jobs/infrastructure/2026-11-27-ada-review-refresh-prune-timeout.yml`**
   (found during verification) — commit `ad5e9f0e4b` landed it with
   `- path: desc` list items whose continuation lines sit at key indent
   (invalid YAML: "could not find expected ':'") and no required
   `title:`. `ssot-validate-all` went to 1 error and the pipeline
   aborted at its gate on every synced host. Rewrote items as
   `filename — desc` scalars and added title/subtitle/icon.

## Result / verification

Deployed the three files to tony-omen's `~/CascadeProjects/chaba` and ran
`systemctl --user start focus-dispatcher-overnight.service` four times
(two earlier runs surfaced contributors 3 and 4). Final run
2026-11-27 11:22–11:27 (+07):

- `Result=success`, `ExecMainStatus=0`, `ActiveState=inactive`
- journal ends `[overnight] completed` (not "with errors"), no TypeError
- `overnight-status.json`: all 9 steps rc=0 incl. the recorded
  `--advance` skip (`chaba-role=exec non-writer checkout`)
- `reports/REMAINING_FOCUS_PLAN.md` regenerated 11:27
- validation: 7867 files, 0 errors
- side effect (intended): ssot-optimize-to-inbox posted 140 one-time
  inbox drafts via board-api `/inbox` on run 1 (deduped by
  `~/.local/state/ssot-optimize-to-inbox-posted.json` thereafter)

Deployed files were restored to HEAD on omen afterwards so
`chaba-repo-sync` pulls the merged fix cleanly. Permanent landing is via
this branch merge — commit `d65848a9c0f` on
`dispatch/20261127-103140-focus-dispatcher-overnight-ser` (4 files:
two scripts, the repaired job yml, new trail doc
`docs/ssot/jobs/infrastructure/2026-11-27-overnight-focus-promise-exit-fix.yml`).

Local checks: `node scripts/ssot-validate-all.mjs` in worktree —
7978 files, Total errors: 0. `python3 -m py_compile
overnight-focus-review.py` OK. Pre-commit hooks (SSOT validation +
optimize gate) passed on commit.

## Notes for the next reader

- idc03 (served) and tony-dell/mn01 (exec) run the same pipeline; the
  TypeError and the dead inbox bridge affected all of them — their
  timer-alert cards should clear on next runs after this merges.
- The `--advance` skip means non-writer hosts no longer attempt focus
  advancement at all; that is by design (mutations can't commit there).
- omen's checkout had unrelated pre-existing dirty/staged drift
  (telemetry-ha-push.py, ai-hub-extension files) — untouched.

lessons:
- `process.exit(asyncFn())` throws ERR_INVALID_ARG_TYPE on Node >= ~20 but silently exits 0 on Node 18 — version-dependent bugs hide on older nodes; check `node --version` per host before trusting a green run.
- `join(dirname(import.meta.url), "..", "..")` from `scripts/` escapes the checkout — sibling scripts use one `..`; always verify resolved paths print correctly on the target host.
- overnight-status.json (`~/var/chaba/`) records per-step returncodes — faster than journal archaeology for "which step failed".
- A dispatch worktree can be missing files that exist on newer master; `git fetch origin master` + merge before fixing unrelated breakage found during verification.
- systemd `Type=oneshot` + `systemctl start` blocks for the whole run — background the ssh or poll `systemctl show` instead of waiting on the start call.
