# TradeCanvas UI Architecture

## Overview
The TradeCanvas UI uses a modular architecture with shared components to avoid code duplication between pages.

## File Structure

### Core Components
- **chart-loader.js** - Shared chart loading module used by all pages
- **styles.css** - Shared styling for all pages
- **nav.js** - Navigation menu active state handler
- **favicon.svg** - Site favicon

### Page-Specific Files
- **index.html** - Full-featured trading dashboard
- **compare.html** - Simplified comparison page
- **app.js** - Legacy full application (being phased out)
- **compare.js** - Legacy compare page logic (being phased out)

## Chart Loader Module

### Purpose
The `chart-loader.js` module provides a unified interface for initializing and managing Lightweight Charts across different pages.

### Features
- **Configurable initialization** - Different pages can enable/disable features
- **Shared data loading** - API integration with fallback to sample data
- **Consistent UI updates** - Standardized price and statistics display
- **Optional features** - Volume, indicators, WebSocket, controls, markers

### Configuration Options
```javascript
const chartLoader = new ChartLoader({
    containerId: 'main-chart',      // Chart container element ID
    symbol: 'THB',                  // Trading symbol
    timeframe: '1Y',                // Time period
    showVolume: true,              // Enable volume chart
    showIndicators: true,          // Enable technical indicators
    enableControls: true,           // Enable zoom controls
    enableWebSocket: true,          // Enable real-time updates
    enableMarkers: true,            // Enable chart markers
    autoRefresh: true,              // Enable auto-refresh
    chartSettings: {                // Custom colors
        upColor: '#238636',
        downColor: '#da3633',
        // ...
    }
});
```

### Page Configurations

#### index.html (Full Dashboard)
```javascript
new ChartLoader({
    containerId: 'main-chart',
    symbol: 'THB',
    timeframe: '1Y',
    showVolume: true,
    showIndicators: true,
    enableControls: true,
    enableWebSocket: true,
    enableMarkers: true,
    autoRefresh: true
});
```

#### compare.html (Simplified)
```javascript
new ChartLoader({
    containerId: 'main-chart',
    symbol: 'THB',
    timeframe: '1Y',
    showVolume: false,
    showIndicators: false,
    enableControls: false,
    enableWebSocket: false,
    enableMarkers: false,
    autoRefresh: false
});
```

## Data Flow

### Data Loading Process
1. **API Attempt** - Try to fetch from `http://tony-omen.local:8080/apps/trade/api`
2. **Fallback** - Use sample data if API unavailable
3. **Chart Update** - Update candlestick series with data
4. **UI Update** - Update price, statistics, and connection status

### Sample Data Generation
- Generates 1 year of daily data
- Skips weekends
- Uses realistic volatility (2% of base price)
- Supports multiple symbols (THB, EUR, GBP, JPY, DXY, OIL)

## Deployment Architecture

### Development vs Production
- **Development**: `/home/tony/CascadeProjects/trade/tradecanvas-ui/`
- **Production**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/trade/tradecanvas-ui/`
- **Web Server**: Caddy serving from production directory
- **URL**: `http://tony-omen.local:8080/apps/trade/tradecanvas-ui/`

### File Synchronization
Use the deployment-sync skill or sync script:
```bash
./sync-tradecanvas-ui.sh
```

## Migration Path

### Phase 1: Current State
- ✅ Created `chart-loader.js` shared module
- ✅ Updated `compare.html` to use shared loader
- ✅ Updated `index.html` to use shared loader
- ✅ Deployed to production directory

### Phase 2: Cleanup (Future)
- Remove `app.js` (functionality moved to chart-loader)
- Remove `compare.js` (functionality moved to chart-loader)

### Phase 3: Enhancement (Future)
- Add WebSocket real-time updates to chart-loader
- Add technical indicators to chart-loader
- Add chart markers functionality to chart-loader
- Add auto-refresh to chart-loader

## UI SSOT Model

The TradeCanvas UI is configured through a four-layer Single Source of Truth (SSOT) YAML system. The loader in `tradecanvas-ui/strategy-compare-new.js` deep-merges the layers in the following order, with later layers overriding earlier ones:

1. **Base SSOT** — `config/ssot/ssot.ui.yml` — global defaults shared by every page.
2. **Family SSOT** — `config/ssot/ssot.ui.compare-family.yml` — shared configuration for the compare page family.
3. **Page SSOT** — `config/ssot/ssot.ui.<page>.yml` — per-page overrides (e.g., `ssot.ui.compare.yml` for the stable page, `ssot.ui.compare2.yml` for the experimental preview page).
4. **Feature SSOTs** — `config/ssot/ssot.ui.feature.<name>.yml` — optional feature-specific overlays requested by the page.

Any `ref` markers are stripped during the merge.

### Feature Promotion Workflow

- `compare2` is the experimental/preview page.
- Create new feature SSOTs under `config/ssot/ssot.ui.feature.<name>.yml` and enable them on `compare2` first.
- If `scripts/validate-ui-ssot.sh` exists, run it to validate SSOT changes before promoting.
- Once the feature is validated, promote its configuration into the compare family SSOT (`config/ssot/ssot.ui.compare-family.yml`) or the stable `compare` page SSOT (`config/ssot/ssot.ui.compare.yml`) as appropriate.
- Sync the updated files to the production directory with `./sync-tradecanvas-ui.sh` from the project root.

## Benefits of Shared Architecture

### Code Reusability
- Single source of truth for chart logic
- Easy to add features to all pages simultaneously
- Reduced maintenance burden

### Consistency
- Same data loading logic across pages
- Consistent UI updates and styling
- Uniform error handling

### Maintainability
- Bug fixes apply to all pages
- Easy to test changes in one place
- Clear separation of concerns

### Performance
- Shared code reduces page load time
- Caching benefits for shared JavaScript
- Consistent user experience

## Troubleshooting

### Chart Not Displaying
1. Check browser console for errors
2. Verify `chart-loader.js` is loaded
3. Verify LightweightCharts library is loaded
4. Check container element exists
5. Verify container has dimensions

### Data Not Loading
1. Check API endpoint is accessible
2. Verify network connectivity
3. Check browser console for API errors
4. Fallback to sample data should work automatically

### File Sync Issues
1. Use deployment-sync skill to investigate
2. Check file permissions in production directory
3. Verify web server configuration
4. Test URL accessibility with curl

## Future Enhancements

### Planned Features
- Real-time WebSocket integration
- Technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands)
- Chart markers and annotations
- Multiple timeframe support
- Custom chart themes
- Export functionality
- Advanced chart types

### Architecture Improvements
- Component-based UI framework
- State management system
- Plugin system for indicators
- Configuration file support
- Internationalization (i18n)
