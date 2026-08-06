// State
let count = 0;
let currentTheme = 0;
const themes = ['', 'theme-dark', 'theme-green', 'theme-purple', 'theme-orange'];

// DOM Elements
const counterBtn = document.getElementById('counter-btn');
const colorBtn = document.getElementById('color-btn');
const resetBtn = document.getElementById('reset-btn');
const counterDisplay = document.getElementById('counter');
const pwaStatus = document.getElementById('pwa-status');
const displayMode = document.getElementById('display-mode');
const onlineStatus = document.getElementById('online-status');

// Initialize
function init() {
  updatePWAStatus();
  updateDisplayMode();
  updateOnlineStatus();
  setupEventListeners();
  loadState();
}

// PWA Status Detection
function updatePWAStatus() {
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
                       window.navigator.standalone === true;
  
  pwaStatus.textContent = isStandalone ? 'Yes ✓' : 'No (browser)';
  pwaStatus.classList.add(isStandalone ? 'online' : 'offline');
}

// Display Mode Detection
function updateDisplayMode() {
  const modes = {
    'standalone': 'Standalone',
    'fullscreen': 'Fullscreen',
    'minimal-ui': 'Minimal UI',
    'browser': 'Browser'
  };
  
  let currentMode = 'browser';
  for (const mode in modes) {
    if (window.matchMedia(`(display-mode: ${mode})`).matches) {
      currentMode = mode;
      break;
    }
  }
  
  displayMode.textContent = modes[currentMode] || currentMode;
}

// Online Status
function updateOnlineStatus() {
  const isOnline = navigator.onLine;
  onlineStatus.textContent = isOnline ? 'Yes ✓' : 'No';
  onlineStatus.className = 'value ' + (isOnline ? 'online' : 'offline');
}

// Event Listeners
function setupEventListeners() {
  counterBtn.addEventListener('click', () => {
    count++;
    counterDisplay.textContent = count;
    saveState();
  });

  colorBtn.addEventListener('click', () => {
    document.body.classList.remove(themes[currentTheme]);
    currentTheme = (currentTheme + 1) % themes.length;
    if (themes[currentTheme]) {
      document.body.classList.add(themes[currentTheme]);
    }
    saveState();
  });

  resetBtn.addEventListener('click', () => {
    count = 0;
    currentTheme = 0;
    counterDisplay.textContent = count;
    document.body.classList.remove(...themes);
    saveState();
  });

  // Listen for display mode changes
  window.matchMedia('(display-mode: standalone)').addEventListener('change', updatePWAStatus);
  window.matchMedia('(display-mode: standalone)').addEventListener('change', updateDisplayMode);
  
  // Listen for online/offline changes
  window.addEventListener('online', updateOnlineStatus);
  window.addEventListener('offline', updateOnlineStatus);
}

// Local Storage
function saveState() {
  localStorage.setItem('test-pwa-state', JSON.stringify({
    count,
    currentTheme
  }));
}

function loadState() {
  const saved = localStorage.getItem('test-pwa-state');
  if (saved) {
    try {
      const state = JSON.parse(saved);
      count = state.count || 0;
      currentTheme = state.currentTheme || 0;
      counterDisplay.textContent = count;
      if (themes[currentTheme]) {
        document.body.classList.add(themes[currentTheme]);
      }
    } catch (e) {
      console.error('Failed to load state:', e);
    }
  }
}

// Service Worker Registration (for full PWA capabilities)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // Service worker would be registered here for offline support
    // For this simple test, we're not including a service worker
    console.log('Service Worker support detected');
  });
}

// Start
init();
