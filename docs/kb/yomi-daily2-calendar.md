# Yomi Daily2 Calendar Page

## What it is

Calendar-based daily summary viewer for Yomi LINE conversations with date selection and summary display.

## Context/Background

Created 2026-08-04 to provide alternative interface for daily summaries with calendar navigation instead of list view.

## Key Details

### Technical Details
- **Location**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/daily2/index.html`
- **Access**: `http://tony-omen.local:8080/apps/yomi/daily2/index.html`
- **Auth**: Basic auth (same as other Yomi pages)
- **Layout**: Two-panel design (calendar left, summary right)

### Implementation
- Left panel: Monthly calendar with navigation, date selection, visual indicators for dates with summaries
- Right panel: Daily summary display (events, actions, topics, message count)
- Uses existing `/api/yomi/conversations` and `/api/yomi/daily` API endpoints
- Follows project styling conventions from original daily page

### Files/Components
- `stacks/web/public/apps/yomi/daily2/index.html` - Main page
- `stacks/web/Caddyfile` - Caddy configuration (no changes needed)
- `scripts/yomi/yomi-api.mjs` - API endpoints (existing)

## Usage/Commands

```bash
# Access the page
http://tony-omen.local:8080/apps/yomi/daily2/index.html?chat=<chatId>

# Restart web stack if new files not picked up
just -f /home/tony/CascadeProjects/chaba/Justfile restart-web
```

## Troubleshooting

### Page not found (404)
- Restart web stack: `just -f /home/tony/CascadeProjects/chaba/Justfile restart-web`
- Verify file exists: `ls -la stacks/web/public/apps/yomi/daily2/`
- Check Caddy is running: `docker ps | grep web`

### 401 Unauthorized
- Expected behavior - Yomi pages require basic auth
- Use Yomi credentials from environment configuration

## Related Documentation

- **[yomi.md](yomi.md)** - Yomi LINE web app comprehensive documentation
- **[auto-kb-creation.md](../../.windsurf/workflows/auto-kb-creation.md)** - Automated KB creation workflow

## Tags

- **yomi**: LINE conversation management
- **daily-summaries**: Daily summary generation and display
- **calendar**: Date-based navigation interface
- **web-ui**: Static web interface components
