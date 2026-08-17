// Chart Data Provider for TradeCanvas
// Fetches and normalizes chart data from the Trade API, CSV files, or sample data.

class ChartDataProvider {
    constructor(options = {}) {
        this.basePrices = options.basePrices || {
            'THB': 35.5,
            'EUR': 1.08,
            'GBP': 1.27,
            'JPY': 155.0,
            'GOLD': 4401.94,
            'DXY': 105.0,
            'OIL': 75.0
        };

        this.symbolFiles = {
            'THB': 'thb_formatted.csv',
            'EUR': 'eur_formatted.csv',
            'GBP': 'gbp_formatted.csv',
            'JPY': 'jpy_formatted.csv',
            'GOLD': 'gold_formatted.csv',
            'DXY': 'dxy_formatted.csv',
            'OIL': 'wti_formatted.csv'
        };

        this.currencyPairs = {
            'THB': { base: 'USD', quote: 'THB' },
            'EUR': { base: 'EUR', quote: 'USD' },
            'GBP': { base: 'GBP', quote: 'USD' },
            'JPY': { base: 'USD', quote: 'JPY' }
        };
    }

    async loadData(symbol, timeframe) {
        console.log('Loading data for', symbol);

        // Try the Trade API first.
        try {
            const apiUrl = `http://100.75.102.88:9000/api/ui/chart-data/${symbol}?timeframe=${timeframe.toLowerCase()}`;
            console.log('Fetching from API:', apiUrl);

            const response = await fetch(apiUrl);
            if (response.ok) {
                const apiData = await response.json();
                console.log('Loaded data from API:', apiData.data.length, 'points');
                console.log('Last updated:', apiData.last_updated);
                return { data: apiData.data, isSampleData: false, loadedFromAPI: true };
            } else {
                console.log('API not available, falling back to CSV');
            }
        } catch (error) {
            console.log('API loading error, falling back to CSV:', error.message);
        }

        // Try Frankfurter for supported currency pairs.
        if (this.currencyPairs[symbol]) {
            try {
                const fxData = await this.fetchFromFrankfurter(symbol, timeframe);
                if (fxData && fxData.length > 0) {
                    console.log('Loaded data from Frankfurter for', symbol);
                    return { data: fxData, isSampleData: false, loadedFromAPI: true };
                }
            } catch (error) {
                console.log('Frankfurter loading error, falling back to CSV:', error.message);
            }
        }

        // Fall back to the corresponding CSV file.
        const csvData = await this.loadFromCSV(symbol, timeframe);
        if (csvData && csvData.length > 0) {
            return { data: csvData, isSampleData: false, loadedFromAPI: false };
        }

        // Last resort: generate sample data for the symbol.
        console.log('CSV not available, using sample data');
        return {
            data: this.generateSampleData(symbol, timeframe),
            isSampleData: true,
            loadedFromAPI: false
        };
    }

    async fetchFromFrankfurter(symbol, timeframe) {
        const pair = this.currencyPairs[symbol];
        if (!pair) {
            console.log('No Frankfurter pair mapping for', symbol);
            return [];
        }

        const endDate = new Date();
        const startDate = this.calculateStartDate(endDate, timeframe);
        const startStr = startDate.toISOString().split('T')[0];
        const endStr = endDate.toISOString().split('T')[0];

        const url = `https://api.frankfurter.app/${startStr}..${endStr}?from=${pair.base}&to=${pair.quote}`;
        console.log('Fetching from Frankfurter:', url);

        const response = await fetch(url);
        if (!response.ok) {
            console.log('Frankfurter request failed:', response.status);
            return [];
        }

        const json = await response.json();
        const rates = json.rates;
        if (!rates) {
            console.log('Frankfurter response missing rates');
            return [];
        }

        const dates = Object.keys(rates).sort();
        const data = [];
        let previousClose = null;

        for (const date of dates) {
            const close = parseFloat(rates[date][pair.quote]);
            if (isNaN(close)) {
                continue;
            }

            const open = previousClose !== null ? previousClose : close;
            const range = Math.abs(close - open) * 0.2 + close * 0.001;
            const high = Math.max(open, close) + range;
            const low = Math.min(open, close) - range;

            const timestamp = Math.floor(new Date(date + 'T00:00:00Z').getTime() / 1000);

            data.push({
                time: timestamp,
                open: open,
                high: high,
                low: low,
                close: close
            });

            previousClose = close;
        }

        console.log('Loaded data from Frankfurter:', data.length, 'points');
        return data;
    }

