/**
 * Map3D - 3D Map Viewer
 * 
 * A dedicated app for 3D visualization including:
 * - Point cloud rendering from PLY files
 * - Tiltable 3D map overlay
 * - Transparent wall visualization
 * 
 * Note: Gaussian splat rendering moved to test page (/apps/test-splat/)
 * due to library compatibility issues. Use test page for experimentation.
 */

import { SplatLayer } from './splat-layer.js';

let map = null;
let splatLayer = null;
let currentScene = null;

// Scene definitions
const scenes = [
  {
    id: 'test-cube',
    name: 'Test Cube',
    file: './data/test-points.ply',
    bounds: [[13.2435, 100.9280], [13.2450, 100.9300]],
    center: [13.2442, 100.9292]
  }
];

async function init() {
  // Initialize MapLibre GL map
  map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8,
      sources: {
        'satellite': {
          type: 'raster',
          tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
          tileSize: 256,
          attribution: '© Esri'
        }
      },
      layers: [{
        id: 'satellite',
        type: 'raster',
        source: 'satellite',
        minzoom: 0,
        maxzoom: 22
      }]
    },
    center: [100.9292, 13.2442],
    zoom: 18,
    pitch: 0,
    bearing: 0
  });

  // Wait for map to load
  map.on('load', () => {
    console.log('MapLibre GL map loaded');

    // Setup controls collapse toggle
    const controlsToggle = document.getElementById('controls-toggle');
    const controlsContent = document.getElementById('controls-content');
    controlsToggle.addEventListener('click', () => {
      controlsToggle.classList.toggle('collapsed');
      controlsContent.classList.toggle('collapsed');
    });

    // Prevent map from intercepting touch events on controls panel
    const controlsPanel = document.getElementById('controls');
    controlsPanel.addEventListener('touchstart', (e) => e.stopPropagation(), { passive: true });
    controlsPanel.addEventListener('touchmove', (e) => e.stopPropagation(), { passive: true });
    controlsPanel.addEventListener('touchend', (e) => e.stopPropagation(), { passive: true });

    // Populate scene selector
    const sceneSelect = document.getElementById('scene-select');
    scenes.forEach(scene => {
      const option = document.createElement('option');
      option.value = scene.id;
      option.textContent = scene.name;
      sceneSelect.appendChild(option);
    });

    // Auto-select first scene and enable 3D for testing
    if (scenes.length > 0) {
      sceneSelect.value = scenes[0].id;
      loadScene(scenes[0].id);
      // Auto-enable 3D
      document.getElementById('toggle-3d').checked = true;
      enable3D();
    }

    setStatus('Ready - select a scene and enable 3D');
  });

  // Scene selection handler
  document.getElementById('scene-select').addEventListener('change', async (e) => {
    const sceneId = e.target.value;
    if (sceneId) {
      await loadScene(sceneId);
    } else {
      clearScene();
    }
  });

  // 3D toggle handler
  document.getElementById('toggle-3d').addEventListener('change', (e) => {
    if (e.target.checked && currentScene) {
      enable3D();
    } else {
      disable3D();
    }
  });

  // Button-based controls for tilt, bearing, zoom
  let currentTilt = 0;
  let currentBearing = 0;
  let currentZoom = 18;
  let isDraggingSlider = false; // Track when user is actively dragging a slider

  // Initialize slider elements
  const tiltSlider = document.getElementById('tilt-slider');
  const bearingSlider = document.getElementById('bearing-slider');
  const zoomSlider = document.getElementById('zoom-slider');
  const tiltSliderValue = document.getElementById('tilt-slider-value');
  const bearingSliderValue = document.getElementById('bearing-slider-value');
  const zoomSliderValue = document.getElementById('zoom-slider-value');

  // Slider event listeners with drag tracking
  if (tiltSlider) {
    tiltSlider.addEventListener('mousedown', () => { isDraggingSlider = true; });
    tiltSlider.addEventListener('touchstart', () => { isDraggingSlider = true; });
    tiltSlider.addEventListener('mouseup', () => { isDraggingSlider = false; });
    tiltSlider.addEventListener('touchend', () => { isDraggingSlider = false; });
    tiltSlider.addEventListener('mouseleave', () => { isDraggingSlider = false; });
    
    tiltSlider.addEventListener('input', (e) => {
      currentTilt = parseInt(e.target.value);
      if (tiltSliderValue) tiltSliderValue.textContent = currentTilt + '°';
      document.getElementById('tilt-value').textContent = currentTilt + '°';
      map.easeTo({ pitch: currentTilt }, { duration: 100 });
      if (splatLayer) splatLayer.setTilt(currentTilt);
    });
  }

  if (bearingSlider) {
    bearingSlider.addEventListener('mousedown', () => { isDraggingSlider = true; });
    bearingSlider.addEventListener('touchstart', () => { isDraggingSlider = true; });
    bearingSlider.addEventListener('mouseup', () => { isDraggingSlider = false; });
    bearingSlider.addEventListener('touchend', () => { isDraggingSlider = false; });
    bearingSlider.addEventListener('mouseleave', () => { isDraggingSlider = false; });
    
    bearingSlider.addEventListener('input', (e) => {
      currentBearing = parseInt(e.target.value);
      if (bearingSliderValue) bearingSliderValue.textContent = currentBearing + '°';
      document.getElementById('bearing-value').textContent = currentBearing + '°';
      map.easeTo({ bearing: currentBearing }, { duration: 100 });
    });
  }

  if (zoomSlider) {
    zoomSlider.addEventListener('mousedown', () => { isDraggingSlider = true; });
    zoomSlider.addEventListener('touchstart', () => { isDraggingSlider = true; });
    zoomSlider.addEventListener('mouseup', () => { isDraggingSlider = false; });
    zoomSlider.addEventListener('touchend', () => { isDraggingSlider = false; });
    zoomSlider.addEventListener('mouseleave', () => { isDraggingSlider = false; });
    
    zoomSlider.addEventListener('input', (e) => {
      currentZoom = parseFloat(e.target.value);
      if (zoomSliderValue) zoomSliderValue.textContent = currentZoom.toFixed(1);
      document.getElementById('zoom-value').textContent = currentZoom.toFixed(1);
      map.easeTo({ zoom: currentZoom }, { duration: 100 });
    });
  }

  const buttons = document.querySelectorAll('.btn-small');
  console.log('Found buttons:', buttons.length);
  
  buttons.forEach(btn => {
    console.log('Button dataset:', btn.dataset);
    btn.addEventListener('click', (e) => {
      const control = e.currentTarget.dataset.control;
      const action = e.currentTarget.dataset.action;
      console.log('Button clicked:', control, action);

      if (!map) {
        console.error('Map not initialized');
        return;
      }

      if (control === 'tilt') {
        if (action === 'increase') currentTilt = Math.min(60, currentTilt + 5);
        else currentTilt = Math.max(0, currentTilt - 5);
        document.getElementById('tilt-value').textContent = currentTilt + '°';
        if (tiltSlider) tiltSlider.value = currentTilt;
        if (tiltSliderValue) tiltSliderValue.textContent = currentTilt + '°';
        console.log('Setting pitch to:', currentTilt);
        console.log('Current map pitch:', map.getPitch());
        map.easeTo({ pitch: currentTilt }, { duration: 300 });
        if (splatLayer) splatLayer.setTilt(currentTilt);
        setTimeout(() => console.log('Map pitch after easeTo:', map.getPitch()), 350);
      } else if (control === 'bearing') {
        if (action === 'increase') currentBearing = (currentBearing + 15) % 360;
        else currentBearing = (currentBearing - 15 + 360) % 360;
        document.getElementById('bearing-value').textContent = currentBearing + '°';
        if (bearingSlider) bearingSlider.value = currentBearing;
        if (bearingSliderValue) bearingSliderValue.textContent = currentBearing + '°';
        console.log('Setting bearing to:', currentBearing);
        map.easeTo({ bearing: currentBearing }, { duration: 300 });
      } else if (control === 'zoom') {
        if (action === 'increase') currentZoom = Math.min(22, currentZoom + 0.5);
        else currentZoom = Math.max(10, currentZoom - 0.5);
        document.getElementById('zoom-value').textContent = currentZoom;
        if (zoomSlider) zoomSlider.value = currentZoom;
        if (zoomSliderValue) zoomSliderValue.textContent = currentZoom.toFixed(1);
        console.log('Setting zoom to:', currentZoom);
        map.easeTo({ zoom: currentZoom }, { duration: 300 });
      }
    });
  });

  // Sync text displays with map changes (but NOT slider values to prevent feedback loop)
  map.on('pitch', (e) => {
    currentTilt = Math.round(e.target.pitch);
    document.getElementById('tilt-value').textContent = currentTilt + '°';
    if (tiltSliderValue) tiltSliderValue.textContent = currentTilt + '°';
    // Don't update slider.value to prevent feedback loop
  });

  map.on('rotate', (e) => {
    currentBearing = Math.round(e.target.bearing);
    document.getElementById('bearing-value').textContent = currentBearing + '°';
    if (bearingSliderValue) bearingSliderValue.textContent = currentBearing + '°';
    // Don't update slider.value to prevent feedback loop
  });

  map.on('zoom', (e) => {
    currentZoom = e.target.zoom;
    document.getElementById('zoom-value').textContent = currentZoom.toFixed(1);
    if (zoomSliderValue) zoomSliderValue.textContent = currentZoom.toFixed(1);
    // Don't update slider.value to prevent feedback loop
  });

  // Reset view button
  document.getElementById('reset-view').addEventListener('click', () => {
    map.flyTo({
      center: [100.9292, 13.2442],
      zoom: 18,
      pitch: 0,
      bearing: 0,
      duration: 1000
    });
  });

  // Camera preset buttons
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const preset = e.target.dataset.preset;
      const center = map.getCenter();
      
      switch (preset) {
        case 'top-down':
          map.flyTo({
            center: center,
            zoom: 18,
            pitch: 0,
            bearing: 0,
            duration: 1000
          });
          break;
        case 'isometric':
          map.flyTo({
            center: center,
            zoom: 17,
            pitch: 45,
            bearing: 45,
            duration: 1000
          });
          break;
        case 'side':
          map.flyTo({
            center: center,
            zoom: 16,
            pitch: 60,
            bearing: 90,
            duration: 1000
          });
          break;
      }
    });
  });

  // Walls toggle handler
  document.getElementById('toggle-walls').addEventListener('change', (e) => {
    if (splatLayer) {
      splatLayer.setWallsVisible(e.target.checked);
    }
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Don't trigger shortcuts when typing in inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    const center = map.getCenter();
    const zoom = map.getZoom();
    const pitch = map.getPitch();
    const bearing = map.getBearing();

    switch (e.key) {
      case 'r':
      case 'R':
        // Reset view
        map.flyTo({
          center: [100.9292, 13.2442],
          zoom: 18,
          pitch: 0,
          bearing: 0,
          duration: 1000
        });
        break;
      case 'ArrowUp':
        // Pan north
        map.easeTo({ center: [center[0], center[1] + 0.001] }, { duration: 100 });
        break;
      case 'ArrowDown':
        // Pan south
        map.easeTo({ center: [center[0], center[1] - 0.001] }, { duration: 100 });
        break;
      case 'ArrowLeft':
        // Pan west
        map.easeTo({ center: [center[0] - 0.001, center[1]] }, { duration: 100 });
        break;
      case 'ArrowRight':
        // Pan east
        map.easeTo({ center: [center[0] + 0.001, center[1]] }, { duration: 100 });
        break;
      case '+':
      case '=':
        // Zoom in
        map.easeTo({ zoom: Math.min(22, zoom + 0.5) }, { duration: 100 });
        break;
      case '-':
      case '_':
        // Zoom out
        map.easeTo({ zoom: Math.max(10, zoom - 0.5) }, { duration: 100 });
        break;
      case '[':
        // Tilt up (increase pitch)
        map.easeTo({ pitch: Math.min(60, pitch + 5) }, { duration: 100 });
        if (splatLayer) splatLayer.setTilt(Math.min(60, pitch + 5));
        break;
      case ']':
        // Tilt down (decrease pitch)
        map.easeTo({ pitch: Math.max(0, pitch - 5) }, { duration: 100 });
        if (splatLayer) splatLayer.setTilt(Math.max(0, pitch - 5));
        break;
      case 'Shift':
        // Shift alone does nothing, handled with arrow keys below
        break;
      default:
        // Check for Shift + arrow keys for rotation
        if (e.shiftKey) {
          switch (e.key) {
            case 'ArrowLeft':
              // Rotate left (decrease bearing)
              map.easeTo({ bearing: (bearing - 15 + 360) % 360 }, { duration: 100 });
              break;
            case 'ArrowRight':
              // Rotate right (increase bearing)
              map.easeTo({ bearing: (bearing + 15) % 360 }, { duration: 100 });
              break;
          }
        }
    }
  });
}

