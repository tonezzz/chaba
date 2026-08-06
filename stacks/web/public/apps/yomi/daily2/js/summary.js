// ============================================================================
// SUMMARY MODULE - Summary rendering and re-summarization
// ============================================================================

console.log('summary.js: Loading module...');

// Initialize shared state on window object
if (!window.dailySummaries) {
  window.dailySummaries = [];
}
if (!window.currentChatId) {
  window.currentChatId = null;
}
if (!window.onRefreshCallback) {
  window.onRefreshCallback = null;
}

console.log('summary.js: window.dailySummaries initialized');

/**
 * Load daily summaries from API
 */
async function loadDailySummaries(chatId) {
  console.log('summary.js: loadDailySummaries called with chatId:', chatId);
  
  // Load all summaries for the calendar to show which dates have data
  const res = await fetch(`/api/yomi/daily?chat=${encodeURIComponent(chatId)}`);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  console.log('summary.js: loadDailySummaries returning:', data.summaries);
  return data.summaries || [];
}

/**
 * Trigger re-summarization for a specific date
 */
async function resummarizeDay(chatId, date) {
  const res = await fetch('/api/yomi/resummarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chatIds: [chatId], forceAll: false, targetDate: date })
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const result = await res.json();
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
    
    if (window.onRefreshCallback) {
      setTimeout(() => window.onRefreshCallback(), 1000);
    }
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
  console.log('summary.js: Available summaries:', window.dailySummaries.map(s => ({
    originalDate: s.date,
    thailandDate: DateUtils.utcToThailandDate(s.date)
  })));
  
  const summary = window.dailySummaries.find(s => {
    const thailandDate = DateUtils.utcToThailandDate(s.date);
    console.log('summary.js: Checking summary:', s.date, '-> Thailand:', thailandDate, 'vs selected:', dateStr);
    return thailandDate === dateStr;
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
  
  const thailandDate = DateUtils.formatDate(dateStr);
  html += `<a class="view-chat" href="/apps/yomi/chat.html?chat=${window.currentChatId}&date=${dateStr}">View conversation</a>`;
  
  html += `<button class="resummarize-btn" onclick="window.resummarizeDayUI('${window.currentChatId}', '${dateStr}', this)">Re-summarize</button>`;
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
  window.dailySummaries = summaries;
}

/**
 * Get daily summaries
 */
function getDailySummaries() {
  return window.dailySummaries;
}

/**
 * Set current chat ID
 */
function setCurrentChatId(chatId) {
  console.log('summary.js: setCurrentChatId called with', chatId);
  window.currentChatId = chatId;
}

/**
 * Get current chat ID
 */
function getCurrentChatId() {
  return window.currentChatId;
}

/**
 * Set refresh callback
 */
function setRefreshCallback(callback) {
  window.onRefreshCallback = callback;
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
