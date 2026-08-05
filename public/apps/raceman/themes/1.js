(function() {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = 'themes/1.css?v=' + Date.now();
  document.head.appendChild(link);
})();

class RacingTheme extends DefaultTheme {
  constructor(options = {}) {
    super(options);
    this.clockInterval = null;
    this.racingMarkerSvgs = {
      'sausage-orange': '<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="12" fill="#f97316" stroke="#fff" stroke-width="3"/></svg>',
      'flag-checkered': '<svg viewBox="0 0 32 32"><rect x="4" y="4" width="24" height="24" fill="#fff"/><path d="M4 4h12v12H4zm12 12h12v12H16z" fill="#111"/></svg>',
      'flag-square': '<svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" fill="#ef4444" stroke="#fff" stroke-width="3"/></svg>'
    };
  }

  markerIcon(name, label) {
    const svg = this.racingMarkerSvgs[name] || '<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="12" fill="#64748b" stroke="#fff" stroke-width="3"/></svg>';
    return L.divIcon({ className: 'racing-marker', html: svg, iconSize: [40, 40], iconAnchor: [20, 20] });
  }

  markerLabelIcon(label) {
    return L.divIcon({ className: 'racing-marker-label', html: `<div class="racing-marker-label-inner">${label}</div>`, iconSize: [120, 24], iconAnchor: [60, 0] });
  }

  lineLabelIcon(text, rotation = 0) {
    return L.divIcon({ className: 'racing-line-label', html: `<div class="racing-line-label-inner" style="transform: translate(-50%,-50%) rotate(${rotation.toFixed(1)}deg);">${text}</div>`, iconSize: [1, 1], iconAnchor: [0, 0] });
  }

  arrowIcon(heading) {
    return L.divIcon({ className: 'racing-arrow', html: `<svg viewBox="0 0 32 32" fill="#facc15" style="transform: rotate(${heading}deg); filter: drop-shadow(0 0 3px rgba(250,204,21,0.6));"><path d="M16 2l12 24H4z"/></svg>`, iconSize: [24, 24], iconAnchor: [12, 12] });
  }

  boatIcon(color, heading, racer = null) {
    const label = (racer ? (racer.sail || '') : '').toUpperCase();
    const flag = racer ? (racer.flag || '') : '';
    const fs = label.length > 8 ? 10 : (label.length > 6 ? 12 : 14);
    const boxW = Math.min(94, 30 + label.length * (fs * 0.65));
    const html = `
      <div class="racing-boat" style="width:110px;height:110px;position:relative;transform:rotate(${heading.toFixed(1)}deg);">
        ${flag ? `
          <div class="racing-boat-link" style="position:absolute;left:50%;top:54px;width:3px;height:34px;background:${color};transform:translate(-50%,0);"></div>
          <div class="racing-boat-label" style="width:${boxW}px;top:88px;bottom:auto;transform:translate(-50%,0) rotate(${(-heading).toFixed(1)}deg);">
            <div class="racing-boat-flag">${flag}</div>
            <div class="racing-boat-sail" style="font-size:${fs}px;">${label}</div>
          </div>
        ` : ''}
        <svg class="racing-boat-arrow" viewBox="0 0 110 110" style="position:absolute;top:0;left:0;width:100%;height:100%;z-index:1;color:${color};">
          <path d="M55 4 L69 40 A14 14 0 0 1 41 40 Z" fill="currentColor" opacity="0.95"/>
        </svg>
      </div>
    `;
    return L.divIcon({ className: 'racing-boat-icon', html, iconSize: [110, 110], iconAnchor: [55, 55] });
  }

