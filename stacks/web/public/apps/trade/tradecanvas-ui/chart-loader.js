// Shared Chart Loading Module for TradeCanvas
// This module provides common chart initialization and data loading functionality
// that can be shared between index.html and compare.html

class ChartLoader {
    constructor(options = {}) {
        this.chart = null;
        this.candlestickSeries = null;
        this.volumeSeries = null;
        this.indicatorSeries = null;
        
        // Configuration with defaults
        this.config = {
            containerId: options.containerId || 'main-chart',
            symbol: options.symbol || 'THB',
            timeframe: options.timeframe || '1Y',
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
        this.basePrices = {
            'THB': 35.5,
            'EUR': 1.08,
            'GBP': 1.27,
            'JPY': 155.0,
            'DXY': 105.0,
            'OIL': 75.0
        };
    }

    async init() {
        console.log('ChartLoader initializing for', this.config.symbol);
        
        try {
            this.initializeChart();
            await this.loadData();
            
            if (this.config.enableControls) {
                this.setupControls();
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
            // Fall back to sample data
            this.data = this.generateSampleData();
            this.updateChart();
            this.updateUI();
        }
    }

    initializeChart() {
        const chartContainer = document.getElementById(this.config.containerId);
        if (!chartContainer) {
            console.error('Chart container not found:', this.config.containerId);
            return;
        }

        // Force dimensions
        chartContainer.style.width = '100%';
        if (!chartContainer.style.height || chartContainer.style.height === '0px') {
            chartContainer.style.height = '400px';
        }

        if (typeof LightweightCharts === 'undefined') {
            console.error('LightweightCharts library not loaded');
            return;
        }

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

        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: this.chartSettings.upColor,
            downColor: this.chartSettings.downColor,
            borderDownColor: this.chartSettings.downColor,
            borderUpColor: this.chartSettings.upColor,
            wickDownColor: this.chartSettings.downColor,
            wickUpColor: this.chartSettings.upColor,
        });

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
        console.log('Loading data for', this.config.symbol);
        
        try {
            // Try to fetch from CSV files directly
            const symbolFiles = {
                'THB': 'thb_formatted.csv',
                'EUR': 'eur_formatted.csv',
                'GBP': 'gbp_formatted.csv',
                'JPY': 'jpy_formatted.csv',
                'DXY': 'dxy_formatted.csv',
                'OIL': 'wti_formatted.csv'
            };
            
            const csvFile = symbolFiles[this.config.symbol];
            if (csvFile) {
                const csvUrl = `../data/imported/${csvFile}`;
                console.log('Fetching CSV from:', csvUrl);
                
                const response = await fetch(csvUrl);
                if (response.ok) {
                    const csvText = await response.text();
                    this.data = this.parseCSV(csvText);
                    this.isSampleData = false;
                    console.log('Loaded data from CSV:', this.data.length, 'points');
                } else {
                    console.log('CSV not available, using sample data');
                    this.data = this.generateSampleData();
                }
            } else {
                console.log('No CSV file for symbol, using sample data');
                this.data = this.generateSampleData();
            }
        } catch (error) {
            console.log('CSV loading error, using sample data:', error.message);
            this.data = this.generateSampleData();
        }

        this.updateChart();
        this.updateUI();
    }

    parseCSV(csvText) {
        const lines = csvText.trim().split('\n');
        const headers = lines[0].split(',');
        const data = [];
        
        // Find column indices
        const dateIndex = headers.indexOf('date');
        const openIndex = headers.indexOf('open_price');
        const highIndex = headers.indexOf('high_price');
        const lowIndex = headers.indexOf('low_price');
        const closeIndex = headers.indexOf('close_price');
        
        for (let i = 1; i < lines.length; i++) {
            const values = lines[i].split(',');
            if (values.length >= 5) {
                const dateStr = values[dateIndex];
                const timestamp = Math.floor(new Date(dateStr).getTime() / 1000);
                
                data.push({
                    time: timestamp,
                    open: parseFloat(values[openIndex]),
                    high: parseFloat(values[highIndex]),
                    low: parseFloat(values[lowIndex]),
                    close: parseFloat(values[closeIndex])
                });
            }
        }
        
        // Filter by timeframe if needed
        if (this.config.timeframe !== 'all') {
            const endTime = Math.floor(Date.now() / 1000);
            const startTime = this.calculateStartDate(new Date(endTime * 1000), this.config.timeframe);
            const startTimestamp = Math.floor(startTime.getTime() / 1000);
            
            return data.filter(point => point.time >= startTimestamp && point.time <= endTime);
        }
        
        return data;
    }

