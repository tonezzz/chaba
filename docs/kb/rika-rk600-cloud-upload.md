# Rika RK600-07B — Cloud Upload Path, Portal Access, and Outage Postmortem

Distilled from Devin session transcripts 2026-09-13 → 2026-09-15 and live device
inspection + API verification 2026-09-22. Memory coverage:
`ada-ha-bank-devin-tony` (MDDB) + transcripts in `~/.local/share/devin/cli/summaries/`.

## Device identity

- Unit: **Rika RK600-07B weather data logger** with an **RK900 module** attached.
- Hardware is actually a **Samkoon HMI**: model `AK070AB` / `AK-070MG`,
  TI AM335x (`am335xevm`), Android 4.2.2, app `ak_v_2.1.3_521_20190327`.
- Samkoon serial: `AKG229221907000048`; cloud device alias: **`R22100502`**.
- Location: Michael's site, WiFi `wlan0` = `192.168.31.148` (Xiaomi router),
  MAC `0c:cf:89:a6:16:fd`.
- Open ports: **23 telnet → root shell, no password**,
  **502 Modbus-TCP** (what michael-ha polls, `packages/rk600_modbus.yaml`).

## Rika cloud — access and API (verified working 2026-09-22)

**The legacy portal is NOT geo-blocked — the DNS moved.** `rikacloud.com` now
resolves to `39.104.200.177` (new portal only). The legacy agriculture portal
and upload API live on the **upload server's IP**:

