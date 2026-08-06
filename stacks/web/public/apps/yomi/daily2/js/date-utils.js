// ============================================================================
// DATE UTILITIES - Centralized Thailand timezone handling
// ============================================================================

const DateUtils = {
  // Thailand timezone offset (UTC+7)
  THAILAND_OFFSET_HOURS: 7,
  
  // Database stores Thailand calendar dates as 17:00 UTC (midnight Thailand time)
  DATABASE_UTC_HOUR: 17,
  
  /**
   * Convert Thailand calendar date (YYYY-MM-DD) to UTC timestamp for database
   * @param {string} dateStr - Thailand calendar date in YYYY-MM-DD format
   * @returns {string} ISO timestamp representing 17:00 UTC on that date
   */
  thailandDateToUtc(dateStr) {
    if (!dateStr || !dateStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
      throw new Error(`Invalid date format: ${dateStr}. Expected YYYY-MM-DD`);
    }
    
    const [year, month, day] = dateStr.split('-').map(Number);
    const utcDate = new Date(Date.UTC(year, month - 1, day, this.DATABASE_UTC_HOUR, 0, 0));
    
    if (isNaN(utcDate.getTime())) {
      throw new Error(`Invalid date: ${dateStr}`);
    }
    
    return utcDate.toISOString();
  },
  
  /**
   * Convert UTC timestamp to Thailand calendar date (YYYY-MM-DD)
   * @param {string} isoTimestamp - ISO timestamp string
   * @returns {string} Thailand calendar date in YYYY-MM-DD format
   */
  utcToThailandDate(isoTimestamp) {
    if (!isoTimestamp) return null;
    
    const utcDate = new Date(isoTimestamp);
    if (isNaN(utcDate.getTime())) return null;
    
    // Add 7 hours to convert UTC to Thailand time
    const thailandDate = new Date(utcDate.getTime() + (this.THAILAND_OFFSET_HOURS * 60 * 60 * 1000));
    
    const year = thailandDate.getFullYear();
    const month = thailandDate.getMonth() + 1;
    const day = thailandDate.getDate();
    
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    console.log('date-utils: utcToThailandDate', isoTimestamp, '->', dateStr);
    return dateStr;
  },
  
  /**
   * Get date range for a Thailand calendar day
   * @param {string} dateStr - Thailand calendar date in YYYY-MM-DD format
   * @returns {object} { startDate: ISO timestamp, endDate: ISO timestamp }
   */
  getThailandDateRange(dateStr) {
    console.log('date-utils: getThailandDateRange called with', dateStr);
    
    const startDate = this.thailandDateToUtc(dateStr);
    console.log('date-utils: startDate (UTC 17:00):', startDate);
    
    const [year, month, day] = dateStr.split('-').map(Number);
    // End of Thailand day is 16:59:59 UTC the next day
    const endDate = new Date(Date.UTC(year, month - 1, day + 1, 16, 59, 59));
    const endDateStr = endDate.toISOString();
    console.log('date-utils: endDate (UTC 16:59:59 next day):', endDateStr);
    
    return {
      startDate,
      endDate: endDateStr
    };
  },
  
  /**
   * Format date for display
   * @param {string} dateStr - Date string (any format)
   * @returns {string} Formatted date string
   */
  formatDate(dateStr) {
    if (!dateStr) return 'Invalid date';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return 'Invalid date';
    return d.toLocaleDateString(undefined, { 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric', 
      weekday: 'long' 
    });
  },
  
  /**
   * Format time for display
   * @param {string|number} timestamp - Timestamp string or number
   * @returns {string} Formatted time string
   */
  formatTime(timestamp) {
    if (!timestamp) return '';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString(undefined, { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  },
  
  /**
   * Validate date format (YYYY-MM-DD)
   * @param {string} dateStr - Date string to validate
   * @returns {boolean} True if valid
   */
  isValidDate(dateStr) {
    return dateStr && !!dateStr.match(/^\d{4}-\d{2}-\d{2}$/);
  },
  
  /**
   * Format date as YYYY-MM-DD in local time
   * @param {Date} date - Date object
   * @returns {string} YYYY-MM-DD format
   */
  formatDateKey(date) {
    const year = date.getFullYear();
    const month = date.getMonth() + 1; // getMonth() returns 0-11
    const day = date.getDate();
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  },
  
  /**
   * Format date as YYYY-MM-DD in Thailand time
   * @param {Date} date - Date object (in local time)
   * @returns {string} YYYY-MM-DD format in Thailand time
   */
  formatDateKeyThailand(date) {
    // Direct conversion: local date + 7 hours = Thailand time
    // Extract the date from Thailand time
    const thailandTime = new Date(date.getTime() + (this.THAILAND_OFFSET_HOURS * 60 * 60 * 1000));
    
    const year = thailandTime.getFullYear();
    const month = thailandTime.getMonth() + 1;
    const day = thailandTime.getDate();
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    
    console.log('date-utils: formatDateKeyThailand', date.toISOString(), '-> Thailand time:', thailandTime.toISOString(), '-> dateStr:', dateStr);
    return dateStr;
  },
  
  /**
   * Convert ISO timestamp to Unix timestamp in seconds
   * @param {string} isoTimestamp - ISO timestamp string
   * @returns {number} Unix timestamp in seconds
   */
  isoToUnix(isoTimestamp) {
    if (!isoTimestamp) return null;
    const date = new Date(isoTimestamp);
    if (isNaN(date.getTime())) return null;
    return Math.floor(date.getTime() / 1000);
  },
  
  /**
   * Convert Unix timestamp in seconds to ISO timestamp
   * @param {number} unixTimestamp - Unix timestamp in seconds
   * @returns {string} ISO timestamp
   */
  unixToIso(unixTimestamp) {
    if (!unixTimestamp) return null;
    const date = new Date(unixTimestamp * 1000);
    if (isNaN(date.getTime())) return null;
    return date.toISOString();
  },
  
  /**
   * Convert millisecond timestamp to ISO timestamp
   * @param {number} msTimestamp - Timestamp in milliseconds
   * @returns {string} ISO timestamp
   */
  msToIso(msTimestamp) {
    if (!msTimestamp) return null;
    const date = new Date(msTimestamp);
    if (isNaN(date.getTime())) return null;
    return date.toISOString();
  },
  
  /**
   * Convert millisecond timestamp to Unix timestamp in seconds
   * @param {number} msTimestamp - Timestamp in milliseconds
   * @returns {number} Unix timestamp in seconds
   */
  msToUnix(msTimestamp) {
    if (!msTimestamp) return null;
    return Math.floor(msTimestamp / 1000);
  }
};

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = DateUtils;
}

// Make DateUtils available globally
window.DateUtils = DateUtils;