    calculateStartDate(endDate, timeframe) {
        const startDate = new Date(endDate);
        switch (timeframe) {
            case '1D':
                startDate.setDate(startDate.getDate() - 1);
                break;
            case '1W':
                startDate.setDate(startDate.getDate() - 7);
                break;
            case '1M':
                startDate.setMonth(startDate.getMonth() - 1);
                break;
            case '3M':
                startDate.setMonth(startDate.getMonth() - 3);
                break;
            case '6M':
                startDate.setMonth(startDate.getMonth() - 6);
                break;
            case '1Y':
                startDate.setFullYear(startDate.getFullYear() - 1);
                break;
            case '2Y':
                startDate.setFullYear(startDate.getFullYear() - 2);
                break;
            case 'all':
                // Return earliest date (no filtering)
                startDate.setFullYear(1980);
                break;
            default:
                startDate.setFullYear(startDate.getFullYear() - 1);
        }
        return startDate;
    }

    generateSampleData() {
        this.isSampleData = true;
        const basePrice = this.basePrices[this.config.symbol] || 100.0;
        const data = [];
        let price = basePrice;
        const endTime = Math.floor(Date.now() / 1000);
        const startTime = endTime - (365 * 86400); // 1 year
        let currentTime = startTime;
        
        while (currentTime <= endTime) {
            const date = new Date(currentTime * 1000);
            if (date.getDay() !== 0 && date.getDay() !== 6) {
                const volatility = basePrice * 0.02;
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
            currentTime += 86400;
        }
        
        console.log('Generated sample data:', data.length, 'points');
        return data;
    }

    updateChart() {
        if (this.candlestickSeries && this.data.length > 0) {
            this.candlestickSeries.setData(this.data);
            this.chart.timeScale().fitContent();
        }
    }

    updateUI() {
        if (this.data.length === 0) return;

        const latestData = this.data[this.data.length - 1];
        const previousData = this.data[this.data.length - 2] || this.data[0];

        // Update current price
        const currentPriceEl = document.getElementById('current-price');
        if (currentPriceEl) {
            currentPriceEl.textContent = latestData.close.toFixed(2);
        }

        // Update price change
        const priceChangeEl = document.getElementById('price-change');
        if (priceChangeEl) {
            const change = latestData.close - previousData.close;
            const changePercent = ((change / previousData.close) * 100).toFixed(2);
            priceChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
            priceChangeEl.className = change >= 0 ? 'positive' : 'negative';
        }

        // Update connection status
        const statusEl = document.getElementById('connection-status');
        if (statusEl) {
            statusEl.textContent = this.isSampleData ? 'Sample Data' : 'CSV Data';
            statusEl.className = 'status connected';
        }

        // Update summary stats
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

        // Update change percentage
        const change = latestData.close - previousData.close;
        const changePercent = ((change / previousData.close) * 100).toFixed(2);
        const statChangeEl = document.getElementById('stat-change');
        if (statChangeEl) {
            statChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
        }
    }

    setupControls() {
        // Zoom controls
        const zoomInBtn = document.getElementById('zoom-in-btn');
        const zoomOutBtn = document.getElementById('zoom-out-btn');
        const resetZoomBtn = document.getElementById('reset-zoom-btn');

        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', () => {
                if (this.chart) this.chart.timeScale().zoomIn();
            });
        }

        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', () => {
                if (this.chart) this.chart.timeScale().zoomOut();
            });
        }

        if (resetZoomBtn) {
            resetZoomBtn.addEventListener('click', () => {
                if (this.chart) this.chart.timeScale().fitContent();
            });
        }
    }

    connectWebSocket() {
        // WebSocket connection for real-time updates
        // Implementation depends on requirements
        console.log('WebSocket connection not implemented in basic loader');
    }

    startAutoRefresh() {
        // Auto-refresh implementation
        console.log('Auto-refresh not implemented in basic loader');
    }

    // Public methods for external control
    updateSymbol(symbol) {
        this.config.symbol = symbol;
        this.loadData();
    }

    updateTimeframe(timeframe) {
        this.config.timeframe = timeframe;
        this.loadData();
    }

    refresh() {
        this.loadData();
    }
}

// Export for use in different pages
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartLoader;
}
