// Compare Page - Candlestick Chart (USD/THB only)
class ComparePage {
    constructor() {
        this.chart = null;
        this.candlestickSeries = null;
        this.indicatorSeries = null;
        this.data = [];
        this.activeIndicators = new Set();
        this.chartSettings = {
            upColor: '#238636',
            downColor: '#da3633',
            backgroundColor: '#21262d',
            gridColor: '#30363d'
        };
        
        // Initialize immediately
        this.init();
    }

    init() {
        console.log('Initializing ComparePage...');
        // Small delay to ensure DOM is ready
        setTimeout(() => {
            this.setupEventListeners();
            this.initializeChart();
            this.loadData();
        }, 100);
    }

    setupEventListeners() {
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
    }

    initializeChart() {
        console.log('Initializing chart...');
        const chartContainer = document.getElementById('main-chart');
        
        if (!chartContainer) {
            console.error('Chart container not found');
            return;
        }

        console.log('Chart container:', chartContainer);
        console.log('Container dimensions:', chartContainer.clientWidth, chartContainer.clientHeight);

        if (typeof LightweightCharts === 'undefined') {
            console.error('LightweightCharts library not loaded');
            return;
        }

        // Force dimensions if needed
        if (chartContainer.clientWidth === 0 || chartContainer.clientHeight === 0) {
            chartContainer.style.width = '100%';
            chartContainer.style.height = '500px';
        }

        console.log('Creating chart...');
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

        console.log('Adding candlestick series...');
        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: this.chartSettings.upColor,
            downColor: this.chartSettings.downColor,
            borderDownColor: this.chartSettings.downColor,
            borderUpColor: this.chartSettings.upColor,
            wickDownColor: this.chartSettings.downColor,
            wickUpColor: this.chartSettings.upColor,
        });

        console.log('Chart initialized successfully');

        // Handle window resize
        window.addEventListener('resize', () => {
            if (this.chart) {
                this.chart.applyOptions({
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight,
                });
            }
        });
    }

    async loadData() {
        try {
            console.log('Loading USD/THB data...');
            // Update connection status
            const statusElement = document.getElementById('connection-status');
            statusElement.textContent = 'Loading...';
            statusElement.className = 'status disconnected';

            // Generate 1 year of sample data for USD/THB
            const endDate = new Date();
            const startDate = new Date();
            startDate.setFullYear(startDate.getFullYear() - 1);

            const sampleData = this.generateSampleData(startDate, endDate);
            this.updateChart(sampleData);
            
            statusElement.textContent = 'Sample Data';
            statusElement.className = 'status connected';
            console.log('Data loaded successfully');
        } catch (error) {
            console.error('Error loading data:', error);
        }
    }

    generateSampleData(startDate, endDate) {
        const data = [];
        const basePrice = 35.5; // USD/THB base price
        let price = basePrice;
        let currentTime = Math.floor(startDate.getTime() / 1000);

        const endTime = Math.floor(endDate.getTime() / 1000);
        const dayInSeconds = 86400;

        while (currentTime <= endTime) {
            const date = new Date(currentTime * 1000);
            
            // Skip weekends
            if (date.getDay() !== 0 && date.getDay() !== 6) {
                const volatility = basePrice * 0.02; // 2% volatility
                const open = price;
                const change = (Math.random() - 0.5) * volatility;
                const close = price + change;
                const high = Math.max(open, close) + Math.random() * volatility * 0.5;
                const low = Math.min(open, close) - Math.random() * volatility * 0.5;

                data.push({
                    time: currentTime,
                    open: open,
                    high: high,
                    low: low,
                    close: close
                });

                price = close;
            }

            currentTime += dayInSeconds;
        }

        console.log(`Generated ${data.length} data points`);
        return data;
    }

    updateChart(data) {
        console.log('Updating chart with', data.length, 'data points');
        if (this.candlestickSeries && data.length > 0) {
            console.log('Setting data to candlestick series...');
            this.candlestickSeries.setData(data);
            console.log('Fitting content...');
            this.chart.timeScale().fitContent();
            console.log('Chart updated successfully');

            // Update current price and stats
            const latestData = data[data.length - 1];
            const previousData = data[data.length - 2] || data[0];

            document.getElementById('current-price').textContent = latestData.close.toFixed(2);
            
            const change = latestData.close - previousData.close;
            const changePercent = ((change / previousData.close) * 100).toFixed(2);
            const changeElement = document.getElementById('price-change');
            changeElement.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
            changeElement.className = change >= 0 ? 'positive' : 'negative';

            // Update stats
            document.getElementById('stat-open').textContent = latestData.open.toFixed(2);
            document.getElementById('stat-high').textContent = latestData.high.toFixed(2);
            document.getElementById('stat-low').textContent = latestData.low.toFixed(2);
            document.getElementById('stat-close').textContent = latestData.close.toFixed(2);
            document.getElementById('stat-change').textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;

            // Update active indicators
            this.activeIndicators.forEach(indicator => {
                this.addIndicator(indicator);
            });
        } else {
            console.error('Cannot update chart: candlestickSeries is null or data is empty');
        }
    }

    addIndicator(indicator) {
        if (!this.data || this.data.length === 0) return;

        const closePrices = this.data.map(d => d.close);
        let indicatorData;

        switch (indicator) {
            case 'sma':
                indicatorData = this.calculateSMA(closePrices, 20);
                this.addIndicatorSeries(indicatorData, 'SMA (20)', '#a371f7');
                break;
            case 'ema':
                indicatorData = this.calculateEMA(closePrices, 12);
                this.addIndicatorSeries(indicatorData, 'EMA (12)', '#58a6ff');
                break;
            case 'rsi':
                indicatorData = this.calculateRSI(closePrices, 14);
                this.addIndicatorSeries(indicatorData, 'RSI (14)', '#f0883e', true);
                break;
            case 'macd':
                const macdData = this.calculateMACD(closePrices);
                this.addIndicatorSeries(macdData.macd, 'MACD', '#238636');
                this.addIndicatorSeries(macdData.signal, 'Signal', '#da3633');
                break;
            case 'bb':
                const bbData = this.calculateBollingerBands(closePrices, 20, 2);
                this.addBollingerBands(bbData);
                break;
        }

        this.updateIndicatorValues();
    }

    removeIndicator(indicator) {
        // Remove all indicator series from chart
        const series = this.chart.getSeries();
        series.forEach(series => {
            if (series !== this.candlestickSeries) {
                this.chart.removeSeries(series);
            }
        });
        this.indicatorSeries = null;
    }

    addIndicatorSeries(data, name, color, isOscillator = false) {
        const series = this.chart.addLineSeries({
            color: color,
            lineWidth: 2,
            title: name,
        });

        const chartData = data.map((value, index) => ({
            time: this.data[index + (isOscillator ? 14 : 19)]?.time || this.data[index]?.time,
            value: value,
        }));

        series.setData(chartData);
        this.indicatorSeries = series;
    }

    addBollingerBands(bbData) {
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
            time: this.data[index + 19].time,
            value: value,
        }));

        const lowerData = bbData.lower.map((value, index) => ({
            time: this.data[index + 19].time,
            value: value,
        }));

        const middleData = bbData.middle.map((value, index) => ({
            time: this.data[index + 19].time,
            value: value,
        }));

        upperBand.setData(upperData);
        lowerBand.setData(lowerData);
        middleBand.setData(middleData);
    }

    updateIndicatorValues() {
        if (!this.data || this.data.length === 0) return;

        const closePrices = this.data.map(d => d.close);

        if (this.activeIndicators.has('sma')) {
            const sma = this.calculateSMA(closePrices, 20);
            if (sma.length > 0) {
                document.getElementById('sma-value').textContent = sma[sma.length - 1].toFixed(2);
            }
        }
        if (this.activeIndicators.has('ema')) {
            const ema = this.calculateEMA(closePrices, 12);
            if (ema.length > 0) {
                document.getElementById('ema-value').textContent = ema[ema.length - 1].toFixed(2);
            }
        }
        if (this.activeIndicators.has('rsi')) {
            const rsi = this.calculateRSI(closePrices, 14);
            if (rsi.length > 0) {
                document.getElementById('rsi-value').textContent = rsi[rsi.length - 1].toFixed(2);
            }
        }
        if (this.activeIndicators.has('macd')) {
            const macdData = this.calculateMACD(closePrices);
            if (macdData.macd.length > 0) {
                document.getElementById('macd-value').textContent = macdData.macd[macdData.macd.length - 1].toFixed(4);
            }
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
}

// Initialize when Lightweight Charts is loaded
function waitForLightweightCharts(callback) {
    if (typeof LightweightCharts !== 'undefined') {
        callback();
    } else {
        setTimeout(() => waitForLightweightCharts(callback), 100);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    waitForLightweightCharts(function() {
        new ComparePage();
    });
});
