const CENTER = [13.252977873086172, 100.92760170433162];
const COLORS = ['#ef4444', '#0a84ff', '#22c55e', '#f97316', '#a855f7'];
const ROUTES = [
  [[13.7563, 100.5018], [13.7663, 100.5018], [13.7663, 100.5118], [13.7563, 100.5118], [13.7563, 100.5018]],
  [[13.7463, 100.4918], [13.7363, 100.4918], [13.7363, 100.5118], [13.7463, 100.5118], [13.7463, 100.4918]],
  [[13.7613, 100.4868], [13.7713, 100.4918], [13.7663, 100.5068], [13.7513, 100.4968], [13.7613, 100.4868]],
  [[13.7413, 100.5068], [13.7313, 100.5168], [13.7363, 100.5268], [13.7463, 100.5218], [13.7413, 100.5068]],
  [[13.7513, 100.4818], [13.7613, 100.4768], [13.7663, 100.4868], [13.7563, 100.4918], [13.7513, 100.4818]]
];

const map = L.map('map').setView(CENTER, 13);
const vehicleLayer = L.layerGroup().addTo(map);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: 'abcd',
  maxZoom: 19
}).addTo(map);

function toRad(deg) { return deg * Math.PI / 180; }
function toDeg(rad) { return rad * 180 / Math.PI; }
function haversine([lat1, lon1], [lat2, lon2]) {
  const R = 6371000;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2)**2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon/2)**2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
function bearing([lat1, lon1], [lat2, lon2]) {
  const p1 = toRad(lat1), p2 = toRad(lat2), dLon = toRad(lon2 - lon1);
  const x = Math.sin(dLon) * Math.cos(p2);
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dLon);
  return (toDeg(Math.atan2(x, y)) + 360) % 360;
}
function interpolate(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }

function buildSegments(route) {
  const segs = [];
  for (let i = 0; i < route.length - 1; i++) {
    const from = route[i], to = route[i+1];
    segs.push({ from, to, distance: haversine(from, to), heading: bearing(from, to) });
  }
  return segs;
}
const segments = ROUTES.map(buildSegments);

const vehicles = [];
let running = true;
let speedMultiplier = 1;
let lastTime = performance.now();

function createIcon(color, heading) {
  return L.divIcon({
    className: 'vehicle-icon',
    html: `<svg viewBox="0 0 24 24" fill="${color}" style="transform: rotate(${heading}deg)"><path d="M12 2l8 20H4z"/></svg>`,
    iconSize: [22, 22], iconAnchor: [11, 11]
  });
}

function spawn(routeIndex, offset = 0) {
  const route = segments[routeIndex];
  const color = COLORS[routeIndex % COLORS.length];
  const id = `V-${Math.floor(Math.random() * 9999)}`;
  const speed = 8 + Math.random() * 12; // m/s
  const marker = L.marker(route[0].from, { icon: createIcon(color, route[0].heading) }).addTo(vehicleLayer);
  marker.bindPopup(`<b>${id}</b><br>Route ${routeIndex + 1}<br>Speed: ${(speed * 3.6).toFixed(0)} km/h`);
  const trail = L.polyline([], { color, opacity: 0.5, weight: 2 }).addTo(vehicleLayer);
  vehicles.push({ id, routeIndex, segIndex: 0, distance: offset, speed, color, marker, trail, lastTrail: 0 });
  updateCount();
}

function updateCount() { document.getElementById('count').textContent = vehicles.length; }

function updateVehicle(v, dt) {
  const route = segments[v.routeIndex];
  let move = v.speed * dt * speedMultiplier;
  v.distance += move;
  while (v.segIndex < route.length && v.distance > route[v.segIndex].distance) {
    v.distance -= route[v.segIndex].distance;
    v.segIndex++;
    if (v.segIndex >= route.length) v.segIndex = 0;
  }
  const seg = route[v.segIndex];
  const len = seg.distance || 1;
  const t = Math.min(1, Math.max(0, v.distance / len));
  const pos = interpolate(seg.from, seg.to, t);
  v.marker.setLatLng(pos);
  const arrow = v.marker.getElement()?.querySelector('svg');
  if (arrow) arrow.style.transform = `rotate(${seg.heading}deg)`;
  v.marker.setPopupContent(`<b>${v.id}</b><br>Route ${v.routeIndex + 1}<br>Speed: ${(v.speed * 3.6).toFixed(0)} km/h`);

  const showTrails = document.getElementById('trails').checked;
  if (!showTrails) { v.trail.setLatLngs([]); return; }
  v.lastTrail += dt;
  if (v.lastTrail >= 0.25) {
    const pts = v.trail.getLatLngs();
    pts.push(pos);
    if (pts.length > 80) pts.shift();
    v.trail.setLatLngs(pts);
    v.lastTrail = 0;
  }
}

function loop(now) {
  if (running) {
    const dt = Math.min((now - lastTime) / 1000, 0.2);
    for (const v of vehicles) updateVehicle(v, dt);
  }
  lastTime = now;
  requestAnimationFrame(loop);
}

