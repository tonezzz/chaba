const ROUND_DIST = 25;
const STORAGE_KEY = 'track3-marker-overrides';
let courseData = null;
let renderer = null;
let state = { overrides: {}, hidden: new Set() };

const map = L.map('map');
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);

const raceLayer = L.layerGroup().addTo(map);
const boatColors = ['#ef4444','#22c55e','#3b82f6','#f59e0b','#a855f7','#ec4899','#06b6d4','#eab308','#6366f1','#14b8a6'];
let simState = { running: false, rafId: null, elapsed: 0, racers: [], speedFactor: 1, lastTs: 0, path: null };

function getMergedMarkers() {
  return Object.entries(courseData.markers || {}).map(([id, m]) => ({ id, ...m, ...(state.overrides[id] || {}) }));
}
function saveOverrides() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.overrides)); } catch (e) { console.warn('failed to save overrides', e); }
}
function loadOverrides() {
  try { state.overrides = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { state.overrides = {}; }
}


function updatePanel(course, g) {
  document.getElementById('summary').textContent = `Total: ${g.total.toFixed(0)} m | Laps: ${course.repeat || 1}`;
  const briefEl = document.getElementById('brief');
  if (briefEl) {
    if (Array.isArray(course.brief) && course.brief.length) {
      briefEl.innerHTML = `<ul class="list-disc pl-4 space-y-1">${course.brief.map(b => `<li>${b}</li>`).join('')}</ul>`;
    } else {
      briefEl.innerHTML = '';
    }
  }
  document.getElementById('legs').innerHTML = g.legInfo.map((l, i) =>
    `<div class="flex justify-between"><span>${i + 1}. ${l.label}</span><span class="text-gray-400">${l.distance.toFixed(0)} m</span></div>`
  ).join('');
}

function updateSections(drawables) {
  const list = document.getElementById('sections-list');
  const sections = (drawables || []).filter(d => d.kind === 'section');
  const header = document.getElementById('check-all-sections');
  if (!sections.length) {
    list.innerHTML = '<div class="text-gray-500 text-xs">No sections defined</div>';
    if (header) header.checked = true;
    return;
  }
  const allChecked = sections.every(s => !state.hidden.has(s.key));
  if (header) {
    header.checked = allChecked;
    header.onchange = (e) => {
      for (const s of sections) {
        if (e.target.checked) state.hidden.delete(s.key);
        else state.hidden.add(s.key);
      }
      render(false);
    };
  }
  list.innerHTML = '';
  sections.forEach((s, i) => {
    const checked = !state.hidden.has(s.key) ? 'checked' : '';
    const row = document.createElement('div');
    row.className = 'mb-2';
    row.innerHTML = `
      <div class="flex items-center justify-between">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" class="accent-toggle" data-key="${s.key}" ${checked}>
          <span class="text-white">${i + 1}. ${s.text || s.key}</span>
        </label>
        <button class="text-accent text-xs hover:underline" data-idx="${i}">Inspect</button>
      </div>
      <div class="text-gray-400 text-xs">${s.distance != null ? s.distance.toFixed(0) + ' m' : ''}</div>
    `;
    row.querySelector('input').onchange = (e) => {
      if (e.target.checked) state.hidden.delete(s.key); else state.hidden.add(s.key);
      render(false);
    };
    row.querySelector('button').onclick = () => {
      const pts = s.points.map(p => [p[0], p[1]]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.25));
    };
    row.onmouseenter = () => renderer && renderer.highlightSection(s.key);
    row.onmouseleave = () => renderer && renderer.clearHighlight();
    list.appendChild(row);
  });
}

function activateTab(which) {
  for (const t of ['map', 'sections', 'sim']) {
    const btn = document.getElementById(`tab-${t}`);
    const content = document.getElementById(`tab-${t}-content`);
    if (!btn || !content) continue;
    if (t === which) {
      content.classList.remove('hidden');
      btn.classList.add('bg-gray-700', 'text-white');
      btn.classList.remove('bg-gray-800', 'text-gray-300');
    } else {
      content.classList.add('hidden');
      btn.classList.remove('bg-gray-700', 'text-white');
      btn.classList.add('bg-gray-800', 'text-gray-300');
    }
  }
}

function setupTabs() {
  for (const t of ['map', 'sections', 'sim']) {
    const btn = document.getElementById(`tab-${t}`);
    if (btn) btn.onclick = () => activateTab(t);
  }
  const secBtn = document.getElementById('tab-sections');
  if (secBtn) {
    secBtn.onmouseenter = () => renderer && renderer.highlightAllSections();
    secBtn.onmouseleave = () => renderer && renderer.clearHighlight();
  }
}

