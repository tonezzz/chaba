# Health Check Dashboard

Location-aware health monitoring dashboard for Chaba services.

## Features

- **Auto-detection**: Automatically detects if you're on home network or mobile
- **Manual override**: Manually select location if auto-detection fails
- **Location-specific configs**: Different health check configurations for home vs mobile
- **Category filtering**: Filter services by category (web, api, datastore, gpu, queue, optional)
- **Auto-refresh**: Configurable auto-refresh (default 30 seconds)
- **Recovery actions**: Displays suggested recovery actions for common failure modes

## Location Modes

### Auto-detect (default)
- Tries to reach local endpoint `http://tony-omen.local:8080/api/status`
- If successful: uses home configuration
- If fails: uses mobile configuration
- 2-second timeout for detection

### Home (Local)
- Full local network access
- All services available including container checks
- Direct access to GPU services
- Faster timeouts (5-10 seconds)

### Mobile (External)
- External/VPN access only
- Limited service set (no container checks)
- Longer timeouts (10-15 seconds)
- Mobile-specific recovery actions

## Configuration Files

- `ssot.health.home.yml` - Full local network configuration
- `ssot.health.mobile.yml` - External/mobile configuration with limited services

## Usage

1. Open dashboard: `http://tony-omen.local:8080/apps/health-check/`
2. Dashboard auto-detects location and loads appropriate config
3. Use location selector to manually override if needed
4. Use category filter to focus on specific service types
5. Click "Refresh Now" for on-demand health checks
6. Toggle auto-refresh for automatic updates

## Mobile Configuration Notes

The mobile configuration:
- Excludes container-based checks (don't work externally)
- Uses longer timeouts for external network latency
- Includes mobile-specific recovery actions (VPN, network issues)
- Focuses on HTTP-accessible services only

## Future Enhancements

- Add external domain support (replace tony-omen.local with your domain)
- Add VPN-specific configuration
- Add office/travel location profiles
- Add historical health data and trends
- Add alert notifications for critical failures
