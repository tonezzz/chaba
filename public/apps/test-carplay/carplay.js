// State
let currentScreen = 'home';
let isPlaying = false;
let mapInitialized = false;
let routeInputInitialized = false;

// Update time
function updateTime() {
  const now = new Date();
  const hours = now.getHours();
  const minutes = now.getMinutes().toString().padStart(2, '0');
  document.getElementById('status-time').textContent = `${hours}:${minutes}`;
}

// Initialize
function init() {
  updateTime();
  setInterval(updateTime, 1000);
}

// Navigation
function openApp(appName) {
  // Hide all screens
  document.querySelectorAll('.screen').forEach(screen => {
    screen.style.display = 'none';
  });

  // Show selected screen
  const screen = document.getElementById(`${appName}-screen`);
  if (screen) {
    screen.style.display = 'flex';
    currentScreen = appName;

    // Initialize map when opening maps app
    if (appName === 'maps' && !mapInitialized) {
      setTimeout(() => {
        if (typeof initMap === 'function') {
          initMap();
          mapInitialized = true;
        }
        // Initialize route input panel
        if (typeof initRouteInput === 'function' && !routeInputInitialized) {
          initRouteInput();
          routeInputInitialized = true;
        }
      }, 100);
    }
  }
}

function goHome() {
  openApp('home');
}

// Music controls
function togglePlay() {
  isPlaying = !isPlaying;
  const playBtn = document.querySelector('.play-btn');
  if (playBtn) {
    playBtn.textContent = isPlaying ? '⏸️' : '▶️';
  }
}

// Touch feedback
document.querySelectorAll('.app-icon, .dock-icon, .control-btn, .keypad-btn, .message-item, .setting-item').forEach(element => {
  element.addEventListener('touchstart', function() {
    this.style.opacity = '0.7';
  });
  element.addEventListener('touchend', function() {
    this.style.opacity = '1';
  });
});

// Initialize on load
document.addEventListener('DOMContentLoaded', init);

// Map helper functions
function centerOnCurrentLocation() {
  if (typeof centerOnLocation === 'function') {
    const currentLoc = getCurrentLocation();
    if (currentLoc) {
      // Center on current GPS location (pass null for current)
      centerOnLocation(null);
    }
  }
}

function clearRoute() {
  if (typeof clearRoute === 'function') {
    clearRoute();
  }
}
