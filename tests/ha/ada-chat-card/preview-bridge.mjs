#!/usr/bin/env node
/**
 * preview-bridge.mjs — run the ada-chat-card harness through OpenChamber
 * Preview (the browser-control plane) and collect durable evidence.
 *
 * How it works
 * ------------
 * OpenChamber's builtin browser provider is a broker: agent `browser.*`
 * actions POST to /api/openchamber/control, the broker emits an SSE
 * `openchamber:browser-control-request` to browser-capable UI clients
 * (GET /api/openchamber/events?browser=1), and the client claims +
 * executes + posts /api/browser-control/result.
 *
 * With no desktop client connected the broker 503s. This script IS the
 * missing client: it connects the SSE stream, registers via
 * /api/browser-control/active, claims requests, and executes them in a
 * real headless Chrome (Playwright, channel:"chrome") — the same engine
 * the desktop BrowserPane drives. Every browser action therefore travels
 * the real OpenChamber Preview control plane; only the renderer is
 * headless instead of an on-screen panel.
 *
 * Usage:
 *   node preview-bridge.mjs [--spawn-server] [--scenario all|key]
 *                           [--oc-url http://127.0.0.1:3000]
 *                           [--server-url http://127.0.0.1:8777]
 *                           [--evidence tests/ha/ada-chat-card/evidence]
 *                           [--direct]        # bypass OpenChamber (debug)
 *
 * Requires: node >= 20, playwright module (PLAYWRIGHT_MODULE or
 * ~/.local/playlive/node_modules/playwright), system Chrome, and for the
 * preview path an OpenChamber server + its uiPassword in
 * ~/.config/openchamber/run/openchamber-<port>.json.
 */
import http from "node:http";
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

/* ---------------- args ---------------- */
const args = {};
for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i];
  if (a === "--direct") args.direct = true;
  else if (a === "--spawn-server") args.spawnServer = true;
  else if (a.startsWith("--")) args[a.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = process.argv[++i];
}
const HERE = path.dirname(new URL(import.meta.url).pathname);
const WT = path.resolve(HERE, "..", "..", "..");
const EVIDENCE = path.resolve(args.evidence || path.join(HERE, "evidence"));
const SHOTS = path.join(EVIDENCE, "shots");
const OC_URL = args.ocUrl || "http://127.0.0.1:3000";
const RUN_FILE = args.runFile || path.join(os.homedir(), ".config/openchamber/run/openchamber-3000.json");
const SCENARIO = args.scenario || "all";
const SCENARIOS = ["connect", "text-urls", "push-image", "push-video", "push-mixed",
  "push-empty", "push-broken", "push-nonhttp", "stream-rerender", "click-open",
  "download-link", "qc-panel", "mobile-layout"];

const log = (...a) => console.log("[preview-bridge]", ...a);
const die = (msg) => { console.error("[preview-bridge] FATAL:", msg); process.exit(2); };

/* ---------------- playwright ---------------- */
async function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    path.join(os.homedir(), ".local/playlive/node_modules/playwright"),
    path.join(os.homedir(), "CascadeProjects/chaba/node_modules/playwright"),
  ].filter(Boolean);
  for (const c of candidates) {
    for (const entry of [c, path.join(c, "index.mjs"), path.join(c, "index.js")]) {
      try { return await import(pathToFileURL(entry).href); }
      catch { try { return await import(entry); } catch {} }
    }
  }
  try { return await import("playwright"); } catch {}
  die("playwright module not found (set PLAYWRIGHT_MODULE)");
}
const { chromium } = await loadPlaywright();

/* ---------------- fixture server ---------------- */
let serverProc = null;
let serverUrl = args.serverUrl || "http://127.0.0.1:8777";
async function ensureServer() {
  try {
    const r = await fetch(`${serverUrl}/tests/ha/ada-chat-card/harness.html`);
    if (r.ok) { log(`fixture server already up: ${serverUrl}`); return; }
  } catch {}
  if (!args.spawnServer) die(`fixture server not reachable at ${serverUrl} (use --spawn-server)`);
  const port = new URL(serverUrl).port || "8777";
  serverProc = spawn("python3", [path.join(HERE, "server.py"), "--port", port], { stdio: "ignore" });
  for (let i = 0; i < 50; i++) {
    await new Promise(r => setTimeout(r, 200));
    try {
      const r = await fetch(`${serverUrl}/tests/ha/ada-chat-card/harness.html`);
      if (r.ok) { log(`spawned fixture server: ${serverUrl}`); return; }
    } catch {}
  }
  die("fixture server did not come up");
}

