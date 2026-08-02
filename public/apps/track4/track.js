const ROUND_DIST = 25;
const DEFAULT_COURSE = 'tabsai-ws8-track3';
let courseId = new URLSearchParams(window.location.search).get('course') || DEFAULT_COURSE;
let saveTimer = null;
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
const RACER_PROFILES = [
  { name: 'Rattanin', flag: '🇹🇭', code: 'THA' },
  { name: 'Kieran', flag: '🇦🇺', code: 'AUS' },
  { name: 'Pierre', flag: '🇫🇷', code: 'FRA' },
  { name: 'Tom', flag: '🇬🇧', code: 'GBR' },
  { name: 'Lilian', flag: '🇳🇱', code: 'NED' },
  { name: 'Maja', flag: '🇵🇱', code: 'POL' },
  { name: 'Blanca', flag: '🇪🇸', code: 'ESP' },
  { name: 'Tobias', flag: '🇩🇪', code: 'GER' },
  { name: 'Mattia', flag: '🇮🇹', code: 'ITA' },
  { name: 'Antoine', flag: '🇳🇿', code: 'NZL' },
  { name: 'Nikos', flag: '🇬🇷', code: 'GRE' },
  { name: 'Ricardo', flag: '🇧🇷', code: 'BRA' },
  { name: 'Li', flag: '🇨🇳', code: 'CHN' },
  { name: 'Yuki', flag: '🇯🇵', code: 'JPN' },
  { name: 'Caleb', flag: '🇺🇸', code: 'USA' },
  { name: 'Jonas', flag: '🇩🇰', code: 'DEN' },
  { name: 'Anton', flag: '🇸🇪', code: 'SWE' },
  { name: 'Erik', flag: '🇳🇴', code: 'NOR' },
  { name: 'Bram', flag: '🇧🇪', code: 'BEL' },
  { name: 'Cameron', flag: '🇨🇦', code: 'CAN' }
];
let simState = { running: false, rafId: null, elapsed: 0, racers: [], speedFactor: 1, lastTs: 0, path: null };
let highlightedRacer = null;

function getMergedMarkers() {
  return Object.entries(courseData.markers || {}).map(([id, m]) => ({ id, ...m, ...(state.overrides[id] || {}) }));
}
function storageKey() { return 'track-marker-overrides-' + courseId; }
function saveOverrides() {
  try { localStorage.setItem(storageKey(), JSON.stringify(state.overrides)); } catch (e) { console.warn('failed to save overrides', e); }
  saveToServer();
}
function loadOverrides() {
  try { state.overrides = JSON.parse(localStorage.getItem(storageKey()) || '{}'); } catch { state.overrides = {}; }
}

async function loadServerState() {
  try {
    const r = await fetch(`api/load.php?course=${courseId}`);
    if (!r.ok) throw new Error(`load ${r.status}`);
    const data = await r.json();
    if (data && typeof data === 'object') {
      if (data.overrides && typeof data.overrides === 'object') state.overrides = data.overrides;
      if (Array.isArray(data.hidden)) state.hidden = new Set(data.hidden);
    }
  } catch (e) { console.warn('server load failed, using local overrides', e); }
}

