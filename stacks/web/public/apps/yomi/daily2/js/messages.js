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
  console.log('messages.js: Fetching messages with date range');
  
  const messages = await YomiApi.loadMessages(chatId, startMs, endMs, 1000);
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
    let mediaUrl;
    if (message.mediaFile) {
      mediaUrl = `/apps/yomi/media/${window.currentChatId}/${message.mediaFile}`;
    } else {
      // Fallback to trying common extensions
      mediaUrl = `/apps/yomi/media/${window.currentChatId}/${message.id}.jpg`;
    }
    
    const isImage = ['image', 'photo', 'sticker'].includes(message.mediaType.toLowerCase());
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
                    onclick="event.stopPropagation(); analyzeMedia(this)">
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
                    onclick="event.stopPropagation(); analyzeMedia(this)">
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
      const hasUnanalyzedMedia = messages.some(m => 
        m.mediaType && ['image', 'photo', 'sticker'].includes(m.mediaType.toLowerCase()) && 
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

/**
 * Analyze multiple media items (batch analysis)
 */
async function analyzeBatchMedia(btn) {
  const chatId = window.currentChatId;
  const messageListContent = document.getElementById('message-list-content');
  
  if (!chatId) {
    alert('No chat selected');
    return;
  }
  
  // Find all unanalyzed media items
  const unanalyzedMedia = [];
  document.querySelectorAll('.analyze-btn:not(.re-analyze)').forEach(btn => {
    const msgId = btn.dataset.msgId;
    const mediaType = btn.dataset.mediaType;
    if (msgId && mediaType) {
      unanalyzedMedia.push({ msgId, mediaType, btn });
    }
  });
  
  if (unanalyzedMedia.length === 0) {
    alert('No unanalyzed media found');
    return;
  }
  
  const confirmed = confirm(`Analyze ${unanalyzedMedia.length} media items? This will use API quota.`);
  if (!confirmed) return;
  
  // Disable batch button
  btn.disabled = true;
  btn.textContent = `Analyzing ${unanalyzedMedia.length} items...`;
  
  let successCount = 0;
  let failCount = 0;
  
  // Process items sequentially to avoid overwhelming the API
  for (const { msgId, mediaType, btn: itemBtn } of unanalyzedMedia) {
    try {
      await analyzeMedia(itemBtn);
      successCount++;
      // Small delay between requests to avoid rate limiting
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (error) {
      console.error(`Failed to analyze ${msgId}:`, error);
      failCount++;
    }
  }
  
  // Re-enable batch button
  btn.disabled = false;
  btn.textContent = 'Batch Analyze';
  
  alert(`Batch analysis complete: ${successCount} succeeded, ${failCount} failed`);
}

/**
 * Analyze media with AI
 */
async function analyzeMedia(btn) {
  const msgId = btn.dataset.msgId;
  const mediaType = btn.dataset.mediaType;
  const chatId = window.currentChatId;
  
  if (!msgId || !chatId) {
    console.error('Missing msgId or chatId');
    return;
  }
  
  // Find the parent wrapper
  const wrapper = btn.closest('.message-media-wrapper');
  if (!wrapper) {
    console.error('Could not find media wrapper');
    return;
  }
  
  // Disable button and show loading state
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'Analyzing...';
  
  // Create or update analysis display
  let analysisDiv = wrapper.querySelector('.media-analysis-result');
  if (!analysisDiv) {
    analysisDiv = document.createElement('div');
    analysisDiv.className = 'media-analysis-result loading';
    analysisDiv.innerHTML = '<div class="analysis-text">Analyzing...</div>';
    wrapper.appendChild(analysisDiv);
  } else {
    analysisDiv.className = 'media-analysis-result loading';
    analysisDiv.innerHTML = '<div class="analysis-text">Analyzing...</div>';
  }
  
  try {
    // Start analysis job
    const result = await YomiApi.analyzeMedia(chatId, msgId, mediaType);
    const { jobId } = result;
    
    // Poll for job completion
    pollAnalysisJob(jobId, btn, analysisDiv, originalText, wrapper);
    
  } catch (err) {
    console.error('Media analysis failed:', err);
    analysisDiv.className = 'media-analysis-result error';
    
    // Check for specific error types
    let errorMsg = err.message || 'Analysis failed';
    if (errorMsg.includes('media unavailable')) {
      errorMsg = 'Media file not available for analysis';
    } else if (errorMsg.includes('quota') || errorMsg.includes('429')) {
      errorMsg = 'Rate limited. Please try again later.';
    } else if (errorMsg.includes('Failed to analyze media with both')) {
      errorMsg = 'Analysis failed with both models. Please try again later.';
    }
    
    analysisDiv.innerHTML = `<div class="analysis-text">Failed: ${escapeHtml(errorMsg)}</div>`;
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/**
 * Extract final answer from verbose AI response
 * Now that we instruct AI to put final answer in last paragraph, we can simplify extraction
 */
function extractFinalAnswer(analysisResult) {
  if (!analysisResult) return '';
  
  // Split by paragraphs (double newlines or single newlines)
  const paragraphs = analysisResult.split(/\n\n+/).filter(p => p.trim());
  if (paragraphs.length === 0) return analysisResult;
  
  // Get the last paragraph (should contain the final clean answer)
  let lastParagraph = paragraphs[paragraphs.length - 1].trim();
  
  // Clean up the last paragraph
  lastParagraph = lastParagraph.replace(/^[\*\-\•]+/, '').trim();
  lastParagraph = lastParagraph.replace(/\([^)]*\)/g, '').trim();
  lastParagraph = lastParagraph.replace(/\s+/g, ' ').trim();
  
  // If the last paragraph is very short, try the second-to-last
  if (lastParagraph.length < 5 && paragraphs.length > 1) {
    let secondLast = paragraphs[paragraphs.length - 2].trim();
    secondLast = secondLast.replace(/^[\*\-\•]+/, '').trim();
    secondLast = secondLast.replace(/\([^)]*\)/g, '').trim();
    secondLast = secondLast.replace(/\s+/g, ' ').trim();
    if (secondLast.length > 5) {
      return secondLast;
    }
  }
  
  return lastParagraph;
}

/**
 * Poll for analysis job completion
 */
async function pollAnalysisJob(jobId, btn, analysisDiv, originalText, container) {
  const maxAttempts = 60; // 2 minutes with 2-second intervals
  let attempts = 0;
  
  const poll = async () => {
    attempts++;
    
    try {
      const data = await YomiApi.getMediaAnalysisStatus(jobId);
      
      console.log(`Polling job ${jobId}, attempt ${attempts}`);
      
      if (!data.ok) {
        throw new Error(data.error || 'Analysis failed');
      }
      
      const job = data.job;
      
      if (job.status === 'completed') {
        analysisDiv.className = 'media-analysis-result';
        const finalAnswer = extractFinalAnswer(job.analysisResult);
        console.log('Original length:', job.analysisResult.length, 'Extracted length:', finalAnswer.length);
        
        // Create toggle and content
        analysisDiv.innerHTML = `
          <div class="analysis-toggle">
            <button class="toggle-btn active" data-view="final">Final Answer</button>
            <button class="toggle-btn" data-view="full">Full Analysis</button>
          </div>
          <div class="analysis-content final-view">
            <div class="analysis-text">${escapeHtml(finalAnswer)}</div>
          </div>
          <div class="analysis-content full-view" style="display: none;">
            <div class="analysis-text">${escapeHtml(job.analysisResult)}</div>
          </div>
        `;
        
        // Add toggle functionality
        const toggleBtns = analysisDiv.querySelectorAll('.toggle-btn');
        toggleBtns.forEach(btn => {
          btn.addEventListener('click', () => {
            toggleBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const view = btn.dataset.view;
            analysisDiv.querySelector('.final-view').style.display = view === 'final' ? 'block' : 'none';
            analysisDiv.querySelector('.full-view').style.display = view === 'full' ? 'block' : 'none';
          });
        });
        
        // Update button to re-analyze
        btn.textContent = '↻ Re-analyze';
        btn.classList.add('re-analyze');
        btn.disabled = false;
        
        // Refresh messages to get updated media_analysis field
        setTimeout(() => {
          const currentChatId = document.getElementById('chat-select').value;
          const currentDate = document.querySelector('.calendar-day.selected')?.dataset.date;
          if (currentChatId && currentDate) {
            renderMessagesForDate(currentChatId, currentDate);
          }
        }, 1000);
        
      } else if (job.status === 'failed') {
        analysisDiv.className = 'media-analysis-result error';
        const errorMsg = job.errorMessage || 'Analysis failed';
        
        // Check for rate limiting
        if (errorMsg.includes('quota') || errorMsg.includes('429') || errorMsg.includes('Too Many Requests')) {
          analysisDiv.innerHTML = `
            <div class="analysis-label">AI Analysis:</div>
            <div class="analysis-text">Rate limited. Please try again later.</div>
          `;
        } else {
          analysisDiv.innerHTML = `
            <div class="analysis-label">AI Analysis:</div>
            <div class="analysis-text">Failed: ${escapeHtml(errorMsg.substring(0, 100))}</div>
          `;
        }
        
        btn.disabled = false;
        btn.textContent = originalText;
        
      } else if (attempts >= maxAttempts) {
        analysisDiv.className = 'media-analysis-result error';
        analysisDiv.innerHTML = `
          <div class="analysis-label">AI Analysis:</div>
          <div class="analysis-text">Analysis timed out</div>
        `;
        btn.disabled = false;
        btn.textContent = originalText;
        
      } else {
        // Continue polling
        setTimeout(poll, 2000);
      }
    } catch (err) {
      console.error('Polling failed:', err);
      analysisDiv.className = 'media-analysis-result error';
      analysisDiv.innerHTML = `
        <div class="analysis-label">AI Analysis:</div>
        <div class="analysis-text">Status check failed: ${escapeHtml(err.message)}</div>
      `;
      btn.disabled = false;
      btn.textContent = originalText;
    }
  };
  
  poll();
}

// Make functions available globally for inter-module communication
window.renderMessagesForDate = renderMessagesForDate;
window.openImage = openImagePopup;
window.openImagePopup = openImagePopup;
window.closeImagePopup = closeImagePopup;
window.analyzeMedia = analyzeMedia;
window.analyzeBatchMedia = analyzeBatchMedia;

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadMessagesForDate,
    renderMessage,
    renderMessageList,
    renderMessagesForDate
  };
}