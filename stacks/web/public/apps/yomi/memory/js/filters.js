// ============================================================================
// FILTERS MODULE - Filter panel logic and management
// ============================================================================

/**
 * Load conversations and populate conversation filters
 */
async function loadConversationFilters() {
  try {
    const conversations = await YomiApi.loadConversations();
    window.memoryState.conversations = conversations;
    
    const filterContainer = document.getElementById('conversation-filters');
    if (!filterContainer) return;
    
    // Group conversations by category
    const categories = {
      'Family': [],
      'Work': [],
      'Personal': [],
      'Promo': [],
      'Official': [],
      'Group': [],
      'Other': []
    };
    
    conversations.forEach(conv => {
      const category = conv.category || 'Other';
      if (categories[category]) {
        categories[category].push(conv);
      } else {
        categories['Other'].push(conv);
      }
    });
    
    // Render filters
    let html = '';
    Object.entries(categories).forEach(([category, convs]) => {
      if (convs.length === 0) return;
      
      html += `<label class="filter-checkbox">
        <input type="checkbox" checked value="${category.toLowerCase()}" data-type="conversation">
        ${category} (${convs.length})
      </label>`;
      
      // Add individual conversation filters for categories with multiple conversations
      if (convs.length > 1) {
        convs.forEach(conv => {
          html += `<label class="filter-checkbox" style="margin-left: 1rem;">
            <input type="checkbox" value="${conv.id}" data-type="conversation" data-parent="${category.toLowerCase()}">
            ${UiUtils.escapeHtml(conv.name)}
          </label>`;
        });
      }
    });
    
    filterContainer.innerHTML = html;
    
    // Add event listeners
    filterContainer.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
      checkbox.addEventListener('change', handleFilterChange);
    });
    
  } catch (error) {
    console.error('Failed to load conversation filters:', error);
  }
}

/**
 * Load topics from existing memories and populate topic filters
 */
async function loadTopicFilters() {
  try {
    // For now, use common topics - in production this would come from API
    const commonTopics = [
      'Health', 'Finance', 'Travel', 'Work', 'Family', 
      'Projects', 'Decisions', 'Events', 'Planning', 'Social'
    ];
    
    const filterContainer = document.getElementById('topic-filters');
    if (!filterContainer) return;
    
    let html = '';
    commonTopics.forEach(topic => {
      html += `<label class="filter-checkbox">
        <input type="checkbox" value="${topic.toLowerCase()}" data-type="topic">
        ${topic}
      </label>`;
    });
    
    filterContainer.innerHTML = html;
    
    // Add event listeners
    filterContainer.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
      checkbox.addEventListener('change', handleFilterChange);
    });
    
  } catch (error) {
    console.error('Failed to load topic filters:', error);
  }
}

/**
 * Handle filter changes
 */
function handleFilterChange(event) {
  const checkbox = event.target;
  const filterType = checkbox.dataset.type;
  const value = checkbox.value;
  const isChecked = checkbox.checked;
  
  if (filterType === 'conversation') {
    if (isChecked) {
      window.memoryState.filters.conversations.push(value);
    } else {
      window.memoryState.filters.conversations = window.memoryState.filters.conversations.filter(v => v !== value);
    }
  } else if (filterType === 'topic') {
    if (isChecked) {
      window.memoryState.filters.topics.push(value);
    } else {
      window.memoryState.filters.topics = window.memoryState.filters.topics.filter(t => t !== value);
    }
  }
  
  // Trigger re-render
  if (window.applyFilters) {
    window.applyFilters();
  }
}

/**
 * Apply current filters to memories
 */
function applyFilters() {
  const { search, startDate, endDate, conversations, topics, memoryTypes } = window.memoryState.filters;
  
  let filteredMemories = [...window.memoryState.memories];
  
  // Apply search filter
  if (search) {
    const searchLower = search.toLowerCase();
    filteredMemories = filteredMemories.filter(memory => {
      return (memory.title || '').toLowerCase().includes(searchLower) ||
             (memory.summary || '').toLowerCase().includes(searchLower) ||
             (memory.topics || []).some(t => t.toLowerCase().includes(searchLower));
    });
  }
  
  // Apply date range filter
  if (startDate) {
    const start = new Date(startDate);
    filteredMemories = filteredMemories.filter(memory => {
      return new Date(memory.timestamp) >= start;
    });
  }
  
  if (endDate) {
    const end = new Date(endDate);
    end.setHours(23, 59, 59, 999);
    filteredMemories = filteredMemories.filter(memory => {
      return new Date(memory.timestamp) <= end;
    });
  }
  
  // Apply conversation filter
  if (conversations.length > 0) {
    filteredMemories = filteredMemories.filter(memory => {
      const memoryConversations = (memory.sources || []).map(s => s.toLowerCase());
      return conversations.some(conv => memoryConversations.includes(conv));
    });
  }
  
  // Apply topic filter
  if (topics.length > 0) {
    filteredMemories = filteredMemories.filter(memory => {
      const memoryTopics = (memory.topics || []).map(t => t.toLowerCase());
      return topics.some(topic => memoryTopics.includes(topic));
    });
  }
  
  // Apply memory type filter
  if (memoryTypes.length > 0) {
    filteredMemories = filteredMemories.filter(memory => {
      return memoryTypes.includes(memory.type);
    });
  }
  
  // Update timeline with filtered memories
  const timelineContent = document.getElementById('timeline-content');
  if (timelineContent) {
    timelineContent.innerHTML = renderTimeline(filteredMemories);
  }
  
  // Update stats
  updateStats(filteredMemories);
}

/**
 * Update statistics display
 */
function updateStats(memories) {
  const totalMemoriesEl = document.getElementById('total-memories');
  const totalConversationsEl = document.getElementById('total-conversations');
  
  if (totalMemoriesEl) {
    totalMemoriesEl.textContent = memories.length;
  }
  
  if (totalConversationsEl) {
    const uniqueConversations = new Set();
    memories.forEach(memory => {
      (memory.sources || []).forEach(source => uniqueConversations.add(source));
    });
    totalConversationsEl.textContent = uniqueConversations.size;
  }
  
  // Update memory state stats
  window.memoryState.stats.totalMemories = memories.length;
  window.memoryState.stats.totalConversations = totalConversationsEl ? 
    new Set(memories.flatMap(m => m.sources || [])).size : 0;
}

// Export functions for use in other modules
window.loadConversationFilters = loadConversationFilters;
window.loadTopicFilters = loadTopicFilters;
window.handleFilterChange = handleFilterChange;
window.applyFilters = applyFilters;
window.updateStats = updateStats;
