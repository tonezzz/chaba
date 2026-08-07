// Route Input Module for CarPlay Maps
// Google Maps-style route planning interface with tabbed saved/map search

// Route input state
let routeInputState = {
  startLocation: null,
  destinationLocation: null,
  isSearching: false,
  searchResults: [],
  activeTab: 'saved' // 'saved' or 'search'
};

// Debounce function for search
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

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
          autocomplete="off"
        >
        <button class="route-input-action" onclick="useCurrentLocation('start')" title="My location">📍</button>
      </div>
      <div class="route-suggestions" id="route-suggestions-start" style="display: none;"></div>
      <div class="route-input-row">
        <div class="route-input-icon dest-icon">■</div>
        <input 
          type="text" 
          class="route-input-field dest-field" 
          placeholder="Choose destination"
          id="route-destination"
          autocomplete="off"
        >
        <button class="route-input-action" onclick="useCurrentLocation('destination')" title="My location">📍</button>
      </div>
      <div class="route-suggestions" id="route-suggestions-destination" style="display: none;"></div>
      <button class="route-calculate-btn" onclick="calculateRouteFromInput()">Start Navigation</button>
    </div>
  `;

  mapContainer.appendChild(routePanel);

  // Add event listeners for input fields
  const startInput = document.getElementById('route-start');
  const destInput = document.getElementById('route-destination');
  
  if (startInput) {
    startInput.addEventListener('focus', () => {
      console.log('Start input focused');
      showLocationSuggestions('start');
    });
    startInput.addEventListener('input', debounce((e) => {
      console.log('Start input changed:', e.target.value);
      handleLocationInput('start', e.target.value);
    }, 300));
  }
  
  if (destInput) {
    destInput.addEventListener('focus', () => {
      console.log('Destination input focused');
      showLocationSuggestions('destination');
    });
    destInput.addEventListener('input', debounce((e) => {
      console.log('Destination input changed:', e.target.value);
      handleLocationInput('destination', e.target.value);
    }, 300));
  }

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
    routeInputState.activeTab = 'saved';
    // Automatically show suggestions for start field
    setTimeout(() => {
      showLocationSuggestions('start');
    }, 100);
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
    // Show saved locations when input is short
    showLocationSuggestions(field);
    return;
  }

  // Auto-switch to search tab and search map
  searchMapLocations(field, value);
}

// Search map locations using Nominatim (OpenStreetMap)
async function searchMapLocations(field, query) {
  const suggestionsPanel = document.getElementById(`route-suggestions-${field}`);
  
  // Show loading state
  suggestionsPanel.innerHTML = `
    <div class="route-suggestions-tabs">
      <button class="suggestion-tab" onclick="switchTab('${field}', 'saved')">Saved</button>
      <button class="suggestion-tab active" onclick="switchTab('${field}', 'search')">Search Map</button>
    </div>
    <div class="route-suggestions-content">
      <div class="suggestion-loading">Searching map...</div>
    </div>
  `;
  suggestionsPanel.style.display = 'block';
  suggestionsPanel.style.visibility = 'visible';

  try {
    const response = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5&addressdetails=1`,
      {
        headers: {
          'Accept': 'application/json',
          'User-Agent': 'CarPlay-Simulator/1.0'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const results = await response.json();
    console.log('Nominatim results:', results);
    
    if (!results || results.length === 0) {
      suggestionsPanel.innerHTML = `
        <div class="route-suggestions-tabs">
          <button class="suggestion-tab" onclick="switchTab('${field}', 'saved')">Saved</button>
          <button class="suggestion-tab active" onclick="switchTab('${field}', 'search')">Search Map</button>
        </div>
        <div class="route-suggestions-content">
          <div class="route-suggestion-item no-results">
            <div class="suggestion-text">
              <div class="suggestion-name">No results found</div>
              <div class="suggestion-address">Try a different search term</div>
            </div>
          </div>
        </div>
      `;
      suggestionsPanel.style.display = 'block';
      suggestionsPanel.style.visibility = 'visible';
      return;
    }
    
    const locations = results.map(result => ({
      id: `osm-${result.place_id}`,
      name: result.display_name.split(',')[0],
      address: result.display_name,
      lat: parseFloat(result.lat),
      lon: parseFloat(result.lon),
      type: 'map'
    }));
    
    console.log('Processed locations:', locations);
    
    // Store search results for selection
    routeInputState.searchResults = locations;
    routeInputState.activeTab = 'search';
    
    showSuggestions(field, locations, 'search');
  } catch (error) {
    console.error('Map search failed:', error);
    suggestionsPanel.innerHTML = `
      <div class="route-suggestions-tabs">
        <button class="suggestion-tab" onclick="switchTab('${field}', 'saved')">Saved</button>
        <button class="suggestion-tab active" onclick="switchTab('${field}', 'search')">Search Map</button>
      </div>
      <div class="route-suggestions-content">
        <div class="route-suggestion-item no-results">
          <div class="suggestion-text">
            <div class="suggestion-name">Search failed</div>
            <div class="suggestion-address">${error.message}</div>
          </div>
        </div>
      </div>
    `;
    suggestionsPanel.style.display = 'block';
    suggestionsPanel.style.visibility = 'visible';
  }
}

