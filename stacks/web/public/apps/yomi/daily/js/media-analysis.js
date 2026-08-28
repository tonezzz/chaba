// ============================================================================
// MEDIA ANALYSIS MODULE - Media analysis functionality
// ============================================================================

/**
 * Analyze a single media item
 */
async function analyzeMedia(buttonElement) {
  const msgId = buttonElement.dataset.msgId;
  const mediaType = buttonElement.dataset.mediaType;
  const currentChatId = DailyApp.getState('currentChatId');
  
  if (!msgId || !currentChatId) {
    console.error('Missing msgId or currentChatId for media analysis');
    return;
  }
  
  // Find the message wrapper
  const wrapper = buttonElement.closest('.message-media-wrapper');
  if (!wrapper) {
    console.error('Message wrapper not found');
    return;
  }
  
  // Update button state
  buttonElement.disabled = true;
  buttonElement.textContent = 'Analyzing...';
  
  try {
    // Call API for analysis
    const response = await fetch('/api/yomi/analyze-media', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ chatId: currentChatId, messageId: msgId, mediaType })
    });
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    
    const result = await response.json();
    
    // Update UI with analysis result
    if (result.analysis) {
      // Create analysis result div
      const analysisDiv = document.createElement('div');
      analysisDiv.className = 'media-analysis-result';
      analysisDiv.innerHTML = `
        <div class="analysis-label">AI Analysis:</div>
        <div class="analysis-text">${escapeHtml(result.analysis)}</div>
      `;
      
      // Change button to re-analyze
      buttonElement.className = 'analyze-btn re-analyze';
      buttonElement.textContent = '↻ Re-analyze';
      
      // Insert analysis after button
      buttonElement.parentNode.insertBefore(analysisDiv, buttonElement.nextSibling);
    }
    
  } catch (error) {
    console.error('Media analysis failed:', error);
    buttonElement.textContent = 'Error - retry';
  } finally {
    buttonElement.disabled = false;
  }
}

/**
 * Analyze multiple media items in batch
 */
async function analyzeBatchMedia(buttonElement) {
  const currentChatId = DailyApp.getState('currentChatId');
  const selectedDate = DailyApp.getState('selectedDate');
  
  if (!currentChatId || !selectedDate) {
    console.error('Missing currentChatId or selectedDate for batch analysis');
    return;
  }
  
  // Find all unanalyzed media items
  const unanalyzedButtons = document.querySelectorAll('.analyze-btn:not(.re-analyze)');
  
  if (unanalyzedButtons.length === 0) {
    alert('No unanalyzed media items found');
    return;
  }
  
  if (!confirm(`Analyze ${unanalyzedButtons.length} media items?`)) {
    return;
  }
  
  buttonElement.disabled = true;
  buttonElement.textContent = `Analyzing 0/${unanalyzedButtons.length}...`;
  
  let analyzed = 0;
  for (const btn of unanalyzedButtons) {
    try {
      await analyzeMedia(btn);
      analyzed++;
      buttonElement.textContent = `Analyzing ${analyzed}/${unanalyzedButtons.length}...`;
    } catch (error) {
      console.error('Failed to analyze media item:', error);
    }
  }
  
  buttonElement.textContent = 'Batch Analyze';
  buttonElement.disabled = false;
}

/**
 * Open image popup
 */
function openImagePopup(imageUrl) {
  const popup = document.getElementById('image-popup');
  const popupImg = document.getElementById('image-popup-img');
  
  if (popup && popupImg) {
    popupImg.src = imageUrl;
    popup.classList.add('active');
  }
}

/**
 * Close image popup
 */
function closeImagePopup() {
  const popup = document.getElementById('image-popup');
  if (popup) {
    popup.classList.remove('active');
  }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[m]));
}

// Make functions available globally for HTML onclick handlers
window.analyzeMedia = analyzeMedia;
window.analyzeBatchMedia = analyzeBatchMedia;
window.openImagePopup = openImagePopup;
window.closeImagePopup = closeImagePopup;

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    analyzeMedia,
    analyzeBatchMedia,
    openImagePopup,
    closeImagePopup
  };
}
