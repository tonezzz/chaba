const ROUND_DIST = 25;
const DEFAULT_COURSE = 'tabsai-ws8';
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
let notificationManager = new NotificationManager();
let dragManager = new DragManager({
  onDrag: onMarkerDrag
});

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
        <div class="flex gap-2">
          <button class="text-accent text-xs hover:underline" data-idx="${i}">Inspect</button>
          <button class="text-green-400 text-xs hover:underline" data-key="${s.key}">Edit</button>
        </div>
      </div>
      <div class="text-gray-400 text-xs">${s.distance != null ? s.distance.toFixed(0) + ' m' : ''}</div>
    `;
    row.querySelector('input').onchange = (e) => {
      e.stopPropagation();
      stateManager.toggleSection(s.key, !e.target.checked);
      stateManager.saveOverrides();
      render(false);
    };
    row.querySelector('button[data-idx]').onclick = (e) => {
      e.stopPropagation();
      const pts = s.points.map(p => [p[0], p[1]]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.25));
    };
    row.querySelector('button[data-key]').onclick = (e) => {
      e.stopPropagation();
      editSection(s.key);
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
    const marker = courseData.markers[id];
    const label = marker ? (marker.label || marker.id) : id;
    notificationManager.showDragNotification(id, label, lat, lon);
  }
}

let selectedMarkerId = null;

function onMarkerClick(id) {
  selectedMarkerId = id;
  updateMarkersList();
  notificationManager.info(`Selected marker: ${id}`);
}

function addMarker() {
  saveCurrentState(); // Save state before modification
  
  const newId = 'marker_' + Date.now();
  const center = map.getCenter();
  
  const newMarker = {
    id: newId,
    lat: center.lat,
    lon: center.lng,
    label: 'New',
    icon: 'default',
    description: 'New marker'
  };
  
  courseData.markers[newId] = newMarker;
  stateManager.updateMarkerOverride(newId, { lat: center.lat, lon: center.lng });
  
  render(false);
  updateMarkersList();
  notificationManager.success(`Added marker: ${newId}`);
}

function deleteSelectedMarker() {
  if (!selectedMarkerId) {
    notificationManager.error('No marker selected');
    return;
  }
  
  saveCurrentState(); // Save state before modification
  
  delete courseData.markers[selectedMarkerId];
  stateManager.updateMarkerOverride(selectedMarkerId, null);
  
  selectedMarkerId = null;
  render(false);
  updateMarkersList();
  notificationManager.success(`Deleted marker: ${selectedMarkerId}`);
}

function updateMarkersList() {
  const markersList = document.getElementById('markers-list');
  if (!markersList) return;
  
  const markers = getMergedMarkers();
  markersList.innerHTML = '';
  
  if (markers.length === 0) {
    markersList.innerHTML = '<div class="text-gray-500 text-xs">No markers</div>';
    return;
  }
  
  markers.forEach(m => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between p-1 rounded cursor-pointer hover:bg-gray-700';
    if (m.id === selectedMarkerId) {
      row.classList.add('bg-accent', 'text-white');
    }
    row.innerHTML = `
      <span class="font-mono">${m.label || m.id}</span>
      <span class="text-gray-400 text-xs">${m.lat.toFixed(4)}, ${m.lon.toFixed(4)}</span>
    `;
    row.onclick = () => onMarkerClick(m.id);
    markersList.appendChild(row);
  });
}

let editingSectionKey = null;

function editSection(key) {
  editingSectionKey = key;
  const section = courseData.course.sections[key];
  if (!section) return;
  
  const editor = document.getElementById('section-editor');
  if (!editor) return;
  
  document.getElementById('edit-section-id').value = key;
  document.getElementById('edit-section-width').value = section.width || 8;
  document.getElementById('edit-section-color').value = section.color || '#eab308';
  document.getElementById('edit-section-rounding').value = section.rounding || 'starboard';
  
  editor.classList.remove('hidden');
  notificationManager.info(`Editing section: ${key}`);
}

function saveSection() {
  if (!editingSectionKey) return;
  
  saveCurrentState(); // Save state before modification
  
  const section = courseData.course.sections[editingSectionKey];
  if (!section) return;
  
  section.width = parseInt(document.getElementById('edit-section-width').value) || 8;
  section.color = document.getElementById('edit-section-color').value;
  section.rounding = document.getElementById('edit-section-rounding').value;
  
  const savedKey = editingSectionKey;
  editingSectionKey = null;
  document.getElementById('section-editor').classList.add('hidden');
  
  render(false);
  notificationManager.success(`Section saved: ${savedKey}`);
}

function cancelSectionEdit() {
  editingSectionKey = null;
  document.getElementById('section-editor').classList.add('hidden');
  notificationManager.info('Section edit cancelled');
}

function validateCourse() {
  const errors = [];
  const warnings = [];
  
  if (!courseData || !courseData.course) {
    errors.push('No course data loaded');
    return { errors, warnings, valid: false };
  }
  
  const course = courseData.course;
  const markers = courseData.markers || {};
  
  // Validate markers
  const markerIds = new Set();
  for (const [id, marker] of Object.entries(markers)) {
    if (markerIds.has(id)) {
      errors.push(`Duplicate marker ID: ${id}`);
    }
    markerIds.add(id);
    
    if (typeof marker.lat !== 'number' || isNaN(marker.lat)) {
      errors.push(`Invalid latitude for marker ${id}`);
    }
    if (typeof marker.lon !== 'number' || isNaN(marker.lon)) {
      errors.push(`Invalid longitude for marker ${id}`);
    }
    if (marker.lat < -90 || marker.lat > 90) {
      errors.push(`Latitude out of range for marker ${id}: ${marker.lat}`);
    }
    if (marker.lon < -180 || marker.lon > 180) {
      errors.push(`Longitude out of range for marker ${id}: ${marker.lon}`);
    }
    if (!marker.label && !marker.id) {
      warnings.push(`Marker ${id} has no label`);
    }
  }
  
  // Validate sections
  const sections = course.sections || {};
  for (const [key, section] of Object.entries(sections)) {
    if (section.type === 'arrow-area') {
      if (!section.from || !section.to) {
        errors.push(`Section ${key} missing from/to references`);
      } else {
        if (!markers[section.from] && !sections[section.from]) {
          errors.push(`Section ${key} references invalid marker: ${section.from}`);
        }
        if (!markers[section.to] && !sections[section.to]) {
          errors.push(`Section ${key} references invalid marker: ${section.to}`);
        }
      }
    } else if (section.type === 'round-bouy' || section.type === 'round-buoy') {
      const zoneKey = section.bouy || section.buoy || section.zone || section.mark;
      if (!zoneKey) {
        errors.push(`Section ${key} missing buoy reference`);
      } else if (!markers[zoneKey]) {
        errors.push(`Section ${key} references invalid marker: ${zoneKey}`);
      }
      if (section.width && (section.width < 1 || section.width > 100)) {
        warnings.push(`Section ${key} has unusual width: ${section.width}m`);
      }
    }
  }
  
  // Validate annotations
  const annotations = course.annotations || {};
  for (const [key, annotation] of Object.entries(annotations)) {
    if (annotation.type === 'line') {
      if (!annotation.from || !annotation.to) {
        errors.push(`Annotation ${key} missing from/to references`);
      } else if (!markers[annotation.from] || !markers[annotation.to]) {
        errors.push(`Annotation ${key} references invalid markers`);
      }
    } else if (annotation.type === 'zone') {
      if (!annotation.mark) {
        errors.push(`Annotation ${key} missing mark reference`);
      } else if (!markers[annotation.mark]) {
        errors.push(`Annotation ${key} references invalid marker: ${annotation.mark}`);
      }
    }
  }
  
  // Check for orphaned markers
  const referencedMarkers = new Set();
  for (const section of Object.values(sections)) {
    if (section.from) referencedMarkers.add(section.from);
    if (section.to) referencedMarkers.add(section.to);
    const zoneKey = section.bouy || section.buoy || section.zone || section.mark;
    if (zoneKey) referencedMarkers.add(zoneKey);
  }
  for (const annotation of Object.values(annotations)) {
    if (annotation.from) referencedMarkers.add(annotation.from);
    if (annotation.to) referencedMarkers.add(annotation.to);
    if (annotation.mark) referencedMarkers.add(annotation.mark);
  }
  
  for (const id of markerIds) {
    if (!referencedMarkers.has(id)) {
      warnings.push(`Marker ${id} is not referenced in any section or annotation`);
    }
  }
  
  const valid = errors.length === 0;
  return { errors, warnings, valid };
}

function showValidationResults() {
  const result = validateCourse();
  
  let message = '';
  if (result.valid) {
    message = `✅ Course is valid`;
    if (result.warnings.length > 0) {
      message += ` (${result.warnings.length} warning${result.warnings.length > 1 ? 's' : ''})`;
    }
    notificationManager.success(message);
  } else {
    message = `❌ Course has ${result.errors.length} error${result.errors.length > 1 ? 's' : ''}`;
    notificationManager.error(message);
  }
  
  // Show details in console
  console.log('Course Validation Results:', result);
  
  return result;
}

function saveCurrentState() {
  const state = {
    markers: JSON.parse(JSON.stringify(courseData.markers)),
    sections: JSON.parse(JSON.stringify(courseData.course.sections)),
    annotations: JSON.parse(JSON.stringify(courseData.course.annotations))
  };
  dragManager.saveState(state);
}

// Expose saveCurrentState globally for CourseManager
window.saveCurrentState = saveCurrentState;

function undo() {
  const previousState = dragManager.undo();
  if (previousState) {
    courseData.markers = previousState.markers;
    courseData.course.sections = previousState.sections;
    courseData.course.annotations = previousState.annotations;
    render(false);
    notificationManager.info('Undo successful');
  } else {
    notificationManager.error('Nothing to undo');
  }
}

function redo() {
  const nextState = dragManager.redo();
  if (nextState) {
    courseData.markers = nextState.markers;
    courseData.course.sections = nextState.sections;
    courseData.course.annotations = nextState.annotations;
    render(false);
    notificationManager.info('Redo successful');
  } else {
    notificationManager.error('Nothing to redo');
  }
}

function render(fit = false) {
  const markers = getMergedMarkers();
  renderer.hidden = stateManager.getHidden();
  const g = renderer.draw(courseData.course, markers, { onDrag: onMarkerDrag, onClick: onMarkerClick, fit });
  updatePanel(courseData.course, g);
  updateSections(renderer.lastDrawables);
  updateMarkersList();
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
    
    // Save initial state for undo/redo
    saveCurrentState();
    
    let ThemeClass = DefaultTheme;
    if (themeId !== 'default') {
      try { ThemeClass = await loadTheme(themeId); } catch (e) { console.warn('theme load failed', e); }
    }
    renderer = new CourseRenderer(map, { roundDist: ROUND_DIST, theme: new ThemeClass(), dragManager: dragManager });
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