/* ---------------- openchamber auth + sse ---------------- */
function ocPassword() {
  if (process.env.OC_UI_PASSWORD) return process.env.OC_UI_PASSWORD;
  if (!existsSync(RUN_FILE)) die(`no OpenChamber run file at ${RUN_FILE}`);
  const j = JSON.parse(readFileSync(RUN_FILE, "utf8"));
  if (!j.uiPassword) die(`run file ${RUN_FILE} has no uiPassword`);
  return j.uiPassword;
}
let cookie = "";
async function ocFetch(p, opts = {}) {
  const u = new URL(p, OC_URL);
  const res = await fetch(u, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(cookie ? { cookie } : {}) },
    redirect: "manual",
  });
  const sc = res.headers.getSetCookie?.() || [];
  if (sc.length) cookie = sc.map(c => c.split(";", 1)[0]).join("; ");
  return res;
}
async function ocLogin() {
  const res = await ocFetch("/auth/session", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ password: ocPassword() }),
  });
  const j = await res.json().catch(() => ({}));
  if (!j.authenticated) die(`OpenChamber login failed (HTTP ${res.status})`);
  log("openchamber session authenticated");
}
async function ocControl(action, input = {}) {
  const res = await ocFetch("/api/openchamber/control", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, input }),
  });
  const j = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  return j;
}

/* ---------------- playwright page ---------------- */
const VIEWPORTS = {
  mobile: { width: 390, height: 844 },    // iPhone 14 — same preset as the pane
  tablet: { width: 768, height: 1024 },   // iPad mini
  desktop: { width: 1440, height: 900 },  // Desktop
};
let browser = null, context = null, page = null;
let viewportMode = "desktop";
const pwConsole = [];   // playwright-side console/pageerror/http problems
let refMap = new Map(); // eN -> cssPath from last snapshot

function pushPw(kind, entry) {
  pwConsole.push({ kind, ...entry, at: Date.now() });
  if (pwConsole.length > 200) pwConsole.splice(0, pwConsole.length - 200);
}

async function ensureBrowser() {
  if (browser) return;
  try {
    browser = await chromium.launch({ channel: "chrome", headless: true });
  } catch {
    browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true });
  }
  context = await browser.newContext({ viewport: VIEWPORTS.desktop });
  page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") {
      // for resource-load failures location().url is the failing asset,
      // not the page — keep it so broken-fixture errors classify correctly
      const loc = m.location?.();
      pushPw(`console.${m.type()}`, { text: m.text().slice(0, 400), url: loc?.url || page.url() });
    }
  });
  page.on("pageerror", (e) => pushPw("pageerror", { text: String(e.message || e).slice(0, 400), url: page.url() }));
  page.on("requestfailed", (r) => pushPw("requestfailed", { text: `${r.url()} ${r.failure()?.errorText || ""}`, url: r.url() }));
  page.on("response", (r) => {
    if (r.status() >= 400) pushPw("http", { text: `HTTP ${r.status()} ${r.url()}`, url: r.url() });
  });
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) { pwConsole.length = 0; refMap = new Map(); } });
  log("headless chrome ready (channel=chrome)");
}

const viewportInfo = () => {
  const v = context ? context.viewportSize?.() || VIEWPORTS.desktop : VIEWPORTS.desktop;
  if (viewportMode === "fill") return { mode: "fill", width: null, height: null };
  return { mode: viewportMode, width: v.width, height: v.height };
};

async function setViewport(mode) {
  viewportMode = mode === "fill" ? "fill" : (VIEWPORTS[mode] ? mode : "custom");
  if (VIEWPORTS[mode]) await page.setViewportSize(VIEWPORTS[mode]);
  // 'fill' keeps the current size — a headless provider has no panel to fill
}

