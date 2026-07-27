    const API = './api';
    const MAX_HISTORY = 12;
    const MAX_QUEUE = 5;

    const $ = (id) => document.getElementById(id);
    const statusEl = $('status');
    const generateBtn = $('generate');
    const outputEl = $('output');
    const thumbsEl = $('thumbs');
    const metaEl = $('meta');
    const downloadSelect = $('download-scale');
    const progressEl = $('progress');
    const refInput = $('reference');
    const refPreview = $('ref-preview');
    const refClear = $('ref-clear');
    const strengthEl = $('strength');
    const strengthVal = $('strength-val');

    let history = [];
    let queue = [];
    let activeJob = null;
    let currentB64 = null;
    let refBase64 = '';
    let activeView = 'generated';
    let pendingDeleteIndex = -1;

    function readFile(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
    }

    function updateRefPreview() {
      refPreview.src = refBase64;
      refPreview.classList.toggle('visible', !!refBase64);
      renderTabs();
      if (activeView === 'original') renderViewer();
    }

    function renderTabs() {
      const tabs = $('view-tabs');
      if (!tabs) return;
      const hasRef = !!refBase64;
      tabs.style.display = hasRef ? 'flex' : 'none';
      tabs.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === activeView);
      });
    }

    function renderViewer() {
      if (activeView === 'original' && refBase64) {
        outputEl.innerHTML = `<img src="${refBase64}" alt="Original">`;
        return;
      }
      if (activeJob && activeJob.preview) {
        outputEl.innerHTML = `<img src="${activeJob.preview}" alt="Preview" style="max-width:100%;max-height:70vh">`;
        return;
      }
      if (activeJob) {
        outputEl.innerHTML = '<div class="placeholder"><div class="spinner"></div>Generating image...</div>';
        return;
      }
      if (currentB64) {
        outputEl.innerHTML = `<img src="data:image/png;base64,${currentB64}" alt="Generated">`;
        return;
      }
      outputEl.innerHTML = '<div class="placeholder">Generated image will appear here</div>';
    }

    function updateGenerateBtn() {
      const pendingCount = history.filter(i => i.pending).length;
      if (pendingCount >= MAX_QUEUE) {
        generateBtn.disabled = true;
        generateBtn.textContent = 'Queue full';
      } else {
        generateBtn.disabled = false;
        generateBtn.textContent = activeJob ? 'Add to queue' : 'Generate';
      }
    }

    function saveForm() {
      const form = {
        prompt: $('prompt').value,
        negative_prompt: $('negative').value,
        width: $('width').value,
        height: $('height').value,
        steps: $('steps').value,
        seed: $('seed').value,
        strength: $('strength').value,
        guidance_scale: $('guidance-scale').value,
        guidance_rescale: $('guidance-rescale').value
      };
      try { localStorage.setItem('imagen2_form', JSON.stringify(form)); } catch {}
    }

    function restoreState() {
      try {
        const form = JSON.parse(localStorage.getItem('imagen2_form') || '{}');
        if (form.prompt !== undefined) $('prompt').value = form.prompt;
        if (form.negative_prompt !== undefined) $('negative').value = form.negative_prompt;
        if (form.width !== undefined) $('width').value = form.width;
        if (form.height !== undefined) $('height').value = form.height;
        if (form.steps !== undefined) $('steps').value = form.steps;
        if (form.seed !== undefined) $('seed').value = form.seed;
        if (form.strength !== undefined) {
          $('strength').value = form.strength;
          $('strength-val').textContent = form.strength;
        }
        if (form.guidance_scale !== undefined) {
          $('guidance-scale').value = form.guidance_scale;
        }
        if (form.guidance_rescale !== undefined) {
          $('guidance-rescale').value = form.guidance_rescale;
        }
      } catch {}
      try {
        const ref = localStorage.getItem('imagen2_ref');
        if (ref) { refBase64 = ref; updateRefPreview(); }
      } catch {}
      try {
        const last = JSON.parse(localStorage.getItem('imagen2_last') || '{}');
        if (last && last.b64) { showImage(last); }
      } catch {}
    }

    function appendIfMissing(el, text) {
      const current = el.value.trim();
      const parts = text.split(',').map(s => s.trim()).filter(Boolean);
      if (!current) {
        el.value = parts.join(', ');
      } else {
        const existing = current.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
        const missing = parts.filter(p => !existing.includes(p.toLowerCase()));
        if (missing.length) {
          const sep = /[,;]$/.test(current) ? ' ' : ', ';
          el.value = current + sep + missing.join(', ');
        }
      }
      saveForm();
    }

    $('add-quality').addEventListener('click', () => {
      appendIfMissing($('prompt'), 'masterpiece, best quality, highly detailed, sharp focus');
    });

    $('add-negative').addEventListener('click', () => {
      appendIfMissing($('negative'), 'worst quality, bad anatomy, deformed, extra limbs, missing fingers, mutated hands, watermark, signature, text, logo');
    });

    $('regenerate').addEventListener('click', () => regenerateLast(false));
    $('variate').addEventListener('click', () => regenerateLast(true));

    ['prompt', 'negative', 'width', 'height', 'steps', 'seed', 'guidance-scale', 'guidance-rescale'].forEach(id => {
      const el = $(id);
      if (el) el.addEventListener('change', saveForm);
    });
    $('strength').addEventListener('input', saveForm);

    refInput.addEventListener('change', async () => {
      const file = refInput.files[0];
      if (!file) {
        refBase64 = '';
        updateRefPreview();
        try { localStorage.removeItem('imagen2_ref'); } catch {}
        return;
      }
      try {
        refBase64 = await readFile(file);
        updateRefPreview();
        try { localStorage.setItem('imagen2_ref', refBase64); } catch {}
      } catch (e) {
        statusEl.textContent = `Failed to read reference image: ${e.message}`;
        statusEl.className = 'status error';
      }
    });

    refClear.addEventListener('click', () => {
      refInput.value = '';
      refBase64 = '';
      updateRefPreview();
      try { localStorage.removeItem('imagen2_ref'); } catch {}
    });

    strengthEl.addEventListener('input', () => {
      strengthVal.textContent = strengthEl.value;
    });

    $('view-tabs').addEventListener('click', (e) => {
      if (e.target.tagName !== 'BUTTON') return;
      activeView = e.target.dataset.tab || 'generated';
      renderTabs();
      renderViewer();
    });

    async function checkHealth() {
      try {
        const r = await fetch(`${API}/health`);
        const data = await r.json();
        statusEl.textContent = `Backend ready: ${data.model}`;
        statusEl.className = 'status ok';
        updateGenerateBtn();
      } catch (e) {
        statusEl.textContent = `Backend unavailable (${e.message})`;
        statusEl.className = 'status error';
      }
    }

    async function loadHistory() {
      try {
        const r = await fetch(`${API}/history`);
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const data = await r.json();
        history = Array.isArray(data.history) ? data.history : [];
      } catch (e) {
        history = [];
      }
      renderHistory();
    }

    async function saveHistory() {
      const payload = { history: history.filter(i => !i.pending).slice(0, MAX_HISTORY) };
      try {
        await fetch(`${API}/history`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (e) {
        console.error('Failed to save history to server:', e);
      }
    }

    function renderHistory() {
      thumbsEl.innerHTML = '';
      history.forEach((item, i) => {
        const div = document.createElement('div');
        const isActive = item === activeJob || (!activeJob && item.b64 === currentB64);
        div.className = 'thumb' + (isActive ? ' active' : '') + (item.pending ? ' pending' : '');
        const img = document.createElement('img');
        if (item.pending && item.preview) {
          img.src = item.preview;
        } else if (item.pending) {
          img.style.display = 'none';
        } else {
          img.src = `data:image/png;base64,${item.b64}`;
        }
        img.alt = item.prompt || '';
        div.appendChild(img);
        if (item.pending) {
          const overlay = document.createElement('div');
          overlay.className = 'overlay';
          if (item.error) {
            div.classList.add('error');
            const label = document.createElement('div');
            label.className = 'step-label';
            label.textContent = 'Error';
            overlay.appendChild(label);
          } else if (!item.submitted) {
            const pos = queue.indexOf(item) + 1;
            const qLabel = document.createElement('div');
            qLabel.className = 'queued-label';
            qLabel.textContent = `Queued #${pos}`;
            div.appendChild(qLabel);
          } else {
            const stepLabel = document.createElement('div');
            stepLabel.className = 'step-label';
            stepLabel.textContent = item.progress ? `Step ${item.progress.step}/${item.totalSteps}` : 'Starting...';
            overlay.appendChild(stepLabel);
            const pbar = document.createElement('div');
            pbar.className = 'progress-bar';
            const fill = document.createElement('div');
            const pct = item.progress && item.totalSteps ? Math.min(100, Math.round((item.progress.step / item.totalSteps) * 100)) : 0;
            fill.style.width = `${pct}%`;
            pbar.appendChild(fill);
            overlay.appendChild(pbar);
          }
          div.appendChild(overlay);
        }
        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove';
        removeBtn.textContent = '×';
        removeBtn.title = 'Remove';
        removeBtn.onclick = (e) => {
          e.stopPropagation();
          if (pendingDeleteIndex === i) {
            removeHistory(i);
          } else {
            resetDeleteButtons();
            removeBtn.textContent = 'Y';
            removeBtn.classList.add('confirm');
            pendingDeleteIndex = i;
          }
        };
        div.appendChild(removeBtn);
        div.onclick = () => recallItem(item);
        thumbsEl.appendChild(div);
      });
      const hasCompleted = history.some(i => !i.pending);
      const regenerateBtn = $('regenerate');
      const variateBtn = $('variate');
      if (regenerateBtn) regenerateBtn.disabled = !hasCompleted;
      if (variateBtn) variateBtn.disabled = !hasCompleted;
    }

    function removeHistory(idx) {
      pendingDeleteIndex = -1;
      const item = history[idx];
      if (item && item.pending) {
        if (item === activeJob) {
          item.discarded = true;
        } else {
          queue = queue.filter(q => q !== item);
        }
      }
      history.splice(idx, 1);
      renderHistory();
      saveHistory();
      updateGenerateBtn();
    }

    function resetDeleteButtons() {
      document.querySelectorAll('.remove').forEach(btn => {
        btn.textContent = '×';
        btn.classList.remove('confirm');
      });
      pendingDeleteIndex = -1;
    }

    function recallItem(item) {
      resetDeleteButtons();
      $('prompt').value = item.prompt || '';
      $('negative').value = item.negative_prompt || '';
      $('width').value = item.width || 1024;
      $('height').value = item.height || 1024;
      $('steps').value = item.steps || 25;
      const wasRandom = item.requested_seed !== undefined && item.requested_seed < 0;
      $('seed').value = wasRandom ? -1 : (item.seed !== undefined ? item.seed : -1);
      $('strength').value = item.strength !== undefined ? item.strength : 0.5;
      $('strength-val').textContent = $('strength').value;
      $('guidance-scale').value = item.guidance_scale !== undefined ? item.guidance_scale : 7.5;
      $('guidance-rescale').value = item.guidance_rescale !== undefined ? item.guidance_rescale : 0.7;
      refBase64 = item.image || '';
      activeView = 'generated';
      updateRefPreview();
      saveForm();
      try { localStorage.setItem('imagen2_ref', refBase64 || ''); } catch {}
      if (activeJob) {
        renderViewer();
      } else {
        showImage(item);
      }
    }

    function regenerateLast(newSeed = false) {
      const item = history.find(i => !i.pending);
      if (!item) {
        alert('No completed history item');
        return;
      }
      recallItem(item);
      if (newSeed) $('seed').value = -1;
      generate();
    }

    function showImage(item) {
      currentB64 = item.b64;
      renderViewer();
      const seedSuffix = item.requested_seed < 0 ? ' (random)' : '';
      metaEl.textContent = `${item.width}x${item.height} · steps ${item.steps} · seed ${item.seed}${seedSuffix} · ${item.time}s`;
      downloadSelect.disabled = false;
      renderHistory();
      try { localStorage.setItem('imagen2_last', JSON.stringify(item)); } catch {}
    }

    function base64ToBlob(b64, mime) {
      const byteString = atob(b64);
      const ab = new ArrayBuffer(byteString.length);
      const ia = new Uint8Array(ab);
      for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
      return new Blob([ab], { type: mime });
    }

    async function downloadScale(scale) {
      if (!currentB64) return;
      downloadSelect.disabled = true;
      try {
        const r = await fetch(`${API}/upscale`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: currentB64, scale: parseInt(scale, 10), fmt: 'png' })
        });
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const data = await r.json();
        const mime = `image/${data.format.toLowerCase()}`;
        const blob = base64ToBlob(data.image_base64, mime);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `imagen_${data.width}x${data.height}_${scale}x.${data.format.toLowerCase()}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (e) {
        const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
        statusEl.textContent = `Upscale error: ${msg}`;
        statusEl.className = 'status error';
      } finally {
        downloadSelect.disabled = false;
        downloadSelect.value = '';
      }
    }

    downloadSelect.addEventListener('change', () => {
      const scale = downloadSelect.value;
      if (!scale) return;
      downloadScale(scale);
    });

    function finishGenerate(queueItem, data) {
      activeJob = null;
      if (!queueItem.discarded) {
        const item = {
          b64: data.image_base64,
          prompt: queueItem.body.prompt,
          negative_prompt: queueItem.body.negative_prompt,
          width: queueItem.body.width,
          height: queueItem.body.height,
          steps: queueItem.body.steps,
          seed: data.seed,
          requested_seed: queueItem.body.seed,
          strength: queueItem.body.strength,
          guidance_scale: queueItem.body.guidance_scale,
          guidance_rescale: queueItem.body.guidance_rescale,
          image: queueItem.ref,
          time: data.inference_time
        };
        const idx = history.indexOf(queueItem);
        if (idx !== -1) history[idx] = item;
        else history.unshift(item);
        currentB64 = item.b64;
        showImage(item);
        statusEl.textContent = 'Done';
        statusEl.className = 'status ok';
        saveHistory();
      }
      updateGenerateBtn();
      processNext();
    }

    function poll(queueItem) {
      fetch(`${API}/progress/${queueItem.job_id}`)
        .then(r => {
          if (r.status === 404) {
            queueItem.timer = setTimeout(() => poll(queueItem), 500);
            return;
          }
          if (!r.ok) return Promise.reject(`${r.status} ${r.statusText}`);
          return r.json();
        })
        .then(data => {
          if (!data) return;
          if (data.error) throw new Error(data.error);
          if (data.done) {
            finishGenerate(queueItem, data.result);
            return;
          }
          if (data.progress && data.progress.image) {
            queueItem.preview = `data:image/jpeg;base64,${data.progress.image}`;
            queueItem.progress = { step: data.progress.step };
            renderHistory();
            if (queueItem === activeJob) {
              renderViewer();
              metaEl.textContent = `Step ${data.progress.step}/${queueItem.totalSteps}`;
              progressEl.value = Math.min(data.progress.step, queueItem.totalSteps);
              progressEl.max = queueItem.totalSteps || 100;
              progressEl.style.display = 'block';
            }
          }
          queueItem.timer = setTimeout(() => poll(queueItem), 500);
        })
        .catch(e => {
          const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
          queueItem.error = msg;
          if (queueItem === activeJob) {
            activeJob = null;
            statusEl.textContent = `Error: ${msg}`;
            statusEl.className = 'status error';
            progressEl.style.display = 'none';
          }
          renderHistory();
          updateGenerateBtn();
          processNext();
        });
    }

    async function generate() {
      saveForm();
      const prompt = $('prompt').value.trim();
      if (!prompt) {
        alert('Please enter a prompt');
        return;
      }
      if (history.filter(i => i.pending).length >= MAX_QUEUE) {
        alert('Queue is full');
        return;
      }
      const body = {
        prompt,
        negative_prompt: $('negative').value,
        width: parseInt($('width').value, 10),
        height: parseInt($('height').value, 10),
        steps: parseInt($('steps').value, 10),
        seed: parseInt($('seed').value, 10),
        strength: parseFloat($('strength').value),
        guidance_scale: parseFloat($('guidance-scale').value),
        guidance_rescale: parseFloat($('guidance-rescale').value)
      };
      const ref = refBase64;
      if (ref) {
        body.image = ref.split(',')[1] || ref;
      }
      if (body.image && body.steps * body.strength < 1) {
        statusEl.textContent = 'Error: for image-to-image, steps × strength must be at least 1';
        statusEl.className = 'status error';
        return;
      }
      const totalSteps = body.image
        ? Math.max(1, Math.floor(body.steps * body.strength))
        : body.steps;
      const queueItem = {
        pending: true,
        submitted: false,
        discarded: false,
        body,
        ref,
        totalSteps,
        prompt: body.prompt,
        negative_prompt: body.negative_prompt,
        width: body.width,
        height: body.height,
        steps: body.steps,
        seed: body.seed,
        strength: body.strength,
        guidance_scale: body.guidance_scale,
        guidance_rescale: body.guidance_rescale,
        time: 0,
        progress: null,
        preview: null,
        error: null,
        job_id: null,
        timer: null
      };
      history.unshift(queueItem);
      queue.push(queueItem);
      activeView = 'generated';
      renderTabs();
      renderHistory();
      updateGenerateBtn();
      if (!activeJob) {
        processNext();
      }
    }

    function processNext() {
      if (activeJob) return;
      if (queue.length === 0) {
        updateGenerateBtn();
        statusEl.textContent = 'Ready';
        statusEl.className = 'status ok';
        progressEl.style.display = 'none';
        return;
      }
      const next = queue.shift();
      activeJob = next;
      statusEl.textContent = 'Generating...';
      statusEl.className = 'status';
      progressEl.value = 0;
      progressEl.max = next.totalSteps || 100;
      progressEl.style.display = 'block';
      updateGenerateBtn();
      renderHistory();
      renderViewer();
      startGenerate(next);
    }

    async function startGenerate(queueItem) {
      queueItem.submitted = true;
      try {
        const r = await fetch(`${API}/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(queueItem.body)
        });
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const data = await r.json();
        queueItem.job_id = data.job_id;
        renderHistory();
        renderViewer();
        poll(queueItem);
      } catch (e) {
        const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
        queueItem.error = msg;
        if (queueItem === activeJob) {
          activeJob = null;
          statusEl.textContent = `Error: ${msg}`;
          statusEl.className = 'status error';
          progressEl.style.display = 'none';
        }
        renderHistory();
        updateGenerateBtn();
        processNext();
      }
    }

    generateBtn.addEventListener('click', generate);
    document.addEventListener('click', () => {
      if (pendingDeleteIndex !== -1) resetDeleteButtons();
    });
    (async () => {
      await loadHistory();
      restoreState();
      checkHealth();
    })();
