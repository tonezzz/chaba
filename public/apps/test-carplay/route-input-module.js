// Route Input Module for CarPlay Maps
// Google Maps-style route planning interface with tabbed saved/map search

// Route input state
let routeInputState = {
  startLocation: null,
  destinationLocation: null,
  isSearching: false,
  searchResults: [],
  selectedRouteOption: 'fastest',
  searchHistory: [],
  voiceRecognition: null,
  isListening: false,
  currentVoiceField: null
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

// Search history management
const SEARCH_HISTORY_KEY = 'carplay_search_history';
const MAX_HISTORY_ITEMS = 10;

function loadSearchHistory() {
  try {
    const stored = localStorage.getItem(SEARCH_HISTORY_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (e) {
    console.error('Failed to load search history:', e);
    return [];
  }
}

function saveSearchHistory(history) {
  try {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(history));
  } catch (e) {
    console.error('Failed to save search history:', e);
  }
}

function addToSearchHistory(location) {
  const history = loadSearchHistory();
  
  // Remove if already exists (to move to top)
  const existingIndex = history.findIndex(item => item.id === location.id);
  if (existingIndex !== -1) {
    history.splice(existingIndex, 1);
  }
  
  // Add to beginning with timestamp
  history.unshift({
    ...location,
    timestamp: Date.now()
  });
  
  // Keep only MAX_HISTORY_ITEMS
  if (history.length > MAX_HISTORY_ITEMS) {
    history.splice(MAX_HISTORY_ITEMS);
  }
  
  saveSearchHistory(history);
  routeInputState.searchHistory = history;
}

function clearSearchHistory() {
  localStorage.removeItem(SEARCH_HISTORY_KEY);
  routeInputState.searchHistory = [];
}

function formatTimestamp(timestamp) {
  const now = Date.now();
  const diff = now - timestamp;
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}

// Voice search functionality
function initVoiceRecognition() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    console.warn('Speech recognition not supported');
    return null;
  }
  
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();
  
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';
  
  recognition.onstart = () => {
    routeInputState.isListening = true;
    updateVoiceButtonState(true);
  };
  
  recognition.onend = () => {
    routeInputState.isListening = false;
    updateVoiceButtonState(false);
  };
  
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    handleVoiceResult(transcript);
  };
  
  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    routeInputState.isListening = false;
    updateVoiceButtonState(false);
    
    let errorMessage = 'Voice search failed';
    if (event.error === 'no-speech') {
      errorMessage = 'No speech detected';
    } else if (event.error === 'not-allowed') {
      errorMessage = 'Microphone access denied';
    } else if (event.error === 'network') {
      errorMessage = 'Network error';
    }
    
    alert(errorMessage);
  };
  
  return recognition;
}

function startVoiceSearch(field) {
  if (routeInputState.isListening) {
    stopVoiceSearch();
    return;
  }
  
  if (!routeInputState.voiceRecognition) {
    routeInputState.voiceRecognition = initVoiceRecognition();
  }
  
  if (!routeInputState.voiceRecognition) {
    alert('Voice search is not supported in this browser');
    return;
  }
  
  routeInputState.currentVoiceField = field;
  
  try {
    routeInputState.voiceRecognition.start();
  } catch (error) {
    console.error('Failed to start voice recognition:', error);
    alert('Failed to start voice search');
  }
}

function stopVoiceSearch() {
  if (routeInputState.voiceRecognition && routeInputState.isListening) {
    try {
      routeInputState.voiceRecognition.stop();
    } catch (error) {
      console.error('Failed to stop voice recognition:', error);
    }
  }
}

function updateVoiceButtonState(isListening) {
  const voiceButtons = document.querySelectorAll('.route-input-voice');
  voiceButtons.forEach(btn => {
    if (isListening) {
      btn.classList.add('listening');
      btn.textContent = '🔴';
    } else {
      btn.classList.remove('listening');
      btn.textContent = '🎤';
    }
  });
}

function handleVoiceResult(transcript) {
  const field = routeInputState.currentVoiceField;
  if (!field) return;
  
  const inputField = document.getElementById(`route-${field}`);
  if (inputField) {
    inputField.value = transcript;
    // Trigger search with the voice input
    handleLocationInput(field, transcript);
  }
}

// Saved places management
const SAVED_PLACES_KEY = 'carplay_saved_places';

