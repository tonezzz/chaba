// TradeCanvas UI Components Library
// Modular component system for reusable UI elements
// Version 1.0

/**
 * Base Component Class
 * Provides common functionality for all UI components
 */
class UIComponent {
    constructor(options = {}) {
        this.containerId = options.containerId;
        this.container = document.getElementById(this.containerId);
        this.config = options;
        this.eventHandlers = new Map();
    }

    render() {
        throw new Error('render() must be implemented by subclass');
    }

    on(event, callback) {
        if (!this.eventHandlers.has(event)) {
            this.eventHandlers.set(event, []);
        }
        this.eventHandlers.get(event).push(callback);
    }

    emit(event, data) {
        if (this.eventHandlers.has(event)) {
            this.eventHandlers.get(event).forEach(callback => callback(data));
        }
    }

    destroy() {
        if (this.container) {
            this.container.innerHTML = '';
        }
        this.eventHandlers.clear();
    }
}

/**
 * Currency Selector Component
 * Provides currency pair selection with chart integration
 */
class CurrencySelector extends UIComponent {
    constructor(options = {}) {
        super(options);
        
        // Currency configuration
        this.currencies = options.currencies || [
            { value: 'THB', label: 'USD/THB', csv: 'thb_formatted.csv' },
            { value: 'EUR', label: 'EUR/USD', csv: 'eur_formatted.csv' },
            { value: 'GBP', label: 'GBP/USD', csv: 'gbp_formatted.csv' },
            { value: 'JPY', label: 'USD/JPY', csv: 'jpy_formatted.csv' },
            { value: 'GOLD', label: 'GOLD', csv: 'gold_formatted.csv' },
            { value: 'DXY', label: 'DXY', csv: 'dxy_formatted.csv' },
            { value: 'OIL', label: 'OIL', csv: 'wti_formatted.csv' }
        ];
        
        this.selectedCurrency = options.selectedCurrency || 'THB';
        this.chartLoader = options.chartLoader || null;
        this.mode = options.mode || 'full'; // 'full' or 'compact'
        this.className = options.className || 'currency-selector';
    }

    render() {
        if (!this.container) {
            console.error('CurrencySelector container not found:', this.containerId);
            return;
        }

        const select = document.createElement('select');
        select.id = this.containerId + '-select';
        select.className = this.className;
        
        // Add currency options
        this.currencies.forEach(currency => {
            const option = document.createElement('option');
            option.value = currency.value;
            option.textContent = currency.label;
            option.selected = currency.value === this.selectedCurrency;
            select.appendChild(option);
        });

        // Event listener for currency changes
        select.addEventListener('change', (e) => {
            this.handleCurrencyChange(e.target.value);
        });

        this.container.innerHTML = '';
        this.container.appendChild(select);
        
        this.selectElement = select;
        return select;
    }

    handleCurrencyChange(newCurrency) {
        this.selectedCurrency = newCurrency;
        
        // Update chart loader if available
        if (this.chartLoader) {
            this.chartLoader.updateSymbol(newCurrency);
        }
        
        // Emit change event
        this.emit('currencyChange', { 
            currency: newCurrency,
            label: this.getCurrencyLabel(newCurrency)
        });
    }

    getCurrencyLabel(value) {
        const currency = this.currencies.find(c => c.value === value);
        return currency ? currency.label : value;
    }

    getCurrencyCSV(value) {
        const currency = this.currencies.find(c => c.value === value);
        return currency ? currency.csv : null;
    }

    setCurrency(value) {
        if (this.selectElement) {
            this.selectElement.value = value;
            this.handleCurrencyChange(value);
        }
    }

    getCurrentCurrency() {
        return this.selectedCurrency;
    }
}

/**
 * Timeframe Selector Component
 * Provides timeframe selection with chart integration
 */
class TimeframeSelector extends UIComponent {
    constructor(options = {}) {
        super(options);
        
        // Timeframe configuration
        this.timeframes = options.timeframes || [
            { value: '1D', label: '1 Day' },
            { value: '1W', label: '1 Week' },
            { value: '1M', label: '1 Month' },
            { value: '3M', label: '3 Months' },
            { value: '6M', label: '6 Months' },
            { value: '1Y', label: '1 Year' },
            { value: '2Y', label: '2 Years' },
            { value: 'all', label: 'All' }
        ];
        
        this.selectedTimeframe = options.selectedTimeframe || '1Y';
        this.chartLoader = options.chartLoader || null;
        this.className = options.className || 'timeframe-selector';
    }

