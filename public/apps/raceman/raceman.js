const ROUND_DIST = 25;
const DEFAULT_COURSE = 'tabsai-ws8-track3';
let courseId = new URLSearchParams(window.location.search).get('course') || DEFAULT_COURSE;
let courseData = null;
let renderer = null;
let stateManager = new StateManager(courseId);

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
let leaderFocus = new LeaderFocus();
let windSystem = new WindSystem();
let simulation = null;
let courseManager = null;
let yamlEditor = null;

// State management functions (delegated to StateManager module)
function getMergedMarkers() {
  return stateManager.getMergedMarkers(courseData);
}

function saveOverrides() {
  stateManager.saveOverrides();
}

function loadOverrides() {
  stateManager.loadOverrides();
}

async function loadServerState() {
  await stateManager.loadServerState();
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
  const allChecked = sections.every(s => !stateManager.isHidden(s.key));
  if (header) {
    header.checked = allChecked;
    header.onchange = (e) => {
      for (const s of sections) {
        stateManager.toggleSection(s.key, !e.target.checked);
      }
      stateManager.saveOverrides();
      render(false);
    };
  }
  list.innerHTML = '';
  sections.forEach((s, i) => {
    const checked = !stateManager.isHidden(s.key) ? 'checked' : '';
    const row = document.createElement('div');
    row.className = 'mb-2 section-row';
    row.dataset.key = s.key;
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
      e.stopPropagation();
      stateManager.toggleSection(s.key, !e.target.checked);
      stateManager.saveOverrides();
      render(false);
    };
    row.querySelector('button').onclick = (e) => {
      e.stopPropagation();
      const pts = s.points.map(p => [p[0], p[1]]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.25));
    };
    row.onclick = () => {
      leaderFocus.setManualSection(s.key);
      const focusToggle = document.getElementById('toggle-focus-leader');
      if (focusToggle) focusToggle.checked = true;
      updateFocusStatus();
      applyLeaderFocus();
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

function onMarkerDrag(id, lat, lon, duringDrag = false) {
  stateManager.updateMarkerOverride(id, { lat, lon });
  
  // Only re-render on drag complete to avoid performance issues
  if (!duringDrag) {
    render(false);
    showDragNotification(id, lat, lon);
  }
}

function showDragNotification(id, lat, lon) {
  const msgEl = document.getElementById('course-msg');
  if (msgEl) {
    const marker = courseData.markers[id];
    const label = marker ? (marker.label || marker.id) : id;
    msgEl.textContent = `Moved ${label} to ${lat.toFixed(6)}, ${lon.toFixed(6)}`;
    msgEl.classList.add('text-green-400');
    setTimeout(() => {
      msgEl.classList.remove('text-green-400');
      msgEl.textContent = '';
    }, 3000);
  }
}

function render(fit = false) {
  const markers = getMergedMarkers();
  renderer.hidden = stateManager.getHidden();
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

// --- Race simulation (delegated to RaceSimulation module) ---

function currentSection(r) {
  return simulation ? simulation.currentSection(r) : 'Finished';
}

function currentSectionKey(r) {
  return simulation ? simulation.currentSectionKey(r) : null;
}

// Leader focus functions (delegated to LeaderFocus module)
function updateFocusStatus() {
  leaderFocus.updateStatus({
    sections: (renderer.lastDrawables || []).filter(d => d.kind === 'section'),
    racers: simulation ? simulation.getRacers() : [],
    currentSection: currentSection
  });
}

function applyLeaderFocus() {
  leaderFocus.applyFocus({
    sections: (renderer.lastDrawables || []).filter(d => d.kind === 'section'),
    racers: simulation ? simulation.getRacers() : [],
    currentSectionKey: currentSectionKey,
    renderer: renderer
  });
}

function startSim() {
  if (simulation) simulation.start();
}

function stopSim() {
  if (simulation) simulation.stop();
}

function setupSim() {
  if (!simulation) {
    simulation = new RaceSimulation({
      map: map,
      renderer: renderer,
      raceLayer: raceLayer,
      boatColors: boatColors,
      racerProfiles: RACER_PROFILES,
      windSystem: windSystem,
      leaderFocus: leaderFocus,
      getCourseData: () => courseData,
      getMergedMarkers: getMergedMarkers
    });
  }
  
  simulation.setupUI({
    onFocusToggle: (state) => {
      updateFocusStatus();
    },
    onFocusApply: () => {
      updateFocusStatus();
      applyLeaderFocus();
    }
  });
}

// --- Course management (delegated to CourseManager module) ---

function showCourseMsg(text) {
  const el = document.getElementById('course-msg');
  if (el) {
    el.textContent = text;
    setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 3000);
  }
}

function loadCourse(id) {
  if (courseManager) courseManager.loadCourse(id);
}

function saveCourse(name) {
  if (courseManager) courseManager.saveCourse(name);
}

function setupCourseControls() {
  if (!courseManager) {
    courseManager = new CourseManager({
      stateManager: stateManager,
      renderer: renderer,
      simulation: simulation,
      getCourseId: () => courseId,
      setCourseId: (id) => courseId = id,
      getCourseData: () => courseData,
      setCourseData: (data) => courseData = data,
      getRenderer: () => renderer,
      setRenderer: (r) => renderer = r,
      getSimulation: () => simulation,
      onRender: (fit) => render(fit),
      onLoadOverrides: () => loadOverrides(),
      onLoadServerState: () => loadServerState(),
      onThemeLoad: () => loadTheme(themeId),
      onShowMsg: (text) => showCourseMsg(text)
    });
  }
  courseManager.setupCourseControls();
}

// --- YAML editor (delegated to YamlEditor module) ---

function openYamlEditor() {
  if (yamlEditor) yamlEditor.openYamlEditor();
}

function setupYamlEditor() {
  if (!yamlEditor) {
    yamlEditor = new YamlEditor({
      getCourseId: () => courseId,
      onShowMsg: (text) => {
        const el = document.getElementById('yaml-msg');
        if (el) {
          el.textContent = text;
          setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 3000);
        }
      },
      onActivateTab: (tab) => activateTab(tab),
      onLoadCourse: (id) => courseManager ? courseManager.loadCourse(id) : null
    });
  }
  yamlEditor.setupYamlEditor();
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
    
    // Load wind configuration from course YAML
    windSystem.loadFromCourse(courseData);
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
    updateFocusStatus();
    applyLeaderFocus();
  } catch (err) {
    console.error('failed to load course data', err);
    document.getElementById('summary').textContent = 'Error loading course';
  }
})();
