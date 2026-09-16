const promptInput = document.getElementById('prompt');
const sendBtn = document.getElementById('send');
const responsesDiv = document.getElementById('responses');
const checkboxes = document.querySelectorAll('.targets input');

function selectedTargets() {
  return Array.from(checkboxes).filter(c => c.checked).map(c => c.value);
}

function appendResponse(site, text) {
  const div = document.createElement('div');
  div.className = 'response';
  div.innerHTML = `<h3>${site}</h3><pre>${text}</pre>`;
  responsesDiv.appendChild(div);
}

sendBtn.addEventListener('click', () => {
  const text = promptInput.value.trim();
  if (!text) return;
  const targets = selectedTargets();
  chrome.runtime.sendMessage({ cmd: 'BROADCAST_PROMPT', text, targets });
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
  captureNotebooklmCookies().catch(err => cookieStatus.textContent = `Error: ${err.message}`);
});

copyCookiesBtn.addEventListener('click', () => {
  if (!lastCookiesJson) return cookieStatus.textContent = 'Capture first.';
  navigator.clipboard.writeText(lastCookiesJson).then(() => cookieStatus.textContent = 'Copied to clipboard.');
});

sendCookiesBtn.addEventListener('click', async () => {
  if (!lastCookiesJson) return cookieStatus.textContent = 'Capture first.';
  const url = (bridgeUrlInput.value.trim() || 'http://127.0.0.1:9876').replace(/\/+$/, '');
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
  try {
    const res = await fetch(`${nbBaseUrl}/v1/notebooks`, { headers: { 'X-API-Key': nbApiKey } });
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    const notebooks = data.notebooks || data;
    populateNotebookList(notebooks);
    nbStatus.textContent = `Loaded ${notebooks.length} notebooks.`;
  } catch (err) {
    nbStatus.textContent = `List failed: ${err.message}`;
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
  return {
    site, host, url: location.href, matched,
    prompt: { found: !!el, selector: getCssPath(el), html: el ? el.outerHTML.slice(0, 500) : '', rect: rectObj(el ? el.getBoundingClientRect() : null) },
    send: { found: !!btn, selector: getCssPath(btn), html: btn ? btn.outerHTML.slice(0, 500) : '', rect: rectObj(btn ? btn.getBoundingClientRect() : null) }
  };
}

const debugCaptureBtn = document.getElementById('debugCaptureBtn');
const debugStatus = document.getElementById('debugStatus');

debugCaptureBtn.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return debugStatus.textContent = 'No active tab.';
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
  }
});
