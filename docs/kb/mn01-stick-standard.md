# USB stick standard — mn01 rescue stick & future sticks

Every portable Ubuntu stick follows the same recipe so any session can
pick one up cold and know exactly what's on it.

## Build recipe (what a "standard stick" carries)

- Ubuntu LTS installed normally to the stick (persistent OS, NOT a
  dd'd installer image)
- `openssh-server` enabled + fleet ssh keys in `~tony/.ssh/authorized_keys`
- tailscale installed — **with its OWN nodekey** (never clone another
  host's `tailscaled.state`; see identity rules below)
- `stick-announce.service` enabled — posts `host_online` to the ops
  feed at boot (LAN + tailnet IP; script at
  `/usr/local/bin/stick-announce.sh`, writes `/var/log/stick-announce.log`)
- curl, git, python3, rsync, tmux — the minimum remote-ops set
- hostname: name of the stick (`tony-usb`), never the machine it boots
- GRUB loopback-ready: keep a spare ISO on the fs + a disabled
  `40_custom` entry — turns any booted host into an installer

## Operating rules

- A stick is **rescue/portable media** — hardware-agnostic.
- Whatever machine it boots is a guest; the stick's tailnet identity
  announces itself (stick_online event → look for `lan_ip`/`tailnet_ip`).
- LAN ssh + fleet keys are the always-on control path; tailnet is the
  reach-anywhere path.
- **Identity collisions are the one real hazard** — never boot a stick
  that carries a clone of another host's nodekey while that host runs.
- Session sudo: `sudo bash -c 'echo "tony ALL=(ALL) NOPASSWD:ALL" >
  /etc/sudoers.d/99-session'` — remove when done.

## Verify a stick after boot

```bash
ssh tony@<lan-ip> 'hostname; tailscale ip -4; systemctl is-enabled ssh stick-announce'
```

Expected: hostname=stick name, own tailnet IP, both enabled.

## Real-world application history

- `mn01` stick → used on MacBookPro13,3 2026-10-10 (the session that
  proved the loopback-ISO trick, APFS read via libfsapfs-utils +
  apfs-dkms, and the cloned-nodekey hazard)
- `tony-macbook` install 2026-10-10 — installer booted off the stick's
  own GRUB + ISO stored on the stick filesystem

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
