const promptInput = document.getElementById('prompt');
const sendBtn = document.getElementById('send');
const responsesDiv = document.getElementById('responses');

function selectedTargets() {
  return Array.from(document.querySelectorAll('.chip.active')).map(c => c.dataset.value);
}

const CHIP_URLMATCH = {
  chatgpt: 'chatgpt.com',
  gemini: 'gemini.google.com/app',
  'gemini-images': 'gemini.google.com/images',
  claude: 'claude.ai',
  midjourney: 'midjourney.com',
  aistudio: 'aistudio.google.com'
};

async function markOpenChips() {
  const tabs = await chrome.tabs.query({});
  document.querySelectorAll('.chip').forEach(chip => {
    const m = CHIP_URLMATCH[chip.dataset.value];
    chip.classList.toggle('has-tab', !!(m && tabs.some(t => t.url && t.url.includes(m))));
  });
}
markOpenChips();
chrome.tabs.onActivated.addListener(markOpenChips);
chrome.tabs.onUpdated.addListener(markOpenChips);
chrome.tabs.onRemoved.addListener(markOpenChips);

chrome.storage.local.get('selectedTargets', r => {
  if (Array.isArray(r.selectedTargets)) {
    document.querySelectorAll('.chip').forEach(c => {
      c.classList.toggle('active', r.selectedTargets.includes(c.dataset.value));
    });
  }
});

document.getElementById('targetChips').addEventListener('click', (e) => {
  if (e.target.classList.contains('chip')) {
    e.target.classList.toggle('active');
    chrome.storage.local.set({ selectedTargets: selectedTargets() });
  }
});

const tabStatus = document.getElementById('tabStatus');
const SITE_LABELS = [
  { label: 'ChatGPT', urlMatch: 'chatgpt.com' },
  { label: 'Gemini', urlMatch: 'gemini.google.com/app' },
  { label: 'Gemini Images', urlMatch: 'gemini.google.com/images' },
  { label: 'Claude', urlMatch: 'claude.ai' },
  { label: 'Midjourney', urlMatch: 'midjourney.com' },
  { label: 'AI Studio', urlMatch: 'aistudio.google.com' }
];

async function updateTabStatus() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) {
    tabStatus.textContent = 'Active tab: —';
    return;
  }
  const site = tab.url ? SITE_LABELS.find(s => tab.url.includes(s.urlMatch)) : null;
  const short = tab.title || tab.url || '—';
  tabStatus.textContent = site ? `Active: ${site.label} — ${short}` : `Active: ${short}`;
}

chrome.tabs.onActivated.addListener(updateTabStatus);
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url || changeInfo.title || changeInfo.status === 'complete') {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      if (tabs[0] && tabs[0].id === tabId) updateTabStatus();
    });
  }
});
window.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') updateTabStatus(); });
updateTabStatus();

const bridgeStatus = document.getElementById('bridgeStatus');

async function checkBridge() {
  const url = (bridgeUrlInput.value.trim() || 'http://127.0.0.1:9876').replace(/\/+$/, '');
  const storage = await chrome.storage.local.get('lastCookieSync');
  const syncText = storage.lastCookieSync
    ? `Last cookie sync: ${new Date(storage.lastCookieSync).toLocaleTimeString()}`
    : 'No cookie sync yet';
  try {
    const res = await fetch(`${url}/health`);
    if (res.ok) bridgeStatus.textContent = `Bridge online — ${syncText}`;
    else bridgeStatus.textContent = `Bridge error ${res.status} — ${syncText}`;
  } catch (err) {
    bridgeStatus.textContent = `Bridge offline — ${syncText}`;
  }
}

bridgeUrlInput.addEventListener('input', () => { saveSettings(); checkBridge(); });
setInterval(checkBridge, 10000);
checkBridge();

document.querySelectorAll('.bridge-preset').forEach(btn => {
  btn.addEventListener('click', () => {
    bridgeUrlInput.value = btn.dataset.bridge;
    saveSettings();
    checkBridge();
  });
});

const sendStatus = document.getElementById('sendStatus');
const clearResponsesBtn = document.getElementById('clearResponsesBtn');

function setBusy(btn, label) {
  btn.dataset.label = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
}
function clearBusy(btn) {
  btn.disabled = false;
  if (btn.dataset.label) btn.textContent = btn.dataset.label;
}

const MAX_STORED_RESPONSES = 20;

