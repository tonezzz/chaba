const SITES = [
  { key: "chatgpt", urlMatch: "chatgpt.com", url: "https://chatgpt.com/" },
  { key: "gemini", urlMatch: "gemini.google.com/app", url: "https://gemini.google.com/app" },
  {
    key: "gemini-images",
    urlMatch: "gemini.google.com/images",
    url: "https://gemini.google.com/images",
  },
  { key: "claude", urlMatch: "claude.ai", url: "https://claude.ai/chat" },
  { key: "midjourney", urlMatch: "midjourney.com", url: "https://www.midjourney.com/imagine" },
  {
    key: "aistudio",
    urlMatch: "aistudio.google.com",
    url: "https://aistudio.google.com/prompts/new_chat",
  },
];

chrome.action.onClicked.addListener(() => {
  chrome.sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.cmd === "BROADCAST_PROMPT") {
    broadcast(request)
      .then((results) => sendResponse({ ok: true, results }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (request.cmd === "RESPONSE") {
    chrome.storage.local.get("responses", (r) => {
      const list = Array.isArray(r.responses) ? r.responses : [];
      list.push({ site: request.site, text: request.text, ts: Date.now() });
      chrome.storage.local.set({ responses: list.slice(-20) });
    });
    return false;
  }
  if (request.cmd === "CAPTURE_TRACKED") {
    captureTrackedTabs()
      .then((results) => sendResponse({ ok: true, results }))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }
  if (request.cmd === "NAVIGATE_CAPTURE") {
    navigateAndCapture(request.url, request.slug)
      .then((r) => sendResponse(r))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }
  if (request.cmd === "RELOAD_CONFIG") {
    loadConfig()
      .then((cfg) => sendResponse({ ok: true, recipes: (cfg.recipes || []).length }))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }
  return false;
});

async function sendPrompt(text, siteKey) {
  function setNativeValue(element, value) {
    if (element.isContentEditable) {
      element.focus();
      document.execCommand("selectAll", false, null);
      document.execCommand("insertText", false, value);
      return;
    }
    const isTextArea = element.tagName === "TEXTAREA";
    const proto = isTextArea
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, value);
    } else {
      element.value = value;
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }
  const ADAPTERS = {
    chatgpt: {
      promptSelector: "#prompt-textarea",
      sendSelector: 'button[data-testid="send-button"]',
    },
    gemini: {
      promptSelector: 'div[contenteditable="true"], textarea',
      sendSelector: 'button[aria-label="Send message"]',
    },
    "gemini-images": {
      promptSelector:
        'textarea[placeholder*="image" i], textarea, div[contenteditable="true"], input[type="text"]',
      sendSelector:
        'button[aria-label="Create" i], button[aria-label="Generate" i], button[type="submit"], [data-testid="generate-button"], [data-testid="create-button"]',
    },
    claude: {
      promptSelector: 'div[contenteditable="true"]',
      sendSelector: 'button[aria-label="Send message"], button[aria-label="Send"]',
    },
    midjourney: {
      promptSelector:
        'textarea, input[type="text"], div[contenteditable="true"], [data-testid="prompt-input"], [placeholder*="imagine" i]',
      sendSelector:
        'button[type="submit"], button[aria-label="Imagine"], button[aria-label="Create"], button[aria-label="Generate"], [data-testid="imagine-button"], [data-testid="generate-button"]',
    },
    aistudio: {
      promptSelector:
        'textarea, div[contenteditable="true"], ms-prompt-input-wrapper textarea, [aria-label*="prompt" i]',
      sendSelector:
        'button[aria-label="Run"], button[aria-label*="Run" i], button[title*="Run" i], button[data-testid="run-button"], .run-button',
    },
  };
  const adapter = ADAPTERS[siteKey];
  if (!adapter) return { ok: false, error: "no adapter for " + siteKey };
  const el = document.querySelector(adapter.promptSelector);
  if (!el) return { ok: false, error: "prompt not found", siteKey };
  setNativeValue(el, text);
  // Send buttons are often disabled until the framework processes the
  // input events — poll briefly (re-querying, since React may swap nodes).
  const deadline = Date.now() + 2500;
  let btn = null;
  while (Date.now() < deadline) {
    btn = document.querySelector(adapter.sendSelector);
    if (btn && !btn.disabled) break;
    await new Promise((r) => setTimeout(r, 150));
  }
  if (!btn) return { ok: false, error: "send button not found", siteKey };
  if (btn.disabled) return { ok: false, error: "send button stayed disabled", siteKey };
  btn.click();
  return { ok: true, siteKey };
}

async function broadcast({ text, targets }) {
  const list = targets?.length ? SITES.filter((s) => targets.includes(s.key)) : SITES;

  const results = [];
  for (const site of list) {
    let opened = false;
    try {
      const allTabs = await chrome.tabs.query({});
      const existing = allTabs.find((t) => t.url && t.url.includes(site.urlMatch));
      let tab = existing;
      if (!tab) {
        tab = await chrome.tabs.create({ url: site.url, active: false });
        opened = true;
        await waitForTab(tab.id);
      }
      const res = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: sendPrompt,
        args: [text, site.key],
      });
      const result = res?.[0]?.result;
      if (!result?.ok) throw new Error(result?.error || "unknown");
      results.push({ key: site.key, ok: true, opened });
    } catch (err) {
      results.push({ key: site.key, ok: false, error: String(err.message || err), opened });
    }
  }
  return results;
}

