// Trading UI Application
// Connects to Trade API and implements Wick-inspired trading components

const API_BASE_URL = 'http://tony-omen.local:8080/apps/trade/api';

class TradingDashboard {
    constructor() {
        this.currentAsset = 'THB';
        this.currentPeriod = '1y';
        this.chart = null;
        this.depthChart = null;
        this.candlestickSeries = null;
        this.depthSeries = null;
        this.initialChartLoad = false; // Track if this is the initial chart load
        this.markers = []; // Store chart markers
        this.syncTimeout = null; // Debounce timeout for sync operations
        this.data = {
            exchangeRates: {},
            dollarIndex: [],
            commodityPrices: {}
        };
        
        this.init();
    }

    debouncedSync(callback, delay = 50) {
        // Debounce sync operations to improve performance
        clearTimeout(this.syncTimeout);
        this.syncTimeout = setTimeout(() => {
            callback();
        }, delay);
    }

    async init() {
        this.setupEventListeners();
        this.initializeCharts();
        await this.loadAllData();
        this.startAutoRefresh();
    }

    setupEventListeners() {
        // Asset selector
        document.getElementById('asset-selector').addEventListener('change', (e) => {
            this.currentAsset = e.target.value;
            this.initialChartLoad = false; // Reset for new asset
            this.updateDashboard();
        });

        // Period selector
        document.getElementById('period-selector').addEventListener('change', (e) => {
            this.currentPeriod = e.target.value;
            this.initialChartLoad = false; // Reset for new period
            this.updateDashboard();
        });

        // Refresh button
        document.getElementById('refresh-btn').addEventListener('click', () => {
            this.loadAllData();
        });

        // Add marker button
        document.getElementById('add-marker-btn').addEventListener('click', () => {
            this.addRandomMarker();
        });

        // Clear markers button
        document.getElementById('clear-markers-btn').addEventListener('click', () => {
            this.clearMarkers();
        });

        // Chart type controls
        document.querySelectorAll('.chart-control-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.chart-control-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.initialChartLoad = false; // Reset for new chart type
                this.changeChartType(e.target.dataset.type);
            });
        });
    }

    initializeCharts() {
        // Check if LightweightCharts is available
        if (typeof LightweightCharts === 'undefined') {
            console.error('LightweightCharts library not loaded');
            setTimeout(() => this.initializeCharts(), 500);
            return;
        }

        // Initialize Candlestick Chart
        const candlestickContainer = document.getElementById('candlestick-chart');
        this.chart = LightweightCharts.createChart(candlestickContainer, {
            width: candlestickContainer.clientWidth,
            height: candlestickContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: '#21262d' },
                textColor: '#e6edf3',
            },
            grid: {
                vertLines: { color: '#30363d' },
                horzLines: { color: '#30363d' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: '#30363d',
            },
            timeScale: {
                borderColor: '#30363d',
                timeVisible: true,
            },
        });

        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: '#238636',
            downColor: '#da3633',
            borderDownColor: '#da3633',
            borderUpColor: '#238636',
            wickDownColor: '#da3633',
            wickUpColor: '#238636',
        });

        // Initialize Depth Chart
        const depthContainer = document.getElementById('depth-chart');
        this.depthChart = LightweightCharts.createChart(depthContainer, {
            width: depthContainer.clientWidth,
            height: depthContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: '#21262d' },
                textColor: '#e6edf3',
            },
            grid: {
                vertLines: { color: '#30363d' },
                horzLines: { color: '#30363d' },
            },
            rightPriceScale: {
                borderColor: '#30363d',
            },
            timeScale: {
                visible: false,
                timeVisible: false,
            },
        });

        this.depthSeries = this.depthChart.addHistogramSeries({
            color: '#58a6ff',
            priceFormat: {
                type: 'volume',
            },
            priceScaleId: '',
        });

        // Sync time scale with main chart (debounced for performance)
        this.chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (range) {
                this.debouncedSync(() => {
                    this.depthChart.timeScale().setVisibleLogicalRange(range);
                });
            }
        });

        // Sync zoom from depth chart to main chart (debounced for performance)
        this.depthChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (range) {
                this.debouncedSync(() => {
                    this.chart.timeScale().setVisibleLogicalRange(range);
                });
            }
        });

        // Price scale synchronization removed - API method not available

        // Sync crosshair from depth chart to main chart
        this.depthChart.subscribeCrosshairMove(param => {
            if (!param.time || !param.point) {
                return;
            }
            this.chart.setCrosshairPosition(param.point, param.time, this.depthSeries);
        });

        // Handle resize with debouncing for performance
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                const chartWidth = candlestickContainer.clientWidth;
                const depthWidth = depthContainer.clientWidth;

                // Apply proportional resizing
                this.chart.applyOptions({ width: chartWidth });
                this.depthChart.applyOptions({ width: depthWidth });
            }, 100); // 100ms debounce for performance
        });

        // Crosshair move handler
        this.chart.subscribeCrosshairMove(param => {
            if (!param.time || !param.point) {
                return;
            }

            // Sync crosshair to depth chart
            this.depthChart.setCrosshairPosition(param.point, param.time, this.candlestickSeries);
        });
    }

    async loadAllData() {
        try {
            await Promise.all([
                this.loadExchangeRates(),
                this.loadDollarIndex(),
                this.loadCommodityPrices()
            ]);
            this.updateDashboard();
            this.updateLastUpdateTime();
        } catch (error) {
            console.error('Error loading data:', error);
            this.showError('Failed to load data. Please try again.');
        }
    }

    async loadExchangeRates() {
        try {
            const response = await fetch(`${API_BASE_URL}/available/currencies`);
            const data = await response.json();
            
            for (const currency of data.items) {
                const rateResponse = await fetch(
                    `${API_BASE_URL}/exchange_rates/${currency}?period=${this.currentPeriod}`
                );
                const rateData = await rateResponse.json();
                this.data.exchangeRates[currency] = rateData.data || rateData;
            }
        } catch (error) {
            console.error('Error loading exchange rates:', error);
        }
    }

    async loadDollarIndex() {
        try {
            const response = await fetch(
                `${API_BASE_URL}/dollar_index?period=${this.currentPeriod}`
            );
            const data = await response.json();
            this.data.dollarIndex = data.data || data;
        } catch (error) {
            console.error('Error loading dollar index:', error);
        }
    }

    async loadCommodityPrices() {
        try {
            const response = await fetch(`${API_BASE_URL}/available/commodities`);
            const data = await response.json();
            
            for (const commodity of data.items) {
                const priceResponse = await fetch(
                    `${API_BASE_URL}/commodity_prices/${commodity}?period=${this.currentPeriod}`
                );
                const priceData = await priceResponse.json();
                this.data.commodityPrices[commodity] = priceData.data || priceData;
            }
        } catch (error) {
            console.error('Error loading commodity prices:', error);
        }
    }

    updateDashboard() {
        this.updatePriceTicker();
        this.updateCandlestickChart();
        this.updateDepthChart();
        this.updateTradeFeed();
        this.updateStatistics();
    }

    updatePriceTicker() {
        // Update exchange rate tickers
        this.updateTickerItem('THB', this.data.exchangeRates.THB);
        this.updateTickerItem('EUR', this.data.exchangeRates.EUR);
        this.updateTickerItem('GBP', this.data.exchangeRates.GBP);
        this.updateTickerItem('JPY', this.data.exchangeRates.JPY);
        
        // Update DXY ticker
        this.updateTickerItem('DXY', this.data.dollarIndex, 'value');
        
        // Update commodity tickers
        this.updateTickerItem('GOLD', this.data.commodityPrices.GOLD, 'price');
        this.updateTickerItem('OIL', this.data.commodityPrices.OIL, 'price');
    }

    updateTickerItem(symbol, data, priceField = 'rate') {
        if (!data || data.length === 0) return;

        const latest = data[data.length - 1];
        const previous = data.length > 1 ? data[data.length - 2] : latest;
        
        const priceEl = document.getElementById(`ticker-${symbol.toLowerCase()}`);
        const changeEl = document.getElementById(`ticker-${symbol.toLowerCase()}-change`);
        
        if (priceEl && changeEl) {
            const price = latest[priceField] || latest.close || latest.rate;
            const prevPrice = previous[priceField] || previous.close || previous.rate;
            const change = price - prevPrice;
            const changePercent = ((change / prevPrice) * 100).toFixed(2);
            
            priceEl.textContent = this.formatPrice(price);
            changeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
            changeEl.className = `ticker-change ${change >= 0 ? 'positive' : 'negative'}`;
        }
    }

    updateCandlestickChart() {
        let data = [];
        
        switch (this.currentAsset) {
            case 'DXY':
                data = this.formatOHLCV(this.data.dollarIndex, 'value');
                break;
            case 'GOLD':
            case 'OIL':
                data = this.formatOHLCV(this.data.commodityPrices[this.currentAsset], 'price');
                break;
            default:
                data = this.formatOHLCV(this.data.exchangeRates[this.currentAsset], 'rate');
        }

        if (data.length > 0) {
            // Save current time scale state to preserve zoom/position
            let visibleRange = null;
            try {
                visibleRange = this.chart.timeScale().getVisibleRange();
            } catch (e) {
                console.log('Could not get visible range:', e);
            }

            this.candlestickSeries.setData(data);

            // Restore time scale state to preserve zoom/position
            if (visibleRange) {
                try {
                    this.chart.timeScale().setVisibleRange(visibleRange);
                } catch (e) {
                    console.log('Could not restore visible range:', e);
                }
            }

            // Only fit content on initial load, not on auto-refresh
            if (!this.initialChartLoad) {
                this.chart.timeScale().fitContent();
                this.initialChartLoad = true;
            }
        }
    }

    updateDepthChart() {
        // Simulated depth data based on recent price action
        let data = [];
        let priceData = [];
        
        switch (this.currentAsset) {
            case 'DXY':
                priceData = this.data.dollarIndex;
                break;
            case 'GOLD':
            case 'OIL':
                priceData = this.data.commodityPrices[this.currentAsset];
                break;
            default:
                priceData = this.data.exchangeRates[this.currentAsset];
        }

        if (priceData && priceData.length > 0) {
            const latest = priceData[priceData.length - 1];
            const basePrice = latest.close || latest.rate || latest.price || latest.value;
            
            // Generate simulated depth data
            for (let i = 0; i < 20; i++) {
                const price = basePrice - (i * 0.001);
                const volume = Math.random() * 1000;
                data.push({
                    time: i,
                    value: volume,
                    color: '#238636',
                });
            }
            
            for (let i = 0; i < 20; i++) {
                const price = basePrice + (i * 0.001);
                const volume = Math.random() * 1000;
                data.push({
                    time: 20 + i,
                    value: volume,
                    color: '#da3633',
                });
            }

            this.depthSeries.setData(data);

            // Only fit content on initial load, not on auto-refresh
            if (!this.initialChartLoad) {
                this.depthChart.timeScale().fitContent();
            }
            
            // Update depth statistics
            const bidVolume = data.slice(0, 20).reduce((sum, d) => sum + d.value, 0);
            const askVolume = data.slice(20).reduce((sum, d) => sum + d.value, 0);
            const spread = ((askVolume - bidVolume) / ((bidVolume + askVolume) / 2) * 100).toFixed(2);
            
            document.getElementById('bid-volume').textContent = this.formatVolume(bidVolume);
            document.getElementById('ask-volume').textContent = this.formatVolume(askVolume);
            document.getElementById('spread-value').textContent = `${spread}%`;
        }
    }

    updateTradeFeed() {
        let tradeData = [];
        
        switch (this.currentAsset) {
            case 'DXY':
                tradeData = this.data.dollarIndex.slice(-10);
                break;
            case 'GOLD':
            case 'OIL':
                tradeData = this.data.commodityPrices[this.currentAsset]?.slice(-10) || [];
                break;
            default:
                tradeData = this.data.exchangeRates[this.currentAsset]?.slice(-10) || [];
        }

        const tradeList = document.getElementById('trade-list');
        tradeList.innerHTML = '';

        tradeData.reverse().forEach(trade => {
            const price = trade.close || trade.rate || trade.price || trade.value;
            const volume = trade.volume || Math.random() * 100;
            const time = new Date(trade.date).toLocaleTimeString();
            
            const prevPrice = tradeData.length > 1 ? 
                tradeData[tradeData.indexOf(trade) - 1]?.close || 
                tradeData[tradeData.indexOf(trade) - 1]?.rate || 
                tradeData[tradeData.indexOf(trade) - 1]?.price ||
                tradeData[tradeData.indexOf(trade) - 1]?.value : price;
            
            const priceClass = price >= prevPrice ? 'up' : 'down';
            
            const tradeEl = document.createElement('div');
            tradeEl.className = 'trade-item';
            tradeEl.innerHTML = `
                <span class="trade-price ${priceClass}">${this.formatPrice(price)}</span>
                <span>${this.formatVolume(volume)}</span>
                <span>${time}</span>
            `;
            tradeList.appendChild(tradeEl);
        });
    }

    updateStatistics() {
        let data = [];
        let priceField = 'rate';
        
        switch (this.currentAsset) {
            case 'DXY':
                data = this.data.dollarIndex;
                priceField = 'value';
                break;
            case 'GOLD':
            case 'OIL':
                data = this.data.commodityPrices[this.currentAsset];
                priceField = 'price';
                break;
            default:
                data = this.data.exchangeRates[this.currentAsset];
        }

        if (data && data.length > 0) {
            const latest = data[data.length - 1];
            const first = data[0];
            
            const open = first.open || first[priceField];
            const high = Math.max(...data.map(d => d.high || d[priceField]));
            const low = Math.min(...data.map(d => d.low || d[priceField]));
            const close = latest.close || latest[priceField];
            const volume = data.reduce((sum, d) => sum + (d.volume || 0), 0);
            const change = ((close - open) / open * 100).toFixed(2);
            
            document.getElementById('stat-open').textContent = this.formatPrice(open);
            document.getElementById('stat-high').textContent = this.formatPrice(high);
            document.getElementById('stat-low').textContent = this.formatPrice(low);
            document.getElementById('stat-close').textContent = this.formatPrice(close);
            document.getElementById('stat-volume').textContent = this.formatVolume(volume);
            
            const changeEl = document.getElementById('stat-change');
            changeEl.textContent = `${change >= 0 ? '+' : ''}${change}%`;
            changeEl.style.color = change >= 0 ? '#238636' : '#da3633';
        }
    }

    formatOHLCV(data, priceField) {
        if (!data) return [];

        return data.map(item => {
            const time = new Date(item.date).getTime() / 1000;
            const price = item[priceField] || item.close || item.rate || item.value || item.price;

            return {
                time: time,
                open: item.open || price,
                high: item.high || price,
                low: item.low || price,
                close: item.close || price,
            };
        }).sort((a, b) => a.time - b.time);
    }

    formatPrice(price) {
        if (price === undefined || price === null) return '--';
        if (price >= 1000) return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        if (price >= 100) return price.toFixed(2);
        if (price >= 1) return price.toFixed(4);
        return price.toFixed(6);
    }

    formatVolume(volume) {
        if (volume === undefined || volume === null) return '--';
        if (volume >= 1000000) return (volume / 1000000).toFixed(2) + 'M';
        if (volume >= 1000) return (volume / 1000).toFixed(2) + 'K';
        return volume.toFixed(2);
    }

    changeChartType(type) {
        // Save current time scale state to preserve zoom/position
        let visibleRange = null;
        try {
            visibleRange = this.chart.timeScale().getVisibleRange();
        } catch (e) {
            console.log('Could not get visible range:', e);
        }

        // Remove existing series
        this.chart.removeSeries(this.candlestickSeries);
        
        let data = [];
        switch (this.currentAsset) {
            case 'DXY':
                data = this.formatOHLCV(this.data.dollarIndex, 'value');
                break;
            case 'GOLD':
            case 'OIL':
                data = this.formatOHLCV(this.data.commodityPrices[this.currentAsset], 'price');
                break;
            default:
                data = this.formatOHLCV(this.data.exchangeRates[this.currentAsset], 'rate');
        }

        switch (type) {
            case 'line':
                this.candlestickSeries = this.chart.addLineSeries({
                    color: '#58a6ff',
                    lineWidth: 2,
                });
                this.candlestickSeries.setData(data.map(d => ({ time: d.time, value: d.close })));
                break;
            case 'area':
                this.candlestickSeries = this.chart.addAreaSeries({
                    lineColor: '#58a6ff',
                    topColor: 'rgba(88, 166, 255, 0.4)',
                    bottomColor: 'rgba(88, 166, 255, 0.0)',
                });
                this.candlestickSeries.setData(data.map(d => ({ time: d.time, value: d.close })));
                break;
            default:
                this.candlestickSeries = this.chart.addCandlestickSeries({
                    upColor: '#238636',
                    downColor: '#da3633',
                    borderDownColor: '#da3633',
                    borderUpColor: '#238636',
                    wickDownColor: '#da3633',
                    wickUpColor: '#238636',
                });
                this.candlestickSeries.setData(data);
        }

        // Restore time scale state to preserve zoom/position
        if (visibleRange) {
            try {
                this.chart.timeScale().setVisibleRange(visibleRange);
            } catch (e) {
                console.log('Could not restore visible range:', e);
            }
        }

        // Only fit content on initial load, not on chart type changes
        if (!this.initialChartLoad) {
            this.chart.timeScale().fitContent();
            this.initialChartLoad = true;
        }
    }

    updateLastUpdateTime() {
        const now = new Date();
        document.getElementById('last-update').textContent = 
            `Last update: ${now.toLocaleTimeString()}`;
    }

    showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = message;
        document.querySelector('.container').insertBefore(errorDiv, document.querySelector('.dashboard-grid'));
        
        setTimeout(() => errorDiv.remove(), 5000);
    }

    startAutoRefresh() {
        // Auto-refresh every 30 seconds
        setInterval(() => {
            this.loadAllData();
        }, 30000);
    }

    addMarker(markerData) {
        // Add marker to main chart
        const marker = {
            time: markerData.time,
            position: markerData.position || 'aboveBar',
            color: markerData.color || '#238636',
            shape: markerData.shape || 'arrowUp',
            text: markerData.text || '',
        };

        this.candlestickSeries.setMarkers([marker]);
        this.markers.push(marker);

        // Sync marker to depth chart if it exists
        if (this.depthSeries) {
            this.depthSeries.setMarkers([marker]);
        }
    }

    clearMarkers() {
        this.candlestickSeries.setMarkers([]);
        if (this.depthSeries) {
            this.depthSeries.setMarkers([]);
        }
        this.markers = [];
    }

    addBuySignal(time) {
        this.addMarker({
            time: time,
            position: 'belowBar',
            color: '#238636',
            shape: 'arrowUp',
            text: 'BUY'
        });
    }

    addSellSignal(time) {
        this.addMarker({
            time: time,
            position: 'aboveBar',
            color: '#da3633',
            shape: 'arrowDown',
            text: 'SELL'
        });
    }

    addEventMarker(time, text, color = '#58a6ff') {
        this.addMarker({
            time: time,
            position: 'inBar',
            color: color,
            shape: 'circle',
            text: text
        });
    }

    addRandomMarker() {
        // Add a random marker to demonstrate the feature
        let data = [];
        switch (this.currentAsset) {
            case 'DXY':
                data = this.data.dollarIndex;
                break;
            case 'GOLD':
            case 'OIL':
                data = this.data.commodityPrices[this.currentAsset];
                break;
            default:
                data = this.data.exchangeRates[this.currentAsset];
        }

        if (data && data.length > 0) {
            const randomIndex = Math.floor(Math.random() * data.length);
            const randomData = data[randomIndex];
            const time = new Date(randomData.date).getTime() / 1000;
            
            const markerTypes = ['buy', 'sell', 'event'];
            const randomType = markerTypes[Math.floor(Math.random() * markerTypes.length)];
            
            switch (randomType) {
                case 'buy':
                    this.addBuySignal(time);
                    break;
                case 'sell':
                    this.addSellSignal(time);
                    break;
                case 'event':
                    this.addEventMarker(time, 'Event');
                    break;
            }
        }
    }
}

// Initialize the dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new TradingDashboard();
});