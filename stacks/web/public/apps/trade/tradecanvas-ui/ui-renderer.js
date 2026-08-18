// YAML-driven UI Renderer for TradeCanvas
class UIRenderer {
    constructor(config) {
        this.config = config;
        this.chart = null;
        this.candlestickSeries = null;
    }

    renderNavigation() {
        const navContainer = document.querySelector('.nav-list');
        if (!navContainer) return;

        const currentPage = window.location.pathname.split('/').pop() || 'index.html';
        
        navContainer.innerHTML = this.config.navigation.map(item => {
            const isActive = item.url === currentPage ? 'active' : '';
            return `
                <li class="nav-item">
                    <a href="${item.url}" class="nav-link ${isActive}">${item.title}</a>
                </li>
            `;
        }).join('');
    }

    renderPage(pageName) {
        const pageConfig = this.config.pages[pageName];
        if (!pageConfig) {
            console.error(`Page config not found for: ${pageName}`);
            return;
        }

        // Update title
        document.title = pageConfig.title;
        document.querySelector('header h1').textContent = pageConfig.title;

        // Initialize chart if enabled
        if (pageConfig.show_chart) {
            this.initializeChart(pageConfig);
        }
    }

    initializeChart(pageConfig) {
        const chartContainer = document.getElementById('main-chart');
        if (!chartContainer) return;

        // Force dimensions
        chartContainer.style.width = '100%';
        chartContainer.style.height = '500px';

        const colors = this.config.colors;
        
        this.chart = LightweightCharts.createChart(chartContainer, {
            width: chartContainer.clientWidth,
            height: chartContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: colors.background },
                textColor: colors.text,
            },
            grid: {
                vertLines: { color: colors.grid },
                horzLines: { color: colors.grid },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    width: 1,
                    color: colors.accent,
                    style: LightweightCharts.LineStyle.Dashed,
                },
                horzLine: {
                    width: 1,
                    color: colors.accent,
                    style: LightweightCharts.LineStyle.Dashed,
                },
            },
            rightPriceScale: {
                borderColor: colors.grid,
            },
            timeScale: {
                borderColor: colors.grid,
                timeVisible: true,
                secondsVisible: false,
            },
        });

        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: colors.up,
            downColor: colors.down,
            borderDownColor: colors.down,
            borderUpColor: colors.up,
            wickDownColor: colors.down,
            wickUpColor: colors.up,
        });

        // Generate sample data
        const data = this.generateSampleData(pageConfig.symbol);
        this.candlestickSeries.setData(data);
        this.chart.timeScale().fitContent();

        // Update UI
        this.updateStats(data);
    }

    generateSampleData(symbol) {
        const basePrices = {
            'THB': 35.5,
            'EUR': 1.08,
            'GBP': 1.27,
            'JPY': 155.0,
            'DXY': 105.0,
            'OIL': 75.0
        };
        
        const basePrice = basePrices[symbol] || 100.0;
        const data = [];
        let price = basePrice;
        const endTime = Math.floor(Date.now() / 1000);
        const startTime = endTime - (365 * 86400);
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
        
        return data;
    }

    updateStats(data) {
        if (data.length === 0) return;

        const latestData = data[data.length - 1];
        const previousData = data[data.length - 2] || data[0];

        const currentPriceEl = document.getElementById('current-price');
        const priceChangeEl = document.getElementById('price-change');
        const statusEl = document.getElementById('connection-status');

        if (currentPriceEl) {
            currentPriceEl.textContent = latestData.close.toFixed(2);
        }

        if (priceChangeEl) {
            const change = latestData.close - previousData.close;
            const changePercent = ((change / previousData.close) * 100).toFixed(2);
            priceChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
            priceChangeEl.className = change >= 0 ? 'positive' : 'negative';
        }

        if (statusEl) {
            statusEl.textContent = 'Sample Data';
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

        const change = latestData.close - previousData.close;
        const changePercent = ((change / previousData.close) * 100).toFixed(2);
        const statChangeEl = document.getElementById('stat-change');
        if (statChangeEl) {
            statChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
        }
    }
}

// Load YAML config and initialize
async function initUI() {
    try {
        const response = await fetch('ssot.ui.yml');
        const yamlText = await response.text();
        
        // Simple YAML parser (for basic structure)
        const config = parseSimpleYAML(yamlText);
        
        const renderer = new UIRenderer(config);
        renderer.renderNavigation();
        
        const currentPage = window.location.pathname.split('/').pop() || 'index.html';
        const pageName = currentPage.replace('.html', '');
        renderer.renderPage(pageName);
        
    } catch (error) {
        console.error('Failed to load UI config:', error);
        // Fallback to basic initialization
        initFallback();
    }
}

