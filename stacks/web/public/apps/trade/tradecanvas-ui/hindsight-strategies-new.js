// Hindsight Strategy Implementations
// Extracted for easier debugging and testing
// Version 1

/**
 * Hindsight-01 Strategy (Peak/Valley Detection with Future Knowledge)
 * Finds ALL significant local minima and maxima using complete future knowledge
 * Captures every meaningful reversal regardless of time window
 */
class Hindsight01Strategy extends Strategy {
    constructor(parameters = { buy_points: [], sell_points: [], auto_detect: true, min_change_pct: 0.01 }) {
        super("Hindsight-01", parameters);
        this.data = null;
        this.minChangePct = parameters.min_change_pct || 0.01; // 1% minimum price change
        this.updatePoints(parameters);
    }

    updatePoints(parameters) {
        this.buyPoints = parameters.buy_points || [];
        this.sellPoints = parameters.sell_points || [];
        this.autoDetect = parameters.auto_detect !== false;
        this.minChangePct = parameters.min_change_pct || 0.01;
        
        if (this.data && this.autoDetect) {
            this.autoDetectPoints();
        }
    }

    autoDetectPoints() {
        if (!this.data || this.data.length === 0) return;

        console.log(`Processing ${this.data.length} data points for Hindsight-01 (peak/valley detection with future knowledge, min change: ${(this.minChangePct * 100).toFixed(1)}%)...`);

        const buyPoints = [];
        const sellPoints = [];
        const minChangePct = this.minChangePct;
        
        // Find all local minima and maxima using future knowledge
        for (let i = 1; i < this.data.length - 1; i++) {
            const currentPrice = this.data[i].close;
            
            // Look backwards to find if this is a local minimum
            let isLocalMin = true;
            let lookbackMin = Math.max(0, i - 5); // Look back up to 5 days
            for (let j = lookbackMin; j < i; j++) {
                if (this.data[j].close <= currentPrice) {
                    isLocalMin = false;
                    break;
                }
            }
            
            // Look forwards to find if this is a local minimum
            if (isLocalMin) {
                let lookforwardMax = Math.min(this.data.length - 1, i + 5); // Look forward up to 5 days
                for (let j = i + 1; j <= lookforwardMax; j++) {
                    if (this.data[j].close <= currentPrice) {
                        isLocalMin = false;
                        break;
                    }
                }
            }
            
            // Look backwards to find if this is a local maximum
            let isLocalMax = true;
            for (let j = lookbackMin; j < i; j++) {
                if (this.data[j].close >= currentPrice) {
                    isLocalMax = false;
                    break;
                }
            }
            
            // Look forwards to find if this is a local maximum
            if (isLocalMax) {
                let lookforwardMax = Math.min(this.data.length - 1, i + 5);
                for (let j = i + 1; j <= lookforwardMax; j++) {
                    if (this.data[j].close >= currentPrice) {
                        isLocalMax = false;
                        break;
                    }
                }
            }
            
            // For local minima, check if price goes up significantly in the future
            if (isLocalMin) {
                let maxFuturePrice = currentPrice;
                let maxFutureIndex = i;
                for (let j = i + 1; j < this.data.length; j++) {
                    if (this.data[j].close > maxFuturePrice) {
                        maxFuturePrice = this.data[j].close;
                        maxFutureIndex = j;
                    }
                }
                
                const priceChange = (maxFuturePrice - currentPrice) / currentPrice;
                if (priceChange >= minChangePct) {
                    buyPoints.push(i);
                }
            }
            
            // For local maxima, check if price goes down significantly in the future
            if (isLocalMax) {
                let minFuturePrice = currentPrice;
                let minFutureIndex = i;
                for (let j = i + 1; j < this.data.length; j++) {
                    if (this.data[j].close < minFuturePrice) {
                        minFuturePrice = this.data[j].close;
                        minFutureIndex = j;
                    }
                }
                
                const priceChange = (currentPrice - minFuturePrice) / currentPrice;
                if (priceChange >= minChangePct) {
                    sellPoints.push(i);
                }
            }
        }

        this.buyPoints = buyPoints;
        this.sellPoints = sellPoints;

        console.log(`Hindsight-01: ${this.buyPoints.length} buy points, ${this.sellPoints.length} sell points (peak/valley detection with future knowledge)`);
    }

    calculateIndicators(data) {
        this.data = data;
        if (this.autoDetect) {
            this.autoDetectPoints();
        }
        return { 
            buyPoints: this.buyPoints,
            sellPoints: this.sellPoints
        };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators) || !this.data) return { buy: false, sell: false };
        
        if (this.buyPoints.includes(i)) {
            return { buy: true, sell: false };
        }
        
        if (this.sellPoints.includes(i)) {
            return { buy: false, sell: true };
        }
        
        return { buy: false, sell: false };
    }
}

/**
 * Hindsight-02 Strategy (Sensitive)
 * Uses day-by-day trend detection for more trading opportunities
 */
class Hindsight02Strategy extends Strategy {
    constructor(parameters = { buy_points: [], sell_points: [], auto_detect: true }) {
        super("Hindsight-02", parameters);
        this.data = null;
        this.updatePoints(parameters);
    }

    updatePoints(parameters) {
        this.buyPoints = parameters.buy_points || [];
        this.sellPoints = parameters.sell_points || [];
        this.autoDetect = parameters.auto_detect !== false;
        
        if (this.data && this.autoDetect) {
            this.autoDetectPoints();
        }
    }

    autoDetectPoints() {
        if (!this.data || this.data.length === 0) return;

        console.log(`Processing ${this.data.length} data points for Hindsight-02 (sensitive detection)...`);

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

        console.log(`Hindsight-02: ${this.buyPoints.length} buy points, ${this.sellPoints.length} sell points`);
    }

    calculateIndicators(data) {
        this.data = data;
        if (this.autoDetect) {
            this.autoDetectPoints();
        }
        return { 
            buyPoints: this.buyPoints,
            sellPoints: this.sellPoints
        };
    }

    getSignal(i, indicators) {
        if (!this.isValidIndex(i, indicators) || !this.data) return { buy: false, sell: false };
        
        if (this.buyPoints.includes(i)) {
            return { buy: true, sell: false };
        }
        
        if (this.sellPoints.includes(i)) {
            return { buy: false, sell: true };
        }
        
        return { buy: false, sell: false };
    }
}

