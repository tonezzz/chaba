# Yomi Daily2 Calendar Page (DEPRECATED)

## What it is

**DEPRECATED (2026-08-12)**: This page has been replaced by the modular daily implementation. The daily2 calendar functionality has been integrated into the main daily page at `/apps/yomi/daily/`.

Calendar-based daily summary viewer for Yomi LINE conversations with date selection and summary display.

## Context/Background

Created 2026-08-04 to provide alternative interface for daily summaries with calendar navigation instead of list view. **Replaced main daily implementation on 2026-08-12.**

## Current Status

**The daily2 implementation is now the primary daily interface.** Use `/apps/yomi/daily/` instead of `/apps/yomi/daily2/`.

- **New Location**: `/home/tony/CascadeProjects/chaba-yomi/stacks/web/public/apps/yomi/daily/index.html`
- **Access**: `http://tony-omen.local:8080/apps/yomi/daily/index.html`
- **Original Location**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/daily2/index.html` (kept for development)

## Key Details

### Technical Details
- **Current Location**: `/home/tony/CascadeProjects/chaba-yomi/stacks/web/public/apps/yomi/daily/`
- **Development Location**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/daily2/`
- **Access**: `http://tony-omen.local:8080/apps/yomi/daily/index.html`
- **Auth**: Basic auth (same as other Yomi pages)
- **Layout**: Three-panel design (calendar left, summary middle, messages right)

### Implementation
- Left panel: Monthly calendar with navigation, date selection, visual indicators for dates with summaries
- Middle panel: Daily summary display (events, actions, topics, message count)
- Right panel: Message list for selected date with media analysis capabilities
- Uses existing `/api/yomi/conversations` and `/api/yomi/daily` API endpoints
- Modular JavaScript architecture with separate modules for calendar, summary, and messages

### Files/Components
- `stacks/web/public/apps/yomi/daily/index.html` - Main page
- `stacks/web/public/apps/yomi/daily/js/init.js` - Initialization module
- `stacks/web/public/apps/yomi/daily/js/calendar.js` - Calendar rendering and interaction
- `stacks/web/public/apps/yomi/daily/js/summary.js` - Summary rendering and re-summarization
- `stacks/web/public/apps/yomi/daily/js/messages.js` - Message list and media analysis
- `stacks/web/public/apps/yomi/daily/js/app.js` - Main application coordination
- `stacks/web/public/apps/yomi/daily/styles/daily.css` - Styling
- `scripts/yomi/yomi-api.mjs` - API endpoints (existing)

## Usage/Commands

```bash
# Access the page (current)
http://tony-omen.local:8080/apps/yomi/daily/index.html?chat=<chatId>

# Access development version
http://tony-omen.local:8080/apps/yomi/daily2/index.html?chat=<chatId>

# Restart web stack if new files not picked up
just -f /home/tony/CascadeProjects/chaba/Justfile restart-web
```

## Troubleshooting

### Page not found (404)
- Restart web stack: `just -f /home/tony/CascadeProjects/chaba/Justfile restart-web`
- Verify file exists: `ls -la stacks/web/public/apps/yomi/daily/`
- Check Caddy is running: `docker ps | grep web`

### 401 Unauthorized
- Expected behavior - Yomi pages require basic auth
- Use Yomi credentials from environment configuration

## Related Documentation

- **[yomi.md](yomi.md)** - Yomi LINE web app comprehensive documentation
- **[yomi-daily-summaries.md](yomi-daily-summaries.md)** - Daily summarization quality and coverage
- **[yomi-media-analysis-http500.md](yomi-media-analysis-http500.md)** - Media analysis HTTP 500 error troubleshooting
- **[auto-kb-creation.md](../../.windsurf/workflows/auto-kb-creation.md)** - Automated KB creation workflow

## Tags

- **yomi**: LINE conversation management
- **daily-summaries**: Daily summary generation and display
- **calendar**: Date-based navigation interface
- **web-ui**: Static web interface components
- **deprecated**: No longer the primary interface
