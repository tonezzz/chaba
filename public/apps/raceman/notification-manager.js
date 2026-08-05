class NotificationManager {
  constructor(options = {}) {
    this.defaultDuration = options.defaultDuration || 3000;
    this.defaultElementId = options.defaultElementId || 'course-msg';
    this.successClass = options.successClass || 'text-green-400';
    this.errorClass = options.errorClass || 'text-red-400';
    this.infoClass = options.infoClass || 'text-blue-400';
  }

  /**
   * Show a notification message
   * @param {string} message - Message to display
   * @param {Object} options - Notification options
   * @param {string} options.type - Notification type (success, error, info)
   * @param {number} options.duration - Duration in milliseconds
   * @param {string} options.elementId - Element ID to show message in
   */
  show(message, options = {}) {
    const {
      type = 'info',
      duration = this.defaultDuration,
      elementId = this.defaultElementId
    } = options;

    const msgEl = document.getElementById(elementId);
    if (!msgEl) {
      console.warn(`Notification element not found: ${elementId}`);
      return;
    }

    // Clear existing classes
    msgEl.classList.remove(this.successClass, this.errorClass, this.infoClass);

    // Add type-specific class
    const typeClass = this.getClassForType(type);
    if (typeClass) {
      msgEl.classList.add(typeClass);
    }

    // Set message
    msgEl.textContent = message;

    // Auto-dismiss after duration
    setTimeout(() => {
      this.clear(elementId);
    }, duration);
  }

  /**
   * Clear notification message
   * @param {string} elementId - Element ID to clear
   */
  clear(elementId = this.defaultElementId) {
    const msgEl = document.getElementById(elementId);
    if (msgEl) {
      msgEl.classList.remove(this.successClass, this.errorClass, this.infoClass);
      msgEl.textContent = '';
    }
  }

  /**
   * Show success notification
   * @param {string} message - Success message
   * @param {Object} options - Additional options
   */
  success(message, options = {}) {
    this.show(message, { ...options, type: 'success' });
  }

  /**
   * Show error notification
   * @param {string} message - Error message
   * @param {Object} options - Additional options
   */
  error(message, options = {}) {
    this.show(message, { ...options, type: 'error' });
  }

  /**
   * Show info notification
   * @param {string} message - Info message
   * @param {Object} options - Additional options
   */
  info(message, options = {}) {
    this.show(message, { ...options, type: 'info' });
  }

  /**
   * Get CSS class for notification type
   * @param {string} type - Notification type
   * @returns {string} CSS class name
   */
  getClassForType(type) {
    switch (type) {
      case 'success':
        return this.successClass;
      case 'error':
        return this.errorClass;
      case 'info':
        return this.infoClass;
      default:
        return this.infoClass;
    }
  }

  /**
   * Show drag completion notification
   * @param {string} markerId - Marker ID
   * @param {string} markerLabel - Marker label
   * @param {number} lat - New latitude
   * @param {number} lon - New longitude
   */
  showDragNotification(markerId, markerLabel, lat, lon) {
    const label = markerLabel || markerId;
    const message = `Moved ${label} to ${lat.toFixed(6)}, ${lon.toFixed(6)}`;
    this.success(message);
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = NotificationManager;
} else if (typeof window !== 'undefined') {
  window.NotificationManager = NotificationManager;
}