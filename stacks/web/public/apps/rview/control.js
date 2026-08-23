(function () {
  const POLL_MS = 2000;
  let selectedId = null;
  let state = null;

  const $newId = document.getElementById('new-view-id');
  const $newName = document.getElementById('new-view-name');
  const $btnCreate = document.getElementById('btn-create');
  const $viewList = document.getElementById('view-list');
  const $selId = document.getElementById('sel-id');
  const $mediaUrl = document.getElementById('media-url');
  const $mediaTitle = document.getElementById('media-title');
  const $mediaType = document.getElementById('media-type');
  const $btnSet = document.getElementById('btn-set');
  const $btnEnqueue = document.getElementById('btn-enqueue');
  const $btnPlay = document.getElementById('btn-play');
  const $btnPause = document.getElementById('btn-pause');
  const $btnStop = document.getElementById('btn-stop');
  const $btnNext = document.getElementById('btn-next');
  const $btnPrev = document.getElementById('btn-prev');
  const $btnClear = document.getElementById('btn-clear');
  const $seekVal = document.getElementById('seek-val');
  const $btnSeek = document.getElementById('btn-seek');
  const $volVal = document.getElementById('vol-val');
  const $btnVol = document.getElementById('btn-vol');
  const $chkFull = document.getElementById('chk-full');
  const $chkLoop = document.getElementById('chk-loop');
  const $chkShuffle = document.getElementById('chk-shuffle');
  const $status = document.getElementById('status');
  const $queue = document.getElementById('queue');
  const $qr = document.getElementById('qr');
  const $qrHint = document.getElementById('qr-hint');
  const $qrUrl = document.getElementById('qr-url');

  async function api(method, body) {
    const r = await fetch('api/state.php', {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    return j;
  }

  async function refreshList() {
    try {
      const r = await fetch('api/state.php?action=list');
      const j = await r.json();
      if (!j.ok) return;
      $viewList.innerHTML = '';
      j.views.forEach((v) => {
        const d = document.createElement('div');
        d.className = 'view-card';
        const current = v.current ? (v.current.title || v.current.url) : 'idle';
        d.innerHTML = '<div><b>' + escapeHtml(v.display_name) + '</b> <code>' + escapeHtml(v.view_id) + '</code><br><small>' + escapeHtml(current) + '</small></div>' +
          '<div>' +
          '<button data-id="' + escapeHtml(v.view_id) + '" class="select-btn secondary">Select</button>' +
          ' <button data-id="' + escapeHtml(v.view_id) + '" class="delete-btn danger">Delete</button>' +
          '</div>';
        $viewList.appendChild(d);
      });
      $viewList.querySelectorAll('.select-btn').forEach((b) => b.addEventListener('click', () => selectView(b.dataset.id)));
      $viewList.querySelectorAll('.delete-btn').forEach((b) => b.addEventListener('click', () => deleteView(b.dataset.id)));
    } catch (e) { console.error(e); }
  }

  function updateQr() {
    if (!selectedId) {
      $qr.style.display = 'none';
      $qrHint.style.display = 'block';
      $qrUrl.textContent = '';
      $qrUrl.href = '';
      return;
    }
    const u = new URL('index.html', window.location.href);
    u.searchParams.set('view_id', selectedId);
    $qrUrl.href = u.toString();
    $qrUrl.textContent = u.toString();
    $qr.src = 'https://api.qrserver.com/v1/create-qr-code/?size=256x256&data=' + encodeURIComponent(u.toString());
    $qr.style.display = 'block';
    $qrHint.style.display = 'none';
  }

  async function selectView(id) {
    selectedId = id;
    $selId.textContent = id;
    await refreshState();
    updateQr();
  }

  async function deleteView(id) {
    if (!confirm('Delete ' + id + '?')) return;
    await api('POST', { view_id: id, action: 'delete' });
    if (selectedId === id) {
      selectedId = null;
      $selId.textContent = 'none';
      $status.textContent = '';
      $queue.innerHTML = '';
      updateQr();
    }
    refreshList();
  }

  async function refreshState() {
    if (!selectedId) return;
    try {
      const r = await fetch('api/state.php?view_id=' + encodeURIComponent(selectedId));
      const j = await r.json();
      if (!j.ok) return;
      state = j;
      $status.textContent = 'playing=' + j.status.playing + ' | current_time=' + j.status.current_time + ' | queue=' + j.queue.length;
      $queue.innerHTML = '';
      (j.queue || []).forEach((it) => {
        const li = document.createElement('li');
        li.innerHTML = '<span>' + escapeHtml(it.title || it.url) + '</span> <small>' + escapeHtml(it.media_type) + '</small>';
        $queue.appendChild(li);
      });
      $chkFull.checked = j.status.fullscreen;
      $chkLoop.checked = j.status.loop;
      $chkShuffle.checked = j.status.shuffle;
    } catch (e) { console.error(e); }
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  $btnCreate.addEventListener('click', async () => {
    const id = $newId.value.trim();
    if (!id) return;
    await api('POST', { view_id: id, action: 'create', display_name: $newName.value.trim() || id });
    $newId.value = '';
    $newName.value = '';
    refreshList();
    selectView(id);
  });

  async function doShow(enqueue) {
    if (!selectedId) return alert('select a view first');
    const url = $mediaUrl.value.trim();
    if (!url) return;
    await api('POST', {
      view_id: selectedId,
      action: 'show',
      url,
      title: $mediaTitle.value.trim(),
      media_type: $mediaType.value,
      enqueue
    });
    $mediaUrl.value = '';
    $mediaTitle.value = '';
    refreshState();
    refreshList();
  }
  $btnSet.addEventListener('click', () => doShow(false));
  $btnEnqueue.addEventListener('click', () => doShow(true));

  $btnPlay.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'play' }).then(refreshState));
  $btnPause.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'pause' }).then(refreshState));
  $btnStop.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'stop' }).then(refreshState));
  $btnNext.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'next' }).then(refreshState));
  $btnPrev.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'prev' }).then(refreshState));
  $btnClear.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'clear_queue' }).then(refreshState));

  $btnSeek.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'seek', value: parseFloat($seekVal.value) || 0 }).then(refreshState));
  $btnVol.addEventListener('click', () => selectedId && api('POST', { view_id: selectedId, action: 'control', command: 'volume', value: parseFloat($volVal.value) || 1 }).then(refreshState));

  [$chkFull, $chkLoop, $chkShuffle].forEach((el) => el.addEventListener('change', () => {
    if (!selectedId) return;
    const map = { 'chk-full': 'fullscreen', 'chk-loop': 'loop', 'chk-shuffle': 'shuffle' };
    const key = map[el.id];
    if (!key) return;
    api('POST', { view_id: selectedId, action: 'control', command: key, value: el.checked }).then(refreshState);
  }));

  refreshList();
  const startView = new URLSearchParams(location.search).get('view_id');
  if (startView) selectView(startView);
  setInterval(() => { refreshList(); refreshState(); }, POLL_MS);
})();
