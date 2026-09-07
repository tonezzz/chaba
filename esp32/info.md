# ESP32 Test Node

## Hardware

- **Chip:** ESP32-D0WD-V3 (revision v3.1)
- **Board:** esp32dev
- **Flash:** 4 MB
- **MAC:** `C0:CD:D6:85:A8:38`

## Network

- **Hostname:** `esp32test`
- **IP Address:** `192.168.2.65` (DHCP — may change on other networks)
- **Subnet:** `255.255.255.0`
- **Gateway:** `192.168.2.1`
- **DNS:** `192.168.2.1`
- **SSID:** `TONY-WIFI_2.4G`
- **BSSID:** `98:00:6A:68:F7:C6`
- **Channel:** 1
- **Signal strength:** ~-18 dBm

## Services

- **ESPHome API:** `192.168.2.65:6053`
- **OTA:** `192.168.2.65:3232` (unreliable if Wi-Fi flaps — serial flash via `/dev/ttyUSB0` on tony-dell works when the board is plugged into its USB hub)
- **mDNS:** `esp32test.local`

## Display

- **Panel:** 2.8" ILI9341 240×320 TFT
- **Touch:** XPT2046 resistive, dedicated SPI bus (CLK=GPIO25, MOSI=GPIO32, MISO=GPIO39)
- **Backlight:** `Display Backlight` entity (PWM on GPIO21)
- **Pages:**
  - `page_pv1` ("Power Sources"): single page, no cycling. Three columns
    PV1/PV2/Grid (kW, V, A/Hz) and a Battery/Load row (kW, SOC%, chg/dis).
    "Upd Ns" turns red when data is older than 120 s.
- Old `page_weather`, `page_gold`, and `page_status` pages plus all HTTPS
  fetches were removed (2026-09-07) — they consumed most of the heap via
  mbedTLS buffers and image decode.

## PV1 data pipeline

The ESP32 has no PSRAM and very little free heap, so it cannot decode card
images. Two pipelines run on `ha-card-snapshot.timer` (systemd user, 60s):

- `scripts/home-assistant/snapshot-card.py`: playlived headless Chrome loads
  `http://127.0.0.1:8124/tony-test/pf3` (auth via injected `hassTokens`),
  screenshots the `sunsynk-power-flow-card`, writes `pv1.png` — for TV cast.
- `scripts/home-assistant/pv1-values.sh`: fetches 9
  `sensor.inverters_1_{pv_*,grid_*}` values plus per-pack
  `sensor.batteries_{1..3}_{power,state_of_charge}` (summed/averaged) and
  `sensor.inverters_1_load_power` from michael-dev REST and writes `pv1.txt`
  (12 lines, plain floats) — for the ESP32.
- Both are served by Caddy at `http://192.168.2.67:8080/snapshots/` (the live
  root is `stacks/web/public/` in this repo, NOT `/srv/public`).
- The ESP32 does ONE `http_request.get` of `pv1.txt` every 60s
  (`capture_response`), parses 12 floats with `sscanf` into globals, and
  renders text on `page_pv1`.
- The full `pv1.png` can be cast to the TV:
  `media_player.play_media` on `media_player.tony_tv_cast` with
  `media_content_type: image/png`.

Why not images: a single RGB565 PNG decode needs ~117 KB contiguous and the
PNGLE engine ~30 KB — both exceed the largest free heap block (~24 KB).
Even 6 small grayscale BMP bands fetched sequentially still exhausted
sockets/heap over time (`HTTP_CLIENT: Allocation failed`,
`esp-tls: Failed to create socket`). With the image subsystem removed, free
heap is ~222 KB stable.

## Remote access

- `tony-dell` advertises `192.168.2.0/24` as a Tailscale subnet route.
- IP forwarding is enabled (`net.ipv4.ip_forward=1`).
- Any Tailscale peer can now reach:
  - **API:** `192.168.2.65:6053`
  - **OTA:** `192.168.2.65:3232`
- Verified from `tony-omen`: `ping` and `nc -z` to `6053` succeed.

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
- `power_save_mode: none` is set under `wifi:` — the board was flapping (OTA windows of a few seconds) with power-save enabled.
