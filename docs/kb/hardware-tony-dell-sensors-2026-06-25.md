---
category: development
date: 2026-06-25
hostname: tony-dell
ip: 192.168.1.37
model: Dell Inc. OptiPlex 7040
board: Dell Inc. 0HD5W2
cpu: Intel Core i7-6700
---

# tony-dell — Sensor & disk health check

## Summary
- All temperatures are within normal limits.
- `sensors-detect` did **not** find any new sensor chips; only the existing Intel `coretemp` sensor was confirmed.
- Internal HDD is still functional but has **8 pending sectors** and **8 offline uncorrectable sectors** that should be monitored.
- No battery present.

## Tools installed / used
- `lm-sensors` (already present)
- `smartmontools`
- `nvme-cli`

## `sensors-detect` result
- **Intel digital thermal sensor (`coretemp`)** — confirmed.
- Super I/O probe found an **unknown SMSC chip with ID 0xc9a1** — no driver available.
- I2C/SMBus probe found only an `ee1004` EEPROM (not a sensor).
- No new modules were added.

## Temperatures / fans

| Source | Sensor | Reading | Limits / Notes |
|---|---|---|---|
| `coretemp` | Package id 0 | 47.0°C | high 84°C, crit 100°C |
| `coretemp` | Core 0 | 53.0°C | high 84°C, crit 100°C |
| `coretemp` | Core 1 | 51.0°C | high 84°C, crit 100°C |
| `coretemp` | Core 2 | 51.0°C | high 84°C, crit 100°C |
| `coretemp` | Core 3 | 49.0°C | high 84°C, crit 100°C |
| `dell_smm` | Ambient | 45.0°C | |
| `dell_smm` | CPU | 39.0°C | |
| `dell_smm` | Processor Fan | 1,146 RPM | max 3,300 RPM |
| `dell_smm` | Motherboard Fan | 2,456 RPM | max 3,100 RPM |
| `pch_skylake` | PCH | 51.5°C | |
| `acpitz` | temp1 | 27.8°C | |
| `acpitz` | temp2 | 29.8°C | |
| `amdgpu` | GPU edge | 50.0°C | crit 120°C |
| `amdgpu` | pwm1 | 49% | |
| `amdgpu` | sclk / mclk | 300 / 1000 MHz | |

## Disk (`/dev/sda`) — Seagate ST500LM000-1EJ162

- **SMART overall-health: PASSED**
- **Temperature:** 42°C
- **Power-on hours:** 8,170
- **Power cycle count:** 3,244
- **Start/stop count:** 2,886

### Attributes of concern

| ID | Attribute | Value | Raw |
|---|---|---|---|
| 5 | Reallocated_Sector_Ct | 100 | 0 |
| 187 | Reported_Uncorrect | 1 | **299** |
| 188 | Command_Timeout | 100 | 1 |
| 190 | Airflow_Temperature_Cel | 58 | 42°C |
| 193 | Load_Cycle_Count | 1 | **306,291** |
| 197 | Current_Pending_Sector | 100 | **8** |
| 198 | Offline_Uncorrectable | 100 | **8** |

### Self-test
- **Short offline test started:** 2026-06-25 17:01:48
- **Scheduled completion:** 2026-06-25 17:03:48
- **Status when last checked:** in progress (90% remaining)
- **Final result:** *not captured in this log — run `sudo smartctl -l selftest /dev/sda` to update*

## Power (RAPL)

| Zone | Constraint | Limit |
|---|---|---|
| package-0 | long_term | 65.0 W |
| package-0 | short_term | 81.25 W |
| core | long_term | 0 W |
| uncore | long_term | 0 W |
| dram | long_term | 0 W |

## Battery
- No battery present on this machine.

## Notes / follow-up
- The 8 pending sectors are the main item to watch. If the count increases, the drive should be replaced.
- Re-run the short self-test and capture the final result.
- Check the pending sector count again in ~30 days.
