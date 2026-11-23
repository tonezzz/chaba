# dispatch-outcome: disk-guard-ssot-enforce

GOAL: close the enforcement gap — disk-trend-watch.py must honor
ssot.audit.hosts.yml `expected_resources.max_root_disk_percent` per host
and the 15 GiB mddb guard floor on `/`, in addition to flat 90%. Also flag
underused mounts. Parity with ansible disk-headroom.yml. — DONE.

## What changed

### scripts/ada/disk-trend-watch.py
- `load_hosts()` now returns per-host config `{ip, max_root_pct}` read
  from `expected_resources.max_root_disk_percent` (85 on
  tony-dell/tony-omen/mn01, 90 on macbook, default = flat CRIT_PCT for
  hosts that don't declare one — same defaulting as the j2).
- `judge(host, mount, t)` returns ok|fill|warn|critical:
  - `critical`: pct >= flat 90 on any real mount (unchanged).
  - `fill`: projected full <= FILL_D (unchanged).
  - `warn` (new, `/` only): pct >= host's declared
    max_root_disk_percent, OR avail < DISK_TREND_MIN_FREE_GIB (15 GiB,
    same floor as mddb-backup's MDDB_BACKUP_MIN_FREE_GB guard).
  - warn cards: `disk-auto-<host>-root`, title "Disk <host> / over
    limit", priority medium (still escalates to high after ESCALATE_H),
    auto-close to done when / returns under the ceiling and above the
    floor.
- `is_underused()`: pct < 50% OR avail > 100 GiB — report-only signal
  (per-mount `underused` flag, `<== UNDERUSED` marker in --report output,
  `N underused` count in summary + meta). Never opens cards — it feeds
  the storage-rebalance-underused capacity-planning card.
- Report rows gain `underused` and per-host
  `ssot_max_root_disk_percent` (parity with the j2's emitted fields).
- New env knobs: DISK_TREND_MIN_FREE_GIB (15),
  DISK_TREND_UNDERUSED_PCT (50), DISK_TREND_UNDERUSED_FREE_GIB (100).
- Selftest extended: synthetic tony-dell at 87% -> warn card; idc03
  fixture at 80%/12 GiB free -> floor warn card; 40% host -> underused.

### ansible/playbooks/disk-headroom.yml + templates/disk-headroom.j2
- New vars `underused_pct: 50` / `underused_free_gib: 100`; each rendered
  mount row gains `underused: bool` and the host report gains a top-level
  `underused_mounts:` list — same thresholds as the watcher, keeps the
  two instantaneous surfaces in parity (also lands the monitoring ask of
  the sibling card storage-rebalance-underused).

### docs/ssot/jobs/infrastructure/2026-10-05-disk-trend-watch.yml
- `design.alerts` updated with the warn tier + underused signal;
  `verification` gains a 2026-11-23 entry.

## Verification
- `python3 scripts/ada/disk-trend-watch.py --selftest` -> PASS: 92%
  critical (high), 87% tony-dell warn (medium, note cites
  max_root_disk_percent 85), 12 GiB-free idc03 floor warn, underused
  flagged in report only.
- Fixture run: tony-dell / at 88% (the exact missed case from the card
  brief) now opens `disk-auto-tony-dell-root` as warn; a pre-existing
  warn card auto-closes at 60%; flat-90 crit unchanged; con01/mn01
  flagged underused.
- `ansible-playbook playbooks/disk-headroom.yml --syntax-check` OK;
  j2 rendered standalone produces correct warn/underused verdicts and
  valid YAML.
- `py_compile` clean; jobs YAML parses.

## Expected first live effect
tony-dell / is already open as a `fill` card (88%, ~2.8d). If growth
stops while pct stays >= 85 the card now stays flagged as warn ("over
limit") instead of auto-closing — that is the closed gap. Warn cards
push only on fresh open, so no re-ping for the already-open card.

lessons:
- disk-trend fixture/selftest hosts aren't in ssot — name a fixture host
  after a real ssot host (tony-dell) to exercise per-host thresholds.
- disk-headroom.j2 uses ansible-only filters (to_json/to_nice_yaml) —
  stub them when test-rendering with plain jinja2.
- judge() order matters: fill is checked before warn so a
  filling-over-limit mount keeps the trajectory reason.
- existing disk-auto-* cards in review update in place — a warn
  transition rewrites the title to "over limit" without a new push.
