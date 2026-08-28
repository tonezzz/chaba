---
category: troubleshooting
---

# TradeCanvas UI Function Mismatch Fix & Modular Refactoring
## What it is

**Date:** 2026-08-08


**Date:** 2026-08-08  
**Category:** UI/JavaScript  
**Tags:** tradecanvas-ui, javascript, debugging, function-mismatch, modular-architecture
## Context/Background

Created 2026-08-08 as part of Chaba infrastructure documentation.


## Context

During development of Hindsight-01 and Hindsight-02 trading strategies, the compare.html page was stuck showing "Loading strategy" forever with JavaScript errors. Later refactored for easier debugging.

## Problem 1: Function Name Mismatch

The compare.html page was calling a JavaScript function that didn't exist, causing the strategy panel to fail initialization:

```javascript
// compare.html (incorrect)
chartLoader.init().then(() => initStrategyPanel(chartLoader));

// strategy-compare.js (actual function name)
function initComparePanel(chartLoader) {
    // ...
}
```

**Error:** `Uncaught (in promise) ReferenceError: initStrategyPanel is not defined`

## Root Cause 1

1. **Function name mismatch**: compare.html was calling `initStrategyPanel()` but strategy-compare.js defines `initComparePanel()`
2. **Wrong JavaScript file**: compare.html was also loading the old `strategy-engine.js` instead of the new `strategy-compare.js`
3. **Browser caching**: Changes weren't reflected due to browser cache

## Solution 1: Fix Function Name

Changed compare.html to call the correct function:

```html
<script>
    document.addEventListener('DOMContentLoaded', function() {
        const chartLoader = new ChartLoader({
            containerId: 'main-chart',
            symbol: 'THB',
            timeframe: 'all',
            showVolume: false,
            showIndicators: false,
            enableControls: false,
            enableWebSocket: false,
            enableMarkers: false,
            autoRefresh: false
        });

        window.chartLoader = chartLoader;
        chartLoader.init().then(() => initComparePanel(chartLoader)); // Fixed function name
    });
</script>
```

## Problem 2: Large Monolithic File

The `strategies.js` file became too large (821 lines) with all strategy implementations, making debugging difficult.

## Solution 2: Modular Refactoring

### Created Separate Module
- **`hindsight-strategies.js`** - New file containing Hindsight01Strategy and Hindsight02Strategy classes
- ~250 lines, focused solely on hindsight algorithms
- Easier to test and debug independently

### Updated Load Order
```html
<script src="chart-loader.js?v=14"></script>
<script src="strategies.js?v=14"></script>
<script src="hindsight-strategies.js?v=14"></script>
<script src="strategy-compare.js?v=14"></script>
```

### Dynamic Registration Pattern
```javascript
function initComparePanel(chartLoader) {
    // Register hindsight strategies from separate module
    if (typeof Hindsight01Strategy !== 'undefined') {
        StrategyFactory.register('hindsight_01', Hindsight01Strategy);
        console.log('Registered Hindsight-01 strategy');
    }
    if (typeof Hindsight02Strategy !== 'undefined') {
        StrategyFactory.register('hindsight_02', Hindsight02Strategy);
        console.log('Registered Hindsight-02 strategy');
    }
    // ... rest of init
}
```

### File Size Reduction
- **strategies.js**: Reduced from 821 lines to ~600 lines (removed 286 lines)
- **hindsight-strategies.js**: New 250-line focused module
- **Total**: More maintainable, easier to debug

## Benefits of Modular Approach

1. **Easier Debugging**: Smaller, focused files
2. **Independent Testing**: Can test hindsight strategies separately
3. **Clear Separation**: Core strategies vs hindsight strategies
4. **Better Organization**: Each module has a single responsibility
5. **Faster Development**: Changes to one strategy don't affect others

## Verification

After deployment:
1. Hard refresh browser (Ctrl+F5) to clear cache
2. Check console for "Registered Hindsight-01 strategy" and "Registered Hindsight-02 strategy"
3. Verify no JavaScript errors in console
4. Confirm strategy panel loads correctly
5. Test that Hindsight-01 and Hindsight-02 strategies are available

## Prevention

1. **Function name consistency**: Ensure function names match between HTML and JavaScript files
2. **File dependency tracking**: When replacing JavaScript files, update all references
3. **Cache busting during development**: Use version parameters (`?v=N`) on script tags
4. **Modular architecture**: Extract related functionality into separate modules when files grow large
5. **Dynamic registration**: Use registration pattern for modular strategy loading
6. **Test after deployment**: Always verify deployed files match development files

## Related Documentation

- `tradecanvas-ui/compare.html` - Main compare page
- `tradecanvas-ui/strategy-compare.js` - Strategy comparison logic
- `tradecanvas-ui/strategies.js` - Core strategy implementations
- `tradecanvas-ui/hindsight-strategies.js` - Hindsight strategy implementations
- `sync-tradecanvas-ui.sh` - Deployment sync script

## Lessons Learned

- Function name mismatches can cause silent failures in JavaScript
- Browser caching can mask deployment issues during development
- When replacing core JavaScript files, audit all references across the codebase
- Cache busting parameters are essential during active development
- Modular architecture improves maintainability and debugging
- Dynamic registration pattern enables flexible module loading
- Smaller files are easier to understand, test, and debug

## Tags

- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **docker**: docker
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **trading**: trading
- **finance**: finance
- **api**: api
- **2026**: 2026