function loadSavedPlaces() {
  try {
    const stored = localStorage.getItem(SAVED_PLACES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (e) {
    console.error('Failed to load saved places:', e);
    return [];
  }
}

function saveSavedPlaces(places) {
  try {
    localStorage.setItem(SAVED_PLACES_KEY, JSON.stringify(places));
  } catch (e) {
    console.error('Failed to save saved places:', e);
  }
}

function isLocationSaved(locationId) {
  const savedPlaces = loadSavedPlaces();
  return savedPlaces.some(place => place.id === locationId);
}

function saveLocation(location) {
  const savedPlaces = loadSavedPlaces();
  
  // Check if already saved
  if (isLocationSaved(location.id)) {
    alert('Location already saved');
    return;
  }
  
  savedPlaces.push({
    ...location,
    savedAt: Date.now()
  });
  
  saveSavedPlaces(savedPlaces);
  alert('Location saved');
}

function removeLocation(locationId) {
  const savedPlaces = loadSavedPlaces();
  const filtered = savedPlaces.filter(place => place.id !== locationId);
  saveSavedPlaces(filtered);
  alert('Location removed');
}

function openSavedPlaces() {
  const modal = document.getElementById('saved-places-modal');
  if (modal) {
    modal.style.display = 'flex';
    loadSavedPlacesContent();
  }
}

function closeSavedPlaces() {
  const modal = document.getElementById('saved-places-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

function loadSavedPlacesContent() {
  const body = document.getElementById('saved-places-body');
  const savedPlaces = loadSavedPlaces();
  
  if (savedPlaces.length === 0) {
    body.innerHTML = `
      <div class="saved-places-empty">
        <div class="saved-places-empty-icon">📍</div>
        <div class="saved-places-empty-text">No saved places yet</div>
        <div class="saved-places-empty-subtext">Search and select locations to save them</div>
      </div>
    `;
    return;
  }
  
  let html = '';
  savedPlaces.forEach(place => {
    const icon = getSuggestionIcon(place.type);
    html += `
      <div class="saved-place-item">
        <div class="saved-place-icon">${icon}</div>
        <div class="saved-place-info">
          <div class="saved-place-name">${place.name}</div>
          <div class="saved-place-address">${place.address}</div>
        </div>
        <div class="saved-place-actions">
          <button class="saved-place-action-btn" onclick="useSavedPlace('${place.id}')" title="Use this place">→</button>
          <button class="saved-place-action-btn delete" onclick="removeSavedPlace('${place.id}')" title="Remove">✕</button>
        </div>
      </div>
    `;
  });
  
  body.innerHTML = html;
}

function useSavedPlace(locationId) {
  const savedPlaces = loadSavedPlaces();
  const place = savedPlaces.find(p => p.id === locationId);
  
  if (place) {
    closeSavedPlaces();
    const destInput = document.getElementById('route-destination');
    if (destInput) {
      destInput.value = place.name;
      routeInputState.destinationLocation = place;
      updateRoutePreview();
    }
  }
}

function removeSavedPlace(locationId) {
  if (confirm('Remove this saved place?')) {
    removeLocation(locationId);
    loadSavedPlacesContent();
  }
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
      <button class="route-saved-btn" onclick="openSavedPlaces()">★</button>
    </div>
    <div class="route-input-body">
      <div class="route-quick-actions">
        <button class="quick-action-btn" onclick="selectQuickLocation('home')">
          <span class="quick-action-icon">🏠</span>
          <span class="quick-action-label">Home</span>
        </button>
        <button class="quick-action-btn" onclick="selectQuickLocation('work')">
          <span class="quick-action-icon">💼</span>
          <span class="quick-action-label">Work</span>
        </button>
        <button class="quick-action-btn" onclick="selectQuickLocation('gym')">
          <span class="quick-action-icon">🏋️</span>
          <span class="quick-action-label">Gym</span>
        </button>
      </div>
      <div class="route-input-row">
        <div class="route-input-icon start-icon">●</div>
        <input 
          type="text" 
          class="route-input-field start-field" 
          placeholder="Where from?"
          id="route-start"
          autocomplete="off"
        >
        <button class="route-input-clear" onclick="clearInput('start')" title="Clear">✕</button>
        <button class="route-input-voice" onclick="startVoiceSearch('start')" title="Voice search">🎤</button>
        <button class="route-input-action" onclick="useCurrentLocation('start')" title="My location">📍</button>
      </div>
      <div class="route-suggestions" id="route-suggestions-start" style="display: none;"></div>
      <div class="route-input-row">
        <div class="route-input-icon dest-icon">■</div>
        <input 
          type="text" 
          class="route-input-field dest-field" 
          placeholder="Where to?"
          id="route-destination"
          autocomplete="off"
        >
        <button class="route-input-clear" onclick="clearInput('destination')" title="Clear">✕</button>
        <button class="route-input-voice" onclick="startVoiceSearch('destination')" title="Voice search">🎤</button>
        <button class="route-input-action" onclick="useCurrentLocation('destination')" title="My location">📍</button>
      </div>
      <div class="route-suggestions" id="route-suggestions-destination" style="display: none;"></div>
      <div class="route-preview" id="route-preview" style="display: none;">
        <div class="route-preview-content">
          <div class="route-preview-info">
            <div class="route-preview-time" id="route-preview-time">-- min</div>
            <div class="route-preview-distance" id="route-preview-distance">-- km</div>
          </div>
          <div class="route-preview-type" id="route-preview-type">Fastest route</div>
        </div>
        <div class="route-options">
          <button class="route-option-btn active" data-option="fastest" onclick="selectRouteOption('fastest')">Fastest</button>
          <button class="route-option-btn" data-option="shortest" onclick="selectRouteOption('shortest')">Shortest</button>
          <button class="route-option-btn" data-option="avoid-tolls" onclick="selectRouteOption('avoid-tolls')">Avoid Tolls</button>
        </div>
      </div>
      <button class="route-calculate-btn" onclick="calculateRouteFromInput()">Start Navigation</button>
    </div>
  `;

  mapContainer.appendChild(routePanel);

  // Create saved places modal
  const savedModal = document.createElement('div');
  savedModal.className = 'saved-places-modal';
  savedModal.id = 'saved-places-modal';
  savedModal.innerHTML = `
    <div class="saved-places-content">
      <div class="saved-places-header">
        <button class="saved-places-close" onclick="closeSavedPlaces()">✕</button>
        <div class="saved-places-title">Saved Places</div>
      </div>
      <div class="saved-places-body" id="saved-places-body">
        <div class="saved-places-loading">Loading saved places...</div>
      </div>
    </div>
  `;
  document.body.appendChild(savedModal);

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
  // Stop voice recognition if active
  stopVoiceSearch();
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
    updateRoutePreview();
  }
  hideSuggestions();
}

// Clear input field
function clearInput(field) {
  const inputField = document.getElementById(`route-${field}`);
  if (inputField) {
    inputField.value = '';
    if (field === 'start') {
      routeInputState.startLocation = null;
    } else {
      routeInputState.destinationLocation = null;
    }
    updateRoutePreview();
    inputField.focus();
  }
}

// Select quick location
function selectQuickLocation(locationId) {
  const allLocations = getAllLocations();
  const location = allLocations[locationId];
  
  if (!location) {
    console.error('Location not found:', locationId);
    return;
  }
  
  // Determine which field to populate (default to destination for quick actions)
  const destInput = document.getElementById('route-destination');
  if (destInput) {
    destInput.value = location.name;
    routeInputState.destinationLocation = {
      id: locationId,
      name: location.name,
      lat: location.lat,
      lon: location.lon,
      address: location.address,
      type: location.type
    };
    destInput.focus();
    updateRoutePreview();
  }
  
  hideSuggestions();
}

// Calculate distance between two coordinates (Haversine formula)
function calculateDistance(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth's radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = 
    Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c; // Distance in km
}

// Estimate travel time based on distance and route option
function estimateTime(distance, routeOption) {
  // Average speeds in km/h based on route type
  const speeds = {
    fastest: 50,    // Mixed city/highway
    shortest: 40,  // Slower routes
    'avoid-tolls': 45  // Slightly slower due to avoiding highways
  };
  
  const speed = speeds[routeOption] || 50;
  const timeHours = distance / speed;
  const timeMinutes = Math.round(timeHours * 60);
  
  if (timeMinutes < 60) {
    return `${timeMinutes} min`;
  } else {
    const hours = Math.floor(timeMinutes / 60);
    const mins = timeMinutes % 60;
    return `${hours}h ${mins}m`;
  }
}

// Update route preview based on selected locations
function updateRoutePreview() {
  const preview = document.getElementById('route-preview');
  const timeDisplay = document.getElementById('route-preview-time');
  const distanceDisplay = document.getElementById('route-preview-distance');
  const typeDisplay = document.getElementById('route-preview-type');
  
  if (!routeInputState.startLocation || !routeInputState.destinationLocation) {
    preview.style.display = 'none';
    return;
  }
  
  const distance = calculateDistance(
    routeInputState.startLocation.lat,
    routeInputState.startLocation.lon,
    routeInputState.destinationLocation.lat,
    routeInputState.destinationLocation.lon
  );
  
  const time = estimateTime(distance, routeInputState.selectedRouteOption);
  const routeTypeText = {
    fastest: 'Fastest route',
    shortest: 'Shortest route',
    'avoid-tolls': 'Avoid tolls'
  }[routeInputState.selectedRouteOption];
  
  timeDisplay.textContent = time;
  distanceDisplay.textContent = `${distance.toFixed(1)} km`;
  typeDisplay.textContent = routeTypeText;
  
  preview.style.display = 'block';
}

// Select route option
function selectRouteOption(option) {
  routeInputState.selectedRouteOption = option;
  
  // Update button states
  document.querySelectorAll('.route-option-btn').forEach(btn => {
    btn.classList.remove('active');
    if (btn.dataset.option === option) {
      btn.classList.add('active');
    }
  });
  
  // Update preview if both locations are selected
  if (routeInputState.startLocation && routeInputState.destinationLocation) {
    updateRoutePreview();
  }
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

  // Show loading state with skeleton animation
  suggestionsPanel.innerHTML = `
    <div class="route-suggestions-content">
      <div class="skeleton-item">
        <div class="skeleton skeleton-icon"></div>
        <div class="skeleton-text">
          <div class="skeleton skeleton-name"></div>
          <div class="skeleton skeleton-address"></div>
        </div>
      </div>
      <div class="skeleton-item">
        <div class="skeleton skeleton-icon"></div>
        <div class="skeleton-text">
          <div class="skeleton skeleton-name"></div>
          <div class="skeleton skeleton-address"></div>
        </div>
      </div>
      <div class="skeleton-item">
        <div class="skeleton skeleton-icon"></div>
        <div class="skeleton-text">
          <div class="skeleton skeleton-name"></div>
          <div class="skeleton skeleton-address"></div>
        </div>
      </div>
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
  
  // Get location from all locations
  const allLocations = getAllLocations();
  const location = allLocations[locationId];
  if (location) {
    setInputLocation(field, {
      id: locationId,
      ...location
    });
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
    updateRoutePreview();
    // Add to search history
    addToSearchHistory(location);
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
    type: 'current',
    category: 'nearby'
  });
  
  // Load search history
  const searchHistory = loadSearchHistory();
  
  // Organize by category
  const categories = {
    favorites: locations.filter(loc => loc.category === 'favorites'),
    recent: locations.filter(loc => loc.category === 'recent'),
    nearby: locations.filter(loc => loc.category === 'nearby' || loc.category === 'current')
  };
  
  // Build suggestions HTML with category headers
  let suggestionsHTML = '';
  
  // Add search history if available
  if (searchHistory.length > 0) {
    suggestionsHTML += `<div class="suggestion-category">Recent Searches (${searchHistory.length})</div>`;
    searchHistory.forEach(loc => {
      const timeAgo = formatTimestamp(loc.timestamp);
      suggestionsHTML += createHistorySuggestionItemHTML(loc, field, timeAgo);
    });
  }
  
  if (categories.favorites.length > 0) {
    suggestionsHTML += `<div class="suggestion-category">Favorites (${categories.favorites.length})</div>`;
    categories.favorites.forEach(loc => {
      suggestionsHTML += createSuggestionItemHTML(loc, field);
    });
  }
  
  if (categories.recent.length > 0) {
    suggestionsHTML += `<div class="suggestion-category">Recent (${categories.recent.length})</div>`;
    categories.recent.forEach(loc => {
      suggestionsHTML += createSuggestionItemHTML(loc, field);
    });
  }
  
  if (categories.nearby.length > 0) {
    suggestionsHTML += `<div class="suggestion-category">Nearby (${categories.nearby.length})</div>`;
    categories.nearby.forEach(loc => {
      suggestionsHTML += createSuggestionItemHTML(loc, field);
    });
  }
  
  // Add clear history button if history exists
  if (searchHistory.length > 0) {
    suggestionsHTML += `
      <div class="clear-history-container">
        <button class="clear-history-btn" onclick="clearHistoryAndRefresh('${field}')">Clear History</button>
      </div>
    `;
  }
  
  const suggestionsPanel = document.getElementById(`route-suggestions-${field}`);
  if (suggestionsPanel) {
    suggestionsPanel.innerHTML = suggestionsHTML;
    suggestionsPanel.style.display = 'block';
    suggestionsPanel.style.visibility = 'visible';
  }
  
  console.log('Showing suggestions for field:', field, 'organized by category');
}

function createHistorySuggestionItemHTML(loc, field, timeAgo) {
  const icon = getSuggestionIcon(loc.type);
  const isSaved = isLocationSaved(loc.id);
  const saveIcon = isSaved ? '★' : '☆';
  return `
    <div class="route-suggestion-item history-item" onclick="selectLocation('${field}', '${loc.id}')">
      <div class="suggestion-icon">${icon}</div>
      <div class="suggestion-text">
        <div class="suggestion-name">${loc.name}</div>
        <div class="suggestion-address">${loc.address}</div>
        <div class="suggestion-time">${timeAgo}</div>
      </div>
      <button class="suggestion-save-btn ${isSaved ? 'saved' : ''}" onclick="event.stopPropagation(); toggleSaveLocation('${loc.id}')" title="${isSaved ? 'Remove from saved' : 'Save location'}">${saveIcon}</button>
    </div>
  `;
}

function clearHistoryAndRefresh(field) {
  clearSearchHistory();
  showLocationSuggestions(field);
}

function createSuggestionItemHTML(loc, field) {
  const icon = getSuggestionIcon(loc.type);
  const isSaved = isLocationSaved(loc.id);
  const saveIcon = isSaved ? '★' : '☆';
  return `
    <div class="route-suggestion-item" onclick="selectLocation('${field}', '${loc.id}')">
      <div class="suggestion-icon">${icon}</div>
      <div class="suggestion-text">
        <div class="suggestion-name">${loc.name}</div>
        <div class="suggestion-address">${loc.address}</div>
      </div>
      <button class="suggestion-save-btn" onclick="event.stopPropagation(); toggleSaveLocation('${loc.id}')" title="${isSaved ? 'Remove from saved' : 'Save location'}">${saveIcon}</button>
    </div>
  `;
}

function toggleSaveLocation(locationId) {
  if (isLocationSaved(locationId)) {
    removeLocation(locationId);
  } else {
    const allLocations = getAllLocations();
    const location = allLocations[locationId];
    if (location) {
      saveLocation({
        id: locationId,
        ...location
      });
    }
  }
  // Refresh suggestions to update save button state
  const activeField = document.activeElement.id === 'route-start' ? 'start' : 'destination';
  showLocationSuggestions(activeField);
}

function getSuggestionIcon(type) {
  const icons = {
    current: '📍',
    home: '🏠',
    work: '💼',
    workstation: '💻',
    cafe: '☕',
    grocery: '🛒',
    gas: '⛽',
    park: '🌳',
    restaurant: '🍜',
    shopping: '🛍️',
    gym: '🏋️',
    library: '📚',
    parking: '🅿️'
  };
  return icons[type] || '📍';
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
    calculateRouteFromInput,
    clearInput,
    selectQuickLocation,
    updateRoutePreview,
    selectRouteOption,
    loadSearchHistory,
    saveSearchHistory,
    addToSearchHistory,
    clearSearchHistory,
    clearHistoryAndRefresh,
    initVoiceRecognition,
    startVoiceSearch,
    stopVoiceSearch,
    handleVoiceResult,
    loadSavedPlaces,
    saveSavedPlaces,
    isLocationSaved,
    saveLocation,
    removeLocation,
    openSavedPlaces,
    closeSavedPlaces,
    loadSavedPlacesContent,
    useSavedPlace,
    removeSavedPlace,
    toggleSaveLocation
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
window.clearInput = clearInput;
window.selectQuickLocation = selectQuickLocation;
window.updateRoutePreview = updateRoutePreview;
window.selectRouteOption = selectRouteOption;
window.loadSearchHistory = loadSearchHistory;
window.saveSearchHistory = saveSearchHistory;
window.addToSearchHistory = addToSearchHistory;
window.clearSearchHistory = clearSearchHistory;
window.clearHistoryAndRefresh = clearHistoryAndRefresh;
window.initVoiceRecognition = initVoiceRecognition;
window.startVoiceSearch = startVoiceSearch;
window.stopVoiceSearch = stopVoiceSearch;
window.handleVoiceResult = handleVoiceResult;
window.loadSavedPlaces = loadSavedPlaces;
window.saveSavedPlaces = saveSavedPlaces;
window.isLocationSaved = isLocationSaved;
window.saveLocation = saveLocation;
window.removeLocation = removeLocation;
window.openSavedPlaces = openSavedPlaces;
window.closeSavedPlaces = closeSavedPlaces;
window.loadSavedPlacesContent = loadSavedPlacesContent;
window.useSavedPlace = useSavedPlace;
window.removeSavedPlace = removeSavedPlace;
window.toggleSaveLocation = toggleSaveLocation;
console.log('route-input-module functions loaded:', { searchAllLocations: typeof window.searchAllLocations, searchMapLocationsOnly: typeof window.searchMapLocationsOnly });
// Force reload
