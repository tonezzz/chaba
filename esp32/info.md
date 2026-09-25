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

## JK BMS bridge node (2026-09-24)

Second, dedicated node for the weather-station battery at Michael's site —
separate from esp32-test (BLE stack won't fit alongside the display app, and
the node must physically sit near the battery enclosure for BLE range).

- **Config source:** `esp32/jkbms.yaml` → `~/.local/share/esphome/jkbms.yaml`
- **Component:** `github://syssi/esphome-jk-bms@main` (`jk_bms_ble`, protocol
  `JK02_24S`; if the BMS turns out to be a JK_PBx hw v14/v15 board, use the
  `txubelaxu/esphome-jk-bms` fork and `JK02_32S` instead)
- **Framework:** resolves to `esp-idf` automatically — ESPHome 2026.x
  requires esp-idf for `ble_client`/`esp32_ble_tracker` (the `type: arduino`
  line in the yaml is overridden; left there for documentation)
- **Secrets needed** in `~/.local/share/esphome/secrets.yaml`:
  `jkbms_ble_mac` (fill after on-site advert capture — placeholder
  `AA:BB:CC:DD:EE:FF` compiles but won't connect), `jkbms_ble_name`,
  `jkbms_password` (already copied from `~/.config/secrets/jkbms.env`)
- **Advert scanner:** `esp32_ble_tracker.on_ble_advertise` logs any
  `JK-*`/`JK_*`/`*BMS*` names with MAC+RSSI at WARN — first boot on-site
  reveals the real MAC for `jkbms_ble_mac`, then reflash.
- **Sensors:** SOC, SOH, pack voltage/current/power, charge/discharge power,
  capacity remaining, cycles, 8× cell voltages, min/max/avg/delta cells,
  MOS temp + 2 battery temps, balancing current, runtime, errors (hex+text);
  switches for charging/discharging/balancer + BLE link toggle.
- **Build verified 2026-09-24:** `esphome compile jkbms.yaml` OK —
  flash 67.2% / RAM 56.5% of a plain esp32dev.
- **Build env fix:** `~/.cache/esphome/idf` was partially downloaded
  (Aug 25) — cmake reinstalled to `tools/cmake/3.30.2` and the esp-idf
  5.5.5 framework re-fetched; builds clean now.
- **Flash:** `~/.local/bin/esphome run ~/.local/share/esphome/jkbms.yaml`
  (serial via `/dev/ttyUSB0` for first flash; OTA after it joins WiFi)

## Merged display+BMS attempt on esp32test (2026-09-24) — FAILED at runtime

Tried merging `jk_bms_ble` into the esp32test config (`esp32/esp32-test-idf.yaml`,
esp-idf, compiled fine: DRAM 58.9% static / flash 78.8%). OTA flash via
michael-ha tunnel to `192.168.31.231:3232` succeeded, but the device died
within ~1 min: WiFi came up, API port listened, handshake never completed,
then total silence (no ping, no ports, no `safe_mode` OTA window after 10+ min).

- **Actual cause (corrected 2026-09-25, from serial console):** NOT a
  crash — the board ran fine but WiFi-cycled forever: `esp32/config.yaml`
  in the repo had drifted from the deployed firmware and listed only
  Tony's SSIDs (TONY-WIFI_*, Albatros, Maesang, TONY-IP) — none exist at
  Michael's site. The deployed firmware had Michael's SSIDs
  (`Xiaomi_A654`/`AisMN_2.4G`); the repo copy never did. So "dead" =
  alive-but-no-network. Lesson: verify the wifi network list matches the
  site's SSIDs before remote-flashing anything.
- **Fix applied in the merge:** `ESP.getFreeHeap()` → `esp_get_free_heap_size()`
  (Arduino API doesn't exist under esp-idf).
- **Conclusion:** **Chosen: option A** — esp32test repurposed as the
  dedicated BMS bridge running `jkbms.yaml` (node `jkbms`, display
  retired). Deployed 2026-09-25 via remote serial flash (below); now live
  at `192.168.31.231`, auto-discovered in michael-ha as
  `sensor.terrace_weather_station_bms_*` (all `unknown` until the BMS
  links). Whether BLE+display would have coexisted was never actually
  tested — the wifi misconfig masked everything.

## Remote serial recovery via the Samkoon HMI (built 2026-09-25)

The ESP32's USB cable plugs into the Samkoon HMI's USB host port (CH340
`1a86:7523`, `/dev/bus/usb/001/006`, unbound — the kernel has no ch341
driver). `espusb` (source: `esp32/espusb.c`) is a static ARM binary that
does CH340 userspace serial + ESP32 SLIP flashing over USBDEVFS ioctls —
full remote serial: console read, DTR/RTS download-mode reset, flash.

- Binary lives at `/data/local/tmp/espusb2` on the HMI (transferred via
  `nc -l 8000` on HMI + `nc 192.168.31.148 8000 < file` from michael-ha).
- Build: `podman run --rm -v /tmp:/work debian:bookworm-slim bash -c
  "apt-get update -qq && apt-get install -y -qq gcc-arm-linux-gnueabihf &&
  arm-linux-gnueabihf-gcc -O2 -static -o /work/espusb /work/espusb.c"`
- Usage: `espusb /dev/bus/usb/001/006 read 15` (console) |
  `flash <file>` (DTR/RTS → ROM bootloader → SLIP flash at offset 0).
- Android HMI notes: no nohup/tee/tail/head; `nc` is OpenBSD-style
  (`nc -l PORT`); telnet shell at `192.168.31.148:23` reached from
  michael-ha via `(printf "sh -i\n..."; sleep) | exec 3<>/dev/tcp/...`.
- HMI USB devices: ttyUSB0-4 = Longsung GSM modem (NOT the ESP32);
  CH340 enumerates but binds no tty — hence userspace.

## Recovery images

- `~/.local/share/esphome/recovery/esp32test-displayonly.{ota,factory}.bin`
  (original display config, no BLE — full restore if display is wanted back)
- `~/.local/share/esphome/recovery/jkbms.{ota,factory}.bin` (BMS bridge)

## Site address notes

- The board DHCPs as `192.168.31.231` on Michael's LAN. Reach via
  michael-ha (a 172.30.x container — `ip neigh` there never shows LAN
  MACs; find ESPHome nodes by port-sweeping 6053/3232).
- SolarAssistant dongle: `192.168.1.120` (web UI on :80, MQTT :1883
  auth-required; monitors the house Solis system, NOT the station BMS).

## Battery/BMS hunt status (2026-09-25)

- **Physical layout (Tony):** battery packs + their controller ARE inside
  the same cabinet as the RK600/HMI/ESP32. Tech says "JK BMS" (unverified);
  his phone app connects when he's physically close.
- **In-box BLE scan: NOTHING in 12 h+.** jkbms ran a continuous active
  `esp32_ble_tracker` — only ~8 weak (-85..-97 dBm) unnamed random-MAC
  advertisers (household devices). A JK dongle advertises continuously
  when powered+unconnected (per JK manual), and its connection indicator
  "flashes when disconnected" — silence therefore implies one of:
  1. BLE module RST/power-switched off except when needed (documented JK
     trick — syssi/esphome-jk-bms issue #107)
  2. It's Bluetooth Classic/SPP, not BLE — esp32_ble_tracker is blind to
     classic BT; the phone app would still work
  3. "JK BMS" is shorthand and it's actually another brand with
     wake-on-demand BLE
- **Decisive next step:** the app NAME on the tech's phone (identifies
  brand+protocol instantly) or an nRF Connect scan at the cabinet (shows
  advert name/MAC; also check Android BT settings — if the device appears
  there it's classic BT).
- **HMI serial:** app holds ttyO0+ttyO1 (ttyO3=console, ttyUSB*=GSM modem,
  no tty for the ESP32 CH340). ttyO1 carried ONE bursty burst of ~29-byte
  binary frames @ ~1 Hz (see /tmp/o1.cap analysis — fields don't match
  the weather snapshot, so probably NOT the RK600 feed; possibly the
  battery controller). ttyO0 silent in all captures. App polls may only
  run while the screen is awake — screen is off (mScreenOn=false,
  screencap blank) and keyevent wake didn't stick.
- `SCharger-7KS-S0-NS2351395951` @ 58:56:C2:C8:EE:62 = Huawei EV wallbox
  (paired to michael-ha hci0 during earlier probing). Not the BMS.

## Notes

- The PSK for `TONY-WIFI_2.4G` is stored in the tony-dell `secrets.yaml` and referenced via `!secret` in the repo config.
- `power_save_mode: none` is set under `wifi:` — the board was flapping (OTA windows of a few seconds) with power-save enabled.
