# device-telemetry-prune — beacon history retention sweep

## What changed

- **`scripts/device-telemetry/prune.py`** (new, ~60 lines) — nightly
  retention sweep for the MDDB `device-telemetry` collection. Pages
  `/v1/search` at 5000/page, deletes `<dev>/<unix-ts>` keys older than the
  retention window via `/v1/delete-batch` (1000-doc chunks,
  `skip += kept` shift-compensation — same proven pattern as
  `scripts/ada/prune-old-docs.py`). Never touches `<dev>/latest` or
  `_watch/<dev>` armed-watch docs (no ts segment, `_watch` prefix
  guarded). `--dry-run` supported.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — new
  `job:device-telemetry-prune` on **idc03**, `OnCalendar=*-*-* 04:20:00`,
  Persistent, 5m timeout, env `DEVICE_TELEMETRY_RETENTION_DAYS=7`.
- **`systemd/generated/idc03/device-telemetry-prune.{service,timer}`** —
  rendered (CI drift-checks these).
- **`scripts/device-telemetry/install.sh`** — new `install.sh prune`
  mode: installs `prune.py` to `~/.local/share/device-telemetry/` + the
  rendered units, arms the timer, installs NO beacon. Self-contained copy
  (same model as the beacon + log-shipper) so idc03 checkout drift can't
  break it.
- **`docs/ssot/jobs/infrastructure/2026-10-10-device-telemetry-retention-prune.yml`** —
  decision/runbook trail.

## Decisions

- **7d, not 30d** — card metric says `<=7d of history per device`; HA
  logbook already covers long-range history. ~300 docs/day → ~2,100
  keys/device steady-state.
- **idc03, not the beacon host** — the sweep is collection maintenance;
  it runs beside the MDDB leader (:11023). `DEVICE_TELEMETRY_MDBB` env
  overrides if the leader moves.
- **Key-segment expiry, not meta-ts** — the skip rules live in the key
  shape; `<dev>/latest` and `_watch/` docs carry no numeric tail.

## Verified

- Stubbed sweep: 1207 docs → 1200 deleted; `latest`, `_watch/dev`, and 5
  fresh docs untouched; multi-page offset math correct.
- **Live `--dry-run` vs leader** (`:11023`): `would delete 0/1056` —
  collection is ~3.5d old, nothing past window. Confirmed real key shapes
  (`tony-omen/<10-digit-ts>` + `tony-omen/latest` at key-sorted tail).
- `render-jobs.py --check` → OK 46 jobs; units render + env line present.
- YAML valid, `bash -n` clean, committed as 887b6038 on the dispatch
  branch.

## Not done (needs approval — deploy to production idc03)

Arming the timer on idc03 is a production deploy; left for the operator:

```
ssh -i ~/.ssh/id_idc03 idc03          # key lives on tony-omen
cd ~/CascadeProjects/chaba && git pull
scripts/device-telemetry/install.sh prune
systemctl --user list-timers device-telemetry-prune.timer
python3 ~/.local/share/device-telemetry/prune.py --dry-run
```

First real deletes fire ~2026-10-17 once keys age past 7d.
