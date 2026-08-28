// ============================================================================
// NETWORK MODULE - Network view visualization and relationship analysis
// ============================================================================

/**
 * Calculate topic overlap between two conversations
 */
function calculateTopicOverlap(conv1, conv2) {
  const topics1 = new Set(conv1.topics || []);
  const topics2 = new Set(conv2.topics || []);
  
  if (topics1.size === 0 || topics2.size === 0) return 0;
  
  // Jaccard similarity
  const intersection = new Set([...topics1].filter(x => topics2.has(x)));
  const union = new Set([...topics1, ...topics2]);
  
  return intersection.size / union.size;
}

/**
 * Calculate time proximity between two conversations
 */
function calculateTimeProximity(conv1, conv2) {
  if (!conv1.lastMessageTime || !conv2.lastMessageTime) return 0;
  
  const time1 = parseInt(conv1.lastMessageTime);
  const time2 = parseInt(conv2.lastMessageTime);
  
  if (isNaN(time1) || isNaN(time2)) return 0;
  
  const timeDiff = Math.abs(time1 - time2);
  const maxDiff = 7 * 24 * 60 * 60 * 1000; // 7 days in milliseconds
  
  // Normalize to 0-1 range (closer in time = higher proximity)
  return Math.max(0, 1 - (timeDiff / maxDiff));
}

/**
 * Calculate overall relationship strength between two conversations
 */
function calculateRelationshipStrength(conv1, conv2) {
  const topicOverlap = calculateTopicOverlap(conv1, conv2);
  const timeProximity = calculateTimeProximity(conv1, conv2);
  
  // Weighted average (topic overlap is more important)
  return (topicOverlap * 0.7) + (timeProximity * 0.3);
}

/**
 * Build network graph from conversations and memories
 */
function buildNetworkGraph(conversations, memories) {
  const nodes = conversations.map(conv => {
    // Count memories for this conversation
    const convMemories = memories.filter(m => 
      (m.sources || []).includes(conv.name)
    );
    
    // Extract topics from memories
    const topics = new Set();
    convMemories.forEach(memory => {
      (memory.topics || []).forEach(topic => topics.add(topic));
    });
    
    return {
      id: conv.id,
      name: conv.name,
      category: conv.category || 'Other',
      memoryCount: convMemories.length,
      messageCount: conv.unread || 0, // Using unread as proxy for activity
      topics: Array.from(topics),
      size: Math.max(30, Math.min(80, 30 + convMemories.length * 5))
    };
  });
  
  // Build edges based on relationship strength
  const edges = [];
  const minStrength = 0.3; // Minimum relationship strength to show edge
  
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const conv1 = conversations[i];
      const conv2 = conversations[j];
      
      const strength = calculateRelationshipStrength(conv1, conv2);
      
      if (strength >= minStrength) {
        edges.push({
          source: nodes[i].id,
          target: nodes[j].id,
          weight: strength,
          type: strength > 0.6 ? 'strong' : strength > 0.4 ? 'medium' : 'weak'
        });
      }
    }
  }
  
  return { nodes, edges };
}

/**
 * Simple force-directed layout calculation
 */
function calculateForceLayout(nodes, edges, width, height) {
  // Check if we have saved positions
  const savedPositions = localStorage.getItem('networkNodePositions');
  if (savedPositions) {
    try {
      const parsed = JSON.parse(savedPositions);
      // Check if the saved positions match our current nodes
      if (parsed.length === nodes.length) {
        return nodes.map((node, i) => ({
          ...node,
          x: parsed[i].x,
          y: parsed[i].y,
          vx: 0,
          vy: 0
        }));
      }
    } catch (e) {
      // If parsing fails, continue with calculation
    }
  }
  
  const positionedNodes = nodes.map(node => ({
    ...node,
    x: Math.random() * (width - 100) + 50,
    y: Math.random() * (height - 100) + 50,
    vx: 0,
    vy: 0
  }));
  
  // Simple force simulation
  const iterations = 50;
  const repulsion = 5000;
  const attraction = 0.01;
  const damping = 0.9;
  
  for (let iter = 0; iter < iterations; iter++) {
    // Repulsion between all nodes
    for (let i = 0; i < positionedNodes.length; i++) {
      for (let j = i + 1; j < positionedNodes.length; j++) {
        const node1 = positionedNodes[i];
        const node2 = positionedNodes[j];
        
        const dx = node2.x - node1.x;
        const dy = node2.y - node1.y;
        const distance = Math.sqrt(dx * dx + dy * dy) || 1;
        
        const force = repulsion / (distance * distance);
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        
        node1.vx -= fx;
        node1.vy -= fy;
        node2.vx += fx;
        node2.vy += fy;
      }
    }
    
    // Attraction along edges
    edges.forEach(edge => {
      const source = positionedNodes.find(n => n.id === edge.source);
      const target = positionedNodes.find(n => n.id === edge.target);
      
      if (source && target) {
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const distance = Math.sqrt(dx * dx + dy * dy) || 1;
        
        const force = attraction * edge.weight * distance;
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        
        source.vx += fx;
        source.vy += fy;
        target.vx -= fx;
        target.vy -= fy;
      }
    });
    
    // Apply velocity and damping
    positionedNodes.forEach(node => {
      node.x += node.vx;
      node.y += node.vy;
      node.vx *= damping;
      node.vy *= damping;
      
      // Keep within bounds
      node.x = Math.max(50, Math.min(width - 50, node.x));
      node.y = Math.max(50, Math.min(height - 50, node.y));
    });
  }
  
  // Save positions for next time
  const positionsToSave = positionedNodes.map(n => ({ id: n.id, x: n.x, y: n.y }));
  localStorage.setItem('networkNodePositions', JSON.stringify(positionsToSave));
  
  return positionedNodes;
}

