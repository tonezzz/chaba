# Assessed Forced Network Settings On Tony-Omen And Tony-Dell Tony-Omen

## What it is

Assessed Forced Network Settings On Tony-Omen And Tony-Dell Tony-Omen

## Context/Background

**Date:** 2026-08-25
**Session Context:** 

## Key Details

### Technical Details
Assessed forced network settings on tony-omen and tony-dell. tony-omen: eno1 now clean (auto-negotiate yes), only wired USB iPhone tether has auto-negotiate no (expected) and netplan-eno1 ipv4.route-metric 40. tony-dell: active enp0s31f6 auto-negotiate no in NM but ethtool shows on/1000 (likely ignored); stale netplan-enp4s0f0 profile with auto-negotiate no for non-existent device.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-25
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