function appendResponse(site, text, ts, persist = true) {
  const div = document.createElement('div');
  div.className = 'response';
  const h = document.createElement('h3');
  h.textContent = site;
  const time = document.createElement('span');
  time.className = 'resp-time';
  time.textContent = new Date(ts || Date.now()).toLocaleTimeString();
  const pre = document.createElement('pre');
  pre.textContent = text;
  div.append(h, time, pre);
  responsesDiv.appendChild(div);
  if (persist) {
    chrome.storage.local.get('responses', r => {
      const list = Array.isArray(r.responses) ? r.responses : [];
      list.push({ site, text, ts: ts || Date.now() });
      chrome.storage.local.set({ responses: list.slice(-MAX_STORED_RESPONSES) });
    });
  }
}

chrome.storage.local.get('responses', r => {
  if (Array.isArray(r.responses)) {
    for (const resp of r.responses) appendResponse(resp.site, resp.text, resp.ts, false);
  }
});

clearResponsesBtn.addEventListener('click', () => {
  responsesDiv.innerHTML = '';
  chrome.storage.local.remove('responses');
});

function sendPrompt() {
  const text = promptInput.value.trim();
  if (!text) return;
  const targets = selectedTargets();
  if (!targets.length) {
    sendStatus.textContent = 'No targets selected.';
    return;
  }
  setBusy(sendBtn, 'Sending…');
  sendStatus.textContent = '';
  chrome.runtime.sendMessage({ cmd: 'BROADCAST_PROMPT', text, targets }, (resp) => {
    clearBusy(sendBtn);
    if (chrome.runtime.lastError) {
      sendStatus.textContent = `Error: ${chrome.runtime.lastError.message}`;
      return;
    }
    if (!resp || !resp.ok) {
      sendStatus.textContent = `Failed: ${resp?.error || 'unknown'}`;
      return;
    }
    const parts = resp.results.map(r =>
      r.ok ? `${r.key}${r.opened ? ' (opened tab)' : ''}` : `${r.key}: ${r.error}`);
    const okCount = resp.results.filter(r => r.ok).length;
    sendStatus.textContent = `Sent ${okCount}/${resp.results.length} — ${parts.join(' · ')}`;
  });
}

sendBtn.addEventListener('click', sendPrompt);

promptInput.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault();
    sendPrompt();
  }
});

// Saved prompts
const savedPromptsSelect = document.getElementById('savedPrompts');
const savePromptBtn = document.getElementById('savePromptBtn');
const delPromptBtn = document.getElementById('delPromptBtn');
const MAX_SAVED_PROMPTS = 20;

function renderSavedPrompts(list) {
  savedPromptsSelect.innerHTML = '<option value="">Saved prompts…</option>';
  list.forEach((p, i) => {
    const opt = document.createElement('option');
    opt.value = String(i);
    opt.textContent = p.length > 60 ? p.slice(0, 60) + '…' : p;
    savedPromptsSelect.appendChild(opt);
  });
}

chrome.storage.local.get('savedPrompts', r => {
  renderSavedPrompts(Array.isArray(r.savedPrompts) ? r.savedPrompts : []);
});

savePromptBtn.addEventListener('click', () => {
  const text = promptInput.value.trim();
  if (!text) return;
  chrome.storage.local.get('savedPrompts', r => {
    let list = Array.isArray(r.savedPrompts) ? r.savedPrompts : [];
    list = list.filter(p => p !== text);
    list.unshift(text);
    list = list.slice(0, MAX_SAVED_PROMPTS);
    chrome.storage.local.set({ savedPrompts: list }, () => renderSavedPrompts(list));
  });
});

savedPromptsSelect.addEventListener('change', () => {
  const i = Number(savedPromptsSelect.value);
  if (savedPromptsSelect.value === '') return;
  chrome.storage.local.get('savedPrompts', r => {
    const list = Array.isArray(r.savedPrompts) ? r.savedPrompts : [];
    if (list[i] != null) promptInput.value = list[i];
  });
});

delPromptBtn.addEventListener('click', () => {
  const i = Number(savedPromptsSelect.value);
  if (savedPromptsSelect.value === '') return;
  chrome.storage.local.get('savedPrompts', r => {
    const list = Array.isArray(r.savedPrompts) ? r.savedPrompts : [];
    list.splice(i, 1);
    chrome.storage.local.set({ savedPrompts: list }, () => renderSavedPrompts(list));
  });
});

chrome.runtime.onMessage.addListener(request => {
  if (request.cmd === 'RESPONSE') {
    appendResponse(request.site, request.text);
  }
});

