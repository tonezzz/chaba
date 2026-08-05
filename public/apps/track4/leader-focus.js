class LeaderFocus {
  constructor() {
    this.state = {
      enabled: true,
      manualSection: null
    };
  }

  /**
   * Update the focus status display
   * @param {Object} options - Update options
   * @param {Array} options.sections - Available sections
   * @param {Array} options.racers - Current racers
   * @param {Function} options.currentSection - Function to get current section name
   */
  updateStatus(options = {}) {
    const { sections, racers, currentSection } = options;
    const el = document.getElementById('focus-status');
    if (!el) return;
    
    if (!this.state.enabled) {
      el.textContent = '';
      return;
    }
    
    if (this.state.manualSection) {
      const section = sections?.find(s => s.key === this.state.manualSection);
      el.textContent = `Focused: ${section ? (section.text || section.key) : this.state.manualSection}`;
    } else {
      if (!racers || !racers.length) {
        el.textContent = 'Start simulation to follow leader';
        return;
      }
      const leader = racers.sort((a, b) => b.distance - a.distance)[0];
      if (leader) {
        const section = currentSection ? currentSection(leader) : '—';
        el.textContent = `Section: ${section}`;
      } else {
        el.textContent = 'Section: —';
      }
    }
  }

  /**
   * Apply leader focus visual effects
   * @param {Object} options - Apply options
   * @param {Array} options.sections - Available sections
   * @param {Array} options.racers - Current racers
   * @param {Function} options.currentSectionKey - Function to get current section key
   * @param {Object} options.renderer - Course renderer instance
   */
  applyFocus(options = {}) {
    const { sections, racers, currentSectionKey, renderer } = options;
    
    document.body.classList.toggle('leader-focus-active', this.state.enabled);
    if (!this.state.enabled || !renderer) return;
    
    let targetSectionKey = this.state.manualSection;
    let leader = null;
    
    if (!targetSectionKey) {
      if (!racers || !racers.length) return;
      leader = racers.sort((a, b) => b.distance - a.distance)[0];
      if (leader && currentSectionKey) targetSectionKey = currentSectionKey(leader);
    } else {
      leader = racers?.sort((a, b) => b.distance - a.distance)[0];
    }
    
    if (!targetSectionKey) return;
    
    const targetSection = sections?.find(s => s.key === targetSectionKey);
    
    // Apply section highlighting
    sections?.forEach(s => {
      const isTarget = s.key === targetSectionKey;
      const polyline = s.polyline;
      if (polyline) {
        const el = polyline.getElement();
        if (el) {
          if (el.tagName === 'path') {
            if (isTarget) {
              el.classList.add('leader-section');
              el.classList.remove('dimmed-section');
            } else {
              el.classList.add('dimmed-section');
              el.classList.remove('leader-section');
            }
          }
        }
      }
    });
    
    // Highlight racers in target section
    racers?.forEach(r => {
      const rSectionKey = currentSectionKey ? currentSectionKey(r) : null;
      const isTarget = rSectionKey === targetSectionKey;
      const iconEl = r.marker?.getElement();
      if (iconEl) {
        if (isTarget) {
          iconEl.classList.add('leader-racer');
          iconEl.classList.remove('dimmed-racer');
        } else {
          iconEl.classList.add('dimmed-racer');
          iconEl.classList.remove('leader-racer');
        }
      }
    });
    
    this.updateSectionListHighlight(targetSectionKey);
  }

  /**
   * Update section list highlighting
   * @param {string} targetKey - Target section key
   */
  updateSectionListHighlight(targetKey) {
    const rows = document.querySelectorAll('.section-row');
    rows.forEach(row => {
      if (row.dataset.key === targetKey) {
        row.classList.add('focus-section');
      } else {
        row.classList.remove('focus-section');
      }
    });
  }

  /**
   * Set manual section focus
   * @param {string} sectionKey - Section key to focus
   */
  setManualSection(sectionKey) {
    this.state.manualSection = sectionKey;
    this.state.enabled = true;
  }

  /**
   * Clear manual section focus
   */
  clearManualSection() {
    this.state.manualSection = null;
  }

  /**
   * Toggle focus state
   * @param {boolean} enabled - Whether focus should be enabled
   */
  setEnabled(enabled) {
    this.state.enabled = enabled;
    if (!enabled) {
      this.state.manualSection = null;
    }
  }

  /**
   * Get current focus state
   * @returns {Object} Copy of focus state
   */
  getState() {
    return { ...this.state };
  }

  /**
   * Set up focus toggle UI
   * @param {Object} options - Setup options
   * @param {Function} options.onToggle - Callback when focus is toggled
   * @param {Function} options.onApply - Callback to apply focus effects
   */
  setupUI(options = {}) {
    const { onToggle, onApply } = options;
    
    const focusToggle = document.getElementById('toggle-focus-leader');
    if (focusToggle) {
      focusToggle.checked = this.state.enabled;
      focusToggle.onchange = (e) => {
        this.setEnabled(e.target.checked);
        if (onToggle) onToggle(this.state);
        if (onApply) onApply();
      };
    }
    
    // Keyboard shortcut
    document.addEventListener('keydown', (e) => {
      if (e.key === 'l' || e.key === 'L') {
        if (focusToggle) {
          focusToggle.checked = !focusToggle.checked;
          this.setEnabled(focusToggle.checked);
          if (onToggle) onToggle(this.state);
          if (onApply) onApply();
        }
      }
    });
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = LeaderFocus;
} else if (typeof window !== 'undefined') {
  window.LeaderFocus = LeaderFocus;
}