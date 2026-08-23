# Tony-Dell Iphone Personal Hotspot Troubleshooting 2026-08-18

## What it is

Tony-Dell Iphone Personal Hotspot Troubleshooting 2026-08-18

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
Tony-Dell iPhone Personal Hotspot troubleshooting (2026-08-18):
- The tony-dell Wi-Fi adapter (wlx00761100125e) is a Ralink MT7601U (148f:7601) and is 2.4 GHz only (channels 1-14, 2412-2484 MHz).
- The `mt7601u` kernel driver is loaded and the device is recognized by `lsusb`.
- `iw dev` and `iw list` work without root; `nmcli device wifi list` and `nmcli device wifi rescan` require root/authorization.
- Modern iPhone Personal Hotspot defaults to 5 GHz when "Maximize Compatibility" is off, so the MT7601U cannot see it.
- Next required action: user enables "Maximize Compatibility" in iPhone Settings > Personal Hotspot, then re-scan on tony-dell.

Conventions:
- For MT7601U-only 2.4 GHz clients, iPhone hotspot must use "Maximize Compatibility" to force 2.4 GHz.
- `iw list` is a safe, non-root way to verify supported Wi-Fi frequencies before changing phone settings.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-18
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
