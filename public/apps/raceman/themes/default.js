class DefaultTheme {
  constructor(options = {}) {
    this.roundDist = options.roundDist || 25;
    this.icons = {
      'sausage-orange': '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="#f97316" stroke="#fff" stroke-width="2"/></svg>',
      'flag-checkered': '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" fill="#fff"/><path d="M3 3h9v9H3zm9 9h9v9h-9z" fill="#111"/></svg>',
      'flag-square': '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="#ef4444" stroke="#fff" stroke-width="2"/></svg>'
    };
  }

  markerIcon(name, label) {
    const svg = this.icons[name] || this.defaultMarkerIcon(name);
    return L.divIcon({ className: 'marker-icon enhanced-marker', html: svg, iconSize: [32, 32], iconAnchor: [16, 16] });
  }

  defaultMarkerIcon(name) {
    const colors = {
      'start': '#22c55e',
      'finish': '#ef4444', 
      '1': '#3b82f6',
      '2': '#a855f7',
      '3': '#f59e0b',
      '4': '#06b6d4',
      '5': '#ec4899',
      'default': '#64748b'
    };
    const color = colors[name] || colors['default'];
    return `<svg viewBox="0 0 24 24">
      <defs>
        <filter id="marker-glow-${name}">
          <feGaussianBlur stdDeviation="1" result="coloredBlur"/>
          <feMerge>
            <feMergeNode in="coloredBlur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>
      <circle cx="12" cy="12" r="10" fill="${color}" stroke="#fff" stroke-width="2" filter="url(#marker-glow-${name})"/>
      <circle cx="12" cy="12" r="4" fill="#fff" opacity="0.8"/>
      <text x="12" y="16" text-anchor="middle" fill="#fff" font-size="8" font-weight="bold">${name}</text>
    </svg>`;
  }

  markerLabelIcon(label) {
    return L.divIcon({ 
      className: 'marker-label enhanced-marker-label', 
      html: `<span class="label-text">${label}</span>`, 
      iconSize: [70, 18], 
      iconAnchor: [35, 0] 
    });
  }

  lineLabelIcon(text, rotation = 0) {
    const style = `position:absolute;left:50%;top:50%;white-space:nowrap;transform:translate(-50%,-50%) rotate(${rotation.toFixed(1)}deg);`;
    return L.divIcon({ className: 'line-label', html: `<span style="${style}">${text}</span>`, iconSize: [1, 1], iconAnchor: [0, 0] });
  }

  highlightLabelIcon(text, rotation = 0) {
    const style = `position:absolute;left:50%;top:50%;white-space:nowrap;transform:translate(-50%,-50%) rotate(${rotation.toFixed(1)}deg);`;
    return L.divIcon({ className: 'line-label-highlight', html: `<span style="${style}">${text}</span>`, iconSize: [1, 1], iconAnchor: [0, 0] });
  }

  arrowIcon(heading) {
    return L.divIcon({ className: 'arrow-icon course-arrow', html: `<svg viewBox="0 0 24 24" fill="#38bdf8" style="transform: rotate(${heading}deg)"><path d="M12 2l10 18H2z"/></svg>`, iconSize: [16, 16], iconAnchor: [8, 8] });
  }

  windIcon(heading, speed) {
    const text = speed != null ? `<text x="12" y="22" text-anchor="middle" fill="#e0f2fe" font-size="7" font-family="sans-serif" font-weight="bold">${speed} kt</text>` : '';
    const speedColor = this.getWindSpeedColor(speed);
    return L.divIcon({ 
      className: 'wind-icon enhanced-wind-icon', 
      html: `<svg viewBox="0 0 24 24" style="transform: rotate(${heading}deg)">
        <defs>
          <filter id="wind-glow-${speed}">
            <feGaussianBlur stdDeviation="1.5" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
        </defs>
        <path d="M12 2l10 18H2z" fill="${speedColor}" filter="url(#wind-glow-${speed})" stroke="#fff" stroke-width="0.5"/>
        <circle cx="12" cy="12" r="2" fill="#fff" opacity="0.8"/>
      </svg>${text}`, 
      iconSize: [32, 32], 
      iconAnchor: [16, 16] 
    });
  }

  getWindSpeedColor(speed) {
    if (speed == null) return '#0ea5e9';
    if (speed < 10) return '#22c55e'; // Light wind - green
    if (speed < 15) return '#eab308'; // Moderate wind - yellow
    if (speed < 20) return '#f97316'; // Strong wind - orange
    return '#ef4444'; // Very strong wind - red
  }

  boatIcon(color, heading) {
    return L.divIcon({ className: 'racer-icon', html: `<svg viewBox="0 0 24 24" style="transform: rotate(${heading.toFixed(1)}deg); color:${color}; fill:currentColor; filter:drop-shadow(0 0 2px rgba(0,0,0,0.8));"><path d="M3 17 Q12 23 21 17 L19 13 H5 Z M12 4 L7 14 h10 Z"/></svg>`, iconSize: [20, 20], iconAnchor: [10, 10] });
  }

  drawLine(p1, p2, color, text, side = 'left', dash = '8,6', drawPoly = true, renderer) {
    if (drawPoly) {
      L.polyline([p1, p2], { color, weight: 4, dashArray: dash }).addTo(renderer.guideLayer);
    }
    const mid = Course.midpoint(p1, p2);
    const h = Course.bearing(p1, p2);
    const labelSide = side === 'right' || side === 'starboard' || side === 'bottom' ? 'right' : 'left';
    const labelPos = Course.offsetPoint(mid, h, 6, labelSide);
    const labelRot = h - 90;
    L.marker(labelPos, { icon: this.lineLabelIcon(text, labelRot), interactive: false }).addTo(renderer.guideLayer);
  }

  drawOne(d, renderer, onDrag) {
    switch (d.kind) {
      case 'marker': {
        const pos = [d.m.lat, d.m.lon];
        const marker = L.marker(pos, { icon: this.markerIcon(d.m.icon, d.m.label), draggable: true })
          .addTo(renderer.markerLayer)
          .bindPopup(`<b>${d.m.label || d.m.id}</b><br>${d.m.description || ''}`);
        
        // Use drag manager if available, otherwise fall back to inline handling
        if (renderer.dragManager) {
          renderer.dragManager.setCallbacks({
            onDrag: onDrag
          });
          renderer.dragManager.setupMarkerDrag(marker, d.m);
        } else if (onDrag) {
          // Fallback to inline drag handling
          marker.on('dragend', (e) => { 
            const ll = e.target.getLatLng(); 
            onDrag(d.m.id, ll.lat, ll.lng); 
          });
        }
        
        L.marker(pos, { icon: this.markerLabelIcon(d.m.label || d.m.id), interactive: false }).addTo(renderer.markerLayer);
        return;
      }
      case 'line':
      case 'path':
        this.drawLine(d.p1, d.p2, d.color, d.text, d.side, d.dash, d.drawPoly, renderer);
        return;
      case 'zone': {
        const m = d.m;
        L.circle([m.lat, m.lon], { radius: d.radius || this.roundDist, color: d.color || '#f59e0b', weight: 1, dashArray: '4,4', fill: false }).addTo(renderer.zoneLayer);
        return;
      }
      case 'section': {
        const pts = d.points.map(p => [p[0], p[1]]);
        d.polyline = L.polyline(pts, { className: 'section-line', color: d.color, weight: d.width || 8, dashArray: d.dash, opacity: 0.8, lineCap: 'round', lineJoin: 'round' }).addTo(renderer.guideLayer);
        const mid = Course.pointAlong(pts, 0.5);
        if (mid && mid.point) {
          L.marker(mid.point, { icon: this.lineLabelIcon(d.text, mid.bearing - 90), interactive: false }).addTo(renderer.guideLayer);
        }
        if (d.center && d.entry && d.exit) {
          L.polyline([[d.center[0], d.center[1]], [d.entry[0], d.entry[1]]], { className: 'section-line', color: d.color, weight: 1, dashArray: '2,4', opacity: 0.6 }).addTo(renderer.guideLayer);
          L.polyline([[d.center[0], d.center[1]], [d.exit[0], d.exit[1]]], { className: 'section-line', color: d.color, weight: 1, dashArray: '2,4', opacity: 0.6 }).addTo(renderer.guideLayer);
        }
        if (pts.length >= 2) {
          const pre = pts[pts.length - 2];
          const end = pts[pts.length - 1];
          const h = Course.bearing(pre, end);
          L.marker(end, { icon: this.arrowIcon(h), interactive: false }).addTo(renderer.guideLayer);
        }
        return;
      }
      case 'label': {
        L.marker([d.pos[0], d.pos[1]], { icon: this.lineLabelIcon(d.text), interactive: false }).addTo(renderer.guideLayer);
        return;
      }
      case 'guidePath': {
        // guide path is intentionally not rendered
        return;
      }
      case 'wind': {
        L.marker([d.center[0], d.center[1]], { icon: this.windIcon(d.direction, d.speed), interactive: false }).addTo(renderer.guideLayer);
        return;
      }
    }
  }
}
