# Fixed Eno1 Dhcp Tony-Omen

## What it is

Fixed Eno1 Dhcp Tony-Omen

## Context/Background

**Date:** 2026-08-19
**Session Context:** 

## Key Details

### Technical Details
Fixed eno1 DHCP on tony-omen. eno1 now uses IPv4 auto/DHCP, has stable 100 Mb/s full-duplex link, and obtained 192.168.2.80/24. Forced 100/full via ethtool was needed because auto-negotiation did not establish link. eno1 is configured as fallback with metric 60 (wlo1 primary 50, enx 100). Measured eno1 throughput ~9.5 MB/s (~76 Mbps). Job SSOT at docs/ssot/jobs/infrastructure/2026-08-19-fix-eno1-dhcp.yml.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-19
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
