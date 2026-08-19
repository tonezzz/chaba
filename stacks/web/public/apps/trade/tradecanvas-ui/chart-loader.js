// Chart Loader (Controller) for TradeCanvas
// Orchestrates ChartDataProvider and ChartRenderer and exposes the public control API.

class ChartLoader {
    constructor(options = {}) {
        this.config = {
            containerId: options.containerId || 'main-chart',
            symbol: options.symbol || localStorage.getItem('trade-canvas-selected-currency') || 'THB',
            timeframe: options.timeframe || localStorage.getItem('trade-canvas-selected-timeframe') || '1Y',
            chartType: options.chartType || localStorage.getItem('trade-canvas-chart-type') || 'candlestick',
            showVolume: options.showVolume !== false,
            showIndicators: options.showIndicators || false,
            enableWebSocket: options.enableWebSocket || false,
            enableControls: options.enableControls !== false,
            enableMarkers: options.enableMarkers || false,
            autoRefresh: options.autoRefresh || false,
            ...options
        };

        this.chartSettings = {
            upColor: options.upColor || '#238636',
            downColor: options.downColor || '#da3633',
            backgroundColor: options.backgroundColor || '#21262d',
            gridColor: options.gridColor || '#30363d',
            ...options.chartSettings
        };

        this.data = [];
        this.isSampleData = false;
        this.loadedFromAPI = false;

        this.dataProvider = null;
        this.renderer = null;
    }

    get chart() {
        return this.renderer ? this.renderer.chart : null;
    }

    get candlestickSeries() {
        return this.renderer ? this.renderer.candlestickSeries : null;
    }

    getBasePrices() {
        return {
            'THB': 35.5,
            'EUR': 1.08,
            'GBP': 1.27,
            'JPY': 155.0,
            'GOLD': 4401.94,
            'DXY': 105.0,
            'OIL': 75.0
        };
    }

    async init() {
        console.log('ChartLoader initializing for', this.config.symbol);

        const statusEl = document.getElementById('connection-status');
        if (statusEl) {
            statusEl.textContent = 'Loading';
            statusEl.className = 'status';
        }

        try {
            this.dataProvider = new ChartDataProvider({
                basePrices: this.getBasePrices()
            });

            this.renderer = new ChartRenderer({
                containerId: this.config.containerId,
                chartType: this.config.chartType,
                chartSettings: this.chartSettings
            });

            this.renderer.initializeChart();
            await this.loadData();

            if (this.config.enableControls) {
                this.renderer.setupControls();
            }

            if (this.config.enableWebSocket) {
                this.connectWebSocket();
            }

            if (this.config.autoRefresh) {
                this.startAutoRefresh();
            }

            console.log('ChartLoader initialized successfully');
        } catch (error) {
            console.error('ChartLoader initialization error:', error);

            // Fall back to sample data.
            if (this.dataProvider && this.renderer) {
                this.data = this.dataProvider.generateSampleData(this.config.symbol, this.config.timeframe);
                this.isSampleData = true;
                this.loadedFromAPI = false;
                this.renderer.updateChart(this.data, this.config.chartType);
                this.updateUI();
            }
        }
    }

    async loadData() {
        console.log('Loading data for', this.config.symbol);
        if (!this.dataProvider || !this.renderer) return;

        const result = await this.dataProvider.loadData(this.config.symbol, this.config.timeframe);
        this.data = result.data;
        this.isSampleData = result.isSampleData;
        this.loadedFromAPI = result.loadedFromAPI;

        this.renderer.updateChart(this.data, this.config.chartType);
        this.updateUI();
    }

    updateUI() {
        // Update connection status even when data is empty so the user
        // sees whether the loader is working, empty, or on sample data.
        const statusEl = document.getElementById('connection-status');
        if (statusEl) {
            if (this.isSampleData) {
                statusEl.textContent = 'Sample Data';
                statusEl.className = 'status disconnected';
            } else if (this.loadedFromAPI) {
                statusEl.textContent = 'API Data';
                statusEl.className = 'status connected';
            } else if (this.data.length > 0) {
                statusEl.textContent = 'CSV Data';
                statusEl.className = 'status connected';
            } else {
                statusEl.textContent = 'No Data';
                statusEl.className = 'status disconnected';
            }
        }

        if (this.data.length === 0) return;

        const latestData = this.data[this.data.length - 1];
        const previousData = this.data[this.data.length - 2] || this.data[0];

        // Update current price.
        const currentPriceEl = document.getElementById('current-price');
        if (currentPriceEl) {
            currentPriceEl.textContent = latestData.close.toFixed(2);
        }

        // Update price change.
        const priceChangeEl = document.getElementById('price-change');
        if (priceChangeEl) {
            const change = latestData.close - previousData.close;
            const changePercent = ((change / previousData.close) * 100).toFixed(2);
            priceChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
            priceChangeEl.className = change >= 0 ? 'positive' : 'negative';
        }

        // Update summary stats.
        const statElements = {
            'stat-open': latestData.open.toFixed(2),
            'stat-high': latestData.high.toFixed(2),
            'stat-low': latestData.low.toFixed(2),
            'stat-close': latestData.close.toFixed(2),
        };

        for (const [id, value] of Object.entries(statElements)) {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        }

        // Update change percentage.
        const change = latestData.close - previousData.close;
        const changePercent = ((change / previousData.close) * 100).toFixed(2);
        const statChangeEl = document.getElementById('stat-change');
        if (statChangeEl) {
            statChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
        }
    }

    connectWebSocket() {
        // WebSocket connection for real-time updates.
        // Implementation depends on requirements.
        console.log('WebSocket connection not implemented in basic loader');
    }

    startAutoRefresh() {
        // Auto-refresh implementation.
        console.log('Auto-refresh not implemented in basic loader');
    }

    // Public methods for external control.
    updateSymbol(symbol) {
        this.config.symbol = symbol;
        try { localStorage.setItem('trade-canvas-selected-currency', symbol); } catch (e) {}
        this.loadData();
    }

    updateTimeframe(timeframe) {
        this.config.timeframe = timeframe;
        try { localStorage.setItem('trade-canvas-selected-timeframe', timeframe); } catch (e) {}
        this.loadData();
    }

    refresh() {
        this.loadData();
    }
}

// Export for use in different pages.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartLoader;
}