async function loadScene(sceneId) {
  setStatus('Loading scene...');
  
  const scene = scenes.find(s => s.id === sceneId);
  if (!scene) {
    setStatus('Error: Scene not found');
    return;
  }

  currentScene = scene;

  // Clear existing layer
  if (splatLayer) {
    splatLayer.onRemove(map);
    splatLayer = null;
  }

  // Move map to scene bounds (MapLibre GL expects [lng, lat] order)
  // Scene bounds are [[south, west], [north, east]] -> convert to [[west, south], [east, north]]
  const mapBounds = [
    [scene.bounds[0][1], scene.bounds[0][0]], // [west, south]
    [scene.bounds[1][1], scene.bounds[1][0]]  // [east, north]
  ];
  map.fitBounds(mapBounds);

  setStatus(`Scene loaded: ${scene.name}`);
}

function enable3D() {
  if (!currentScene) {
    setStatus('Error: No scene selected');
    return;
  }

  setStatus('Initializing 3D renderer...');

  splatLayer = new SplatLayer({
    splatUrl: currentScene.file,
    gpsBounds: currentScene.bounds,
    gpsCenter: currentScene.center
  });

  splatLayer.addTo(map);

  setStatus('3D enabled');
}

function disable3D() {
  if (splatLayer) {
    splatLayer.onRemove(map);
    splatLayer = null;
  }
  setStatus('3D disabled');
}

function clearScene() {
  disable3D();
  currentScene = null;
  setStatus('Scene cleared');
}

function setStatus(message) {
  document.getElementById('status').textContent = message;
}

// Initialize on load
init();
