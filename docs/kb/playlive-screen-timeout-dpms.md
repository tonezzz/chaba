---
category: operations
---

# PlayLive Screen Timeout: DPMS Session Closure

## What it is

DPMS (Display Power Management Signaling) screen power management causes PlayLive Chrome CDP sessions to close unexpectedly, breaking browser automation with "Target page, context or browser has been closed" errors. Resolved with a time-based screen timeout scheduler that balances PlayLive compatibility with power savings.

## Context/Background

Identified during PlayLive automation operations where Chrome CDP sessions would fail after periods of inactivity. The root cause was DPMS screen power management turning off the display, which caused Chrome CDP connections to terminate. This created a conflict between power saving needs and PlayLive's requirement for persistent browser sessions.

## Related Documentation

- **[ssot.apps.playlive.yml](../ssot/apps/ssot.apps.playlive.yml)** - PlayLive SSOT documentation with screen power management limitation note
- **[playlive-authentication.md](./playlive-authentication.md)** - PlayLive basic authentication implementation
- **[playwright-vs-playlive.md](./playwright-vs-playlive.md)** - PlayLive vs Playwright comparison and architecture

## Tags

- **playlive**: Browser automation daemon
- **dpms**: Display Power Management Signaling
- **screen-timeout**: Display power management configuration
- **chrome-cdp**: Chrome DevTools Protocol
- **automation**: Browser automation reliability
- **infrastructure**: System configuration and scheduling
- **power-management**: Energy saving configuration
- **troubleshooting**: Session closure debugging

## See also

- [Playlive Screen Timeout Dpms Implementation](playlive-screen-timeout-dpms-implementation.md)
- [Playlive Screen Timeout Dpms Troubleshooting](playlive-screen-timeout-dpms-troubleshooting.md)
- [Playlive Screen Timeout Dpms Verification](playlive-screen-timeout-dpms-verification.md)
