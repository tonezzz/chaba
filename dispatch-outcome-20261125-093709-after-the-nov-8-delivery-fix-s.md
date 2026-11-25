# Dispatch outcome — system-report-18-missing-nodes

Card: `system-report-18-missing-nodes` (triage the 18 missing + 3 unreachable report nodes).

## Verdict

All 18 "missing" nodes are **alive** — none are dead, decommissioned, or moved. They were a
meta-delivery gap (reports/* is gitignored; producer metas never reached the
con01 renderer), already fixed 2026-11-18 by `pull-report-metas.sh`
(`docs/ssot/jobs/infrastructure/2026-11-18-report-meta-pull.yml`). Verified
live on con01: every listed node has a fresh meta dated 2026-11-23/24.
`audit-hosts/macbook` unreachable is expected (`offline_ok` laptop);
tony-omen/mn01 were transient and now report `delta`.

## What was actually broken (and fixed)

1. **L3 renderer crash** — `chaba-system-report.service` on con01 failed
   daily since 2026-11-21 with `KeyError: 'no-config'` (mcp-inventory began
   emitting the new `no-config` status; `_BADGE`/`_WORST` in
   `scripts/report-system.py` were never updated). Served system-report.yml
   frozen at 2026-11-20 — this, not missing producers, is why the watchdog
   picture looked wrong. **Fix in worktree**: added `no-config` to both
   maps (informational, worst=1).
2. **Watchdog offline_ok gap** — `system-report-watchdog.py` counted
   `audit-hosts/macbook` unreachable as red forever. **Fix**: `resolve_node()`
   now emits `offline_ok`; watchdog exempts `unreachable`+`offline_ok`, with
   a registry fallback for pre-flag yml.
3. **ha-live 502** — tony-omen rebooted ~11-23; `ha-live.service` was
   disabled+inactive (never enabled since the 10-19 unit was written).
   Restarted + enabled; `:8444` returns 200.
4. **ada-stt-con01 false positive + broken mn-bot STT** — con01 ada-stt was
   stopped+disabled 11-23 (absorber shed). Last consumer pointer
   (`telegram-mn-bot.env` TG_WHISPER_URL on idc03) repointed to healthy
   idc03-local `127.0.0.1:8914`; `ada-tg-relay-mn` restarted. SSOT health
   entry marked `disabled: true` with re-enable notes.

## Files changed (worktree, uncommitted — dispatch rules)

- `scripts/report-system.py` — `no-config` badge/worst
- `scripts/lib/report.py` — emit `offline_ok` in resolved state
- `scripts/report/system-report-watchdog.py` — exempt offline_ok unreachable
- `docs/ssot/infrastructure/ssot.health.home.datastore.yml` — ada-stt-con01 disabled
- `docs/ssot/jobs/infrastructure/2026-11-25-system-report-missing-nodes-triage.yml` — full triage record

## Live actions taken (reversible)

- `systemctl --user start+enable ha-live` on tony-omen (verified 200)
- repointed `~/.config/secrets/telegram-mn-bot.env` on idc03 (backup `.bak-con01stt-20261125`), restarted `ada-tg-relay-mn`
- filed card OPS-1367 for the 4 still-dead omen units (plug-watch,
  ha-stall-watchdog, playlive-chrome, yolo-detect)

## Open items

- 1 invalid SSOT file on idc03 served checkout (overnight ssot_validate
  step) — not reproducible in this worktree (6417/6417 valid); tonight's
  ORCHESTRATION.json will name it.
- mn01 meta-pull flaked once (rc=23) — metas still fresh via other roots.

## Verify

- After merge + repo-sync: next `chaba-system-report.timer` run (06:45)
  completes without KeyError; served yml `generated_at` fresh.
- Watchdog `--no-alert` on tony-dell: macbook drops from red set.
- `curl https://tony-omen.taila0626a.ts.net:8444/` → 200 (already verified).

lessons:
- New status-enum values must be added to EVERY consumer map — `no-config` landed in lib/report.py STATUSES + mcp-inventory but not report-system.py's _BADGE/_WORST, silently freezing the L3 report for 4 days. Grep for sibling maps when extending status vocab.
- system-report-watchdog reads a rendered yml that may predate new fields — carry exemptions in the registry and read it as fallback, not only per-node flags.
- Post-reboot user units on tony-omen that were never `enable`d stay dead forever (Restart=always doesn't survive boot if disabled) — the 10-19 evacuation wrote ha-live.service but apparently never enabled it.
- con01 ada-stt was shed 11-23 but one consumer env (telegram-mn-bot) kept pointing at it — consumer-reference audit caught a real STT outage for the mn-ha lane.