/* css path helper injected into the page for stable-ish element refs */
const CSS_PATH_FN = `function cssPath(el){
  if (el.id) return '#'+CSS.escape(el.id);
  const parts=[]; let n=el;
  while(n && n.nodeType===1 && parts.length<6){
    let s=n.tagName.toLowerCase();
    if(n.classList && n.classList.length) s+='.'+[...n.classList].slice(0,2).join('.');
    const p=n.parentElement;
    if(p){const same=[...p.children].filter(c=>c.tagName===n.tagName); if(same.length>1) s+=':nth-of-type('+(same.indexOf(n)+1)+')';}
    parts.unshift(s); n=p;
  }
  return parts.join('>');
}`;

const SNAPSHOT_EVAL = `(() => {
  ${CSS_PATH_FN}
  const sel = ${"__SEL__"};
  const root = sel ? document.querySelector(sel) : document;
  const scope = sel || null;
  const text = (root && root.innerText || document.body && document.body.innerText || "");
  const INTERACTIVE = 'a,button,input,select,textarea,summary,[role],[onclick],img,video';
  const els = [...(root||document).querySelectorAll(INTERACTIVE)]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width>0||r.height>0; })
    .slice(0, 200).map((el, i) => {
      const r = el.getBoundingClientRect();
      const e = { id: 'e'+(i+1), selector: cssPath(el), tag: el.tagName.toLowerCase(),
        bounds: {x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)},
        inViewport: r.bottom>0 && r.top<innerHeight };
      const label = el.getAttribute('aria-label') || el.getAttribute('placeholder')
        || el.getAttribute('alt') || el.getAttribute('title')
        || (el.innerText||el.value||'').trim().slice(0,80);
      if (label) e.label = label;
      if (el.tagName==='A') e.href = el.href;
      if (el.tagName==='IMG') { e.src = el.currentSrc||el.src; e.naturalWidth = el.naturalWidth; }
      if (el.tagName==='VIDEO') { e.src = el.currentSrc||el.src; }
      if (el.type) e.type = el.type;
      if (el.getAttribute('role')) e.role = el.getAttribute('role');
      if ('disabled' in el && el.disabled) e.disabled = true;
      return e;
    });
  const acc = window.__accDone !== undefined ? {
    done: !!window.__accDone,
    scenario: window.__accScenario ? {name: window.__accScenario.name, pass: window.__accScenario.pass,
      checks: window.__accScenario.checks} : null,
    results: window.__accResults || null,
    console: window.__accConsole || null,
    opened: window.__accOpened || [],
    linkClicks: window.__accLinkClicks || [],
  } : null;
  return { url: location.href, title: document.title, scope,
    scrollY: Math.round(scrollY), maxScrollY: Math.max(0, document.documentElement.scrollHeight - innerHeight),
    text: text.slice(0, 12000), textTruncated: text.length > 12000, textTotalChars: text.length,
    elements: els, elementsTruncated: els.length >= 200,
    interactiveElementsOnPage: (root||document).querySelectorAll(INTERACTIVE).length,
    acc, viewport: { width: innerWidth, height: innerHeight } };
})()`;

async function execSnapshot(parameters = {}) {
  const expr = SNAPSHOT_EVAL.replace("__SEL__", JSON.stringify(parameters.selector || null));
  const data = await page.evaluate(expr);
  refMap = new Map((data.elements || []).map(e => [e.id, e.selector]));
  const problems = [
    ...pwConsole.map(p => ({ kind: p.kind, message: p.text, url: p.url })),
    ...((data.acc && data.acc.console) ? [
      ...(data.acc.console.errors || []).map(t => ({ kind: "console.error", message: t })),
      ...(data.acc.console.pageErrors || []).map(t => ({ kind: "pageerror", message: t })),
      ...(data.acc.console.rejections || []).map(t => ({ kind: "rejection", message: t })),
      ...(data.acc.console.resources || []).map(r => ({ kind: "resource-error", message: `${r.tag} ${r.src}`, url: r.src })),
    ] : []),
  ].slice(-80);
  return { ...data, viewport: viewportInfo(), consoleProblems: problems };
}