function saveToServer() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      const payload = { course: courseId, overrides: state.overrides, hidden: [...state.hidden] };
      await fetch('api/save.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (e) { console.warn('server save failed', e); }
  }, 500);
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
      saveToServer();
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
      saveToServer();
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
  for (const t of ['course', 'map', 'sections', 'sim', 'yaml']) {
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
  for (const t of ['course', 'map', 'sections', 'sim', 'yaml']) {
    const btn = document.getElementById(`tab-${t}`);
    if (!btn) continue;
    if (t === 'yaml') btn.onclick = () => { activateTab('yaml'); openYamlEditor(); };
    else btn.onclick = () => activateTab(t);
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

function boatIcon(color, heading, racer = null) {
  if (renderer && renderer.theme && typeof renderer.theme.boatIcon === 'function') {
    return renderer.theme.boatIcon(color, heading, racer);
  }
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
      ranges.push({ key, endDist, text: s.text || key });
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
    r.marker.setIcon(boatIcon(r.color, r.heading, r));
    r.speed = speed;
    if (r.hoverMarker) r.hoverMarker.setLatLng(next);
    return;
  }
  const { pts, cum, total } = simState.path;
  if (r.distance >= total) { r.distance = total; r.finished = true; r.returning = true; r.speed = 0; return; }
  const seg = findSegment(r.distance);
  const p1 = pts[seg], p2 = pts[seg + 1];
  const segLen = cum[seg + 1] - cum[seg];
  const t = segLen ? (r.distance - cum[seg]) / segLen : 0;
  const heading = Course.bearing(p1, p2);
  r.speed = r.baseSpeed * simWindFactor(heading) * (0.85 + Math.random() * 0.3) * startPenalty(r.distance) * simState.speedFactor;
  r.distance += r.speed * dt;
  if (r.distance >= total) { r.distance = total; r.finished = true; r.returning = true; r.speed = 0; return; }
  const newT = segLen ? Math.min(1, (r.distance - cum[seg]) / segLen) : 0;
  const rawLat = p1[0] + (p2[0] - p1[0]) * newT;
  const rawLon = p1[1] + (p2[1] - p1[1]) * newT;
  r.heading = r.heading ? (r.heading * 0.6 + heading * 0.4) : heading;
  let pos = [rawLat, rawLon];
  if (r.distance < simState.path.startDist) {
    pos = Course.pointAt(pos, simState.path.beachBearing, r.startOffset || 0);
  } else {
    const lane = r.lanes[seg] + (r.lanes[seg + 1] - r.lanes[seg]) * newT;
    if (Math.abs(lane) > 0.1) pos = Course.pointAt(pos, heading + (lane >= 0 ? 90 : -90), Math.abs(lane));
  }
  r.marker.setLatLng(pos);
  r.marker.setIcon(boatIcon(r.color, r.heading, r));
  if (r.hoverMarker) r.hoverMarker.setLatLng(pos);
}

function simStep(ts) {
  if (!simState.running) return;
  if (!simState.lastTs) simState.lastTs = ts;
  const dt = (ts - simState.lastTs) / 1000;
  simState.lastTs = ts;
  simState.elapsed += dt;
  const active = simState.racers.filter(r => !r.returned);
  if (!active.length) { stopSim(); updateSimStandings(); return; }
  for (const r of simState.racers) updateRacer(r, dt);
  resolveCollisions(simState.racers);
  updateSimStandings();
  simState.rafId = requestAnimationFrame(simStep);
}

function initRacers() {
  if (!renderer.guide || !renderer.guide.guidePts.length) return;
  highlightedRacer = null;
  simState.path = buildSimPath();
  const pts = simState.path.pts;
  const { beachBearing, lineLen } = simState.path;
  raceLayer.clearLayers();
  simState.racers = [];
  const count = Math.min(10, Math.max(2, parseInt(document.getElementById('sim-racers').value, 10) || 10));
  const maxSpread = Math.min((lineLen || 0) * 0.8, Math.min(80, count * 10));
  const spacing = count > 1 ? maxSpread / (count - 1) : 0;
  const shuffled = [...RACER_PROFILES].sort(() => Math.random() - 0.5);
  for (let i = 0; i < count; i++) {
    const color = boatColors[i % boatColors.length];
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
    const marker = L.marker(startPos, { icon: boatIcon(color, h, r), zIndexOffset: 1000 }).addTo(raceLayer);
    marker.on('mouseover', () => highlightRacer(r));
    marker.on('mouseout', clearRacerHighlight);
    r.marker = marker;
    simState.racers.push(r);
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

function currentSectionKey(r) {
  if (r.finished) return null;
  const ranges = (simState.path && simState.path.sectionRanges) || [];
  for (const range of ranges) {
    if (r.distance < range.endDist) return range.key || null;
  }
  return null;
}

function highlightRacer(r) {
  clearRacerHighlight();
  highlightedRacer = r;
  if (!r) return;
  r.marker.setZIndexOffset(10000);
  const pos = r.marker.getLatLng();
  r.hoverMarker = L.circleMarker([pos.lat, pos.lng], { radius: 14, color: r.color, weight: 3, fillColor: r.color, fillOpacity: 0.25, opacity: 0.9 }).addTo(raceLayer);
  const key = currentSectionKey(r);
  if (key && renderer) renderer.highlightSection(key);
}

function clearRacerHighlight() {
  if (!highlightedRacer) return;
  highlightedRacer.marker.setZIndexOffset(1000);
  if (highlightedRacer.hoverMarker) {
    raceLayer.removeLayer(highlightedRacer.hoverMarker);
    highlightedRacer.hoverMarker = null;
  }
  highlightedRacer = null;
  if (renderer) renderer.clearHighlight();
}

function updateSimStandings() {
  const el = document.getElementById('sim-standings');
  if (!simState.racers.length) { el.textContent = 'Press Start to simulate'; return; }
  const { total } = simState.path || { total: 1 };
  const sorted = [...simState.racers].sort((a, b) => b.distance - a.distance);
  if (renderer && renderer.theme && typeof renderer.theme.renderStandings === 'function') {
    renderer.theme.renderStandings({ sorted, total, elapsed: simState.elapsed, speedFactor: simState.speedFactor });
    return;
  }
  const pct = d => total ? (d / total * 100).toFixed(0) : 0;
  const rows = sorted.map((r, i) => `
    <tr class="align-middle whitespace-nowrap" data-name="${r.name}">
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
  if (!simState.racers.length || simState.racers.every(r => r.returned)) initRacers();
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
  
  // Wind configuration controls
  const windDirSlider = document.getElementById('wind-direction');
  const windSpeedSlider = document.getElementById('wind-speed');
  const windGustSlider = document.getElementById('wind-gust');
  const applyWindBtn = document.getElementById('apply-wind');
  
  // Update wind direction display
  function updateWindDirectionDisplay() {
    const dir = parseInt(windDirSlider.value);
    document.getElementById('wind-direction-value').textContent = dir + '°';
    
    // Convert to compass direction
    const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const index = Math.round(dir / 45) % 8;
    document.getElementById('wind-direction-label').textContent = directions[index];
  }
  
  // Update wind speed display
  function updateWindSpeedDisplay() {
    const speed = parseInt(windSpeedSlider.value);
    document.getElementById('wind-speed-value').textContent = speed;
  }
  
  // Update wind gust display
  function updateWindGustDisplay() {
    const gust = parseFloat(windGustSlider.value);
    document.getElementById('wind-gust-value').textContent = gust.toFixed(2);
  }
  
  // Apply wind configuration
  function applyWindConfig() {
    if (simulationEngine) {
      simulationEngine.setWind({
        direction: parseInt(windDirSlider.value),
        speed: parseInt(windSpeedSlider.value),
        gustFactor: parseFloat(windGustSlider.value),
        variability: 10 // Fixed for now
      });
      console.log('Wind configuration applied:', simulationEngine.getWind());
    }
  }
  
  // Set up wind control event listeners
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
  
  // Initialize wind displays from current simulation engine state
  if (simulationEngine) {
    const currentWind = simulationEngine.getWind();
    if (windDirSlider) windDirSlider.value = currentWind.direction;
    if (windSpeedSlider) windSpeedSlider.value = currentWind.speed;
    if (windGustSlider) windGustSlider.value = currentWind.gustFactor;
    updateWindDirectionDisplay();
    updateWindSpeedDisplay();
    updateWindGustDisplay();
  }
  
  // Leader focus toggle
  const focusToggle = document.getElementById('toggle-focus-leader');
  if (focusToggle) {
    focusToggle.onchange = (e) => {
      focusState.enabled = e.target.checked;
      if (!focusState.enabled) {
        focusState.manualSection = null;
      }
      updateFocusStatus();
      applyLeaderFocus();
    };
  }
  
  document.addEventListener('keydown', (e) => {
    if (e.key === 'l' || e.key === 'L') {
      if (focusToggle) {
        focusToggle.checked = !focusToggle.checked;
        focusState.enabled = focusToggle.checked;
        if (!focusState.enabled) {
          focusState.manualSection = null;
        }
        updateFocusStatus();
        applyLeaderFocus();
      }
    }
  });
  
  const standingsEl = document.getElementById('sim-standings');
  if (standingsEl) {
    standingsEl.onmouseover = (e) => {
      const tr = e.target.closest('[data-name]');
      if (!tr) return;
      const r = simState.racers.find(x => x.name === tr.dataset.name);
      if (r) highlightRacer(r);
    };
    standingsEl.onmouseout = (e) => {
      const tr = e.target.closest('[data-name]');
      if (!tr) return;
      clearRacerHighlight();
    };
  }
}

function showCourseMsg(text) {
  const el = document.getElementById('course-msg');
  if (el) {
    el.textContent = text;
    setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 3000);
  }
}

function updateUrlCourse() {
  const url = new URL(window.location.href);
  url.searchParams.set('course', courseId);
  window.history.replaceState({}, '', url);
}

async function populateCourseList() {
  try {
    const r = await fetch('api/list.php');
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('course-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">Load course...</option>';
    for (const c of list) {
      const label = c.name + (c.saved ? ' (saved)' : '');
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = label;
      sel.appendChild(opt);
    }
    sel.value = '';
  } catch (e) { console.warn('course list failed', e); }
}

async function loadCourseYaml(id) {
  const r = await fetch(`courses/${id}.yml`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`course not found: ${r.status}`);
  return jsyaml.load(await r.text());
}

async function loadCourse(id) {
  if (!id || !/^[a-zA-Z0-9_-]+$/.test(id)) { showCourseMsg('invalid course name'); return; }
  stopSim();
  try {
    courseData = await loadCourseYaml(id);
  } catch (e) {
    console.warn(`no YAML for ${id}; keeping current base`, e);
  }
  courseId = id;
  loadOverrides();
  await loadServerState();
  document.getElementById('course-name').value = courseId;
  updateUrlCourse();
  let ThemeClass = DefaultTheme;
  if (themeId !== 'default') {
    try { ThemeClass = await loadTheme(themeId); } catch (e) { console.warn('theme load failed', e); }
  }
  if (!renderer) renderer = new CourseRenderer(map, { roundDist: ROUND_DIST, theme: new ThemeClass() });
  renderer.hidden = state.hidden;
  render(true);
  initRacers();
  if (renderer.theme && renderer.theme.installChrome) renderer.theme.installChrome(courseData);
  populateCourseList();
  showCourseMsg('Loaded ' + courseId);
}

async function saveCourse(name) {
  name = (name || '').trim();
  if (!name) name = courseId;
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) { showCourseMsg('invalid course name'); return; }
  const payload = { course: name, overrides: state.overrides, hidden: [...state.hidden] };
  try {
    const r = await fetch('api/save.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok && data.ok) {
      courseId = name;
      try { localStorage.setItem(storageKey(), JSON.stringify(state.overrides)); } catch (e) {}
      document.getElementById('course-name').value = courseId;
      updateUrlCourse();
      populateCourseList();
      showCourseMsg('Saved ' + courseId);
    } else {
      showCourseMsg(data.error || 'save failed');
    }
  } catch (e) {
    console.warn('save failed', e);
    showCourseMsg('save error');
  }
}

function setupCourseControls() {
  const nameInput = document.getElementById('course-name');
  const sel = document.getElementById('course-select');
  if (nameInput) nameInput.value = courseId;
  populateCourseList();
  document.getElementById('btn-save').onclick = () => saveCourse(nameInput ? nameInput.value : '');
  document.getElementById('btn-load').onclick = () => { if (sel && sel.value) loadCourse(sel.value); };
}

function showYamlMsg(text) {
  const el = document.getElementById('yaml-msg');
  if (el) {
    el.textContent = text;
    setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 3000);
  }
}

async function openYamlEditor() {
  const textarea = document.getElementById('yaml-text');
  if (!textarea) return;
  try {
    const r = await fetch(`courses/${courseId}.yml`, { cache: 'no-store' });
    if (!r.ok) throw new Error(`load ${r.status}`);
    textarea.value = await r.text();
  } catch (e) {
    console.warn('yaml load failed', e);
    showYamlMsg('Failed to load YAML');
  }
}

async function saveYamlEditor() {
  const textarea = document.getElementById('yaml-text');
  if (!textarea) return;
  const yaml = textarea.value;
  try {
    try { jsyaml.load(yaml); } catch (e) { showYamlMsg('Invalid YAML: ' + e.message); return; }
    const r = await fetch('api/save-course.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ course: courseId, yaml })
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok && data.ok) {
      showYamlMsg('Saved; reloading...');
      await loadCourse(courseId);
      activateTab('course');
    } else {
      showYamlMsg(data.error || 'save failed');
    }
  } catch (e) {
    console.warn('yaml save failed', e);
    showYamlMsg('save error');
  }
}

function setupYamlEditor() {
  const cancel = document.getElementById('btn-cancel-yaml');
  const save = document.getElementById('btn-save-yaml');
  if (cancel) cancel.onclick = () => activateTab('course');
  if (save) save.onclick = saveYamlEditor;
}

const urlParams = new URLSearchParams(window.location.search);
const simOnly = urlParams.get('view') === 'sim';
const themeId = urlParams.get('theme') || 'default';

async function loadTheme(id) {
  if (id === 'default') return DefaultTheme;
  return new Promise((resolve) => {
    const s = document.createElement('script');
    s.src = `themes/${encodeURIComponent(id)}.js?v=${Date.now()}`;
    s.onload = () => resolve(window.TrackTheme || DefaultTheme);
    s.onerror = () => { console.warn(`Theme ${id} not found, falling back to default`); resolve(DefaultTheme); };
    document.head.appendChild(s);
  });
}

(async function init() {
  try {
    if (simOnly) {
      document.getElementById('app-nav').style.display = 'none';
      document.querySelector('.course-panel').style.display = 'none';
    }
    const appsText = await (await fetch('/apps/apps.yml')).text();
    const appData = jsyaml.load(appsText);
    document.getElementById('app-nav').innerHTML = ChabaNav.renderNav(appData.nav);

    let courseText = '';
    try {
      courseText = await (await fetch(`courses/${courseId}.yml`)).text();
    } catch (e) {
      console.warn(`course YAML ${courseId} not found, using ${DEFAULT_COURSE}`, e);
      courseText = await (await fetch(`courses/${DEFAULT_COURSE}.yml`)).text();
    }
    courseData = jsyaml.load(courseText);
    loadOverrides();
    await loadServerState();
    let ThemeClass = DefaultTheme;
    if (themeId !== 'default') {
      try { ThemeClass = await loadTheme(themeId); } catch (e) { console.warn('theme load failed', e); }
    }
    renderer = new CourseRenderer(map, { roundDist: ROUND_DIST, theme: new ThemeClass() });
    document.getElementById('course-name').value = courseId;
    render(true);
    setupToggles();
    setupTabs();
    setupSim();
    activateTab('sim');
    startSim();
    setupCourseControls();
    setupYamlEditor();
    if (renderer && renderer.theme && renderer.theme.installChrome) renderer.theme.installChrome(courseData);
  } catch (err) {
    console.error('failed to load course data', err);
    document.getElementById('summary').textContent = 'Error loading course';
  }
})();
