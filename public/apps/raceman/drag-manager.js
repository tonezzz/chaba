class DragManager {
  constructor(options = {}) {
    this.onDragCallback = options.onDrag || null;
    this.onDragStartCallback = options.onDragStart || null;
    this.onDragEndCallback = options.onDragEnd || null;
    this.draggingMarker = null;
    this.originalPositions = new Map();
  }

  /**
   * Set up drag handling for a marker
   * @param {Object} marker - Leaflet marker instance
   * @param {Object} markerData - Marker data object
   */
  setupMarkerDrag(marker, markerData) {
    if (!marker || !markerData) return;

    marker.on('dragstart', (e) => this.handleDragStart(e, markerData));
    marker.on('drag', (e) => this.handleDrag(e, markerData));
    marker.on('dragend', (e) => this.handleDragEnd(e, markerData));
  }

  /**
   * Handle drag start event
   * @param {Object} event - Leaflet drag event
   * @param {Object} markerData - Marker data
   */
  handleDragStart(event, markerData) {
    const el = event.target.getElement();
    if (el) {
      el.classList.add('marker-dragging');
      document.body.style.cursor = 'grabbing';
      document.body.classList.add('dragging-marker');
    }

    // Store original position for potential undo
    const originalPos = event.target.getLatLng();
    this.originalPositions.set(markerData.id, {
      lat: originalPos.lat,
      lng: originalPos.lng
    });
    this.draggingMarker = markerData.id;

    if (this.onDragStartCallback) {
      this.onDragStartCallback(markerData.id, originalPos.lat, originalPos.lng);
    }
  }

  /**
   * Handle drag event (during drag)
   * @param {Object} event - Leaflet drag event
   * @param {Object} markerData - Marker data
   */
  handleDrag(event, markerData) {
    const ll = event.target.getLatLng();
    
    if (this.onDragCallback) {
      this.onDragCallback(markerData.id, ll.lat, ll.lng, true); // true = during drag
    }
  }

  /**
   * Handle drag end event
   * @param {Object} event - Leaflet drag event
   * @param {Object} markerData - Marker data
   */
  handleDragEnd(event, markerData) {
    const el = event.target.getElement();
    if (el) {
      el.classList.remove('marker-dragging');
      document.body.style.cursor = '';
      document.body.classList.remove('dragging-marker');
    }

    const ll = event.target.getLatLng();
    this.draggingMarker = null;

    if (this.onDragCallback) {
      this.onDragCallback(markerData.id, ll.lat, ll.lng, false); // false = drag complete
    }

    if (this.onDragEndCallback) {
      this.onDragEndCallback(markerData.id, ll.lat, ll.lng);
    }
  }

  /**
   * Get original position for a marker
   * @param {string} markerId - Marker ID
   * @returns {Object|null} Original position {lat, lng} or null
   */
  getOriginalPosition(markerId) {
    return this.originalPositions.get(markerId) || null;
  }

  /**
   * Clear stored original positions
   */
  clearOriginalPositions() {
    this.originalPositions.clear();
  }

  /**
   * Check if currently dragging
   * @returns {boolean} Whether a marker is being dragged
   */
  isDragging() {
    return this.draggingMarker !== null;
  }

  /**
   * Get currently dragging marker ID
   * @returns {string|null} Current dragging marker ID or null
   */
  getDraggingMarker() {
    return this.draggingMarker;
  }

  /**
   * Set drag callbacks
   * @param {Object} callbacks - Callback functions
   * @param {Function} callbacks.onDrag - Called during drag
   * @param {Function} callbacks.onDragStart - Called when drag starts
   * @param {Function} callbacks.onDragEnd - Called when drag ends
   */
  setCallbacks(callbacks) {
    if (callbacks.onDrag) this.onDragCallback = callbacks.onDrag;
    if (callbacks.onDragStart) this.onDragStartCallback = callbacks.onDragStart;
    if (callbacks.onDragEnd) this.onDragEndCallback = callbacks.onDragEnd;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = DragManager;
} else if (typeof window !== 'undefined') {
  window.DragManager = DragManager;
}