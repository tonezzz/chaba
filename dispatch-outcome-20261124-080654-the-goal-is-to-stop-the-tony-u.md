# Dispatch outcome — tony-usb-own-nodekey (attempt on tony-omen)

Card: `tony-usb-own-nodekey` (SEC-0303) — give the tony-usb stick its own
tailnet nodekey instead of cloning mn01's.

## What I found

The physical step is still impossible from a dispatch — re-verified from
two vantage points this session:

- **Tailnet**: no `tony-usb`/`rescue` node; `ssh mn01` lands on the real
  ESPRIMO Q556/2 (uptime 34d) — the stick is not holding mn01's session.
- **Ops feed** (`ada-ha-events-tony`, mddb-ops :11025): 500 ops-event docs
  scanned — zero `stick_online`/`host_online` announce events; the stick
  has not booted in the covered window.
- **LAN**: port-22 sweep of 192.168.2.0/24 via tony-dell (wired; omen's
  wifi segment is client-isolated) — only tony-dell (.67), mn01 (.79/.81,
  real hardware via ssh), and a key-denied phone (.98). No stick.
- **tony-omen local**: `lsblk`/`lsusb` show no USB mass storage.

## What I changed (commit 7d4cf43f8d on dispatch/20261124-080654-...)

The repeated failure mode was detection, not preparation — four prior
attempts all concluded "stick not booted" because nothing tells anyone
WHEN it boots. Delivered the missing piece:

- `scripts/ops/stick-watch.py` — fleet-side detector, three signals:
  1. ops-feed `stick_online`/`host_online` announce within window
     (earliest signal — fires at boot even during the theft),
  2. `ssh mn01 hostname` answering `tony-usb` (active theft — ssh lands
     on whatever owns the nodekey),
  3. tailnet roster carrying `tony-usb`/`rescue` (fix applied → suggests
     registry update + card close).
  Alerts = board-api comment on the card + `board_notify` push (HA iPhone
  default on tony-dell) containing the exact `stick-own-nodekey.sh`
  command. Deduped per signal (24h), kill switch
  `~/.config/stick-watch.off`, `--dry-run`, stdlib-only.
- `systemd/stick-watch.{service,timer}` — 5-min cadence + boot catch-up,
  written for tony-dell's user manager (has `home-assistant-token.env`
  and the `~/CascadeProjects/chaba` exec checkout).
- `docs/kb/mn01-stick-standard.md` — collision checklist documents the
  automatic detection path.
- `docs/ssot/jobs/infrastructure/2026-11-24-tony-usb-own-nodekey.yml` —
  full trail.

## Verification

- `stick-watch.py --dry-run --verbose` on tony-omen: all three probes
  clean → "no stick signals", rc=0.
- Unit-tested every signal with stubs: theft/announce/own_node fire;
  non-stick `host_online`, unrelated types, stale timestamps ignored.
- Pre-commit gates passed (fast pytest gate, SSOT validation).

## Result / what's still needed

Done-condition is half-met again: detection + procedure + docs are done;
the stick's own nodekey still requires a real stick boot. Two asks are
now on the board:

1. **Board request raised**: approve installing `stick-watch.timer` on
   tony-dell (`install -m644 systemd/stick-watch.{service,timer}
   ~/.config/systemd/user/ && systemctl --user daemon-reload &&
   systemctl --user enable --now stick-watch.timer`). Not installed —
   prod service change needs approval.
2. **Physical (unchanged)**: next stick boot →
   `ssh -t tony@<lan-ip> 'sudo bash -s' < scripts/ops/stick-own-nodekey.sh`,
   approve the `tony-usb` node in the admin console, fill the registry
   row in `mn01-stick-standard.md`. With the watcher installed, Tony
   gets an HA push with this command automatically instead of the
   session theft going unnoticed.

lessons:
- Dispatch cards for physical-access tasks keep burning attempts; the
  fix is a detector that converts "waiting for hardware" into an alert.
- `ssh <tailnet-host> hostname` doubles as a nodekey-theft probe: it
  lands on whoever owns the nodekey, so `tony-usb` answering for `mn01`
  is the theft signature.
- Ops-feed announce (`stick_online`/`host_online` in
  ada-ha-events-tony) is the earliest stick-boot signal — it fires even
  while the stick is still contesting mn01's session.
- tony-omen's wifi segment (192.168.2.x via wlo1) is client-isolated —
  LAN sweeps must go through tony-dell's wired NIC.
