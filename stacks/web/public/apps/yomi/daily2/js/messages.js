// ============================================================================
// MESSAGES MODULE - Message list functionality
// ============================================================================

/**
 * Load messages for a specific date
 */
async function loadMessagesForDate(chatId, dateStr) {
  console.log('messages.js: loadMessagesForDate called with chatId:', chatId, 'dateStr:', dateStr);
  
  // Get date range for Thailand calendar day
  const { startDate, endDate } = DateUtils.getThailandDateRange(dateStr);
  console.log('messages.js: Date range (ISO):', startDate, 'to', endDate);
  
  // Convert ISO timestamps to Unix timestamps (seconds) for API
  const startUnix = Math.floor(new Date(startDate).getTime() / 1000);
  const endUnix = Math.floor(new Date(endDate).getTime() / 1000);
  console.log('messages.js: Date range (Unix seconds):', startUnix, 'to', endUnix);
  
  const url = `/api/yomi/messages?chat=${encodeURIComponent(chatId)}&startDate=${startUnix}&endDate=${endUnix}&limit=1000`;
  console.log('messages.js: Fetching URL:', url);
  
  const res = await fetch(url);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  console.log('messages.js: Loaded', data.messages?.length || 0, 'messages');
  
  // Log first and last message timestamps for debugging
  if (data.messages && data.messages.length > 0) {
    console.log('messages.js: First message timestamp:', data.messages[0].timestamp);
    console.log('messages.js: First message Thailand time:', DateUtils.utcToThailandDate(new Date(data.messages[0].timestamp * 1000).toISOString()));
    console.log('messages.js: Last message timestamp:', data.messages[data.messages.length - 1].timestamp);
    console.log('messages.js: Last message Thailand time:', DateUtils.utcToThailandDate(new Date(data.messages[data.messages.length - 1].timestamp * 1000).toISOString()));
  }
  
  return data.messages || [];
}

/**
 * Format message time for display
 */
function formatMessageTime(timestamp) {
  const thailandTime = DateUtils.utcToThailandDate(timestamp);
  return DateUtils.formatTime(timestamp);
}

/**
 * Render a single message item
 */
function renderMessage(message) {
  const isSystem = message.type === 'system' || message.fromType === 'system';
  const sender = message.sender || message.fromName || (isSystem ? 'System' : 'Unknown');
  const text = message.text || message.content || '';
  
  if (!text && !message.mediaType) {
    return ''; // Skip empty messages without media
  }
  
  let content = '';
  
  // Handle media with thumbnail
  if (message.mediaType && message.id) {
    const mediaUrl = `/api/yomi/media/${window.currentChatId}/${message.id}`;
    const isImage = ['image', 'photo', 'sticker'].includes(message.mediaType.toLowerCase());
    
    if (isImage) {
      content = `
        <div class="message-media">
          <img src="${mediaUrl}" alt="${escapeHtml(message.mediaType)}" 
               class="message-thumbnail" 
               onclick="window.openImage('${mediaUrl}')"
               onerror="this.style.display='none'">
        </div>
      `;
    } else {
      content = `<div class="message-media-type">[${escapeHtml(message.mediaType).toUpperCase()}]</div>`;
    }
  } else if (message.mediaType) {
    content = `[${message.mediaType.toUpperCase()}]`;
  } else {
    content = escapeHtml(text);
  }
  
  // Format time in Thailand timezone
  const timeStr = message.deliveredTime || message.timestamp;
  const formattedTime = timeStr ? DateUtils.formatTime(timeStr) : '';
  
  return `
    <div class="message-item ${isSystem ? 'system' : ''}">
      <div class="message-sender">${escapeHtml(sender)}</div>
      <div class="message-time">${formattedTime}</div>
      <div class="message-text">${content}</div>
    </div>
  `;
}

/**
 * Render message list
 */
function renderMessageList(messages) {
  if (!messages || !messages.length) {
    return '<div class="empty-state" style="padding: 1rem;">No messages for this date</div>';
  }
  
  return messages.map(m => renderMessage(m)).join('');
}

/**
 * Render messages for a specific date
 */
async function renderMessagesForDate(chatId, dateStr) {
  console.log('messages.js: renderMessagesForDate called with chatId:', chatId, 'dateStr:', dateStr);
  
  const messageContent = document.getElementById('message-list-content');
  const messageCountEl = document.getElementById('message-list-count');
  
  if (!dateStr) {
    messageContent.innerHTML = '<div class="empty-state" style="padding: 1rem;">Select a date to view messages</div>';
    messageCountEl.textContent = '';
    return;
  }
  
  messageContent.innerHTML = '<div class="loading">Loading messages...</div>';
  
  try {
    const messages = await loadMessagesForDate(chatId, dateStr);
    console.log('messages.js: Rendering', messages.length, 'messages');
    
    // Log first few messages for debugging
    if (messages.length > 0) {
      console.log('messages.js: First message timestamp:', messages[0].timestamp);
      console.log('messages.js: First message Thailand time:', DateUtils.utcToThailandDate(messages[0].timestamp));
    }
    
    messageCountEl.textContent = `${messages.length} messages`;
    messageContent.innerHTML = renderMessageList(messages);
  } catch (err) {
    console.error('messages.js: Error loading messages:', err);
    messageContent.innerHTML = `<div class="empty-state" style="padding: 1rem; color: #dc2626;">Error loading messages: ${escapeHtml(err.message)}</div>`;
    messageCountEl.textContent = '';
  }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// Make functions available globally for inter-module communication
window.renderMessagesForDate = renderMessagesForDate;
window.openImage = function(url) {
  window.open(url, '_blank');
};

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadMessagesForDate,
    renderMessage,
    renderMessageList,
    renderMessagesForDate
  };
}
