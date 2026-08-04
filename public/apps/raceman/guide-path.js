class GuidePathBuilder {
  constructor(roundDist = 25) {
    this.roundDist = roundDist;
  }

  build(course, markers, g) {
    const all = { ...(course.annotations || {}), ...(course.sections || {}) };
    const path = (g && g.guidePts) ? [...g.guidePts] : [];

    for (const [key, s] of Object.entries(course.sections || {})) {
      if (s.type === 'arrow-area' && key === 'beach_start') {
        const beachStart = this._resolveRef(markers, all, s.from);
        if (beachStart && beachStart.length === 2 && (path.length === 0 || !this._same(beachStart, path[0]))) {
          path.unshift(beachStart);
        }
        break;
      }
    }

    return path;
  }

  _same(a, b) {
    return a && b && a[0] === b[0] && a[1] === b[1];
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
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = GuidePathBuilder;
} else if (typeof window !== 'undefined') {
  window.GuidePathBuilder = GuidePathBuilder;
}
