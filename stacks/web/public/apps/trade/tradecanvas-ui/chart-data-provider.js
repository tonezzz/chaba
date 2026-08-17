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
    }

    async loadData(symbol, timeframe) {
        console.log('Loading data for', symbol);

        // Try the Trade API first.
        try {
            const apiUrl = `/apps/trade/api/ui/chart-data/${symbol}?timeframe=${timeframe.toLowerCase()}`;
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
