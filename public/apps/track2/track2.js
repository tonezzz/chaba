const CENTER = [13.24400, 100.92650];
const KTS_TO_MS = 0.514444;
const MS_TO_KMH = 3.6;
const ROUND_DIST = 25;

const map = L.map('map').setView(CENTER, 15);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);

function toRad(d) { return d * Math.PI / 180; }
function toDeg(r) { return r * 180 / Math.PI; }
function haversine([lat1, lon1], [lat2, lon2]) {
  const R = 6371000;
  const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
function bearing([lat1, lon1], [lat2, lon2]) {
  const p1 = toRad(lat1), p2 = toRad(lat2), dLon = toRad(lon2 - lon1);
  const x = Math.sin(dLon) * Math.cos(p2);
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dLon);
  return (toDeg(Math.atan2(x, y)) + 360) % 360;
}
function lerp(a, b, t) { return a + (b - a) * t; }
function interp([lat1, lon1], [lat2, lon2], t) { return [lerp(lat1, lat2, t), lerp(lon1, lon2, t)]; }
function linePos(line, t) { return interp([line[0].lat, line[0].lon], [line[1].lat, line[1].lon], t); }
function moveToward(from, to, distM) {
  const d = haversine(from, to);
  if (d < 0.1) return { pos: [...to], reached: true, remaining: distM };
  if (distM >= d) return { pos: [...to], reached: true, remaining: distM - d };
  const f = distM / d;
  return { pos: [lerp(from[0], to[0], f), lerp(from[1], to[1], f)], reached: false, remaining: 0 };
}
function windSpeedFactor(heading, windDir) {
  const rel = (heading - windDir + 360) % 360;
  return Math.min(1, Math.max(0.25, 0.5 + 0.5 * Math.sin(rel * Math.PI / 180)));
}

function sailIcon(color, heading) {
  return L.divIcon({
    className: 'racer-icon',
    html: `<svg viewBox="0 0 24 24" fill="${color}" style="transform: rotate(${heading}deg)"><path d="M12 2l6 18H6z"/><rect x="9" y="18" width="6" height="4" rx="1" fill="#1f2937"/></svg>`,
    iconSize: [28, 28], iconAnchor: [14, 14]
  });
}
function boatIcon(color) {
  return L.divIcon({
    className: 'boat-icon',
    html: `<svg viewBox="0 0 24 24" fill="${color}"><path d="M12 2l6 18H6z"/><rect x="9" y="18" width="6" height="4" rx="1" fill="#1f2937"/></svg>`,
    iconSize: [30, 30], iconAnchor: [15, 15]
  });
}
function startLabelIcon(angle) {
  return L.divIcon({
    className: 'start-label',
    html: `<span style="display:inline-block;transform:rotate(${angle.toFixed(1)}deg);transform-origin:center;">start</span>`,
    iconSize: [44, 16], iconAnchor: [22, 8]
  });
}
function finishLabelIcon(angle) {
  return L.divIcon({
    className: 'finish-label',
    html: `<span style="display:inline-block;transform:rotate(${angle.toFixed(1)}deg);transform-origin:center;">finish</span>`,
    iconSize: [44, 16], iconAnchor: [22, 8]
  });
}

let course = null, guide = null, racers = [], wind = { direction: 90, speed: 12 };
let status = 'ready';
let raceStartTime = 0, elapsedTime = 0;
let speedMultiplier = 1;
let lastTime = performance.now();
let lastLeaderboard = 0;
let courseTrackPoly = null;
let startLinePoly = null;
let startLabelMarker = null;
let finishLinePoly = null;
let finishLabelMarker = null;

function rebuildGuide() {
  const markers = {};
  for (const b of course.buoys) markers[b.id] = b;
  const guideCourse = {
    annotations: {
      start_line: { type: 'line', role: 'start', from: course.start_line[0], to: course.start_line[1] },
      finish_line: { type: 'line', role: 'finish', from: course.finish_line[0], to: course.finish_line[1] }
    },
    legs: course.legs.map(l => ({
      mark: l.target,
      rounding: l.rounding || (l.type === 'upwind' ? 'port' : l.type === 'downwind' ? 'starboard' : 'port'),
      label: `${l.type} to ${l.target}`
    })).filter(l => l.mark !== 'finish')
  };
  guide = Course.buildRoundedGuide(Object.values(markers), guideCourse, ROUND_DIST);
}
function startMid() { return linePos(course.start_line, 0.5); }
function finishMid() { return linePos(course.finish_line, 0.5); }

