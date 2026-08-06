// Route Input Module for CarPlay Maps
// Google Maps-style route planning interface

// Route input state
let routeInputState = {
  startLocation: null,
  destinationLocation: null,
  isSearching: false,
  searchResults: []
};

// Initialize route input panel
function initRouteInput() {
  const mapContainer = document.querySelector('.map-container');
  if (!mapContainer) return;

  // Create route input panel
  const routePanel = document.createElement('div');
  routePanel.className = 'route-input-panel';
  routePanel.innerHTML = `
    <div class="route-input-header">
      <button class="route-close-btn" onclick="closeRouteInput()">✕</button>
      <div class="route-input-title">Directions</div>
    </div>
    <div class="route-input-body">
      <div class="route-input-row">
        <div class="route-input-icon start-icon">●</div>
        <input 
          type="text" 
          class="route-input-field start-field" 
          placeholder="Choose starting point"
          id="route-start"
          onfocus="showLocationSuggestions('start')"
          oninput="handleLocationInput('start', this.value)"
        >
        <button class="route-input-action" onclick="useCurrentLocation('start')">📍</button>
      </div>
      <div class="route-input-row">
        <div class="route-input-icon dest-icon">■</div>
        <input 
          type="text" 
          class="route-input-field dest-field" 
          placeholder="Choose destination"
          id="route-destination"
          onfocus="showLocationSuggestions('destination')"
          oninput="handleLocationInput('destination', this.value)"
        >
        <button class="route-input-action" onclick="useCurrentLocation('destination')">📍</button>
      </div>
      <div class="route-suggestions" id="route-suggestions" style="display: none;"></div>
      <button class="route-calculate-btn" onclick="calculateRouteFromInput()">Start Navigation</button>
    </div>
  `;

  mapContainer.appendChild(routePanel);

  // Add route input button to map controls
  const mapControls = document.querySelector('.map-controls');
  if (mapControls) {
    const routeBtn = document.createElement('button');
    routeBtn.className = 'map-control-btn route-input-btn';
    routeBtn.textContent = '🔍 Route';
    routeBtn.onclick = openRouteInput;
    mapControls.insertBefore(routeBtn, mapControls.firstChild);
  }
}

// Open route input panel
function openRouteInput() {
  const panel = document.querySelector('.route-input-panel');
  if (panel) {
    panel.style.display = 'block';
    // Clear previous inputs
    document.getElementById('route-start').value = '';
    document.getElementById('route-destination').value = '';
    routeInputState.startLocation = null;
    routeInputState.destinationLocation = null;
  }
}

// Close route input panel
function closeRouteInput() {
  const panel = document.querySelector('.route-input-panel');
  if (panel) {
    panel.style.display = 'none';
  }
  hideSuggestions();
}

// Use current GPS location
function useCurrentLocation(field) {
  const currentLoc = getCurrentLocation();
  if (!currentLoc) {
    alert('GPS location not available');
    return;
  }

  const inputField = document.getElementById(`route-${field}`);
  if (inputField) {
    inputField.value = 'Current Location';
    if (field === 'start') {
      routeInputState.startLocation = { ...currentLoc, name: 'Current Location' };
    } else {
      routeInputState.destinationLocation = { ...currentLoc, name: 'Current Location' };
    }
  }
  hideSuggestions();
}

// Handle location input
function handleLocationInput(field, value) {
  if (value.length < 2) {
    hideSuggestions();
    return;
  }

  // Search for locations
  const results = searchLocation(value);
  showSuggestions(field, results);
}

// Show location suggestions
function showSuggestions(field, results) {
  const suggestionsPanel = document.getElementById('route-suggestions');
  if (!suggestionsPanel) return;

  if (results.length === 0) {
    suggestionsPanel.style.display = 'none';
    return;
  }

  suggestionsPanel.innerHTML = results.map(result => `
    <div class="route-suggestion-item" onclick="selectLocation('${field}', '${result.id}')">
      <div class="suggestion-icon">${getLocationIcon(result.type)}</div>
      <div class="suggestion-text">
        <div class="suggestion-name">${result.name}</div>
        <div class="suggestion-address">${result.address}</div>
      </div>
    </div>
  `).join('');

  suggestionsPanel.style.display = 'block';
  suggestionsPanel.dataset.field = field;
}

// Hide suggestions
function hideSuggestions() {
  const suggestionsPanel = document.getElementById('route-suggestions');
  if (suggestionsPanel) {
    suggestionsPanel.style.display = 'none';
  }
}

// Get location icon based on type
function getLocationIcon(type) {
  const icons = {
    home: '🏠',
    workstation: '💻',
    server: '🖥️',
    default: '📍'
  };
  return icons[type] || icons.default;
}

// Select location from suggestions
function selectLocation(field, locationId) {
  const location = getLocation(locationId);
  if (!location) return;

  const inputField = document.getElementById(`route-${field}`);
  if (inputField) {
    inputField.value = location.name;
    if (field === 'start') {
      routeInputState.startLocation = location;
    } else {
      routeInputState.destinationLocation = location;
    }
  }
  hideSuggestions();
}

// Show location suggestions on focus
function showLocationSuggestions(field) {
  const allLocations = getAllLocations();
  const locations = Object.keys(allLocations).map(id => ({
    id,
    ...allLocations[id]
  }));
  showSuggestions(field, locations);
}

// Calculate route from input
function calculateRouteFromInput() {
  if (!routeInputState.startLocation || !routeInputState.destinationLocation) {
    alert('Please enter both start and destination');
    return;
  }

  const from = {
    lat: routeInputState.startLocation.lat,
    lon: routeInputState.startLocation.lon,
    name: routeInputState.startLocation.name
  };

  const to = {
    lat: routeInputState.destinationLocation.lat,
    lon: routeInputState.destinationLocation.lon,
    name: routeInputState.destinationLocation.name
  };

  // Calculate route using existing function
  const route = calculateRoute(from, to);
  
  // Display route on map
  if (typeof displayRoute === 'function') {
    displayRoute(route);
  }
  
  // Show route info
  if (typeof showRouteInfo === 'function') {
    showRouteInfo(route);
  }

  // Close the input panel
  closeRouteInput();

  // Center map on route
  if (typeof getMapBounds === 'function') {
    // Map will auto-center from displayRoute
  }
}

// Add custom location (for future use)
function addCustomLocation(name, lat, lon, type = 'custom') {
  // This could be expanded to allow users to save custom locations
  console.log('Custom location:', { name, lat, lon, type });
}

// Export for use in CarPlay
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    initRouteInput,
    openRouteInput,
    closeRouteInput,
    useCurrentLocation,
    handleLocationInput,
    selectLocation,
    calculateRouteFromInput
  };
}