| What | Where | Status |
|---|---|---|
| Legacy portal (technician's URL) | `http://39.99.253.232:8000/agriculture/chart` | **Works** |
| Legacy login page | `http://39.99.253.232:8000/agriculture/login` | Works |
| Portal API | `http://39.99.253.232:8005` | Works |
| HMI upload socket | `39.99.253.232:8899` | Works — device pushes Modbus-response frames |
| `rikacloud.com:8000` | `39.104.200.177:8000` | **Port closed** — DNS points to new host |
| New portal | `https://rikacloud.com/` (`/api/v2`) | Works, but `R22100502` has no account there |

**PC login for Tony:** open `http://39.99.253.232:8000/agriculture/login`,
username `R22100502`, password = the one in `~/.config/secrets/rikacloud.env`
(verified valid 2026-09-22 — `POST :8005/login` returns `认证成功` + JWT).

### API recipe (for re-querying — keep as fallback, prefer this doc's cached facts)

```bash
TOKEN=$(curl -s -X POST http://39.99.253.232:8005/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$RIKA_ACCOUNT\",\"password\":\"$RIKA_PASSWORD\"}" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
# token TTL 86400s; send as header  token: <jwt>   (NOT Authorization: Bearer)
```

Endpoints (device key is **facId `22100502`**, not id `286`):

- `GET /user/R22100502` — account + device list
- `GET /data/22100502` — latest record
- `GET /todaydata/22100502` — today's rows
- `GET /datas/22100502?pageNum=1&pageSize=500&startTime=…&endTime=…` — history
- `GET /device/22100502` — device metadata + element map

### Element map (device `eleName`/`eleNum`)

`e1` Wind Direction · `e2` Wind Speed · `e3` Air Temperature (°C×10) ·
`e4` Air Humidity (%×10) · **`e5` Rainfall** · `e6`–`e16` unused (all 0)

The upload frame is a Modbus response `01 03 20` (16 regs) + CRC; the server
polls with `01 03 0000 0010`. Currently only regs 0–3 carry data — **e5 rain
has been 0 in every row ever uploaded** (see rain verification below).

## Data paths (status 2026-09-22)

| Path | Endpoint | Status |
|---|---|---|
| Sensor → HA | Modbus-TCP `192.168.31.148:502` | Working — regs 0–3 only (wind dir/spd, temp, hum) |
| HMI → Rika cloud | TCP `39.99.253.232:8899` | **Working** — ESTABLISHED, ~1 row/min since 14:44 |
| Samkoon tunnel | peergine `connect.peergine.com:7885` | Working after route fix |
| HA rain/pressure sensors | `sensor.rk600_rainfall` etc. | **Hardcoded stubs** (`state: "0"` in `packages/rika_rk600.yaml`) — HA cannot see rain at all |
| Battery BMS | BLE only (JK BMS) | Not polled by HMI — see below |

## Bluetooth (surveyed 2026-09-24)

The site technician reported "the weather station has Bluetooth" — that is the
**battery module's JK BMS**, not a sensor-data path. Verified:

- **Samkoon HMI has no Bluetooth at all** — `bluetooth_manager` service absent,
  `/sys/class/bluetooth` empty, `bluetooth_on=0`, no BT packages. Technician's
  "HMIClient" reference is the Samkoon phone app (TCP/cloud, not BT).
- **BLE scan from michael-ha hci0** found only household devices (Amway
  purifier, LG/Samsung appliances, XMEye cams, Tuya, Solis datalogger,
  SolarAssistant, TV box). Full inventory in
  `ssot.mac-address-registry.michael.yml`. No Rika/weather advert exists.
- **`SCharger-7KS-S0-NS2351395951` @ `58:56:C2:C8:EE:62` is NOT the BMS** —
  it's Michael's **Huawei SCharger-7KS-S0 EV wallbox** (BLE = FusionSolar app
  auth only; bonding required, GATT reads empty). Also offers Modbus-TCP/OCPP
  if EV-charger telemetry is ever wanted — separate integration.
- **The JK BMS itself did NOT appear in the scan** — confirmed 2026-09-24
  to be a **range issue**, not a dead radio: the site technician's phone app
  finds the BMS automatically when he is physically close to it. michael-ha
  is too far away. An ESP32 parked near the battery enclosure would see the
  advert the same way the phone does. Still needed on-site: advert name/MAC
  (nRF Connect scan or read from the app), and WHICH app the tech uses
  (identifies the protocol — "JK BMS" app → JK02 protocol →
  `syssi/esphome-jk-bms` works out of the box).
- **No BMS on the Modbus bus:** `:502` regs 4–47 are all zero — only e1–e4
  (rain e5 when raining) are polled. The BMS cannot be read *through* the HMI.
- **ESP32 path is viable if wanted:** JK BMS BLE = service `FFE0`, char `FFE1`;
  `syssi/esphome-jk-bms` (or `txubelaxu` fork for PB-series hw v14/15) polls it
  from ESPHome → HA/MQTT. Needs a **dedicated ESP32 at Michael's site**
  (BLE range; `esp32test` stays home and is heap-constrained anyway). WiFi creds
  for `Xiaomi_A654`/`AisMN_2.4G` already exist in `esp32/config.yaml`.
- Alternative: the on-site **SolarAssistant** dongle can bridge a JK BMS over
  RS485→MQTT if it's wired to the station battery — check with Michael.
- Do NOT write to `SCharger`/`SolarAssistant` BLE characteristics remotely;
  probing is read-only + connect attempts only.

## Root cause of the upload outage

The HMI **lost its default route** — `/proc/net/route` had only the connected
`192.168.31.0/24` route. Same-subnet traffic (Modbus from michael-ha, telnet)
kept working, so HA data looked fine while every outbound connection died
with `ENETUNREACH`. Likely triggered by a DHCP/netd flap after the WiFi move.

Fix applied 2026-09-22:

```
route add default gw 192.168.31.1 dev wlan0
setprop net.dns1 192.168.31.1 ; setprop net.dns2 8.8.8.8
```

Result: upload socket ESTABLISHED immediately, cloud history shows ~1 row/min
starting 14:44. **The route is volatile** — lost on reboot/WiFi flap.

**Watchdog installed:** `rika-watchdog.service` (persistent user service on
tony-omen, `linger=yes`) runs `~/.local/bin/rika-cloud-watchdog.py` — every
2 min checks via telnet that the default route exists and the 8899 socket is
ESTABLISHED; re-adds route or restarts `com.android.Samkoonhmi` if broken.

## Cloud history timeline (what the dashboard recorded)

- Aug – Sep 10: **empty** — no uploads in the cloud before our work began
- Sep 13 16:03 – Sep 14 13:23: 28 sparse rows (early bridge/DNAT experiments)
- Sep 16 – Sep 22 14:44: **empty** (route lost ~Sep 16 09:58 UTC, matching the
  HA `last_updated` freeze on the stub sensors)
- Sep 22 14:44 → now: continuous ~1/min

## Rain sensor — VERIFIED 2026-09-23

Rain = element `e5`, eleNum `147`. Overnight rain on 2026-09-22/23 produced
real data end-to-end (sensor → HMI → :8899 upload → cloud):

- Main event ~22:55–23:42 (+08 server time) — 47 min, peak `e5`=525,
  classic onset/peak/decay shape
- Second event ~03:12–03:45 — light drizzle, `e5` 1–28
- ~74 nonzero rows total; continuous ~1/min uploads all night

Note: `e5` reads 0 when it isn't raining — yesterday's "regs 4–15 all zero"
was absence of rain, not a copy bug. Exact unit of `e5` is unconfirmed
(likely intensity or 0.1 mm ticks — peak 525 suggests intensity×10 or a
rate field, not raw bucket counts). Calibrate against a reference if
precision matters.

## Useful on-device commands (telnet 192.168.31.148, root, no password)

- `cat /proc/net/route` — check default route (`00000000` + `011FA8C0`)
- `netstat -tn | grep 8899` — upload socket state
- `logcat -d` — `ak macro open host:39.99.253.232,port:8899` lines
- `screencap -p /data/local/tmp/scr.png` — screenshot (binary over tty is
  mangled: `\n`→`\r\n` and high bytes→spaces; decode carefully)
- `tcpdump -i wlan0 -XX port 8899` — decode upload frames live
- No `wc`, `head`, `md5sum`, `od`, `base64`, `curl`, `wget`; has `nc`,
  `tftp`, `sqlite3`, `gzip`, `tcpdump`. Device **cannot** reach `192.168.2.x`
  (gw doesn't route back) — transfer targets must be on `192.168.31.x`
  (michael-ha works).

## Credentials

`~/.config/secrets/rikacloud.env` (mode 600): `RIKA_ACCOUNT=R22100502`,
`RIKA_PASSWORD=…` — **verified working** against `:8005/login` 2026-09-22.
Never copy to chat, git, Ada memory, or backups.

## Source memory

- Key transcripts: `history_4cfecc165cec40c9`, `history_e451002457894faf`,
  `history_13665e98c78b41a8`, `history_63054d50dd784a00`
- Live verification via telnet + portal API on 2026-09-22.