function resolveTarget(parameters) {
  if (parameters.ref) {
    const sel = refMap.get(parameters.ref);
    if (!sel) throw new Error(`${parameters.ref} is not on the page any more, or comes from an older snapshot. Take a new browser.snapshot and use its refs.`);
    return { selector: sel, via: parameters.ref };
  }
  if (parameters.selector) return { selector: parameters.selector, via: parameters.selector };
  if (parameters.text) return { text: parameters.text, via: `text:${parameters.text}` };
  throw new Error("Name the element with ref from browser.snapshot, a selector, or text");
}

async function execAction(action, parameters = {}) {
  if (parameters.tabId)
    throw new Error("single-page provider: tabId refused (this provider lists no tabs)");
  await ensureBrowser();
  switch (action) {
    case "browser.open": {
      if (parameters.viewport) await setViewport(parameters.viewport);
      const resp = await page.goto(parameters.url, { waitUntil: "domcontentloaded", timeout: 30000 });
      let settled = true;
      try { await page.waitForLoadState("networkidle", { timeout: 8000 }); }
      catch { settled = false; }
      return { url: page.url(), title: await page.title(), opened: true, settled,
               status: resp ? resp.status() : null, viewport: viewportInfo() };
    }
    case "browser.snapshot": return execSnapshot(parameters);
    case "browser.click": {
      const t = resolveTarget(parameters);
      let locator;
      if (t.selector) locator = page.locator(t.selector).first();
      else locator = page.getByText(t.text, { exact: false }).first();
      await locator.click({ timeout: 8000 });
      return { clicked: t.via, label: (await locator.innerText().catch(() => ""))?.slice(0, 80) || null, url: page.url() };
    }
    case "browser.type": {
      if (!parameters.selector) throw new Error("browser.type requires selector");
      await page.fill(parameters.selector, String(parameters.value ?? ""), { timeout: 8000 });
      if (parameters.submit) await page.press(parameters.selector, "Enter");
      return { selector: parameters.selector, url: page.url() };
    }
    case "browser.select": {
      if (!parameters.selector) throw new Error("browser.select requires selector");
      const opt = parameters.label !== undefined ? { label: parameters.label } : { value: parameters.value };
      await page.selectOption(parameters.selector, opt, { timeout: 8000 });
      return { selector: parameters.selector, ...opt, url: page.url() };
    }
    case "browser.scroll": {
      if (parameters.selector) {
        await page.locator(parameters.selector).first().scrollIntoViewIfNeeded({ timeout: 5000 });
        return { scrolledTo: parameters.selector, url: page.url(), ...(await scrollMetrics()) };
      }
      const dir = parameters.direction || "down";
      const px = dir === "top" ? -1e7 : dir === "bottom" ? 1e7 : dir === "up" ? -600 : 600;
      await page.evaluate((y) => scrollBy(0, y), px);
      await page.waitForTimeout(120);
      return { direction: dir, ...(await scrollMetrics()) };
    }
    case "browser.back": await page.goBack({ waitUntil: "domcontentloaded" }); return navInfo();
    case "browser.forward": await page.goForward({ waitUntil: "domcontentloaded" }); return navInfo();
    case "browser.inspect": {
      if (!parameters.selector) throw new Error("browser.inspect requires selector");
      return await page.evaluate(({ sel, fnSrc }) => {
        const el = document.querySelector(sel);
        if (!el) return { error: `No element matches ${sel}` };
        const r = el.getBoundingClientRect();
        const computed = getComputedStyle(el);
        const props = ["color","background-color","font-family","font-size","font-weight","line-height","border-radius","border-width","border-color","box-shadow","display","position","padding","margin","opacity","visibility"];
        const styles = {}; for (const p of props) { const v = computed.getPropertyValue(p); if (v) styles[p] = v.trim(); }
        const label = el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("alt") || el.getAttribute("title") || (el.innerText || el.value || "").trim().slice(0, 80);
        return { selector: sel, tag: el.tagName.toLowerCase(), label: label || undefined,
          bounds: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) },
          inViewport: r.bottom > 0 && r.top < innerHeight, styles };
      }, { sel: parameters.selector });
    }
    case "browser.capture": {
      const buf = await page.screenshot({ type: "png" });
      const b64 = buf.toString("base64");
      const label = (parameters.label || "page").replace(/[^a-z0-9-]+/gi, "-").slice(0, 48) || "page";
      mkdirSync(SHOTS, { recursive: true });
      const file = path.join(SHOTS, `${label}-${Date.now()}.png`);
      writeFileSync(file, buf);
      const v = viewportInfo();
      return { base64: b64, mime: "image/png",
               width: v.width || VIEWPORTS.desktop.width, height: v.height || VIEWPORTS.desktop.height,
               url: page.url(), title: await page.title(), viewport: v,
               savedCopy: file };
    }
    case "browser.resize": {
      if (!parameters.viewport) throw new Error("viewport is required for browser.resize");
      await setViewport(parameters.viewport);
      return viewportInfo();
    }
    case "browser.close":
      throw new Error("single-page provider: nothing to close (the provider's one page stays open)");
    default:
      throw new Error(`unsupported action: ${action}`);
  }
}
async function scrollMetrics() {
  return page.evaluate(() => ({
    scrollY: Math.round(scrollY),
    maxScrollY: Math.max(0, document.documentElement.scrollHeight - innerHeight),
    atTop: scrollY <= 1,
    atBottom: scrollY + innerHeight >= document.documentElement.scrollHeight - 1,
  }));
}
async function navInfo() {
  return { url: page.url(), title: await page.title() };
}

