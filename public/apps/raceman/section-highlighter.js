class SectionHighlighter {
  constructor(renderer) {
    this.renderer = renderer;
    this.map = renderer.map;
    this.layer = renderer.highlightLayer || L.layerGroup().addTo(this.map);
    this.paneName = 'highlightPane';
    if (!this.map.getPane(this.paneName)) {
      const pane = this.map.createPane(this.paneName);
      pane.style.zIndex = 650;
    }
    this.drawables = [];
  }

  setDrawables(drawables) {
    this.drawables = drawables || [];
  }

  getSection(key) {
    const list = this.drawables.length ? this.drawables : (this.renderer.lastDrawables || []);
    return list.find(d => d.kind === 'section' && d.key === key);
  }

  bindToList(listEl, getDrawables) {
    if (!listEl) return;
    const rows = listEl.querySelectorAll('[data-key]');
    for (const row of rows) {
      const key = row.dataset.key;
      row.onmouseenter = () => {
        this.setDrawables(getDrawables ? getDrawables() : (this.renderer.lastDrawables || []));
        this.highlight(key);
      };
      row.onmouseleave = () => this.clear();
    }
  }

  highlight(key) {
    this.clear();
    const d = this.getSection(key);
    if (!d || !d.points) return;
    const pts = d.points.map(p => [p[0], p[1]]);
    this._pts = pts;
    const color = d.color || '#ffffff';
    this._color = color;

    // Enhanced base line with glow effect
    L.polyline(pts, { 
      color, 
      weight: 4, 
      opacity: 0.7, 
      lineCap: 'round', 
      lineJoin: 'round', 
      interactive: false, 
      pane: this.paneName,
      className: 'highlight-section-line'
    }).addTo(this.layer);

    // Add glow effect layer
    L.polyline(pts, { 
      color, 
      weight: 8, 
      opacity: 0.3, 
      lineCap: 'round', 
      lineJoin: 'round', 
      interactive: false, 
      pane: this.paneName,
      className: 'highlight-section-glow'
    }).addTo(this.layer);

    // Add section endpoints
    if (pts.length >= 2) {
      this._startPoint = L.circleMarker(pts[0], {
        radius: 8,
        color: color,
        fillColor: color,
        fillOpacity: 0.5,
        weight: 2,
        pane: this.paneName,
        className: 'highlight-section-endpoint'
      }).addTo(this.layer);

      this._endPoint = L.circleMarker(pts[pts.length - 1], {
        radius: 8,
        color: color,
        fillColor: color,
        fillOpacity: 0.5,
        weight: 2,
        pane: this.paneName,
        className: 'highlight-section-endpoint'
      }).addTo(this.layer);
    }

    this._arrowColor = '#facc15';
    const h = Course.bearing(pts[0], pts[1] || pts[0]);
    this._movingArrow = L.marker(pts[0], { icon: this.animatedArrowIcon(h, this._arrowColor), interactive: false, pane: this.paneName }).addTo(this.layer);
    this._t = 0;
    this._speed = 0.001;
    this._startAnimation();
  }

  _startAnimation() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    const step = () => {
      if (!this._movingArrow || !this._pts) return;
      this._t += this._speed;
      if (this._t > 1) this._t -= 1;
      const along = Course.pointAlong(this._pts, this._t);
      const p = along && along.point ? along.point : this._pts[0];
      const b = along && along.bearing != null ? along.bearing : Course.bearing(this._pts[0], this._pts[1] || this._pts[0]);
      this._movingArrow.setLatLng(p);
      const el = this._movingArrow.getElement();
      if (el) {
        const svg = el.querySelector('svg');
        if (svg) svg.style.setProperty('--arrow-heading', `${b.toFixed(1)}deg`);
      }
      this._rafId = requestAnimationFrame(step);
    };
    this._rafId = requestAnimationFrame(step);
  }

  animatedArrowIcon(heading, color = '#facc15') {
    return L.divIcon({
      className: 'highlight-arrow',
      html: `<svg viewBox="0 0 24 24" fill="${color}" stroke="rgba(0,0,0,0.5)" stroke-width="1.5" style="--arrow-heading: ${heading.toFixed(1)}deg; transform: rotate(var(--arrow-heading)); filter: drop-shadow(0 0 5px ${color});"><path d="M12 2l10 18H2z"/></svg>`,
      iconSize: [40, 40],
      iconAnchor: [20, 20]
    });
  }

  clear() {
    if (this._rafId) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
    this._movingArrow = null;
    this._pts = null;
    this._startPoint = null;
    this._endPoint = null;
    this.layer.clearLayers();
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = SectionHighlighter;
} else if (typeof window !== 'undefined') {
  window.SectionHighlighter = SectionHighlighter;
}
