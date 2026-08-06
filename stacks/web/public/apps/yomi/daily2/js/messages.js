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
  
  // Convert to Unix milliseconds for API (database stores delivered_time as bigint in milliseconds)
  const startMs = DateUtils.isoToUnix(startDate) * 1000;
  const endMs = DateUtils.isoToUnix(endDate) * 1000;
  console.log('messages.js: Date range (Unix ms):', startMs, 'to', endMs);
  
  // Use API date filtering
  const url = `/api/yomi/messages?chat=${encodeURIComponent(chatId)}&startDate=${startMs}&endDate=${endMs}&limit=1000`;
  console.log('messages.js: Fetching URL:', url);
  
  const res = await fetch(url);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  console.log('messages.js: Loaded', data.messages?.length || 0, 'messages');
  
  // Sort messages descending (newest first)
  const messages = (data.messages || []).sort((a, b) => {
    const timeA = a.deliveredTime || a.createdTime || 0;
    const timeB = b.deliveredTime || b.createdTime || 0;
    return timeB - timeA;
  });
  
  // Log first and last message timestamps for debugging
  if (messages.length > 0) {
    const firstTimestamp = messages[0].deliveredTime || messages[0].createdTime;
    const lastTimestamp = messages[messages.length - 1].deliveredTime || messages[messages.length - 1].createdTime;
    
    console.log('messages.js: First message deliveredTime:', messages[0].deliveredTime);
    console.log('messages.js: First message createdTime:', messages[0].createdTime);
    console.log('messages.js: First message Thailand time:', DateUtils.msToIso(firstTimestamp));
    console.log('messages.js: Last message deliveredTime:', messages[messages.length - 1].deliveredTime);
    console.log('messages.js: Last message createdTime:', messages[messages.length - 1].createdTime);
    console.log('messages.js: Last message Thailand time:', DateUtils.msToIso(lastTimestamp));
  }
  
  return messages;
}

/**
 * Format message time for display
 */
function formatMessageTime(timestamp) {
  // Database stores Thailand time in milliseconds
  // Convert to ISO timestamp for formatting
  const thailandTime = DateUtils.msToIso(timestamp);
  return DateUtils.formatTime(thailandTime);
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
    // Use direct file path instead of API proxy
    // Files are served directly by Caddy at /apps/yomi/media/
    const mediaUrl = `/apps/yomi/media/${window.currentChatId}/${message.id}.jpg`;
    const isImage = ['image', 'photo', 'sticker'].includes(message.mediaType.toLowerCase());
    
    if (isImage) {
      content = `
        <img src="${mediaUrl}" alt="${escapeHtml(message.mediaType)}" 
             class="message-thumbnail" 
             onclick="window.openImagePopup('${mediaUrl}')"
             onerror="this.style.display='none'">
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
      console.log('messages.js: First message Thailand time:', DateUtils.msToIso(messages[0].timestamp));
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

/**
 * Open image popup
 */
function openImagePopup(imageUrl) {
  const popup = document.getElementById('image-popup');
  const img = document.getElementById('image-popup-img');
  
  if (popup && img) {
    img.src = imageUrl;
    popup.classList.add('active');
  }
}

/**
 * Close image popup
 */
function closeImagePopup() {
  const popup = document.getElementById('image-popup');
  const img = document.getElementById('image-popup-img');
  
  if (popup && img) {
    popup.classList.remove('active');
    img.src = '';
  }
}

// Make functions available globally for inter-module communication
window.renderMessagesForDate = renderMessagesForDate;
window.openImage = openImagePopup;
window.openImagePopup = openImagePopup;
window.closeImagePopup = closeImagePopup;

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadMessagesForDate,
    renderMessage,
    renderMessageList,
    renderMessagesForDate
  };
}