/* ---------------- SSE claim loop ---------------- */
let myConnectionId = null;
let sseReq = null;
const requestQueue = [];
let pumping = false;

async function claimAndRun(requestId, action, parameters) {
  const cres = await ocFetch("/api/browser-control/claim", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ requestId }),
  });
  const cj = await cres.json().catch(() => ({}));
  if (!cj.granted) { log(`claim refused for ${requestId} (${action})`); return; }
  const t0 = Date.now();
  try {
    const data = await execAction(action, parameters || {});
    await ocFetch("/api/browser-control/result", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ requestId, ok: true, data }),
    });
    log(`served ${action} in ${Date.now() - t0}ms`);
  } catch (e) {
    await ocFetch("/api/browser-control/result", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ requestId, ok: false, error: String(e.message || e).slice(0, 500) }),
    });
    log(`served ${action} ERROR in ${Date.now() - t0}ms: ${e.message || e}`);
  }
}
function pump() {
  if (pumping) return;
  pumping = true;
  (async () => {
    while (requestQueue.length) {
      const { requestId, action, parameters } = requestQueue.shift();
      await claimAndRun(requestId, action, parameters);
    }
    pumping = false;
  })();
}
function connectSse() {
  const u = new URL("/api/openchamber/events?browser=1", OC_URL);
  sseReq = http.get({ hostname: u.hostname, port: u.port, path: u.pathname + u.search,
    headers: { cookie, accept: "text/event-stream" } }, (res) => {
    if (res.statusCode !== 200) { log(`SSE connect failed: HTTP ${res.statusCode}`); return; }
    let buf = "";
    res.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const dataLines = block.split("\n").filter(l => l.startsWith("data:")).map(l => l.slice(5).trim());
        if (!dataLines.length) continue;
        let ev; try { ev = JSON.parse(dataLines.join("\n")); } catch { continue; }
        if (ev.type === "openchamber:event-stream-ready") {
          myConnectionId = ev.properties?.connectionId || null;
          log(`SSE connected, connectionId=${myConnectionId}`);
        } else if (ev.type === "openchamber:browser-control-request") {
          const p = ev.properties || {};
          const pref = p.preferredConnectionId;
          if (pref && myConnectionId && pref !== myConnectionId) {
            log(`skipping ${p.action} — preferred client is ${pref}`);
            continue;
          }
          requestQueue.push({ requestId: p.requestId, action: p.action, parameters: p.parameters });
          pump();
        }
      }
    });
    res.on("error", (e) => log("SSE stream error:", e.message));
  });
  sseReq.on("error", (e) => log("SSE request error:", e.message));
}
async function registerPreferred() {
  // wait for connectionId from the ready event
  for (let i = 0; i < 50 && !myConnectionId; i++) await new Promise(r => setTimeout(r, 100));
  if (!myConnectionId) die("no connectionId from SSE ready event");
  const res = await ocFetch("/api/browser-control/active", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ connectionId: myConnectionId, previousConnectionId: null }),
  });
  const j = await res.json().catch(() => ({}));
  if (!j.preferredConnectionId) die(`browser-control/active refused: ${JSON.stringify(j)}`);
  log(`registered as preferred browser client (${j.preferredConnectionId})`);
}