    render() {
        if (!this.container) {
            console.error('TimeframeSelector container not found:', this.containerId);
            return;
        }

        const select = document.createElement('select');
        select.id = this.containerId + '-select';
        select.className = this.className;
        
        // Add timeframe options
        this.timeframes.forEach(timeframe => {
            const option = document.createElement('option');
            option.value = timeframe.value;
            option.textContent = timeframe.label;
            option.selected = timeframe.value === this.selectedTimeframe;
            select.appendChild(option);
        });

        // Event listener for timeframe changes
        select.addEventListener('change', (e) => {
            this.handleTimeframeChange(e.target.value);
        });

        this.container.innerHTML = '';
        this.container.appendChild(select);
        
        this.selectElement = select;
        return select;
    }

    handleTimeframeChange(newTimeframe) {
        this.selectedTimeframe = newTimeframe;
        
        // Update chart loader if available
        if (this.chartLoader) {
            this.chartLoader.updateTimeframe(newTimeframe);
        }
        
        // Emit change event
        this.emit('timeframeChange', { 
            timeframe: newTimeframe,
            label: this.getTimeframeLabel(newTimeframe)
        });
    }

    getTimeframeLabel(value) {
        const timeframe = this.timeframes.find(t => t.value === value);
        return timeframe ? timeframe.label : value;
    }

    setTimeframe(value) {
        if (this.selectElement) {
            this.selectElement.value = value;
            this.handleTimeframeChange(value);
        }
    }

    getCurrentTimeframe() {
        return this.selectedTimeframe;
    }
}

/**
 * Control Button Component
 * Reusable button with consistent styling and event handling
 */
class ControlButton extends UIComponent {
    constructor(options = {}) {
        super(options);
        this.label = options.label || 'Button';
        this.action = options.action || null;
        this.className = options.className || 'btn';
        this.icon = options.icon || null;
        this.disabled = options.disabled || false;
    }

    render() {
        if (!this.container) {
            console.error('ControlButton container not found:', this.containerId);
            return;
        }

        const button = document.createElement('button');
        button.className = this.className;
        button.disabled = this.disabled;
        
        if (this.icon) {
            button.innerHTML = `${this.icon} ${this.label}`;
        } else {
            button.textContent = this.label;
        }

        button.addEventListener('click', (e) => {
            if (this.action) {
                this.action(e);
            }
            this.emit('click', e);
        });

        this.container.innerHTML = '';
        this.container.appendChild(button);
        
        this.buttonElement = button;
        return button;
    }

    setLabel(label) {
        this.label = label;
        if (this.buttonElement) {
            this.buttonElement.textContent = this.icon ? `${this.icon} ${label}` : label;
        }
    }

    setDisabled(disabled) {
        this.disabled = disabled;
        if (this.buttonElement) {
            this.buttonElement.disabled = disabled;
        }
    }
}

/**
 * Status Indicator Component
 * Shows connection status with visual feedback
 */
class StatusIndicator extends UIComponent {
    constructor(options = {}) {
        super(options);
        this.status = options.status || 'disconnected'; // 'connected', 'disconnected', 'connecting'
        this.label = options.label || 'Status';
        this.className = options.className || 'status-indicator';
    }

    render() {
        if (!this.container) {
            console.error('StatusIndicator container not found:', this.containerId);
            return;
        }

        const indicator = document.createElement('div');
        indicator.className = `${this.className} ${this.status}`;
        indicator.innerHTML = `
            <span class="status-dot ${this.status}"></span>
            <span class="status-label">${this.label}</span>
        `;

        this.container.innerHTML = '';
        this.container.appendChild(indicator);
        
        this.indicatorElement = indicator;
        return indicator;
    }

    setStatus(status, label = null) {
        this.status = status;
        if (label) {
            this.label = label;
        }
        
        if (this.indicatorElement) {
            this.indicatorElement.className = `${this.className} ${this.status}`;
            const dot = this.indicatorElement.querySelector('.status-dot');
            const labelElement = this.indicatorElement.querySelector('.status-label');
            
            if (dot) dot.className = `status-dot ${this.status}`;
            if (labelElement) labelElement.textContent = this.label;
        }
        
        this.emit('statusChange', { status, label: this.label });
    }
}

/**
 * Component Factory
 * Helper for creating components with consistent configuration
 */
class ComponentFactory {
    static createCurrencySelector(containerId, options = {}) {
        return new CurrencySelector({
            containerId,
            ...options
        });
    }

    static createTimeframeSelector(containerId, options = {}) {
        return new TimeframeSelector({
            containerId,
            ...options
        });
    }

    static createControlButton(containerId, options = {}) {
        return new ControlButton({
            containerId,
            ...options
        });
    }

    static createStatusIndicator(containerId, options = {}) {
        return new StatusIndicator({
            containerId,
            ...options
        });
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        UIComponent,
        CurrencySelector,
        TimeframeSelector,
        ControlButton,
        StatusIndicator,
        ComponentFactory
    };
}
