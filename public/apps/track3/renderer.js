class CourseRenderer {
  constructor(map, options = {}) {
    this.map = map;
    this.roundDist = options.roundDist || 25;
    this.guideLayer = L.layerGroup().addTo(map);
    this.markerLayer = L.layerGroup().addTo(map);
    this.zoneLayer = L.layerGroup().addTo(map);
    this.highlightLayer = L.layerGroup().addTo(map);
    this.hidden = new Set();
    this.icons = {
      'sausage-orange': '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="#f97316" stroke="#fff" stroke-width="2"/></svg>',
      'flag-checkered': '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" fill="#fff"/><path d="M3 3h9v9H3zm9 9h9v9h-9z" fill="#111"/></svg>',
      'flag-square': '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="#ef4444" stroke="#fff" stroke-width="2"/></svg>'
    };
  }

  markerIcon(name, label) {
    const svg = this.icons[name] || '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="#64748b" stroke="#fff" stroke-width="2"/></svg>';
    return L.divIcon({ className: 'marker-icon', html: svg, iconSize: [28, 28], iconAnchor: [14, 14] });
  }
  markerLabelIcon(label) {
    return L.divIcon({ className: 'marker-label', html: `<span>${label}</span>`, iconSize: [60, 14], iconAnchor: [30, 0] });
  }
  lineLabelIcon(text, rotation = 0) {
    const style = `display:inline-block;white-space:nowrap;transform:rotate(${rotation.toFixed(1)}deg);transform-origin:center;`;
    return L.divIcon({ className: 'line-label', html: `<span style="${style}">${text}</span>`, iconSize: [80, 18], iconAnchor: [40, 9] });
  }
  arrowIcon(heading) {
    return L.divIcon({ className: 'arrow-icon course-arrow', html: `<svg viewBox="0 0 24 24" fill="#38bdf8" style="transform: rotate(${heading}deg)"><path d="M12 2l10 18H2z"/></svg>`, iconSize: [16, 16], iconAnchor: [8, 8] });
  }
  windIcon(heading, speed) {
    const text = speed != null ? `<text x="12" y="22" text-anchor="middle" fill="#e0f2fe" font-size="7" font-family="sans-serif">${speed} kt</text>` : '';
    return L.divIcon({ className: 'wind-icon', html: `<svg viewBox="0 0 24 24" style="transform: rotate(${heading}deg)"><path d="M12 2l10 18H2z" fill="#0ea5e9"/></svg>${text}`, iconSize: [28, 28], iconAnchor: [14, 14] });
  }

  clear() {
    this.guideLayer.clearLayers();
    this.markerLayer.clearLayers();
    this.zoneLayer.clearLayers();
    this.highlightLayer.clearLayers();
  }

  _roleSide(markers, course, g) {
    const roleSide = {};
    if (g.guidePts.length > 1) {
      roleSide.start = Course.pointSide(g.start1, g.start2, g.guidePts[1]);
      const beachAnn = Object.values(course.annotations || {}).find(a => a.type === 'line' && a.role === 'beach_start');
      if (beachAnn) {
        roleSide.beach_start = Course.pointSide(Course.coordsOf(markers, beachAnn.from), Course.coordsOf(markers, beachAnn.to), g.guidePts[1]);
      }
      const lastPass = g.guidePts[g.guidePts.length - 2];
      const finishFront = [2 * g.finishMid[0] - lastPass[0], 2 * g.finishMid[1] - lastPass[1]];
      roleSide.finish = Course.pointSide(g.finish1, g.finish2, finishFront);
    }
    return roleSide;
  }

  buildDrawables(markers, course) {
    const all = { ...(course.annotations || {}), ...(course.sections || {}) };
    const g = Course.buildRoundedGuide(markers, course, this.roundDist);
    const center = {
      lat: markers.reduce((sum, m) => sum + m.lat, 0) / markers.length,
      lon: markers.reduce((sum, m) => sum + m.lon, 0) / markers.length
    };
    const roleSide = this._roleSide(markers, course, g);

    const resolveRef = (ref, seen = new Set()) => {
      if (Array.isArray(ref)) return ref;
      if (ref && typeof ref === 'object' && 'lat' in ref && 'lon' in ref) return [ref.lat, ref.lon];
      if (typeof ref !== 'string') return [0, 0];
      if (seen.has(ref)) return [0, 0];
      seen.add(ref);
      const m = Course.markerById(markers, ref);
      if (m) return [m.lat, m.lon];
      const a = all[ref];
      if (!a) return [0, 0];
      if (a.type === 'line') return Course.midpoint(resolveRef(a.from, seen), resolveRef(a.to, seen));
      if (a.type === 'zone') return resolveRef(a.mark, seen);
      if (a.type === 'arrow-area') return Course.midpoint(resolveRef(a.from, seen), resolveRef(a.to, seen));
      if (a.type === 'round-bouy' || a.type === 'round-buoy') return resolveRef(a.bouy || a.buoy || a.zone || a.mark, seen);
      return [0, 0];
    };

    const drawables = [];
    for (const m of markers) drawables.push({ kind: 'marker', m });

    const drawnLineKeys = new Set();
    for (const [key, a] of Object.entries(course.annotations || {})) {
      if (a.type === 'line') {
        const p1 = Course.coordsOf(markers, a.from);
        const p2 = Course.coordsOf(markers, a.to);
        const lineKey = [a.from, a.to].sort().join('|');
        const drawPoly = !drawnLineKeys.has(lineKey);
        drawnLineKeys.add(lineKey);
        const color = a.color || (a.role === 'start' ? '#22c55e' : a.role === 'finish' ? '#ef4444' : a.role === 'beach_start' ? '#a855f7' : '#38bdf8');
        const side = Course.resolveSide(p1, p2, a.label_side, a.role || key, roleSide, center);
        drawables.push({ kind: 'line', p1, p2, color, text: a.text || a.role || key, side, dash: a.dash || '8,6', drawPoly });
      } else if (a.type === 'zone') {
        const m = Course.markerById(markers, a.mark);
        if (m) drawables.push({ kind: 'zone', m, radius: a.radius, color: a.color });
      } else if (a.type === 'path') {
        const p1 = resolveRef(a.from);
        const p2 = resolveRef(a.to);
        const lineKey = [a.from, a.to].sort().join('|');
        const drawPoly = !drawnLineKeys.has(lineKey);
        drawnLineKeys.add(lineKey);
        const color = a.color || '#64748b';
        const side = Course.resolveSide(p1, p2, a.label_side, a.role || key, roleSide, center);
        drawables.push({ kind: 'path', p1, p2, color, text: a.text || '', side, dash: a.dash || '4,6', drawPoly });
      } else if (a.type === 'label') {
        const m = Course.markerById(markers, a.mark);
        if (m) drawables.push({ kind: 'label', pos: [m.lat, m.lon], text: a.text });
      }
    }

    drawables.push({ kind: 'guidePath', points: g.guidePts });

    if (course.wind) {
      drawables.push({ kind: 'wind', center: [center.lat, center.lon], direction: course.wind.direction, speed: course.wind.speed_kts });
    }

    const sectionEntries = Object.entries(course.sections || {});
    const rawSections = new Map();
    for (const [key, s] of sectionEntries) {
      if (s.type === 'arrow-area') {
        rawSections.set(key, { kind: 'arrow-area', from: resolveRef(s.from), to: resolveRef(s.to) });
      } else if (s.type === 'round-bouy' || s.type === 'round-buoy') {
        const zoneKey = s.bouy || s.buoy || s.zone || s.mark;
        const centerPt = resolveRef(zoneKey);
        const zone = all[zoneKey];
        const radius = s.rounding_radius || s.radius || (zone && zone.radius) || this.roundDist;
        rawSections.set(key, { kind: 'round-bouy', center: centerPt, radius, rounding: s.rounding || 'starboard' });
      }
    }

    const roundArcs = g.roundArcs || new Map();
    const sectionTint = (i, n) => {
      const l = 30 + (i / (n - 1 || 1)) * 50;
      return `hsl(48, 100%, ${l.toFixed(1)}%)`;
    };

    for (let i = 0; i < sectionEntries.length; i++) {
      const [key, s] = sectionEntries[i];
      let points, end, width, color, extra = {};
      if (s.type === 'arrow-area') {
        const raw = rawSections.get(key);
        let p1 = raw.from;
        let p2 = raw.to;
        if (i > 0) {
          const [prevKey, prevS] = sectionEntries[i - 1];
          if ((prevS.type === 'round-bouy' || prevS.type === 'round-buoy') && String(s.from) === String(prevS.bouy || prevS.buoy || prevS.zone || prevS.mark)) {
            const arc = roundArcs.get(prevKey);
            if (arc) p1 = arc.exit;
          }
        }
        if (i + 1 < sectionEntries.length) {
          const [nextKey, nextS] = sectionEntries[i + 1];
          if ((nextS.type === 'round-bouy' || nextS.type === 'round-buoy') && String(s.to) === String(nextS.bouy || nextS.buoy || nextS.zone || nextS.mark)) {
            const arc = roundArcs.get(nextKey);
            if (arc) p2 = arc.entry;
          }
        }
        points = [p1, p2];
        end = p2;
        width = s.width || 8;
        color = s.color || sectionTint(i, sectionEntries.length);
      } else if (s.type === 'round-bouy' || s.type === 'round-buoy') {
        const arc = roundArcs.get(key);
        points = arc.arcPoints;
        end = arc.exit;
        width = s.width || 8;
        color = s.color || sectionTint(i, sectionEntries.length);
        extra = { center: arc.center, entry: arc.entry, exit: arc.exit, turn: arc.turn };
      } else {
        continue;
      }
      let distance = 0;
      for (let k = 1; k < points.length; k++) distance += Course.haversine(points[k - 1], points[k]);
      drawables.push({ kind: 'section', key, points, end, color, text: s.text || key, width, dash: s.dash || '4,4', distance, ...extra });
    }

    return { drawables, g };
  }

  drawLine(p1, p2, color, text, side = 'left', dash = '8,6', drawPoly = true) {
    if (drawPoly) {
      L.polyline([p1, p2], { color, weight: 4, dashArray: dash }).addTo(this.guideLayer);
    }
    const mid = Course.midpoint(p1, p2);
    const h = Course.bearing(p1, p2);
    const labelSide = side === 'right' || side === 'starboard' || side === 'bottom' ? 'right' : 'left';
    const labelPos = Course.offsetPoint(mid, h, 6, labelSide);
    const labelRot = h - 90;
    L.marker(labelPos, { icon: this.lineLabelIcon(text, labelRot), interactive: false }).addTo(this.guideLayer);
  }

  drawOne(d, onDrag) {
    switch (d.kind) {
      case 'marker': {
        const pos = [d.m.lat, d.m.lon];
        const marker = L.marker(pos, { icon: this.markerIcon(d.m.icon, d.m.label), draggable: true })
          .addTo(this.markerLayer)
          .bindPopup(`<b>${d.m.label || d.m.id}</b><br>${d.m.description || ''}`);
        if (onDrag) {
          marker.on('dragend', (e) => { const ll = e.target.getLatLng(); onDrag(d.m.id, ll.lat, ll.lng); });
        }
        L.marker(pos, { icon: this.markerLabelIcon(d.m.label || d.m.id), interactive: false }).addTo(this.markerLayer);
        return;
      }
      case 'line':
      case 'path':
        this.drawLine(d.p1, d.p2, d.color, d.text, d.side, d.dash, d.drawPoly);
        return;
      case 'zone': {
        const m = d.m;
        L.circle([m.lat, m.lon], { radius: d.radius || this.roundDist, color: d.color || '#f59e0b', weight: 1, dashArray: '4,4', fill: false }).addTo(this.zoneLayer);
        return;
      }
      case 'section': {
        const pts = d.points.map(p => [p[0], p[1]]);
        L.polyline(pts, { className: 'section-line', color: d.color, weight: d.width || 8, dashArray: d.dash, opacity: 0.8, lineCap: 'round', lineJoin: 'round' }).addTo(this.guideLayer);
        const midIdx = Math.floor(pts.length / 2);
        const mid = pts[midIdx];
        if (mid) {
          const pBefore = pts[midIdx - 1] || pts[0];
          const pAfter = pts[midIdx + 1] || pts[pts.length - 1];
          const h = Course.bearing(pBefore, pAfter);
          L.marker(mid, { icon: this.lineLabelIcon(d.text, h - 90), interactive: false }).addTo(this.guideLayer);
        }
        if (d.center && d.entry && d.exit) {
          L.polyline([[d.center[0], d.center[1]], [d.entry[0], d.entry[1]]], { className: 'section-line', color: d.color, weight: 1, dashArray: '2,4', opacity: 0.6 }).addTo(this.guideLayer);
          L.polyline([[d.center[0], d.center[1]], [d.exit[0], d.exit[1]]], { className: 'section-line', color: d.color, weight: 1, dashArray: '2,4', opacity: 0.6 }).addTo(this.guideLayer);
        }
        if (pts.length >= 2) {
          const pre = pts[pts.length - 2];
          const end = pts[pts.length - 1];
          const h = Course.bearing(pre, end);
          L.marker(end, { icon: this.arrowIcon(h), interactive: false }).addTo(this.guideLayer);
        }
        return;
      }
      case 'label': {
        L.marker([d.pos[0], d.pos[1]], { icon: this.lineLabelIcon(d.text), interactive: false }).addTo(this.guideLayer);
        return;
      }
      case 'guidePath': {
        // guide path is intentionally not rendered
        return;
      }
      case 'wind': {
        L.marker([d.center[0], d.center[1]], { icon: this.windIcon(d.direction, d.speed), interactive: false }).addTo(this.guideLayer);
        return;
      }
    }
  }

  highlightSection(key) {
    this.highlightLayer.clearLayers();
    if (!this.lastDrawables) return;
    const d = this.lastDrawables.find(x => x.kind === 'section' && x.key === key);
    if (!d || !d.points) return;
    this._drawSectionHighlight(d);
  }

  highlightAllSections() {
    this.highlightLayer.clearLayers();
    if (!this.lastDrawables) return;
    for (const d of this.lastDrawables) {
      if (d.kind === 'section' && d.points && d.points.length) this._drawSectionHighlight(d);
    }
  }

  _drawSectionHighlight(d) {
    const pts = d.points.map(p => [p[0], p[1]]);
    L.polyline(pts, { className: 'animated-section', color: d.color || '#ffffff', weight: (d.width || 8) + 4, opacity: 0.75, interactive: false }).addTo(this.highlightLayer);
    if (pts.length >= 2) {
      const h = Course.bearing(pts[pts.length - 2], pts[pts.length - 1]);
      L.marker(pts[pts.length - 1], { icon: this.arrowIcon(h), interactive: false }).addTo(this.highlightLayer);
    }
  }

  clearHighlight() {
    this.highlightLayer.clearLayers();
  }

  draw(course, markers, options = {}) {
    this.clear();
    const { drawables, g } = this.buildDrawables(markers, course);
    this.lastDrawables = drawables;
    this.guide = g;
    for (const d of drawables) {
      if (this.hidden.size && d.key && this.hidden.has(d.key)) continue;
      this.drawOne(d, options.onDrag);
    }
    if (options.fit) {
      const allPts = markers.map(m => [m.lat, m.lon]);
      this.map.fitBounds(L.latLngBounds(allPts).pad(0.25));
    }
    return g;
  }
}