function waitForTab(tabId) {
  return new Promise((resolve) => {
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(resolve, 800);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

const NOTEBOOKLM_URLS = [
  "https://notebooklm.google.com/",
  "https://notebook.google.com/",
  "https://accounts.google.com/",
];

function mapSameSite(value) {
  if (value === "strict") return "Strict";
  if (value === "lax") return "Lax";
  if (value === "no_restriction") return "None";
  return "Lax";
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
    sameSite: mapSameSite(c.sameSite),
  };
}

function getCookiesForUrl(url) {
  return new Promise((resolve, reject) => {
    chrome.cookies.getAll({ url }, (cookies) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(cookies || []);
    });
  });
}

function captureAndSendCookies() {
  chrome.storage.local.get("bridgeUrl", async ({ bridgeUrl }) => {
    const url = (bridgeUrl || "http://127.0.0.1:9876").replace(/\/+$/, "");
    const sets = await Promise.all(NOTEBOOKLM_URLS.map((u) => getCookiesForUrl(u)));
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
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies }),
      });
      const text = await res.text();
      if (res.status === 409) {
        console.log("cookie-bridge refused sync (protected state):", text);
        chrome.storage.local.set({ lastCookieSyncResult: `protected: ${text.slice(0, 80)}` });
      } else if (!res.ok) {
        console.error("cookie-bridge returned", res.status, text);
        chrome.storage.local.set({ lastCookieSyncResult: `error ${res.status}` });
      } else {
        console.log("cookie-bridge updated with", cookies.length, "cookies");
        chrome.storage.local.set({ lastCookieSync: Date.now(), lastCookieSyncResult: "ok" });
      }
    } catch (err) {
      console.error("cookie-bridge error:", err.message);
    }
  });
}

let lastCookieSend = 0;
const COOKIE_SEND_COOLDOWN = 300_000;

function isRelevantCookie(cookie) {
  return cookie && cookie.domain && /(?:^|\.)google\.com$/.test(cookie.domain);
}

chrome.cookies.onChanged.addListener((changeInfo) => {
  if (!isRelevantCookie(changeInfo.cookie)) return;
  const now = Date.now();
  if (now - lastCookieSend < COOKIE_SEND_COOLDOWN) return;
  lastCookieSend = now;
  captureAndSendCookies();
});

