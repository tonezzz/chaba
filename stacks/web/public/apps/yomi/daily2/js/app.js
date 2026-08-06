// ============================================================================
// APP MODULE - Main application initialization and coordination
// ============================================================================

// Reference to currentChatId from summary module
let currentChatId = window.currentChatId || null;

/**
 * Load conversations from API
 */
async function loadConversations() {
  try {
    const res = await fetch('/api/yomi/conversations');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const { conversations } = await res.json();
    return conversations || [];
  } catch (error) {
    console.error('Failed to load conversations:', error);
    return [];
  }
}

/**
 * Load chat data (summaries and calendar)
 */
async function loadChatData(chatId) {
  window.currentChatId = chatId;
  
  // Set chat ID in summary module
  if (window.setCurrentChatId) {
    window.setCurrentChatId(chatId);
  }
  
  // Load daily summaries
  const summaries = await window.loadDailySummaries(chatId);
  
  // Update both calendar and summary modules with summaries
  if (window.setDailySummaries) {
    window.setDailySummaries(summaries);
  }
  if (window.setCalendarDailySummaries) {
    window.setCalendarDailySummaries(summaries);
  }
  
  // Set current month to most recent summary date
  if (window.setCurrentMonthToData) {
    window.setCurrentMonthToData();
  }
  
  // Build calendar
  if (window.buildCalendar) {
    window.buildCalendar();
  }
  
  // Select most recent date if available
  if (summaries.length > 0) {
    const dateStr = summaries[0].date;
    if (dateStr) {
      if (window.selectDate) {
        window.selectDate(dateStr);
      }
    }
  }
}

/**
 * Handle date selection
 */
function handleDateSelected(dateStr) {
  console.log('app.js: handleDateSelected called with', dateStr);
  
  // Update summary panel
  const summaryContent = document.getElementById('summary-content');
  const summaryDate = document.getElementById('summary-date');
  const summaryCount = document.getElementById('summary-count');
  const headerResummarizeBtn = document.getElementById('header-resummarize-btn');
  
  if (summaryDate) {
    summaryDate.textContent = DateUtils.formatDate(dateStr);
  }
  
  if (window.renderSummaryForDate) {
    const summaryHtml = window.renderSummaryForDate(dateStr);
    if (summaryContent) {
      summaryContent.innerHTML = summaryHtml;
    }
  }
  
  // Update message count
  // Database returns Thailand calendar date as YYYY-MM-DD string
  // No conversion needed - direct string comparison
  const summary = window.dailySummaries.find(s => {
    return s.date === dateStr;
  });
  
  if (summaryCount && summary) {
    summaryCount.textContent = `${summary.messageCount || 0} messages`;
  } else if (summaryCount) {
    summaryCount.textContent = '';
  }
  
  // Show/hide header re-summarize button
  if (headerResummarizeBtn) {
    if (summary) {
      headerResummarizeBtn.style.display = 'inline-block';
      headerResummarizeBtn.onclick = () => window.resummarizeDayUI(window.currentChatId, dateStr, headerResummarizeBtn);
    } else {
      headerResummarizeBtn.style.display = 'none';
    }
  }
  
  // Render messages
  if (window.renderMessagesForDate) {
    window.renderMessagesForDate(window.currentChatId, dateStr);
  }
}

/**
 * Handle refresh after re-summarization
 */
function handleRefresh() {
  // Update calendar with new data
  if (window.buildCalendar) {
    window.buildCalendar();
  }
}

/**
 * Initialize the application
 */
async function init() {
  const select = document.getElementById('chat-select');
  
  try {
    const conversations = await loadConversations();
    if (!conversations.length) {
      document.getElementById('app').innerHTML = '<div class="empty-state">No conversations found.</div>';
      return;
    }
    
    // Populate chat selector
    select.innerHTML = conversations.map(c => 
      `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`
    ).join('');
    
    // Load chat from URL parameter or first available
    const chatParam = new URLSearchParams(location.search).get('chat');
    if (chatParam) {
      select.value = chatParam;
      await loadChatData(chatParam);
    } else if (conversations.length) {
      select.value = conversations[0].id;
      await loadChatData(conversations[0].id);
    }
    
    // Set up event listeners
    select.addEventListener('change', () => {
      const chatId = select.value;
      if (chatId) {
        const url = new URL(location.href);
        url.searchParams.set('chat', chatId);
        history.replaceState(null, '', url);
        loadChatData(chatId);
      }
    });
    
    document.getElementById('prev-month').addEventListener('click', () => {
      if (window.navigatePrevMonth) {
        window.navigatePrevMonth();
      }
    });
    
    document.getElementById('next-month').addEventListener('click', () => {
      if (window.navigateNextMonth) {
        window.navigateNextMonth();
      }
    });
    
    // Set up callbacks
    window.onDateSelected = handleDateSelected;
    if (window.setRefreshCallback) {
      window.setRefreshCallback(handleRefresh);
    }
    
  } catch (err) {
    document.getElementById('app').innerHTML = `<div class="empty-state">Error: ${escapeHtml(err.message)}</div>`;
  }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadConversations,
    loadChatData,
    handleDateSelected,
    handleRefresh,
    init
  };
}
