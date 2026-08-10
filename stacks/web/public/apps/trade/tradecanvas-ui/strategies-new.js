// Modular Strategy System
// Base Strategy class and concrete strategy implementations
// Version 13

/**
 * Base Strategy class - abstract class for trading strategies
 */
class Strategy {
    constructor(name, parameters = {}) {
        if (this.constructor === Strategy) {
            throw new Error("Abstract class Strategy cannot be instantiated directly");
        }
        this.name = name;
        this.parameters = parameters;
    }

    /**
     * Calculate technical indicators for the strategy
     * @param {Array} data - Array of OHLC data objects
     * @returns {Object} Object containing calculated indicators
     */
    calculateIndicators(data) {
        throw new Error("Method calculateIndicators() must be implemented");
    }

    /**
     * Generate trading signals based on indicators
     * @param {number} i - Current index in data
     * @param {Object} indicators - Calculated indicators
     * @returns {Object} Signal object with buy/sell boolean flags
     */
    getSignal(i, indicators) {
        throw new Error("Method getSignal() must be implemented");
    }

    /**
     * Validate if signal can be generated at current index
     * @param {number} i - Current index
     * @param {Object} indicators - Calculated indicators
     * @returns {boolean} True if signal generation is valid
     */
    isValidIndex(i, indicators) {
        return i > 0 && indicators !== null;
    }

    /**
     * Set data for strategies that need access to raw data
     * @param {Array} data - Array of OHLC data objects
     */
    setData(data) {
        // Default implementation - override if needed
        this.data = data;
    }
}

/**
 * SMA Crossover Strategy
 */
class SMACrossoverStrategy extends Strategy {
    constructor(parameters = { short_period: 20, long_period: 50 }) {
        super("SMA Crossover", parameters);
    }

    calculateIndicators(data) {
        return {
            short: this.calculateSMA(data, this.parameters.short_period),
            long: this.calculateSMA(data, this.parameters.long_period)
        };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators)) return { buy: false, sell: false };
        
        const prev = i - 1;
        const s = indicators.short;
        const l = indicators.long;

        if (s[i] == null || s[prev] == null || l[i] == null || l[prev] == null) {
            return { buy: false, sell: false };
        }

        return {
            buy: s[i] > l[i] && s[prev] <= l[prev],
            sell: s[i] < l[i] && s[prev] >= l[prev]
        };
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
}

/**
 * EMA Crossover Strategy
 */
class EMACrossoverStrategy extends Strategy {
    constructor(parameters = { short_period: 12, long_period: 26 }) {
        super("EMA Crossover", parameters);
    }

    calculateIndicators(data) {
        return {
            short: this.calculateEMA(data, this.parameters.short_period),
            long: this.calculateEMA(data, this.parameters.long_period)
        };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators)) return { buy: false, sell: false };
        
        const prev = i - 1;
        const s = indicators.short;
        const l = indicators.long;

        if (s[i] == null || s[prev] == null || l[i] == null || l[prev] == null) {
            return { buy: false, sell: false };
        }

        return {
            buy: s[i] > l[i] && s[prev] <= l[prev],
            sell: s[i] < l[i] && s[prev] >= l[prev]
        };
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
}

/**
 * RSI Reversal Strategy
 */
class RSIReversalStrategy extends Strategy {
    constructor(parameters = { period: 14, oversold: 30, overbought: 70 }) {
        super("RSI Reversal", parameters);
    }

    calculateIndicators(data) {
        return { rsi: this.calculateRSI(data, this.parameters.period) };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators)) return { buy: false, sell: false };
        
        const prev = i - 1;
        const r = indicators.rsi;

        if (r[i] == null || r[prev] == null) return { buy: false, sell: false };

        return {
            buy: r[i] <= this.parameters.oversold && r[prev] > this.parameters.oversold,
            sell: r[i] >= this.parameters.overbought && r[prev] < this.parameters.overbought
        };
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
}

/**
 * MACD Crossover Strategy
 */
class MACDCrossoverStrategy extends Strategy {
    constructor(parameters = { fast: 12, slow: 26, signal: 9 }) {
        super("MACD Crossover", parameters);
    }

    calculateIndicators(data) {
        const ema12 = this.calculateEMA(data, this.parameters.fast);
        const ema26 = this.calculateEMA(data, this.parameters.slow);
        const macd = ema12.map((v, i) => v - ema26[i]);
        const signal = this.calculateEMARaw(macd, this.parameters.signal);
        return { macd, signal };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators)) return { buy: false, sell: false };
        
        const prev = i - 1;
        const m = indicators.macd;
        const s = indicators.signal;

        if (m[i] == null || m[prev] == null || s[i] == null || s[prev] == null) {
            return { buy: false, sell: false };
        }

        return {
            buy: m[i] > s[i] && m[prev] <= s[prev],
            sell: m[i] < s[i] && m[prev] >= s[prev]
        };
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
}

/**
 * Bollinger Reversion Strategy
 */
class BollingerReversionStrategy extends Strategy {
    constructor(parameters = { period: 20, std_dev: 2.0 }) {
        super("Bollinger Reversion", parameters);
        this.data = null;
    }

