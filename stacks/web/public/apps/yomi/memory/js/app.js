// ============================================================================
// APP MODULE - Main application coordination for memory app
// ============================================================================

/**
 * Load collective memory data from API
 */
async function loadCollectiveMemory() {
  try {
    // For now, simulate memory data from daily summaries
    // In production, this would call a dedicated collective memory API
    const conversations = await YomiApi.loadConversations();
    const allMemories = [];
    
    // Generate mock memories from daily summaries for demonstration
    for (const conv of conversations.slice(0, 3)) {
      try {
        const summaries = await YomiApi.loadDailySummaries(conv.id);
        summaries.forEach(summary => {
          if (summary.events && summary.events.length > 0) {
            allMemories.push({
              id: `${conv.id}-${summary.date}`,
              title: summary.events[0] || 'Memory',
              summary: summary.events.slice(1, 3).join('. ') || 'Event summary',
              timestamp: summary.date,
              topics: summary.topics || [],
              sources: [conv.name],
              type: 'events'
            });
          }
          
          if (summary.actions && summary.actions.length > 0) {
            allMemories.push({
              id: `${conv.id}-${summary.date}-action`,
              title: summary.actions[0] || 'Decision',
              summary: summary.actions.slice(1, 3).join('. ') || 'Action summary',
              timestamp: summary.date,
              topics: summary.topics || [],
              sources: [conv.name],
              type: 'decisions'
            });
          }
        });
      } catch (error) {
        console.error(`Failed to load summaries for ${conv.id}:`, error);
      }
    }
    
    window.memoryState.memories = allMemories;
    return allMemories;
    
  } catch (error) {
    console.error('Failed to load collective memory:', error);
    return [];
  }
}

/**
 * Initialize the application
 */
async function init() {
  try {
    // Set API base URL for Yomi API
    ApiUtils.baseUrl = 'http://tony-omen.local:3000';
    
    // Load conversation filters
    await loadConversationFilters();
    
    // Load topic filters
    await loadTopicFilters();
    
    // Load memory data
    const memories = await loadCollectiveMemory();
    
    // Render initial timeline
    const timelineContent = document.getElementById('timeline-content');
    if (timelineContent) {
      timelineContent.innerHTML = renderTimeline(memories);
    }
    
    // Update insights
    updateInsightsPanel();
    
    // Update stats
    updateStats(memories);
    
    // Set up event listeners
    setupEventListeners();
    
  } catch (error) {
    console.error('Failed to initialize memory app:', error);
    const timelineContent = document.getElementById('timeline-content');
    if (timelineContent) {
      timelineContent.innerHTML = `<div class="error">Error: ${UiUtils.escapeHtml(error.message)}</div>`;
    }
  }
}

/**
 * Set up event listeners
 */
function setupEventListeners() {
  // Search input
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      window.memoryState.filters.search = e.target.value;
      applyFilters();
    });
  }
  
  // Date range inputs
  const startDateInput = document.getElementById('start-date');
  const endDateInput = document.getElementById('end-date');
  
  if (startDateInput) {
    startDateInput.addEventListener('change', (e) => {
      window.memoryState.filters.startDate = e.target.value;
      applyFilters();
    });
  }
  
  if (endDateInput) {
    endDateInput.addEventListener('change', (e) => {
      window.memoryState.filters.endDate = e.target.value;
      applyFilters();
    });
  }
  
  // Memory type filters
  const memoryTypeCheckboxes = document.querySelectorAll('.filter-section:last-child input[type="checkbox"]');
  memoryTypeCheckboxes.forEach(checkbox => {
    checkbox.addEventListener('change', (e) => {
      const value = e.target.value;
      const isChecked = e.target.checked;
      
      if (isChecked) {
        window.memoryState.filters.memoryTypes.push(value);
      } else {
        window.memoryState.filters.memoryTypes = window.memoryState.filters.memoryTypes.filter(t => t !== value);
      }
      
      applyFilters();
    });
  });
  
  // View toggle buttons
  const timelineButtons = document.querySelectorAll('.timeline-btn');
  timelineButtons.forEach(button => {
    button.addEventListener('click', (e) => {
      const view = e.target.dataset.view;
      
      // Update active state
      timelineButtons.forEach(btn => btn.classList.remove('active'));
      e.target.classList.add('active');
      
      // Handle view change
      if (view === 'timeline') {
        const memories = window.memoryState.memories;
        const timelineContent = document.getElementById('timeline-content');
        if (timelineContent) {
          timelineContent.innerHTML = renderTimeline(memories);
        }
      } else if (view === 'clusters') {
        // Show clusters view
        const memories = window.memoryState.memories;
        const timelineContent = document.getElementById('timeline-content');
        if (timelineContent) {
          timelineContent.innerHTML = renderClusterView(memories);
        }
      } else if (view === 'network') {
        // Show network view (placeholder for now)
        const timelineContent = document.getElementById('timeline-content');
        if (timelineContent) {
          timelineContent.innerHTML = '<div class="empty-state">Network view coming soon</div>';
        }
      }
    });
  });
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
    loadCollectiveMemory,
    init,
    setupEventListeners
  };
}
