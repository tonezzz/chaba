# Dispatch outcome — ada-ha-loopback-ssh-probe (2026-10-12)

**Card:** `ada-ha-loopback-ssh-probe` · **Runner:** tony-omen · **Repos touched:**
`~/.config/ada-ha` + `~/.config/containers/systemd/` on tony-dell (live edits,
uncommitted — daily snapshotter picks them up), this chaba dispatch worktree
(quadlet mirror + SSOT trail).

## What was actually wrong

The card pinned `backend/tool_runner/screens.py`, but screens.py isn't loaded
inside the ada-ha container at all — `ada-ha` on tony-dell is the **Home
Assistant dev container** (quadlet, `Network=podman`, port 8125), and the spam
came from its `configuration.yaml`, which is a clone of host-networked tony-ha
where `127.0.0.1` really was the host:

- `command_line` switch `usb_test_hub` — `command_state` ssh'd
  `tony@127.0.0.1` for uhubctl every 30s → the `ssh: connect to host
  127.0.0.1 port 22: Connection refused` spam (~2k/day).
- `rest:` sensors on `http://127.0.0.1:8799/state` (10s) and
  `http://127.0.0.1:8014/api/chaba/pending` (20s) → the recurring
  `rest.data` fetch errors.
- Same class of bug, quieter: 5× `rtsp://127.0.0.1:8554` go2rtc cameras,
  3× `http://192.168.2.67:8123` desktop cameras (tony-ha never bound the LAN
  IP anyway), `cast_host_cleanup` ssh to `tony-omen.taila0626a.ts.net`
  resolving to stale LAN addr `192.168.1.48` in the container's /etc/hosts,
  and `trusted_proxies` missing the podman gateway so X-Forwarded-For from
  host-side proxies was ignored.

Reachability map probed from inside the container: `host.containers.internal`
(169.254.1.2) reaches host services bound to non-loopback addrs (:22, :8554
open); `100.75.102.88:8799` → 200 (tony-omen cast-browser over tailnet NAT);
`https://tony-dell.taila0626a.ts.net:8123` → 200 (tailnet-serve TLS → tony-ha
loopback; plain http → 400); `:8014` chaba-guest is **loopback-bound on the
host — unreachable by any path** (LAN socat 192.168.2.67:8126 firewall-blocked
from the netns, edge 404).

## What changed

**tony-dell `~/.config/ada-ha/configuration.yaml`** (backup:
`configuration.yaml.bak-loopback-20261012`):
- `rtsp://127.0.0.1:8554` ×5 → `rtsp://host.containers.internal:8554`
- `tony@127.0.0.1` ×3 → `tony@host.containers.internal` (uhubctl switch —
  verified key auth + sudo work: uhubctl ran, reports "No compatible devices
  detected at location 2-1" same as before)
- `http://127.0.0.1:8799` ×4 → `http://tony-omen.taila0626a.ts.net:8799`
- `http://192.168.2.67:8123` ×3 → `https://tony-dell.taila0626a.ts.net:8123`
- Commented out (with re-enable note): `chaba_guest_promote`,
  `chaba_guest_revoke`, `chaba_ha_bridge_mint`, `chaba_guest_reissue`
  rest_commands + `Chaba pending guests` rest sensor — chaba-guest binds
  host loopback only; no consumer references them in ada-ha automations.
- `http.trusted_proxies` += `10.88.0.1` (podman gateway).

**tony-dell `~/.config/containers/systemd/ada-ha.container`**:
`AddHost=tony-omen.taila0626a.ts.net:100.75.102.88` (also fixes
`cast_host_cleanup` ssh, which was silently dead on the stale LAN entry).

**This worktree:**
- `stacks/tony-dell/ada-ha/ada-ha.container` — same AddHost line (repo copy
  was identical to live before the change).
- `docs/ssot/infrastructure/ssot.home-assistant.instances.yml` — `netns_note`
  on the ada-ha entry documenting the loopback rule.
- `docs/ssot/jobs/home-assistant/2026-10-12-ada-ha-loopback-ssh-probe.yml` —
  full job trail incl. the reachability map.

## Result / verification

- `check_config -c /config` inside the container → exit 0; restarted via
  `systemctl --user daemon-reload && systemctl --user restart ada-ha`;
  healthcheck `healthy`.
- `journalctl --user -u ada-ha` since new-container boot (covers several
  poll cycles of the 30s/10s/20s jobs): **0** `ssh.*refused` and **0**
  `rest.data` fetch errors (was ~2/min + sensor cadence).
- Inside container: `curl tony-omen.taila0626a.ts.net:8799/state` → 200;
  `nc host.containers.internal 22`/`8554` → open.

To re-verify the card's criterion later:
`journalctl --user -u ada-ha --since '24 hours ago' | grep -c 'ssh.*refused'`
→ expect ~0/day.

## Not done / follow-up

- `:8014` chaba-guest rest_commands stay disabled until someone exposes the
  service on the podman gateway or tailnet (socat `10.88.0.1:8014 →
  127.0.0.1:8014` would do it); the note in the file says how to re-enable.
- The ada-ha config is hand-cloned from tony-ha — the same class of
  loopback bug can re-enter on the next clone; the `netns_note` in the
  instances SSOT is the guard.
- Board comment posted with the summary.