    calculateIndicators(data) {
        // Store data reference for signal generation
        this.data = data;
        return this.calculateBollingerBands(data, this.parameters.period, this.parameters.std_dev);
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators) || !this.data) return { buy: false, sell: false };
        
        const prev = i - 1;
        const u = indicators.upper;
        const l = indicators.lower;

        if (u[i] == null || u[prev] == null || l[i] == null || l[prev] == null) {
            return { buy: false, sell: false };
        }

        return {
            buy: this.data[i].close <= l[i] && this.data[prev].close > l[prev],
            sell: this.data[i].close >= u[i] && this.data[prev].close < u[prev]
        };
    }

    setData(data) {
        this.data = data;
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

    calculateSMA(data, period) {
        const out = new Array(data.length).fill(null);
        for (let i = period - 1; i < data.length; i++) {
            let sum = 0;
            for (let j = i - period + 1; j <= i; j++) sum += data[j].close;
            out[i] = sum / period;
        }
        return out;
    }
}

/**
 * Manual Perfect Strategy (God Mode)
 * Allows manual definition of perfect buy/sell points for maximum profit analysis
 * Can also auto-detect all local minima/maxima for truly perfect hindsight trading
 */
class ManualPerfectStrategy extends Strategy {
    constructor(parameters = { buy_points: [], sell_points: [], auto_detect: false, algorithm: 'sensitive' }) {
        super("Perfect", parameters);
        this.data = null;
        // Update points when parameters change
        this.updatePoints(parameters);
    }

    updatePoints(parameters) {
        this.buyPoints = parameters.buy_points || [];
        this.sellPoints = parameters.sell_points || [];
        this.autoDetect = parameters.auto_detect || false;
        this.algorithm = parameters.algorithm || 'sensitive';
        
        // Always auto-detect if we have data (Perfect strategy always runs detection)
        if (this.data) {
            this.autoDetectPoints();
        }
    }

    autoDetectPoints() {
        if (!this.data || this.data.length === 0) return;

        if (this.algorithm === 'sensitive') {
            this.autoDetectSensitive();
        } else if (this.algorithm === 'conservative') {
            this.autoDetectConservative();
        }
    }

    autoDetectSensitive() {
        console.log(`Processing ${this.data.length} data points for auto-detection using sensitive trend algorithm...`);

        // Sensitive algorithm: detect trend changes day by day
        const buyPoints = [];
        const sellPoints = [];
        
        let mode = 'BUYING';
        let trendDirection = null;
        let lowestPrice = Infinity;
        let lowestIndex = -1;
        let highestPrice = -Infinity;
        let highestIndex = -1;
        
        for (let i = 0; i < this.data.length; i++) {
            let currentTrend = trendDirection;
            if (i < this.data.length - 1) {
                if (this.data[i].close < this.data[i + 1].close) {
                    currentTrend = 'up';
                } else if (this.data[i].close > this.data[i + 1].close) {
                    currentTrend = 'down';
                }
            }

            const trendChanged = (trendDirection !== null && currentTrend !== null && currentTrend !== trendDirection);

            if (mode === 'BUYING') {
                if (this.data[i].close < lowestPrice) {
                    lowestPrice = this.data[i].close;
                    lowestIndex = i;
                }

                if (trendChanged && trendDirection === 'down' && currentTrend === 'up') {
                    buyPoints.push(lowestIndex);
                    mode = 'SELLING';
                    highestPrice = this.data[i].close;
                    highestIndex = i;
                    lowestPrice = Infinity;
                }
            } else if (mode === 'SELLING') {
                if (this.data[i].close > highestPrice) {
                    highestPrice = this.data[i].close;
                    highestIndex = i;
                }

                if (trendChanged && trendDirection === 'up' && currentTrend === 'down') {
                    sellPoints.push(highestIndex);
                    mode = 'BUYING';
                    lowestPrice = this.data[i].close;
                    lowestIndex = i;
                    highestPrice = -Infinity;
                }
            }

            trendDirection = currentTrend;
        }

        if (mode === 'SELLING' && highestIndex !== -1) {
            sellPoints.push(highestIndex);
        } else if (mode === 'BUYING' && lowestIndex !== -1) {
            buyPoints.push(lowestIndex);
        }

        this.buyPoints = buyPoints;
        this.sellPoints = sellPoints;

        console.log(`Auto-detected ${this.buyPoints.length} buy points and ${this.sellPoints.length} sell points using sensitive trend algorithm`);
    }

