# key-watch: credential expiry/quota monitor (SEC-0499)

Built the sources monitor from card `key-watch-monitor`. Committed on the
dispatch branch as `bfa6b7ca` — not pushed, not deployed (arming is a
separate gated step).

## What changed

- `scripts/ops/key-watch.py` — the monitor. Groups declared slots by host,
  ships one python3 probe per host over ssh (`python3 -`), so secret
  values never leave their host — returns masked fp + verdict only.
  Checks: OR `/api/v1/auth/key` (label/expires_at/usage/limit_remaining +
  cross-slot fingerprint drift), HA LLATs (`GET /api/` per stored token,
  401/403 = dead), `CF_API_TOKEN` (verify → zones fallback for the cfat_
  scoped-token quirk), and Gemini quota via a 24h MDDB ops-event scan
  (`ada-ha-events-{kk,tony,michael}`, QuotaExhausted markers).
  `--gemini-probe` optionally adds the ~1-token generateContent probe.
- Thresholds: expiry <48h or usage/limit ≥80% → LINE warn via
  ada-line-relay `:8912/send` (direct loopback, ssh idc03 fallback —
  chaba-nag's path); dead/expired/limit_remaining=0 → alert + auto-filed
  `keywatch-*` incident card via board-api, auto-closed on recovery.
  Quiet hours 00–07 ICT defer LINE only. Every run emits one
  `kind=ops-event` doc (`type: key_watch`) into `ada-ha-events-tony`.
- `systemd/key-watch.{service,timer}` — 6h (`00,06,12,18:10`) + OnBootSec
  5min, Persistent. Host-agnostic `%h` paths; intended host is **idc03**
  (canonical writer post-migration — the card's "tony-dell" target predates
  the migration; dell was powered off 2026-10-20).
- `tests/ops/test_key_watch.py` — 20 tests, all pass.
- `docs/ssot/ssot.procedures.yml` — `key-watch` entry ("what monitors our
  keys" now has a system answer).
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — `key-watch.timer` in
  idc03 expected_services so drift-reconcile will notice a silent disable.
- `docs/ssot/jobs/infrastructure/2026-10-22-key-watch.yml` — trail doc.

## Live dry-run findings (2026-10-22 ~19:55 ICT, from idc02)

The monitor earns its keep immediately:

- **ALERT: fleet OR key …5528 has `limit_remaining=$0`** on all 3 slots
  (dell/omen/idc03) — the exact 2026-10-12 failure mode, live right now.
- **ALERT: `ha-mdev-omen`** — michael-dev LLAT on tony-omen is stale
  (401, fp …HfN4 vs live …i2no on dell).
- `cfat_` tokens confirmed live via the zones fallback (verify rejects
  them as documented); `cfut_` live via verify.
- `cf-idc01` unreachable by ssh from idc02 (idc01 tailscale off — works
  from idc03, so placement on idc03 covers it). Reported `unknown`, not
  alerted.
- Gemini ops-scan: 0 quota markers in 24h across all 3 collections.
- mn01 slots needed `michael-ha.taila0626a.ts.net:8123` (no local HA) —
  fixed in the watchlist.

## Verify

```
python3 scripts/ops/key-watch.py --selftest   # fixture through judge path
python3 -m unittest tests.ops.test_key_watch  # 20 tests
python3 scripts/ops/key-watch.py --dry-run    # real probes, zero writes
systemd-analyze calendar '*-*-* 00,06,12,18:10:00'  # next elapse verified
```

Install (post-merge, on idc03):

```
cp systemd/key-watch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now key-watch.timer
journalctl --user -u key-watch.service   # first boot run
```

Board: status + findings posted to `key-watch-monitor` comms.
