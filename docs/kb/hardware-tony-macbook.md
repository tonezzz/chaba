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
  macbook`, tailnet up) rather than force-off: run
  `incident-capture` (~/.local/bin) FIRST — it grabs the amdgpu
  devcoredump (self-destructs on read/reboot) + journal slices + GPU
  state into `~/incidents/<ts>.tar.gz`. Then `sudo systemctl restart gdm`
  may recover the display with evidence already safe.
- Lost evidence 2026-10-11: the 15:56 wedge wrote a devcoredump at
  `/sys/class/drm/card2/device/devcoredump/data` — per-boot, consumed on
  read, gone after the force-off. incident-capture exists so this never
  happens again.
- Timeline tools on this host: `lnav` (static, ~/.local/bin — merge any
  logs into one chronology; `lnav /var/log/journal` or files from an
  incident bundle), `journalctl -b -1 -o short-precise`,
  `~/incidents/*/journal-*.txt` from capture bundles.

## Battery fault → SMC PROCHOT 800MHz lock (incident 2026-10-13)

- **Symptom**: all 8 cores pinned at exactly 800MHz — even under full
  load, temps normal (59°C), intel_pstate healthy (max 3.5GHz allowed,
  turbo on, powersave governor). OS not clamping → hardware pin.
- **Root cause**: battery degraded — `CHARGE_FULL` 3,873 mAh vs design
  6,669 mAh (**58% of design at only 87 cycles**), gauge contradicting
  itself (`STATUS=Full` + `CAPACITY=45` + `CURRENT_NOW=0`). SMC sees a
  battery it doesn't trust → asserts external PROCHOT → CPU honors it →
  hard 800MHz floor. Classic MacBook battery-fault lock.
- **Workaround (applied, works)**: clear BD PROCHOT bit 0 of MSR `0x1FC`
  on all cores — CPU then ignores the *external* signal (internal
  thermal protection unaffected):
  `rdmsr 0x1FC` → `0x24005d`; `sudo wrmsr -a 0x1FC 0x24005c` → clocks
  unlocked immediately.
- **Persistence**: MSR clears on reboot AND suspend/resume →
  `bdprochot-off.service` (oneshot, multi-user.target) +
  `/usr/lib/systemd/system-sleep/99-bdprochot` (post hook). Files staged
  at `/tmp/bdprochot/`; install commands in the card/comms. If SMC
  re-asserts mid-session (watch for snap-back), add a 5-min timer.
- **Real fix**: battery replacement. This host's battery is dying —
  workaround keeps CPU usable but the pack keeps degrading.
- Requires `msr-tools` (`apt install msr-tools`) + `modprobe msr`.
- **Verify anytime**: `cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`

## Fleet role

- Portable dev/lab host — same standard as any onboarded fleet node:
  ssh keys, own tailnet identity, stick-announce, audit-hosts entry,
  runner-agent lane.