    autoDetectConservative() {
        console.log(`Processing ${this.data.length} data points for auto-detection using 3-point trend confirmation...`);

        // Conservative algorithm: uses 3-point confirmation
        const buyPoints = [];
        const sellPoints = [];
        
        let currentTrend = null;
        let trendStartIndex = 0;
        let lowestPrice = Infinity;
        let lowestIndex = -1;
        let highestPrice = -Infinity;
        let highestIndex = -1;
        
        for (let i = 2; i < this.data.length; i++) {
            const p1 = this.data[i - 2].close;
            const p2 = this.data[i - 1].close;
            const p3 = this.data[i].close;
            
            let newTrend = currentTrend;
            if (p1 < p2 && p2 < p3) {
                newTrend = 'up';
            } else if (p1 > p2 && p2 > p3) {
                newTrend = 'down';
            }
            
            if (currentTrend === 'down' || currentTrend === null) {
                if (p2 < lowestPrice) {
                    lowestPrice = p2;
                    lowestIndex = i - 1;
                }
                if (p3 < lowestPrice) {
                    lowestPrice = p3;
                    lowestIndex = i;
                }
            }
            
            if (currentTrend === 'up' || currentTrend === null) {
                if (p2 > highestPrice) {
                    highestPrice = p2;
                    highestIndex = i - 1;
                }
                if (p3 > highestPrice) {
                    highestPrice = p3;
                    highestIndex = i;
                }
            }
            
            if (currentTrend !== null && newTrend !== null && newTrend !== currentTrend) {
                if (currentTrend === 'down' && newTrend === 'up') {
                    if (lowestIndex !== -1) {
                        buyPoints.push(lowestIndex);
                    }
                    highestPrice = p3;
                    highestIndex = i;
                    lowestPrice = Infinity;
                    lowestIndex = -1;
                } else if (currentTrend === 'up' && newTrend === 'down') {
                    if (highestIndex !== -1) {
                        sellPoints.push(highestIndex);
                    }
                    lowestPrice = p3;
                    lowestIndex = i;
                    highestPrice = -Infinity;
                    highestIndex = -1;
                }
                trendStartIndex = i;
            }
            
            currentTrend = newTrend;
        }
        
        if (currentTrend === 'down' && lowestIndex !== -1) {
            buyPoints.push(lowestIndex);
        } else if (currentTrend === 'up' && highestIndex !== -1) {
            sellPoints.push(highestIndex);
        }

        this.buyPoints = buyPoints;
        this.sellPoints = sellPoints;

        console.log(`Auto-detected ${this.buyPoints.length} buy points and ${this.sellPoints.length} sell points using 3-point trend confirmation`);
    }

    filterConsecutive(points, minGap) {
        if (points.length === 0) return [];
        
        const filtered = [points[0]];
        for (let i = 1; i < points.length; i++) {
            if (points[i] - filtered[filtered.length - 1] >= minGap) {
                filtered.push(points[i]);
            }
        }
        return filtered;
    }

    // Legacy method - not used in new auto-detect logic
    // Kept for backward compatibility if needed

    calculateIndicators(data) {
        // Store data reference for signal generation
        this.data = data;
        
        // Always auto-detect for Perfect strategy (clears and re-detects on every run)
        this.autoDetectPoints();
        
        // For manual strategy, we don't calculate technical indicators
        // We use the predefined buy/sell points
        return { 
            buyPoints: this.buyPoints,
            sellPoints: this.sellPoints
        };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators) || !this.data) return { buy: false, sell: false };
        
        // Check if current index is a buy point
        if (this.buyPoints.includes(i)) {
            return { buy: true, sell: false };
        }
        
        // Check if current index is a sell point
        if (this.sellPoints.includes(i)) {
            return { buy: false, sell: true };
        }
        
        return { buy: false, sell: false };
    }

    setData(data) {
        this.data = data;
        // If auto-detect is enabled, recalculate points when data changes
        if (this.autoDetect) {
            this.autoDetectPoints();
        }
    }

    addBuyPoint(index) {
        if (!this.buyPoints.includes(index)) {
            this.buyPoints.push(index);
            this.buyPoints.sort((a, b) => a - b);
        }
    }

    addSellPoint(index) {
        if (!this.sellPoints.includes(index)) {
            this.sellPoints.push(index);
            this.sellPoints.sort((a, b) => a - b);
        }
    }

    removeBuyPoint(index) {
        this.buyPoints = this.buyPoints.filter(i => i !== index);
    }

    removeSellPoint(index) {
        this.sellPoints = this.sellPoints.filter(i => i !== index);
    }

    clearPoints() {
        this.buyPoints = [];
        this.sellPoints = [];
    }

    getPoints() {
        return {
            buyPoints: [...this.buyPoints],
            sellPoints: [...this.sellPoints]
        };
    }
}

/**
 * Strategy Factory - creates strategy instances from configuration
 */
class StrategyFactory {
    static strategies = {
        'sma_crossover': SMACrossoverStrategy,
        'ema_crossover': EMACrossoverStrategy,
        'rsi_reversal': RSIReversalStrategy,
        'macd_crossover': MACDCrossoverStrategy,
        'bollinger_reversion': BollingerReversionStrategy,
        'manual_perfect': ManualPerfectStrategy
        // Hindsight strategies will be registered dynamically
    };

    static create(key, parameters) {
        const StrategyClass = this.strategies[key];
        if (!StrategyClass) {
            throw new Error(`Unknown strategy key: ${key}`);
        }
        return new StrategyClass(parameters);
    }

    static register(key, strategyClass) {
        this.strategies[key] = strategyClass;
    }

    static getAvailableStrategies() {
        return Object.keys(this.strategies);
    }
}
