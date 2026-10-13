# Dispatch outcome — cms-nest-stale-investigation (20261013-192549)

## What was wrong

`nest-mgr.service` on tony-dell, tony-omen, and idc03 was **alive and
publishing every 15 min** — but to the **old mddb primary :11023**. The
`ada-cms-*` collections moved to mddb-cms **:11027** in the MEM-0545 split;
:11027's copies of the nest-* docs were seeded by a one-time migration copy
at ~01:0x UTC on 2026-10-13 and never written again — which is exactly the
`last_run` timestamp cms-auto-health reported as stale.

- Repo `stacks/services/nest-mgr/nest-mgr.py` already had the :11027 fix;
  the installed copies under `~/.local/share/nest/` were never updated.
- `install.sh` used `systemctl --user enable --now`, which is a no-op on an
  already-running unit — even re-running it would not have applied the fix.
- The "tick error: Connection refused" journal bursts (~15:34–15:40 +07,
  synchronized across all three hosts) were a brief :11023 outage window,
  unrelated noise — the daemon recovered and kept writing to :11023.
- Evidence of split-brain: :11023's copy of `nest-tony-dell` showed
  `last_run=12:23Z` (fresh) while :11027's showed `01:02Z` (frozen).

## What I changed

- Ran `stacks/services/nest-mgr/install.sh tony-dell tony-omen idc03`
  (installs the :11027 repo copy + unit on each host).
- `systemctl --user restart nest-mgr.service` on all three hosts — the step
  install.sh was missing.
- Patched `install.sh` (worktree diff): `enable` + explicit `restart` on
  both the local and ssh paths, so re-installs actually take effect.
- Wrote job trail `docs/ssot/jobs/nest/2026-10-13-nest-mgr-mddb-cms-cutover.yml`.
- Commented findings on `cms-auto-nest-tony-dell` and `cms-auto-nest-tony-omen`.

## Threshold audit — sane, no change

`cms-auto-health.py` marks stale at one interval + 30m grace (~45m for a
15m job), with a page-freshness rescue via `ada-cms-pages` updatedAt. Both
signals were genuinely stale on the serving backend — the alert was a true
positive, not threshold noise. The cards auto-close (`column=done`) on the
next kanban-sync run (~15 min cadence).

## Verify

```
curl -s -X POST http://100.102.134.91:11027/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"ada-cms-automation","key":"nest-tony-dell","lang":"en"}' \
  | python3 -c 'import sys,json; print(json.loads(json.load(sys.stdin)["contentMd"])["last_run"])'
# -> timestamp within the last ~15 min for nest-tony-dell / nest-tony-omen / nest-idc03
```

lessons:
- `systemctl --user enable --now` does NOT restart a running unit — install/upgrade scripts for long-lived daemons need an explicit `restart` or the new binary never loads.
- After a backend migration (mddb :11023 -> :11027 split), installed copies under `~/.local/share/` can silently lag the repo fix and keep writing to the retired endpoint — alerts fire on the new backend while the daemon looks healthy.
- stdout `print()` is block-buffered under systemd — the journal showed only stderr "tick error" lines; absence of "published" lines does not prove the loop stopped.
- Simultaneous "Connection refused" bursts on multiple hosts point at the shared remote (mddb) bouncing, not per-host failures.
