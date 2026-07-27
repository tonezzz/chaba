const API = './api';

export async function checkHealth() {
  const r = await fetch(`${API}/health`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return await r.json();
}

export async function loadHistory() {
  try {
    const r = await fetch(`${API}/history`);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const data = await r.json();
    return Array.isArray(data.history) ? data.history : [];
  } catch (e) {
    console.error('Failed to load history:', e);
    return [];
  }
}

export async function saveHistory(history, max = 12) {
  const payload = { history: history.filter(i => !i.pending).slice(0, max) };
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

export async function postGenerate(body) {
  const r = await fetch(`${API}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return await r.json();
}

export async function fetchProgress(jobId) {
  const r = await fetch(`${API}/progress/${jobId}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return await r.json();
}

export async function downloadUpscaled(currentB64, scale) {
  const r = await fetch(`${API}/upscale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image: currentB64, scale: parseInt(scale, 10), fmt: 'png' })
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return await r.json();
}
