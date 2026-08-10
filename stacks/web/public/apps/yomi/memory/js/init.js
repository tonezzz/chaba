// ============================================================================
// INITIALIZATION - Initialize shared state for memory app
// ============================================================================

// Initialize shared state
if (!window.memoryState) {
  window.memoryState = {
    conversations: [],
    memories: [],
    filters: {
      search: '',
      startDate: null,
      endDate: null,
      conversations: [],
      topics: [],
      memoryTypes: ['events', 'decisions', 'patterns']
    },
    currentView: 'timeline',
    stats: {
      totalMemories: 0,
      totalConversations: 0
    }
  };
}

console.log('Memory app initialization complete');
