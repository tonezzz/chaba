let activeHls = null;
let cameras = [];
let groups = {};
let map = null;
let markers = [];
let filtered = [];
let currentIndex = 0;
let autoTimer = null;
let selectedCam = null;
let currentView = 'map';

function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function escapeJs(str) {
    return String(str || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r');
}

function safeId(str) {
    return String(str || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function stopAllPlayers() {
    if (activeHls) { activeHls.destroy(); activeHls = null; }
}

function startHls(videoEl, url) {
    if (activeHls) { activeHls.destroy(); activeHls = null; }
    const loading = videoEl.parentElement.querySelector('.loading');
    if (Hls.isSupported()) {
        activeHls = new Hls({ liveDurationInfinity: true, liveBackBufferLength: 0 });
        activeHls.loadSource(url);
        activeHls.attachMedia(videoEl);
        activeHls.on(Hls.Events.MANIFEST_PARSED, () => {
            if (loading) loading.style.display = 'none';
            videoEl.play().catch(() => {});
        });
        activeHls.on(Hls.Events.ERROR, (_, data) => {
            if (data.fatal && loading) loading.textContent = 'Stream unavailable';
        });
    } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
        videoEl.src = url;
        videoEl.play().catch(() => {});
        if (loading) loading.style.display = 'none';
    } else if (loading) {
        loading.textContent = 'HLS not supported';
    }
}

function pickPlayUrl(cam) {
    const candidates = [cam.hls_url, ...(cam.alt_urls || [])].filter(Boolean);
    return candidates.find(u => u.startsWith('https://')) || cam.hls_url || null;
}

function renderLegend(list) {
    const legend = document.getElementById('legend');
    if (!list) { legend.textContent = 'Loading cameras...'; return; }
    const counts = {};
    list.forEach(c => { counts[c.group] = (counts[c.group] || 0) + 1; });
    const items = Object.entries(groups).sort((a, b) => (a[1].order || 0) - (b[1].order || 0));
    legend.innerHTML = items.map(([name, info]) => {
        const color = /^#[0-9a-fA-F]{6}$/.test(info.color) ? info.color : '#0a84ff';
        const count = counts[name] || 0;
        return `<div><span class="dot" style="background:${color}"></span>${escapeHtml(name)} ${count ? '(' + count + ')' : ''}</div>`;
    }).join('');
}

function createMarker(map, cam, rawColor) {
    const color = /^#[0-9a-fA-F]{6}$/.test(rawColor) ? rawColor : '#0a84ff';
    const safeName = safeId(cam.name);
    const headingVal = Number(cam.heading);
    const hasHeading = !isNaN(headingVal) && cam.heading !== null && cam.heading !== undefined;
    let iconHtml, iconSize, iconAnchor;
    if (hasHeading) {
        iconHtml = `<div style="width:0;height:0;border-left:8px solid transparent;border-right:8px solid transparent;border-bottom:20px solid ${color};filter:drop-shadow(0 0 3px rgba(0,0,0,0.6));transform:rotate(${headingVal}deg);transform-origin:50% 60%;"></div>`;
        iconSize = [20, 24];
        iconAnchor = [10, 14];
    } else {
        iconHtml = `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,0.5);"></div>`;
        iconSize = [20, 20];
        iconAnchor = [10, 10];
    }

    const icon = L.divIcon({ className: 'custom-marker', html: iconHtml, iconSize, iconAnchor });

    const noStreamHtml = `<div class="video-container"><div class="loading">No live stream on chaba.h3</div></div>`;
    const videoHtml = cam.play_url
        ? `<div class="video-container"><video id="vid_${safeName}" muted autoplay playsinline></video><div class="loading" id="load_${safeName}">Loading stream...</div></div>`
        : noStreamHtml;

    const coverage = cam.view && cam.view.coverage ? cam.view.coverage.map(x => `<span class="coverage-tag">${escapeHtml(x)}</span>`).join(' ') : '';
    const location = cam.location ? `<div class="meta">${[cam.location.road, cam.location.km != null ? 'km ' + cam.location.km : '', cam.location.side, cam.location.area].filter(Boolean).map(escapeHtml).join(' · ')}</div>` : '';
    const perspective = cam.perspective ? `<div class="meta">Perspective: ${escapeHtml(cam.perspective)}</div>` : '';
    const viewDesc = cam.view && cam.view.heading_description ? `<div class="meta">Facing: ${escapeHtml(cam.view.heading_description)}</div>` : '';
    const desc = cam.description ? `<div class="meta">${escapeHtml(cam.description)}</div>` : '';
    const status = cam.stream_status || cam.stream_type || '';

    const popupHtml = `
        <div class="camera-popup">
            <h3>${escapeHtml(cam.title)}</h3>
            ${videoHtml}
            <div class="meta"><b>${escapeHtml(cam.group)}</b> · ${escapeHtml(cam.source)}${status ? ' · ' + escapeHtml(status) : ''}</div>
            ${location}${perspective}${viewDesc}${coverage ? '<div class="meta">Coverage: ' + coverage + '</div>' : ''}${desc}
        </div>
    `;

    const marker = L.marker([cam.lat, cam.lon], { icon }).bindPopup(popupHtml).addTo(map);
    marker.cam = cam;

    marker.on('popupopen', () => {
        stopAllPlayers();
        if (cam.play_url) {
            const videoEl = document.getElementById(`vid_${safeName}`);
            if (videoEl) startHls(videoEl, cam.play_url);
        }
    });
    return marker;
}

function renderList() {
    const tbody = document.getElementById('listBody');
    if (currentView !== 'list') return;
    tbody.innerHTML = filtered.map((cam, i) => `
        <tr data-idx="${i}">
            <td>${escapeHtml(cam.name)}</td>
            <td>${escapeHtml(cam.title || '')}</td>
            <td>${escapeHtml(cam.group || '')}</td>
            <td>${escapeHtml(cam.source || '')}</td>
            <td>${escapeHtml(cam.stream_type || '')}</td>
            <td>${cam.enabled !== false ? 'Yes' : 'No'}</td>
            <td>${cam.lat}</td>
            <td>${cam.lon}</td>
            <td>${cam.heading != null ? cam.heading : ''}</td>
            <td><button class="control-btn" data-idx="${i}">View</button></td>
        </tr>
    `).join('');
}

function switchView(view) {
    currentView = view;
    document.getElementById('tabMap').classList.toggle('active', view === 'map');
    document.getElementById('tabList').classList.toggle('active', view === 'list');
    document.getElementById('map').classList.toggle('hidden', view !== 'map');
    document.getElementById('listView').classList.toggle('hidden', view !== 'list');
    document.querySelectorAll('.map-only').forEach(el => el.classList.toggle('hidden', view !== 'map'));
    if (view === 'list') { map.closePopup(); stopAllPlayers(); renderList(); }
    else { stopAllPlayers(); }
}

function openDetail(cam) {
    stopAllPlayers();
    selectedCam = cam;
    const safeName = safeId(cam.name);
    const container = document.getElementById('detailVideoContainer');
    container.innerHTML = cam.play_url
        ? `<div class="video-container"><video id="vid_detail_${safeName}" muted autoplay playsinline controls></video><div class="loading" id="load_detail_${safeName}">Loading stream...</div></div>`
        : `<div class="video-container"><div class="loading">No live stream on chaba.h3</div></div>`;
    if (cam.play_url) {
        const videoEl = document.getElementById(`vid_detail_${safeName}`);
        if (videoEl) startHls(videoEl, cam.play_url);
    }
    document.getElementById('detailTitle').textContent = cam.title || cam.name;
    const coverage = cam.view && cam.view.coverage ? cam.view.coverage.map(x => `<span class="coverage-tag">${escapeHtml(x)}</span>`).join(' ') : '';
    const location = cam.location ? `<div class="meta">${[cam.location.road, cam.location.km != null ? 'km ' + cam.location.km : '', cam.location.side, cam.location.area].filter(Boolean).map(escapeHtml).join(' · ')}</div>` : '';
    document.getElementById('detailMeta').innerHTML = `
        <div class="meta"><b>${escapeHtml(cam.group || '')}</b> · ${escapeHtml(cam.source || '')} · ${escapeHtml(cam.stream_type || '')}</div>
        ${location}
        <div class="meta">Lat: ${cam.lat}, Lon: ${cam.lon}${cam.heading != null ? ', Heading: ' + cam.heading : ''}</div>
        ${cam.perspective ? '<div class="meta">Perspective: ' + escapeHtml(cam.perspective) + '</div>' : ''}
        ${cam.view && cam.view.heading_description ? '<div class="meta">Facing: ' + escapeHtml(cam.view.heading_description) + '</div>' : ''}
        ${coverage ? '<div class="meta">Coverage: ' + coverage + '</div>' : ''}
        ${cam.description ? '<div class="meta">' + escapeHtml(cam.description) + '</div>' : ''}
    `;
    document.getElementById('detailDrawer').classList.remove('hidden');
}

function closeDetail() {
    stopAllPlayers();
    selectedCam = null;
    document.getElementById('detailDrawer').classList.add('hidden');
    document.getElementById('detailVideoContainer').innerHTML = '';
}

function populateFilters() {
    const groupSelect = document.getElementById('groupFilter');
    const sourceSelect = document.getElementById('sourceFilter');
    const groupSet = new Set();
    const sourceSet = new Set();
    cameras.forEach(c => { if (c.group) groupSet.add(c.group); if (c.source) sourceSet.add(c.source); });
    groupSelect.innerHTML = '<option value="">All groups</option>' + [...groupSet].sort().map(g => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join('');
    sourceSelect.innerHTML = '<option value="">All sources</option>' + [...sourceSet].sort().map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
}

function filterCameras() {
    const q = document.getElementById('search').value.trim().toLowerCase();
    const g = document.getElementById('groupFilter').value;
    const s = document.getElementById('sourceFilter').value;
    return cameras.filter(cam => {
        if (g && cam.group !== g) return false;
        if (s && cam.source !== s) return false;
        if (!q) return true;
        const hay = [
            cam.title, cam.name, cam.camid, cam.group, cam.source,
            cam.description, cam.perspective,
            cam.location && cam.location.road,
            cam.location && cam.location.area,
            cam.view && cam.view.heading_description,
            ...(cam.view && cam.view.coverage || [])
        ].filter(Boolean).join(' ').toLowerCase();
        return hay.includes(q);
    });
}

function updateMarkers() {
    markers.forEach(m => {
        if (filtered.includes(m.cam)) map.addLayer(m);
        else map.removeLayer(m);
    });
}

function fitAll() {
    const visible = markers.filter(m => filtered.includes(m.cam));
    if (visible.length) {
        const bounds = L.latLngBounds(visible.map(m => m.getLatLng()));
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
    }
}

function openCamera(i) {
    if (!filtered.length) return;
    currentIndex = ((i % filtered.length) + filtered.length) % filtered.length;
    const cam = filtered[currentIndex];
    const marker = markers.find(m => m.cam === cam);
    if (!marker) return;
    stopAllPlayers();
    map.flyTo([cam.lat, cam.lon], 16, { duration: 0.6 });
    marker.openPopup();
    document.getElementById('pageInfo').textContent = `${currentIndex + 1} / ${filtered.length}`;
}

function applyFilters() {
    filtered = filterCameras();
    currentIndex = 0;
    updateMarkers();
    renderList();
    renderLegend(filtered);
    if (filtered.length) {
        document.getElementById('pageInfo').textContent = `1 / ${filtered.length}`;
        fitAll();
    } else {
        document.getElementById('pageInfo').textContent = '0 / 0';
    }
}

function stopAuto() {
    if (autoTimer) {
        clearInterval(autoTimer);
        autoTimer = null;
        document.getElementById('autoBtn').textContent = '▶ Discover';
    }
}

function toggleAuto() {
    if (autoTimer) { stopAuto(); return; }
    if (!filtered.length) return;
    openCamera(currentIndex);
    autoTimer = setInterval(() => { currentIndex = (currentIndex + 1) % filtered.length; openCamera(currentIndex); }, 5000);
    document.getElementById('autoBtn').textContent = '⏸ Pause';
}

function setupControls() {
    document.getElementById('search').addEventListener('input', () => { stopAuto(); applyFilters(); });
    document.getElementById('groupFilter').addEventListener('change', () => { stopAuto(); applyFilters(); });
    document.getElementById('sourceFilter').addEventListener('change', () => { stopAuto(); applyFilters(); });
    document.getElementById('fitBtn').addEventListener('click', fitAll);
    document.getElementById('resetBtn').addEventListener('click', () => {
        stopAuto();
        document.getElementById('search').value = '';
        document.getElementById('groupFilter').value = '';
        document.getElementById('sourceFilter').value = '';
        applyFilters();
    });
    document.getElementById('prevBtn').addEventListener('click', () => { stopAuto(); openCamera(currentIndex - 1); });
    document.getElementById('nextBtn').addEventListener('click', () => { stopAuto(); openCamera(currentIndex + 1); });
    document.getElementById('autoBtn').addEventListener('click', toggleAuto);
    document.getElementById('tabMap').addEventListener('click', () => switchView('map'));
    document.getElementById('tabList').addEventListener('click', () => switchView('list'));
    document.getElementById('detailClose').addEventListener('click', closeDetail);
    document.getElementById('listBody').addEventListener('click', e => {
        const row = e.target.closest('tr');
        if (row && row.dataset.idx != null) {
            const idx = parseInt(row.dataset.idx, 10);
            if (filtered[idx]) openDetail(filtered[idx]);
        }
    });
}

function initMap() {
    map = L.map('map').setView([13.7, 100.7], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18
    }).addTo(map);

    markers = [];
    cameras.forEach(cam => {
        const color = (groups[cam.group] && groups[cam.group].color) || '#0a84ff';
        const marker = createMarker(map, cam, color);
        markers.push(marker);
    });

    map.on('popupclose', stopAllPlayers);
}

async function load() {
    try {
        const res = await fetch('/cameras.json');
        if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
        const data = await res.json();
        groups = data.groups || {};
        cameras = (data.cameras || []).filter(c => c.enabled !== false).map(cam => ({ ...cam, play_url: pickPlayUrl(cam) }));
        renderLegend();
        initMap();
        populateFilters();
        setupControls();
        applyFilters();
    } catch (e) {
        document.getElementById('legend').textContent = 'Failed to load cameras: ' + e.message;
    }
}

load();
