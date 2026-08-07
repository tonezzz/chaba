// Route Input Module for CarPlay Maps
// Google Maps-style route planning interface with tabbed saved/map search

// Route input state
let routeInputState = {
  startLocation: null,
  destinationLocation: null,
  isSearching: false,
  searchResults: []
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
          placeholder="Search for a location"
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
          placeholder="Search for a location"
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
    startInput.addEventListener('input', debounce(async (e) => {
      console.log('Start input changed:', e.target.value);
      await handleLocationInput('start', e.target.value);
    }, 100));
  }
  
  if (destInput) {
    destInput.addEventListener('focus', () => {
      console.log('Destination input focused');
      showLocationSuggestions('destination');
    });
    destInput.addEventListener('input', debounce(async (e) => {
      console.log('Destination input changed:', e.target.value);
      await handleLocationInput('destination', e.target.value);
    }, 100));
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
async function handleLocationInput(field, value) {
  // Search immediately on any input
  await searchAllLocations(field, value);
}

// Search all locations (saved + map) and merge results
async function searchAllLocations(field, query) {
  const suggestionsPanel = document.getElementById(`route-suggestions-${field}`);
  
  if (!query || query.length === 0) {
    // Show saved locations when input is empty
    showLocationSuggestions(field);
    return;
  }

  // Show loading state
  suggestionsPanel.innerHTML = `
    <div class="route-suggestions-content">
      <div class="suggestion-loading">Searching...</div>
    </div>
  `;
  suggestionsPanel.style.display = 'block';
  suggestionsPanel.style.visibility = 'visible';

  try {
    // Search both saved locations and map in parallel
    const [savedResults, mapResults] = await Promise.all([
      Promise.resolve(searchSavedLocations(query)),
      searchMapLocationsOnly(query)
    ]);

    // Prioritize map results, then saved results
    const allResults = [...mapResults, ...savedResults];
    
    // Store map results for selection
    routeInputState.searchResults = mapResults;
    
    if (allResults.length === 0) {
      suggestionsPanel.innerHTML = `
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

    showSuggestions(field, allResults);
  } catch (error) {
    console.error('Search failed:', error);
    suggestionsPanel.innerHTML = `
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

// Search map locations only (without UI)
async function searchMapLocationsOnly(query) {
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
      return [];
    }
    
    const locations = results.map(result => ({
      id: `osm-${result.place_id}`,
      name: result.display_name.split(',')[0],
      address: result.display_name,
      lat: parseFloat(result.lat),
      lon: parseFloat(result.lon),
      type: 'map'
    }));
    
    console.log('Processed map locations:', locations);
    return locations;
  } catch (error) {
    console.error('Map search failed:', error);
    return [];
  }
}

// Show location suggestions (no tabs, merged results)
function showSuggestions(field, results) {
  const suggestionsPanel = document.getElementById(`route-suggestions-${field}`);
  if (!suggestionsPanel) {
    console.log('Suggestions panel not found for field:', field);
    return;
  }

  console.log('Showing suggestions for field:', field, 'results:', results);

  if (results.length === 0) {
    suggestionsPanel.innerHTML = `
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
function searchSavedLocations(query) {
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
  
  console.log('Showing suggestions for field:', field, 'locations:', locations);
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
    showLocationSuggestions,
    hideSuggestions,
    searchSavedLocations,
    searchAllLocations,
    searchMapLocationsOnly,
    showSuggestions,
    selectLocation,
    calculateRouteFromInput
  };
}

// Export functions to window object for global access
console.log('Loading route-input-module functions...');
window.initRouteInput = initRouteInput;
window.openRouteInput = openRouteInput;
window.closeRouteInput = closeRouteInput;
window.handleLocationInput = handleLocationInput;
window.showLocationSuggestions = showLocationSuggestions;
window.hideSuggestions = hideSuggestions;
window.searchSavedLocations = searchSavedLocations;
window.searchAllLocations = searchAllLocations;
window.searchMapLocationsOnly = searchMapLocationsOnly;
window.showSuggestions = showSuggestions;
window.selectLocation = selectLocation;
window.useCurrentLocation = useCurrentLocation;
window.calculateRouteFromInput = calculateRouteFromInput;
console.log('route-input-module functions loaded:', { searchAllLocations: typeof window.searchAllLocations, searchMapLocationsOnly: typeof window.searchMapLocationsOnly });
