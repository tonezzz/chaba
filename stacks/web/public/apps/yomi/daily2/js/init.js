// ============================================================================
// INITIALIZATION - Initialize shared state before other modules
// ============================================================================

// Initialize shared dailySummaries once globally
if (!window.dailySummaries) {
  window.dailySummaries = [];
}

console.log('Daily2 initialization complete');