// --- Pre-programmed page capture bot -------------------------------------
// Tracked pages are dumped to the local bridge automatically when they
// finish loading, and on demand via CAPTURE_TRACKED from the sidepanel.
// No cookies or auth headers are sent — only visible page contents.
// Config is hot-loaded from the bridge (~/.local/ai-hub/config.json) on every
// alarm tick — adding a page or changing the allowlist needs no Chrome reload.
const DEFAULT_CONFIG = {
  allow_hosts: ["app.devin.ai", "aistudio.google.com", "console.cloud.google.com"],
  recipes: [
    {
      key: "devin_usage_history",
      contains: ["app.devin.ai/", "/settings/usage?tab=history"],
      slug: "devin_usage_history",
    },
    { key: "devin_usage", contains: ["app.devin.ai/", "/settings/usage"], slug: "devin_usage" },
    { key: "devin_billing", contains: ["app.devin.ai/", "/settings/plans"], slug: "devin_billing" },
    {
      key: "gemini_rate_limits",
      contains: ["aistudio.google.com/", "/app/rate-limit"],
      slug: "gemini_rate_limits",
    },
    {
      key: "gcp_quotas",
      contains: ["console.cloud.google.com/", "/iam-admin/quotas"],
      slug: "gcp_quotas",
    },
  ],
};
let activeConfig = DEFAULT_CONFIG;
const CAPTURE_COOLDOWN_MS = 30 * 60 * 1000;
const CAPTURE_RENDER_DELAY_MS = 3000;
const lastCapture = {};

function recipeForUrl(url) {
  const u = String(url || "");
  return (activeConfig.recipes || []).find(
    (r) => (r.contains || []).every((c) => u.includes(c))
  ) || null;
}

async function loadConfig() {
  try {
    const resp = await fetch(`${await bridgeBase()}/config`);
    if (resp.ok) {
      const cfg = await resp.json();
      if (Array.isArray(cfg.recipes) && Array.isArray(cfg.allow_hosts)) {
        activeConfig = cfg;
        await chrome.storage.local.set({ aiHubConfig: cfg });
      }
    }
  } catch (_) {
    // bridge down — keep the last known config
  }
  return activeConfig;
}

(async () => {
  try {
    const r = await chrome.storage.local.get("aiHubConfig");
    if (r.aiHubConfig?.recipes) activeConfig = r.aiHubConfig;
  } catch (_) {}
})();

// Injected verbatim — must be self-contained (no closure references).
function extractPage() {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const rows = [];
  const seen = new Set();
  for (const sel of ["table tbody tr", '[role="row"]', ".mat-row", "tr"]) {
    for (const el of document.querySelectorAll(sel)) {
      const cells = Array.from(
        el.querySelectorAll("th,td,[role='cell'],[role='columnheader']")
      ).map((c) => clean(c.innerText));
      const text = cells.length ? cells.join(" | ") : clean(el.innerText);
      if (!text || seen.has(text)) continue;
      seen.add(text);
      rows.push(text);
      if (rows.length >= 400) break;
    }
    if (rows.length >= 400) break;
  }
  return {
    url: location.href,
    text: clean(document.body ? document.body.innerText : "").slice(0, 200000),
    rows,
  };
}

async function bridgeBase() {
  const r = await chrome.storage.local.get("bridgeUrl");
  return (r.bridgeUrl || "http://127.0.0.1:9876").replace(/\/+$/, "");
}

async function appendCaptureLog(entry) {
  const r = await chrome.storage.local.get("captureLog");
  const list = Array.isArray(r.captureLog) ? r.captureLog : [];
  list.unshift({ ...entry, at: Date.now() });
  await chrome.storage.local.set({ captureLog: list.slice(0, 20) });
}

async function captureTab(tab, recipe, force = false) {
  const key = recipe.key + "|" + tab.id;
  const now = Date.now();
  if (!force && now - (lastCapture[key] || 0) < CAPTURE_COOLDOWN_MS) {
    return { ok: false, recipe: recipe.key, skipped: "cooldown" };
  }
  lastCapture[key] = now;
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPage,
    });
    const page = res?.[0]?.result || {};
    if (!page.text && !(page.rows || []).length) throw new Error("empty page");
    const payload = {
      ...page,
      title: recipe.slug,
      recipe: recipe.key,
      captured_at: new Date().toISOString(),
    };
    const resp = await fetch(`${await bridgeBase()}/page-dump`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const text = await resp.text();
    if (!resp.ok) throw new Error(`${resp.status} ${text.slice(0, 120)}`);
    const out = { ok: true, recipe: recipe.key, slug: recipe.slug, detail: text.slice(0, 200) };
    await appendCaptureLog(out);
    return out;
  } catch (err) {
    const out = { ok: false, recipe: recipe.key, error: String(err.message || err).slice(0, 200) };
    await appendCaptureLog(out);
    return out;
  }
}

