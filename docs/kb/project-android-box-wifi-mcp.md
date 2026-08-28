---
category: operations
---

# Android TV Box — WiFi Connection & MCP Server Notes

**Date:** 2026-06-25  
**Device:** Android TV box (`sailfish`)  
**WiFi target:** `TONY-WIFI_2.4G` / `TONY-WIFI_5G`  
**WiFi password:** `tonytony`  
**Device IP (Ethernet):** `192.168.1.43`  
**Device IP (WiFi):** `192.168.1.200`  

---

## Problem Summary

The Android TV box could not stay connected to `TONY-WIFI_2.4G`. The Android WiFi service would:

1. Authenticate successfully (`WPA2-PSK`, 4-way handshake complete).
2. Reach `COMPLETED` state.
3. Immediately disconnect with `reason=3` (locally generated disconnect) and `networkId=-1`.

`networkId=-1` indicated that the Android WiFi service could not map the wpa_supplicant network back to its internal `WifiConfigStore` network ID, so it tore the connection down.

---

## Root Cause

The Android WiFi service manages networks via its HAL, not by reading `wpa_supplicant.conf` directly. When we manually injected `TONY-WIFI_2.4G` into the configuration, wpa_supplicant used it and completed the WPA handshake, but the Android layer never saw a valid internal network ID for the connection. The HAL's state-change callbacks reported `nid=-1`, triggering the service to call `disconnect()`.

Two contributing factors:

- `wpa_cli` network activation commands (`enable_network`, `select_network`, `reconfigure`) returned `UNKNOWN COMMAND` / `FAIL` on the global control interface, which suggested the Android HAL and wpa_supplicant were not fully synchronized.
- The `wpa_supplicant` control interface was a file socket at `/data/vendor/wifi/wpa/sockets`, not the global `@android:wpa_wlan0` interface for some commands.

---

## Open Items / Future Work

- Determine whether the Android WiFi service can be repaired so it manages the network properly again. This would require understanding why the internal `networkId` mapping failed and possibly rebuilding `WifiConfigStore.xml` from a clean state.
- Consider installing a DHCP client in Termux (e.g., `dhcpcd`) if dynamic IP assignment is preferred over static.
- Automate the manual WiFi setup on boot via `init.d` or a persistent Termux:Widget workflow.

---

## Hardware Information

| Component | Details |
|-----------|---------|
| **SoC / Board** | Rockchip RK3328 (`rockchip,rk3328-box-liantong-avb`) |
| **Build flavor** | `rk3328_box-userdebug` |
| **Device tree** | `Rockchip RK3328 box liantong avb` |
| **CPU** | ARM Cortex-A53 (implementer `0x41`, part `0xd03`) |
| **CPU cores** | 4 (aarch64, ARMv8) |
| **CPU features** | fp, asimd, evtstrm, aes, pmull, sha1, sha2, crc32, cpuid |
| **BogoMIPS** | 48.00 per core |
| **RAM** | 4 GB (`MemTotal: 4049476 kB`, ~3.8G usable) |
| **Swap** | ~2 GB |
| **Internal storage** | 64 GB eMMC (`mmcblk1`, 61071360 blocks ≈ 58.2 GiB) |
| **Data partition** | `/dev/block/mmcblk1p17` — 53G, 13% used |
| **System partition** | `/dev/block/dm-0` (apex overlay) |
| **Vendor partition** | `/dev/block/dm-1` — 120M, ~100% used |
| **GPU** | Mali (`ro.hardware.egl=mali`) |
| **Bootloader** | `rk30board` (reported as `unknown` in `ro.bootloader`) |
| **Kernel** | Linux 4.19.111 `#56 SMP PREEMPT aarch64` |
| **Kernel build date** | Mon Nov 16 17:36:14 CST 2020 |
| **Android version** | 10 (`QQ2A.200305.004.A1`) |
| **Security patch** | 2020-05-05 |
| **Build date** | Thu Nov 19 15:23:27 CST 2020 |
| **Build user/host** | `foxluo@hugsun02` |
| **ABI** | `arm64-v8a` (also supports `armeabi-v7a`, `armeabi`) |
| **Characteristics** | `tv` |
| **Google Play client ID** | `android-rockchip-tv` |
| **GMS version** | `10_201910` |

### Network Hardware

| Interface | MAC | Driver | Notes |
|-----------|-----|--------|-------|
| **WiFi** | `e0:76:d0:44:7f:f5` | `bcmsdh_sdmmc` | Broadcom `bcmdhd` module (1.5 MB) |
| **Ethernet** | `6c:5c:3d:0d:06:99` | `rk_gmac-dwmac` | Rockchip GMAC / DesignWare MAC |

### Display

| Property | Value |
|----------|-------|
| Resolution | 1920 × 1080 |
| Refresh rate | 60 Hz |
| Density | 213 dpi |
| Type | Built-in screen, internal touch |
| Color modes | 0 (default) |
| Secure content | Supported (`FLAG_SUPPORTS_PROTECTED_BUFFERS`) |

### Other Hardware

| Property | Value |
|----------|-------|
| **Sensors** | None (`No Sensors on the device`) |
| **Bluetooth** | Enabled and ON (`enabled: true`, `state: ON`); address `22:22:9E:65:01:00`, name `TONY-TV`; bonded device `TONY-XS` (`38:53:9C:AC:FB:30`). `config.disable_bluetooth=true` exists but only affects the UI toggle, not the adapter. |
| **USB** | Disconnected (host mode not active, no external device) |
| **Battery** | AC powered, level 100%, present flag `false` (no physical battery, likely always-on power) |
| **DRM** | Widevine / ClearKey services running (`drm.service.enabled=true`) |


## See also

- [Project Android Box Commands](project-android-box-commands.md)
- [Project Android Box Glossary](project-android-box-glossary.md)
- [Project Android Box Solution](project-android-box-solution.md)
