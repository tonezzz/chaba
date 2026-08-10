// ============================================================================
// INSIGHTS MODULE - Insights panel logic and analysis
// ============================================================================

/**
 * Generate key insights from memories
 */
function generateKeyInsights(memories) {
  if (!memories || memories.length === 0) {
    return 'No insights available yet.';
  }
  
  // Simple insight generation based on topic frequency
  const topicCounts = {};
  memories.forEach(memory => {
    (memory.topics || []).forEach(topic => {
      topicCounts[topic] = (topicCounts[topic] || 0) + 1;
    });
  });
  
  const sortedTopics = Object.entries(topicCounts).sort((a, b) => b[1] - a[1]);
  
  if (sortedTopics.length > 0) {
    const topTopic = sortedTopics[0];
    const count = sortedTopics[0][1];
    const total = memories.length;
    const percentage = Math.round((count / total) * 100);
    
    return `"${topTopic[0]}" appears in ${percentage}% of memories (${count} out of ${total}), indicating this is a primary theme in your conversations.`;
  }
  
  return 'Analyzing conversation patterns...';
}

/**
 * Detect patterns in memories
 */
function detectPatterns(memories) {
  if (!memories || memories.length < 3) {
    return 'Need more memories to detect patterns.';
  }
  
  // Simple pattern detection: check for weekend vs weekday activity
  const weekendActivity = memories.filter(m => {
    const date = new Date(m.timestamp);
    const day = date.getDay();
    return day === 0 || day === 6; // Sunday or Saturday
  }).length;
  
  const weekdayActivity = memories.length - weekendActivity;
  
  if (weekendActivity > weekdayActivity * 1.5) {
    return 'Higher activity detected on weekends, suggesting this is primarily personal/social time.';
  } else if (weekdayActivity > weekendActivity * 1.5) {
    return 'Higher activity detected on weekdays, suggesting work-related conversations dominate.';
  }
  
  return 'Balanced activity across weekdays and weekends.';
}

/**
 * Get trending topics
 */
function getTrendingTopics(memories) {
  if (!memories || memories.length === 0) {
    return '<div style="color: var(--muted);">No topics available</div>';
  }
  
  const topicCounts = {};
  memories.forEach(memory => {
    (memory.topics || []).forEach(topic => {
      topicCounts[topic] = (topicCounts[topic] || 0) + 1;
    });
  });
  
  const sortedTopics = Object.entries(topicCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
  
  if (sortedTopics.length === 0) {
    return '<div style="color: var(--muted);">No topics available</div>';
  }
  
  return sortedTopics.map(([topic, count]) => 
    `<span class="topic-tag">${UiUtils.escapeHtml(topic)} (${count})</span>`
  ).join('');
}

/**
 * Get recent activity
 */
function getRecentActivity(memories) {
  if (!memories || memories.length === 0) {
    return '<div style="font-size: 0.75rem; color: var(--muted);">No recent activity</div>';
  }
  
  // Sort by date descending and take last 5
  const recentMemories = [...memories]
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, 5);
  
  return recentMemories.map(memory => {
    const date = DateUtils.formatDate(memory.timestamp);
    const title = memory.title || 'Memory';
    return `<div>• ${date}: ${UiUtils.escapeHtml(title)}</div>`;
  }).join('');
}

/**
 * Update insights panel
 */
function updateInsightsPanel() {
  const memories = window.memoryState.memories;
  
  // Update key insight
  const keyInsightContent = document.getElementById('key-insight-content');
  if (keyInsightContent) {
    keyInsightContent.textContent = generateKeyInsights(memories);
  }
  
  // Update pattern
  const patternContent = document.getElementById('pattern-content');
  if (patternContent) {
    patternContent.textContent = detectPatterns(memories);
  }
  
  // Update trending topics
  const trendingTopics = document.getElementById('trending-topics');
  if (trendingTopics) {
    trendingTopics.innerHTML = getTrendingTopics(memories);
  }
  
  // Update recent activity
  const recentActivity = document.getElementById('recent-activity');
  if (recentActivity) {
    recentActivity.innerHTML = getRecentActivity(memories);
  }
}

// Export functions for use in other modules
window.generateKeyInsights = generateKeyInsights;
window.detectPatterns = detectPatterns;
window.getTrendingTopics = getTrendingTopics;
window.getRecentActivity = getRecentActivity;
window.updateInsightsPanel = updateInsightsPanel;
