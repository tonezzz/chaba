class RaceSimulation {
  constructor(options = {}) {
    this.map = options.map;
    this.renderer = options.renderer;
    this.raceLayer = options.raceLayer || L.layerGroup().addTo(this.map);
    this.boatColors = options.boatColors || ['#ef4444','#22c55e','#3b82f6','#f59e0b','#a855f7','#ec4899','#06b6d4','#eab308','#6366f1','#14b8a6'];
    this.racerProfiles = options.racerProfiles || [];
    this.windSystem = options.windSystem;
    this.leaderFocus = options.leaderFocus;
    this.getCourseData = options.getCourseData;
    this.getMergedMarkers = options.getMergedMarkers;
    
    this.state = {
      running: false,
      rafId: null,
      elapsed: 0,
      racers: [],
      speedFactor: 1,
      lastTs: 0,
      path: null
    };
    
    this.highlightedRacer = null;
  }

  boatIcon(color, heading, racer = null) {
    if (this.renderer && this.renderer.theme && typeof this.renderer.theme.boatIcon === 'function') {
      return this.renderer.theme.boatIcon(color, heading, racer);
    }
    return L.divIcon({
      className: 'racer-icon',
      html: `<svg viewBox="0 0 24 24" style="transform: rotate(${heading.toFixed(1)}deg); color:${color}; fill:currentColor; filter:drop-shadow(0 0 2px rgba(0,0,0,0.8));"><path d="M3 17 Q12 23 21 17 L19 13 H5 Z M12 4 L7 14 h10 Z"/></svg>`,
      iconSize: [20, 20], iconAnchor: [10, 10]
    });
  }

  simWindFactor(heading) {
    return this.windSystem ? this.windSystem.simWindFactor(heading) : 1;
  }

  startPenalty(dist) {
    const s = (this.state.path && this.state.path.startDist) || 0;
    if (dist < s) return 0.3;
    const ramp = 30;
    if (dist >= s + ramp) return 1;
    return 0.3 + 0.7 * ((dist - s) / ramp);
  }

  buildSimPath() {
    const guide = this.renderer.guide;
    const guidePts = guide.guidePts;
    const markers = this.getMergedMarkers();
    const courseData = this.getCourseData();
    const Course = window.Course;
    
    const beachEntry = Course.lineEntry(courseData.course, 'beach_start');
    const beach1 = Course.coordsOf(markers, beachEntry.from);
    const beach2 = Course.coordsOf(markers, beachEntry.to);
    const beachMid = Course.midpoint(beach1, beach2);
    const lineLen = Course.haversine(beach1, beach2);
    const beachBearing = Course.bearing(beach1, beach2);
    const startMid = guidePts[0];
    const toStart = Course.bearing(beachMid, startMid);
    const reverse = toStart + 180;
    const perpA = beachBearing + 90;
    const perpB = beachBearing - 90;
    const diff = deg => Math.abs(((deg - reverse) % 360 + 540) % 360 - 180);
    const behindBearing = diff(perpA) < diff(perpB) ? perpA : perpB;
    const startBehind = Course.pointAt(beachMid, behindBearing, 5);
    const pts = [startBehind, beachMid, startMid, ...guidePts.slice(1)];
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum[i] = cum[i - 1] + Course.haversine(pts[i - 1], pts[i]);
    const sectionRanges = this.buildSectionRanges(pts, cum, guide);
    return { pts, cum, total: cum[cum.length - 1], startDist: cum[2], beachBearing, lineLen, sectionRanges };
  }

  buildSectionRanges(pts, cum, guide) {
    const guidePts = guide.guidePts;
    const roundArcs = guide.roundArcs || new Map();
    const roundQueue = [];
    const courseData = this.getCourseData();
    
    for (const [key, s] of Object.entries(courseData.course.sections || {})) {
      if (s.type === 'round-bouy' || s.type === 'round-buoy') {
        const arc = roundArcs.get(key);
        if (arc) roundQueue.push(arc);
      }
    }
    const find = p => guidePts.findIndex(x => x === p);
    const ranges = [{ endDist: cum[1], text: 'Pre-start' }];
    for (const [key, s] of Object.entries(courseData.course.sections || {})) {
      let endDist = null;
      if (key === 'beach_start') {
        endDist = cum[2];
      } else if (s.type === 'round-bouy' || s.type === 'round-buoy') {
        const arc = roundArcs.get(key);
        if (arc) {
          const idx = find(arc.exit);
          endDist = idx >= 0 ? cum[idx + 2] : null;
        }
        if (roundQueue.length && roundQueue[0] === arc) roundQueue.shift();
      } else if (s.type === 'arrow-area') {
        if (s.to === 'finish_line') {
          endDist = cum[cum.length - 1];
        } else if (roundQueue.length) {
          const arc = roundQueue[0];
          const idx = find(arc.entry);
          endDist = idx >= 0 ? cum[idx + 2] : null;
        }
      }
      if (endDist != null && endDist > ranges[ranges.length - 1].endDist) {
        ranges.push({ key, endDist, text: s.text || key });
      }
    }
    return ranges;
  }

  findSegment(dist) {
    const { cum } = this.state.path;
    for (let i = 1; i < cum.length; i++) {
      if (dist < cum[i]) return i - 1;
    }
    return cum.length - 2;
  }

  updateRacer(r, dt) {
    const Course = window.Course;
    if (r.returned) return;
    if (r.returning) {
      const pos = r.marker.getLatLng();
      const start = r.startPos;
      const d = Course.haversine([pos.lat, pos.lng], start);
      if (d < 3) {
        r.returned = true;
        r.speed = 0;
        r.marker.setLatLng(start);
        if (r.hoverMarker) r.hoverMarker.setLatLng(start);
        return;
      }
      let h = Course.bearing([pos.lat, pos.lng], start) + (Math.random() * 60 - 30);
      const speed = 3 + Math.random() * 2;
      const next = Course.pointAt([pos.lat, pos.lng], h, speed * dt);
      r.heading = r.heading ? (r.heading * 0.6 + h * 0.4) : h;
      r.marker.setLatLng(next);
      r.marker.setIcon(this.boatIcon(r.color, r.heading, r));
      r.speed = speed;
      if (r.hoverMarker) r.hoverMarker.setLatLng(next);
      return;
    }
    const { pts, cum, total } = this.state.path;
    if (r.distance >= total) { r.distance = total; r.finished = true; r.returning = true; r.speed = 0; return; }
    const seg = this.findSegment(r.distance);
    const p1 = pts[seg], p2 = pts[seg + 1];
    const segLen = cum[seg + 1] - cum[seg];
    const t = segLen ? (r.distance - cum[seg]) / segLen : 0;
    const heading = Course.bearing(p1, p2);
    r.speed = r.baseSpeed * this.simWindFactor(heading) * (0.85 + Math.random() * 0.3) * this.startPenalty(r.distance) * this.state.speedFactor;
    r.distance += r.speed * dt;
    if (r.distance >= total) { r.distance = total; r.finished = true; r.returning = true; r.speed = 0; return; }
    const newT = segLen ? Math.min(1, (r.distance - cum[seg]) / segLen) : 0;
    const rawLat = p1[0] + (p2[0] - p1[0]) * newT;
    const rawLon = p1[1] + (p2[1] - p1[1]) * newT;
    r.heading = r.heading ? (r.heading * 0.6 + heading * 0.4) : heading;
    let pos = [rawLat, rawLon];
    if (r.distance < this.state.path.startDist) {
      pos = Course.pointAt(pos, this.state.path.beachBearing, r.startOffset || 0);
    } else {
      const lane = r.lanes[seg] + (r.lanes[seg + 1] - r.lanes[seg]) * newT;
      if (Math.abs(lane) > 0.1) pos = Course.pointAt(pos, heading + (lane >= 0 ? 90 : -90), Math.abs(lane));
    }
    r.marker.setLatLng(pos);
    r.marker.setIcon(this.boatIcon(r.color, r.heading, r));
    if (r.hoverMarker) r.hoverMarker.setLatLng(pos);
  }

  simStep(ts) {
    if (!this.state.running) return;
    if (!this.state.lastTs) this.state.lastTs = ts;
    const dt = (ts - this.state.lastTs) / 1000;
    this.state.lastTs = ts;
    this.state.elapsed += dt;
    const active = this.state.racers.filter(r => !r.returned);
    if (!active.length) { this.stop(); this.updateSimStandings(); return; }
    for (const r of this.state.racers) this.updateRacer(r, dt);
    this.resolveCollisions(this.state.racers);
    this.updateSimStandings();
    if (this.onFocusApply) this.onFocusApply();
    this.state.rafId = requestAnimationFrame(this.simStep.bind(this));
  }

  initRacers() {
    const Course = window.Course;
    if (!this.renderer.guide || !this.renderer.guide.guidePts.length) return;
    this.highlightedRacer = null;
    this.state.path = this.buildSimPath();
    const pts = this.state.path.pts;
    const { beachBearing, lineLen } = this.state.path;
    this.raceLayer.clearLayers();
    this.state.racers = [];
    const count = Math.min(10, Math.max(2, parseInt(document.getElementById('sim-racers').value, 10) || 10));
    const maxSpread = Math.min((lineLen || 0) * 0.8, Math.min(80, count * 10));
    const spacing = count > 1 ? maxSpread / (count - 1) : 0;
    const shuffled = [...this.racerProfiles].sort(() => Math.random() - 0.5);
    for (let i = 0; i < count; i++) {
      const color = this.boatColors[i % this.boatColors.length];
      const startOffset = (i - (count - 1) / 2) * spacing;
      const lanes = pts.map(() => (Math.random() * 8 - 4));
      lanes[2] = startOffset;
      const h = Course.bearing(pts[0], pts[1] || pts[0]);
      const startPos = Course.pointAt(pts[0], beachBearing, startOffset);
      const profile = shuffled[i % shuffled.length];
      const sail = `${profile.code}-${100 + i * 9}`;
      const r = {
        name: profile.name, color, baseSpeed: 5 + Math.random() * 4,
        startOffset, startPos, lanes, distance: 0, finished: false, returning: false, returned: false, speed: 0, heading: h, sail, flag: profile.flag, code: profile.code
      };
      const marker = L.marker(startPos, { icon: this.boatIcon(color, h, r), zIndexOffset: 1000 }).addTo(this.raceLayer);
      marker.on('mouseover', () => this.highlightRacer(r));
      marker.on('mouseout', () => this.clearRacerHighlight());
      r.marker = marker;
      this.state.racers.push(r);
    }
    this.updateSimStandings();
  }

  resolveCollisions(racers) {
    const Course = window.Course;
    const MIN = 6;
    const active = racers.filter(r => !r.finished);
    for (let pass = 0; pass < 3; pass++) {
      for (let i = 0; i < active.length; i++) {
        for (let j = i + 1; j < active.length; j++) {
          const a = active[i].marker.getLatLng();
          const b = active[j].marker.getLatLng();
          const d = Course.haversine([a.lat, a.lng], [b.lat, b.lng]);
          if (d > 0 && d < MIN) {
            const overlap = (MIN - d) / 2;
            const h = Course.bearing([a.lat, a.lng], [b.lat, b.lng]);
            active[i].marker.setLatLng(Course.pointAt([a.lat, a.lng], h, -overlap));
            active[j].marker.setLatLng(Course.pointAt([b.lat, b.lng], h, overlap));
          }
        }
      }
    }
  }

  currentSection(r) {
    if (r.finished) return 'Finished';
    const ranges = (this.state.path && this.state.path.sectionRanges) || [];
    for (const range of ranges) {
      if (r.distance < range.endDist) return range.text;
    }
    return 'Finished';
  }

  currentSectionKey(r) {
    if (r.finished) return null;
    const ranges = (this.state.path && this.state.path.sectionRanges) || [];
    for (const range of ranges) {
      if (r.distance < range.endDist) return range.key || null;
    }
    return null;
  }

  highlightRacer(r) {
    this.clearRacerHighlight();
    this.highlightedRacer = r;
    if (!r) return;
    r.marker.setZIndexOffset(10000);
    const pos = r.marker.getLatLng();
    r.hoverMarker = L.circleMarker([pos.lat, pos.lng], { radius: 14, color: r.color, weight: 3, fillColor: r.color, fillOpacity: 0.25, opacity: 0.9 }).addTo(this.raceLayer);
    const key = this.currentSectionKey(r);
    if (key && this.renderer) this.renderer.highlightSection(key);
  }

  clearRacerHighlight() {
    if (!this.highlightedRacer) return;
    this.highlightedRacer.marker.setZIndexOffset(1000);
    if (this.highlightedRacer.hoverMarker) {
      this.raceLayer.removeLayer(this.highlightedRacer.hoverMarker);
      this.highlightedRacer.hoverMarker = null;
    }
    this.highlightedRacer = null;
    if (this.renderer) this.renderer.clearHighlight();
  }

  updateSimStandings() {
    const el = document.getElementById('sim-standings');
    if (!this.state.racers.length) { el.textContent = 'Press Start to simulate'; return; }
    const { total } = this.state.path || { total: 1 };
    const sorted = [...this.state.racers].sort((a, b) => b.distance - a.distance);
    if (this.renderer && this.renderer.theme && typeof this.renderer.theme.renderStandings === 'function') {
      this.renderer.theme.renderStandings({ sorted, total, elapsed: this.state.elapsed, speedFactor: this.state.speedFactor });
      return;
    }
    const pct = d => total ? (d / total * 100).toFixed(0) : 0;
    const rows = sorted.map((r, i) => `
      <tr class="align-middle whitespace-nowrap" data-name="${r.name}">
        <td class="text-left py-0.5 pr-1 truncate">${i + 1}. <span style="color:${r.color}">●</span> ${r.name}</td>
        <td class="text-left py-0.5 px-1 text-gray-400 truncate">${this.currentSection(r)}</td>
        <td class="text-right py-0.5 px-1 text-gray-400 w-12">${r.finished ? '' : pct(r.distance)}</td>
        <td class="text-right py-0.5 pl-1 text-gray-400 w-14">${(r.speed * 3.6).toFixed(1)}</td>
      </tr>
    `).join('');
    el.innerHTML = `
      <table class="w-full border-collapse table-fixed text-xs">
        <thead>
          <tr class="text-gray-500 whitespace-nowrap">
            <th class="text-left font-normal py-0.5 pr-1 w-1/3">Boat</th>
            <th class="text-left font-normal py-0.5 px-1 w-1/3">Section</th>
            <th class="text-right font-normal py-0.5 px-1 w-16">%</th>
            <th class="text-right font-normal py-0.5 pl-1 w-16">km/h</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  dimCourse(active) {
    document.body.classList.toggle('sim-active', !!active);
  }

  start() {
    if (this.state.running) return;
    if (!this.state.racers.length || this.state.racers.every(r => r.returned)) this.initRacers();
    if (!this.state.racers.length) return;
    this.state.speedFactor = parseFloat(document.getElementById('sim-speed').value) || 1;
    this.state.running = true; this.state.lastTs = 0;
    this.dimCourse(true);
    this.state.rafId = requestAnimationFrame(this.simStep.bind(this));
  }

  stop() {
    this.state.running = false;
    cancelAnimationFrame(this.state.rafId);
    this.state.rafId = null;
    this.state.lastTs = 0;
    this.dimCourse(false);
  }

  setupUI(options = {}) {
    this.initRacers();
    document.getElementById('sim-start').onclick = () => this.start();
    document.getElementById('sim-reset').onclick = () => { this.stop(); this.initRacers(); };
    document.getElementById('sim-racers').oninput = () => { this.stop(); this.initRacers(); };
    document.getElementById('sim-speed').oninput = (e) => { this.state.speedFactor = parseFloat(e.target.value) || 1; };
    
    // Set up wind system UI
    if (this.windSystem) {
      this.windSystem.setupUI({
        onApply: (config) => {
          console.log('Wind configuration applied:', config);
        },
        onReinit: () => {
          if (this.state.running) {
            this.stop();
            this.initRacers();
          }
        }
      });
    }
    
    // Set up leader focus UI
    if (this.leaderFocus) {
      this.leaderFocus.setupUI({
        onToggle: (state) => {
          if (options.onFocusToggle) options.onFocusToggle(state);
        },
        onApply: () => {
          if (options.onFocusApply) options.onFocusApply();
        }
      });
    }
    this.onFocusApply = options.onFocusApply || null;
    
    document.addEventListener('keydown', (e) => {
      if (e.key === 'l' || e.key === 'L') {
        const focusToggle = document.getElementById('toggle-focus-leader');
        if (focusToggle) {
          focusToggle.checked = !focusToggle.checked;
          if (options.onFocusToggle) options.onFocusToggle(focusToggle.checked);
          if (options.onFocusApply) options.onFocusApply();
        }
      }
    });
    
    const standingsEl = document.getElementById('sim-standings');
    if (standingsEl) {
      standingsEl.onmouseover = (e) => {
        const tr = e.target.closest('[data-name]');
        if (!tr) return;
        const r = this.state.racers.find(x => x.name === tr.dataset.name);
        if (r) this.highlightRacer(r);
      };
      standingsEl.onmouseout = (e) => {
        const tr = e.target.closest('[data-name]');
        if (!tr) return;
        this.clearRacerHighlight();
      };
    }
  }

  getState() {
    return this.state;
  }

  getRacers() {
    return this.state.racers;
  }
}