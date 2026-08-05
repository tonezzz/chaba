// Strategy engine for the Compare page backtest panel
// Loads ssot.ui.yml and lets the user run a quick client-side backtest
// against the data already loaded by ChartLoader.

class StrategyPanel {
    constructor(chartLoader, config) {
        this.chartLoader = chartLoader;
        this.config = config;
        this.data = chartLoader.data || [];
        this.controlsContainer = document.getElementById('strategy-controls');
        this.resultContainer = document.getElementById('strategy-results');
    }

    init() {
        window.runAllBacktest = this.runAll.bind(this);
        this.buildControls();
        this.resultContainer.innerHTML = '<div id="single-result" style="margin-bottom:10px;"><p style="color:#8b949e; font-size:13px; margin-top:6px;">Click "Run Backtest" or "Run All" to see results.</p></div><div id="compare-table"></div>';
        this.singleResult = document.getElementById('single-result');
        this.compareTable = document.getElementById('compare-table');
        this.backtests = [];
    }

    buildControls() {
        const strategies = this.config.strategies;

        let html = '<div class="setting-group" style="margin-bottom:10px;">';
        html += '<label>Strategy:</label>';
        html += '<select id="strategy-select" class="selector">';
        for (const [key, strat] of Object.entries(strategies)) {
            html += `<option value="${key}" ${strat.enabled ? 'selected' : ''}>${strat.label}</option>`;
        }
        html += '</select></div>';

        html += '<div id="strategy-params" style="margin-bottom:10px;"></div>';

        const exec = this.config.execution;
        html += this.numberInput('Capital', 'strategy-capital', exec.initial_capital, 1);
        html += this.numberInput('Position %', 'strategy-position', exec.position_sizing.value, 0.01);
        html += this.numberInput('Stop %', 'strategy-stop', exec.stop_loss.value, 0.001);
        html += this.numberInput('Take Profit %', 'strategy-tp', exec.take_profit.value, 0.001);
        html += this.numberInput('Commission', 'strategy-commission', exec.commission, 0.0001);
        html += this.numberInput('Slippage', 'strategy-slippage', exec.slippage, 0.0001);

        html += '<button id="run-backtest" class="btn" style="width:100%; margin-top:10px;">Run Backtest</button>';
        html += '<button id="run-all" class="btn" style="width:100%; margin-top:6px;" onclick="window.runAllBacktest()">Run All & Compare</button>';

        this.controlsContainer.innerHTML = html;

        document.getElementById('strategy-select').addEventListener('change', () => this.renderParams());
        this.renderParams();
        document.getElementById('run-backtest').addEventListener('click', () => this.runBacktest());
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
        let html = '<div style="display:flex; flex-direction:column; gap:6px;">';
        for (const [pkey, pval] of Object.entries(strat.parameters)) {
            html += `<div class="setting-group">
                <label>${pkey}:</label>
                <input type="number" class="strategy-param" data-key="${pkey}" step="any" value="${pval}">
            </div>`;
        }
        html += '</div>';
        container.innerHTML = html;
    }

    getSelected() {
        const key = document.getElementById('strategy-select').value;
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

        const { result, metrics } = this.runStrategy(key, params, settings);
        this.updateResults(metrics);
        this.addBacktest(key, params, settings, result, metrics);
        this.renderComparisonTable();

        if (this.config.display.show_chart_markers && this.chartLoader.candlestickSeries) {
            this.setMarkers(result.trades);
        }
    }

    getIndicators(key, params) {
        switch (key) {
            case 'sma_crossover':
                return {
                    short: this.calculateSMA(this.data, params.short_period),
                    long: this.calculateSMA(this.data, params.long_period)
                };
            case 'ema_crossover':
                return {
                    short: this.calculateEMA(this.data, params.short_period),
                    long: this.calculateEMA(this.data, params.long_period)
                };
            case 'rsi_reversal':
                return { rsi: this.calculateRSI(this.data, params.period) };
            case 'macd_crossover': {
                const ema12 = this.calculateEMA(this.data, params.fast);
                const ema26 = this.calculateEMA(this.data, params.slow);
                const macd = ema12.map((v, i) => v - ema26[i]);
                const signal = this.calculateEMARaw(macd, params.signal);
                return { macd, signal };
            }
            case 'bollinger_reversion':
                return this.calculateBollingerBands(this.data, params.period, params.std_dev);
            default:
                return {};
        }
    }

