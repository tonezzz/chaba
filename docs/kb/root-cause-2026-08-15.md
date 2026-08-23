# Root Cause

## What it is

Root Cause

## Context/Background

**Date:** 2026-08-15
**Session Context:** 

## Key Details

### Technical Details
Root cause: Google Chrome was not running with a remote debugging port on any of the three hosts, so playlive chrome-live/playwright-chrome sessions failed with ECONNREFUSED to 127.0.0.1:9223 (tony-dell) or were unreachable.

Fixes applied:
- Started dedicated headless Google Chrome with --remote-debugging-port=9222 and a separate user-data-dir on tony-omen (/tmp/playlive-chrome-omen), tony-dell (/tmp/playlive-chrome-dell), and macbook (/tmp/playlive-chrome-mac).
- Restarted tony-dell playlived with PLAYLIVED_REMOTE_CDP=http://127.0.0.1:9222 so its default remote CDP matches the Chrome instance.
- Updated /home/tony/.local/playlive/remote-setup.sh on tony-dell to export PLAYLIVED_REMOTE_CDP=http://127.0.0.1:9222 for future restarts.
- For macbook, created an SSH tunnel from tony-omen (nohup ssh -N -L 9224:127.0.0.1:9222 macbook) because macbook has no playlived and Chrome's CDP only listens on 127.0.0.1.

Verification:
- Tony-dell playlive_create_chrome_live with target=remote now creates a session successfully via the existing playlive MCP (PLAYLIVE_URL=http://tony-dell:9230).
- Tony-omen playlived (http://127.0.0.1:9230) successfully created a chrome-live session with target=local against 127.0.0.1:9222.
- Tony-omen playlived successfully created a chrome-live session against macbook by using remote_url=http://127.0.0.1:9224 through the SSH tunnel.

Important discovery: Google Chrome with --headless=new and --remote-debugging-address=0.0.0.0 still binds CDP HTTP/WebSocket to 127.0.0.1 only. To access a remote host's CDP from another machine, use an SSH tunnel (ssh -N -L localport:127.0.0.1:9222 <host>) or a proxy such as socat.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-15
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
