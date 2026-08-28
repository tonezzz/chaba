// ============================================================================
// EXPORT MODULE - Memory export functionality
// ============================================================================

/**
 * Export memories as JSON
 */
function exportMemoriesAsJSON(memories, filename = 'memories.json') {
  const exportData = {
    exportDate: new Date().toISOString(),
    totalMemories: memories.length,
    memories: memories.map(memory => ({
      id: memory.id,
      title: memory.title,
      summary: memory.summary,
      timestamp: memory.timestamp,
      topics: memory.topics,
      sources: memory.sources,
      type: memory.type
    }))
  };
  
  const jsonString = JSON.stringify(exportData, null, 2);
  downloadFile(jsonString, filename, 'application/json');
}

/**
 * Export memories as CSV
 */
function exportMemoriesAsCSV(memories, filename = 'memories.csv') {
  if (!memories || memories.length === 0) {
    alert('No memories to export');
    return;
  }
  
  // CSV header
  const headers = ['ID', 'Title', 'Summary', 'Date', 'Topics', 'Sources', 'Type'];
  
  // CSV rows
  const rows = memories.map(memory => [
    memory.id || '',
    `"${(memory.title || '').replace(/"/g, '""')}"`,
    `"${(memory.summary || '').replace(/"/g, '""')}"`,
    memory.timestamp || '',
    `"${(memory.topics || []).join(', ')}"`,
    `"${(memory.sources || []).join(', ')}"`,
    memory.type || ''
  ]);
  
  // Combine header and rows
  const csvContent = [headers.join(','), ...rows.map(row => row.join(','))].join('\n');
  
  downloadFile(csvContent, filename, 'text/csv');
}

/**
 * Export memories as Markdown
 */
function exportMemoriesAsMarkdown(memories, filename = 'memories.md') {
  if (!memories || memories.length === 0) {
    alert('No memories to export');
    return;
  }
  
  let markdown = `# Collective Memory Export\n\n`;
  markdown += `Export Date: ${new Date().toLocaleDateString()}\n`;
  markdown += `Total Memories: ${memories.length}\n\n`;
  markdown += `---\n\n`;
  
  // Group by date
  const groupedByDate = memories.reduce((groups, memory) => {
    const date = DateUtils.formatDate(memory.timestamp);
    if (!groups[date]) {
      groups[date] = [];
    }
    groups[date].push(memory);
    return groups;
  }, {});
  
  Object.keys(groupedByDate).sort().reverse().forEach(date => {
    markdown += `## ${date}\n\n`;
    
    groupedByDate[date].forEach(memory => {
      markdown += `### ${memory.title || 'Memory'}\n\n`;
      markdown += `**Type:** ${memory.type || 'General'}\n\n`;
      markdown += `**Topics:** ${(memory.topics || []).join(', ')}\n\n`;
      markdown += `**Sources:** ${(memory.sources || []).join(', ')}\n\n`;
      markdown += `${memory.summary || ''}\n\n`;
      markdown += `---\n\n`;
    });
  });
  
  downloadFile(markdown, filename, 'text/markdown');
}

/**
 * Export filtered memories
 */
function exportFilteredMemories(format = 'json') {
  const memories = window.memoryState.memories;
  
  if (!memories || memories.length === 0) {
    alert('No memories to export');
    return;
  }
  
  const filename = `memories-${new Date().toISOString().split('T')[0]}`;
  
  switch (format.toLowerCase()) {
    case 'json':
      exportMemoriesAsJSON(memories, `${filename}.json`);
      break;
    case 'csv':
      exportMemoriesAsCSV(memories, `${filename}.csv`);
      break;
    case 'markdown':
    case 'md':
      exportMemoriesAsMarkdown(memories, `${filename}.md`);
      break;
    default:
      alert(`Unsupported export format: ${format}`);
  }
}

/**
 * Download file helper
 */
function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// Export functions for use in other modules
window.exportMemoriesAsJSON = exportMemoriesAsJSON;
window.exportMemoriesAsCSV = exportMemoriesAsCSV;
window.exportMemoriesAsMarkdown = exportMemoriesAsMarkdown;
window.exportFilteredMemories = exportFilteredMemories;
