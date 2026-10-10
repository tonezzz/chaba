# mn01 stick — identity & management standard

`mn01` is a real box (ESPRIMO Q556/2 — `hardware-mn01-tony-usb.md`).
The tony-usb stick carries a **clone of mn01's tailscale node key** —
booting it anywhere hijacks the `mn01` tailnet session (verified
2026-10-10: MacBookPro13,3 stole 100.106.196.22 until its tailscaled
was stopped; the box then reclaimed it normally).

## Rules

1. **One mn01 at a time.** The stick carries the node key
   (`/var/lib/tailscale/tailscaled.state`). Two machines booted from
   mn01-stamped media fight for the same tailnet IP. If mn01 needs to move
   permanently to new hardware, transplant the state file or retire the old
   node in the tailnet admin console.
2. **mn01 = portable ops/rescue node.** Its jobs: Ada standby lane, devin-
   dispatch lane (cap ~2), legacy Caddy alias, rescue shell into the fleet.
   Whatever hardware it lands on should stay *ops-grade*, not user data.
3. **Fresh-boot fix.** The image lacks `curl` and `sshd` isn't enabled:
   `sudo apt install -y curl && sudo systemctl enable ssh` (password once).
   sshd + fleet authorized_keys + tailscale state are already baked.
4. **Imaging.** Treat the stick as golden media — after material changes,
   `dd` a compressed image to backup (card TBD: auto-image after updates).
5. **Internal installs are separate machines.** An OS installed to a host's
   internal disk gets its **own tailnet name** — mn01 stays with the stick.
   Exception: deliberate transplant (rule 1).

## Collision checklist

- `ssh mn01` → run `cat /sys/class/dmi/id/product_name` to see which hardware
  actually holds the identity right now.
- If a boot lands somewhere unexpected: `sudo tailscale logout` on it, or
  power it off — the last-connected peer wins the IP.

## Call-home (verified live 2026-10-10)

The stick announces itself at boot: `stick-announce.service` (enabled)
runs `/usr/local/bin/stick-announce.sh` — waits for network+tailscaled,
then posts `kind=ops-event type=stick_online` to `ada-ha-events-tony`
with hostname + LAN IP + tailnet IP, and appends to
`/var/log/stick-announce.log`. The ops-digest picks it up — no manual
"is it up?" needed. Requires tailscaled running (normal boot path).

## Remote-control playbook (distilled 2026-10-10)

Once the stick boots a machine:

1. **Find it** — LAN: `arp -an` on any local host, or the stick_online
   event carries `lan_ip`. Reachable via `ssh tony@<lan-ip>` keyless
   (fleet keys baked). Tailnet name only after its own nodekey lands
   (currently clones mn01 — card `tony-usb-own-nodekey`).
2. **Sudo once** — password is interactive. Session-wide unlock:
   `sudo bash -c 'echo "tony ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/99-session'`
   — then everything is remote. Remove the file when done.
3. **Persist sshd** — `sudo systemctl enable ssh` (image ships with
   sshd running but not enabled).
4. **Install curl** — `sudo apt install -y curl` (image lacks it; wget,
   python3, tailscale are present).
5. **Read macOS disks** — `apfs-dkms` builds for the *running* kernel:
   `sudo apt install -y linux-headers-$(uname -r) && sudo dkms install
   linux-apfs-rw/0.3.18 -k $(uname -r) && sudo modprobe apfs && sudo
   mount -t apfs -o ro /dev/nvme0n1p2 /mnt`. (`fsapfsmount` ships without
   FUSE glue — dead end. apfs-fuse is not in 26.04 repos.)
6. **Serve the stick an ISO** — `wget` the installer ISO to the stick's
   fs (99G free), add a GRUB loopback entry to `/etc/grub.d/40_custom`,
   `update-grub`, reboot → installer boots from the same stick, install
   to the internal disk. No second USB needed.
