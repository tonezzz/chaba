class SectionBuilder {
  constructor(roundDist = 25) {
    this.roundDist = roundDist;
  }

  build(course, markers, g) {
    const all = { ...(course.annotations || {}), ...(course.sections || {}) };
    const rawSections = this._resolveRawSections(course, markers, all);
    const roundArcs = g.roundArcs || new Map();
    const sectionEntries = Object.entries(course.sections || {});
    const drawables = [];

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
        color = s.color || this._tint(i, sectionEntries.length);
      } else if (s.type === 'round-bouy' || s.type === 'round-buoy') {
        const arc = roundArcs.get(key);
        points = arc.arcPoints;
        end = arc.exit;
        width = s.width || 8;
        color = s.color || this._tint(i, sectionEntries.length);
        extra = { center: arc.center, entry: arc.entry, exit: arc.exit, turn: arc.turn };
      } else {
        continue;
      }

      let distance = 0;
      for (let k = 1; k < points.length; k++) distance += Course.haversine(points[k - 1], points[k]);
      drawables.push({ kind: 'section', key, points, end, color, text: s.text || key, width, dash: s.dash || '4,4', distance, ...extra });
    }

    return drawables;
  }

  _resolveRawSections(course, markers, all) {
    const raw = new Map();
    const sectionEntries = Object.entries(course.sections || {});
    for (const [key, s] of sectionEntries) {
      if (s.type === 'arrow-area') {
        raw.set(key, { kind: 'arrow-area', from: this._resolveRef(markers, all, s.from), to: this._resolveRef(markers, all, s.to) });
      } else if (s.type === 'round-bouy' || s.type === 'round-buoy') {
        const zoneKey = s.bouy || s.buoy || s.zone || s.mark;
        const centerPt = this._resolveRef(markers, all, zoneKey);
        const zone = all[zoneKey];
        const radius = s.rounding_radius || s.radius || (zone && zone.radius) || this.roundDist;
        raw.set(key, { kind: 'round-bouy', center: centerPt, radius, rounding: s.rounding || 'starboard' });
      }
    }
    return raw;
  }

  _resolveRef(markers, all, ref, seen = new Set()) {
    if (Array.isArray(ref)) return ref;
    if (ref && typeof ref === 'object' && 'lat' in ref && 'lon' in ref) return [ref.lat, ref.lon];
    if (typeof ref !== 'string') return [0, 0];
    if (seen.has(ref)) return [0, 0];
    seen.add(ref);
    const m = Course.markerById(markers, ref);
    if (m) return [m.lat, m.lon];
    const a = all[ref];
    if (!a) return [0, 0];
    if (a.type === 'line') return Course.midpoint(this._resolveRef(markers, all, a.from, seen), this._resolveRef(markers, all, a.to, seen));
    if (a.type === 'zone') return this._resolveRef(markers, all, a.mark, seen);
    if (a.type === 'arrow-area') return Course.midpoint(this._resolveRef(markers, all, a.from, seen), this._resolveRef(markers, all, a.to, seen));
    if (a.type === 'round-bouy' || a.type === 'round-buoy') return this._resolveRef(markers, all, a.bouy || a.buoy || a.zone || a.mark, seen);
    return [0, 0];
  }

  _tint(i, n) {
    const l = 30 + (i / (n - 1 || 1)) * 50;
    return `hsl(48, 100%, ${l.toFixed(1)}%)`;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = SectionBuilder;
} else if (typeof window !== 'undefined') {
  window.SectionBuilder = SectionBuilder;
}