const bridgeUrlInput = document.getElementById('bridgeUrl');
const captureCookiesBtn = document.getElementById('captureCookies');
const copyCookiesBtn = document.getElementById('copyCookies');
const sendCookiesBtn = document.getElementById('sendCookies');
const cookieStatus = document.getElementById('cookieStatus');
let lastCookiesJson = '';

const nbApiKeyInput = document.getElementById('nbApiKey');
const nbBaseUrlInput = document.getElementById('nbBaseUrl');
const nbNotebookIdInput = document.getElementById('nbNotebookId');
const nbListBtn = document.getElementById('nbListBtn');
const nbUploadBtn = document.getElementById('nbUploadBtn');
const nbStatus = document.getElementById('nbStatus');
const notebookListSelect = document.getElementById('notebookList');

const STORAGE_KEYS = ['bridgeUrl', 'nbApiKey', 'nbBaseUrl', 'nbNotebookId'];
chrome.storage.local.get(STORAGE_KEYS, (r) => {
  if (r.bridgeUrl) bridgeUrlInput.value = r.bridgeUrl;
  if (r.nbApiKey) nbApiKeyInput.value = r.nbApiKey;
  if (r.nbBaseUrl) nbBaseUrlInput.value = r.nbBaseUrl;
  if (r.nbNotebookId) nbNotebookIdInput.value = r.nbNotebookId;
});

function saveSettings() {
  chrome.storage.local.set({
    bridgeUrl: bridgeUrlInput.value,
    nbApiKey: nbApiKeyInput.value,
    nbBaseUrl: nbBaseUrlInput.value,
    nbNotebookId: nbNotebookIdInput.value
  });
}

bridgeUrlInput.addEventListener('input', saveSettings);
nbApiKeyInput.addEventListener('input', saveSettings);
nbBaseUrlInput.addEventListener('input', saveSettings);
nbNotebookIdInput.addEventListener('input', saveSettings);

const NOTEBOOKLM_URLS = [
  'https://notebooklm.google.com/',
  'https://notebook.google.com/',
  'https://accounts.google.com/'
];

function mapSameSite(value) {
  if (value === 'strict') return 'Strict';
  if (value === 'lax') return 'Lax';
  if (value === 'no_restriction') return 'None';
  return 'Lax';
}

function formatCookie(c) {
  return {
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    expires: c.expirationDate ? Math.floor(c.expirationDate) : -1,
    httpOnly: !!c.httpOnly,
    secure: !!c.secure,
    sameSite: mapSameSite(c.sameSite)
  };
}

function getCookiesForUrl(url) {
  if (!chrome.cookies) {
    throw new Error('chrome.cookies is not available. Please reload the AI Hub extension from chrome://extensions.');
  }
  return new Promise((resolve, reject) => {
    chrome.cookies.getAll({ url }, cookies => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(cookies || []);
    });
  });
}

async function captureNotebooklmCookies() {
  const sets = await Promise.all(NOTEBOOKLM_URLS.map(url => getCookiesForUrl(url)));
  const seen = new Set();
  const cookies = [];
  for (const set of sets) {
    for (const c of set) {
      const key = `${c.name}|${c.domain}|${c.path}`;
      if (seen.has(key)) continue;
      seen.add(key);
      cookies.push(formatCookie(c));
    }
  }
  lastCookiesJson = JSON.stringify({ cookies }, null, 2);
  cookieStatus.textContent = `Captured ${cookies.length} cookies.`;
}

captureCookiesBtn.addEventListener('click', () => {
  setBusy(captureCookiesBtn, 'Capturing…');
  captureNotebooklmCookies()
    .catch(err => cookieStatus.textContent = `Error: ${err.message}`)
    .finally(() => clearBusy(captureCookiesBtn));
});

copyCookiesBtn.addEventListener('click', () => {
  if (!lastCookiesJson) return cookieStatus.textContent = 'Capture first.';
  navigator.clipboard.writeText(lastCookiesJson).then(() => cookieStatus.textContent = 'Copied to clipboard.');
});

