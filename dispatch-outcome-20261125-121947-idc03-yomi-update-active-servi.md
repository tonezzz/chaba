# dispatch-outcome — yomi-update-active/update-all fail every run (OPS-1382)

Card: `yomi-update-active-update-all-fail-every-8afee2` (attempt 2, runner mn01, branch `dispatch/20261125-121947-idc03-yomi-update-active-servi`)

## What was found

Attempt 1 (tony-omen, ~14:50) had already applied the real fix on idc03 but produced zero commits, so merge-sweep marked it unverified and the card was re-dispatched. This run verified the fix holds and landed the missing repo trail.

Root cause (confirmed): `yomi-api.service` on idc03 (`~/.config/systemd/user/yomi-api.service`, hand-installed, not a quadlet) was `disabled`+`dead` since 2026-11-23 ~19:50 — stopped during a systemd daemon-reexec/user-manager restart and never restarted because it was disabled. With no `yomi-api` container, `yomi-update-active.service`'s `podman run --network=container:yomi-api` one-shots failed status=125 every 15m. `yomi-update-all` never used `--network=container:` and was exiting 0 (card spec slightly off). Workload was NOT retired — ssot.services.yml declares idc03 primary since 2026-10-19.

## What changed (commit 20edca5439)

- `systemd/yomi-api.service` — vendored canonical copy of the live hand-installed unit (it had no repo copy; recoverability gap).
- `docs/ssot/jobs/infrastructure/2026-11-25-yomi-api-idc03-disabled-reenable.yml` — incident jobs doc (root cause, fix, verification evidence, residuals).
- `docs/ssot/infrastructure/ssot.services.yml` — yomi-api status note records the 2026-11-25 re-enable (OPS-1382).

## Verification (live, via ssh idc03 ~19:25 +07)

- `systemctl --user is-enabled/is-active yomi-api.service` → enabled / active; `podman ps` → yomi-api Up.
- `curl 127.0.0.1:3000/api/yomi/health` → `{"ok":true,...}`.
- `journalctl --user -u yomi-update-active.service -u yomi-update-all.service --since 14:50` → every run Finished cleanly (15:22→19:08 for active, 15:48→18:48 for all); `Result=success ExecMainStatus=0` on both; zero status=125 in ~5h / 20+ cycles.
- All four yomi timers (update-active, update-all, mddb-digest, backup) enabled.

## Residuals / follow-ups

- The `.d/home.conf` drop-ins (`-e HOME=/home/tony`) on yomi-update-active/all belong to OPS-1398 / card `yomi-line-session-expired-idc03`; if that branch doesn't land, a future re-render loses HOME and LINE-session writes regress to `/root/.local/share/yomi`. Noted on the card.
- `ssot.yomi-failover.yml` still names tony_dell primary — stale vs ssot.services.yml (idc03). Doc-rot flagged in the jobs doc, not fixed here.
- Root cause of the original `disable` is unproven; SSOT audit treats declared units as active-by-default so no `expected_state` pin was added.

lessons:
- "A 'no container found' status=125 from --network=container:X means the dependency container's unit is dead — check is-enabled as well as is-active; a disabled unit stays dead across user-manager restarts/daemon-reexec."
- "Dispatch verify counted attempt 1 as failed purely because it produced zero commits — host-side fixes still need a repo trail (jobs doc + vendored unit) to count as landed work."
- "systemd/user hand-installed units (~/.config/systemd/user/*.service) are NOT repo-rendered and had no vendored copy — vendor canonical units into systemd/ when touching them so a lost host unit is recoverable."
- "Card specs written from journal symptoms can misattribute which unit failed — yomi-update-all was green; only yomi-update-active used --network=container:yomi-api."
