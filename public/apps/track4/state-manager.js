class StateManager {
  constructor(courseId) {
    this.courseId = courseId;
    this.state = {
      overrides: {},
      hidden: new Set()
    };
    this.saveTimer = null;
  }

  /**
   * Get storage key for current course
   * @returns {string} Storage key
   */
  getStorageKey() {
    return 'track-marker-overrides-' + this.courseId;
  }

  /**
   * Get merged markers with overrides applied
   * @param {Object} courseData - Course data containing markers
   * @returns {Array} Merged markers
   */
  getMergedMarkers(courseData) {
    return Object.entries(courseData.markers || {}).map(([id, m]) => ({ 
      id, 
      ...m, 
      ...(this.state.overrides[id] || {}) 
    }));
  }

  /**
   * Save overrides to localStorage
   */
  saveOverrides() {
    try {
      localStorage.setItem(this.getStorageKey(), JSON.stringify(this.state.overrides));
    } catch (e) {
      console.warn('failed to save overrides', e);
    }
    this.saveToServer();
  }

  /**
   * Load overrides from localStorage
   */
  loadOverrides() {
    try {
      this.state.overrides = JSON.parse(localStorage.getItem(this.getStorageKey()) || '{}');
    } catch {
      this.state.overrides = {};
    }
  }

  /**
   * Load state from server
   */
  async loadServerState() {
    try {
      const r = await fetch(`api/load.php?course=${this.courseId}`);
      if (!r.ok) throw new Error(`load ${r.status}`);
      const data = await r.json();
      if (data && typeof data === 'object') {
        if (data.overrides && typeof data.overrides === 'object') {
          this.state.overrides = data.overrides;
        }
        if (Array.isArray(data.hidden)) {
          this.state.hidden = new Set(data.hidden);
        }
      }
    } catch (e) {
      console.warn('server load failed, using local overrides', e);
    }
  }

  /**
   * Save state to server (debounced)
   */
  saveToServer() {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(async () => {
      try {
        const payload = { 
          course: this.courseId, 
          overrides: this.state.overrides, 
          hidden: [...this.state.hidden] 
        };
        await fetch('api/save.php', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (e) {
        console.warn('server save failed', e);
      }
    }, 500);
  }

  /**
   * Update marker override
   * @param {string} id - Marker ID
   * @param {Object} override - Override data (lat, lon)
   */
  updateMarkerOverride(id, override) {
    this.state.overrides[id] = override;
    this.saveOverrides();
  }

  /**
   * Set hidden sections
   * @param {Set} hidden - Set of hidden section keys
   */
  setHidden(hidden) {
    this.state.hidden = hidden;
  }

  /**
   * Get hidden sections
   * @returns {Set} Set of hidden section keys
   */
  getHidden() {
    return this.state.hidden;
  }

  /**
   * Check if section is hidden
   * @param {string} key - Section key
   * @returns {boolean} Whether section is hidden
   */
  isHidden(key) {
    return this.state.hidden.has(key);
  }

  /**
   * Toggle section visibility
   * @param {string} key - Section key
   * @param {boolean} hidden - Whether to hide
   */
  toggleSection(key, hidden) {
    if (hidden) {
      this.state.hidden.add(key);
    } else {
      this.state.hidden.delete(key);
    }
  }

  /**
   * Get current state
   * @returns {Object} Copy of current state
   */
  getState() {
    return {
      overrides: { ...this.state.overrides },
      hidden: new Set(this.state.hidden)
    };
  }

  /**
   * Set course ID
   * @param {string} courseId - New course ID
   */
  setCourseId(courseId) {
    this.courseId = courseId;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = StateManager;
} else if (typeof window !== 'undefined') {
  window.StateManager = StateManager;
}