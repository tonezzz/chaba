// TradeCanvas Enhanced UI Application
const API_BASE_URL = 'http://tony-omen.local:8080/apps/trade/api';
const WS_BASE_URL = 'ws://tony-omen.local:8080/apps/trade/api/ws';

class TradeCanvasApp {
    constructor() {
        this.currentSymbol = 'THB';
        this.currentTimeframe = '1Y';
        this.chartType = 'candlestick';
        this.chart = null;
        this.candlestickSeries = null;
        this.volumeSeries = null;
        this.indicatorSeries = null;
        this.data = [];
        this.websocket = null;
        this.autoRefreshInterval = null;
        this.activeIndicators = new Set();
        this.chartSettings = {
            upColor: '#238636',
            downColor: '#da3633',
            backgroundColor: '#21262d',
            gridColor: '#30363d',
            showVolume: true,
            showCrosshair: true,
            autoRefresh: 30
        };
        
        this.init();
    }

    async init() {
        this.setupEventListeners();
        this.initializeChart();
        await this.loadData();
        this.connectWebSocket();
        this.startAutoRefresh();
    }

    setupEventListeners() {
        // Symbol selector
        document.getElementById('symbol-selector').addEventListener('change', (e) => {
            this.currentSymbol = e.target.value;
            this.updateChartTitle();
            this.loadData();
            // Reconnect WebSocket with new symbol
            if (this.websocket) {
                this.websocket.close();
            }
            this.connectWebSocket();
        });

        // Timeframe selector
        document.getElementById('timeframe-selector').addEventListener('change', (e) => {
            this.currentTimeframe = e.target.value;
            this.updateChartTitle();
            this.loadData();
        });

        // Refresh button
        document.getElementById('refresh-btn').addEventListener('click', () => {
            this.loadData();
        });

        // Settings button
        document.getElementById('settings-btn').addEventListener('click', () => {
            this.openSettings();
        });

        // Chart type buttons
        document.querySelectorAll('.chart-type-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.chart-type-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.chartType = e.target.dataset.type;
                this.updateChartType();
            });
        });

        // Indicator buttons
        document.querySelectorAll('.indicator-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const indicator = e.target.dataset.indicator;
                e.target.classList.toggle('active');
                
                if (this.activeIndicators.has(indicator)) {
                    this.activeIndicators.delete(indicator);
                    this.removeIndicator(indicator);
                } else {
                    this.activeIndicators.add(indicator);
                    this.addIndicator(indicator);
                }
            });
        });

        // Zoom controls
        document.getElementById('zoom-in-btn').addEventListener('click', () => {
            this.chart.timeScale().zoomIn();
        });

        document.getElementById('zoom-out-btn').addEventListener('click', () => {
            this.chart.timeScale().zoomOut();
        });

        document.getElementById('reset-zoom-btn').addEventListener('click', () => {
            this.chart.timeScale().fitContent();
        });

        // Settings modal
        document.getElementById('close-settings').addEventListener('click', () => {
            this.closeSettings();
        });

        document.getElementById('cancel-settings').addEventListener('click', () => {
            this.closeSettings();
        });

        document.getElementById('apply-settings').addEventListener('click', () => {
            this.applySettings();
        });

        // Close modal on outside click
        document.getElementById('settings-modal').addEventListener('click', (e) => {
            if (e.target.id === 'settings-modal') {
                this.closeSettings();
            }
        });
    }

    initializeChart() {
        const chartContainer = document.getElementById('main-chart');
        const volumeContainer = document.getElementById('volume-chart');
        const indicatorContainer = document.getElementById('indicator-chart');

        // Ensure container has dimensions
        if (chartContainer.clientWidth === 0 || chartContainer.clientHeight === 0) {
            setTimeout(() => this.initializeChart(), 100);
            return;
        }

        // Main chart
        this.chart = LightweightCharts.createChart(chartContainer, {
            width: chartContainer.clientWidth,
            height: chartContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: this.chartSettings.backgroundColor },
                textColor: '#e6edf3',
            },
            grid: {
                vertLines: { color: this.chartSettings.gridColor },
                horzLines: { color: this.chartSettings.gridColor },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    width: 1,
                    color: '#58a6ff',
                    style: LightweightCharts.LineStyle.Dashed,
                },
                horzLine: {
                    width: 1,
                    color: '#58a6ff',
                    style: LightweightCharts.LineStyle.Dashed,
                },
            },
            rightPriceScale: {
                borderColor: this.chartSettings.gridColor,
            },
            timeScale: {
                borderColor: this.chartSettings.gridColor,
                timeVisible: true,
                secondsVisible: false,
            },
        });

        // Candlestick series
        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: this.chartSettings.upColor,
            downColor: this.chartSettings.downColor,
            borderDownColor: this.chartSettings.downColor,
            borderUpColor: this.chartSettings.upColor,
            wickDownColor: this.chartSettings.downColor,
            wickUpColor: this.chartSettings.upColor,
        });

        // Volume chart
        if (this.chartSettings.showVolume) {
            this.volumeChart = LightweightCharts.createChart(volumeContainer, {
                width: volumeContainer.clientWidth,
                height: volumeContainer.clientHeight,
                layout: {
                    background: { type: 'solid', color: this.chartSettings.backgroundColor },
                    textColor: '#e6edf3',
                },
                grid: {
                    vertLines: { color: this.chartSettings.gridColor },
                    horzLines: { color: this.chartSettings.gridColor },
                },
                rightPriceScale: {
                    borderColor: this.chartSettings.gridColor,
                },
                timeScale: {
                    visible: false,
                },
            });

            this.volumeSeries = this.volumeChart.addHistogramSeries({
                color: '#58a6ff',
                priceFormat: {
                    type: 'volume',
                },
                priceScaleId: '',
            });
        }

        // Indicator chart
        this.indicatorChart = LightweightCharts.createChart(indicatorContainer, {
            width: indicatorContainer.clientWidth,
            height: indicatorContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: this.chartSettings.backgroundColor },
                textColor: '#e6edf3',
            },
            grid: {
                vertLines: { color: this.chartSettings.gridColor },
                horzLines: { color: this.chartSettings.gridColor },
            },
            rightPriceScale: {
                borderColor: this.chartSettings.gridColor,
            },
            timeScale: {
                visible: false,
            },
        });

        // Handle resize
        window.addEventListener('resize', () => {
            this.chart.applyOptions({ width: chartContainer.clientWidth });
            if (this.volumeChart) {
                this.volumeChart.applyOptions({ width: volumeContainer.clientWidth });
            }
            this.indicatorChart.applyOptions({ width: indicatorContainer.clientWidth });
        });

        // Crosshair move handler
        this.chart.subscribeCrosshairMove(param => {
            if (!param.time || !param.point) {
                return;
            }
            
            const data = param.seriesData.get(this.candlestickSeries);
            if (data) {
                this.updateCrosshairInfo(data, param.time);
            }
        });
    }

    async loadData() {
        try {
            this.updateConnectionStatus('connecting');
            
            let endpoint;
            if (this.currentSymbol === 'DXY') {
                endpoint = `${API_BASE_URL}/dollar_index?period=${this.currentTimeframe.toLowerCase()}&limit=1000`;
            } else if (this.currentSymbol === 'OIL') {
                endpoint = `${API_BASE_URL}/commodity_prices/OIL?period=${this.currentTimeframe.toLowerCase()}&limit=1000`;
            } else {
                endpoint = `${API_BASE_URL}/exchange_rates/${this.currentSymbol}?period=${this.currentTimeframe.toLowerCase()}&limit=1000`;
            }

            const response = await fetch(endpoint);
            const result = await response.json();
            this.data = result.data || result;
            
            this.updateChart();
            this.updateStatistics();
            this.updateConnectionStatus('connected');
            this.updateLastUpdateTime();
            
        } catch (error) {
            console.error('Error loading data:', error);
            this.updateConnectionStatus('disconnected');
        }
    }

    updateChart() {
        if (!this.data || this.data.length === 0) return;

        const candlestickData = this.data.map(item => {
            const priceField = this.currentSymbol === 'DXY' ? 'value' :
                              this.currentSymbol === 'OIL' ? 'price' : 'rate';
            const price = item[priceField] || item.close || item.rate || item.value || item.price;

            return {
                time: new Date(item.date).getTime() / 1000,
                open: item.open || price,
                high: item.high || price,
                low: item.low || price,
                close: item.close || price,
            };
        });

        this.candlestickSeries.setData(candlestickData);

        // Update volume chart
        if (this.volumeSeries && this.chartSettings.showVolume) {
            const volumeData = this.data.map(item => {
                const open = item.open || item.close || item.rate || item.value || item.price;
                const close = item.close || item.rate || item.value || item.price;
                return {
                    time: new Date(item.date).getTime() / 1000,
                    value: item.volume || 1000000,
                    color: close >= open ? this.chartSettings.upColor : this.chartSettings.downColor,
                };
            });
            this.volumeSeries.setData(volumeData);
        }

        // Update active indicators
        this.activeIndicators.forEach(indicator => {
            this.addIndicator(indicator);
        });

        // Fit content
        this.chart.timeScale().fitContent();
    }

    updateChartType() {
        // Remove existing series
        this.chart.removeSeries(this.candlestickSeries);

        // Add new series based on type
        if (this.chartType === 'candlestick') {
            this.candlestickSeries = this.chart.addCandlestickSeries({
                upColor: this.chartSettings.upColor,
                downColor: this.chartSettings.downColor,
                borderDownColor: this.chartSettings.downColor,
                borderUpColor: this.chartSettings.upColor,
                wickDownColor: this.chartSettings.downColor,
                wickUpColor: this.chartSettings.upColor,
            });
        } else if (this.chartType === 'line') {
            this.candlestickSeries = this.chart.addLineSeries({
                color: '#58a6ff',
                lineWidth: 2,
            });
        } else if (this.chartType === 'area') {
            this.candlestickSeries = this.chart.addAreaSeries({
                topColor: 'rgba(88, 166, 255, 0.4)',
                bottomColor: 'rgba(88, 166, 255, 0.0)',
                lineColor: '#58a6ff',
                lineWidth: 2,
            });
        }

        this.updateChart();
    }

    addIndicator(indicator) {
        if (!this.data || this.data.length === 0) return;

        const closePrices = this.data.map(item => 
            item.close || item.rate || item.value || item.price
        );

        let indicatorData;

        switch (indicator) {
            case 'sma':
                indicatorData = this.calculateSMA(closePrices, 20);
                this.updateIndicatorChart(indicatorData, 'SMA (20)', '#f0883e');
                break;
            case 'ema':
                indicatorData = this.calculateEMA(closePrices, 12);
                this.updateIndicatorChart(indicatorData, 'EMA (12)', '#a371f7');
                break;
            case 'rsi':
                indicatorData = this.calculateRSI(closePrices, 14);
                this.updateIndicatorChart(indicatorData, 'RSI (14)', '#58a6ff', true);
                break;
            case 'macd':
                const macdData = this.calculateMACD(closePrices);
                this.updateIndicatorChart(macdData.macd, 'MACD', '#238636');
                this.updateIndicatorChart(macdData.signal, 'Signal', '#da3633');
                break;
            case 'bb':
                const bbData = this.calculateBollingerBands(closePrices, 20, 2);
                this.updateBollingerBands(bbData);
                break;
        }
    }

    removeIndicator(indicator) {
        // Remove indicator series from chart
        if (this.indicatorSeries) {
            this.indicatorChart.removeSeries(this.indicatorSeries);
            this.indicatorSeries = null;
        }
    }

    calculateSMA(data, period) {
        const sma = [];
        for (let i = 0; i < data.length; i++) {
            if (i < period - 1) {
                continue;
            }
            const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
            sma.push(sum / period);
        }
        return sma;
    }

    calculateEMA(data, period) {
        const ema = [];
        const multiplier = 2 / (period + 1);
        
        ema[0] = data[0];
        for (let i = 1; i < data.length; i++) {
            ema[i] = (data[i] - ema[i - 1]) * multiplier + ema[i - 1];
        }
        
        return ema;
    }

    calculateRSI(data, period) {
        const rsi = [];
        let gains = 0;
        let losses = 0;

        for (let i = 1; i <= period; i++) {
            const change = data[i] - data[i - 1];
            if (change > 0) {
                gains += change;
            } else {
                losses += Math.abs(change);
            }
        }

        let avgGain = gains / period;
        let avgLoss = losses / period;

        for (let i = period; i < data.length; i++) {
            const change = data[i] - data[i - 1];
            const gain = change > 0 ? change : 0;
            const loss = change < 0 ? Math.abs(change) : 0;

            avgGain = (avgGain * (period - 1) + gain) / period;
            avgLoss = (avgLoss * (period - 1) + loss) / period;

            const rs = avgGain / avgLoss;
            rsi.push(100 - (100 / (1 + rs)));
        }

        return rsi;
    }

    calculateMACD(data) {
        const ema12 = this.calculateEMA(data, 12);
        const ema26 = this.calculateEMA(data, 26);
        
        const macd = [];
        for (let i = 0; i < ema12.length; i++) {
            macd.push(ema12[i] - ema26[i]);
        }

        const signal = this.calculateEMA(macd, 9);

        return { macd, signal };
    }

    calculateBollingerBands(data, period, stdDev) {
        const sma = this.calculateSMA(data, period);
        const upper = [];
        const lower = [];

        for (let i = period - 1; i < data.length; i++) {
            const slice = data.slice(i - period + 1, i + 1);
            const mean = sma[i - period + 1];
            const variance = slice.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / period;
            const std = Math.sqrt(variance);

            upper.push(mean + stdDev * std);
            lower.push(mean - stdDev * std);
        }

        return { upper, lower, middle: sma };
    }

    updateIndicatorChart(data, name, color, isOscillator = false) {
        if (this.indicatorSeries) {
            this.indicatorChart.removeSeries(this.indicatorSeries);
        }

        const chartData = data.map((value, index) => ({
            time: this.data[index + (isOscillator ? 14 : 19)]?.date ? 
                  new Date(this.data[index + (isOscillator ? 14 : 19)].date).getTime() / 1000 : 
                  new Date(this.data[index].date).getTime() / 1000,
            value: value,
        }));

        this.indicatorSeries = this.indicatorChart.addLineSeries({
            color: color,
            lineWidth: 2,
            title: name,
        });

        this.indicatorSeries.setData(chartData);
    }

    updateBollingerBands(bbData) {
        // Remove existing series
        this.chart.removeSeries(this.candlestickSeries);

        // Add candlestick series back
        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: this.chartSettings.upColor,
            downColor: this.chartSettings.downColor,
            borderDownColor: this.chartSettings.downColor,
            borderUpColor: this.chartSettings.upColor,
            wickDownColor: this.chartSettings.downColor,
            wickUpColor: this.chartSettings.upColor,
        });

        // Add Bollinger Bands
        const upperBand = this.chart.addLineSeries({
            color: '#f0883e',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
        });

        const lowerBand = this.chart.addLineSeries({
            color: '#f0883e',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
        });

        const middleBand = this.chart.addLineSeries({
            color: '#a371f7',
            lineWidth: 1,
        });

        const upperData = bbData.upper.map((value, index) => ({
            time: new Date(this.data[index + 19].date).getTime() / 1000,
            value: value,
        }));

        const lowerData = bbData.lower.map((value, index) => ({
            time: new Date(this.data[index + 19].date).getTime() / 1000,
            value: value,
        }));

        const middleData = bbData.middle.map((value, index) => ({
            time: new Date(this.data[index + 19].date).getTime() / 1000,
            value: value,
        }));

        upperBand.setData(upperData);
        lowerBand.setData(lowerData);
        middleBand.setData(middleData);

        this.updateChart();
    }

    updateStatistics() {
        if (!this.data || this.data.length === 0) return;

        const latest = this.data[this.data.length - 1];
        const previous = this.data[this.data.length - 2] || latest;

        const priceField = this.currentSymbol === 'DXY' ? 'value' : 
                          this.currentSymbol === 'OIL' ? 'price' : 'rate';

        const open = latest.open || latest[priceField];
        const high = latest.high || latest[priceField];
        const low = latest.low || latest[priceField];
        const close = latest.close || latest[priceField];
        const volume = latest.volume || 0;

        const change = close - (previous.close || previous[priceField]);
        const changePercent = ((change / (previous.close || previous[priceField])) * 100).toFixed(2);

        document.getElementById('stat-open').textContent = this.formatPrice(open);
        document.getElementById('stat-high').textContent = this.formatPrice(high);
        document.getElementById('stat-low').textContent = this.formatPrice(low);
        document.getElementById('stat-close').textContent = this.formatPrice(close);
        document.getElementById('stat-volume').textContent = this.formatVolume(volume);
        document.getElementById('stat-change').textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
        document.getElementById('stat-change').className = `stat-value ${change >= 0 ? 'positive' : 'negative'}`;

        document.getElementById('current-price').textContent = this.formatPrice(close);
        document.getElementById('price-change').textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
        document.getElementById('price-change').className = change >= 0 ? 'positive' : 'negative';

        // Update indicator values
        if (this.activeIndicators.has('sma')) {
            const sma = this.calculateSMA(this.data.map(d => d.close || d.rate || d.value || d.price), 20);
            document.getElementById('sma-value').textContent = this.formatPrice(sma[sma.length - 1]);
        }
        if (this.activeIndicators.has('ema')) {
            const ema = this.calculateEMA(this.data.map(d => d.close || d.rate || d.value || d.price), 12);
            document.getElementById('ema-value').textContent = this.formatPrice(ema[ema.length - 1]);
        }
        if (this.activeIndicators.has('rsi')) {
            const rsi = this.calculateRSI(this.data.map(d => d.close || d.rate || d.value || d.price), 14);
            document.getElementById('rsi-value').textContent = rsi[rsi.length - 1].toFixed(2);
        }
    }

    updateCrosshairInfo(data, time) {
        // Update crosshair info display if needed
        const date = new Date(time * 1000).toLocaleString();
        console.log(`Crosshair: ${date} - Open: ${data.open}, High: ${data.high}, Low: ${data.low}, Close: ${data.close}`);
    }

    updateChartTitle() {
        const symbolDisplay = this.currentSymbol === 'DXY' ? 'DXY' : 
                             this.currentSymbol === 'OIL' ? 'OIL' : 
                             `USD/${this.currentSymbol}`;
        document.getElementById('chart-title').textContent = `${symbolDisplay} - ${this.currentTimeframe}`;
    }

    updateConnectionStatus(status) {
        const statusEl = document.getElementById('connection-status');
        statusEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        statusEl.className = `status ${status}`;
    }

    updateLastUpdateTime() {
        const now = new Date().toLocaleString();
        document.getElementById('last-update').textContent = `Last update: ${now}`;
    }

    formatPrice(price) {
        if (this.currentSymbol === 'JPY' || this.currentSymbol === 'THB') {
            return price.toFixed(2);
        }
        return price.toFixed(4);
    }

    formatVolume(volume) {
        if (volume >= 1000000) {
            return (volume / 1000000).toFixed(2) + 'M';
        } else if (volume >= 1000) {
            return (volume / 1000).toFixed(2) + 'K';
        }
        return volume.toFixed(0);
    }

    connectWebSocket() {
        try {
            // WebSocket connection is optional - the system works fine without it
            // Since we have historical data but no live data feed, we'll skip WebSocket
            console.log('WebSocket connection skipped - using historical data mode');
            this.updateConnectionStatus('connected');
            return;

            // Determine the correct WebSocket endpoint based on current symbol
            let wsEndpoint;
            if (this.currentSymbol === 'DXY') {
                wsEndpoint = `${WS_BASE_URL}/dollar_index`;
            } else if (this.currentSymbol === 'OIL') {
                wsEndpoint = `${WS_BASE_URL}/commodity_prices/OIL`;
            } else {
                wsEndpoint = `${WS_BASE_URL}/exchange_rates/${this.currentSymbol}`;
            }

            console.log('Connecting to WebSocket:', wsEndpoint);
            this.websocket = new WebSocket(wsEndpoint);

            this.websocket.onopen = () => {
                console.log('WebSocket connected');
                this.updateConnectionStatus('connected');
            };

            this.websocket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.handleWebSocketMessage(data);
            };

            this.websocket.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus('disconnected');
            };

            this.websocket.onclose = () => {
                console.log('WebSocket closed');
                this.updateConnectionStatus('disconnected');
                // Attempt to reconnect after 5 seconds
                setTimeout(() => this.connectWebSocket(), 5000);
            };
        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
        }
    }

    handleWebSocketMessage(data) {
        // Handle real-time updates
        if (data.type === 'price_update' && data.symbol === this.currentSymbol) {
            this.updateRealtimePrice(data);
        } else if (data.type === 'trade') {
            this.addTradeToFeed(data);
        }
    }

    updateRealtimePrice(data) {
        // Update chart with new data point
        const newCandle = {
            time: new Date(data.date).getTime() / 1000,
            open: data.open,
            high: data.high,
            low: data.low,
            close: data.close,
        };

        this.candlestickSeries.update(newCandle);
        this.updateStatistics();
    }

    addTradeToFeed(trade) {
        const feed = document.getElementById('trade-feed');
        const tradeItem = document.createElement('div');
        tradeItem.className = `trade-item ${trade.side}`;
        tradeItem.innerHTML = `
            <span>${this.formatPrice(trade.price)}</span>
            <span>${this.formatVolume(trade.size)}</span>
            <span>${new Date(trade.time).toLocaleTimeString()}</span>
        `;
        feed.insertBefore(tradeItem, feed.firstChild);

        // Keep only last 20 trades
        while (feed.children.length > 20) {
            feed.removeChild(feed.lastChild);
        }
    }

    startAutoRefresh() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }

        this.autoRefreshInterval = setInterval(() => {
            this.loadData();
        }, this.chartSettings.autoRefresh * 1000);
    }

    openSettings() {
        document.getElementById('settings-modal').classList.add('show');
        
        // Load current settings
        document.getElementById('up-color').value = this.chartSettings.upColor;
        document.getElementById('down-color').value = this.chartSettings.downColor;
        document.getElementById('bg-color').value = this.chartSettings.backgroundColor;
        document.getElementById('grid-color').value = this.chartSettings.gridColor;
        document.getElementById('show-volume').checked = this.chartSettings.showVolume;
        document.getElementById('show-crosshair').checked = this.chartSettings.showCrosshair;
        document.getElementById('auto-refresh').value = this.chartSettings.autoRefresh;
    }

    closeSettings() {
        document.getElementById('settings-modal').classList.remove('show');
    }

    applySettings() {
        this.chartSettings.upColor = document.getElementById('up-color').value;
        this.chartSettings.downColor = document.getElementById('down-color').value;
        this.chartSettings.backgroundColor = document.getElementById('bg-color').value;
        this.chartSettings.gridColor = document.getElementById('grid-color').value;
        this.chartSettings.showVolume = document.getElementById('show-volume').checked;
        this.chartSettings.showCrosshair = document.getElementById('show-crosshair').checked;
        this.chartSettings.autoRefresh = parseInt(document.getElementById('auto-refresh').value);

        // Apply settings to chart
        this.chart.applyOptions({
            layout: {
                background: { type: 'solid', color: this.chartSettings.backgroundColor },
            },
            grid: {
                vertLines: { color: this.chartSettings.gridColor },
                horzLines: { color: this.chartSettings.gridColor },
            },
        });

        this.candlestickSeries.applyOptions({
            upColor: this.chartSettings.upColor,
            downColor: this.chartSettings.downColor,
            borderDownColor: this.chartSettings.downColor,
            borderUpColor: this.chartSettings.upColor,
            wickDownColor: this.chartSettings.downColor,
            wickUpColor: this.chartSettings.upColor,
        });

        // Restart auto refresh with new interval
        this.startAutoRefresh();

        this.closeSettings();
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    new TradeCanvasApp();
});
