---
category: operations
---

# Technical Implementation

### GPS Module (`gps-module.js`)
- **Real Location Tracking**: Uses browser Geolocation API for actual GPS coordinates
- **Simulation Fallback**: Provides simulated GPS movement when real GPS unavailable
- **Location Database**: Contains real locations from SSOT (tony-omen, tony-dell, home, chaba-h3)
- **Route Calculation**: Implements Haversine formula for distance and bearing calculations
- **Location Types**: Supports home, workstation, and server location types

### Map Module (`map-module.js`)
- **Leaflet.js Integration**: Uses Leaflet library for interactive maps
- **OpenStreetMap Tiles**: Displays real map tiles from OpenStreetMap
- **Custom Markers**: CarPlay-style markers for current location and known locations
- **Route Display**: Visual route lines with step-by-step navigation
- **Touch Controls**: Map controls for navigation and route clearing

### Route Input Module (`route-input-module.js`)
- **Google Maps-Style Interface**: Start/destination input fields with suggestions
- **Location Search**: Real-time search through known locations
- **Current Location Button**: Quick GPS-based start/destination selection
- **Route Planning**: Calculate routes from user input
- **Touch-Friendly Panel**: CarPlay-styled input panel with dark theme

### Integration Points
- **Module Loading**: Leaflet CSS/JS loaded via CDN in index.html
- **Initialization**: Map and route input initialize when Maps app is opened
- **State Management**: Prevents duplicate initialization with proper cleanup
- **CarPlay Styling**: Custom CSS for map controls, route panels, and input interface

## Usage

### Access
- **Local Testing**: `http://tony-omen.local:8766/apps/test-carplay/`
- **Production**: `https://chaba.h3.gizmo-thailand.com/apps/test-carplay/`
- **PWA**: Install to iPad home screen for full-screen standalone mode

### Features
1. **Real GPS Tracking**: Automatically uses device GPS when available
2. **Location Markers**: Tap markers to see location details and navigate
3. **Route Planning**: 
   - Click "Navigate" on location markers to calculate routes
   - Use "🔍 Route" button to open Google Maps-style route input panel
   - Enter start/destination with location suggestions
   - Use "📍" button for current GPS location
4. **Map Controls**: 
   - "Clear Route" button to remove current route
   - "My Location" button to center on current GPS position
5. **Touch-Friendly**: Optimized for iPad touch interface

## Configuration

### Location Coordinates
Located in `gps-module.js` LOCATIONS object:
```javascript
const LOCATIONS = {
  tonyOmen: { lat: 13.7563, lon: 100.5018, type: "workstation" },
  tonyDell: { lat: 13.7565, lon: 100.5020, type: "workstation" },
  home: { lat: 13.7560, lon: 100.5015, type: "home" },
  chabaH3: { lat: 13.7520, lon: 100.5000, type: "server" }
};
```

### Map Styling
Custom CarPlay styling in `carplay.css`:
- Dark theme map containers
- Custom marker icons (car icon for current location)
- Route info panels with distance/duration display
- Touch-friendly control buttons
- Google Maps-style route input panel with dark theme

### Route Input Panel
Located in `route-input-module.js`:
- Start/destination input fields with autocomplete
- Location suggestions from known locations database
- Current location button for GPS-based selection
- Route calculation and display integration

## Troubleshooting

### Map Not Loading
- Check Leaflet CDN links in index.html
- Verify GPS module and map module are loaded before carplay.js
- Check browser console for initialization errors

### GPS Not Working
- Ensure HTTPS for production (Geolocation API requires secure context)
- Check browser permissions for location access
- Simulation mode activates automatically if GPS unavailable

### Route Calculation Issues
- Verify location coordinates are valid
- Check Haversine formula implementation in gps-module.js
- Ensure route display container exists in HTML

### Route Input Panel Issues
- Verify route-input-module.js is loaded in index.html
- Check that route input panel initializes when Maps app opens
- Ensure location suggestions appear when typing in input fields
- Verify "Start Navigation" button triggers route calculation

### Issue: Destination Search Not Working
- **Symptoms**: Nominatim API search returns no results or errors when searching for destinations
- **Causes**: Function name conflict between map-module.js and route-input-module.js - both files had a `searchLocation` function, causing the wrong function to be called
- **Solutions**:
  - Rename functions to be descriptive and unique (e.g., `searchLocationForMap` vs `searchLocationForRoute`)
  - Ensure event handler functions are marked as `async` and async operations are properly awaited
  - Use descriptive function names to avoid conflicts across modules
  - Export functions at the end of the file in both window object and module.exports for maximum compatibility