/* ---------------- driver ---------------- */
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function control(action, input = {}) {
  const r = await ocControl(action, input);
  if (r && r.error) throw new Error(`${action}: ${r.error}`);
  return r;
}
async function waitHarnessDone(timeoutMs = 180000) {
  const t0 = Date.now();
  for (;;) {
    const snap = await control("browser.snapshot", {});
    const acc = snap.acc || {};
    if (acc.done) return snap;
    if (Date.now() - t0 > timeoutMs) throw new Error(`harness did not finish in ${timeoutMs}ms`);
    await sleep(1200);
  }
}
const EXPECTED_BROKEN = /\/gone\/|does-not-exist|\/bogus\//;
function unexpectedProblems(problems) {
  const list = problems || [];
  // a bare "Failed to load resource" console line carries no URL — excuse it
  // only when this page also logged an expected-broken asset
  const hasExpectedAsset = list.some(p => EXPECTED_BROKEN.test(p.url || "") || EXPECTED_BROKEN.test(p.message || ""));
  return list.filter(p => {
    const u = p.url || "";
    const m = p.message || "";
    if (EXPECTED_BROKEN.test(u) || EXPECTED_BROKEN.test(m)) return false;
    if (hasExpectedAsset && /Failed to load resource/.test(m)) return false;
    return true;
  });
}

