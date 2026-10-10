# mn01 stick — identity & management standard

`mn01` is not a box — it is a **tailnet identity that lives on the tony-usb
stick**. Verified 2026-10-10: a MacBookPro13,3 booted from the stick came up
as `mn01.taila0626a.ts.net` (100.106.196.22) with fleet ssh keys already
authorized.

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
