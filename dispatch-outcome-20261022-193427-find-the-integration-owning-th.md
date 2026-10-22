# Dispatch outcome — tony-ha-usb-probe-loop (HOM-0003)

## Root cause

The "2-1 USB probe" in `journalctl --user -u tony-ha` was the **command_line
switch `USB Test Hub`** (`unique_id: usb_test_hub`) in
`/home/tony/.config/home-assistant/configuration.yaml` — not a
serial/zigbee/zwave dongle as the card guessed. Its `command_state` ssh'd
`tony@127.0.0.1 'sudo /usr/sbin/uhubctl -l 2-1'` every 30 s.

The log text changed with the ph5 move to tony-omen:

- on tony-dell: uhubctl existed → `No compatible devices at 2-1` (card title)
- on tony-omen: uhubctl absent → `sudo: '/usr/sbin/uhubctl': command not found`

## Why disabled (not re-pointed)

- `/sys/bus/usb/devices` on tony-omen has no `2-1` device; uhubctl binary is
  absent there.
- uhubctl **is** installed on tony-dell but reports `No compatible devices
  detected!` — no per-port-power hub is attached to any reachable host
  (matches the earlier finding in job 2026-10-12-ada-ha-loopback-ssh-probe).
- The switch exists only to power-cycle esp32test
  (`reboot_esp32test_when_offline`, packages/system-managed.yaml); esp32test
  has been off since 2026-10-20 and SSOT notes it is dead at Michael's since
  2026-09-24 (bad merged flash). There is no real device path to point at.

## Changes (live tony-ha config, tony-omen)

- `configuration.yaml`: USB Test Hub switch block commented out with a dated
  re-enable note.
- `packages/system-managed.yaml`: `reboot_esp32test_when_offline` automation
  commented out (its only action targeted the removed switch).
- Entity registry: orphaned `switch.usb_test_hub` +
  `automation.reboot_esp32test_when_offline` entries removed via websocket
  `config/entity_registry/remove`.
- Applied via `command_line.reload` + `automation.reload` services — no HA
  restart.
- HA config repo left uncommitted; `ha-config-backup.timer` (nightly 03:30)
  snapshot-commits it.
- Worktree trail: `docs/ssot/jobs/home-assistant/2026-10-22-tony-ha-usb-probe-loop.yml`;
  `ssot.home-assistant.automations.yml` entry marked `status: disabled-2026-10-22`.

## Verification

- `journalctl --user -u tony-ha --since -90s/-3min` → 0 uhubctl/ssh lines
  (was 2 lines every 30 s). Done-when met.
- Both entities → `unavailable` on reload, then removed from the registry.

## Re-enable path (noted in config + job file)

Flash esp32test → attach a uhubctl-compatible (PPPS) hub to the tony-ha host →
verify `uhubctl -l <loc>` → uncomment both blocks → reload command_line +
automation. If the hub lands on a different host, repoint the ssh target away
from 127.0.0.1.
