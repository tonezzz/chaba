// ============================================================================
// SUMMARY MODULE - Summary rendering and re-summarization
// ============================================================================

console.log('summary.js: Loading module...');

// Initialize shared state using namespace
if (!DailyApp.getState('dailySummaries')) {
  DailyApp.setState('dailySummaries', []);
}
if (!DailyApp.getState('currentChatId')) {
  DailyApp.setState('currentChatId', null);
}

console.log('summary.js: DailyApp state initialized');

/**
 * Load daily summaries from API
 */
async function loadDailySummaries(chatId) {
  console.log('summary.js: loadDailySummaries called with chatId:', chatId);
  
  // Load all summaries for the calendar to show which dates have data
  const summaries = await YomiApi.loadDailySummaries(chatId);
  console.log('summary.js: loadDailySummaries returning:', summaries);
  return summaries;
}

/**
 * Trigger re-summarization for a specific date
 */
async function resummarizeDay(chatId, date) {
  const result = await YomiApi.resummarize([chatId], false, date);
  if (!result.ok) throw new Error(result.error || 'Re-summarization failed');
  return result;
}

/**
 * Handle re-summarization UI with progress feedback
 */
async function resummarizeDayUI(chatId, date, btnElement) {
  const progressDiv = document.getElementById(`progress-${date}`);
  
  if (!progressDiv || !btnElement) {
    console.error('Progress div or button not found for date:', date);
    return;
  }
  
  // Validate date format
  if (!date || !date.match(/^\d{4}-\d{2}-\d{2}$/)) {
    console.error('Invalid date format:', date);
    return;
  }
  
  btnElement.disabled = true;
  btnElement.textContent = 'Processing...';
  
  try {
    progressDiv.innerHTML = '<div class="loading">Starting re-summarization...</div>';
    
    const result = await resummarizeDay(chatId, date);
    
    progressDiv.innerHTML = '<div class="loading">✓ Done - refreshing...</div>';
    
    // Emit refresh event instead of callback
    setTimeout(() => {
      DailyApp.events.emit(DailyApp.modules.config?.EVENTS?.DATA_REFRESHED || 'daily:dataRefreshed');
    }, DailyApp.modules.config?.TIMEOUTS?.REFRESH_DELAY || 1000);
  } catch (error) {
    progressDiv.innerHTML = `<div class="loading" style="color: red;">Error: ${error.message}</div>`;
  } finally {
    btnElement.disabled = false;
    btnElement.textContent = 'Re-summarize';
  }
}

/**
 * Render summary for a specific date
 */
function renderSummaryForDate(dateStr) {
  console.log('summary.js: renderSummaryForDate called with', dateStr);
  const summaries = DailyApp.getState('dailySummaries') || [];
  console.log('summary.js: Available summaries:', summaries.map(s => ({
    originalDate: s.date,
    datePart: s.date.split('T')[0]
  })));
  
  const summary = summaries.find(s => {
    // API returns dates as "2026-08-03T17:00:00.000Z" (Thailand calendar date start time)
    // Extract just the date part for comparison
    const datePart = s.date.split('T')[0];
    console.log('summary.js: Checking summary:', s.date, '-> datePart:', datePart, 'vs selected:', dateStr);
    return datePart === dateStr;
  });
  
  if (!summary) {
    console.log('summary.js: No summary found for date', dateStr);
    return '<div class="empty-state">No summary available for this date</div>';
  }
  
  console.log('summary.js: Found summary for date', dateStr, summary);
  
  let html = '';
  
  if (summary.events && summary.events.length > 0) {
    html += '<div class="summary-section"><div class="section-title">Events</div><div class="tag-list">';
    summary.events.forEach(event => {
      html += `<span class="tag events">${event}</span>`;
    });
    html += '</div></div>';
  }
  
  if (summary.actions && summary.actions.length > 0) {
    html += '<div class="summary-section"><div class="section-title">Actions</div><div class="tag-list">';
    summary.actions.forEach(action => {
      html += `<span class="tag actions">${action}</span>`;
    });
    html += '</div></div>';
  }
  
  if (summary.topics && summary.topics.length > 0) {
    html += '<div class="summary-section"><div class="section-title">Topics</div><div class="tag-list">';
    summary.topics.forEach(topic => {
      html += `<span class="tag topics">${topic}</span>`;
    });
    html += '</div></div>';
  }
  
  if (summary.messageCount) {
    html += `<div class="summary-count">${summary.messageCount} messages</div>`;
  }
  
  html += `<div id="progress-${dateStr}"></div>`;
  
  console.log('summary.js: Generated HTML for date', dateStr);
  return html;
}

/**
 * Render summary content
 */
function renderSummary(summary) {
  if (!summary) {
    return '<div class="empty-state">No summary available</div>';
  }
  
  let html = '';
  
  if (summary.events && summary.events.length > 0) {
    html += '<div class="summary-section"><div class="section-title">Events</div><div class="tag-list">';
    summary.events.forEach(event => {
      html += `<span class="tag events">${event}</span>`;
    });
    html += '</div></div>';
  }
  
  if (summary.actions && summary.actions.length > 0) {
    html += '<div class="summary-section"><div class="section-title">Actions</div><div class="tag-list">';
    summary.actions.forEach(action => {
      html += `<span class="tag actions">${action}</span>`;
    });
    html += '</div></div>';
  }
  
  if (summary.topics && summary.topics.length > 0) {
    html += '<div class="summary-section"><div class="section-title">Topics</div><div class="tag-list">';
    summary.topics.forEach(topic => {
      html += `<span class="tag topics">${topic}</span>`;
    });
    html += '</div></div>';
  }
  
  return html;
}

/**
 * Set daily summaries
 */
function setDailySummaries(summaries) {
  console.log('summary.js: setDailySummaries called with', summaries.length, 'summaries');
  DailyApp.setState('dailySummaries', summaries);
}

/**
 * Get daily summaries
 */
function getDailySummaries() {
  return DailyApp.getState('dailySummaries');
}

/**
 * Set current chat ID
 */
function setCurrentChatId(chatId) {
  console.log('summary.js: setCurrentChatId called with', chatId);
  DailyApp.setState('currentChatId', chatId);
}

/**
 * Get current chat ID
 */
function getCurrentChatId() {
  return DailyApp.getState('currentChatId');
}

/**
 * Set refresh callback (deprecated - use events instead)
 */
function setRefreshCallback(callback) {
  console.warn('setRefreshCallback is deprecated. Use DailyApp.events.on instead');
  DailyApp.events.on(DailyApp.modules.config?.EVENTS?.DATA_REFRESHED || 'daily:dataRefreshed', callback);
}

// Make functions available globally for inter-module communication
console.log('summary.js: Exporting functions to window...');
window.loadDailySummaries = loadDailySummaries;
window.resummarizeDayUI = resummarizeDayUI;
window.renderSummaryForDate = renderSummaryForDate;
window.setDailySummaries = setDailySummaries;
window.setRefreshCallback = setRefreshCallback;
window.setCurrentChatId = setCurrentChatId;
window.getDailySummaries = getDailySummaries;
console.log('summary.js: Functions exported successfully');

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadDailySummaries,
    resummarizeDay,
    resummarizeDayUI,
    renderSummary,
    renderSummaryForDate,
    setCurrentChatId,
    getCurrentChatId,
    setDailySummaries,
    getDailySummaries,
    setRefreshCallback
  };
}
