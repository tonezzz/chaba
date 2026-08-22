// ============================================================================
// CONFIGURATION MODULE - Constants and configuration for daily app
// ============================================================================

export const CONFIG = {
  // API endpoints
  API: {
    CONVERSATIONS: '/api/yomi/conversations',
    DAILY_SUMMARIES: '/api/yomi/daily',
    MESSAGES: '/api/yomi/messages',
    RESUMMARIZE: '/api/yomi/resummarize',
    MEDIA_ANALYZE: '/api/yomi/analyze-media'
  },

  // UI constants
  UI: {
    PAGE_LIMIT: 50,
    MESSAGE_LIMIT: 1000,
    CALENDAR_DAY_HEADERS: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    THAILAND_OFFSET_HOURS: 7
  },

  // Media types
  MEDIA: {
    IMAGE_TYPES: ['image', 'photo', 'sticker'],
    THUMBNAIL_SIZE: 135,
    COMMON_EXTENSIONS: ['.jpg', '.jpeg', '.png', '.gif']
  },

  // CSS selectors
  SELECTORS: {
    APP: '#app',
    CHAT_SELECT: '#chat-select',
    CALENDAR_GRID: '#calendar-grid',
    CALENDAR_TITLE: '#calendar-title',
    SUMMARY_CONTENT: '#summary-content',
    SUMMARY_DATE: '#summary-date',
    SUMMARY_COUNT: '#summary-count',
    HEADER_RESUMMARIZE_BTN: '#header-resummarize-btn',
    MESSAGE_LIST_CONTENT: '#message-list-content',
    MESSAGE_LIST_COUNT: '#message-list-count',
    BATCH_ANALYZE_BTN: '#batch-analyze-btn',
    IMAGE_POPUP: '#image-popup',
    IMAGE_POPUP_IMG: '#image-popup-img'
  },

  // Event names
  EVENTS: {
    DATE_SELECTED: 'daily:dateSelected',
    DATA_REFRESHED: 'daily:dataRefreshed',
    CHAT_CHANGED: 'daily:chatChanged',
    SUMMARY_UPDATED: 'daily:summaryUpdated',
    MESSAGES_LOADED: 'daily:messagesLoaded'
  },

  // Timeouts and delays
  TIMEOUTS: {
    REFRESH_DELAY: 1000,
    API_TIMEOUT: 30000
  },

  // Version for cache busting
  VERSION: '1'
};

// Make available globally for legacy compatibility
if (typeof window !== 'undefined') {
  window.DailyConfig = CONFIG;
  
  // Register with DailyApp namespace if available
  if (window.DailyApp) {
    window.DailyApp.registerModule('config', CONFIG);
  }
}