function resetRacers() {
  for (let i = 0; i < racers.length; i++) {
    const t = (i + 0.5) / Math.max(1, racers.length);
    const r = racers[i];
    r.pos = linePos(course.start_line, t);
    r.leg = 0;
    r.waypoint = 1;
    r.heading = bearing(r.pos, guide.guidePts[r.waypoint]);
    r.finished = false;
    r.finishTime = null;
    r.speedKmh = 0;
    r.trail.setLatLngs([]);
    r.marker.setLatLng(r.pos);
    r.marker.setIcon(sailIcon(r.color, r.heading));
    r.marker.setPopupContent(r.name);
  }
  status = 'ready';
  raceStartTime = 0;
  elapsedTime = 0;
  updateUI();
}

function updateRace(dt) {
  if (status !== 'running') return;
  elapsedTime += dt;
  const showTrails = document.getElementById('trails').checked;
  for (const r of racers) {
    if (r.finished) continue;
    let remaining = dt * speedMultiplier;
    while (remaining > 1e-4 && !r.finished) {
      const target = guide.guidePts[r.waypoint];
      if (!target) { r.finished = true; r.finishTime = elapsedTime; continue; }
      r.heading = bearing(r.pos, target);
      const factor = windSpeedFactor(r.heading, wind.direction);
      const gust = 0.95 + Math.random() * 0.1;
      const speedMs = r.baseSpeedKts * KTS_TO_MS * factor * gust * r.handling;
      const step = moveToward(r.pos, target, Math.max(0, speedMs * remaining));
      r.pos = step.pos;
      r.speedKmh = speedMs * MS_TO_KMH;
      remaining = step.remaining;
      if (showTrails) {
        const pts = r.trail.getLatLngs();
        pts.push([...r.pos]);
        if (pts.length > 120) pts.shift();
        r.trail.setLatLngs(pts);
      }
      if (step.reached) {
        r.waypoint++;
        if (r.leg < guide.legInfo.length && r.waypoint > guide.legInfo[r.leg].endIdx) r.leg++;
        if (r.waypoint >= guide.guidePts.length) {
          r.finished = true;
          r.finishTime = elapsedTime;
        }
      }
    }
    r.marker.setLatLng(r.pos);
    r.marker.setIcon(sailIcon(r.color, r.heading));
    r.marker.setPopupContent(`${r.name}<br>${r.speedKmh.toFixed(1)} km/h<br>Leg ${Math.min(r.leg + 1, guide.legInfo.length)}/${guide.legInfo.length}`);
  }
  if (racers.every(r => r.finished)) {
    status = 'finished';
  }
}

