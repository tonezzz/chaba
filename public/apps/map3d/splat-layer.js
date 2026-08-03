/**
 * SplatLayer - MapLibre GL custom layer for Three.js point cloud renderer
 *
 * Uses Three.js to render point clouds from PLY files. 
 * 
 * Note: Gaussian splat rendering has been moved to test page (/apps/test-splat/)
 * due to library compatibility issues. This layer now focuses on reliable
 * point cloud rendering with GPS mapping and camera sync.
 */

class SplatLayer {
  constructor(options = {}) {
    this.splatUrl = options.splatUrl;
    this.gpsBounds = options.gpsBounds; // [[south, west], [north, east]]
    this.gpsCenter = options.gpsCenter; // Reference GPS point [lat, lon]
    this.sceneOffset = options.sceneOffset || [0, 0, 0];
    this.sceneScale = options.sceneScale || 1.0;
    this._map = null;
    this._loaded = false;
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.points = null;
    this.walls = null;
    this.sceneGroup = null; // Group for scene rotation
    this.tiltAngle = 0; // Scene tilt in degrees (0 = flat, 60 = tilted)
  }

  addTo(map) {
    this._map = map;

    // Create container for Three.js canvas
    this._el = document.createElement('div');
    this._el.className = 'splat-layer';
    this._el.style.position = 'absolute';
    this._el.style.top = '0';
    this._el.style.left = '0';
    this._el.style.width = '100%';
    this._el.style.height = '100%';
    this._el.style.pointerEvents = 'none';
    this._el.style.zIndex = '100';

    map.getCanvasContainer().appendChild(this._el);

    // Initialize Three.js point cloud renderer
    this._initViewer();

    // Sync camera on map moves
    map.on('move', () => this._syncCamera());
    map.on('zoom', () => this._syncCamera());
    map.on('pitch', () => this._syncCamera());
    map.on('rotate', () => this._syncCamera());
    map.on('moveend', () => this._syncCamera());

    // Initial sync
    this._syncCamera();

    return this._el;
  }

  onRemove(map) {
    if (this.renderer) {
      this.renderer.dispose();
      this.renderer = null;
    }
    if (this._el && this._el.parentNode) {
      this._el.parentNode.removeChild(this._el);
    }
    map.off('move', this._syncCamera);
    map.off('zoom', this._syncCamera);
    map.off('pitch', this._syncCamera);
    map.off('rotate', this._syncCamera);
    map.off('moveend', this._syncCamera);
  }

  async _initViewer() {
    try {
      // Import Three.js from CDN
      const THREE = await import('https://esm.sh/three@0.160.0');

      // Create scene
      this.scene = new THREE.Scene();

      // Create camera
      this.camera = new THREE.PerspectiveCamera(75, 1, 0.1, 1000);
      this.camera.position.set(0, 0, 100);

      // Create renderer
      this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
      this.renderer.setSize(this._el.clientWidth, this._el.clientHeight);
      this.renderer.setPixelRatio(window.devicePixelRatio);
      this._el.appendChild(this.renderer.domElement);

      // Load PLY point cloud
      if (this.splatUrl) {
        await this._loadPointCloud(THREE, this.splatUrl);
      }

      // Start render loop
      this._startRenderLoop(THREE);

      this._loaded = true;
      console.log('Point cloud viewer loaded');

    } catch (error) {
      console.error('Failed to initialize point cloud viewer:', error);
      this._el.innerHTML = `<div style="color: #ef4444; padding: 10px; font-size: 12px;">Failed to load point cloud: ${error.message}</div>`;
    }
  }

  async _loadPointCloud(THREE, url) {
    try {
      // Fetch PLY file
      const response = await fetch(url);
      const text = await response.text();

      // Parse simple ASCII PLY format
      const lines = text.split('\n');
      let vertexCount = 0;
      let vertexStart = 0;
      const vertices = [];
      const colors = [];

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line.startsWith('element vertex')) {
          vertexCount = parseInt(line.split(' ')[2]);
        } else if (line === 'end_header') {
          vertexStart = i + 1;
          break;
        }
      }

      // Parse vertex data
      for (let i = vertexStart; i < vertexStart + vertexCount && i < lines.length; i++) {
        const parts = lines[i].trim().split(/\s+/);
        if (parts.length >= 6) {
          const x = parseFloat(parts[0]) * this.sceneScale + this.sceneOffset[0];
          const y = parseFloat(parts[1]) * this.sceneScale + this.sceneOffset[1];
          const z = parseFloat(parts[2]) * this.sceneScale + this.sceneOffset[2];
          const r = parseInt(parts[3]) / 255;
          const g = parseInt(parts[4]) / 255;
          const b = parseInt(parts[5]) / 255;

          vertices.push(x, y, z);
          colors.push(r, g, b);
        }
      }

      // Create geometry
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

      // Skip point cloud rendering - only create walls
      console.log(`Parsed ${vertices.length / 3} points (not rendering)`);