  drawLine(p1, p2, color, text, side = 'left', dash = '8,6', drawPoly = true, renderer) {
    const isGate = /^(START|FINISH|BEACH START)$/i.test(text || '');
    if (drawPoly) {
      if (isGate) {
        const h = Course.bearing(p1, p2);
        const post = 30;
        const left1 = Course.offsetPoint(p1, h, post, 'left');
        const right1 = Course.offsetPoint(p1, h, post, 'right');
        const left2 = Course.offsetPoint(p2, h, post, 'left');
        const right2 = Course.offsetPoint(p2, h, post, 'right');
        L.polyline([p1, p2], { color, weight: 5, lineCap: 'round', lineJoin: 'round' }).addTo(renderer.guideLayer);
        L.polyline([left1, p1, right1], { color, weight: 4, lineCap: 'round', lineJoin: 'round' }).addTo(renderer.guideLayer);
        L.polyline([left2, p2, right2], { color, weight: 4, lineCap: 'round', lineJoin: 'round' }).addTo(renderer.guideLayer);
      } else {
        L.polyline([p1, p2], { color, weight: 4, dashArray: dash, lineCap: 'round', lineJoin: 'round' }).addTo(renderer.guideLayer);
      }
    }
    const mid = Course.midpoint(p1, p2);
    const h = Course.bearing(p1, p2);
    const labelSide = side === 'right' || side === 'starboard' || side === 'bottom' ? 'right' : 'left';
    const labelPos = Course.offsetPoint(mid, h, 12, labelSide);
    const labelRot = h - 90;
    L.marker(labelPos, { icon: this.lineLabelIcon(text, labelRot), interactive: false }).addTo(renderer.guideLayer);
  }

  drawOne(d, renderer, onDrag) {
    if (d.kind === 'section') {
      const pts = d.points.map(p => [p[0], p[1]]);
      d.polyline = L.polyline(pts, { className: 'racing-section-line', color: d.color, weight: (d.width || 8) + 4, dashArray: null, opacity: 0.9, lineCap: 'round', lineJoin: 'round' }).addTo(renderer.guideLayer);
      const mid = Course.pointAlong(pts, 0.5);
      if (mid && mid.point) {
        const n = (d.key.match(/\d+$/) || [''])[0];
        const isRound = /round/i.test(d.key);
        const dist = (!isRound && d.distance) ? ' ' + (d.distance / 1000).toFixed(2) + ' km' : '';
        const label = isRound ? `MARK ${n} ROUNDING` : `LEG ${n}${dist}`;
        L.marker(mid.point, { icon: this.lineLabelIcon(label, mid.bearing - 90), interactive: false }).addTo(renderer.guideLayer);
      }
      if (d.center && d.entry && d.exit) {
        L.polyline([[d.center[0], d.center[1]], [d.entry[0], d.entry[1]]], { className: 'racing-section-line', color: d.color, weight: 1, dashArray: '3,4', opacity: 0.6 }).addTo(renderer.guideLayer);
        L.polyline([[d.center[0], d.center[1]], [d.exit[0], d.exit[1]]], { className: 'racing-section-line', color: d.color, weight: 1, dashArray: '3,4', opacity: 0.6 }).addTo(renderer.guideLayer);
      }
      if (pts.length >= 2) {
        const pre = pts[pts.length - 2];
        const end = pts[pts.length - 1];
        const h = Course.bearing(pre, end);
        L.marker(end, { icon: this.arrowIcon(h), interactive: false }).addTo(renderer.guideLayer);
      }
      return;
    }
    super.drawOne(d, renderer, onDrag);
  }

  _windDirName(deg) {
    const names = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
    const i = (Math.round(deg / 22.5) % 16 + 16) % 16;
    return names[i];
  }

  _startClock() {
    if (this.clockInterval) return;
    const tick = () => {
      const el = document.getElementById('race-clock');
      if (!el) return;
      const now = new Date();
      const h = String(now.getUTCHours()).padStart(2, '0');
      const m = String(now.getUTCMinutes()).padStart(2, '0');
      const s = String(now.getUTCSeconds()).padStart(2, '0');
      el.textContent = `${h}:${m}:${s} UTC`;
    };
    tick();
    this.clockInterval = setInterval(tick, 1000);
  }