function formatTime(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`;
}

function updateLeaderboard() {
  const board = racers.map(r => {
    if (r.finished) return { r, sort: -1, rankKey: r.finishTime };
    const target = guide.guidePts[r.waypoint] || guide.finishMid;
    const d = haversine(r.pos, target);
    return { r, sort: r.leg * 1000000 - d, rankKey: null };
  });
  board.sort((a, b) => {
    if (a.sort === -1 && b.sort === -1) return a.rankKey - b.rankKey;
    if (a.sort === -1) return -1;
    if (b.sort === -1) return 1;
    return b.sort - a.sort;
  });
  const html = board.map((b, i) => {
    const r = b.r;
    const state = r.finished ? formatTime(r.finishTime) : `Leg ${r.leg + 1} / ${r.speedKmh.toFixed(1)} km/h`;
    return `<div class="flex items-center gap-2 p-1 rounded hover:bg-slate-800">
      <span class="font-mono w-4 text-right">${i + 1}</span>
      <span class="w-3 h-3 rounded-full" style="background:${r.color}"></span>
      <span class="flex-1 truncate">${r.name}</span>
      <span class="text-gray-400">${state}</span>
    </div>`;
  }).join('');
  document.getElementById('leaderboard').innerHTML = html;
}

function updateUI() {
  const badge = document.getElementById('race-status');
  badge.textContent = status[0].toUpperCase() + status.slice(1);
  badge.className = status === 'running' ? 'bg-green-600 px-2 py-0.5 rounded text-xs' : status === 'finished' ? 'bg-accent px-2 py-0.5 rounded text-xs' : 'bg-gray-700 px-2 py-0.5 rounded text-xs';
  document.getElementById('timer').textContent = formatTime(elapsedTime);
  document.getElementById('wind-readout').textContent = `${wind.direction}° @ ${wind.speed} kts`;
  document.getElementById('btn-start').textContent = status === 'finished' ? 'Restart' : (status === 'running' ? 'Running' : 'Start');
  document.getElementById('btn-start').disabled = status === 'running';
  document.getElementById('btn-pause').disabled = status !== 'running' && status !== 'paused';
  document.getElementById('btn-pause').textContent = status === 'paused' ? 'Resume' : 'Pause';
}

function loop(now) {
  const dt = Math.min((now - lastTime) / 1000, 0.5);
  lastTime = now;
  updateRace(dt);
  updateUI();
  if (now - lastLeaderboard > 250) { updateLeaderboard(); lastLeaderboard = now; }
  requestAnimationFrame(loop);
}

function renderCourseGuide() {
  const el = document.getElementById('course-guide');
  if (!el) return;
  const rows = guide.legInfo.map((l, i) =>
    `<div class="flex justify-between text-xs"><span>${i + 1}. ${l.label}</span><span class="text-gray-400">${l.distance.toFixed(0)} m</span></div>`
  ).join('');
  el.innerHTML = `
    <p class="text-gray-400 text-xs mb-2">${course.description || ''}</p>
    <div class="flex justify-between text-xs font-medium mb-2"><span>Total</span><span class="text-white">${guide.total.toFixed(0)} m</span></div>
    <div class="space-y-1">${rows}</div>
  `;
}

function updateCourse() {
  rebuildGuide();
  if (courseTrackPoly) courseTrackPoly.setLatLngs(guide.guidePts);
  renderCourseGuide();
}
function updateStartLine() {
  if (!startLinePoly || !startLabelMarker) return;
  const s1 = [course.start_line[0].lat, course.start_line[0].lon];
  const s2 = [course.start_line[1].lat, course.start_line[1].lon];
  startLinePoly.setLatLngs([s1, s2]);
  startLabelMarker.setLatLng(startMid());
  let a = 90 - bearing(s1, s2);
  while (a < -90) a += 180;
  while (a > 90) a -= 180;
  startLabelMarker.setIcon(startLabelIcon(a));
}
function updateFinishLine() {
  if (!finishLinePoly || !finishLabelMarker) return;
  const f1 = [course.finish_line[0].lat, course.finish_line[0].lon];
  const f2 = [course.finish_line[1].lat, course.finish_line[1].lon];
  finishLinePoly.setLatLngs([f1, f2]);
  finishLabelMarker.setLatLng(finishMid());
  let a = 90 - bearing(f1, f2);
  while (a < -90) a += 180;
  while (a > 90) a -= 180;
  finishLabelMarker.setIcon(finishLabelIcon(a));
}
function saveState() {
  const state = {
    start_line: course.start_line.map(p => [p.lat, p.lon]),
    finish_line: course.finish_line.map(p => [p.lat, p.lon]),
    buoys: {},
    map: { center: [map.getCenter().lat, map.getCenter().lng], zoom: map.getZoom() }
  };
  for (const b of course.buoys) state.buoys[b.id] = [b.lat, b.lon];
  localStorage.setItem('track2-state', JSON.stringify(state));
}
function restoreState() {
  const raw = localStorage.getItem('track2-state');
  if (!raw) return;
  try {
    const state = JSON.parse(raw);
    if (state.start_line) state.start_line.forEach(([lat, lon], i) => {
      if (course.start_line[i]) { course.start_line[i].lat = lat; course.start_line[i].lon = lon; }
    });
    if (state.finish_line) state.finish_line.forEach(([lat, lon], i) => {
      if (course.finish_line[i]) { course.finish_line[i].lat = lat; course.finish_line[i].lon = lon; }
    });
    if (state.buoys) {
      for (const id in state.buoys) {
        const b = course.buoys.find(b => b.id === id);
        if (b) { [b.lat, b.lon] = state.buoys[id]; }
      }
    }
    if (state.map) map.setView(state.map.center, state.map.zoom);
  } catch (e) { console.warn('failed to restore track2 state', e); }
}

function renderCourse() {
  const fl = course.finish_line.map(p => [p.lat, p.lon]);
  finishLinePoly = L.polyline(fl, { color: '#ef4444', weight: 4, dashArray: '8,6' }).addTo(map).bindPopup('Finish line');

  for (const [idx, b] of course.finish_line.entries()) {
    const label = idx === 0 ? 'F1' : 'F2';
    const marker = L.marker([b.lat, b.lon], {
      icon: L.divIcon({ className: 'boui-icon', html: `<span style="background:#ef4444">${label}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
      draggable: true
    }).addTo(map).bindPopup(`<b>${b.name}</b> (${label}) — drag to move finish line`);
    marker.dragging.enable();
    marker.on('dragend', (e) => {
      const ll = e.target.getLatLng();
      course.finish_line[idx].lat = ll.lat;
      course.finish_line[idx].lon = ll.lng;
      updateFinishLine();
      updateCourse();
      saveState();
      if (status !== 'ready') { status = 'ready'; resetRacers(); updateUI(); }
    });
  }
  finishLabelMarker = L.marker(finishMid(), { icon: finishLabelIcon(0) }).addTo(map);
  updateFinishLine();

  startLinePoly = L.polyline([[course.start_line[0].lat, course.start_line[0].lon], [course.start_line[1].lat, course.start_line[1].lon]], { color: '#22c55e', weight: 3, dashArray: '8,6' }).addTo(map);

  for (const [idx, b] of course.start_line.entries()) {
    const label = idx === 0 ? 'S1' : 'S2';
    const marker = L.marker([b.lat, b.lon], {
      icon: L.divIcon({ className: 'boui-icon', html: `<span style="background:#22c55e">${label}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
      draggable: true
    }).addTo(map).bindPopup(`<b>${b.name}</b> (${label}) — drag to move start line`);
    marker.dragging.enable();
    marker.on('dragend', (e) => {
      const ll = e.target.getLatLng();
      course.start_line[idx].lat = ll.lat;
      course.start_line[idx].lon = ll.lng;
      updateStartLine();
      updateCourse();
      saveState();
      if (status !== 'ready') { status = 'ready'; resetRacers(); updateUI(); }
    });
  }
  startLabelMarker = L.marker(startMid(), { icon: startLabelIcon(0) }).addTo(map);
  updateStartLine();

  for (const b of course.buoys) {
    const isBoat = ['w1', 'l1'].includes(b.id);
    const icon = isBoat ? boatIcon(b.color) : L.divIcon({ className: 'boui-icon', html: `<span style="background:${b.color}">${b.label || 'B'}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] });
    const marker = L.marker([b.lat, b.lon], { icon, draggable: true }).addTo(map).bindPopup(`<b>${b.name}</b> (${b.id}) — drag to set course`);
    marker.dragging.enable();
    marker.on('dragend', (e) => {
      const ll = e.target.getLatLng();
      b.lat = ll.lat;
      b.lon = ll.lng;
      updateCourse();
      saveState();
      if (status !== 'ready') { status = 'ready'; resetRacers(); updateUI(); }
    });
  }

  courseTrackPoly = L.polyline(guide.guidePts, { color: '#64748b', weight: 2, dashArray: '4,6', opacity: 0.6 }).addTo(map);
}

