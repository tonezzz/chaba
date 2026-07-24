const ROUND_DIST = 25;
const STORAGE_KEY = 'track3-marker-overrides';
let courseData = null;
let renderer = null;
let state = { overrides: {} };

const map = L.map('map');
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);

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
  if (!sections.length) {
    list.innerHTML = '<div class="text-gray-500 text-xs">No sections defined</div>';
    return;
  }
  list.innerHTML = '';
  sections.forEach((s, i) => {
    const row = document.createElement('div');
    row.className = 'mb-2';
    row.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="text-white">${i + 1}. ${s.text || s.key}</span>
        <button class="text-accent text-xs hover:underline" data-idx="${i}">Inspect</button>
      </div>
      <div class="text-gray-400 text-xs">${s.distance != null ? s.distance.toFixed(0) + ' m' : ''}</div>
    `;
    row.querySelector('button').onclick = () => {
      const pts = s.points.map(p => [p[0], p[1]]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.25));
    };
    list.appendChild(row);
  });
}

function setupTabs() {
  const mapBtn = document.getElementById('tab-map');
  const secBtn = document.getElementById('tab-sections');
  const mapContent = document.getElementById('tab-map-content');
  const secContent = document.getElementById('tab-sections-content');
  function activate(which) {
    if (which === 'map') {
      mapContent.classList.remove('hidden');
      secContent.classList.add('hidden');
      mapBtn.classList.add('bg-gray-700', 'text-white');
      mapBtn.classList.remove('bg-gray-800', 'text-gray-300');
      secBtn.classList.add('bg-gray-800', 'text-gray-300');
      secBtn.classList.remove('bg-gray-700', 'text-white');
    } else {
      mapContent.classList.add('hidden');
      secContent.classList.remove('hidden');
      secBtn.classList.add('bg-gray-700', 'text-white');
      secBtn.classList.remove('bg-gray-800', 'text-gray-300');
      mapBtn.classList.add('bg-gray-800', 'text-gray-300');
      mapBtn.classList.remove('bg-gray-700', 'text-white');
    }
  }
  mapBtn.onclick = () => activate('map');
  secBtn.onclick = () => activate('sections');
}

function onMarkerDrag(id, lat, lon) {
  state.overrides[id] = { lat, lon };
  saveOverrides();
  render(false);
}

function render(fit = false) {
  const markers = getMergedMarkers();
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
  })
  .catch(err => {
    console.error('failed to load course data', err);
    document.getElementById('summary').textContent = 'Error loading course';
  });
