// ============================================================================
// INITIALIZATION - Initialize shared state before other modules
// ============================================================================

// Initialize DailyApp namespace
if (!window.DailyApp) {
  console.error('DailyApp namespace not loaded. Ensure namespace.js is loaded before init.js');
} else {
  DailyApp.init();
  
  // Initialize current month in Thailand time
  const currentMonth = new Date();
  const thailandMonth = new Date(currentMonth.getTime() + (DailyApp.modules.config?.UI?.THAILAND_OFFSET_HOURS || 7) * 60 * 60 * 1000);
  DailyApp.setState('currentMonth', thailandMonth);
  
  console.log('Daily initialization complete');
}