async function runPreviewSuite() {
  await ocLogin();
  connectSse();
  await registerPreferred();
  await ensureBrowser();
  const H = `${serverUrl}/tests/ha/ada-chat-card/harness.html`;
  const out = { startedAt: new Date().toISOString(), ocUrl: OC_URL, serverUrl, scenarios: {}, summary: {} };

  const runOne = async (key, extra = "") => {
    log(`scenario ${key}: open`);
    await control("browser.open", { url: `${H}?scenario=${key}${extra}` });
    const snap = await waitHarnessDone();
    const acc = snap.acc || {};
    const scen = acc.scenario || (acc.results || []).find(r => r.name === key) || null;
    const problems = unexpectedProblems(snap.consoleProblems || []);
    const checks = scen ? scen.checks : [];
    const pass = !!(scen && scen.pass && problems.length === 0);
    out.scenarios[key] = {
      pass, checks,
      console: acc.console || {},
      opened: acc.opened || [], linkClicks: acc.linkClicks || [],
      consoleProblems: snap.consoleProblems || [],
      unexpectedProblems: problems,
      viewport: snap.viewport, url: snap.url, title: snap.title,
    };
    log(`scenario ${key}: ${pass ? "PASS" : "FAIL"} (${checks.filter(c => !c.pass).length} failed checks, ${problems.length} unexpected console problems)`);
    await control("browser.capture", { label: `ada-chat-${key}`, directory: EVIDENCE });
    return pass;
  };

  if (SCENARIO === "all") {
    for (const k of SCENARIOS) await runOne(k);
    // whole-suite page as one durable artifact
    log("scenario all: open");
    await control("browser.open", { url: `${H}?scenario=all` });
    const snap = await waitHarnessDone(300000);
    out.scenarios["all"] = { pass: true, results: snap.acc?.results || null,
      consoleProblems: snap.consoleProblems || [], viewport: snap.viewport };
    await control("browser.capture", { label: "ada-chat-suite-all", directory: EVIDENCE });
  } else if (SCENARIOS.includes(SCENARIO)) {
    await runOne(SCENARIO, SCENARIO === "mobile-layout" ? "&w=360" : "");
  } else {
    die(`unknown scenario ${SCENARIO}`);
  }

  // mobile viewport pass through the preview resize action
  log("mobile pass: browser.resize mobile");
  await control("browser.resize", { viewport: "mobile" });
  await control("browser.open", { url: `${H}?scenario=mobile-layout&w=360` });
  const msnap = await waitHarnessDone();
  const mscen = msnap.acc?.scenario;
  const mprobs = unexpectedProblems(msnap.consoleProblems || []);
  out.scenarios["mobile-viewport"] = {
    pass: !!(mscen && mscen.pass && mprobs.length === 0),
    checks: mscen ? mscen.checks : [], consoleProblems: msnap.consoleProblems || [],
    unexpectedProblems: mprobs, viewport: msnap.viewport,
  };
  log(`mobile-viewport: ${out.scenarios["mobile-viewport"].pass ? "PASS" : "FAIL"}`);
  await control("browser.capture", { label: "ada-chat-mobile-390", directory: EVIDENCE });
  await control("browser.resize", { viewport: "desktop" });

  out.finishedAt = new Date().toISOString();
  const fails = Object.entries(out.scenarios).filter(([, s]) => s.pass === false).map(([k]) => k);
  out.summary = { total: Object.keys(out.scenarios).length, failed: fails,
    verdict: fails.length ? "FAIL" : "PASS" };
  mkdirSync(EVIDENCE, { recursive: true });
  writeFileSync(path.join(EVIDENCE, "results.json"), JSON.stringify(out, null, 2));
  writeFileSync(path.join(EVIDENCE, "latest.json"), JSON.stringify(out, null, 2));
  log(`verdict: ${out.summary.verdict} — evidence in ${EVIDENCE}`);
  for (const [k, s] of Object.entries(out.scenarios)) {
    const bad = (s.checks || []).filter(c => !c.pass);
    if (bad.length) for (const b of bad) log(`  ${k} FAIL check: ${b.name} — ${b.detail}`);
    if ((s.unexpectedProblems || []).length) for (const p of s.unexpectedProblems) log(`  ${k} UNEXPECTED console: ${p.kind} ${p.message}`);
  }
  return out.summary.verdict === "PASS";
}

async function runDirectSuite() {
  // debug path: same actions, no OpenChamber — validates the executor alone
  await ensureBrowser();
  const H = `${serverUrl}/tests/ha/ada-chat-card/harness.html`;
  const keys = SCENARIO === "all" ? SCENARIOS : [SCENARIO];
  let allPass = true;
  for (const k of keys) {
    await execAction("browser.open", { url: `${H}?scenario=${k}${k === "mobile-layout" ? "&w=360" : ""}` });
    const t0 = Date.now();
    let snap;
    while (Date.now() - t0 < 180000) {
      snap = await execSnapshot({});
      if (snap.acc?.done) break;
      await sleep(1200);
    }
    const scen = snap.acc?.scenario;
    const probs = unexpectedProblems(snap.consoleProblems || []);
    const pass = !!(scen && scen.pass && probs.length === 0);
    allPass &&= pass;
    log(`${k}: ${pass ? "PASS" : "FAIL"}`);
    if (!pass) console.log(JSON.stringify({ checks: scen?.checks?.filter(c => !c.pass), probs }, null, 2));
    await execAction("browser.capture", { label: `direct-${k}` });
  }
  return allPass;
}

/* ---------------- main ---------------- */
let ok = false;
try {
  await ensureServer();
  ok = args.direct ? await runDirectSuite() : await runPreviewSuite();
} catch (e) {
  console.error("[preview-bridge] run failed:", e);
  ok = false;
} finally {
  try { sseReq?.destroy(); } catch {}
  try { await browser?.close(); } catch {}
  if (serverProc) { try { serverProc.kill(); } catch {} }
}
process.exit(ok ? 0 : 1);
