// ============================================================================
// DATE UTILITIES - Centralized Thailand timezone handling
// ============================================================================
//
// CRITICAL: Database stores delivered_time as Thailand time (milliseconds since epoch)
// Thailand calendar day = 00:00 to 23:59:59 Thailand time
// This means Thailand calendar date directly matches the Thailand time date
//
// Example: Thailand calendar date "2026-08-03" spans:
//   Start: 2026-08-03T00:00:00.000Z (midnight Thailand time)
//   End: 2026-08-03T23:59:59.000Z (23:59:59 Thailand time)
//
// CONVERSION RULES:
// 1. Thailand time → Thailand calendar date: Extract date directly
//    Database stores Thailand time, so no conversion needed
//    Example: 2026-08-03T15:29:28Z → "2026-08-03"
//
// 2. Thailand calendar date → Thailand time range: 00:00 to 23:59:59
//    For API filtering, use simple date range in Thailand time
//    Example: "2026-08-03" → 2026-08-03T00:00:00Z to 2026-08-03T23:59:59Z
//
// See: docs/kb/thailand-timezone-standard.md for comprehensive documentation
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
   * Convert Thailand time timestamp to Thailand calendar date (YYYY-MM-DD)
   * 
   * CRITICAL: Database stores delivered_time as Thailand time (milliseconds since epoch)
   * Thailand calendar day = 00:00 to 23:59:59 Thailand time
   * 
   * Conversion: Extract date directly from Thailand time
   * No timezone conversion needed since database stores Thailand time
   * 
   * Example:
   *   Input: 2026-08-03T15:29:28.491Z (Thailand time)
   *   Output: "2026-08-03" (Thailand calendar date)
   * 
   * @param {string} isoTimestamp - ISO timestamp string (Thailand time)
   * @returns {string} Thailand calendar date in YYYY-MM-DD format
   */
  utcToThailandDate(isoTimestamp) {
    if (!isoTimestamp) return null;
    
    const thailandTime = new Date(isoTimestamp);
    if (isNaN(thailandTime.getTime())) return null;
    
    // Database stores Thailand time, so extract date directly
    const year = thailandTime.getFullYear();
    const month = thailandTime.getMonth() + 1;
    const day = thailandTime.getDate();
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    
    console.log('date-utils: utcToThailandDate', isoTimestamp, '-> Thailand calendar date:', dateStr);
    return dateStr;
  },
  
  /**
   * Get date range for a Thailand calendar day
   * 
   * CRITICAL: This is for API filtering by Thailand calendar date
   * Database stores delivered_time as Thailand time (milliseconds since epoch)
   * Thailand calendar day = 17:00 UTC to 16:59:59 UTC next day
   * In Thailand time, this is 00:00 to 23:59:59
   * 
   * Example:
   *   Input: "2026-08-03"
   *   Output: {
   *     startDate: "2026-08-03T00:00:00.000Z" (midnight Thailand time),
   *     endDate: "2026-08-03T23:59:59.000Z" (23:59:59 Thailand time)
   *   }
   * 
   * @param {string} dateStr - Thailand calendar date in YYYY-MM-DD format
   * @returns {object} { startDate: ISO timestamp, endDate: ISO timestamp }
   */
  getThailandDateRange(dateStr) {
    console.log('date-utils: getThailandDateRange called with', dateStr);
    
    const [year, month, day] = dateStr.split('-').map(Number);
    
    // Database stores delivered_time as Thailand time
    // Thailand calendar day in Thailand time: 00:00 to 23:59:59
    const startDate = new Date(Date.UTC(year, month - 1, day, 0, 0, 0));
    const endDate = new Date(Date.UTC(year, month - 1, day, 23, 59, 59));
    
    const startDateStr = startDate.toISOString();
    const endDateStr = endDate.toISOString();
    
    console.log('date-utils: startDate (Thailand 00:00):', startDateStr);
    console.log('date-utils: endDate (Thailand 23:59:59):', endDateStr);
    
    return {
      startDate: startDateStr,
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
    // Calendar should generate Thailand calendar dates directly
    // No conversion needed - use the date as-is
    const year = date.getFullYear();
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    
    console.log('date-utils: formatDateKeyThailand', date.toISOString(), '-> dateStr:', dateStr);
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
