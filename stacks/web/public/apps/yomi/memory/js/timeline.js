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
  // Enhanced clustering with topic similarity scoring
  const clusters = [];
  const usedIndices = new Set();
  
  // Sort memories by date for chronological clusters
  const sortedMemories = [...memories].sort((a, b) => {
    return new Date(a.timestamp) - new Date(b.timestamp);
  });
  
  sortedMemories.forEach((memory, index) => {
    if (usedIndices.has(index)) return;
    
    // Find related memories using topic similarity
    const relatedMemories = [memory];
    usedIndices.add(index);
    
    // Calculate topic similarity for each other memory
    sortedMemories.forEach((otherMem, otherIndex) => {
      if (usedIndices.has(otherIndex)) return;
      
      const similarity = calculateTopicSimilarity(memory, otherMem);
      if (similarity > 0.3) { // Threshold for clustering
        relatedMemories.push(otherMem);
        usedIndices.add(otherIndex);
      }
    });
    
    // Only create cluster if it has meaningful content
    if (relatedMemories.length > 0) {
      clusters.push({
        title: generateClusterTitle(relatedMemories),
        date: DateUtils.formatDate(memory.timestamp),
        topics: [...new Set(relatedMemories.flatMap(m => m.topics || []))],
        summary: generateClusterSummary(relatedMemories),
        sources: [...new Set(relatedMemories.flatMap(m => m.sources || []))],
        count: relatedMemories.length
      });
    }
  });
  
  return clusters;
}

/**
 * Calculate topic similarity between two memories
 */
function calculateTopicSimilarity(mem1, mem2) {
  const topics1 = new Set(mem1.topics || []);
  const topics2 = new Set(mem2.topics || []);
  
  if (topics1.size === 0 || topics2.size === 0) return 0;
  
  // Jaccard similarity: intersection / union
  const intersection = new Set([...topics1].filter(x => topics2.has(x)));
  const union = new Set([...topics1, ...topics2]);
  
  return intersection.size / union.size;
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
    <div class="memory-cluster" onclick="showMemoryDetail()">
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

/**
 * Render cluster view with topic-based grouping
 */
function renderClusterView(memories) {
  if (!memories || memories.length === 0) {
    return '<div class="empty-state">No memories found</div>';
  }

  // Group memories by topics
  const clusters = createTopicClusters(memories);
  
  let html = '<div class="cluster-grid">';
  
  clusters.forEach(cluster => {
    html += renderClusterCard(cluster);
  });
  
  html += '</div>';
  return html;
}

/**
 * Create topic-based clusters from memories
 */
function createTopicClusters(memories) {
  const clusters = [];
  const usedMemories = new Set();
  
  // Sort memories by date descending
  const sortedMemories = [...memories].sort((a, b) => {
    return new Date(b.timestamp) - new Date(a.timestamp);
  });
  
  // Create clusters based on topic similarity
  sortedMemories.forEach((memory, index) => {
    if (usedMemories.has(index)) return;
    
    // Start new cluster with this memory
    const clusterMemories = [memory];
    usedMemories.add(index);
    
    // Find related memories by topic overlap
    memory.topics.forEach(topic => {
      sortedMemories.forEach((otherMem, otherIndex) => {
        if (!usedMemories.has(otherIndex) && otherMem.topics.includes(topic)) {
          clusterMemories.push(otherMem);
          usedMemories.add(otherIndex);
        }
      });
    });
    
    // Only add cluster if it has meaningful content
    if (clusterMemories.length > 0) {
      clusters.push({
        title: generateClusterTitle(clusterMemories),
        count: clusterMemories.length,
        conversations: getUniqueConversations(clusterMemories),
        dateRange: getClusterDateRange(clusterMemories),
        topics: [...new Set(clusterMemories.flatMap(m => m.topics || []))],
        summary: generateClusterSummary(clusterMemories),
        type: determineClusterType(clusterMemories),
        color: getClusterColor(clusterMemories)
      });
    }
  });
  
  // Sort clusters by memory count (descending)
  return clusters.sort((a, b) => b.count - a.count);
}

/**
 * Render a single cluster card
 */
function renderClusterCard(cluster) {
  const topicsHtml = cluster.topics.map(topic => 
    `<span class="topic-tag">${UiUtils.escapeHtml(topic)}</span>`
  ).join('');
  
  const borderColor = cluster.color || 'var(--accent)';
  
  return `
    <div class="cluster-card" style="border-left: 4px solid ${borderColor}" onclick="showMemoryDetail()">
      <div class="cluster-card-header">
        <div class="cluster-card-title">${UiUtils.escapeHtml(cluster.title)}</div>
        <div class="cluster-card-meta">${cluster.count} memories • ${cluster.conversations} conversations</div>
      </div>
      <div class="cluster-card-date">${cluster.dateRange}</div>
      <div class="cluster-card-topics">
        ${topicsHtml}
      </div>
      <div class="cluster-card-summary">
        ${UiUtils.escapeHtml(cluster.summary)}
      </div>
    </div>
  `;
}

/**
 * Get date range for cluster
 */
function getClusterDateRange(memories) {
  const dates = memories.map(m => new Date(m.timestamp)).sort((a, b) => a - b);
  const start = dates[0];
  const end = dates[dates.length - 1];
  
  if (start.getTime() === end.getTime()) {
    return DateUtils.formatDate(start);
  }
  
  return `${DateUtils.formatDate(start)} - ${DateUtils.formatDate(end)}`;
}

/**
 * Determine cluster type based on memories
 */
function determineClusterType(memories) {
  const types = memories.map(m => m.type);
  const typeCounts = {};
  
  types.forEach(type => {
    typeCounts[type] = (typeCounts[type] || 0) + 1;
  });
  
  const dominantType = Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0];
  return dominantType ? dominantType[0] : 'general';
}

