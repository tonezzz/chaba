(function () {
  const POLL_MS = 2000;
  let viewId = null;
  let lastState = null;
  let lastSeek = null;
  let activeEl = null;

  const $setup = document.getElementById('setup');
  const $media = document.getElementById('media');
  const $input = document.getElementById('view-id-input');
  const $join = document.getElementById('join-btn');
  const $display = document.getElementById('media-display');
  const $idle = document.getElementById('idle');
  const $viewId = document.getElementById('view-id');
  const $status = document.getElementById('status-label');
  const $btnPlay = document.getElementById('btn-play');
  const $btnNext = document.getElementById('btn-next');
  const $btnPrev = document.getElementById('btn-prev');
  const $btnFull = document.getElementById('btn-full');

  function saveView(id) { localStorage.setItem('rview-view-id', id); }

  function init() {
    const q = new URLSearchParams(location.search).get('view_id') || localStorage.getItem('rview-view-id') || '';
    if (q) {
      setView(q);
    } else {
      $setup.classList.add('active');
      $media.classList.remove('active');
    }

    $join.addEventListener('click', () => { const v = $input.value.trim(); if (v) setView(v); });
    $input.addEventListener('keydown', (e) => { if (e.key === 'Enter') $join.click(); });

    $btnPlay.addEventListener('click', () => sendControl('playpause'));
    $btnNext.addEventListener('click', () => sendControl('next'));
    $btnPrev.addEventListener('click', () => sendControl('prev'));
    $btnFull.addEventListener('click', toggleFull);

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js');
    }
  }

  function setView(id) {
    viewId = id;
    saveView(id);
    history.replaceState({}, '', '?view_id=' + encodeURIComponent(id));
    $setup.classList.remove('active');
    $media.classList.add('active');
    $viewId.textContent = id;
    fetchState();
    setInterval(fetchState, POLL_MS);
  }

  async function fetchState() {
    if (!viewId) return;
    try {
      const r = await fetch('api/state.php?view_id=' + encodeURIComponent(viewId));
      const s = await r.json();
      if (!s.ok) throw new Error(s.error);
      lastState = s;
      render(s);
      $status.textContent = s.status.playing ? 'playing' : 'paused';
    } catch (e) {
      $status.textContent = 'error: ' + e.message;
    }
  }

  function inferType(url) {
    const lower = url.toLowerCase();
    if (/\.(jpg|jpeg|png|gif|webp|svg|bmp|avif)([?#]|$)/.test(lower)) return 'image';
    if (/\.(mp4|webm|ogg|mov|mkv|m4v)([?#]|$)/.test(lower)) return 'video';
    if (/\.(mp3|wav|ogg|flac|aac|m4a|oga)([?#]|$)/.test(lower)) return 'audio';
    if (/\.pdf([?#]|$)/.test(lower)) return 'pdf';
    return 'iframe';
  }

  function render(s) {
    if (!s.current) {
      $display.innerHTML = '<div id="idle">No media loaded</div>';
      activeEl = null;
      return;
    }

    const url = s.current.url;
    const type = s.current.media_type === 'auto' ? inferType(url) : s.current.media_type;
    const title = s.current.title || url;

    if (activeEl && activeEl.dataset.url === url && activeEl.dataset.type === type) {
      syncMedia(activeEl, s.status, type);
      return;
    }

    $display.innerHTML = '';
    activeEl = null;

    if (type === 'image') {
      const img = document.createElement('img');
      img.src = url;
      img.alt = title;
      img.dataset.url = url;
      img.dataset.type = type;
      $display.appendChild(img);
      activeEl = img;
    } else if (type === 'video' || type === 'audio') {
      const el = document.createElement(type);
      el.src = url;
      el.dataset.url = url;
      el.dataset.type = type;
      el.controls = true;
      el.loop = s.status.loop;
      el.muted = s.status.muted;
      el.volume = s.status.volume;
      el.autoplay = s.status.playing;
      if (type === 'video') el.playsInline = true;
      $display.appendChild(el);
      activeEl = el;
      syncMedia(el, s.status, type);
    } else if (type === 'pdf') {
      const embed = document.createElement('embed');
      embed.src = url;
      embed.type = 'application/pdf';
      embed.style.width = '100%';
      embed.style.height = '100%';
      embed.dataset.url = url;
      embed.dataset.type = type;
      $display.appendChild(embed);
      activeEl = embed;
    } else {
      const iframe = document.createElement('iframe');
      iframe.src = url;
      iframe.allowFullscreen = true;
      iframe.dataset.url = url;
      iframe.dataset.type = type;
      $display.appendChild(iframe);
      activeEl = iframe;
    }
  }

  function syncMedia(el, status, type) {
    if (type !== 'video' && type !== 'audio') return;
    if (status.playing && el.paused) el.play().catch(() => {});
    if (!status.playing && !el.paused) el.pause();
    el.volume = status.volume;
    el.muted = status.muted;
    el.loop = status.loop;
    const t = parseFloat(status.current_time || 0);
    if (!isNaN(t) && lastSeek !== t) {
      el.currentTime = t;
      lastSeek = t;
    }
    if (status.fullscreen && !document.fullscreenElement) {
      el.requestFullscreen?.();
    }
    if (!status.fullscreen && document.fullscreenElement) {
      document.exitFullscreen?.();
    }
  }

  function sendControl(cmd) {
    if (!viewId) return;
    let action = cmd;
    if (cmd === 'playpause') {
      action = lastState && lastState.status.playing ? 'pause' : 'play';
    }
    fetch('api/state.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ view_id: viewId, action: 'control', command: action })
    });
  }

  function toggleFull() {
    if (!document.fullscreenElement) {
      $display.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }

  init();
})();
