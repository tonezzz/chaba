// ============================================================================
// TIMELINE MODULE - Timeline view rendering and logic
// ============================================================================

/**
 * Render timeline view with memory clusters organized by time periods
 */
function renderTimeline(memories) {
  if (!memories || memories.length === 0) {
    return '<div class="empty-state">No memories found</div>';
  }

  // Group memories by time periods (weeks)
  const periods = groupMemoriesByPeriod(memories);
  
  let html = '<div class="timeline">';
  
  periods.forEach(period => {
    html += `
      <div class="timeline-period">
        <div class="timeline-period-marker"></div>
        <div class="timeline-period-header">
          <div class="timeline-period-title">${period.title}</div>
          <div class="timeline-period-subtitle">${period.subtitle}</div>
        </div>
    `;
    
    period.clusters.forEach(cluster => {
      html += renderMemoryCluster(cluster);
    });
    
    html += '</div>';
  });
  
  html += '</div>';
  return html;
}

/**
 * Group memories by time periods (weeks)
 */
function groupMemoriesByPeriod(memories) {
  const periods = [];
  
  // Sort memories by date descending
  const sortedMemories = [...memories].sort((a, b) => {
    return new Date(b.timestamp) - new Date(a.timestamp);
  });
  
  // Group by week
  const weekGroups = {};
  sortedMemories.forEach(memory => {
    const date = new Date(memory.timestamp);
    const weekStart = getWeekStart(date);
    const weekKey = weekStart.toISOString().split('T')[0];
    
    if (!weekGroups[weekKey]) {
      weekGroups[weekKey] = [];
    }
    weekGroups[weekKey].push(memory);
  });
  
  // Convert to periods
  Object.keys(weekGroups).sort().reverse().forEach(weekKey => {
    const weekMemories = weekGroups[weekKey];
    const weekStart = new Date(weekKey);
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekEnd.getDate() + 6);
    
    periods.push({
      title: formatDateRange(weekStart, weekEnd),
      subtitle: `${weekMemories.length} memories • ${getUniqueConversations(weekMemories)} conversations`,
      clusters: createMemoryClusters(weekMemories)
    });
  });
  
  return periods;
}

/**
 * Create memory clusters from grouped memories
 */
function createMemoryClusters(memories) {
  // Simple clustering by topic similarity
  const clusters = [];
  const usedIndices = new Set();
  
  memories.forEach((memory, index) => {
    if (usedIndices.has(index)) return;
    
    // Find related memories by topic overlap
    const relatedMemories = [memory];
    usedIndices.add(index);
    
    memory.topics.forEach(topic => {
      memories.forEach((otherMem, otherIndex) => {
        if (!usedIndices.has(otherIndex) && otherMem.topics.includes(topic)) {
          relatedMemories.push(otherMem);
          usedIndices.add(otherIndex);
        }
      });
    });
    
    clusters.push({
      title: generateClusterTitle(relatedMemories),
      date: DateUtils.formatDate(memory.timestamp),
      topics: [...new Set(relatedMemories.flatMap(m => m.topics || []))],
      summary: generateClusterSummary(relatedMemories),
      sources: [...new Set(relatedMemories.flatMap(m => m.sources || []))]
    });
  });
  
  return clusters;
}

/**
 * Render a single memory cluster
 */
function renderMemoryCluster(cluster) {
  const topicsHtml = cluster.topics.map(topic => 
    `<span class="topic-tag">${UiUtils.escapeHtml(topic)}</span>`
  ).join('');
  
  const sourcesHtml = cluster.sources.map(source => 
    `<span class="source-chip">${UiUtils.escapeHtml(source)}</span>`
  ).join('');
  
  return `
    <div class="memory-cluster">
      <div class="memory-cluster-header">
        <div class="memory-cluster-title">${UiUtils.escapeHtml(cluster.title)}</div>
        <div class="memory-cluster-meta">${cluster.date}</div>
      </div>
      <div class="memory-cluster-topics">
        ${topicsHtml}
      </div>
      <div class="memory-cluster-summary">
        ${UiUtils.escapeHtml(cluster.summary)}
      </div>
      <div class="memory-cluster-sources">
        ${sourcesHtml}
      </div>
    </div>
  `;
}

/**
 * Get week start date for a given date
 */
function getWeekStart(date) {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day;
  return new Date(d.setDate(diff));
}

/**
 * Format date range for display
 */
function formatDateRange(start, end) {
  const options = { month: 'long', day: 'numeric' };
  const startStr = start.toLocaleDateString(undefined, options);
  const endStr = end.toLocaleDateString(undefined, options);
  
  if (start.getMonth() === end.getMonth()) {
    return `${DateUtils.getMonthName(start)} ${start.getDate()} - ${end.getDate()}, ${start.getFullYear()}`;
  }
  
  return `${startStr} - ${endStr}`;
}

/**
 * Get unique conversation count
 */
function getUniqueConversations(memories) {
  const conversations = new Set();
  memories.forEach(memory => {
    (memory.sources || []).forEach(source => conversations.add(source));
  });
  return conversations.size;
}

/**
 * Generate cluster title from memories
 */
function generateClusterTitle(memories) {
  if (memories.length === 1) {
    return memories[0].title || 'Memory';
  }
  
  // Use most common topic as title
  const topicCounts = {};
  memories.forEach(memory => {
    (memory.topics || []).forEach(topic => {
      topicCounts[topic] = (topicCounts[topic] || 0) + 1;
    });
  });
  
  const topTopic = Object.entries(topicCounts).sort((a, b) => b[1] - a[1])[0];
  return topTopic ? topTopic[0] : 'Memory Cluster';
}

/**
 * Generate cluster summary from memories
 */
function generateClusterSummary(memories) {
  if (memories.length === 1) {
    return memories[0].summary || '';
  }
  
  // Combine summaries from multiple memories
  const summaries = memories
    .map(m => m.summary || '')
    .filter(s => s.length > 0)
    .slice(0, 3); // Take first 3 summaries
  
  if (summaries.length === 0) {
    return `${memories.length} related memories`;
  }
  
  return summaries.join(' ');
}

// Export functions for use in other modules
window.renderTimeline = renderTimeline;
window.groupMemoriesByPeriod = groupMemoriesByPeriod;
