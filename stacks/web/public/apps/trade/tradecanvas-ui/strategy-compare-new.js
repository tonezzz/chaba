// Strategy engine for the Compare page backtest panel
// Loads ssot.ui.yml and lets the user run a quick client-side backtest
// against the data already loaded by ChartLoader.
// Now uses modular strategy system from strategies.js
// Hindsight strategies loaded from hindsight-strategies.js
// Version 14

class StrategyPanel {
    constructor(chartLoader, config) {
        this.chartLoader = chartLoader;
        this.config = config;
        this.data = chartLoader.data || [];
        this.controlsContainer = document.getElementById('strategy-controls');
        this.resultContainer = document.getElementById('strategy-results');
        this.strategyInstances = new Map(); // Cache strategy instances
    }

    init() {
        window.runAllBacktest = this.runAll.bind(this);
        window.runAllWithFeedback = () => {
            const status = document.getElementById('single-result');
            try {
                if (status) status.innerHTML = '<p style="color:#a8d5ff; font-size:11px;">Running all strategies...</p>';
                if (typeof window.runAllBacktest !== 'function') {
                    if (status) status.innerHTML = '<p style="color:#da3633; font-size:11px;">Run All not ready yet.</p>';
                    return;
                }
                window.runAllBacktest();
            } catch (e) {
                if (status) status.innerHTML = '<p style="color:#da3633; font-size:11px;">' + e.message + '</p>';
                console.error(e);
            }
        };
        
        // Add toggle functionality for parameters
        const toggleBtn = document.getElementById('toggle-params');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => this.toggleParams());
        }
        
        this.buildControls();
        this.resultContainer.innerHTML = '<div id="single-result" style="margin-bottom:4px;"><p style="color:#a8d5ff; font-size:11px; margin-top:2px;">Click "Run Backtest" or "Run All" to see results.</p></div><div id="compare-table"></div>';
        this.singleResult = document.getElementById('single-result');
        this.compareTable = document.getElementById('compare-table');
        this.backtests = [];
        
        // Manual perfect strategy state
        this.manualBuyPoints = [];
        this.manualSellPoints = [];
        this.chartClickEnabled = false;
        this.chartClickHandler = null;
        this.autoDetect = false;
    }
    
    toggleParams() {
        const paramsContainer = document.getElementById('strategy-params');
        const toggleBtn = document.getElementById('toggle-params');
        if (paramsContainer) {
            paramsContainer.style.display = paramsContainer.style.display === 'none' ? 'block' : 'none';
            toggleBtn.textContent = paramsContainer.style.display === 'none' ? '▶' : '▼';
        }
    }

    buildControls() {
        const strategies = this.config.strategies;

        let html = '<div class="setting-group" style="margin-bottom:6px;">';
        html += '<label style="font-size:11px; color:#a8d5ff; display:block; margin-bottom:2px;">Strategy:</label>';
        html += '<select id="strategy-select" class="selector" style="width:100%; padding:4px; font-size:12px; background:#21262d; border:1px solid #30363d; border-radius:3px; color:#e6edf3;">';
        for (const [key, strat] of Object.entries(strategies)) {
            html += `<option value="${key}" ${strat.enabled ? 'selected' : ''}>${strat.label}</option>`;
        }
        html += '</select></div>';

        html += '<div id="strategy-params" style="margin-bottom:6px;"></div>';

        const exec = this.config.execution;
        html += '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:4px; margin-bottom:4px;">';
        html += this.compactNumberInput('Capital', 'strategy-capital', exec.initial_capital, 1);
        html += this.compactNumberInput('Pos %', 'strategy-position', exec.position_sizing.value, 0.01);
        html += this.compactNumberInput('Stop %', 'strategy-stop', exec.stop_loss.value, 0.001);
        html += this.compactNumberInput('TP %', 'strategy-tp', exec.take_profit.value, 0.001);
        html += this.compactNumberInput('Comm', 'strategy-commission', exec.commission, 0.0001);
        html += this.compactNumberInput('Slip', 'strategy-slippage', exec.slippage, 0.0001);
        html += '</div>';

        html += '<button id="run-backtest" class="btn" style="width:100%; margin-top:6px; padding:8px; font-size:12px;">Run Backtest</button>';
        html += '<button id="run-walkforward" class="btn" style="width:100%; margin-top:4px; padding:8px; font-size:12px; background:#8957e5; border-color:#8957e5;">Walk-Forward Analysis</button>';
        html += '<button id="run-all" class="btn" style="width:100%; margin-top:4px; padding:8px; font-size:12px;">Run All & Compare</button>';

        this.controlsContainer.innerHTML = html;

        // Setup event listeners
        document.getElementById('run-backtest').addEventListener('click', () => this.runBacktest());
        document.getElementById('run-walkforward').addEventListener('click', () => this.runWalkForward());
        document.getElementById('run-all').addEventListener('click', () => this.runAll());

        // Hide SL/TP and Pos % for hindsight strategies on initial load
        const initialKey = document.getElementById('strategy-select').value;
        const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
        if (hindsightStrategies.includes(initialKey)) {
            const stopField = document.getElementById('strategy-stop');
            const tpField = document.getElementById('strategy-tp');
            const posField = document.getElementById('strategy-position');
            if (stopField) stopField.parentElement.style.display = 'none';
            if (tpField) tpField.parentElement.style.display = 'none';
            if (posField) posField.parentElement.style.display = 'none';
        }

        document.getElementById('strategy-select').addEventListener('change', () => {
            this.renderParams();
            // Handle chart clicking for manual strategy
            const key = document.getElementById('strategy-select').value;
            
            // Hide SL/TP and Pos % for hindsight strategies
            const stopField = document.getElementById('strategy-stop');
            const tpField = document.getElementById('strategy-tp');
            const posField = document.getElementById('strategy-position');
            const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
            if (hindsightStrategies.includes(key)) {
                if (stopField) stopField.parentElement.style.display = 'none';
                if (tpField) tpField.parentElement.style.display = 'none';
                if (posField) posField.parentElement.style.display = 'none';
                // No chart clicking for automatic strategies
            } else {
                if (stopField) stopField.parentElement.style.display = 'flex';
                if (tpField) tpField.parentElement.style.display = 'flex';
                if (posField) posField.parentElement.style.display = 'flex';
                // Clear manual point markers when switching away
                if (this.chartLoader.candlestickSeries) {
                    this.chartLoader.candlestickSeries.setMarkers([]);
                }
            }
        });
        
        this.renderParams();
    }
    
    compactNumberInput(label, id, value, step) {
        return `<div class="setting-group" style="display:flex; gap:4px; align-items:center;">
            <label style="min-width:35px; font-size:11px; color:#a8d5ff;">${label}:</label>
            <input type="number" id="${id}" step="${step}" value="${value}" style="flex:1; padding:4px; font-size:11px; background:#21262d; border:1px solid #30363d; border-radius:3px; color:#e6edf3;">
        </div>`;
    }

    numberInput(label, id, value, step) {
        return `<div class="setting-group">
            <label>${label}:</label>
            <input type="number" id="${id}" step="${step}" value="${value}">
        </div>`;
    }

    renderParams() {
        const key = document.getElementById('strategy-select').value;
        const strat = this.config.strategies[key];
        const container = document.getElementById('strategy-params');
        
        // Special handling for hindsight strategies
        const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
        if (hindsightStrategies.includes(key)) {
            this.renderHindsightParams(container, key);
            return;
        }
        
        let html = '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:4px;">';
        for (const [pkey, pval] of Object.entries(strat.parameters)) {
            html += `<div class="setting-group" style="display:flex; gap:4px; align-items:center;">
                <label style="min-width:50px; font-size:11px; color:#a8d5ff;">${pkey}:</label>
                <input type="number" class="strategy-param" data-key="${pkey}" step="any" value="${pval}" style="flex:1; padding:4px; font-size:11px; background:#21262d; border:1px solid #30363d; border-radius:3px; color:#e6edf3;">
            </div>`;
        }
        html += '</div>';
        container.innerHTML = html;
    }

    renderHindsightParams(container, key) {
        const descriptions = {
            'hindsight_01': '🎯 Hindsight-01: Peak/valley detection with future knowledge',
            'hindsight_02': '🎯 Hindsight-02: Sensitive day-by-day trend detection'
        };
        
        let html = '<div style="font-size:11px; color:#a8d5ff; margin-bottom:4px;">';
        html += `<p style="margin:0 0 4px 0;">${descriptions[key]}</p>`;
        html += '<p style="margin:0 0 4px 0;">• Auto-detects buy/sell points automatically</p>';
        html += '<p style="margin:0 0 4px 0;">• Uses 100% position sizing</p>';
        html += '<p style="margin:0 0 8px 0;">• No stop loss or take profit</p>';
        html += '</div>';
        
        // Add min change parameter for Hindsight-01
        if (key === 'hindsight_01') {
            html += '<div style="display:flex; gap:4px; align-items:center; margin-bottom:4px;">';
            html += `<label style="min-width:50px; font-size:11px; color:#a8d5ff;">Min %:</label>`;
            html += `<input type="number" id="min-change-pct" value="1.0" min="0.1" max="10" step="0.1" style="flex:1; padding:4px; font-size:11px; background:#21262d; border:1px solid #30363d; border-radius:3px; color:#e6edf3;">`;
            html += '</div>';
        }
        
        html += '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:4px; margin-bottom:4px;">';
        html += `<div class="setting-group" style="display:flex; gap:4px; align-items:center;">
            <label style="min-width:50px; font-size:11px; color:#a8d5ff;">Buy pts:</label>
            <span id="buy-count" style="flex:1; padding:4px; font-size:11px; background:#21262d; border:1px solid #30363d; border-radius:3px; color:#e6edf3;">Auto</span>
        </div>`;
        html += `<div class="setting-group" style="display:flex; gap:4px; align-items:center;">
            <label style="min-width:50px; font-size:11px; color:#a8d5ff;">Sell pts:</label>
            <span id="sell-count" style="flex:1; padding:4px; font-size:11px; background:#21262d; border:1px solid #30363d; border-radius:3px; color:#e6edf3;">Auto</span>
        </div>`;
        html += '</div>';
        
        container.innerHTML = html;
        
        // Min change listener for Hindsight-01
        if (key === 'hindsight_01') {
            document.getElementById('min-change-pct').addEventListener('change', (e) => {
                this.minChangePct = parseFloat(e.target.value) / 100 || 0.01;
            });
        }
        
        // Auto-detect always runs on backtest - no manual controls needed
        this.autoDetect = true;
    }

    getSelected() {
        const key = document.getElementById('strategy-select').value;
        
        // Special handling for hindsight strategies
        const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
        if (hindsightStrategies.includes(key)) {
            const params = {
                buy_points: [],  // Empty - let strategy auto-detect
                sell_points: [], // Empty - let strategy auto-detect
                auto_detect: true  // Always auto-detect on every run
            };
            
            // Add min_change_pct for Hindsight-01
            if (key === 'hindsight_01') {
                const minChangeInput = document.getElementById('min-change-pct');
                if (minChangeInput) {
                    params.min_change_pct = parseFloat(minChangeInput.value) / 100 || 0.01;
                } else {
                    params.min_change_pct = 0.01;
                }
            }
            
            return { key, params };
        }
        
        // For non-hindsight strategies, get parameters from inputs
        const inputs = document.querySelectorAll('.strategy-param');
        const params = {};
        inputs.forEach(input => {
            params[input.dataset.key] = parseFloat(input.value);
        });
        return { key, params };
    }

    runBacktest() {
        if (!this.data || this.data.length === 0) {
            this.singleResult.innerHTML = '<p style="color:#da3633;">No chart data loaded yet.</p>';
            this.compareTable.innerHTML = '';
            return;
        }

        const { key, params } = this.getSelected();
        const settings = {
            capital: parseFloat(document.getElementById('strategy-capital').value) || this.config.execution.initial_capital,
            positionPct: parseFloat(document.getElementById('strategy-position').value) || 0.1,
            stopPct: parseFloat(document.getElementById('strategy-stop').value) || 0.05,
            tpPct: parseFloat(document.getElementById('strategy-tp').value) || 0.10,
            commission: parseFloat(document.getElementById('strategy-commission').value) || 0.001,
            slippage: parseFloat(document.getElementById('strategy-slippage').value) || 0.0001
        };

        // For hindsight strategies, always use 100% position sizing
        const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
        if (hindsightStrategies.includes(key)) {
            settings.positionPct = 1.0;
            settings.stopPct = 0;
            settings.tpPct = 0;
        }
        
        // For hindsight strategies, set SL/TP to 0 (they won't be used)

        // Special handling for hindsight strategies - always auto-detect
        if (hindsightStrategies.includes(key)) {
            // Create a temporary strategy instance to run auto-detect
            const tempStrategy = StrategyFactory.create(key, params);
            tempStrategy.setData(this.data);
            tempStrategy.calculateIndicators(this.data); // This triggers auto-detect
            
            // Get the auto-detected points
            const autoParams = {
                buy_points: tempStrategy.buyPoints,
                sell_points: tempStrategy.sellPoints,
                auto_detect: true
            };
            
            const { result, metrics } = this.runStrategy(key, autoParams, settings);
            this.updateResults(metrics);
            this.addBacktest(key, autoParams, settings, result, metrics);
            this.renderComparisonTable();

            if (this.config.display.show_chart_markers && this.chartLoader.candlestickSeries) {
                this.setMarkers(result.trades);
            }
        } else {
            const { result, metrics } = this.runStrategy(key, params, settings);
            this.updateResults(metrics);
            this.addBacktest(key, params, settings, result, metrics);
            this.renderComparisonTable();

            if (this.config.display.show_chart_markers && this.chartLoader.candlestickSeries) {
                this.setMarkers(result.trades);
            }
        }
    }

    runWalkForward() {
        const { key, params } = this.getSelected();
        const settings = {
            capital: parseFloat(document.getElementById('strategy-capital').value) || this.config.execution.initial_capital,
            positionPct: parseFloat(document.getElementById('strategy-position').value) || 0.1,
            stopPct: parseFloat(document.getElementById('strategy-stop').value) || 0.05,
            tpPct: parseFloat(document.getElementById('strategy-tp').value) || 0.10,
            commission: parseFloat(document.getElementById('strategy-commission').value) || 0.001,
            slippage: parseFloat(document.getElementById('strategy-slippage').value) || 0.0001
        };

        // For hindsight strategies, always use 100% position sizing
        const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
        if (hindsightStrategies.includes(key)) {
            settings.positionPct = 1.0;
            settings.stopPct = 0;
            settings.tpPct = 0;
        }

        this.runWalkForwardAnalysis(key, params, settings);
    }

    getStrategy(key, params) {
        // Get or create strategy instance
        const cacheKey = `${key}_${JSON.stringify(params)}`;
        if (!this.strategyInstances.has(cacheKey)) {
            const strategy = StrategyFactory.create(key, params);
            // Set data for strategies that need it (like Bollinger)
            if (strategy.setData) {
                strategy.setData(this.data);
            }
            this.strategyInstances.set(cacheKey, strategy);
        } else {
            // Update data if it has changed
            const strategy = this.strategyInstances.get(cacheKey);
            if (strategy.setData) {
                strategy.setData(this.data);
            }
            // Update points for manual strategy
            if (key === 'manual_perfect' && strategy.updatePoints) {
                strategy.updatePoints(params);
            }
        }
        return this.strategyInstances.get(cacheKey);
    }

    getIndicators(key, params) {
        const strategy = this.getStrategy(key, params);
        return strategy.calculateIndicators(this.data);
    }

    getSignal(i, key, params, inds) {
        const strategy = this.getStrategy(key, params);
        return strategy.getSignal(i, inds);
    }

    simulate(key, params, settings) {
        const data = this.data;
        const inds = this.getIndicators(key, params);
        let cash = settings.capital;
        let inPosition = false;
        let shares = 0;
        let entryPrice = 0;
        let stopPrice = 0;
        let tpPrice = 0;
        let entryIdx = -1;
        const trades = [];
        let maxEquity = settings.capital;
        let maxDrawdown = 0;
        
        // Hindsight strategies don't use SL/TP
        const isHindsightStrategy = ['manual_perfect', 'hindsight_01', 'hindsight_02'].includes(key);

        for (let i = 1; i < data.length; i++) {
            const equity = cash + (inPosition ? shares * data[i].close : 0);
            if (equity > maxEquity) maxEquity = equity;
            const dd = (maxEquity - equity) / maxEquity;
            if (dd > maxDrawdown) maxDrawdown = dd;

            const signal = this.getSignal(i, key, params, inds);

            if (inPosition) {
                let exitPrice = null;
                
                if (isHindsightStrategy) {
                    // Hindsight strategies: only exit on sell signal
                    if (signal.sell) exitPrice = data[i].close;
                } else {
                    // Other strategies: use SL/TP
                    if (data[i].low <= stopPrice) exitPrice = stopPrice;
                    else if (data[i].high >= tpPrice) exitPrice = tpPrice;
                    else if (signal.sell) exitPrice = data[i].close;
                }

                if (exitPrice !== null) {
                    const sellPrice = exitPrice * (1 - settings.commission - settings.slippage);
                    const profit = shares * (sellPrice - entryPrice);
                    cash += shares * sellPrice;
                    trades.push({
                        entryIndex: entryIdx,
                        exitIndex: i,
                        entryPrice,
                        exitPrice: sellPrice,
                        profit,
                        returnPct: entryPrice > 0 ? profit / (shares * entryPrice) : 0
                    });
                    inPosition = false;
                    shares = 0;
                }
            }

            if (!inPosition && signal.buy) {
                const rawPrice = data[i].close;
                const buyPrice = rawPrice * (1 + settings.commission + settings.slippage);
                const positionValue = cash * settings.positionPct;
                const qty = positionValue / buyPrice;
                const cost = qty * buyPrice;
                if (cost <= cash) {
                    cash -= cost;
                    shares = qty;
                    inPosition = true;
                    entryPrice = buyPrice;
                    entryIdx = i;
                    
                    // Only set SL/TP for non-hindsight strategies
                    if (!isHindsightStrategy) {
                        stopPrice = buyPrice * (1 - settings.stopPct);
                        tpPrice = buyPrice * (1 + settings.tpPct);
                    }
                }
            }
        }

        if (inPosition) {
            const sellPrice = data[data.length - 1].close * (1 - settings.commission - settings.slippage);
            const profit = shares * (sellPrice - entryPrice);
            cash += shares * sellPrice;
            trades.push({
                entryIndex: entryIdx,
                exitIndex: data.length - 1,
                entryPrice,
                exitPrice: sellPrice,
                profit,
                returnPct: entryPrice > 0 ? profit / (shares * entryPrice) : 0
            });
        }

        return { trades, finalCapital: cash, maxDrawdown, initialCapital: settings.capital };
    }

    computeMetrics(result, settings) {
        const trades = result.trades;
        const totalTrades = trades.length;
        const wins = trades.filter(t => t.profit > 0).length;
        const losses = totalTrades - wins;
        const winRate = totalTrades > 0 ? wins / totalTrades : 0;
        const grossWins = trades.filter(t => t.profit > 0).reduce((a, t) => a + t.profit, 0);
        const grossLosses = Math.abs(trades.filter(t => t.profit < 0).reduce((a, t) => a + t.profit, 0));
        const profitFactor = grossLosses > 0 ? grossWins / grossLosses : (grossWins > 0 ? Infinity : 0);
        const avgWin = wins > 0 ? grossWins / wins : 0;
        const avgLoss = losses > 0 ? grossLosses / losses : 0;
        const totalReturn = (result.finalCapital - result.initialCapital) / result.initialCapital;

        return {
            total_return: totalReturn,
            total_trades: totalTrades,
            win_rate: winRate,
            profit_factor: profitFactor,
            max_drawdown: result.maxDrawdown,
            avg_win: avgWin,
            avg_loss: avgLoss,
            final_capital: result.finalCapital
        };
    }

    updateResults(metrics) {
        const labels = {
            total_return: 'Total Return %',
            total_trades: 'Total Trades',
            win_rate: 'Win Rate %',
            profit_factor: 'Profit Factor',
            max_drawdown: 'Max Drawdown %',
            avg_win: 'Avg Win $',
            avg_loss: 'Avg Loss $',
            final_capital: 'Final Capital $'
        };
        const order = this.config.metrics;

        let html = '<div class="summary-stats">';
        for (const key of order) {
            const v = metrics[key];
            let text;
            if (['total_return', 'max_drawdown', 'win_rate'].includes(key)) {
                text = (v * 100).toFixed(2) + '%';
            } else if (key === 'total_trades') {
                text = String(v);
            } else if (key === 'profit_factor') {
                text = v.toFixed(2);
            } else if (['avg_win', 'avg_loss', 'final_capital'].includes(key)) {
                text = v.toFixed(2);
            } else {
                text = typeof v === 'number' ? v.toFixed(2) : v;
            }
            html += `<div class="stat-row"><span class="stat-label">${labels[key] || key}:</span><span class="stat-value">${text}</span></div>`;
        }
        html += '</div>';
        this.singleResult.innerHTML = html;
    }

    runStrategy(key, params, settings) {
        const result = this.simulate(key, params, settings);
        const metrics = this.computeMetrics(result, settings);
        return { result, metrics };
    }

    addBacktest(key, params, settings, result, metrics) {
        const runId = `${key}_${this.backtests.length + 1}`;
        const idx = this.backtests.findIndex(b => b.key === key);
        const entry = {
            id: runId,
            key,
            label: this.config.strategies[key].label,
            params,
            settings,
            result,
            metrics
        };
        if (idx !== -1) {
            this.backtests[idx] = entry;
        } else {
            this.backtests.push(entry);
        }
    }

    runAll() {
        try {
        if (!this.data || this.data.length === 0) {
            this.singleResult.innerHTML = '<p style="color:#da3633;">No chart data loaded yet.</p>';
            this.compareTable.innerHTML = '';
            return;
        }
        const settings = {
            capital: parseFloat(document.getElementById('strategy-capital').value) || this.config.execution.initial_capital,
            positionPct: parseFloat(document.getElementById('strategy-position').value) || 0.1,
            stopPct: parseFloat(document.getElementById('strategy-stop').value) || 0.05,
            tpPct: parseFloat(document.getElementById('strategy-tp').value) || 0.10,
            commission: parseFloat(document.getElementById('strategy-commission').value) || 0.001,
            slippage: parseFloat(document.getElementById('strategy-slippage').value) || 0.0001
        };

        this.backtests = [];
        for (const [key, strat] of Object.entries(this.config.strategies)) {
            let params = { ...strat.parameters };
            
            // For hindsight strategies, set SL/TP to 0 and use 100% position sizing
            let strategySettings = { ...settings };
            const hindsightStrategies = ['hindsight_01', 'hindsight_02'];
            if (hindsightStrategies.includes(key)) {
                strategySettings.stopPct = 0;
                strategySettings.tpPct = 0;
                strategySettings.positionPct = 1.0;
                
                // Create a temporary strategy instance to run auto-detect
                const tempStrategy = StrategyFactory.create(key, params);
                tempStrategy.setData(this.data);
                tempStrategy.calculateIndicators(this.data); // This triggers auto-detect
                
                // Update params with auto-detected points
                params = {
                    buy_points: tempStrategy.buyPoints,
                    sell_points: tempStrategy.sellPoints,
                    auto_detect: true
                };
            }
            
            const { result, metrics } = this.runStrategy(key, params, strategySettings);
            this.addBacktest(key, params, strategySettings, result, metrics);
        }
        this.singleResult.innerHTML = `<p style="color:#a8d5ff; font-size:10px; margin-top:2px;">Ran ${this.backtests.length} strategies. See comparison below.</p>`;
        this.renderComparisonTable();
        if (this.config.display.show_chart_markers && this.chartLoader.candlestickSeries && this.backtests.length) {
            this.setMarkers(this.backtests[0].result.trades);
        }
        } catch (e) {
            console.error('Run All error:', e);
            this.singleResult.innerHTML = '<p style="color:#da3633;">Run All failed: ' + e.message + '</p>';
        }
    }

    renderComparisonTable() {
        if (!this.compareTable) return;
        const order = this.config.metrics;
        const labels = {
            total_return: 'Return %',
            total_trades: 'Trades',
            win_rate: 'Win %',
            profit_factor: 'P/F',
            max_drawdown: 'DD %',
            avg_win: 'Avg Win',
            avg_loss: 'Avg Loss',
            final_capital: 'Final $'
        };
        const best = {};
        for (const key of order) {
            const values = this.backtests.map(b => b.metrics[key]);
            if (['total_return', 'profit_factor', 'win_rate', 'final_capital', 'avg_win'].includes(key)) {
                best[key] = Math.max(...values);
            } else if (['max_drawdown', 'avg_loss', 'total_trades'].includes(key)) {
                best[key] = Math.min(...values);
            } else {
                best[key] = null;
            }
        }
        let html = '<div style="margin:4px 0; padding:6px; background:#21262d; border-radius:4px; border:1px solid #30363d;">';
        html += '<div style="overflow-x:auto;"><table style="width:100%; font-size:10px; border-collapse:collapse;">';
        html += '<thead><tr style="text-align:left; border-bottom:1px solid #30363d;"><th style="padding:2px 3px;">Strategy</th>';
        for (const key of order) {
            html += `<th style='padding:2px 3px;'>${labels[key] || key}</th>`;
        }
        html += '</tr></thead><tbody>';
        for (const b of this.backtests) {
            html += `<tr style='border-bottom:1px solid #21262d;'>`;
            html += `<td style='padding:2px 3px;'><strong style="font-size:10px;">${b.label}</strong></td>`;
            for (const key of order) {
                const v = b.metrics[key];
                const isBest = best[key] !== null && Math.abs(v - best[key]) < 1e-9;
                let text;
                if (['total_return', 'max_drawdown', 'win_rate'].includes(key)) {
                    text = (v * 100).toFixed(1) + '%';
                } else if (key === 'total_trades') {
                    text = String(v);
                } else if (key === 'profit_factor') {
                    text = v.toFixed(1);
                } else if (['avg_win', 'avg_loss', 'final_capital'].includes(key)) {
                    text = v.toFixed(0);
                } else {
                    text = typeof v === 'number' ? v.toFixed(1) : v;
                }
                const color = isBest ? '#3fb950' : 'inherit';
                html += `<td style='padding:2px 3px; color:${color};'>${text}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table></div></div>';
        this.compareTable.innerHTML = html;
    }

    setMarkers(trades) {
        if (!this.chartLoader.candlestickSeries) return;
        const markers = [];
        for (const t of trades) {
            markers.push({
                time: this.data[t.entryIndex].time,
                position: 'belowBar',
                color: '#238636',
                shape: 'arrowUp',
                text: 'BUY',
                size: 1
            });
            markers.push({
                time: this.data[t.exitIndex].time,
                position: 'aboveBar',
                color: '#da3633',
                shape: 'arrowDown',
                text: 'SELL',
                size: 1
            });
        }
        this.chartLoader.candlestickSeries.setMarkers(markers);
    }

    // Manual perfect strategy methods
    enableChartClicking() {
        if (!this.chartLoader.candlestickSeries) {
            console.warn('Chart series not available for clicking');
            return;
        }

        this.chartClickEnabled = true;
        
        // Remove existing handler if any
        if (this.chartClickHandler) {
            this.chartLoader.chart.subscribeClick(this.chartClickHandler);
        }

        // Add click handler
        this.chartClickHandler = (param) => {
            if (!this.chartClickEnabled) return;
            
            const key = document.getElementById('strategy-select').value;
            if (key !== 'manual_perfect') return;

            // Find the data point closest to the click
            const time = param.time;
            const dataIndex = this.data.findIndex(d => d.time === time);
            
            if (dataIndex === -1) return;

            // Check if shift key is pressed for sell point
            const isSell = param.shiftKey;

            if (isSell) {
                this.toggleManualPoint(dataIndex, 'sell');
            } else {
                this.toggleManualPoint(dataIndex, 'buy');
            }

            this.updateManualPointCounts();
            this.updateManualPointMarkers();
        };

        this.chartLoader.chart.subscribeClick(this.chartClickHandler);
    }

    disableChartClicking() {
        this.chartClickEnabled = false;
        if (this.chartClickHandler && this.chartLoader.chart) {
            this.chartLoader.chart.unsubscribeClick(this.chartClickHandler);
        }
    }

    toggleManualPoint(index, type) {
        if (type === 'buy') {
            const buyIndex = this.manualBuyPoints.indexOf(index);
            if (buyIndex !== -1) {
                // Remove existing buy point
                this.manualBuyPoints.splice(buyIndex, 1);
            } else {
                // Add buy point (remove from sell if exists)
                const sellIndex = this.manualSellPoints.indexOf(index);
                if (sellIndex !== -1) {
                    this.manualSellPoints.splice(sellIndex, 1);
                }
                this.manualBuyPoints.push(index);
                this.manualBuyPoints.sort((a, b) => a - b);
            }
        } else {
            const sellIndex = this.manualSellPoints.indexOf(index);
            if (sellIndex !== -1) {
                // Remove existing sell point
                this.manualSellPoints.splice(sellIndex, 1);
            } else {
                // Add sell point (remove from buy if exists)
                const buyIndex = this.manualBuyPoints.indexOf(index);
                if (buyIndex !== -1) {
                    this.manualBuyPoints.splice(buyIndex, 1);
                }
                this.manualSellPoints.push(index);
                this.manualSellPoints.sort((a, b) => a - b);
            }
        }
        this.updateManualPointCounts();
        this.updateManualPointMarkers();
    }

    clearManualPoints() {
        this.manualBuyPoints = [];
        this.manualSellPoints = [];
        // Don't auto-detect immediately - let user decide when to re-detect
        const buyCount = document.getElementById('buy-count');
        const sellCount = document.getElementById('sell-count');
        if (buyCount) buyCount.textContent = '0';
        if (sellCount) sellCount.textContent = '0';
        this.updateManualPointMarkers();
    }

    updateManualPointCounts() {
        const buyCount = document.getElementById('buy-count');
        const sellCount = document.getElementById('sell-count');
        
        // Always auto-detect - clear and re-detect on every call
        if (this.chartLoader && this.chartLoader.data) {
            const key = document.getElementById('strategy-select').value;
            const params = { auto_detect: true };
            const tempStrategy = StrategyFactory.create(key, params);
            tempStrategy.setData(this.chartLoader.data);
            tempStrategy.calculateIndicators(this.chartLoader.data);
            this.manualBuyPoints = tempStrategy.buyPoints;
            this.manualSellPoints = tempStrategy.sellPoints;
        }
        
        if (buyCount) buyCount.textContent = this.manualBuyPoints.length;
        if (sellCount) sellCount.textContent = this.manualSellPoints.length;
    }

    updateManualPointMarkers() {
        if (!this.chartLoader.candlestickSeries) return;

        const markers = [];
        
        // Add buy point markers
        for (const index of this.manualBuyPoints) {
            markers.push({
                time: this.data[index].time,
                position: 'belowBar',
                color: '#238636',
                shape: 'circle',
                text: 'B',
                size: 2
            });
        }

        // Add sell point markers
        for (const index of this.manualSellPoints) {
            markers.push({
                time: this.data[index].time,
                position: 'aboveBar',
                color: '#da3633',
                shape: 'circle',
                text: 'S',
                size: 2
            });
        }

        this.chartLoader.candlestickSeries.setMarkers(markers);
    }

    runWalkForwardAnalysis(key, params, settings) {
        if (!this.data || this.data.length === 0) {
            this.singleResult.innerHTML = '<p style="color:#da3633;">No chart data loaded yet.</p>';
            return;
        }

        // Walk-forward parameters
        const trainingPeriodMonths = 6;  // 6 months training
        const testingPeriodMonths = 1;   // 1 month testing
        const stepMonths = 1;             // Move forward 1 month at a time
        
        // Convert months to data points (assuming ~20 trading days per month)
        const trainingSize = trainingPeriodMonths * 20;
        const testingSize = testingPeriodMonths * 20;
        const stepSize = stepMonths * 20;
        
        const totalData = this.data.length;
        if (totalData < trainingSize + testingSize) {
            this.singleResult.innerHTML = '<p style="color:#da3633;">Not enough data for walk-forward analysis. Need at least ' + (trainingSize + testingSize) + ' data points.</p>';
            return;
        }

        this.singleResult.innerHTML = '<p style="color:#a8d5ff; font-size:11px;">Running walk-forward analysis...</p>';
        
        const results = [];
        let currentPosition = 0;
        
        while (currentPosition + trainingSize + testingSize <= totalData) {
            // Training period
            const trainingStart = currentPosition;
            const trainingEnd = currentPosition + trainingSize;
            const trainingData = this.data.slice(trainingStart, trainingEnd);
            
            // Testing period  
            const testingStart = trainingEnd;
            const testingEnd = trainingEnd + testingSize;
            const testingData = this.data.slice(testingStart, testingEnd);
            
            // Optimize parameters on training data
            const optimizedParams = this.optimizeParameters(key, params, trainingData, settings);
            
            // Test on testing data
            const testResult = this.runStrategyOnData(key, optimizedParams, testingData, settings);
            
            results.push({
                trainingPeriod: { start: trainingStart, end: trainingEnd },
                testingPeriod: { start: testingStart, end: testingEnd },
                optimizedParams: optimizedParams,
                testResult: testResult
            });
            
            currentPosition += stepSize;
        }
        
        // Aggregate results
        const aggregated = this.aggregateWalkForwardResults(results);
        
        // Display results
        this.displayWalkForwardResults(results, aggregated);
    }

    optimizeParameters(key, baseParams, trainingData, settings) {
        // Simple parameter optimization - can be enhanced
        // For now, return base params (can add grid search, genetic algorithms, etc.)
        
        if (key === 'hindsight_01') {
            // Optimize min_change_pct for Hindsight-01
            const testValues = [0.005, 0.01, 0.015, 0.02, 0.025];
            let bestParams = { ...baseParams };
            let bestSharpe = -Infinity;
            
            for (const minChange of testValues) {
                const testParams = { ...baseParams, min_change_pct: minChange };
                const result = this.runStrategyOnData(key, testParams, trainingData, settings);
                const sharpe = this.calculateSharpeRatio(result);
                
                if (sharpe > bestSharpe) {
                    bestSharpe = sharpe;
                    bestParams = testParams;
                }
            }
            
            return bestParams;
        }
        
        // For other strategies, return base params
        return { ...baseParams };
    }

    runStrategyOnData(key, params, data, settings) {
        const strategy = StrategyFactory.create(key, params);
        strategy.setData(data);
        strategy.calculateIndicators(data);
        
        let cash = settings.capital;
        let shares = 0;
        let inPosition = false;
        const trades = [];
        
        for (let i = 0; i < data.length; i++) {
            const signal = strategy.getSignal(i, {});
            
            if (!inPosition && signal.buy) {
                const buyPrice = data[i].close * (1 + settings.commission + settings.slippage);
                const positionValue = cash * settings.positionPct;
                const qty = positionValue / buyPrice;
                const cost = qty * buyPrice;
                
                if (cost <= cash) {
                    cash -= cost;
                    shares = qty;
                    inPosition = true;
                    trades.push({ type: 'buy', index: i, price: buyPrice, qty });
                }
            } else if (inPosition && signal.sell) {
                const sellPrice = data[i].close * (1 - settings.commission - settings.slippage);
                const proceeds = shares * sellPrice;
                cash += proceeds;
                
                const lastBuy = trades[trades.length - 1];
                trades.push({ 
                    type: 'sell', 
                    index: i, 
                    price: sellPrice, 
                    qty: shares,
                    profit: proceeds - (lastBuy.qty * lastBuy.price)
                });
                
                shares = 0;
                inPosition = false;
            }
        }
        
        // Close final position if still open
        if (inPosition) {
            const finalPrice = data[data.length - 1].close * (1 - settings.commission - settings.slippage);
            const proceeds = shares * finalPrice;
            cash += proceeds;
            
            const lastBuy = trades[trades.length - 1];
            trades.push({ 
                type: 'sell', 
                index: data.length - 1, 
                price: finalPrice, 
                qty: shares,
                profit: proceeds - (lastBuy.qty * lastBuy.price)
            });
        }
        
        const totalReturn = (cash - settings.capital) / settings.capital;
        const winningTrades = trades.filter(t => t.type === 'sell' && t.profit > 0).length;
        const totalTrades = trades.filter(t => t.type === 'sell').length;
        const winRate = totalTrades > 0 ? winningTrades / totalTrades : 0;
        
        return {
            finalCapital: cash,
            totalReturn: totalReturn,
            trades: trades,
            winRate: winRate,
            totalTrades: totalTrades
        };
    }

    calculateSharpeRatio(result) {
        if (result.trades.length < 2) return 0;
        
        const returns = result.trades
            .filter(t => t.type === 'sell')
            .map(t => t.profit / (result.trades.find(b => b.index < t.index && b.type === 'buy')?.price * t.qty || 1));
        
        if (returns.length === 0) return 0;
        
        const avgReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
        const stdDev = Math.sqrt(returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length);
        
        return stdDev > 0 ? avgReturn / stdDev : 0;
    }

    aggregateWalkForwardResults(results) {
        const totalReturn = results.reduce((sum, r) => sum + r.testResult.totalReturn, 0);
        const avgReturn = totalReturn / results.length;
        
        const allWinRates = results.map(r => r.testResult.winRate);
        const avgWinRate = allWinRates.reduce((a, b) => a + b, 0) / allWinRates.length;
        
        const allTrades = results.reduce((sum, r) => sum + r.testResult.totalTrades, 0);
        
        const profitablePeriods = results.filter(r => r.testResult.totalReturn > 0).length;
        const consistency = profitablePeriods / results.length;
        
        return {
            totalReturn: totalReturn,
            avgReturn: avgReturn,
            avgWinRate: avgWinRate,
            totalTrades: allTrades,
            consistency: consistency,
            periods: results.length
        };
    }

    displayWalkForwardResults(results, aggregated) {
        let html = '<div style="font-size:11px; color:#e6edf3;">';
        html += '<h4 style="margin:0 0 8px 0; color:#58a6ff;">Walk-Forward Analysis Results</h4>';
        
        html += '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:4px; margin-bottom:8px;">';
        html += `<div style="background:#21262d; padding:4px; border-radius:3px;">
            <span style="color:#a8d5ff; font-size:10px;">Total Return:</span>
            <span style="color:#e6edf3; font-weight:600;">${(aggregated.totalReturn * 100).toFixed(2)}%</span>
        </div>`;
        html += `<div style="background:#21262d; padding:4px; border-radius:3px;">
            <span style="color:#a8d5ff; font-size:10px;">Avg Return/Period:</span>
            <span style="color:#e6edf3; font-weight:600;">${(aggregated.avgReturn * 100).toFixed(2)}%</span>
        </div>`;
        html += `<div style="background:#21262d; padding:4px; border-radius:3px;">
            <span style="color:#a8d5ff; font-size:10px;">Avg Win Rate:</span>
            <span style="color:#e6edf3; font-weight:600;">${(aggregated.avgWinRate * 100).toFixed(1)}%</span>
        </div>`;
        html += `<div style="background:#21262d; padding:4px; border-radius:3px;">
            <span style="color:#a8d5ff; font-size:10px;">Consistency:</span>
            <span style="color:#e6edf3; font-weight:600;">${(aggregated.consistency * 100).toFixed(1)}%</span>
        </div>`;
        html += '</div>';
        
        html += '<h5 style="margin:8px 0 4px 0; color:#58a6ff; font-size:11px;">Period Details</h5>';
        html += '<div style="max-height:200px; overflow-y:auto; font-size:10px;">';
        html += '<table style="width:100%; border-collapse:collapse;">';
        html += '<tr style="background:#30363d;"><th style="padding:4px; text-align:left;">Period</th><th style="padding:4px; text-align:right;">Return</th><th style="padding:4px; text-align:right;">Win Rate</th><th style="padding:4px; text-align:right;">Trades</th></tr>';
        
        results.forEach((r, i) => {
            const rowColor = r.testResult.totalReturn >= 0 ? '#238636' : '#da3633';
            html += `<tr style="border-bottom:1px solid #30363d;">
                <td style="padding:4px;">${i + 1}</td>
                <td style="padding:4px; text-align:right; color:${rowColor};">${(r.testResult.totalReturn * 100).toFixed(2)}%</td>
                <td style="padding:4px; text-align:right;">${(r.testResult.winRate * 100).toFixed(1)}%</td>
                <td style="padding:4px; text-align:right;">${r.testResult.totalTrades}</td>
            </tr>`;
        });
        
        html += '</table></div></div>';
        
        this.singleResult.innerHTML = html;
    }
}

function initComparePanel(chartLoader) {
    console.log('initComparePanel called');
    
    // Register hindsight strategies from separate module
    if (typeof Hindsight01Strategy !== 'undefined') {
        StrategyFactory.register('hindsight_01', Hindsight01Strategy);
        console.log('Registered Hindsight-01 strategy');
    }
    if (typeof Hindsight02Strategy !== 'undefined') {
        StrategyFactory.register('hindsight_02', Hindsight02Strategy);
        console.log('Registered Hindsight-02 strategy');
    }

    const yaml = (typeof jsyaml !== 'undefined' && jsyaml.load) ? jsyaml : null;
    console.log('jsyaml available:', !!yaml);
    
    const fallBack = () => {
        document.getElementById('strategy-controls').innerHTML = 'Failed to load strategy configuration.';
    };

    if (!yaml) {
        console.error('js-yaml library not loaded');
        fallBack();
        return;
    }

    console.log('Fetching ssot.ui.yml...');
    fetch('ssot.ui.yml')
        .then(response => {
            console.log('Fetch response status:', response.status);
            if (!response.ok) throw new Error('ssot.ui.yml not found');
            return response.text();
        })
        .then(text => {
            console.log('YAML text length:', text.length);
            console.log('YAML text preview:', text.substring(0, 200));
            const doc = yaml.load(text);
            console.log('YAML parsed, doc keys:', Object.keys(doc || {}));
            if (!doc || !doc.strategy_panel) throw new Error('strategy_panel not found in ssot.ui.yml');
            console.log('Creating StrategyPanel...');
            const panel = new StrategyPanel(chartLoader, doc.strategy_panel);
            console.log('Initializing StrategyPanel...');
            panel.init();
        })
        .catch(error => {
            console.error('Strategy panel init failed:', error);
            console.error('Error details:', error.message, error.stack);
            fallBack();
        });
}
