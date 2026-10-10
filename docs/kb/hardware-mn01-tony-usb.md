# mn01 / tony-usb — portable boot stick

Verified 2026-10-10 (MacBook booted from `tony-usb`, LAN 192.168.2.88).

`tony-usb` is a portable Ubuntu stick Tony carries. Any host booted from it
comes up fleet-ready:

- Hostname: `tony-usb` (`/dev/sda2` root, ~115G, ~11G used on MacBook boot)
- **Tailscale identity: mn01** (`mn01.taila0626a.ts.net`, `100.106.196.22`) —
  the stick carries mn01's node key, so any machine booted from it *claims the
  mn01 identity*. If a second mn01-bearing machine powers on they will fight
  for the same IP — treat mn01 as "the stick is wherever it's plugged in".
- `openssh-server` installed + running, **authorized_keys already contains the
  fleet keys** (`ssh tony@<lan-ip>` works keyless out of the box)
- `sshd` is **not** enabled for boot by default — `sudo systemctl enable ssh`
- `curl` is NOT in the image (this is why `curl … | bash` fails on a fresh
  boot); `wget`, `python3`, `tailscale` all are
- `sudo` is interactive (tony's password), not NOPASSWD
- First-boot fix (needs password once):
  `sudo apt install -y curl && sudo systemctl enable ssh`

MacBook hardware booted 2026-10-10: 15G RAM, laptop chassis. Whether mn01
has always been this MacBook or other hardware got the same stick —
unconfirmed; mn01's identity lives in the stick, not a specific machine.
