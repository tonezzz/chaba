// ============================================================================
// SUMMARY MODULE - Summary rendering and re-summarization
// ============================================================================

let currentChatId = null;
let dailySummaries = [];
let onRefreshCallback = null;

/**
 * Load daily summaries from API
 */
async function loadDailySummaries(chatId) {
  const res = await fetch(`/api/yomi/daily?chat=${encodeURIComponent(chatId)}`);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
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
  if (!DateUtils.isValidDate(date)) {
    progressDiv.innerHTML = `<div class="progress-container" style="color: #dc2626;">Error: Invalid date format: ${escapeHtml(date)}</div>`;
    return;
  }
  
  // Show progress
  btnElement.disabled = true;
  const originalText = btnElement.textContent;
  btnElement.textContent = 'Processing...';
  
  const updateProgress = (message) => {
    progressDiv.innerHTML = `<div class="progress-container"><span class="progress-spinner"></span>${escapeHtml(message)}</div>`;
  };
  
  const actionText = originalText === 'Summarize' ? 'Generating summary...' : 'Re-summarizing...';
  updateProgress(actionText);
  
  try {
    // Convert Thailand calendar date to UTC timestamp for API
    const utcDateStr = DateUtils.thailandDateToUtc(date);
    
    // Step 1: Fetching messages
    updateProgress('Fetching messages...');
    await new Promise(resolve => setTimeout(resolve, 500)); // Brief delay to show progress
    
    // Step 2: Generating summary
    updateProgress(actionText);
    const result = await resummarizeDay(chatId, utcDateStr);
    
    // Check if the operation was successful
    if (result.ok) {
      // Show done status
      progressDiv.innerHTML = '<div class="progress-container progress-done">✓ Done - refreshing...</div>';
      
      // Reload summaries after a short delay
      setTimeout(async () => {
        dailySummaries = await loadDailySummaries(chatId);
        // Trigger refresh callback
        if (onRefreshCallback) {
          onRefreshCallback();
        }
        // Re-render summary for selected date
        const selectedDate = window.getSelectedDate ? window.getSelectedDate() : date;
        if (window.renderSummaryForDate) {
          window.renderSummaryForDate(selectedDate);
        }
      }, 1500);
    } else {
      throw new Error(result.error || 'Re-summarization failed');
    }
    
  } catch (err) {
    progressDiv.innerHTML = `<div class="progress-container" style="color: #dc2626;">Error: ${escapeHtml(err.message)}</div>`;
    btnElement.disabled = false;
    btnElement.textContent = originalText;
  }
}

/**
 * Render summary section
 */
function renderSummary(summary, chatId) {
  // Use the globally selected date, or fall back to today
  const dateStr = window.getSelectedDate ? window.getSelectedDate() : DateUtils.formatDateKey(new Date());
  
  if (!summary) {
    return `
      <div class="summary-section">
        <div class="section-title" style="display: flex; justify-content: space-between; align-items: center;">
          <span>Daily Summary</span>
          <button class="resummarize-btn" onclick="resummarizeDayUI('${chatId}', '${dateStr}', this)">Summarize</button>
        </div>
        <div id="progress-${dateStr}"></div>
        <div class="empty-state">No summary available for this date. Click Summarize to generate one.</div>
      </div>
    `;
  }
  
  // Convert UTC timestamp to Thailand calendar date for display
  const dateKey = DateUtils.utcToThailandDate(summary.date);
  
  return `
    <div class="summary-section">
      <div class="section-title" style="display: flex; justify-content: space-between; align-items: center;">
        <span>Daily Summary</span>
        <button class="resummarize-btn" onclick="resummarizeDayUI('${chatId}', '${dateKey}', this)">Re-summarize</button>
      </div>
      <div id="progress-${dateKey}"></div>
    </div>
    ${renderSection('Events', summary.events, 'events')}
    ${renderSection('Actions', summary.actions, 'actions')}
    ${renderSection('Topics', summary.topics, 'topics')}
    <a class="view-chat" href="/apps/yomi/chat.html?chat=${encodeURIComponent(chatId)}">View conversation</a>
  `;
}

/**
 * Render a summary section (events, actions, topics)
 */
function renderSection(title, items, type) {
  if (!items || !items.length) return '';
  return `
    <div class="summary-section">
      <div class="section-title">${title}</div>
      <div class="tag-list">${items.map(t => renderTag(t, type)).join('')}</div>
    </div>
  `;
}

/**
 * Render a tag
 */
function renderTag(tag, type) {
  return `<span class="tag ${type}">${escapeHtml(tag)}</span>`;
}

/**
 * Render summary for a specific date
 */
function renderSummaryForDate(dateStr) {
  const content = document.getElementById('summary-content');
  const dateEl = document.getElementById('summary-date');
  const countEl = document.getElementById('summary-count');
  
  if (!dateStr) {
    content.innerHTML = '<div class="empty-state">Select a date from the calendar to view the daily summary</div>';
    dateEl.textContent = 'Select a date';
    countEl.textContent = '';
    return;
  }
  
  // Convert Thailand calendar date to UTC timestamp for database lookup
  const utcDateStr = DateUtils.thailandDateToUtc(dateStr);
  const summary = dailySummaries.find(s => s.date === utcDateStr);
  
  dateEl.textContent = DateUtils.formatDate(dateStr);
  countEl.textContent = summary ? `${summary.message_count} messages` : '';
  content.innerHTML = '<div class="loading">Loading...</div>';
  
  // Small delay to allow UI to update
  setTimeout(() => {
    content.innerHTML = renderSummary(summary, currentChatId);
  }, 50);
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

/**
 * Set current chat ID
 */
function setCurrentChatId(chatId) {
  currentChatId = chatId;
}

/**
 * Get current chat ID
 */
function getCurrentChatId() {
  return currentChatId;
}

/**
 * Set daily summaries
 */
function setDailySummaries(summaries) {
  dailySummaries = summaries;
}

/**
 * Get daily summaries
 */
function getDailySummaries() {
  return dailySummaries;
}

/**
 * Set refresh callback
 */
function setRefreshCallback(callback) {
  onRefreshCallback = callback;
}

// Make functions available globally for inter-module communication
window.loadDailySummaries = loadDailySummaries;
window.resummarizeDayUI = resummarizeDayUI;
window.renderSummaryForDate = renderSummaryForDate;
window.setDailySummaries = setDailySummaries;
window.setRefreshCallback = setRefreshCallback;
window.setCurrentChatId = setCurrentChatId;

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