function parseSimpleYAML(yamlText) {
    // Very basic YAML parser for our specific structure
    const lines = yamlText.split('\n');
    const result = { pages: {}, navigation: [], chart_settings: {}, colors: {} };
    
    let currentSection = null;
    let currentSubsection = null;
    
    for (const line of lines) {
        const trimmed = line.trim();
        
        if (trimmed.startsWith('pages:')) {
            currentSection = 'pages';
            continue;
        } else if (trimmed.startsWith('navigation:')) {
            currentSection = 'navigation';
            continue;
        } else if (trimmed.startsWith('chart_settings:')) {
            currentSection = 'chart_settings';
            continue;
        } else if (trimmed.startsWith('colors:')) {
            currentSection = 'colors';
            continue;
        }
        
        if (currentSection === 'pages' && trimmed.endsWith(':')) {
            currentSubsection = trimmed.replace(':', '');
            result.pages[currentSubsection] = {};
        } else if (currentSection === 'pages' && currentSubsection) {
            const [key, value] = trimmed.split(':').map(s => s.trim());
            if (key && value) {
                const boolValue = value === 'true' ? true : value === 'false' ? false : value;
                result.pages[currentSubsection][key] = boolValue;
            }
        } else if (currentSection === 'navigation' && trimmed.startsWith('-')) {
            const navItem = {};
            const itemContent = trimmed.replace('-', '').trim();
            const parts = itemContent.split(':').map(s => s.trim());
            if (parts.length >= 2) {
                navItem[parts[0]] = parts[1].replace(/"/g, '');
                if (parts.length >= 4) {
                    navItem[parts[2]] = parts[3] === 'true';
                }
            }
            result.navigation.push(navItem);
        } else if (currentSection === 'colors' && trimmed.includes(':')) {
            const [key, value] = trimmed.split(':').map(s => s.trim());
            if (key && value) {
                result.colors[key] = value.replace(/"/g, '');
            }
        }
    }
    
    return result;
}

function initFallback() {
    // Fallback to direct chart initialization
    document.addEventListener('DOMContentLoaded', function() {
        const chartContainer = document.getElementById('main-chart');
        if (!chartContainer) return;

        chartContainer.style.width = '100%';
        chartContainer.style.height = '500px';
        
        const chart = LightweightCharts.createChart(chartContainer, {
            width: chartContainer.clientWidth,
            height: chartContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: '#21262d' },
                textColor: '#e6edf3',
            },
            grid: {
                vertLines: { color: '#30363d' },
                horzLines: { color: '#30363d' },
            },
        });
        
        const candlestickSeries = chart.addCandlestickSeries({
            upColor: '#238636',
            downColor: '#da3633',
            borderDownColor: '#da3633',
            borderUpColor: '#238636',
            wickDownColor: '#da3633',
            wickUpColor: '#238636',
        });
        
        // Generate sample data
        const data = [];
        const basePrice = 35.5;
        let price = basePrice;
        const endTime = Math.floor(Date.now() / 1000);
        const startTime = endTime - (365 * 86400);
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
        
        candlestickSeries.setData(data);
        chart.timeScale().fitContent();
        
        // Update UI
        const latestData = data[data.length - 1];
        const previousData = data[data.length - 2] || data[0];
        
        const currentPriceEl = document.getElementById('current-price');
        const priceChangeEl = document.getElementById('price-change');
        const statusEl = document.getElementById('connection-status');
        
        if (currentPriceEl) currentPriceEl.textContent = latestData.close.toFixed(2);
        
        if (priceChangeEl) {
            const change = latestData.close - previousData.close;
            const changePercent = ((change / previousData.close) * 100).toFixed(2);
            priceChangeEl.textContent = `${change >= 0 ? '+' : ''}${changePercent}%`;
            priceChangeEl.className = change >= 0 ? 'positive' : 'negative';
        }
        
        if (statusEl) {
            statusEl.textContent = 'Sample Data';
            statusEl.className = 'status connected';
        }
    });
}

// Initialize when DOM is ready
if (typeof LightweightCharts !== 'undefined') {
    initUI();
} else {
    document.addEventListener('DOMContentLoaded', function() {
        // Wait for Lightweight Charts
        function waitForLib() {
            if (typeof LightweightCharts !== 'undefined') {
                initUI();
            } else {
                setTimeout(waitForLib, 100);
            }
        }
        waitForLib();
    });
}
