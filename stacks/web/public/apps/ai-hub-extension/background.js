const SITES = [
  { host: 'chatgpt.com', url: 'https://chatgpt.com/' },
  { host: 'gemini.google.com', url: 'https://gemini.google.com/app' },
  { host: 'claude.ai', url: 'https://claude.ai/chat' }
];

chrome.action.onClicked.addListener(() => {
  chrome.sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.cmd === 'BROADCAST_PROMPT') {
    broadcast(request)
      .then(() => sendResponse({ ok: true }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  return false;
});

async function broadcast({ text, targets }) {
  const list = targets?.length
    ? SITES.filter(s => targets.includes(s.host))
    : SITES;

  for (const site of list) {
    const tabs = await chrome.tabs.query({ url: `https://${site.host}/*` });
    const tab = tabs[0] || await chrome.tabs.create({ url: site.url, active: false });
    await waitForTab(tab.id);
    try {
      await chrome.tabs.sendMessage(tab.id, { cmd: 'SEND', text });
    } catch (err) {
      console.error(`Failed to message ${site.host}:`, err);
    }
  }
}

function waitForTab(tabId) {
  return new Promise(resolve => {
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(resolve, 500);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

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
  return new Promise((resolve, reject) => {
    chrome.cookies.getAll({ url }, cookies => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(cookies || []);
    });
  });
}

function captureAndSendCookies() {
  chrome.storage.local.get('bridgeUrl', async ({ bridgeUrl }) => {
    const url = (bridgeUrl || 'http://127.0.0.1:9876').replace(/\/+$/, '');
    const sets = await Promise.all(NOTEBOOKLM_URLS.map(u => getCookiesForUrl(u)));
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
    try {
      const res = await fetch(`${url}/cookies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookies })
      });
      if (!res.ok) console.error('cookie-bridge returned', res.status, await res.text());
      else console.log('cookie-bridge updated with', cookies.length, 'cookies');
    } catch (err) {
      console.error('cookie-bridge error:', err.message);
    }
  });
}

let lastCookieSend = 0;
const COOKIE_SEND_COOLDOWN = 60_000;

function isRelevantCookie(cookie) {
  return cookie && cookie.domain && /(?:^|\.)google\.com$/.test(cookie.domain);
}

chrome.cookies.onChanged.addListener(changeInfo => {
  if (!isRelevantCookie(changeInfo.cookie)) return;
  const now = Date.now();
  if (now - lastCookieSend < COOKIE_SEND_COOLDOWN) return;
  lastCookieSend = now;
  captureAndSendCookies();
});