  renderStandings({ sorted, total, elapsed, speedFactor }) {
    const el = document.getElementById('sim-standings');
    if (!el) return;
    const pct = d => total ? (d / total * 100).toFixed(0) : 0;
    const fmt = s => { const m = Math.floor(s / 60); const sec = Math.floor(s % 60); return `${m}:${String(sec).padStart(2, '0')}`; };
    const leader = sorted[0];
    const leaderDist = leader ? leader.distance : 0;
    const section = leader ? currentSection(leader) : '—';
    const progress = leader ? pct(leader.distance) : 0;
    const courseLength = total ? (total / 1000).toFixed(1) : '—';
    const rows = sorted.map((r, i) => {
      const speed = (r.speed * 3.6).toFixed(1);
      let gap = '—';
      if (i > 0 && r.speed > 0.1) {
        const seconds = (leaderDist - r.distance) / r.speed;
        if (seconds > 0.5) {
          const m = Math.floor(seconds / 60);
          const s = Math.floor(seconds % 60);
          gap = `+${m}:${String(s).padStart(2, '0')}`;
        }
      }
      const status = i === 0 ? '<span class="race-status-leader">LEADER</span>' : '—';
      return `
        <tr class="race-table-row" data-name="${r.name}">
          <td class="race-table-pos" style="color:${r.color}">${i + 1}</td>
          <td class="race-table-sail">${r.sail}</td>
          <td class="race-table-boat">${r.name}</td>
          <td class="race-table-speed">${speed}</td>
          <td class="race-table-gap">${gap}</td>
          <td class="race-table-status">${status}</td>
        </tr>
      `;
    }).join('');
    el.innerHTML = `
      <div class="race-table-header">
        <span class="race-table-title">Race Simulation</span>
        <span class="race-table-time">TIME ${fmt(elapsed)}</span>
      </div>
      <table class="race-table">
        <thead>
          <tr>
            <th class="race-table-th-pos">POS</th>
            <th class="race-table-th-sail">SAIL</th>
            <th class="race-table-th-boat">BOAT</th>
            <th class="race-table-th-speed">SPD</th>
            <th class="race-table-th-gap">GAP</th>
            <th class="race-table-th-status">STS</th>
          </tr>
        </thead>
        <tbody class="race-table-body">${rows}</tbody>
      </table>
      <div class="race-info">
        <div class="race-info-title">RACE INFO</div>
        <div class="race-info-row"><span>Course Length</span><span>${courseLength} km</span></div>
        <div class="race-info-row"><span>Laps</span><span>1</span></div>
        <div class="race-info-row"><span>Section</span><span>${section}</span></div>
        <div class="race-info-progress-label"><span>1/1 LAPS</span><span>${progress}%</span></div>
        <div class="race-info-progress-bar"><div class="race-info-progress-fill" style="width:${progress}%"></div></div>
      </div>
    `;
  }

