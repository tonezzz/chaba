// Hindsight Strategy Implementations
// Extracted for easier debugging and testing
// Version 1

// Ensure Strategy class is available before defining these strategies
if (typeof Strategy === 'undefined') {
    console.error('Strategy class not available. Ensure strategies.js is loaded before hindsight-strategies.js');
} else {

/**
 * Hindsight-01 Strategy (Conservative)
 * Uses 3-point trend confirmation for fewer but higher-quality trades
 */
class Hindsight01Strategy extends Strategy {
    constructor(parameters = { buy_points: [], sell_points: [], auto_detect: true }) {
        super("Hindsight-01", parameters);
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

        console.log(`Processing ${this.data.length} data points for Hindsight-01 (3-point confirmation)...`);

        const buyPoints = [];
        const sellPoints = [];
        
        let currentTrend = null;
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

        console.log(`Hindsight-01: ${this.buyPoints.length} buy points, ${this.sellPoints.length} sell points`);
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

} // End of Strategy class availability check