/**
 * Render network view
 */
function renderNetworkView(conversations, memories) {
  if (!conversations || conversations.length === 0) {
    return '<div class="empty-state">No conversations to visualize</div>';
  }
  
  const { nodes, edges } = buildNetworkGraph(conversations, memories);
  
  // Use larger canvas dimensions for better layout
  const canvasWidth = 1400;
  const canvasHeight = 800;
  
  const positionedNodes = calculateForceLayout(nodes, edges, canvasWidth, canvasHeight);
  
  let html = `
    <div class="network-toolbar">
      <button class="network-btn active" data-layout="force">Force Layout</button>
      <button class="network-btn" data-layout="circular">Circular Layout</button>
      <button class="network-btn" data-layout="reset" onclick="resetNetworkLayout()">Reset View</button>
    </div>
    
    <div class="network-canvas-inner" style="width: 100%; height: 600px; position: relative; background: #f8fafc; border-radius: 0.25rem; overflow: auto;">
  `;
  
  // Render edges
  edges.forEach(edge => {
    const source = positionedNodes.find(n => n.id === edge.source);
    const target = positionedNodes.find(n => n.id === edge.target);
    
    if (source && target) {
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const length = Math.sqrt(dx * dx + dy * dy);
      const angle = Math.atan2(dy, dx) * 180 / Math.PI;
      
      html += `
        <div class="edge ${edge.type}" 
             style="width: ${length}px; left: ${source.x}px; top: ${source.y}px; transform: rotate(${angle}deg);">
        </div>
      `;
    }
  });
  
  // Render nodes
  positionedNodes.forEach(node => {
    const categoryClass = node.category.toLowerCase();
    html += `
      <div class="node ${categoryClass}" 
           style="width: ${node.size}px; height: ${node.size}px; left: ${node.x - node.size/2}px; top: ${node.y - node.size/2}px;"
           onclick="selectNetworkNode('${node.id}')">
        ${node.name.substring(0, 2)}
        <div class="node-label">${UiUtils.escapeHtml(node.name)}</div>
      </div>
    `;
  });
  
  html += '</div>';
  
  return html;
}

/**
 * Reset network layout
 */
function resetNetworkLayout() {
  localStorage.removeItem('networkNodePositions');
  // Re-render with new layout
  const conversations = window.memoryState.conversations;
  const memories = window.memoryState.memories;
  const networkCanvas = document.getElementById('network-canvas');
  if (networkCanvas) {
    networkCanvas.innerHTML = renderNetworkView(conversations, memories);
  }
}

/**
 * Select a network node and show details
 */
function selectNetworkNode(nodeId) {
  const conversations = window.memoryState.conversations;
  const memories = window.memoryState.memories;
  
  const conversation = conversations.find(c => c.id === nodeId);
  if (!conversation) return;
  
  // Find related conversations
  const relatedConversations = conversations
    .filter(c => c.id !== nodeId)
    .map(c => ({
      name: c.name,
      strength: calculateRelationshipStrength(conversation, c)
    }))
    .filter(r => r.strength > 0.3)
    .sort((a, b) => b.strength - a.strength)
    .slice(0, 5);
  
  // Find memories for this conversation
  const convMemories = memories.filter(m => 
    (m.sources || []).includes(conversation.name)
  );
  
  // Extract topics
  const topics = new Set();
  convMemories.forEach(memory => {
    (memory.topics || []).forEach(topic => topics.add(topic));
  });
  
  // Update details panel
  const detailsPanel = document.querySelector('.network-details');
  if (detailsPanel) {
    detailsPanel.innerHTML = `
      <div class="detail-card">
        <h3>Selected Node</h3>
        <div class="detail-content">
          <strong>${UiUtils.escapeHtml(conversation.name)}</strong><br>
          <span style="color: var(--muted);">${convMemories.length} memories • ${relatedConversations.length} connections</span>
        </div>
      </div>
      
      <div class="detail-card">
        <h3>Connections</h3>
        <div class="connection-list">
          ${relatedConversations.map(rel => `
            <div class="connection-item">
              <span>${UiUtils.escapeHtml(rel.name)}</span>
              <span class="connection-strength">${Math.round(rel.strength * 100)}%</span>
            </div>
          `).join('')}
        </div>
      </div>
      
      <div class="detail-card">
        <h3>Shared Topics</h3>
        <div class="detail-content">
          <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">
            ${Array.from(topics).map(topic => 
              `<span class="topic-tag">${UiUtils.escapeHtml(topic)}</span>`
            ).join('')}
          </div>
        </div>
      </div>
      
      <div class="detail-card">
        <h3>Network Statistics</h3>
        <div class="detail-content">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem;">
            <div style="text-align: center; background: var(--bg); padding: 0.5rem; border-radius: 0.25rem;">
              <div style="font-size: 1.25rem; font-weight: 600; color: var(--accent);">${conversations.length}</div>
              <div style="font-size: 0.7rem; color: var(--muted);">Total Nodes</div>
            </div>
            <div style="text-align: center; background: var(--bg); padding: 0.5rem; border-radius: 0.25rem;">
              <div style="font-size: 1.25rem; font-weight: 600; color: var(--success);">${memories.length}</div>
              <div style="font-size: 0.7rem; color: var(--muted);">Total Memories</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }
}

// Export functions for use in other modules
window.renderNetworkView = renderNetworkView;
window.selectNetworkNode = selectNetworkNode;
window.calculateRelationshipStrength = calculateRelationshipStrength;
window.resetNetworkLayout = resetNetworkLayout;
