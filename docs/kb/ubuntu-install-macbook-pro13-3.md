# Ubuntu install — MacBookPro13,3 (15" Late 2016, Touch Bar)

Standard procedure for putting Ubuntu on the MacBook's internal SSD
(Apple SM0256L, `nvme0n1`, 233.8G). Verified hardware scan 2026-10-10.

## Hardware notes (13,3)

- Intel — **no T2 chip** → normal Linux install, no Secure-Boot dance.
- WiFi `BCM43602` (brcmfmac) — needs firmware; have a USB-Ethernet
  dongle or phone tether ready (the current session runs on a Realtek
  USB ethernet adapter for exactly this reason).
- Boot picker: hold **Option (⌥)** at power-on → choose `EFI Boot`.
- Touch Bar / keyboard: works on modern kernels (applespi); brightness
  keys may need `applespi` quirks — cosmetic, fix later.
- FaceTime camera needs out-of-tree `facetimehd` — skip unless wanted.

## Procedure

1. **Backup** anything on `nvme0n1` (the internal SSD) if it holds data.
2. **Media**: tony-usb is a persistent Ubuntu install, not an installer —
   write the Ubuntu ISO to a second stick, or run the installer image
   from an SD/second USB. (Or: from the booted stick, use
   `usb-creator-gtk`/`dd` to burn ISO onto a *different* device.)
3. Boot MacBook holding **Option** → pick the orange `EFI Boot` drive.
4. `Try Ubuntu` → connect network (USB-Ethernet dongle) → run installer.
5. Disk choice:
   - **Full wipe** → "Erase disk and install" (installer creates EFI +
     root on nvme0n1 automatically). Recommended if macOS is dead.
   - Keep macOS → shrink first in macOS Disk Utility, then install
     alongside (installer offers "Install alongside").
6. After install, boot picker (**Option**) shows `EFI Boot` for Ubuntu.
7. **Post-install essentials** (first boot):
   ```bash
   sudo apt update && sudo apt install -y bcmwl-kernel-source \
        openssh-server curl && sudo systemctl enable --now ssh
   sudo apt install -y linux-firmware   # covers most brcm blobs
   ```
   Wifi firmware arrives via the ethernet dongle or USB tether.
8. **Fleet onboard** — new machine = new tailnet name (see
   `mn01-stick-standard.md`): the internal install must NOT import the
   stick's tailscaled.state. Then:
   `curl -fsSL https://api.surf-thailand.com/install | sudo bash`
9. Register the host in `ssot.services.yml` + a hardware doc + host-loads.

## Gotchas seen live

- `/dev/sda2` = the stick when booted from USB — do not install to it.
- The stick's tailnet state is mn01; the installed OS gets a new node.