// Switch between saved and search tabs
function switchTab(field, tab) {
  routeInputState.activeTab = tab;
  
  if (tab === 'saved') {
    showLocationSuggestions(field);
  } else if (tab === 'search') {
    const inputField = document.getElementById(`route-${field}`);
    const query = inputField.value;
    if (query.length >= 2) {
      searchMapLocations(field, query);
    } else {
      // Show placeholder for empty search
      showSuggestions(field, [], 'search');
    }
  }
}

// Show location suggestions with tabs
function showSuggestions(field, results, activeTab = 'saved') {
  const suggestionsPanel = document.getElementById(`route-suggestions-${field}`);
  if (!suggestionsPanel) {
    console.log('Suggestions panel not found for field:', field);
    return;
  }

  console.log('Showing suggestions for field:', field, 'results:', results, 'tab:', activeTab);

  if (results.length === 0 && activeTab === 'search') {
    suggestionsPanel.innerHTML = `
      <div class="route-suggestions-tabs">
        <button class="suggestion-tab" onclick="switchTab('${field}', 'saved')">Saved</button>
        <button class="suggestion-tab active" onclick="switchTab('${field}', 'search')">Search Map</button>
      </div>
      <div class="route-suggestions-content">
        <div class="route-suggestion-item no-results">
          <div class="suggestion-text">
            <div class="suggestion-name">No results found</div>
            <div class="suggestion-address">Try a different search term</div>
          </div>
        </div>
      </div>
    `;
  } else {
    suggestionsPanel.innerHTML = `
      <div class="route-suggestions-tabs">
        <button class="suggestion-tab ${activeTab === 'saved' ? 'active' : ''}" 
                onclick="switchTab('${field}', 'saved')">Saved</button>
        <button class="suggestion-tab ${activeTab === 'search' ? 'active' : ''}" 
                onclick="switchTab('${field}', 'search')">Search Map</button>
      </div>
      <div class="route-suggestions-content">
        ${results.map(result => `
          <div class="route-suggestion-item" onclick="selectLocation('${field}', '${result.id}')">
            <div class="suggestion-icon">${getLocationIcon(result.type)}</div>
            <div class="suggestion-text">
              <div class="suggestion-name">${result.name}</div>
              <div class="suggestion-address">${result.address}</div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }
  
  suggestionsPanel.style.display = 'block';
  suggestionsPanel.style.visibility = 'visible';
  suggestionsPanel.style.zIndex = '3000';
  suggestionsPanel.dataset.field = field;
}

// Hide suggestions
function hideSuggestions() {
  document.querySelectorAll('.route-suggestions').forEach(panel => {
    panel.style.display = 'none';
    panel.style.visibility = 'hidden';
  });
}

// Search for location (local implementation - saved locations only)
function searchLocation(query) {
  const locations = getAllLocations();
  const results = [];
  const lowerQuery = query.toLowerCase().trim();
  
  Object.keys(locations).forEach(id => {
    const location = locations[id];
    if (location.name.toLowerCase().includes(lowerQuery) ||
        location.address.toLowerCase().includes(lowerQuery)) {
      results.push({ id, ...location });
    }
  });
  
  return results;
}

// Export functions to window object for global access
window.initRouteInput = initRouteInput;
window.openRouteInput = openRouteInput;
window.closeRouteInput = closeRouteInput;
window.handleLocationInput = handleLocationInput;
window.showLocationSuggestions = showLocationSuggestions;
window.hideSuggestions = hideSuggestions;
window.searchLocation = searchLocation;
window.showSuggestions = showSuggestions;
window.selectLocation = selectLocation;
window.useCurrentLocation = useCurrentLocation;
window.calculateRouteFromInput = calculateRouteFromInput;
window.switchTab = switchTab;
window.searchMapLocations = searchMapLocations;

// Get location icon based on type
function getLocationIcon(type) {
  const icons = {
    home: '🏠',
    workstation: '💻',
    server: '🖥️',
    current: '📍',
    map: '🗺️',
    default: '📍'
  };
  return icons[type] || icons.default;
}

// Select location from suggestions
function selectLocation(field, locationId) {
  if (locationId === 'current') {
    useCurrentLocation(field);
    return;
  }
  
  // Check if it's an OSM map search result
  if (locationId.startsWith('osm-')) {
    const searchResults = routeInputState.searchResults || [];
    const location = searchResults.find(r => r.id === locationId);
    if (location) {
      setInputLocation(field, location);
    }
    return;
  }
  
  // Original SSOT location logic
  const location = getLocation(locationId);
  if (location) {
    setInputLocation(field, location);
  }
}

// Set input field and state
function setInputLocation(field, location) {
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

// Show location suggestions on focus (saved locations)
function showLocationSuggestions(field) {
  const allLocations = getAllLocations();
  const locations = Object.keys(allLocations).map(id => ({
    id,
    ...allLocations[id]
  }));
  
  // Add "Current Location" option
  locations.unshift({
    id: 'current',
    name: 'Current Location',
    address: 'Use GPS location',
    type: 'current'
  });
  
  routeInputState.activeTab = 'saved';
  console.log('Showing suggestions for field:', field, 'locations:', locations);
  showSuggestions(field, locations, 'saved');
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
    calculateRouteFromInput,
    switchTab,
    searchMapLocations
  };
}
