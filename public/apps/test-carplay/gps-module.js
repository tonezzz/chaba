// GPS Location Module for CarPlay Map
// Provides real location data and GPS tracking simulation

// Real locations from SSOT
const LOCATIONS = {
  tonyOmen: {
    name: "Tony Omen",
    lat: 13.7563,  // Bangkok area (approximate)
    lon: 100.5018,
    address: "Primary Workstation (192.168.1.48)",
    type: "workstation"
  },
  tonyDell: {
    name: "Tony Dell", 
    lat: 13.7565,  // Bangkok area (approximate)
    lon: 100.5020,
    address: "Secondary Workstation (192.168.1.42)",
    type: "workstation"
  },
  home: {
    name: "Home",
    lat: 13.7560,  // Bangkok area (approximate)
    lon: 100.5015,
    address: "Home Location",
    type: "home"
  },
  chabaH3: {
    name: "Chaba H3",
    lat: 13.7520,  // Bangkok area (approximate)
    lon: 100.5000,
    address: "Chaba H3 Server",
    type: "server"
  }
};

// Current GPS state
let currentLocation = null;
let isTracking = false;
let watchId = null;

// Simulated GPS movement
let simulationInterval = null;
let simulationAngle = 0;
const SIMULATION_SPEED = 0.0001; // degrees per tick
const SIMULATION_RADIUS = 0.005; // degrees from center

// Initialize GPS
function initGPS() {
  // Start with current location
  currentLocation = { ...LOCATIONS.home };
  
  // Try to get real GPS if available
  if ('geolocation' in navigator) {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        currentLocation = {
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          accuracy: position.coords.accuracy,
          timestamp: position.timestamp
        };
      },
      (error) => {
        console.log('GPS not available, using simulated location:', error);
      }
    );
  }
}

// Start GPS tracking
function startTracking() {
  if (isTracking) return;
  
  isTracking = true;
  
  if ('geolocation' in navigator) {
    watchId = navigator.geolocation.watchPosition(
      (position) => {
        currentLocation = {
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          accuracy: position.coords.accuracy,
          heading: position.coords.heading,
          speed: position.coords.speed,
          timestamp: position.timestamp
        };
      },
      (error) => {
        console.log('GPS tracking error:', error);
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0
      }
    );
  } else {
    // Start simulation
    startSimulation();
  }
}

// Stop GPS tracking
function stopTracking() {
  isTracking = false;
  
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  
  if (simulationInterval !== null) {
    clearInterval(simulationInterval);
    simulationInterval = null;
  }
}

// Start simulated GPS movement
function startSimulation() {
  const centerLat = currentLocation.lat;
  const centerLon = currentLocation.lon;
  
  simulationInterval = setInterval(() => {
    simulationAngle += SIMULATION_SPEED;
    
    currentLocation = {
      ...currentLocation,
      lat: centerLat + Math.cos(simulationAngle) * SIMULATION_RADIUS,
      lon: centerLon + Math.sin(simulationAngle) * SIMULATION_RADIUS,
      heading: (simulationAngle * 180 / Math.PI) % 360,
      speed: 5, // simulated speed in m/s
      timestamp: Date.now()
    };
  }, 1000);
}

// Get current location
function getCurrentLocation() {
  return currentLocation;
}

// Get distance between two points (Haversine formula)
function getDistance(lat1, lon1, lat2, lon2) {
  const R = 6371e3; // Earth's radius in meters
  const φ1 = lat1 * Math.PI / 180;
  const φ2 = lat2 * Math.PI / 180;
  const Δφ = (lat2 - lat1) * Math.PI / 180;
  const Δλ = (lon2 - lon1) * Math.PI / 180;
  
  const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
          Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ/2) * Math.sin(Δλ/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  
  return R * c;
}

// Get bearing between two points
function getBearing(lat1, lon1, lat2, lon2) {
  const φ1 = lat1 * Math.PI / 180;
  const φ2 = lat2 * Math.PI / 180;
  const λ1 = lon1 * Math.PI / 180;
  const λ2 = lon2 * Math.PI / 180;
  
  const y = Math.sin(λ2 - λ1) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(λ2 - λ1);
  
  const θ = Math.atan2(y, x);
  return (θ * 180 / Math.PI + 360) % 360;
}

// Calculate route between two points
function calculateRoute(from, to) {
  const distance = getDistance(from.lat, from.lon, to.lat, to.lon);
  const bearing = getBearing(from.lat, from.lon, to.lat, to.lon);
  const duration = distance / 5; // Assume 5 m/s average speed
  
  return {
    from,
    to,
    distance,
    bearing,
    duration,
    steps: generateRouteSteps(from, to, bearing, distance)
  };
}

// Generate route steps (simplified)
function generateRouteSteps(from, to, bearing, distance) {
  const steps = [];
  const stepDistance = distance / 5; // 5 steps
  
  for (let i = 0; i < 5; i++) {
    const progress = (i + 1) / 5;
    const stepLat = from.lat + (to.lat - from.lat) * progress;
    const stepLon = from.lon + (to.lon - from.lon) * progress;
    
    steps.push({
      instruction: i === 0 ? "Start" : (i === 4 ? "Arrive" : "Continue"),
      distance: stepDistance,
      duration: duration / 5,
      lat: stepLat,
      lon: stepLon
    });
  }
  
  return steps;
}

// Get all locations
function getAllLocations() {
  return LOCATIONS;
}

// Get location by ID
function getLocation(id) {
  return LOCATIONS[id];
}

// Set current location manually
function setCurrentLocation(lat, lon) {
  currentLocation = { lat, lon, timestamp: Date.now() };
}

// Export for use in CarPlay map
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    initGPS,
    startTracking,
    stopTracking,
    getCurrentLocation,
    getDistance,
    getBearing,
    calculateRoute,
    getAllLocations,
    getLocation,
    setCurrentLocation
  };
}

// Export to window for browser environment
if (typeof window !== 'undefined') {
  window.initGPS = initGPS;
  window.startTracking = startTracking;
  window.stopTracking = stopTracking;
  window.getCurrentLocation = getCurrentLocation;
  window.getDistance = getDistance;
  window.getBearing = getBearing;
  window.calculateRoute = calculateRoute;
  window.getAllLocations = getAllLocations;
  window.getLocation = getLocation;
  window.setCurrentLocation = setCurrentLocation;
}