sendCookiesBtn.addEventListener('click', async () => {
  if (!lastCookiesJson) return cookieStatus.textContent = 'Capture first.';
  const url = (bridgeUrlInput.value.trim() || 'http://127.0.0.1:9876').replace(/\/+$/, '');
  setBusy(sendCookiesBtn, 'Sending…');
  try {
    const res = await fetch(`${url}/cookies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: lastCookiesJson
    });
    const text = await res.text();
    cookieStatus.textContent = res.ok ? `Bridge: ${text}` : `Bridge error ${res.status}: ${text}`;
  } catch (err) {
    cookieStatus.textContent = `Bridge unreachable: ${err.message}`;
  } finally {
    clearBusy(sendCookiesBtn);
  }
});

function getNbConfig() {
  return {
    nbApiKey: nbApiKeyInput.value.trim(),
    nbBaseUrl: nbBaseUrlInput.value.trim().replace(/\/+$/, '')
  };
}

nbListBtn.addEventListener('click', async () => {
  const { nbApiKey, nbBaseUrl } = getNbConfig();
  if (!nbApiKey || !nbBaseUrl) return nbStatus.textContent = 'Set API key and base URL.';
  setBusy(nbListBtn, 'Loading…');
  try {
    const res = await fetch(`${nbBaseUrl}/v1/notebooks`, { headers: { 'X-API-Key': nbApiKey } });
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    const notebooks = data.items || data.notebooks || data;
    populateNotebookList(notebooks);
    nbStatus.textContent = `Loaded ${notebooks.length} notebooks.`;
  } catch (err) {
    nbStatus.textContent = `List failed: ${err.message}`;
  } finally {
    clearBusy(nbListBtn);
  }
});

const nbAuthBtn = document.getElementById('nbAuthBtn');
nbAuthBtn.addEventListener('click', async () => {
  const { nbApiKey, nbBaseUrl } = getNbConfig();
  if (!nbApiKey || !nbBaseUrl) return nbStatus.textContent = 'Set API key and base URL.';
  setBusy(nbAuthBtn, 'Checking…');
  try {
    const res = await fetch(`${nbBaseUrl}/health/auth`, { headers: { 'X-API-Key': nbApiKey } });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.auth === 'ok') {
      const acct = data.probe?.account?.email || '';
      nbStatus.textContent = `Session OK${acct ? ` (${acct})` : ''} — master_token: ${data.probe?.master_token?.present ? 'yes' : 'no'}`;
    } else {
      nbStatus.textContent = `Session problem ${res.status}: ${data.detail || data.auth || 'unknown'}`;
    }
  } catch (err) {
    nbStatus.textContent = `Auth check error: ${err.message}`;
  } finally {
    clearBusy(nbAuthBtn);
  }
});

function populateNotebookList(notebooks) {
  notebookListSelect.innerHTML = '<option value="">Select notebook</option>';
  for (const nb of notebooks) {
    const opt = document.createElement('option');
    opt.value = nb.id || nb.guid;
    opt.textContent = nb.title || nb.name || nb.id;
    notebookListSelect.appendChild(opt);
  }
}

notebookListSelect.addEventListener('change', () => {
  if (notebookListSelect.value) {
    nbNotebookIdInput.value = notebookListSelect.value;
    saveSettings();
  }
});

nbUploadBtn.addEventListener('click', async () => {
  const { nbApiKey, nbBaseUrl } = getNbConfig();
  const notebookId = nbNotebookIdInput.value.trim();
  if (!nbApiKey || !nbBaseUrl || !notebookId) return nbStatus.textContent = 'Set API key, base URL and notebook ID.';
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return nbStatus.textContent = 'No active tab.';
  setBusy(nbUploadBtn, 'Uploading…');
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({ title: document.title, url: location.href, text: document.body.innerText.slice(0, 200_000) })
    });
    const { title, url, text } = result[0].result;
    const payload = { title: `From: ${title}`, content: `${url}\n\n${text}` };
    const res = await fetch(`${nbBaseUrl}/v1/notebooks/${notebookId}/sources/text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': nbApiKey },
      body: JSON.stringify(payload)
    });
    const out = await res.text();
    nbStatus.textContent = res.ok ? `Uploaded: ${res.status} ${out}` : `Upload failed ${res.status}: ${out}`;
  } catch (err) {
    nbStatus.textContent = `Upload error: ${err.message}`;
  } finally {
    clearBusy(nbUploadBtn);
  }
});