function onMarkerDrag(id, lat, lon) {
  state.overrides[id] = { lat, lon };
  saveOverrides();
  render(false);
}

function render(fit = false) {
  const markers = getMergedMarkers();
  renderer.hidden = state.hidden;
  const g = renderer.draw(courseData.course, markers, { onDrag: onMarkerDrag, fit });
  updatePanel(courseData.course, g);
  updateSections(renderer.lastDrawables);
}

function setupToggles() {
  document.getElementById('toggle-guide').addEventListener('change', (e) => {
    if (e.target.checked) renderer.guideLayer.addTo(map); else map.removeLayer(renderer.guideLayer);
  });
  document.getElementById('toggle-markers').addEventListener('change', (e) => {
    if (e.target.checked) renderer.markerLayer.addTo(map); else map.removeLayer(renderer.markerLayer);
  });
  document.getElementById('toggle-zones').addEventListener('change', (e) => {
    if (e.target.checked) renderer.zoneLayer.addTo(map); else map.removeLayer(renderer.zoneLayer);
  });
}

// --- Race simulation ---------------------------------------------------------

function boatIcon(color, heading) {
  return L.divIcon({
    className: 'racer-icon',
    html: `<svg viewBox="0 0 24 24" style="transform: rotate(${heading.toFixed(1)}deg); color:${color}; fill:currentColor; filter:drop-shadow(0 0 2px rgba(0,0,0,0.8));"><path d="M3 17 Q12 23 21 17 L19 13 H5 Z M12 4 L7 14 h10 Z"/></svg>`,
    iconSize: [20, 20], iconAnchor: [10, 10]
  });
}

function simWindFactor(heading) {
  const wind = (courseData.wind && courseData.wind.direction) || 180;
  const a = Math.abs(((heading - wind + 540) % 360) - 180);
  return 0.55 + 0.45 * (1 - Math.cos(a * Math.PI / 180));
}

function startPenalty(dist) {
  const s = (simState.path && simState.path.startDist) || 0;
  if (dist < s) return 0.3;
  const ramp = 30;
  if (dist >= s + ramp) return 1;
  return 0.3 + 0.7 * ((dist - s) / ramp);
}

function buildSimPath() {
  const guide = renderer.guide;
  const guidePts = guide.guidePts;
  const markers = getMergedMarkers();
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
  const sectionRanges = buildSectionRanges(pts, cum, guide);
  return { pts, cum, total: cum[cum.length - 1], startDist: cum[2], beachBearing, lineLen, sectionRanges };
}

function buildSectionRanges(pts, cum, guide) {
  const guidePts = guide.guidePts;
  const roundArcs = guide.roundArcs || new Map();
  const roundQueue = [];
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
      ranges.push({ endDist, text: s.text || key });
    }
  }
  return ranges;
}

function findSegment(dist) {
  const { cum } = simState.path;
  for (let i = 1; i < cum.length; i++) {
    if (dist < cum[i]) return i - 1;
  }
  return cum.length - 2;
}

function updateRacer(r, dt) {
  if (r.finished) return;
  const { pts, cum, total } = simState.path;
  if (r.distance >= total) { r.finished = true; return; }
  const seg = findSegment(r.distance);
  const p1 = pts[seg], p2 = pts[seg + 1];
  const segLen = cum[seg + 1] - cum[seg];
  const t = segLen ? (r.distance - cum[seg]) / segLen : 0;
  const heading = Course.bearing(p1, p2);
  r.speed = r.baseSpeed * simWindFactor(heading) * (0.85 + Math.random() * 0.3) * startPenalty(r.distance) * simState.speedFactor;
  r.distance += r.speed * dt;
  if (r.distance >= total) { r.distance = total; r.finished = true; }
  const newT = segLen ? Math.min(1, (r.distance - cum[seg]) / segLen) : 0;
  const rawLat = p1[0] + (p2[0] - p1[0]) * newT;
  const rawLon = p1[1] + (p2[1] - p1[1]) * newT;
  r.heading = heading;
  let pos = [rawLat, rawLon];
  if (r.distance < simState.path.startDist) {
    pos = Course.pointAt(pos, simState.path.beachBearing, r.startOffset || 0);
  } else {
    const lane = r.lanes[seg] + (r.lanes[seg + 1] - r.lanes[seg]) * newT;
    if (Math.abs(lane) > 0.1) pos = Course.pointAt(pos, heading + (lane >= 0 ? 90 : -90), Math.abs(lane));
  }
  r.marker.setLatLng(pos);
  r.marker.setIcon(boatIcon(r.color, heading));
}

