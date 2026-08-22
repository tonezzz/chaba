// ============================================================================
// MESSAGES MODULE - Message list functionality
// ============================================================================

// Get configuration from namespace
const CONFIG = DailyApp.modules.config || {};

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
  console.log('messages.js: Fetching messages with date range');
  
  const messageLimit = CONFIG.UI?.MESSAGE_LIMIT || 1000;
  const messages = await YomiApi.loadMessages(chatId, startMs, endMs, messageLimit);
  console.log('messages.js: Loaded', messages?.length || 0, 'messages');
  
  // Sort messages descending (newest first)
  const sortedMessages = (messages || []).sort((a, b) => {
    const timeA = a.deliveredTime || a.createdTime || 0;
    const timeB = b.deliveredTime || b.createdTime || 0;
    return timeB - timeA;
  });
  
  // Log first and last message timestamps for debugging
  if (sortedMessages.length > 0) {
    const firstTimestamp = sortedMessages[0].deliveredTime || sortedMessages[0].createdTime;
    const lastTimestamp = sortedMessages[sortedMessages.length - 1].deliveredTime || sortedMessages[sortedMessages.length - 1].createdTime;
    
    console.log('messages.js: First message deliveredTime:', sortedMessages[0].deliveredTime);
    console.log('messages.js: First message createdTime:', sortedMessages[0].createdTime);
    console.log('messages.js: First message Thailand time:', DateUtils.msToIso(firstTimestamp));
    console.log('messages.js: Last message deliveredTime:', sortedMessages[sortedMessages.length - 1].deliveredTime);
    console.log('messages.js: Last message createdTime:', sortedMessages[sortedMessages.length - 1].createdTime);
    console.log('messages.js: Last message Thailand time:', DateUtils.msToIso(lastTimestamp));
  }
  
  return sortedMessages;
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
  
  console.log('renderMessage:', { id: message.id, mediaType: message.mediaType, mediaFile: message.mediaFile, hasText: !!text });
  
  if (!text && !message.mediaType) {
    return ''; // Skip empty messages without media
  }
  
  let content = '';
  const isMediaOnly = !text || text.trim() === '' || (text.startsWith('{') && text.includes('keyMaterial'));
  
  // Handle media with thumbnail
  if (message.mediaType && message.id) {
    console.log('Processing media:', { mediaType: message.mediaType, id: message.id, mediaFile: message.mediaFile });
    
    // Use direct file path instead of API proxy
    // Files are served directly by Caddy at /apps/yomi/media/
    // Use mediaFile if available, otherwise construct from id with common extensions
    const currentChatId = DailyApp.getState('currentChatId');
    let mediaUrl;
    if (message.mediaFile) {
      mediaUrl = `/apps/yomi/media/${currentChatId}/${message.mediaFile}`;
    } else {
      // Fallback to trying common extensions
      mediaUrl = `/apps/yomi/media/${currentChatId}/${message.id}.jpg`;
    }
    
    const imageTypes = CONFIG.MEDIA?.IMAGE_TYPES || ['image', 'photo', 'sticker'];
    const isImage = imageTypes.includes(message.mediaType.toLowerCase());
    console.log('Is image?', isImage, 'mediaType:', message.mediaType);
    
    if (isImage) {
      const hasAnalysis = message.mediaAnalysis && message.mediaAnalysis.trim() !== '';
      
      if (hasAnalysis) {
        // Show analysis result with re-analyze button
        content = `
          <div class="message-media-wrapper">
            <img src="${mediaUrl}" alt="${escapeHtml(message.mediaType)}" 
                 class="message-thumbnail" 
                 onclick="window.openImagePopup('${mediaUrl}')"
                 onerror="this.style.display='none'">
            <button class="analyze-btn re-analyze" 
                    data-msg-id="${message.id}" 
                    data-media-type="image"
                    onclick="event.stopPropagation(); window.analyzeMedia(this)">
              ↻ Re-analyze
            </button>
            <div class="media-analysis-result">
              <div class="analysis-label">AI Analysis:</div>
              <div class="analysis-text">${escapeHtml(message.mediaAnalysis)}</div>
            </div>
          </div>
        `;
      } else {
        // Show analyze button
        content = `
          <div class="message-media-wrapper">
            <img src="${mediaUrl}" alt="${escapeHtml(message.mediaType)}" 
                 class="message-thumbnail" 
                 onclick="window.openImagePopup('${mediaUrl}')"
                 onerror="this.style.display='none'">
            <button class="analyze-btn" 
                    data-msg-id="${message.id}" 
                    data-media-type="image"
                    onclick="event.stopPropagation(); window.analyzeMedia(this)">
              🔍 Analyze
            </button>
          </div>
        `;
      }
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
  
  // For media-only messages, show minimal layout
  if (isMediaOnly && message.mediaType) {
    return `
      <div class="message-item ${isSystem ? 'system' : ''} media-only">
        <div class="message-time">${formattedTime}</div>
        <div class="message-text">${content}</div>
      </div>
    `;
  }
  
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
    
    // Show/hide batch analyze button based on unanalyzed media
    const batchBtn = document.getElementById('batch-analyze-btn');
    if (batchBtn) {
      const imageTypes = CONFIG.MEDIA?.IMAGE_TYPES || ['image', 'photo', 'sticker'];
      const hasUnanalyzedMedia = messages.some(m => 
        m.mediaType && imageTypes.includes(m.mediaType.toLowerCase()) && 
        (!m.mediaAnalysis || m.mediaAnalysis.trim() === '')
      );
      batchBtn.style.display = hasUnanalyzedMedia ? 'inline-block' : 'none';
    }
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

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadMessagesForDate,
    renderMessage,
    renderMessageList,
    renderMessagesForDate
  };
}