/**
 * Get cluster color based on type
 */
function getClusterColor(memories) {
  const type = determineClusterType(memories);
  const colors = {
    'events': 'var(--accent)',
    'decisions': 'var(--success)',
    'patterns': 'var(--warning)',
    'general': 'var(--danger)'
  };
  return colors[type] || 'var(--accent)';
}

/**
 * Show memory detail modal
 */
function showMemoryDetail(clusterId) {
  // For now, show a simple detail view
  // In production, this would fetch detailed information about the cluster
  const detailModal = document.createElement('div');
  detailModal.className = 'memory-detail-modal';
  detailModal.innerHTML = `
    <div class="memory-detail-content">
      <div class="memory-detail-header">
        <h2>Memory Details</h2>
        <button class="memory-detail-close" onclick="closeMemoryDetail()">&times;</button>
      </div>
      <div class="memory-detail-body">
        <div class="loading">Loading memory details...</div>
      </div>
    </div>
  `;
  
  document.body.appendChild(detailModal);
  
  // In production, fetch detailed data here
  setTimeout(() => {
    const body = detailModal.querySelector('.memory-detail-body');
    body.innerHTML = `
      <div class="memory-detail-section">
        <h3>Summary</h3>
        <p>Detailed memory information would be displayed here. This could include:</p>
        <ul>
          <li>Full conversation context</li>
          <li>Related messages and media</li>
          <li>Timeline of events</li>
          <li>Participant information</li>
          <li>Connected memories</li>
        </ul>
      </div>
      <div class="memory-detail-section">
        <h3>Actions</h3>
        <button class="memory-detail-btn">View in Original Conversation</button>
        <button class="memory-detail-btn">Export Memory</button>
        <button class="memory-detail-btn">Share Memory</button>
      </div>
    `;
  }, 500);
}

/**
 * Close memory detail modal
 */
function closeMemoryDetail() {
  const modal = document.querySelector('.memory-detail-modal');
  if (modal) {
    modal.remove();
  }
}

// Export functions for use in other modules
window.renderTimeline = renderTimeline;
window.groupMemoriesByPeriod = groupMemoriesByPeriod;
window.renderClusterView = renderClusterView;
window.createTopicClusters = createTopicClusters;
window.showMemoryDetail = showMemoryDetail;
window.closeMemoryDetail = closeMemoryDetail;