    async loadFromCSV(symbol, timeframe) {
        const csvFile = this.symbolFiles[symbol];
        if (!csvFile) {
            console.log('No CSV file for symbol:', symbol);
            return [];
        }

        const csvUrl = `../data/imported/${csvFile}`;
        console.log('Fetching CSV from:', csvUrl);

        try {
            const response = await fetch(csvUrl);
            if (!response.ok) {
                console.log('CSV not available:', csvUrl);
                return [];
            }

            const csvText = await response.text();
            const data = this.parseCSV(csvText, timeframe);
            console.log('Loaded data from CSV:', data.length, 'points');
            return data;
        } catch (error) {
            console.log('CSV loading error:', error.message);
            return [];
        }
    }

    async validateDataPath(symbol) {
        const pair = this.currencyPairs[symbol];
        if (pair) {
            const url = `https://api.frankfurter.app/latest?from=${pair.base}&to=${pair.quote}`;
            try {
                const response = await fetch(url);
                if (response.ok) {
                    console.log('Validated currency data path for', symbol, 'via Frankfurter:', url);
                    return { valid: true, source: 'frankfurter', url };
                }
                console.log('Currency data path validation failed for', symbol, ':', response.status);
                return { valid: false, source: 'frankfurter', status: response.status };
            } catch (error) {
                console.log('Currency data path validation error for', symbol, ':', error.message);
                return { valid: false, source: 'frankfurter', error: error.message };
            }
        }

        const csvFile = this.symbolFiles[symbol];
        if (csvFile) {
            const csvUrl = `../data/imported/${csvFile}`;
            try {
                const response = await fetch(csvUrl);
                if (response.ok) {
                    console.log('Validated commodity data path for', symbol, 'via CSV:', csvUrl);
                    return { valid: true, source: 'csv', url: csvUrl };
                }
                console.log('Commodity data path validation failed for', symbol, ':', csvUrl, response.status);
                return { valid: false, source: 'csv', status: response.status, note: 'will fall back to sample data' };
            } catch (error) {
                console.log('Commodity data path validation error for', symbol, ':', csvUrl, error.message);
                return { valid: false, source: 'csv', error: error.message, note: 'will fall back to sample data' };
            }
        }

        console.log('No known data path for symbol:', symbol);
        return { valid: false, source: 'none' };
    }

    parseCSV(csvText, timeframe) {
        const lines = csvText.trim().split('\n');
        if (lines.length < 2) {
            console.warn('CSV has no data rows');
            return [];
        }

        const headers = lines[0].split(',');
        const data = [];

        const dateIndex = headers.indexOf('date');
        const openIndex = headers.indexOf('open_price');
        const highIndex = headers.indexOf('high_price');
        const lowIndex = headers.indexOf('low_price');
        const closeIndex = headers.indexOf('close_price');

        if (dateIndex === -1 || openIndex === -1 || highIndex === -1 || lowIndex === -1 || closeIndex === -1) {
            console.warn('CSV missing required columns');
            return [];
        }

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

        // Filter by timeframe if needed.
        if (timeframe !== 'all') {
            const endTime = Math.floor(Date.now() / 1000);
            const startTime = this.calculateStartDate(new Date(endTime * 1000), timeframe);
            const startTimestamp = Math.floor(startTime.getTime() / 1000);

            const filtered = data.filter(point => point.time >= startTimestamp && point.time <= endTime);
            if (filtered.length >= 5) {
                return filtered;
            }

            const fallback = data.slice(-5);
            console.log('Short timeframe has', filtered.length, 'points; falling back to', fallback.length, 'recent points');
            return fallback;
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
                startDate.setFullYear(1980);
                break;
            default:
                startDate.setFullYear(startDate.getFullYear() - 1);
        }
        return startDate;
    }

    generateSampleData(symbol, timeframe) {
        const basePrice = this.basePrices[symbol] || 100.0;
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
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartDataProvider;
}
