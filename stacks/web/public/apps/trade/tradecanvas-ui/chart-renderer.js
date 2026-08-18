// Chart Renderer for TradeCanvas
// Owns LightweightCharts initialization, candlestick rendering, and zoom controls.

class ChartRenderer {
    constructor(options = {}) {
        this.containerId = options.containerId || 'main-chart';
        this.chartSettings = {
            upColor: options.upColor || '#238636',
            downColor: options.downColor || '#da3633',
            backgroundColor: options.backgroundColor || '#21262d',
            gridColor: options.gridColor || '#30363d',
            ...options.chartSettings
        };

        this.chart = null;
        this.candlestickSeries = null;
        this.volumeSeries = null;
        this.indicatorSeries = null;
        this.activeSeries = null;
    }

    initializeChart() {
        const chartContainer = document.getElementById(this.containerId);
        if (!chartContainer) {
            console.error('Chart container not found:', this.containerId);
            return;
        }

        // Force dimensions.
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

        this.activeSeries = null;

        // Handle window resize.
        window.addEventListener('resize', () => {
            if (this.chart) {
                this.chart.applyOptions({
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight,
                });
            }
        });
    }

    _formatTime(timestamp) {
        if (typeof timestamp === 'string') return timestamp;
        if (timestamp == null) return null;
        const date = new Date(timestamp * 1000);
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    updateChart(data) {
        if (!this.chart || !data || data.length === 0) return;

        // Remove any previously-added series so we can switch between candle and line.
        if (this.activeSeries) {
            this.chart.removeSeries(this.activeSeries);
            this.activeSeries = null;
        }

        // Detect whether the data has genuine OHLC variation. If not, draw a line chart.
        const hasOhlc = data.some(d =>
            Number.isFinite(d.open) && Number.isFinite(d.high) &&
            Number.isFinite(d.low) && Number.isFinite(d.close) &&
            (d.open !== d.close || d.high !== d.low || d.high !== d.close)
        );

        let displayData = [];

        if (hasOhlc) {
            displayData = data
                .filter(d => d.time != null && Number.isFinite(d.open) && Number.isFinite(d.high) && Number.isFinite(d.low) && Number.isFinite(d.close))
                .map(d => ({
                    time: this._formatTime(d.time),
                    open: d.open,
                    high: d.high,
                    low: d.low,
                    close: d.close
                }));

            this.candlestickSeries = this.chart.addCandlestickSeries({
                upColor: this.chartSettings.upColor,
                downColor: this.chartSettings.downColor,
                borderDownColor: this.chartSettings.downColor,
                borderUpColor: this.chartSettings.upColor,
                wickDownColor: this.chartSettings.downColor,
                wickUpColor: this.chartSettings.upColor,
            });
            this.candlestickSeries.setData(displayData);
            this.activeSeries = this.candlestickSeries;
        } else {
            displayData = data
                .filter(d => d.time != null && Number.isFinite(d.close))
                .map(d => ({
                    time: this._formatTime(d.time),
                    value: d.close
                }));

            this.lineSeries = this.chart.addLineSeries({
                color: this.chartSettings.upColor,
                lineWidth: 2,
            });
            this.lineSeries.setData(displayData);
            this.activeSeries = this.lineSeries;
        }

        if (displayData.length === 0) {
            return;
        }

        if (displayData.length === 1) {
            // Show a few logical bars of empty space around the lone candle.
            this.chart.timeScale().setVisibleLogicalRange({ from: -3.5, to: 3.5 });
            return;
        }

        // Density guard: if all candles are too dense to be visible, show
        // only the most recent bars instead of letting fitContent squeeze
        // them to sub-pixel width.
        const chartContainer = document.getElementById(this.containerId);
        const chartWidth = chartContainer ? chartContainer.clientWidth : this.chart.options().width;
        const desiredBarSpacing = 4; // px per bar, enough to see a candle
        const maxVisibleBars = Math.max(50, Math.floor(chartWidth / desiredBarSpacing));

        if (displayData.length > maxVisibleBars) {
            const from = Math.max(0, displayData.length - maxVisibleBars);
            this.chart.timeScale().setVisibleLogicalRange({ from: from, to: displayData.length - 1 });
        } else {
            this.chart.timeScale().fitContent();
        }
    }

    setupControls() {
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
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartRenderer;
}