function simStep(ts) {
  if (!simState.running) return;
  if (!simState.lastTs) simState.lastTs = ts;
  const dt = (ts - simState.lastTs) / 1000;
  simState.lastTs = ts;
  simState.elapsed += dt;
  const active = simState.racers.filter(r => !r.finished);
  if (!active.length) { stopSim(); updateSimStandings(); return; }
  for (const r of simState.racers) updateRacer(r, dt);
  resolveCollisions(simState.racers);
  updateSimStandings();
  simState.rafId = requestAnimationFrame(simStep);
}

function initRacers() {
  if (!renderer.guide || !renderer.guide.guidePts.length) return;
  simState.path = buildSimPath();
  const pts = simState.path.pts;
  const { beachBearing, lineLen } = simState.path;
  raceLayer.clearLayers();
  simState.racers = [];
  const count = Math.min(10, Math.max(2, parseInt(document.getElementById('sim-racers').value, 10) || 5));
  const maxSpread = Math.min((lineLen || 0) * 0.8, Math.min(80, count * 10));
  const spacing = count > 1 ? maxSpread / (count - 1) : 0;
  for (let i = 0; i < count; i++) {
    const color = boatColors[i % boatColors.length];
    const startOffset = (i - (count - 1) / 2) * spacing;
    const lanes = pts.map(() => (Math.random() * 8 - 4));
    lanes[2] = startOffset;
    const h = Course.bearing(pts[0], pts[1] || pts[0]);
    const startPos = Course.pointAt(pts[0], beachBearing, startOffset);
    const marker = L.marker(startPos, { icon: boatIcon(color, h), zIndexOffset: 1000 }).addTo(raceLayer);
    simState.racers.push({
      name: `Boat ${i + 1}`, color, baseSpeed: 5 + Math.random() * 4,
      startOffset, lanes, distance: 0, finished: false, marker, speed: 0, heading: h
    });
  }
  updateSimStandings();
}

function resolveCollisions(racers) {
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

function currentSection(r) {
  if (r.finished) return 'Finished';
  const ranges = (simState.path && simState.path.sectionRanges) || [];
  for (const range of ranges) {
    if (r.distance < range.endDist) return range.text;
  }
  return 'Finished';
}

function updateSimStandings() {
  const el = document.getElementById('sim-standings');
  if (!simState.racers.length) { el.textContent = 'Press Start to simulate'; return; }
  const { total } = simState.path || { total: 1 };
  const sorted = [...simState.racers].sort((a, b) => b.distance - a.distance);
  const pct = d => total ? (d / total * 100).toFixed(0) : 0;
  const rows = sorted.map((r, i) => `
    <tr class="align-middle whitespace-nowrap">
      <td class="text-left py-0.5 pr-1 truncate">${i + 1}. <span style="color:${r.color}">●</span> ${r.name}</td>
      <td class="text-left py-0.5 px-1 text-gray-400 truncate">${currentSection(r)}</td>
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

function dimCourse(active) {
  document.body.classList.toggle('sim-active', !!active);
}

function startSim() {
  if (simState.running) return;
  if (!simState.racers.length || simState.racers.every(r => r.finished)) initRacers();
  if (!simState.racers.length) return;
  simState.speedFactor = parseFloat(document.getElementById('sim-speed').value) || 1;
  simState.running = true; simState.lastTs = 0;
  dimCourse(true);
  simState.rafId = requestAnimationFrame(simStep);
}

function stopSim() {
  simState.running = false;
  cancelAnimationFrame(simState.rafId);
  simState.rafId = null;
  simState.lastTs = 0;
  dimCourse(false);
}

function setupSim() {
  initRacers();
  document.getElementById('sim-start').onclick = startSim;
  document.getElementById('sim-reset').onclick = () => { stopSim(); initRacers(); };
  document.getElementById('sim-racers').oninput = () => { stopSim(); initRacers(); };
  document.getElementById('sim-speed').oninput = (e) => { simState.speedFactor = parseFloat(e.target.value) || 1; };
}

Promise.all([fetch('/apps/apps.yml'), fetch('/apps/track3/courses/tabsai-ws8-track3.yml')])
  .then(rs => Promise.all(rs.map(r => r.text())))
  .then(([appsText, courseText]) => {
    const appData = jsyaml.load(appsText);
    courseData = jsyaml.load(courseText);
    loadOverrides();
    renderer = new CourseRenderer(map, { roundDist: ROUND_DIST });
    document.getElementById('app-nav').innerHTML = ChabaNav.renderNav(appData.nav);
    render(true);
    setupToggles();
    setupTabs();
    setupSim();
  })
  .catch(err => {
    console.error('failed to load course data', err);
    document.getElementById('summary').textContent = 'Error loading course';
  });
