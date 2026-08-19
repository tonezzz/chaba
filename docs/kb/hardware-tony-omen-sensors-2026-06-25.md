---
category: development
date: 2026-06-25
hostname: tony-omen
ip: 192.168.1.40
model: HP 15-BC (laptop)
board: HP 8641
cpu: Intel Core i7-9750H
---

# tony-omen — Sensor & disk health check

## Summary
- All temperatures are within safe limits; CPU and GPU are cool.
- `sensors-detect` did **not** discover any new sensor chips beyond the existing Intel `coretemp`.
- Internal NVMe SSD is healthy (5% wear, 0 media errors).
- External/USB drive (`/dev/sda`) reports SMART PASSED via the SAT pass-through driver.
- Battery is at full health (100%, 0 cycles).

## Tools installed / used
- `lm-sensors`
- `smartmontools`
- `nvme-cli`

## `sensors-detect` result
- **Intel digital thermal sensor (`coretemp`)** — confirmed.
- Super I/O probe found an **unknown chip with ID 0x8987** — no driver available.
- I2C/SMBus probe found only an `ee1004` EEPROM (not a sensor).
- No new modules were added.

## Temperatures

| Source | Sensor | Reading | Limits / Notes |
|---|---|---|---|
| `coretemp` | Package id 0 | 57.0°C | high 100°C, crit 100°C |
| `coretemp` | Core 0 | 57.0°C | high 100°C, crit 100°C |
| `coretemp` | Core 1 | 53.0°C | high 100°C, crit 100°C |
| `coretemp` | Core 2 | 48.0°C | high 100°C, crit 100°C |
| `coretemp` | Core 3 | 52.0°C | high 100°C, crit 100°C |
| `coretemp` | Core 4 | 50.0°C | high 100°C, crit 100°C |
| `coretemp` | Core 5 | 55.0°C | high 100°C, crit 100°C |
| `pch_cannonlake` | PCH | 60.0°C | |
| `acpitz` | temp1 | 46.0°C | |
| `iwlwifi_1` | Wi-Fi | 47.0°C | |
| `nvme` | Composite | 46.9°C | high 82.8°C, crit 89.8°C |
| `nvme` | Sensor 2 | 78.8°C | warm but below critical |
| `hp` | pwm1 | N/A | no exposed RPM |
| `BAT0-acpi-0` | Voltage | 10.57 V | |

## GPU — NVIDIA GeForce GTX 1650

| Metric | Value |
|---|---|
| Performance state | P8 |
| GPU temperature | 44°C |
| Shutdown temperature | 102°C |
| Slowdown temperature | 97°C |
| Max operating temperature | 102°C |
| Instantaneous power draw | 1.30 W |
| Power limit | 50.0 W |
| Graphics clock | 300 MHz |
| Memory clock | 405 MHz |
| Max graphics clock | 2,100 MHz |
| Max memory clock | 4,001 MHz |

## Disk — internal NVMe (`/dev/nvme0`)

- **SMART overall-health: PASSED**
- **Temperature:** 47°C (composite), 79°C (Sensor 2)
- **Percentage used:** 5%
- **Data read:** 49.2 TB
- **Data written:** 53.7 TB
- **Power cycles:** 1,520
- **Power-on hours:** 6,024
- **Unsafe shutdowns:** 40
- **Media errors:** 0
- **Critical warning:** 0x00

## Disk — external USB (`/dev/sda`)

- `smartctl -d sat -H /dev/sda` → **PASSED**
- `smartctl -d usbjmicron` / `usbsunplus` → unsupported on this bridge
- The drive appears to be behind a JMicron USB-SATA bridge that works with the SAT pass-through driver.

## Power (RAPL)

| Zone | Constraint | Limit |
|---|---|---|
| package-0 | long_term | 200.0 W |
| package-0 | short_term | 56.25 W |
| core | long_term | 0 W |
| uncore | long_term | 0 W |
| dram | long_term | 0 W |

## Battery

| Property | Value |
|---|---|
| Status | Full |
| Capacity | 100% |
| Cycle count | 0 |
| Charge full | 2,816 mAh |
| Charge full design | 2,816 mAh |
| Voltage now | 10.568 V |
| Voltage design | 11.400 V |

No measurable wear.

## Notes / follow-up
- NVMe secondary sensor runs warm (79°C) but is below the critical threshold (89.8°C) and no thermal warnings are logged.
- Consider checking NVMe temperature under sustained load.