  installChrome(courseData) {
    if (document.getElementById('race-chrome')) return;
    const wind = (courseData && courseData.wind) || { direction: 225, speed_kts: 18 };
    const dir = wind.direction || 225;
    const speed = wind.speed_kts || 18;
    const dirName = this._windDirName(dir);
    const nav = document.getElementById('app-nav');
    const navHidden = !nav || nav.style.display === 'none' || window.getComputedStyle(nav).display === 'none';

    const chrome = document.createElement('div');
    chrome.id = 'race-chrome';
    chrome.style.top = navHidden ? '0' : '48px';
    chrome.innerHTML = `
      <div class="race-left">
        <svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor"><path d="M22 17c0-3.5-4-6.5-9-7.5v-1c3.5-1 6-3.5 6-6.5 0-1.5-1-2.5-2.5-2.5S14 1.5 14 3c0 1.5 1 2.5 2.5 2.5.5 0 1 0 1.5-.2-1 2-3 3.5-6 4.3v1.9c-5 .6-9 3.6-9 7.5 0 3.5 4 6.5 9 7.5v1c-3.5 1-6 3.5-6 6.5 0 1.5 1 2.5 2.5 2.5S10 22.5 10 21c0-1.5-1-2.5-2.5-2.5-.5 0-1 0-1.5.2 1-2 3-3.5 6-4.3v-1.9c5-.6 9-3.6 9-7.5z" opacity=".85"/></svg>
        <div class="race-brand">
          <div class="race-title">WINDSURF RACING</div>
          <div class="race-subtitle">INTERNATIONAL SERIES</div>
        </div>
      </div>
      <div class="race-center">
        <div class="race-status"><span class="race-dot"></span> LIVE <span id="race-clock" class="race-clock">--:--:-- UTC</span></div>
        <div class="race-sim">RACE SIMULATION</div>
      </div>
      <div class="race-right">
        <div class="race-wind-arrow">
          <svg viewBox="0 0 24 24" width="28" height="28" style="transform: rotate(${dir}deg);"><path d="M12 2l10 18H2z"/></svg>
        </div>
        <div class="race-wind-stack">
          <div class="race-wind-label">WIND</div>
          <div class="race-wind-value">${speed} <span>kt</span></div>
          <div class="race-wind-dir">${dirName} ${dir}°</div>
        </div>
      </div>
    `;
    document.body.appendChild(chrome);

    const compass = document.createElement('div');
    compass.id = 'race-compass';
    compass.className = 'race-compass';
    compass.innerHTML = `
      <svg viewBox="0 0 80 80" width="64" height="64">
        <circle cx="40" cy="40" r="38" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="2"/>
        <text x="40" y="14" text-anchor="middle" fill="white" font-size="11" font-weight="bold">N</text>
        <text x="69" y="44" text-anchor="middle" fill="white" font-size="10">E</text>
        <text x="40" y="73" text-anchor="middle" fill="white" font-size="10">S</text>
        <text x="11" y="44" text-anchor="middle" fill="white" font-size="10">W</text>
        <path d="M40 8 L44 36 L40 32 L36 36 Z" fill="#0a84ff"/>
        <path d="M40 72 L36 44 L40 48 L44 44 Z" fill="#ef4444"/>
      </svg>
    `;
    document.body.appendChild(compass);

    const windKmh = (speed * 1.852).toFixed(0);
    const gustKmh = Math.round(speed * 1.852 * 1.2);
    const left = document.createElement('div');
    left.id = 'race-left-panel';
    left.style.top = navHidden ? '64px' : '112px';
    left.innerHTML = `
      <div class="race-left-card">
        <div class="race-left-section">
          <div class="race-left-label">WIND</div>
          <div class="race-left-value">${windKmh} <span>km/h</span></div>
          <div class="race-left-sub">GUST ${gustKmh} km/h · ${dirName}</div>
        </div>
        <div class="race-left-section">
          <div class="race-left-label">SEA CONDITION</div>
          <div class="race-left-value">MODERATE</div>
          <div class="race-left-sub">WAVE 0.6 - 1.0 m</div>
        </div>
        <div class="race-left-section">
          <div class="race-left-label">AIR TEMP</div>
          <div class="race-left-value">32°C</div>
        </div>
        <div class="race-left-legend">
          <div class="race-left-label">LEGEND</div>
          <div class="race-legend-item"><span class="race-legend-dot" style="background:#f97316"></span> Turning Mark</div>
          <div class="race-legend-item"><span class="race-legend-dot" style="background:#ef4444"></span> Start / Finish</div>
          <div class="race-legend-item"><span class="race-legend-dot" style="background:#fff"></span> Race Committee</div>
          <div class="race-legend-item"><span class="race-legend-dot" style="background:#3b82f6"></span> Safety Boat</div>
        </div>
      </div>
    `;
    document.body.appendChild(left);

    this._startClock();

    const simTab = document.getElementById('tab-sim-content');
    if (simTab) simTab.classList.add('racing-sim');
    const standings = document.getElementById('sim-standings');
    if (standings) standings.className = 'racing-standings';
  }

  // Override map visual methods here to match the race-simulation style:
  // - markerIcon(name, label) for large rounding-mark / start-finish SVGs
  // - lineLabelIcon(text, rotation) for leg distance callouts (e.g. "LEG 1 2.1 km")
  // - arrowIcon(heading) for thick yellow direction arrows
  // - drawOne(d, renderer, onDrag) for section fills, gradient lanes, finish gates, etc.
}

window.TrackTheme = RacingTheme;
