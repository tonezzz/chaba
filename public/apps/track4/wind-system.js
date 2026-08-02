class WindSystem {
  constructor() {
    this.config = {
      direction: 180, // Wind from direction (degrees)
      speed: 15, // Wind speed in knots
      gustFactor: 0.2, // Gust variability (0-1)
      variability: 10 // Direction variability (degrees)
    };
  }

  /**
   * Calculate wind factor for boat speed based on heading and wind conditions
   * @param {number} heading - Boat heading in degrees
   * @returns {number} Wind factor (multiplier for boat speed)
   */
  simWindFactor(heading) {
    const windDir = this.config.direction;
    const windSpeed = this.config.speed;
    const gustFactor = this.config.gustFactor;
    const variability = this.config.variability;
    
    // Add some randomness to wind direction (gusts and shifts)
    const effectiveWindDir = windDir + (Math.random() - 0.5) * variability * 2;
    
    // Calculate angle difference between boat heading and wind direction
    const angleDiff = Math.abs(((heading - effectiveWindDir + 540) % 360) - 180);
    
    // Base wind factor based on point of sail
    // Upwind (close-hauled): slower, Downwind (reaching/running): faster
    const baseFactor = 0.55 + 0.45 * (1 - Math.cos(angleDiff * Math.PI / 180));
    
    // Add gust effect (random speed variation)
    const gustEffect = 1 + (Math.random() - 0.5) * gustFactor;
    
    // Wind speed modifier (stronger wind = faster, but with diminishing returns)
    const speedModifier = Math.min(1.5, 0.5 + windSpeed / 20);
    
    return baseFactor * gustEffect * speedModifier;
  }

  /**
   * Set wind configuration
   * @param {Object} config - Wind configuration object
   * @param {number} config.direction - Wind direction in degrees
   * @param {number} config.speed - Wind speed in knots
   * @param {number} config.gustFactor - Gust variability (0-1)
   * @param {number} config.variability - Direction variability in degrees
   */
  setConfig(config) {
    if (config) {
      this.config = {
        ...this.config,
        ...config
      };
    }
  }

  /**
   * Get current wind configuration
   * @returns {Object} Copy of current wind configuration
   */
  getConfig() {
    return { ...this.config };
  }

  /**
   * Set up wind control UI elements
   * @param {Object} options - Setup options
   * @param {Function} options.onApply - Callback when wind configuration is applied
   * @param {Function} options.onReinit - Callback to reinitialize simulation
   */
  setupUI(options = {}) {
    const { onApply, onReinit } = options;
    
    const windDirSlider = document.getElementById('wind-direction');
    const windSpeedSlider = document.getElementById('wind-speed');
    const windGustSlider = document.getElementById('wind-gust');
    const applyWindBtn = document.getElementById('apply-wind');
    
    // Update wind direction display
    const updateWindDirectionDisplay = () => {
      const dir = parseInt(windDirSlider.value);
      const dirValueEl = document.getElementById('wind-direction-value');
      const dirLabelEl = document.getElementById('wind-direction-label');
      
      if (dirValueEl) dirValueEl.textContent = dir + '°';
      
      // Convert to compass direction
      if (dirLabelEl) {
        const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const index = Math.round(dir / 45) % 8;
        dirLabelEl.textContent = directions[index];
      }
    };
    
    // Update wind speed display
    const updateWindSpeedDisplay = () => {
      const speed = parseInt(windSpeedSlider.value);
      const speedValueEl = document.getElementById('wind-speed-value');
      if (speedValueEl) speedValueEl.textContent = speed;
    };
    
    // Update wind gust display
    const updateWindGustDisplay = () => {
      const gust = parseFloat(windGustSlider.value);
      const gustValueEl = document.getElementById('wind-gust-value');
      if (gustValueEl) gustValueEl.textContent = gust.toFixed(2);
    };
    
    // Apply wind configuration
    const applyWindConfig = () => {
      this.setConfig({
        direction: parseInt(windDirSlider.value),
        speed: parseInt(windSpeedSlider.value),
        gustFactor: parseFloat(windGustSlider.value),
        variability: 10 // Fixed for now
      });
      
      console.log('Wind configuration applied:', this.getConfig());
      
      if (onApply) onApply(this.getConfig());
      
      // Reinitialize simulation if callback provided
      if (onReinit) onReinit();
    };
    
    // Set up event listeners
    if (windDirSlider) {
      windDirSlider.oninput = updateWindDirectionDisplay;
    }
    if (windSpeedSlider) {
      windSpeedSlider.oninput = updateWindSpeedDisplay;
    }
    if (windGustSlider) {
      windGustSlider.oninput = updateWindGustDisplay;
    }
    if (applyWindBtn) {
      applyWindBtn.onclick = applyWindConfig;
    }
    
    // Initialize displays from current configuration
    if (windDirSlider) windDirSlider.value = this.config.direction;
    if (windSpeedSlider) windSpeedSlider.value = this.config.speed;
    if (windGustSlider) windGustSlider.value = this.config.gustFactor;
    
    updateWindDirectionDisplay();
    updateWindSpeedDisplay();
    updateWindGustDisplay();
  }

  /**
   * Load wind configuration from course YAML
   * @param {Object} courseData - Course data object
   */
  loadFromCourse(courseData) {
    if (courseData && courseData.course && courseData.course.wind) {
      const courseWind = courseData.course.wind;
      this.setConfig({
        direction: courseWind.direction || this.config.direction,
        speed: courseWind.speed_kts || this.config.speed,
        gustFactor: courseWind.gust_factor || this.config.gustFactor,
        variability: courseWind.variability || this.config.variability
      });
    }
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = WindSystem;
} else if (typeof window !== 'undefined') {
  window.WindSystem = WindSystem;
}