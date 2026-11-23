# Dispatch outcome — tony-usb-own-nodekey (2026-11-23, idc02)

## What was found

- The card's physical precondition is not met: the tony-usb stick is not
  booted and not attached to any reachable host. Verified three ways:
  tailnet (`tailscale status` — no `tony-usb` node; `ssh mn01` + DMI
  confirms 100.106.196.22 is the real ESPRIMO Q556/2, not the stick),
  home-LAN sweep via tony-dell (ssh-open hosts = mn01 dual-NIC, macbook,
  one key-denied phone; stick's last IP 192.168.2.86 absent), and
  `lsblk` on mn01 / tony-dell / tony-omen / tony-macbook / con01 / idc03
  (no ~117G USB stick). Prior dispatch failures (exit=1, zero commits)
  were provider/session crashes, not approach errors — there is simply
  nothing a dispatch can execute on a stick that isn't running.

## What changed (this branch)

- `scripts/ops/stick-own-nodekey.sh` (new) — self-contained fix for the
  next stick session: stop tailscaled (ends the mn01 session fight),
  move `tailscaled.state` aside as `.cloned-<ts>.bak`, restart, then
  `tailscale up --hostname=tony-usb` and print the new identity for the
  runbook registry. Supports `ssh tony@<lan-ip> 'sudo bash -s' < script`
  and `TS_AUTHKEY`/`STICK_NODE_NAME` overrides. `bash -n` clean.
- `docs/kb/mn01-stick-standard.md` — new "Per-stick tailnet identity"
  section (rule, fix procedure, identity registry table with tony-usb
  marked pending), rules 0/1/2/5 updated for the post-fix model
  (mn01 = real box, stick = own `tony-usb` node), collision checklist
  now warns against `tailscale logout` on cloned media.
- `docs/kb/hardware-mn01-tony-usb.md` — caveat updated to point at the
  prepared fix.
- `docs/ssot/jobs/infrastructure/2026-11-23-tony-usb-own-nodekey.yml` —
  decision/runbook trail incl. the reachability evidence.

## Key correction to the card spec

Spec said `sudo tailscale logout` + delete state + `tailscale up`.
**Logout is deliberately omitted**: while the clone exists, stick and
mn01 share ONE nodekey — they are the same tailnet node. `logout`
expires that key server-side and would knock the REAL mn01 offline
(runner-agent, dispatch lanes) until re-auth. Stopping tailscaled +
removing local state separates the identities without touching mn01's
registration. Documented in the runbook and jobs file.

## Result / how to verify

- Prepared, not executed — done-condition's first half ("stick
  authenticates with a distinct node key") awaits a physical stick
  session. Card comms + a board request record exactly what Tony must
  do: boot the stick, run the script first, approve the `tony-usb` node
  in the admin console, then fill the registry row.
- Until then every stick boot re-triggers the mn01 session fight.

lessons:
- `tailscale logout` on cloned-nodekey media is a footgun: it expires the SHARED node key server-side and takes down the real host too — prefer stop+delete-state+up.
- This card is physically gated: three prior dispatch attempts died exit=1 with zero commits because no agent can run commands on an unbooted USB stick — check reachability (tailnet node, LAN ARP/ssh, lsblk on fleet hosts) before attempting, and deliver the prepared fix + docs instead.
- A dispatch CAN sweep the home LAN indirectly: ssh to a LAN-resident host (tony-dell @192.168.2.67) and probe /dev/tcp port 22 + ssh hostname — found no stick, ruling out "it's booted somewhere".
- mn01 answers on two LAN IPs (.79/.81) — ethernet + USB-wifi NIC on the same box; don't double-count hosts in LAN sweeps.
