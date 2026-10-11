# tony-macbook — hardware & capability record

- **Host**: MacBookPro13,3 (2016 15") · Ubuntu 26.04.1 LTS · tailnet
  `tony-macbook` (100.77.76.112) · LAN .88
- **CPU**: i7-6700HQ 4c/8t @ 2.6GHz
- **RAM**: 15Gi
- **Disk**: 233.8G Apple NVMe (SM0256L) — fresh ext4+EFI install
  2026-10-10, macOS wiped (user data backed up to the tony-usb stick first)
- **Net**: USB-C ethernet dongle + BCM43602 Wi-Fi (`wlp3s0` via
  brcmfmac — persisted in `/etc/modules-load.d/brcmfmac.conf`)

## GPU (bench 2026-10-10)

- **Intel HD 530** (Skylake iGPU, i915) — display/default
- **AMD Radeon Pro 450** (Baffin/Polaris11, amdgpu + Mesa RADV)
  - 640 shaders, 2GB GDDR5, ~1.2 TFLOPS FP32
  - **Vulkan 1.4.335 works** (`AMD Radeon 550 Series (RADV POLARIS11)`)
  - **OpenCL: no devices** — rusticl doesn't bind Polaris; ROCm
    dropped Polaris years ago
  - **Ada-offload verdict**: usable for Vulkan-accelerated
    whisper.cpp/llama.cpp inference (small models — whisper tiny/base,
    7B-class llama with Vulkan backend). Not a training or vision node;
    GPU-labeled dispatch cards expecting CUDA/ROCm will not match.
  - Bench tools present: vulkan-tools, clinfo, mesa-utils, glmark2
- **Software**: Chrome 155, devin-desktop (windsurf) 3.10.48 via the
  windsurf apt repo, devin CLI 3000.11.3 (credentials ported),
  tailscale, runner-agent lane (cap 2, labels cpu/dev/portable)

## Display (verified 2026-10-11)

- **Panel**: 2880×1800 Retina (eDP-1, i915) @ mutter scale 2.5 → 1152×720
  logical. Fractional scaling + `xwayland-native-scaling` on.
- **External path**: USB-C dock → one DP MST link via amdgpu dGPU →
  per-monitor connectors appear as `card2-DP-N` (dynamic, numbering not
  stable). Verified: PHL 276E7 27" (DP-7) + DELL P2425H 24" (DP-8),
  both 1920×1080@60, extended via `gdctl`.
- **Quirk**: multi-monitor enable on the MST link can fail at kernel
  level (`amdgpu ERROR Step 2 of creating MST payload failed`) — retry
  or replug; `gdctl set -P -L -M <conn> --right-of <anchor>` persists to
  `~/.config/monitors.xml`. Genesys Logic hub in the dock is data+video
  but alt-mode negotiation is flaky; a connector can show `connected`
  while GNOME has it disabled.
- **`text-scaling-factor 0.6`** is set (compact UI on retina) — affects
  GTK apps only, not Chrome. Standard procedure: codeword `scalecheck`
  → `scripts/devin/display-scale-check.sh` (skill `.devin/skills/scalecheck`).

## Suspend wedge (incident 2026-10-11)

- **S3 (`deep`) suspend + resume kills the display path**: TB pcieports
  never leave D3cold → amdgpu SMU dead → `GPU Recovery Failed -22` →
  screen dark, host alive (ssh works). Card `macbook-suspend-dgpu-wedge`.
- Workaround under test: `mem_sleep_default=s2idle`. Until fixed, avoid
  suspending while docked — if it goes dark again, **ssh in** (`ssh
  macbook`, tailnet up) rather than force-off: `sudo systemctl restart
  gdm` may recover, and logs are intact for diagnosis.

## Fleet role

- Portable dev/lab host — same standard as any onboarded fleet node:
  ssh keys, own tailnet identity, stick-announce, audit-hosts entry,
  runner-agent lane.
