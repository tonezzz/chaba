# dispatch-outcome — mddb-backup disk-headroom guard (2026-11-19)

## What changed

**New canonical script: `stacks/idc03/mddb/mddb-backup.sh`** — the live
`~/mddb-backup.sh` on idc03 (generalized 4-instance script deployed
2026-11-11, card backup-coverage-mddb-ops-mddb-cms-mddb-e) was never
versioned in the repo; this lands it for the first time, at the path the
stack README already declared, with the ENOSPC guards from the card:

1. **Pre-flight df check** — before each instance writes a byte, require
   `free >= max(MDDB_BACKUP_MIN_FREE_GB=15, 2x live db size)` (live size via
   `podman exec stat -c %s /app/data/mddb.db`). Low headroom → skip that
   instance + board alert; run exits non-zero so timer-sentinel flags it.
   Re-checked before the filecopy fallback too.
2. **.tmp + rename** — pulls land as `*.db.gz.tmp`, renamed to `.db.gz`
   only after `gzip -t` passes. Pull streams `podman exec cat | gzip` so
   only compressed bytes hit the host fs (~10x less than the incident's
   raw `podman cp`); uncompressed `podman cp` to `.tmp` remains only as
   the shell-less-image fallback, still under the 2x margin. Failed
   filecopies gzip to `*.db.gz.UNVERIFIED` — never a valid `*.db.gz`.
3. **Retention sweep** — stale `*.tmp*` (>2h) + stale in-container staging
   (>60min) purged BEFORE the df check; `KEEP_COPIES=3` per instance;
   `CAP_GB=80` whole-dir cap that never deletes an instance's newest copy.
4. **Alert path** — board-api `/comment` on `timer-alert-idc03-mddb-backup`
   + `/inbox` (priority high, tags ops/mddb/backup) via `127.0.0.1:8787`;
   degrades to stderr + exit 1 if board-api is down.
5. pg_dump|gzip analog — implemented as `podman exec cat | gzip` streaming
   (mddb isn't postgres; the native `/v1/backup` read-tx snapshot already
   provides consistency).

Also: `stacks/idc03/mddb/README.md` + `stack.yml` updated to mark the file
canonical + document deploy; `docs/ssot/jobs/mddb/2026-11-19-backup-disk-headroom-guard.yml`
records the decision trail. `stacks/idc01/mddb/mddb-backup.sh` left
untouched (leader-era single-instance copy — flagged as follow-up).

## Result

All card requirements implemented and tested locally (stub podman/curl
harness): 7/7 checks — happy path lands `.db.gz` with no `.tmp` residue;
`MIN_FREE_GB` floor refusal and the `2x-expected` margin both skip with
exit 1 writing zero bytes; retention keep-count, dir-cap floor
(newest-per-instance survives), stale-.tmp purge, cp fallback, and
container-down probe all verified. Testing also caught a real bug: bare
`mddb-*` globs match `mddb-ops-*` files — all instance globs now pinned
to `<name>-2*.db.gz` (the YYYYMMDD stamp digit).

## How to verify

- Deploy after merge: `scp stacks/idc03/mddb/mddb-backup.sh idc03:~/mddb-backup.sh`
- Manual run: `systemctl --user start mddb-backup.service` on idc03,
  watch `journalctl --user -u mddb-backup.service -f`
- Guard check: `MDDB_BACKUP_MIN_FREE_GB=999999 ~/mddb-backup.sh` → skips
  all instances, exit 1, alert lands on the timer-alert card + inbox
- Card done-condition "idc03 disk <90% after a week of cycles" is
  observational — watch `df /` and `~/mddb-backups` across the 02:30 runs.

lessons:
- Live ~/mddb-backup.sh on idc03 was unversioned — repo `stacks/idc0X/`
  copies can drift far behind deployed scripts; always diff live vs repo
  before editing.
- Instance-prefix globs collide (`mddb-*` matches `mddb-ops-*`) — pin to
  the date-stamp digit (`<name>-2*`), same trick the original script used.
- Functions invoked under `if`/`||` run with set -e disabled — fine here,
  but don't rely on errexit inside them; return codes are the contract.
- An empty gzip stream passes `gzip -t` — rely on pipeline status
  (pipefail) for truncation, `[ -s ]` only catches zero-byte output.
