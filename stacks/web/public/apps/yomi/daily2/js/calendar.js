// ============================================================================
// CALENDAR MODULE - Calendar rendering and interaction
// ============================================================================

const DAY_HEADERS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

let currentMonth = new Date();
let selectedDate = null;
let availableDates = new Set();

// Shared dailySummaries - initialized once globally
if (!window.dailySummaries) {
  window.dailySummaries = [];
}
let dailySummaries = window.dailySummaries;

/**
 * Set current month to the most recent summary date's month for better UX
 * This ensures the calendar shows the month with data
 */
function setCurrentMonthToData() {
  if (dailySummaries.length > 0) {
    const thailandDateStr = DateUtils.utcToThailandDate(dailySummaries[0].date);
    if (thailandDateStr) {
      const [year, month, day] = thailandDateStr.split('-').map(Number);
      currentMonth = new Date(year, month - 1, 1);
    }
  }
}

/**
 * Build the calendar grid
 */
function buildCalendar() {
  const grid = document.getElementById('calendar-grid');
  const title = document.getElementById('calendar-title');
  
  const year = currentMonth.getFullYear();
  const month = currentMonth.getMonth();
  
  title.textContent = currentMonth.toLocaleDateString(undefined, { year: 'numeric', month: 'long' });
  
  // Update available dates to use Thailand calendar date format
  availableDates = new Set(dailySummaries.map(s => {
    if (!s.date) return null;
    return DateUtils.utcToThailandDate(s.date);
  }).filter(Boolean));
  
  // Clear and rebuild entire grid including headers
  grid.innerHTML = '';
  
  // Add day headers
  DAY_HEADERS.forEach(day => {
    const header = document.createElement('div');
    header.className = 'calendar-day-header';
    header.textContent = day;
    grid.appendChild(header);
  });
  
  // Get first day of month and total days
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startDay = firstDay.getDay();
  const totalDays = lastDay.getDate();
  
  // Get previous month's days for padding
  const prevMonthLastDay = new Date(year, month, 0).getDate();
  
  // Add previous month's days
  for (let i = startDay - 1; i >= 0; i--) {
    const day = prevMonthLastDay - i;
    const dateStr = DateUtils.formatDateKey(new Date(year, month - 1, day));
    const dayEl = createDayElement(day, dateStr, true);
    grid.appendChild(dayEl);
  }
  
  // Add current month's days
  const today = new Date();
  for (let day = 1; day <= totalDays; day++) {
    const date = new Date(year, month, day);
    const dateStr = DateUtils.formatDateKey(date);
    const isToday = date.toDateString() === today.toDateString();
    const dayEl = createDayElement(day, dateStr, false, isToday);
    grid.appendChild(dayEl);
  }
  
  // Add next month's days to fill grid
  const totalCells = startDay + totalDays;
  const remainingCells = totalCells <= 35 ? 35 - totalCells : 42 - totalCells;
  for (let day = 1; day <= remainingCells; day++) {
    const dateStr = DateUtils.formatDateKey(new Date(year, month + 1, day));
    const dayEl = createDayElement(day, dateStr, true);
    grid.appendChild(dayEl);
  }
}

/**
 * Create a calendar day element
 */
function createDayElement(day, dateStr, isOtherMonth, isToday = false) {
  const el = document.createElement('div');
  el.className = 'calendar-day';
  if (isOtherMonth) el.classList.add('other-month');
  if (isToday) el.classList.add('today');
  
  // Check if this date has data by converting to UTC for database matching
  const hasData = dailySummaries.some(s => {
    if (!s.date) return false;
    const thailandDate = DateUtils.utcToThailandDate(s.date);
    return thailandDate === dateStr;
  });
  if (hasData) el.classList.add('has-data');
  
  if (selectedDate === dateStr) el.classList.add('selected');
  
  el.textContent = day;
  el.addEventListener('click', () => selectDate(dateStr));
  return el;
}

/**
 * Select a date from the calendar
 */
function selectDate(dateStr) {
  selectedDate = dateStr;
  buildCalendar();
  // Trigger summary rendering via callback
  if (window.onDateSelected) {
    window.onDateSelected(dateStr);
  }
  // Also make it available globally for other modules
  window.getSelectedDate = getSelectedDate;
}

/**
 * Navigate to previous month
 */
function navigatePrevMonth() {
  currentMonth.setMonth(currentMonth.getMonth() - 1);
  buildCalendar();
}

/**
 * Navigate to next month
 */
function navigateNextMonth() {
  currentMonth.setMonth(currentMonth.getMonth() + 1);
  buildCalendar();
}

/**
 * Update daily summaries data
 */
function setDailySummaries(summaries) {
  dailySummaries = summaries;
}

/**
 * Update daily summaries data (alias for app.js)
 */
function setCalendarDailySummaries(summaries) {
  dailySummaries = summaries;
}

/**
 * Get current selected date
 */
function getSelectedDate() {
  return selectedDate;
}

/**
 * Set current selected date
 */
function setSelectedDate(dateStr) {
  selectedDate = dateStr;
}

/**
 * Get current month
 */
function getCurrentMonth() {
  return currentMonth;
}

/**
 * Set current month
 */
function setCurrentMonth(date) {
  currentMonth = date;
}

// Make functions available globally for inter-module communication
window.buildCalendar = buildCalendar;
window.selectDate = selectDate;
window.navigatePrevMonth = navigatePrevMonth;
window.navigateNextMonth = navigateNextMonth;
window.setDailySummaries = setDailySummaries;
window.setCalendarDailySummaries = setCalendarDailySummaries;
window.getSelectedDate = getSelectedDate;
window.setSelectedDate = setSelectedDate;
window.getCurrentMonth = getCurrentMonth;
window.setCurrentMonth = setCurrentMonth;
window.setCurrentMonthToData = setCurrentMonthToData;

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    buildCalendar,
    selectDate,
    navigatePrevMonth,
    navigateNextMonth,
    setDailySummaries,
    setCalendarDailySummaries,
    getSelectedDate,
    setSelectedDate,
    getCurrentMonth,
    setCurrentMonth,
    setCurrentMonthToData
  };
}