function captureDebugInfo(site) {
  function getCssPath(el) {
    if (!el) return '';
    const parts = [];
    while (el && el.nodeType === 1) {
      let name = el.nodeName.toLowerCase();
      if (el.id) { name += '#' + el.id; parts.unshift(name); break; }
      let sib = el, nth = 1;
      while (sib = sib.previousElementSibling) { if (sib.nodeName.toLowerCase() === name) nth++; }
      if (nth > 1 || el.nextElementSibling) name += `:nth-of-type(${nth})`;
      parts.unshift(name);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }
  function rectObj(r) {
    return r ? { x: r.x, y: r.y, width: r.width, height: r.height, top: r.top, right: r.right, bottom: r.bottom, left: r.left } : null;
  }
  const ADAPTERS = {
    'midjourney.com': {
      promptSelector: 'textarea, input[type="text"], div[contenteditable="true"], [data-testid="prompt-input"], [placeholder*="imagine" i]',
      sendSelector: 'button[type="submit"], button[aria-label="Imagine"], button[aria-label="Create"], button[aria-label="Generate"], [data-testid="imagine-button"], [data-testid="generate-button"]'
    }
  };
  const host = location.hostname;
  const matched = Object.keys(ADAPTERS).find(h => host === h || host.endsWith('.' + h));
  const adapter = matched ? ADAPTERS[matched] : null;
  const el = adapter ? document.querySelector(adapter.promptSelector) : null;
  const btn = adapter ? document.querySelector(adapter.sendSelector) : null;
  const result = {
    site, host, url: location.href, matched,
    prompt: { found: !!el, selector: getCssPath(el), html: el ? el.outerHTML.slice(0, 500) : '', rect: rectObj(el ? el.getBoundingClientRect() : null) },
    send: { found: !!btn, selector: getCssPath(btn), html: btn ? btn.outerHTML.slice(0, 500) : '', rect: rectObj(btn ? btn.getBoundingClientRect() : null) }
  };
  if (!adapter) {
    const describe = e => ({ selector: getCssPath(e), html: e.outerHTML.slice(0, 200) });
    result.candidates = {
      inputs: Array.from(document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]')).slice(0, 8).map(describe),
      buttons: Array.from(document.querySelectorAll('button[aria-label], button[type="submit"], [role="button"][aria-label]')).slice(0, 8).map(describe)
    };
  }
  return result;
}

const debugCaptureBtn = document.getElementById('debugCaptureBtn');
const debugStatus = document.getElementById('debugStatus');

debugCaptureBtn.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return debugStatus.textContent = 'No active tab.';
  setBusy(debugCaptureBtn, 'Capturing…');
  let debug = {};
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: captureDebugInfo,
      args: [tab.url]
    });
    debug = res?.[0]?.result || { error: 'no result from executeScript' };
  } catch (err) {
    debugStatus.textContent = `Script injection failed for ${tab.url}: ${err.message}`;
    console.error('debug capture error:', err);
    clearBusy(debugCaptureBtn);
    return;
  }
  debugStatus.textContent = `Debug captured: prompt=${debug.prompt?.found}, send=${debug.send?.found}. Sending to bridge...`;
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(chrome.windows.WINDOW_ID_CURRENT, { format: 'png' });
    const url = (bridgeUrlInput.value.trim() || 'http://127.0.0.1:9876').replace(/\/+$/, '');
    const res = await fetch(`${url}/debug-screenshot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imageData: dataUrl, debug })
    });
    const text = await res.text();
    debugStatus.textContent = res.ok ? text : `Debug save failed: ${res.status} ${text}`;
  } catch (err) {
    debugStatus.textContent = `Capture error: ${err.message}`;
  } finally {
    clearBusy(debugCaptureBtn);
  }
});

const dumpPageBtn = document.getElementById('dumpPageBtn');

dumpPageBtn.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return debugStatus.textContent = 'No active tab.';
  setBusy(dumpPageBtn, 'Dumping…');
  let page = {};
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        url: location.href,
        title: document.title,
        text: document.body ? document.body.innerText : '',
        fields: Array.from(document.querySelectorAll('input,select,textarea')).map(el => ({
          tag: el.tagName.toLowerCase(),
          type: el.type || '',
          id: el.id || '',
          name: el.name || '',
          value: el.type === 'password'
            ? (el.value ? '(set)' : '')
            : (el.tagName === 'SELECT' ? (el.options[el.selectedIndex] || {}).text : el.value),
          checked: typeof el.checked === 'boolean' ? el.checked : undefined
        })),
        html: document.documentElement ? document.documentElement.outerHTML : ''
      })
    });
    page = res?.[0]?.result || {};
    if (!page.text && !page.html) throw new Error('empty result');
  } catch (err) {
    debugStatus.textContent = `Script injection failed for ${tab.url}: ${err.message}`;
    return;
  }
  try {
    const url = (bridgeUrlInput.value.trim() || 'http://127.0.0.1:9876').replace(/\/+$/, '');
    const res = await fetch(`${url}/page-dump`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(page)
    });
    const text = await res.text();
    debugStatus.textContent = res.ok ? `Dumped ${page.text.length} chars: ${text}` : `Dump failed: ${res.status} ${text}`;
  } catch (err) {
    debugStatus.textContent = `Dump error: ${err.message}`;
  } finally {
    clearBusy(dumpPageBtn);
  }
});
