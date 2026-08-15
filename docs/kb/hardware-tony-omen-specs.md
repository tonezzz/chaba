# tony-omen — Hardware Specs

**Scanned:** 2026-07-08  
**Form Factor:** HP 15-BC Laptop  
**Hardware SKU:** D98SKU1@@GM (HW Version: 52.08)  
**Firmware:** BIOS F.19 (2023-04-17)

**Note**: This file contains static hardware specifications. For operational history and changes, see `hardware/tony-omen/changes.md`

---

## OS & Kernel

- **OS:** Ubuntu 26.04 LTS (Resolute Raccoon)
- **Kernel:** Linux 7.0.0-27-generic (x86_64)

---

## CPU

- **Model:** Intel Core i7-9750H @ 2.60 GHz (CoffeeLake-H)
- **Cores / Threads:** 6 cores / 12 threads (Hyper-Threading enabled)
- **Max Turbo:** 4.5 GHz
- **Cache:** L1d 192 KiB, L1i 192 KiB, L2 1.5 MiB, L3 12 MiB
- **Virtualization:** VT-x enabled

---

## RAM

- **Total:** 32 GB DDR4 dual-channel (2 × 16 GB), configured at 2667 MT/s
- **Slot 1 (BANK 0):** 16 GB DDR4 @ 2667 MT/s — Part: EXRAM (manufacturer unknown)
- **Slot 2 (BANK 2):** 16 GB DDR4 @ 3200 MT/s (downclocked to 2667) — Corsair CMSX16GX4M1A3200C22

---

## GPU

- **Discrete:** NVIDIA GeForce GTX 1650 Mobile / Max-Q (TU117M, rev a1) — 4 GB VRAM
- **Integrated:** Intel UHD Graphics 630 (CoffeeLake-H GT2)
- **NVIDIA Driver:** 595.71.05 (Open Kernel Module)

---

## Storage

- **Primary:** Kingston SNV2S1000G — 1 TB NVMe SSD (`/dev/nvme0n1`)
  - `nvme0n1p1` — 100 MB EFI
  - `nvme0n1p2` — 16 MB (MSR)
  - `nvme0n1p3` — 865.7 GB (Windows / shared data)
  - `nvme0n1p4` — 768 MB (WinRE)
  - `nvme0n1p5` — 64.9 GB → Ubuntu `/`
- **Secondary:** WD WD5000LPLX-22ZNT — 500 GB 2.5" SATA HDD (`/dev/sdb`)
  - `sdb1` — 499 MB
  - `sdb2` — 128 MB
  - `sdb3` — 20 GB
  - `sdb4` — 445.1 GB
  - ⚠️ **Note (2026-07-08):** `gdisk` reports no valid partition table; `sdb1`–`sdb4` throw I/O errors when read directly. Drive may be failing or in an inconsistent state. `lsblk` shows partitions but `blkid` returns nothing. Recommend checking SMART data (`smartctl -a /dev/sdb`).
- **SATA Controller:** Intel 82801 Mobile SATA Controller (RAID mode)

---

## Display

- **Resolution:** 1920 × 1080 (internal panel; RDP active at time of scan)

---

## Networking

- **Ethernet:** Realtek RTL8111/8168/8411 PCIe Gigabit (`03:00.0`)
- **Wi-Fi:** Intel Wireless 7265 (`04:00.0`, interface `wlo1`)

---

## Audio

- **Integrated:** Intel Cannon Lake PCH cAVS (`00:1f.3`)
- **HDMI / DP audio:** NVIDIA Device 10fa (`01:00.1`)

---

## USB

- **Controller:** Intel Cannon Lake PCH USB 3.1 xHCI (`00:14.0`)

---

## Battery

- **Status at scan:** 100 %, Full