function downloadCourse() {
  const data = {
    start_line: course.start_line,
    finish_line: course.finish_line,
    wind: course.wind,
    buoys: course.buoys,
    course: { description: course.description, legs: course.legs }
  };
  const yml = jsyaml.dump(data);
  const blob = new Blob([yml], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'course.yml';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function initRacers(raw) {
  racers = raw.map(rr => {
    const marker = L.marker([0, 0], { icon: sailIcon(rr.color, 0) }).addTo(map);
    marker.bindPopup(rr.name);
    const trail = L.polyline([], { color: rr.color, opacity: 0.45, weight: 2 }).addTo(map);
    return { ...rr, baseSpeedKts: rr.base_speed_kts, pos: [0, 0], leg: 0, heading: 0, finished: false, finishTime: null, speedKmh: 0, marker, trail };
  });
}

function renderNav(items) {
  const path = window.location.pathname;
  const isActive = (href) => href && href !== '#' && (path === href || path.startsWith(href));
  const renderItem = (i) => {
    if (i.children && i.children.length) {
      const anyActive = isActive(i.href) || i.children.some(c => isActive(c.href));
      return `<div class="relative group h-full flex items-center">
        <a href="${i.href}" class="${anyActive ? 'text-accent font-semibold' : 'text-gray-400 hover:text-white transition'} cursor-pointer h-full flex items-center gap-1">${i.label} <span class="text-[10px]">▾</span></a>
        <div class="absolute left-0 top-full hidden group-hover:block bg-card border border-gray-700 rounded-lg shadow-lg min-w-[8rem] p-1 z-[1100]">
          ${i.children.map(c => `<a href="${c.href}" class="block px-3 py-2 text-sm ${isActive(c.href) ? 'text-accent font-semibold' : 'text-gray-300 hover:text-white transition'}">${c.label}</a>`).join('')}
        </div>
      </div>`;
    }
    return `<a href="${i.href}" class="${isActive(i.href) ? 'text-accent font-semibold' : i.placeholder ? 'text-gray-500 cursor-not-allowed' : 'text-gray-400 hover:text-white transition'}">${i.label}</a>`;
  };
  return `<nav class="bg-card border-b border-gray-700 sticky top-0 z-[1100] h-12">
    <div class="max-w-7xl mx-auto px-4 h-full flex items-center justify-between">
      <a href="/" class="text-lg font-bold text-white">HomeLab</a>
      <div class="hidden md:flex gap-4 text-sm h-full items-center">
        ${items.map(renderItem).join('')}
      </div>
    </div>
  </nav>`;
}

document.getElementById('btn-start').addEventListener('click', () => {
  if (status === 'finished' || status === 'running') return;
  if (status === 'ready') { raceStartTime = performance.now(); elapsedTime = 0; }
  status = 'running';
  lastTime = performance.now();
  updateUI();
});
document.getElementById('btn-pause').addEventListener('click', () => {
  status = status === 'running' ? 'paused' : (status === 'paused' ? 'running' : status);
  lastTime = performance.now();
  updateUI();
});
document.getElementById('btn-reset').addEventListener('click', resetRacers);
document.getElementById('btn-download').addEventListener('click', downloadCourse);
document.getElementById('speed').addEventListener('input', (e) => {
  speedMultiplier = parseFloat(e.target.value);
  document.getElementById('speed-label').textContent = speedMultiplier.toFixed(1) + 'x';
});
document.getElementById('wind-dir').addEventListener('input', (e) => { wind.direction = (parseInt(e.target.value, 10) || 0) % 360; updateUI(); });
document.getElementById('wind-kts').addEventListener('input', (e) => { wind.speed = parseFloat(e.target.value) || 0; updateUI(); });

Promise.all([fetch('/apps/apps.yml'), fetch('/apps/track2/course.yml'), fetch('/apps/track2/racers.yml')])
  .then(rs => Promise.all(rs.map(r => r.text())))
  .then(([appsText, courseText, racerText]) => {
    const appData = jsyaml.load(appsText);
    course = jsyaml.load(courseText);
    course.legs = course.course.legs;
    course.description = course.course.description;
    const racerData = jsyaml.load(racerText);
    document.getElementById('app-nav').innerHTML = ChabaNav.renderNav(appData.nav);
    wind.direction = course.wind.direction;
    wind.speed = course.wind.speed_kts;
    document.getElementById('wind-dir').value = wind.direction;
    document.getElementById('wind-kts').value = wind.speed;
    restoreState();
    rebuildGuide();
    map.on('moveend', saveState);
    renderCourseGuide();
    renderCourse();
    initRacers(racerData.racers);
    resetRacers();
    requestAnimationFrame(loop);
  })
  .catch(err => {
    console.error('failed to load race data', err);
    document.getElementById('leaderboard').textContent = 'Race data unavailable';
  });
