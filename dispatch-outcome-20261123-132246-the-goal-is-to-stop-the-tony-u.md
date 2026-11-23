# Dispatch outcome — tony-usb-own-nodekey (2026-11-23, mn01)

## What was found

This dispatch ran **on mn01 itself** — the exact node whose tailnet
session the stick steals — on the same home LAN where the stick last
lived. After Tony answered `proceed` on the board request, I re-verified
the physical precondition end-to-end:

- **Tailnet**: `tailscale status` shows no `tony-usb`/`rescue` node.
  mn01's tailscaled has been up 12 days with **zero**
  login/logout/auth journal events in 7 days — no session fight is
  occurring, so no cloned stick is currently online.
- **Home LAN** `192.168.2.0/24`: full port-22 sweep from mn01 (both
  ethernet .79 and wifi .81 legs) found only tony-dell (.67), mn01
  itself, and two key-denied devices (.90/.98 — phones). The stick's
  last known IP .86 is dead (no ping, no ssh).
- **mn01 local**: `lsblk`/`lsusb` show no USB mass storage — the stick
  isn't plugged into mn01 either.
- **Ops feed** (`ada-ha-events-tony` on mddb-ops :11025): no
  `stick_online`/`host_online` docs — `stick-announce.service` has not
  fired.

Conclusion: the stick is still not booted or attached anywhere
reachable. The physical step cannot execute from any dispatch — it
needs Tony to boot the stick. Prior dispatch failures (exit=1, zero
commits) were this same physical gate, not approach errors.

## What changed (this branch, commit 53ced1ff53)

- `scripts/ops/stick-own-nodekey.sh` — hardened for the real stick
  session: waits up to 30s for `/run/tailscale/tailscaled.sock` after
  `systemctl start` (start returns before the daemon is reachable on
  slow USB media), and retries `tailscale up` 5×/5s (fails fast if the
  socket isn't ready; still idempotent). Header ssh example now uses
  `-t`.
- `docs/kb/mn01-stick-standard.md` — fixed a real friction bug: the
  ssh pipe example now uses `ssh -t` because sudo reads the stick
  password from the **tty, not stdin** — without `-t` sudo fails "a
  terminal is required" while stdin carries the script. Added the
  manual 4-command console equivalent (the script isn't on the stick —
  no chaba checkout there).
- `docs/ssot/jobs/infrastructure/2026-11-23-tony-usb-own-nodekey.yml` —
  appended the mn01-vantage reachability evidence, hardening notes, and
  the corrected pending-step command.

## Key correction to the card spec (carried from prior dispatch)

Spec said `sudo tailscale logout` + delete state + `tailscale up`.
**Logout is deliberately omitted**: while the clone exists, stick and
mn01 share ONE nodekey — `logout` expires that key server-side and
knocks the REAL mn01 offline until re-auth. The script stops
tailscaled, moves `tailscaled.state` aside as `.cloned-<ts>.bak`,
restarts, and `tailscale up --hostname=tony-usb` registers a fresh node
key. mn01's registration is never touched.

## Result / how to verify

- Done-condition half-met as before: docs + procedure + hardened script
  are committed; the stick's distinct nodekey awaits a physical stick
  session. `mn01-stick-standard.md` carries the procedure and a pending
  identity-registry row to fill after the run.
- Next stick session, FIRST thing: `ssh -t tony@<stick-lan-ip>
  'sudo bash -s' < scripts/ops/stick-own-nodekey.sh` from any fleet
  host (or the 4 manual commands in the runbook at the stick console),
  then approve the `tony-usb` node in the Tailscale admin console.
- Verify after: `tailscale status` shows a `tony-usb` node with its
  own IP (not 100.106.196.22), and mn01 stays online throughout.

lessons:
- `ssh host 'sudo bash -s' < script` fails "a terminal is required" —
  sudo reads the password from the tty, not stdin; always use `ssh -t`
  for remote-sudo script pipes.
- `systemctl start tailscaled` returns before the daemon's localapi
  socket exists on slow media — wait for /run/tailscale/tailscaled.sock
  or retry `tailscale up`, don't trust a fixed sleep.
- Dispatches for physically-gated cards should re-verify reachability
  cheaply before working: this card ran on mn01 itself — `tailscale
  status` + journalctl auth events + a /24 port-22 sweep ruled out a
  booted stick in ~1 min.
- filterMeta on mddb /v1/search supports kind/type but semantic `query`
  on ada-ha-events-tony is dominated by huge HA event bundles — stick
  announces are better checked via filterMeta type or not at all.
