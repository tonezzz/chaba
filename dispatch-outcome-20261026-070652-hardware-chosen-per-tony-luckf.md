# Dispatch outcome — nest-node-hardware plan doc (2026-10-26)

**Result:** Done. Wrote `reports/nest-node-hardware.md` — the order checklist + provisioning runbook for Tony's chosen hardware (Luckfox Pico Ultra W vision node + ESP32-P4-EYE MCU node, ~$75). No purchase made, per task.

## What the doc covers

- **Order checklist**: exact SKUs — Pico Ultra W must be the **RV1106G3** variant (1 TOPS/256 MB, not the G2 "B"), camera module is **not bundled** (SC3336 3MP recommended / MIS5001 5MP option); P4-EYE is self-contained (cam+mic+LCD+radio) but needs its u.FL antenna confirmed in-box. Accessories: USB-C power, optional PoE module deferred, optional microSD. Vendors + ~$70–85 landed budget.
- **Vision-node runbook**: first contact via USB-C RNDIS (`172.32.0.93`, `root`/`luckfox`); buildroot image required (CSI cam + onboard mic are buildroot-only per Luckfox wiki); camera wiring rule (ribbon metal side faces RV1106) → `luckfox-config` enable CSI → `rkipc` RTSP `/live/0`+`/live/1`; onboard analog mic works as-shipped (`arecord` verify), external mic needs MICBIAS circuit — deferred; WiFi → `TONY-WIFI_2.4G` + DHCP reservation; tailnet via armv7 tailscaled (userspace-networking fallback, LAN-relay escape); Frigate enroll through `frigate/cameras.json` + existing rebuild workflow on tony-omen; first detection → MDDB `ada-ha-events-tony` ops event (same payload shape as `kanban-dispatch.py`), `nest-eye-01` CMS page → `/chaba-nest` dashboard tile via existing auto-discovery regex.
- **MCU-node runbook**: ESP-IDF v5.4+ on tony-dell, USB debug port (USB-Serial-JTAG); lane A esp-dl/ESP-WHO person-detect (recommended, matches card's 73 ms metric) vs lane B ESPHome (fleet-consistent but P4 MIPI-CSI camera support unverified — flagged as decision point); HA enroll via ESPHome api or MQTT discovery; ops event via HA automation/LAN relay.

## Notable findings baked into the plan

- Card verify demands detections "via tailnet" — Luckfox is LAN-native, so the runbook carries a documented tailscaled-vs-relay decision point (256 MB RAM is tight).
- Frigate runs on tony-omen (`:5000`); camera additions go through `frigate/cameras.json` → `generate_config.py` → `just rebuild-cameras` + `restart-frigate` (existing workflow).
- Nest dashboard tiles auto-surface for `nest-*` CMS slugs (PROPOSED state → Tony accepts), matching the card's "visible on the nest dashboard lane" verify.

## How to verify

`reports/nest-node-hardware.md` exists on this dispatch branch with sections 1–7; board card `nest-node-hardware` has a `devin` comm pointing at the doc. Next step (not this dispatch): Tony orders the kit, then a bring-up session runs sections 3–5.

## Files changed

- `reports/nest-node-hardware.md` (new) — the plan doc
- This outcome file
- Board comment posted via board-api (`/comment`)
