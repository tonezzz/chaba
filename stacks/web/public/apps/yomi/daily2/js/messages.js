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
  
  // Convert to Unix timestamps for comparison
  const startUnix = DateUtils.isoToUnix(startDate);
  const endUnix = DateUtils.isoToUnix(endDate);
  console.log('messages.js: Date range (Unix seconds):', startUnix, 'to', endUnix);
  
  // Load all messages (API doesn't support date filtering)
  const url = `/api/yomi/messages?chat=${encodeURIComponent(chatId)}&limit=1000`;
  console.log('messages.js: Fetching URL:', url);
  
  const res = await fetch(url);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  console.log('messages.js: Loaded total messages:', data.messages?.length || 0);
  
  // Filter messages client-side by Thailand calendar date
  const filteredMessages = (data.messages || []).filter(message => {
    const timestamp = message.deliveredTime || message.createdTime;
    if (!timestamp) {
      console.log('messages.js: Skipping message without timestamp:', message.id);
      return false;
    }
    
    // Convert millisecond timestamp to ISO, then to Thailand date
    const isoTimestamp = DateUtils.msToIso(timestamp);
    const thailandDate = DateUtils.utcToThailandDate(isoTimestamp);
    
    // Check if message's Thailand date matches selected date
    const matches = thailandDate === dateStr;
    if (!matches) {
      console.log('messages.js: Message Thailand date', thailandDate, '!= selected', dateStr);
    }
    return matches;
  });
  
  console.log('messages.js: Filtered to', filteredMessages.length, 'messages for date', dateStr);
  
  // Log first and last message timestamps for debugging
  if (filteredMessages.length > 0) {
    const firstTimestamp = filteredMessages[0].deliveredTime || filteredMessages[0].createdTime;
    const lastTimestamp = filteredMessages[filteredMessages.length - 1].deliveredTime || filteredMessages[filteredMessages.length - 1].createdTime;
    
    console.log('messages.js: First message deliveredTime:', filteredMessages[0].deliveredTime);
    console.log('messages.js: First message createdTime:', filteredMessages[0].createdTime);
    console.log('messages.js: First message Thailand date:', DateUtils.utcToThailandDate(DateUtils.msToIso(firstTimestamp)));
    console.log('messages.js: Last message deliveredTime:', filteredMessages[filteredMessages.length - 1].deliveredTime);
    console.log('messages.js: Last message createdTime:', filteredMessages[filteredMessages.length - 1].createdTime);
    console.log('messages.js: Last message Thailand date:', DateUtils.utcToThailandDate(DateUtils.msToIso(lastTimestamp)));
  }
  
  return filteredMessages;
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
    // Use mediaFile field for the filename
    const mediaFilename = message.mediaFile || message.id;
    const mediaUrl = `/api/yomi/media/${window.currentChatId}/${mediaFilename}`;
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
  
  // Format time in Thailand timezone using deliveredTime or createdTime
  const timeStr = message.deliveredTime || message.createdTime;
  const formattedTime = timeStr ? DateUtils.formatTime(DateUtils.msToIso(timeStr)) : '';
  
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
