// TradeCanvas SSOT Page Initializer
// Resolves the SSOT page config, loads page scripts, initializes ChartLoader,
// and renders configured Currency/Timeframe selectors.

(function () {
    function snakeToCamel(str) {
        return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    }

    function camelizeKeys(obj) {
        if (obj === null || typeof obj !== 'object') return obj;
        if (Array.isArray(obj)) return obj.map(camelizeKeys);
        const result = {};
        for (const [key, value] of Object.entries(obj)) {
            result[snakeToCamel(key)] = camelizeKeys(value);
        }
        return result;
    }

    function getVersion(src, versions) {
        const filename = src.split('/').pop().replace(/\.js$/, '');
        const key = filename.replace(/-/g, '_');
        if (versions && versions[key] !== undefined) return versions[key];
        if (versions && versions.default !== undefined) return versions.default;
        return '';
    }

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error(`Failed to load ${src}`));
            document.body.appendChild(script);
        });
    }

    async function initPage() {
        const config = await window.loadPageConfig();
        window.SSOTPageConfig = config;

        // Apply page layout as a body class
        const layout = (config.page && config.page.layout) || 'default';
        document.body.classList.add('layout-' + layout);

        // Load scripts list in order with cache-busting
        const shared = (config.scripts && config.scripts.shared) || [];
        const extra = (config.scripts && (config.scripts.extra || config.scripts.page)) || [];
        const tail = (config.scripts && config.scripts.tail) || [];
        const scripts = [...shared, ...extra, ...tail];
        const versions = (config.cache_busting && config.cache_busting.versions) || {};
        for (const src of scripts) {
            const v = getVersion(src, versions);
            const qs = v !== '' ? `?v=${v}` : '';
            await loadScript(src + qs);
        }

        // Initialize ChartLoader from merged chart_loader config
        const clConfig = config.chart_loader || {};
        const chartOptions = camelizeKeys(clConfig);
        if (!chartOptions.containerId) chartOptions.containerId = 'main-chart';

        // Honor localStorage currency/timeframe overrides
        try {
            const savedCurrency = localStorage.getItem('trade-canvas-selected-currency');
            const savedTimeframe = localStorage.getItem('trade-canvas-selected-timeframe');
            if (savedCurrency) chartOptions.symbol = savedCurrency;
            if (savedTimeframe) chartOptions.timeframe = savedTimeframe;
        } catch (e) {
            // localStorage may not be available in test contexts
        }

        const chartLoader = new ChartLoader(chartOptions);
        window.chartLoader = chartLoader;
        await chartLoader.init();

        // Render CurrencySelector if configured
        const cs = config.currency_selector;
        if (cs && typeof CurrencySelector !== 'undefined') {
            let selectedCurrency;
            try { selectedCurrency = localStorage.getItem('trade-canvas-selected-currency'); } catch (e) {}
            if (!selectedCurrency) selectedCurrency = cs.selected_currency || chartLoader.config.symbol;

            const cOptions = camelizeKeys(cs);
            cOptions.containerId = cs.container_id;
            cOptions.chartLoader = chartLoader;
            cOptions.selectedCurrency = selectedCurrency;

            const currencySelector = new CurrencySelector(cOptions);
            currencySelector.render();

            const pairLabel = document.getElementById('pair-label');
            if (pairLabel) {
                pairLabel.textContent = currencySelector.getCurrencyLabel(currencySelector.getCurrentCurrency());
            }

            currencySelector.on('currencyChange', (data) => {
                if (pairLabel) pairLabel.textContent = data.label;
            });

            window.currencySelector = currencySelector;
        }

        // Render TimeframeSelector if configured
        const ts = config.timeframe_selector;
        if (ts && typeof TimeframeSelector !== 'undefined') {
            let selectedTimeframe;
            try { selectedTimeframe = localStorage.getItem('trade-canvas-selected-timeframe'); } catch (e) {}
            if (!selectedTimeframe) selectedTimeframe = ts.selected_timeframe || chartLoader.config.timeframe;

            const tOptions = camelizeKeys(ts);
            tOptions.containerId = ts.container_id;
            tOptions.chartLoader = chartLoader;
            tOptions.selectedTimeframe = selectedTimeframe;

            const timeframeSelector = new TimeframeSelector(tOptions);
            timeframeSelector.render();

            window.timeframeSelector = timeframeSelector;
        }

        // Initialize the compare strategy panel
        if (typeof initComparePanel === 'function') {
            initComparePanel(chartLoader);
        } else {
            console.error('initComparePanel is not available after loading scripts');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPage);
    } else {
        initPage();
    }
})();
