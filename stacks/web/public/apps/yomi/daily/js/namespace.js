// ============================================================================
// NAMESPACE MODULE - Main application namespace to reduce global pollution
// ============================================================================

const DailyApp = {
  // Application state
  state: {
    currentChatId: null,
    dailySummaries: [],
    currentMonth: null,
    selectedDate: null,
    availableDates: new Set(),
    isInitialized: false
  },

  // Module references
  modules: {
    calendar: null,
    summary: null,
    messages: null,
    config: null
  },

  // Event emitter for inter-module communication
  events: {
    listeners: {},

    on(event, callback) {
      if (!this.listeners[event]) {
        this.listeners[event] = [];
      }
      this.listeners[event].push(callback);
    },

    off(event, callback) {
      if (!this.listeners[event]) return;
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    },

    emit(event, data) {
      if (!this.listeners[event]) return;
      this.listeners[event].forEach(callback => callback(data));
    }
  },

  // State management
  setState(key, value) {
    this.state[key] = value;
    this.events.emit('stateChanged', { key, value });
  },

  getState(key) {
    return this.state[key];
  },

  // Initialize application
  init() {
    if (this.state.isInitialized) {
      console.warn('DailyApp already initialized');
      return;
    }
    this.state.isInitialized = true;
    console.log('DailyApp namespace initialized');
  },

  // Register module
  registerModule(name, module) {
    this.modules[name] = module;
    console.log(`DailyApp module registered: ${name}`);
  },

  // Get module
  getModule(name) {
    return this.modules[name];
  }
};

// Make available globally
window.DailyApp = DailyApp;

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = DailyApp;
}