      // Create transparent walls around the point cloud
      this._createWalls(THREE, vertices);

    } catch (error) {
      console.error('Failed to load point cloud:', error);
      throw error;
    }
  }

  _createWalls(THREE, vertices) {
    // Find bounding box of point cloud
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;

    for (let i = 0; i < vertices.length; i += 3) {
      minX = Math.min(minX, vertices[i]);
      maxX = Math.max(maxX, vertices[i]);
      minY = Math.min(minY, vertices[i + 1]);
      maxY = Math.max(maxY, vertices[i + 1]);
      minZ = Math.min(minZ, vertices[i + 2]);
      maxZ = Math.max(maxZ, vertices[i + 2]);
    }

    // Add padding
    const padding = 5;
    minX -= padding; maxX += padding;
    minY -= padding; maxY += padding;
    minZ -= padding; maxZ += padding;

    // Create wall material (transparent cyan)
    const wallMaterial = new THREE.MeshBasicMaterial({
      color: 0x00ffff,
      transparent: true,
      opacity: 0.2,
      side: THREE.DoubleSide,
      depthWrite: false
    });

    // Create 4 walls (north, south, east, west) - reduced height
    const wallHeight = 15; // Fixed shorter height
    const wallThickness = 1;
    const wallBaseZ = 0; // Walls start at ground level (Z=0)

    const walls = [];

    // North wall
    const northGeo = new THREE.BoxGeometry(maxX - minX + wallThickness * 2, wallThickness, wallHeight);
    const northWall = new THREE.Mesh(northGeo, wallMaterial);
    northWall.position.set((minX + maxX) / 2, maxY - wallThickness / 2, wallBaseZ + wallHeight / 2);
    walls.push(northWall);

    // South wall
    const southGeo = new THREE.BoxGeometry(maxX - minX + wallThickness * 2, wallThickness, wallHeight);
    const southWall = new THREE.Mesh(southGeo, wallMaterial);
    southWall.position.set((minX + maxX) / 2, minY + wallThickness / 2, wallBaseZ + wallHeight / 2);
    walls.push(southWall);

    // East wall
    const eastGeo = new THREE.BoxGeometry(wallThickness, maxY - minY + wallThickness * 2, wallHeight);
    const eastWall = new THREE.Mesh(eastGeo, wallMaterial);
    eastWall.position.set(maxX + wallThickness / 2, (minY + maxY) / 2, wallBaseZ + wallHeight / 2);
    walls.push(eastWall);

    // West wall
    const westGeo = new THREE.BoxGeometry(wallThickness, maxY - minY + wallThickness * 2, wallHeight);
    const westWall = new THREE.Mesh(westGeo, wallMaterial);
    westWall.position.set(minX - wallThickness / 2, (minY + maxY) / 2, wallBaseZ + wallHeight / 2);
    walls.push(westWall);

    // Add walls to scene as a group
    this.walls = new THREE.Group();
    walls.forEach(wall => this.walls.add(wall));
    this.walls.visible = true; // Visible by default for easier testing

    // Create scene group for rotation (tilt)
    this.sceneGroup = new THREE.Group();
    this.sceneGroup.add(this.walls);
    this.scene.add(this.sceneGroup);

    console.log('Created transparent walls around point cloud');
  }

  _syncCamera() {
    if (!this.camera || !this._loaded || !this._map) return;

    const map = this._map;
    const center = map.getCenter(); // MapLibre returns [lng, lat]
    const zoom = map.getZoom();
    const pitch = map.getPitch();
    const bearing = map.getBearing();

    // Convert GPS to 3D world coordinates (MapLibre: [lng, lat])
    const worldCenter = this._gpsToWorld(center[1], center[0]);

    // Calculate camera height based on zoom level
    const baseHeight = 100;
    const heightFactor = Math.pow(2, 18 - zoom);
    const cameraHeight = baseHeight * heightFactor;

    // Set camera position (top-down, no tilt - MapLibre handles tilt via pitch)
    this.camera.position.set(worldCenter.x, worldCenter.y, cameraHeight);
    this.camera.lookAt(worldCenter.x, worldCenter.y, 0);
    this.camera.up.set(0, 1, 0);

    // Apply tilt to scene group (walls only) - sync with MapLibre pitch
    if (this.sceneGroup) {
      this.sceneGroup.rotation.x = pitch * Math.PI / 180;
    }

    // Update renderer size
    const size = map.getContainer().getBoundingClientRect();
    this.renderer.setSize(size.width, size.height);
    this.camera.aspect = size.width / size.height;
    this.camera.updateProjectionMatrix();
  }

  setTilt(angle) {
    this.tiltAngle = Math.max(0, Math.min(60, angle)); // Clamp between 0 and 60 degrees
    this._syncCamera();
  }

  setWallsVisible(visible) {
    if (this.walls) {
      this.walls.visible = visible;
    }
  }

  _gpsToWorld(lat, lon) {
    if (!this.gpsCenter) {
      return { x: 0, y: 0 };
    }

    const [refLat, refLon] = this.gpsCenter;
    const R = 6371000; // Earth radius in meters

    const lat1 = refLat * Math.PI / 180;
    const lat2 = lat * Math.PI / 180;
    const lon1 = refLon * Math.PI / 180;
    const lon2 = lon * Math.PI / 180;

    const x = R * (lon2 - lon1) * Math.cos((lat1 + lat2) / 2);
    const y = R * (lat2 - lat1);

    return { x, y };
  }

  _startRenderLoop(THREE) {
    const render = () => {
      if (this.renderer && this._loaded) {
        this.renderer.render(this.scene, this.camera);
      }
      requestAnimationFrame(render);
    };
    requestAnimationFrame(render);
  }

  // Public methods for Leaflet layer interface
  getBounds() {
    return this.gpsBounds;
  }

  setOpacity(opacity) {
    if (this._el) {
      this._el.style.opacity = opacity;
    }
    if (this.points) {
      this.points.material.opacity = opacity;
    }
  }

  bringToFront() {
    if (this._el && this._el.parentNode) {
      this._el.parentNode.appendChild(this._el);
    }
  }

  bringToBack() {
    if (this._el && this._el.parentNode) {
      this._el.parentNode.insertBefore(this._el, this._el.parentNode.firstChild);
    }
  }
}

// ES6 export for module usage
export { SplatLayer };

// CommonJS export for Node.js compatibility
if (typeof module !== 'undefined' && module.exports) {
  module.exports = SplatLayer;
}
// Also attach to window for browser context (legacy)
if (typeof window !== 'undefined') {
  window.SplatLayer = SplatLayer;
}
