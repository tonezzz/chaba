const API = './api';

export function imageUrl(path) {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('data:')) return path;
  return `${API}/${path.replace(/^\/+/, '')}`;
}

export async function checkHealth() {
  const r = await fetch(`${API}/health`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function loadHistory() {
  try {
    const r = await fetch(`${API}/history`);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const data = await r.json();
    if (Array.isArray(data.history)) return data.history;
    if (data.history && typeof data.history === 'object') return Object.values(data.history);
    return [];
  } catch (e) {
    console.error('Failed to load history:', e);
    return [];
  }
}

export async function loadHistoryItem(id) {
  const r = await fetch(`${API}/history/${id}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function deleteHistory(id) {
  const r = await fetch(`${API}/history/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function postGenerate(body) {
  const r = await fetch(`${API}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function fetchProgress(jobId) {
  const r = await fetch(`${API}/progress/${jobId}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
