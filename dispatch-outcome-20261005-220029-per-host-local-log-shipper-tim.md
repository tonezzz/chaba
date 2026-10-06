# logs-local-shippers — per-host local log-shipper timers

## What changed

- **`scripts/ada/log-shipper.py`** — added `--self` mode (ships only the
  local host's journals; fleet name from `LOG_SHIP_HOST` or hostname) and
  `_is_local()` so any host named in `--hosts` that equals the local
  machine runs `journalctl` locally instead of ssh. New `ha-cli-ssh`
  transport for michael-ha (`ha host logs` over key-auth ssh with a
  collector-side ts+hash dedup file, since HAOS exposes no journald
  cursor protocol). `ship-state` docs now carry a `lane` field
  (`local`|`ssh`|`ha-cli-ssh`). `DEFAULT_HOSTS` += idc03, michael-ha.
  MDDB default fixed to the live leader `http://100.102.134.91:11023/v1`
  (the committed `100.74.146.0` is dead — that tailnet node no longer
  serves MDDB; docs' "idc01" label for the leader is stale, it actually
  runs on tailscale node idc03).
- **`scripts/ada/install-log-shipper.sh`** — NEW installer: bundles the
  script + rendered units, pushes over ssh (`--via` jump support — idc03
  needs it, its `id_idc03` key lives only on tony-omen), enables the
  timer, optional first run. Ships the script self-contained to
  `~/.local/share/log-shipper/` — NOT the repo checkout, so a stale
  checkout (e.g. mn01's, which lacks scripts/ada) can't break shipping.
- **`ssot.jobs.yml`** — 6× `log-shipper` jobs (tony_dell, tony_omen,
  idc01, idc02, idc03, mn01; hourly, `--self --max-docs 2000`) +
  `log-shipper-mha` on tony_dell (hourly, `--hosts michael-ha`). idc03
  added to `config.repo`. Units rendered to `systemd/generated/<host>/`.
- **`logs-kanban.py`** — same MDDB default fix; expected-fleet fallback
  += idc03/michael-ha; `ha-cli-ssh` lane exempt from the one-sided
  journal check; coverage matrix shows the lane.
- **`logs-report.py`**, **`export-transcripts.py`** — same default fix;
  the omen chain now invokes the shipper with no `--hosts` (full fleet)
  as the retained ssh fallback lane.
- **`docs/ssot/jobs/infrastructure/2026-10-05-log-shipper-local-timers.yml`**
  — full runbook/decision doc.

## Result — installed and verified live

`log-shipper.timer` armed and first-run-verified on **tony-dell,
tony-omen, idc01, idc02, idc03, mn01** (idc03 installed through the
tony-omen hop); `log-shipper-mha.timer` armed on tony-dell pulling
michael-ha. All 7 `ship/<host>` state docs on the MDDB leader are fresh
(<0.2h) with `lane=local` ×6 + `lane=ha-cli-ssh`; a michael-ha doc was
verified present in `host-logs` by key. Both lanes share the remote
cursor files — no double-posting.

## Verify

- `systemctl --user list-timers 'log-shipper*'` on each host.
- `curl -X POST http://100.102.134.91:11023/v1/search -d '{"collection":
  "host-logs-state","query":"","limit":50}'` — every `ship/<host>` doc's
  `updatedAt` < 26h and `lane` tells you which lane shipped it.
- The next `logs-report.py` digest / `logs-kanban.py` coverage card
  shows all 7 hosts reporting; backlog cards (`logs-auto-*-backlog`)
  self-clear as the hourly runs drain the capped backlog at 2000/run.

## Caveats

- **michael-ha cannot host a local timer** (ssh lands in the Alpine
  core-ssh addon: no python3/systemd/journalctl; supervisor `/host/logs`
  is text-only). It's covered by the dell pull timer — the card's
  "timer on EACH host" isn't literally achievable there; this is the
  closest robust lane (key-auth, immune to tailscale-ssh auth expiry).
- idc01/idc02/idc03 system journals are unreadable by user `tony`
  (pre-existing; same as the ssh lane). `usermod -aG systemd-journal
  tony` on the VPSes would close that gap.
- Shipper updates now propagate by re-running the installer, not by git
  pull (self-contained install is deliberate).
