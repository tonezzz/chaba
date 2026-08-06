// Map Module for CarPlay
// Integrates with GPS module to show real locations and navigation

// Leaflet integration
let map = null;
let currentMarker = null;
let locationMarkers = {};
let routeLine = null;
let routeMarkers = [];

// Initialize map
function initMap() {
  // Check if map is already initialized
  if (map) {
    console.log('Map already initialized');
    return;
  }
  
  // Initialize GPS
  if (typeof initGPS === 'function') {
    initGPS();
  }
  
  // Create map centered on current location
  const currentLoc = getCurrentLocation() || { lat: 13.7563, lon: 100.5018 };
  
  map = L.map('carplay-map', {
    zoomControl: false,
    attributionControl: false
  }).setView([currentLoc.lat, currentLoc.lon], 15);
  
  // Add OpenStreetMap tiles
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19
  }).addTo(map);
  
  // Add current location marker
  updateCurrentLocationMarker();
  
  // Add all known locations
  addAllLocations();
  
  // Start tracking
  if (typeof startTracking === 'function') {
    startTracking();
  }
  
  // Update location every 2 seconds
  setInterval(updateCurrentLocationMarker, 2000);
}

// Update current location marker
function updateCurrentLocationMarker() {
  const currentLoc = getCurrentLocation();
  if (!currentLoc || !map) return;
  
  // Remove old marker
  if (currentMarker) {
    map.removeLayer(currentMarker);
  }
  
  // Create custom car icon
  const carIcon = L.divIcon({
    className: 'carplay-car-icon',
    html: '<div class="car-icon"></div>',
    iconSize: [40, 40],
    iconAnchor: [20, 20]
  });
  
  // Add new marker
  currentMarker = L.marker([currentLoc.lat, currentLoc.lon], {
    icon: carIcon
  }).addTo(map);
  
  // Center map on current location
  map.panTo([currentLoc.lat, currentLoc.lon]);
}

// Add all known locations to map
function addAllLocations() {
  const locations = getAllLocations();
  
  Object.keys(locations).forEach(id => {
    addLocationMarker(id, locations[id]);
  });
}

// Add a single location marker
function addLocationMarker(id, location) {
  if (!map) return;
  
  // Remove existing marker
  if (locationMarkers[id]) {
    map.removeLayer(locationMarkers[id]);
  }
  
  // Create custom icon based on type
  const iconClass = `carplay-${location.type}-icon`;
  const icon = L.divIcon({
    className: iconClass,
    html: `<div class="location-icon ${location.type}">${location.name.charAt(0)}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15]
  });
  
  // Add marker
  const marker = L.marker([location.lat, location.lon], {
    icon: icon
  }).addTo(map);
  
  // Add popup
  marker.bindPopup(`
    <div class="carplay-popup">
      <strong>${location.name}</strong><br>
      ${location.address}<br>
      <button onclick="navigateTo('${id}')" class="navigate-btn">Navigate</button>
    </div>
  `);
  
  locationMarkers[id] = marker;
}

// Navigate to a location
function navigateTo(locationId) {
  const targetLocation = getLocation(locationId);
  if (!targetLocation) return;
  
  const currentLoc = getCurrentLocation();
  if (!currentLoc) return;
  
  // Calculate route
  const route = calculateRoute(currentLoc, targetLocation);
  
  // Display route on map
  displayRoute(route);
  
  // Show route info
  showRouteInfo(route);
}

// Make navigateTo globally accessible for popup buttons
window.navigateTo = navigateTo;

// Display route on map
function displayRoute(route) {
  if (!map) return;
  
  // Remove old route
  if (routeLine) {
    map.removeLayer(routeLine);
  }
  
  // Remove old route markers
  routeMarkers.forEach(marker => map.removeLayer(marker));
  routeMarkers = [];
  
  // Create route coordinates
  const coordinates = [
    [route.from.lat, route.from.lon],
    ...route.steps.map(step => [step.lat, step.lon]),
    [route.to.lat, route.to.lon]
  ];
  
  // Add route line
  routeLine = L.polyline(coordinates, {
    color: '#007AFF',
    weight: 5,
    opacity: 0.8
  }).addTo(map);
  
  // Add step markers
  route.steps.forEach((step, index) => {
    const marker = L.circleMarker([step.lat, step.lon], {
      radius: 6,
      color: '#007AFF',
      fillColor: '#007AFF',
      fillOpacity: 1
    }).addTo(map);
    
    marker.bindPopup(step.instruction);
    routeMarkers.push(marker);
  });
  
  // Fit map to route
  map.fitBounds(routeLine.getBounds(), { padding: [50, 50] });
}

// Show route information
function showRouteInfo(route) {
  const distance = (route.distance / 1000).toFixed(1);
  const duration = Math.round(route.duration / 60);
  
  const routeInfo = document.getElementById('route-info');
  if (routeInfo) {
    routeInfo.innerHTML = `
      <div class="route-summary">
        <div class="route-distance">${distance} km</div>
        <div class="route-duration">${duration} min</div>
        <div class="route-destination">to ${route.to.name || 'destination'}</div>
      </div>
      <div class="route-steps">
        ${route.steps.map((step, i) => `
          <div class="route-step">
            <div class="step-number">${i + 1}</div>
            <div class="step-instruction">${step.instruction}</div>
            <div class="step-distance">${(step.distance / 1000).toFixed(1)} km</div>
          </div>
        `).join('')}
      </div>
    `;
  }
}

// Clear route
function clearRoute() {
  if (routeLine) {
    map.removeLayer(routeLine);
    routeLine = null;
  }
  
  routeMarkers.forEach(marker => map.removeLayer(marker));
  routeMarkers = [];
  
  const routeInfo = document.getElementById('route-info');
  if (routeInfo) {
    routeInfo.innerHTML = '';
  }
}

// Search for location
function searchLocation(query) {
  const locations = getAllLocations();
  const results = [];
  
  Object.keys(locations).forEach(id => {
    const location = locations[id];
    if (location.name.toLowerCase().includes(query.toLowerCase()) ||
        location.address.toLowerCase().includes(query.toLowerCase())) {
      results.push({ id, ...location });
    }
  });
  
  return results;
}

// Center map on location
function centerOnLocation(locationId) {
  if (!map) return;
  
  if (locationId === 'current' || locationId === null) {
    const currentLoc = getCurrentLocation();
    if (currentLoc) {
      map.setView([currentLoc.lat, currentLoc.lon], 16);
    }
  } else {
    const location = getLocation(locationId);
    if (location) {
      map.setView([location.lat, location.lon], 16);
    }
  }
}

// Get map bounds
function getMapBounds() {
  if (!map) return null;
  return map.getBounds();
}

// Set map zoom
function setMapZoom(zoom) {
  if (!map) return;
  map.setZoom(zoom);
}

// Cleanup
function cleanupMap() {
  if (typeof stopTracking === 'function') {
    stopTracking();
  }
  
  if (map) {
    map.remove();
    map = null;
  }
  
  currentMarker = null;
  locationMarkers = {};
  routeLine = null;
  routeMarkers = [];
}

// Export for use in CarPlay
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    initMap,
    updateCurrentLocationMarker,
    addAllLocations,
    addLocationMarker,
    navigateTo,
    displayRoute,
    showRouteInfo,
    clearRoute,
    searchLocation,
    centerOnLocation,
    getMapBounds,
    setMapZoom,
    cleanupMap
  };
}
