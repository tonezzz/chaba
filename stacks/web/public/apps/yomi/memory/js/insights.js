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
  
  const patterns = [];
  
  // Pattern 1: Weekend vs weekday activity
  const weekendActivity = memories.filter(m => {
    const date = new Date(m.timestamp);
    const day = date.getDay();
    return day === 0 || day === 6;
  }).length;
  
  const weekdayActivity = memories.length - weekendActivity;
  
  if (weekendActivity > weekdayActivity * 1.5) {
    patterns.push('Higher activity on weekends (personal/social focus)');
  } else if (weekdayActivity > weekendActivity * 1.5) {
    patterns.push('Higher activity on weekdays (work-related focus)');
  }
  
  // Pattern 2: Time of day analysis
  const morningActivity = memories.filter(m => {
    const hour = new Date(m.timestamp).getHours();
    return hour >= 6 && hour < 12;
  }).length;
  
  const afternoonActivity = memories.filter(m => {
    const hour = new Date(m.timestamp).getHours();
    return hour >= 12 && hour < 18;
  }).length;
  
  const eveningActivity = memories.filter(m => {
    const hour = new Date(m.timestamp).getHours();
    return hour >= 18 && hour < 24;
  }).length;
  
  const peakTime = Math.max(morningActivity, afternoonActivity, eveningActivity);
  if (peakTime === morningActivity && morningActivity > memories.length * 0.4) {
    patterns.push('Peak activity in morning hours');
  } else if (peakTime === afternoonActivity && afternoonActivity > memories.length * 0.4) {
    patterns.push('Peak activity in afternoon hours');
  } else if (peakTime === eveningActivity && eveningActivity > memories.length * 0.4) {
    patterns.push('Peak activity in evening hours');
  }
  
  // Pattern 3: Topic evolution over time
  const topicEvolution = analyzeTopicEvolution(memories);
  if (topicEvolution) {
    patterns.push(topicEvolution);
  }
  
  // Pattern 4: Conversation diversity
  const uniqueConversations = new Set(memories.flatMap(m => m.sources || [])).size;
  if (uniqueConversations > 3) {
    patterns.push(`High conversation diversity (${uniqueConversations} conversations)`);
  } else if (uniqueConversations === 1) {
    patterns.push('Single conversation focus');
  }
  
  if (patterns.length === 0) {
    return 'Balanced activity patterns detected across time and topics.';
  }
  
  return patterns.join('; ');
}

/**
 * Analyze topic evolution over time
 */
function analyzeTopicEvolution(memories) {
  if (memories.length < 5) return null;
  
  // Sort memories by date
  const sortedMemories = [...memories].sort((a, b) => 
    new Date(a.timestamp) - new Date(b.timestamp)
  );
  
  // Split into first half and second half
  const midPoint = Math.floor(sortedMemories.length / 2);
  const firstHalf = sortedMemories.slice(0, midPoint);
  const secondHalf = sortedMemories.slice(midPoint);
  
  // Get topic frequencies for each half
  const firstTopics = getTopicFrequencies(firstHalf);
  const secondTopics = getTopicFrequencies(secondHalf);
  
  // Find emerging topics (new in second half)
  const emergingTopics = Object.keys(secondTopics).filter(topic => 
    !firstTopics[topic] || secondTopics[topic] > firstTopics[topic] * 1.5
  );
  
  // Find declining topics (decreased in second half)
  const decliningTopics = Object.keys(firstTopics).filter(topic => 
    secondTopics[topic] && firstTopics[topic] > secondTopics[topic] * 1.5
  );
  
  if (emergingTopics.length > 0) {
    return `Emerging focus: ${emergingTopics.slice(0, 2).join(', ')}`;
  } else if (decliningTopics.length > 0) {
    return `Declining focus: ${decliningTopics.slice(0, 2).join(', ')}`;
  }
  
  return null;
}

/**
 * Get topic frequencies from memories
 */
function getTopicFrequencies(memories) {
  const frequencies = {};
  memories.forEach(memory => {
    (memory.topics || []).forEach(topic => {
      frequencies[topic] = (frequencies[topic] || 0) + 1;
    });
  });
  return frequencies;
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