    getSignal(i, key, params, inds) {
        const prev = i - 1;
        if (prev < 0) return { buy: false, sell: false };

        switch (key) {
            case 'sma_crossover':
            case 'ema_crossover': {
                const s = inds.short, l = inds.long;
                if (s[i] == null || s[prev] == null || l[i] == null || l[prev] == null) {
                    return { buy: false, sell: false };
                }
                return {
                    buy: s[i] > l[i] && s[prev] <= l[prev],
                    sell: s[i] < l[i] && s[prev] >= l[prev]
                };
            }
            case 'rsi_reversal': {
                const r = inds.rsi;
                if (r[i] == null || r[prev] == null) return { buy: false, sell: false };
                return {
                    buy: r[i] <= params.oversold && r[prev] > params.oversold,
                    sell: r[i] >= params.overbought && r[prev] < params.overbought
                };
            }
            case 'macd_crossover': {
                const m = inds.macd, s = inds.signal;
                if (m[i] == null || m[prev] == null || s[i] == null || s[prev] == null) {
                    return { buy: false, sell: false };
                }
                return {
                    buy: m[i] > s[i] && m[prev] <= s[prev],
                    sell: m[i] < s[i] && m[prev] >= s[prev]
                };
            }
            case 'bollinger_reversion': {
                const u = inds.upper, l = inds.lower;
                if (u[i] == null || u[prev] == null || l[i] == null || l[prev] == null) {
                    return { buy: false, sell: false };
                }
                const c = this.data;
                return {
                    buy: c[i].close <= l[i] && c[prev].close > l[prev],
                    sell: c[i].close >= u[i] && c[prev].close < u[prev]
                };
            }
            default:
                return { buy: false, sell: false };
        }
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

        for (let i = 1; i < data.length; i++) {
            const equity = cash + (inPosition ? shares * data[i].close : 0);
            if (equity > maxEquity) maxEquity = equity;
            const dd = (maxEquity - equity) / maxEquity;
            if (dd > maxDrawdown) maxDrawdown = dd;

            const signal = this.getSignal(i, key, params, inds);

            if (inPosition) {
                let exitPrice = null;
                if (data[i].low <= stopPrice) exitPrice = stopPrice;
                else if (data[i].high >= tpPrice) exitPrice = tpPrice;
                else if (signal.sell) exitPrice = data[i].close;

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
                    stopPrice = buyPrice * (1 - settings.stopPct);
                    tpPrice = buyPrice * (1 + settings.tpPct);
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
            const params = { ...strat.parameters };
            const { result, metrics } = this.runStrategy(key, params, settings);
            this.addBacktest(key, params, settings, result, metrics);
        }
        this.singleResult.innerHTML = `<p style="color:#8b949e; font-size:13px; margin-top:6px;">Ran ${this.backtests.length} strategies. See comparison below.</p>`;
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
            total_return: 'Total Return %',
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
        let html = '<h4 style="margin:8px 0 4px 0; font-size:14px;">Backtest Comparison</h4>';
        html += '<div style="overflow-x:auto;"><table style="width:100%; font-size:12px; border-collapse:collapse;">';
        html += '<thead><tr style="text-align:left; border-bottom:1px solid #30363d;"><th>Strategy</th>';
        for (const key of order) {
            html += `<th style='padding:4px 6px;'>${labels[key] || key}</th>`;
        }
        html += '</tr></thead><tbody>';
        for (const b of this.backtests) {
            html += `<tr style='border-bottom:1px solid #21262d;'>`;
            html += `<td style='padding:4px 6px;'><strong>${b.label}</strong><br><span style='font-size:10px;color:#8b949e;'>${Object.entries(b.params).map(([k,v])=>`${k}=${v}`).join(', ')}</span></td>`;
            for (const key of order) {
                const v = b.metrics[key];
                const isBest = best[key] !== null && Math.abs(v - best[key]) < 1e-9;
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
                const color = isBest ? '#3fb950' : 'inherit';
                html += `<td style='padding:4px 6px; color:${color};'>${text}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';
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

    calculateSMA(data, period) {
        const out = new Array(data.length).fill(null);
        for (let i = period - 1; i < data.length; i++) {
            let sum = 0;
            for (let j = i - period + 1; j <= i; j++) sum += data[j].close;
            out[i] = sum / period;
        }
        return out;
    }

    calculateEMA(data, period) {
        const out = new Array(data.length).fill(null);
        if (data.length === 0) return out;
        const mult = 2 / (period + 1);
        out[0] = data[0].close;
        for (let i = 1; i < data.length; i++) {
            out[i] = (data[i].close - out[i - 1]) * mult + out[i - 1];
        }
        return out;
    }

    calculateEMARaw(values, period) {
        const out = new Array(values.length).fill(null);
        if (values.length === 0 || values[0] == null) return out;
        const mult = 2 / (period + 1);
        out[0] = values[0];
        for (let i = 1; i < values.length; i++) {
            if (values[i] == null) continue;
            const prev = out[i - 1] || values[i];
            out[i] = (values[i] - prev) * mult + prev;
        }
        return out;
    }

    calculateRSI(data, period) {
        const out = new Array(data.length).fill(null);
        if (data.length <= period) return out;
        let gains = 0;
        let losses = 0;
        for (let i = 1; i <= period; i++) {
            const ch = data[i].close - data[i - 1].close;
            if (ch > 0) gains += ch;
            else losses -= ch;
        }
        let avgGain = gains / period;
        let avgLoss = losses / period;

        for (let i = period; i < data.length; i++) {
            const ch = data[i].close - data[i - 1].close;
            const gain = ch > 0 ? ch : 0;
            const loss = ch < 0 ? -ch : 0;
            avgGain = (avgGain * (period - 1) + gain) / period;
            avgLoss = (avgLoss * (period - 1) + loss) / period;
            if (avgLoss === 0) {
                out[i] = 100;
            } else {
                const rs = avgGain / avgLoss;
                out[i] = 100 - (100 / (1 + rs));
            }
        }
        return out;
    }

    calculateBollingerBands(data, period, stdDev) {
        const middle = this.calculateSMA(data, period);
        const upper = new Array(data.length).fill(null);
        const lower = new Array(data.length).fill(null);
        for (let i = period - 1; i < data.length; i++) {
            const mean = middle[i];
            let sumSq = 0;
            for (let j = i - period + 1; j <= i; j++) {
                sumSq += Math.pow(data[j].close - mean, 2);
            }
            const sd = Math.sqrt(sumSq / period) * stdDev;
            upper[i] = mean + sd;
            lower[i] = mean - sd;
        }
        return { middle, upper, lower };
    }
}

function initComparePanel(chartLoader) {
    const yaml = (typeof jsyaml !== 'undefined' && jsyaml.load) ? jsyaml : null;
    const fallBack = () => {
        document.getElementById('strategy-controls').innerHTML = 'Failed to load strategy configuration.';
    };

    if (!yaml) {
        console.error('js-yaml library not loaded');
        fallBack();
        return;
    }

    fetch('ssot.ui.yml')
        .then(response => {
            if (!response.ok) throw new Error('ssot.ui.yml not found');
            return response.text();
        })
        .then(text => {
            const doc = yaml.load(text);
            if (!doc || !doc.strategy_panel) throw new Error('strategy_panel not found in ssot.ui.yml');
            const panel = new StrategyPanel(chartLoader, doc.strategy_panel);
            panel.init();
        })
        .catch(error => {
            console.error('Strategy panel init failed:', error);
            fallBack();
        });
}
