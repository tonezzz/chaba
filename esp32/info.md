# ESP32 Test Node

## Hardware

- **Chip:** ESP32-D0WD-V3 (revision v3.1)
- **Board:** esp32dev
- **Flash:** 4 MB
- **MAC:** `C0:CD:D6:85:A8:38`

## Network

- **Hostname:** `esp32test`
- **IP Address:** `192.168.2.86` (manual/static)
- **Subnet:** `255.255.255.0`
- **Gateway:** `192.168.2.1`
- **DNS:** `192.168.2.1`
- **SSID:** `TONY-WIFI_2.4G`
- **BSSID:** `98:00:6A:68:F7:C6`
- **Channel:** 1
- **Signal strength:** ~-18 dBm

## Services

- **ESPHome API:** `192.168.2.86:6053`
- **OTA:** `192.168.2.86:3232`
- **mDNS:** `esp32test.local`

## Display

- **Panel:** 2.8" ILI9341 240×320 TFT
- **Touch:** XPT2046 resistive, dedicated SPI bus (CLK=GPIO25, MOSI=GPIO32, MISO=GPIO39)
- **Backlight:** `Display Backlight` entity (PWM on GPIO21)
- **Pages:**
  - `page_main`: "Hello CYD"
  - `page_status`: IP, SSID, MAC, Wi-Fi signal, uptime, free heap
  - Auto-cycles every 5 seconds

## Build / flash

- **ESPHome version:** 2026.8.1
- **Working directory on tony-dell:** `~/.local/share/esphome`
- **Config source:** `esp32/config.yaml`
- **Secrets:** `~/.local/share/esphome/secrets.yaml` (not in git)
- **Build command:**

  ```bash
  ~/.local/bin/esphome run ~/.local/share/esphome/esp32-test.yaml
  ```

## Notes

- The PSK for `TONY-WIFI_2.4G` is stored in the tony-dell `secrets.yaml` and referenced via `!secret` in the repo config.
- Initial ICMP ping latency can be high because of Wi-Fi power-save. If lower latency is needed, add `power_save_mode: none` under the `wifi:` block.
