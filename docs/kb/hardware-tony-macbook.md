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

## Fleet role

- Portable dev/lab host — same standard as any onboarded fleet node:
  ssh keys, own tailnet identity, stick-announce, audit-hosts entry,
  runner-agent lane.
