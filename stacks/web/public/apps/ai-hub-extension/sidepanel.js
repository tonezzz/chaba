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

chrome.storage.local.get('bridgeUrl', ({ bridgeUrl }) => {
  if (bridgeUrl) bridgeUrlInput.value = bridgeUrl;
});

bridgeUrlInput.addEventListener('input', () => {
  chrome.storage.local.set({ bridgeUrl: bridgeUrlInput.value });
});

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
