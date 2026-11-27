# Dispatch outcome — idc03-swap-workload-placement (MEM-1511 / OPS-1511)

## What was done

**Ranked candidates by reclaim vs risk** (live per-unit MemorySwapCurrent/MemoryCurrent on idc03, 19:20 +07):

| candidate | swap | RSS | reclaim action | risk |
|---|---|---|---|---|
| jevos.service | 780MiB | 961MiB | move off-host (~1.7GiB footprint) | med — JEV_LANE consumer, safe fallback |
| ada-dev+ada-kk-dev | ~430MiB | ~320MiB | stop+disable (dead twins, bench lane on omen) | low |
| ada-bankq-student | 309MiB | 14MiB | restart (idle shadow :8791) | low |
| ada-ha-ada/kk-ha/ada-kk/ada-chaba | ~1.27GiB | ~300MiB | staggered restart | med — prod lanes, all verified |
| mddb-cms/mddb | hot | 1.9+3.4GiB | none — leader/path | high — do not touch |

**Capacity verified live:** con01 18GiB avail (load ~10, no swap), idc02 6GiB avail (load ~2.3, no swap), tony-omen 11-13GiB avail (load ~8.5, already hosts the twins + jev-student:8778 + open-jev — jev-plane consolidation candidate).

**Owner decision requested** on the card (request `idc03-swap-placement-two-owner-decisions-c55571`): dev-twin bench lane retirement and JevOS destination (omen ★ / idc02 / con01 / stay+guard / retire). No answer arrived during the session — both playbooks are staged to execute on approval.

## Applied (gated Ansible, `-e idc03_swap_approved=true -e card_id=...`)

`ansible/playbooks/idc03-swap-placement.yml` (new; preflight `--check --diff` ok=11 changed=4 failed=0):
- ada-dev + ada-kk-dev on idc03: stopped, verified `inactive`/`disabled` (they were disabled-but-active — resurrected by deploys).
- ada-bankq-student: restarted (active/enabled).
- ada-ha-ada, kk-ha, ada-kk, ada-chaba: staggered restarts; :8006/:8007/:8008 `/api/health` all 200, kk-ha container up. One probe raced the pwa_server bind — playbook now wait-loops ~2min.
- jevos-swap-reclaim.{sh,service,timer} installed on idc03 — daily 04:30, restarts jevos only when MemorySwapCurrent >512MiB (open-jev-guard.yml pattern). Verified in timer list.

`scripts/deploy-ada.sh`: removed ada-dev/ada-kk-dev from idc03 SERVICES (ports realigned). NOTE: the actual resurrection source is **ada-voice's own** `scripts/deploy-ada.sh` (`systemctl --user restart $SERVICES` unconditional) — outside this repo; flagged on the card as required follow-up or the twins return on next ada-voice deploy.

## Honest result

Total swap is still ~4/4GiB (34MiB free at last check). Restart-reclaim is **whack-a-mole**: per-unit swap cleared for every restarted lane, but mddb re-swapped ~1GiB and jevos +260MiB within ~3min — hot services absorb the freed headroom on this structurally oversubscribed host (~13-14GiB demand / 15GiB). One contained litellm cgroup OOM (MemoryMax=1600M guard working) during the spike; auto-recovered. MemAvailable recovered to ~3.6GiB, load settling.

**Durable swap reduction needs the pending owner calls:** jevos migration (~1.7GiB, `ansible/playbooks/jevos-migrate.yml` ready — rsync payload, tailnet-bound unit, /health+/v1/systemone verify, JEVOS_URL repoint, gated retire) or capacity work (zram-swap.yml precedent on omen; VPS resize = spend).

## Files

- `ansible/playbooks/idc03-swap-placement.yml` — gated reclaim playbook (applied)
- `ansible/playbooks/jevos-migrate.yml` — gated migration playbook (staged, `-e jevos_target_host=<omen|idc02|con01>`)
- `scripts/deploy-ada.sh` — twins out of idc03 restart list
- `docs/ssot/jobs/infrastructure/2026-11-27-idc03-swap-workload-placement.yml` — full job record

## Verify

- `ssh idc03 'systemctl --user is-active ada-dev ada-kk-dev'` → inactive; `is-enabled` → disabled
- `ssh idc03 'systemctl --user list-timers jevos-swap-reclaim.timer'` → next 04:30
- `ssh idc03 'for p in 8006 8007 8008; do curl -sf 127.0.0.1:$p/api/health; done'` → all ok
- `free -m` on idc03 → swap still ~4/4 (expected — see whack-a-mole note)

lessons:
- On an oversubscribed host, restart-reclaim is whack-a-mole: freed swap is re-occupied by hot services within minutes. Measure SwapFree, not per-unit swap, to judge real progress.
- `systemctl is-active/is-enabled` return non-zero for inactive/disabled — append `|| true` or `failed_when: false` in verify commands or the play fails after doing the right thing.
- ansible `command` tasks skip in --check mode; read-only probes need `check_mode: no`. `systemd_service` can't see a unit whose file is only a pending copy — enable timers via `command` + `changed_when: false`.
- pwa_server HTTP health lags `is-active` by 30-90s; single-shot probes race the bind — wait-loop up to ~2min.
- The unit-resurrection source for "disabled but restarted" services is an unconditional `systemctl --user restart $SERVICES` in ada-voice's deploy-ada.sh — chaba's deploy-ada.sh has an is-active guard and was NOT the culprit.