async function captureTrackedTabs(force = false) {
  const tabs = await chrome.tabs.query({});
  const results = [];
  for (const tab of tabs) {
    const recipe = recipeForUrl(tab.url);
    if (!recipe) continue;
    results.push(await captureTab(tab, recipe, force));
  }
  return results;
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  const recipe = recipeForUrl(tab.url);
  if (!recipe) return;
  setTimeout(async () => {
    try {
      const fresh = await chrome.tabs.get(tabId);
      if (recipeForUrl(fresh.url)?.key !== recipe.key) return;
      await captureTab(fresh, recipe);
    } catch (_) {
      // tab may have been closed — never let a capture break navigation
    }
  }, CAPTURE_RENDER_DELAY_MS);
});

// --- On-demand command channel -------------------------------------------
// The bridge holds a small commands.json queue; an alarm polls it once a
// minute. This lets an agent ask the extension to open a tracked URL and
// capture it without anyone touching the browser.
function waitForComplete(tabId, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("tab load timed out"));
    }, timeoutMs);
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function navigateAndCapture(url, slug) {
  let target;
  try {
    target = new URL(url);
  } catch (_) {
    return { ok: false, error: "bad url" };
  }
  const allowed = (activeConfig.allow_hosts || []).some(
    (h) => target.hostname === h || target.hostname.endsWith("." + h)
  );
  if (!allowed) {
    return { ok: false, error: `host ${target.hostname} not in hot-config allowlist` };
  }
  const all = await chrome.tabs.query({});
  let tab = all.find((t) => {
    try {
      const x = new URL(t.url);
      return x.host === target.host && x.pathname === target.pathname;
    } catch (_) {
      return false;
    }
  });
  if (tab) {
    await chrome.tabs.update(tab.id, { url, active: false });
  } else {
    tab = await chrome.tabs.create({ url, active: false });
  }
  await waitForComplete(tab.id);
  await new Promise((r) => setTimeout(r, CAPTURE_RENDER_DELAY_MS));
  const res = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: extractPage,
  });
  const page = res?.[0]?.result || {};
  if (!page.text && !(page.rows || []).length) {
    return { ok: false, error: "empty page after navigation" };
  }
  const payload = {
    ...page,
    title: slug || "devin_usage",
    recipe: "command",
    captured_at: new Date().toISOString(),
  };
  const resp = await fetch(`${await bridgeBase()}/page-dump`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const detail = await resp.text();
  if (!resp.ok) return { ok: false, error: `${resp.status} ${detail.slice(0, 120)}` };
  const out = { ok: true, slug: payload.title, url, detail: detail.slice(0, 200) };
  await appendCaptureLog(out);
  return out;
}

let commandBusy = false;
async function pollCommands() {
  if (commandBusy) return;
  commandBusy = true;
  try {
    await loadConfig();
    const base = await bridgeBase();
    const resp = await fetch(`${base}/commands`);
    if (!resp.ok) return;
    const data = await resp.json();
    for (const cmd of data.commands || []) {
      if (cmd.action !== "navigate_capture") continue;
      await navigateAndCapture(cmd.url, cmd.slug);
      await fetch(`${base}/commands/ack`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: cmd.id }),
      });
    }
  } catch (_) {
    // bridge down — keep the queue for the next tick
  } finally {
    commandBusy = false;
  }
}

function ensureCommandAlarm() {
  chrome.alarms.create("aiHubCommandTick", { periodInMinutes: 1 });
}
chrome.runtime.onInstalled.addListener(ensureCommandAlarm);
chrome.runtime.onStartup.addListener(ensureCommandAlarm);
ensureCommandAlarm();
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "aiHubCommandTick") pollCommands();
});