for (let i = 0; i < ROUTES.length; i++) {
  spawn(i, 0);
  spawn(i, segments[i][0].distance * 0.4);
}

const playBtn = document.getElementById('playPause');
playBtn.addEventListener('click', () => {
  running = !running;
  playBtn.textContent = running ? 'Pause' : 'Play';
  lastTime = performance.now();
});
document.getElementById('speed').addEventListener('input', (e) => {
  speedMultiplier = parseFloat(e.target.value);
  document.getElementById('speedLabel').textContent = speedMultiplier.toFixed(2) + 'x';
});
document.getElementById('reset').addEventListener('click', () => {
  for (const v of vehicles) {
    v.segIndex = 0; v.distance = 0;
    v.trail.setLatLngs([]);
  }
});
document.getElementById('addVehicle').addEventListener('click', () => {
  const i = Math.floor(Math.random() * ROUTES.length);
  spawn(i, Math.random() * segments[i][0].distance);
});

requestAnimationFrame(loop);

const bouiLayer = L.layerGroup().addTo(map);
const bouis = [];
function setBouiVisible(id, show) {
  const b = bouis.find(x => x.id === id);
  if (b) b.marker.setStyle({ opacity: show ? 1 : 0, fillOpacity: show ? 0.8 : 0 });
}
function renderObjectList() {
  const list = document.getElementById('objectList');
  if (!list) return;
  list.innerHTML = `
    <label class="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" id="toggle-vehicles" checked class="accent-accent">
      <span>Vehicles (${vehicles.length})</span>
    </label>
    ${bouis.map(b => `
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" id="toggle-${b.id}" checked class="accent-accent">
        <span style="color:${b.color}">${b.name}</span>
      </label>
    `).join('')}
  `;
  document.getElementById('toggle-vehicles').addEventListener('change', e => {
    if (e.target.checked) vehicleLayer.addTo(map); else map.removeLayer(vehicleLayer);
  });
  bouis.forEach(b => {
    document.getElementById(`toggle-${b.id}`).addEventListener('change', e => setBouiVisible(b.id, e.target.checked));
  });
}
function isActive(path, href) {
  if (href === '#' || !href) return false;
  if (href === '/') return path === '/';
  return path === href || path.startsWith(href);
}
function renderNav(items) {
  const path = window.location.pathname;
  const renderItem = (i) => {
    if (i.children && i.children.length) {
      const anyActive = isActive(path, i.href) || i.children.some(c => isActive(path, c.href));
      return `<div class="relative group h-full flex items-center">
        <a href="${i.href}" class="${anyActive ? 'text-accent font-semibold' : 'text-gray-400 hover:text-white transition'} cursor-pointer h-full flex items-center gap-1">${i.label} <span class="text-[10px]">▾</span></a>
        <div class="absolute left-0 top-full hidden group-hover:block bg-card border border-gray-700 rounded-lg shadow-lg min-w-[8rem] p-1 z-[1100]">
          ${i.children.map(c => `<a href="${c.href}" class="block px-3 py-2 text-sm ${isActive(path, c.href) ? 'text-accent font-semibold' : 'text-gray-300 hover:text-white transition'}">${c.label}</a>`).join('')}
        </div>
      </div>`;
    }
    const active = isActive(path, i.href);
    const cls = active ? 'text-accent font-semibold' : i.placeholder ? 'text-gray-500 hover:text-gray-400 transition cursor-not-allowed' : 'text-gray-400 hover:text-white transition';
    return `<a href="${i.href}" class="${cls}">${i.label}</a>`;
  };
  return `<nav class="bg-card border-b border-gray-700 sticky top-0 z-[1100] h-12">
    <div class="max-w-7xl mx-auto px-4 h-full flex items-center justify-between">
      <div class="flex items-center gap-6 h-full">
        <a href="/" class="text-lg font-bold text-white">HomeLab</a>
        <div class="hidden md:flex gap-4 text-sm h-full items-center">
          ${items.map(renderItem).join('')}
        </div>
      </div>
    </div>
  </nav>`;
}
Promise.all([fetch('../apps.yml'), fetch('objects.yml')])
  .then(([appsRes, objRes]) => Promise.all([appsRes.text(), objRes.text()]))
  .then(([appsText, objText]) => {
    const appData = jsyaml.load(appsText);
    const objData = jsyaml.load(objText);
    document.getElementById('app-nav').innerHTML = ChabaNav.renderNav(appData.nav);
    for (const b of objData.bouis || []) {
      const marker = L.circleMarker([b.lat, b.lon], {
        radius: 8, color: b.color, fillColor: b.color, fillOpacity: 0.8, weight: 2
      }).addTo(bouiLayer).bindPopup(`<b>${b.name}</b>`);
      bouis.push({ ...b, marker });
    }
    renderObjectList();
  })
  .catch(err => {
    console.error('failed to load yaml', err);
    document.getElementById('objectList').textContent = 'Object list unavailable';
  });
