// cast-browser-server.mjs — persistent headless Chrome for voice-driven TV casting.
// Keeps the Playwright context (and its HA login) open, re-screenshots after
// each action, and re-casts the PNG if it changed.
// API:
//   POST /nav     {url|key}            go to page
//   POST /scroll  {dx?,dy?,factor?}    scroll (factor is fraction of viewport height)
//   POST /click   {text|selector|role} click element
//   POST /type    {text}               type into focused field
//   POST /press   {key}                press a key
//   POST /back                         browser back
//   POST /select  {key}                select view + shot + cast (timer path)
//   POST /viewport {width,height}      change viewport
//   GET  /state                        {url, title, lastCmd, queue, viewport}
//   GET  /shot?out=<name>              screenshot + cast current page
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { chromium } from '/home/tony/.local/playlive/node_modules/playwright/index.mjs';

// Host-portable (2026-09-29): all host bindings are env-overridable so the
// same file can run on any LAN host. Defaults preserve tony-dell behavior.
const HA_BASE = process.env.HA_BASE || 'http://127.0.0.1:8123';
const OUT_DIR = process.env.OUT_DIR || '/home/tony/.config/home-assistant/www/ha';
// Public URL prefix the TV/Chromecast fetches shots from. On tony-dell this
// is HA's /local/ha/; on other hosts serve OUT_DIR over plain http.
const MEDIA_BASE = process.env.MEDIA_BASE || (HA_BASE + "/local/ha");
const PROFILE = process.env.HA_CAST_PROFILE || '/home/tony/.config/ha-cast-profile';
const PORT = parseInt(process.env.PORT || '8799', 10);

const MACBOOK_VNC_PASSWORD = process.env.MACBOOK_VNC_PASSWORD || '';

// Physical desktop X display for workspace switching / screen grabs.
// Hardcoded ':1' was right for the old seat layout; tony-omen's XFCE
// session runs on :0 (only X socket present). Override via CAST_X_DISPLAY.
const X_DISPLAY = process.env.CAST_X_DISPLAY || ':0';

const KEYS = {
  'smart-home': '/smart-home',
  dossier: '/dossier',
  photos: '/dossier/photos',
  youtube: '/dossier/youtube',
  map: '/map',
  panel: '/local/ha/tony-ha/index.html',
  help: '/local/ha/cast-help.html',
  vms: 'http://tony-dell/apps/vnc/vnc.html'
    + (MACBOOK_VNC_PASSWORD ? `?password=${encodeURIComponent(MACBOOK_VNC_PASSWORD)}` : '?password='),
  yolo: 'http://127.0.0.1:8080/apps/yolo/',
};

// Legacy aliases that keep old cast requests working.
const ALIASES = {
  macbook: 'vms',
};

const TOKEN = fs.readFileSync('/home/tony/.config/secrets/home-assistant-token.env','utf8')
  .match(/HA_LONG_LIVED_TOKEN=(.+)/)?.[1]?.trim();

let ctx, page;
let currentName = 'cast';
let lastCmd = null;
let viewport = { width: 1280, height: 720 };
const queue = [];
let processing = false;
const navHistory = ['smart-home'];

// A crashed/killed cast-browser leaves Chromium singleton locks behind;
// the next launch then fails with "profile appears to be in use" and
// tv_action returns 500 (2026-09-30). Clear them when the recorded pid
// is actually dead — a live pid means a real browser holds the profile
// and the launch should fail loudly as before.
function clearStaleProfileLock() {
  try {
    const target = fs.readlinkSync(PROFILE + "/SingletonLock");
    const pid = parseInt((target.split("-").pop() || "0"), 10);
    if (pid) process.kill(pid, 0);  // throws ESRCH if dead
    return;                        // alive holder — leave locks alone
  } catch (e) { /* dead holder or unreadable — safe to clear */ }
  for (const f of ["SingletonLock", "SingletonCookie", "SingletonSocket"]) {
    try { fs.unlinkSync(PROFILE + "/" + f); } catch {}
  }
}

async function browser() {
  if (!ctx) {
    clearStaleProfileLock();
    ctx = await chromium.launchPersistentContext(PROFILE, {
      channel: 'chrome', headless: true,
      viewport,
      args: ['--no-sandbox', '--enable-unsafe-swiftshader'],
        // WebGL needs the GPU process (Vulkan/SwiftShader path) —
        // --disable-gpu leaves Cesium half-initialized (2026-10-02 GEV TV cast
        // showed 'Error constructing CesiumWidget'). ANGLE-Vulkan on the real
        // NVIDIA driver returns NULL for powerPreference:'high-performance',
        // which Cesium requires — plain SwiftShader renders it correctly.
    });
    page = ctx.pages()[0] ?? await ctx.newPage();
  }
  if (page.isClosed()) page = await ctx.newPage();
  return page;
}

async function ensureLogin(p) {
  const trusted = p.locator('ha-list-item:has-text("Trusted Networks"), [role="listitem"]:has-text("Trusted Networks")').first();
  if (await trusted.isVisible({ timeout: 1500 }).catch(() => false)) { await trusted.click(); await p.waitForTimeout(1500); }
  const radio = p.locator('ha-radio-option').first();
  if (await radio.isVisible({ timeout: 1500 }).catch(() => false)) {
    await radio.click();
    await p.locator('ha-button:has-text("Log in")').first().click().catch(() => {});
    await p.waitForTimeout(4000);
  }
}

function hashFile(n) { return `/tmp/cast-browser.${n}.sha`; }
function safeName(n) { return String(n).replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 80) || 'page'; }

const CAST_TARGET_MAP = {
  'TONY-TV Cast': 'media_player.tony_tv_cast',
};

// Hard allowlist — only Tony's own TV (Skyworth SKWAMX3 on 192.168.2.x) may
// ever be a cast target. TVs discovered via the wlx/Naris USB-WiFi dongle
// (192.168.1.x — foreign network, e.g. the neighbor's Samsung TV-40C5000)
// must be refused even if a select option or screens.json entry maps to them.
const CAST_ALLOWLIST = new Set([
  'media_player.tony_tv_cast',
  'media_player.tony_tv',
]);
const CAST_DEFAULT = 'media_player.tony_tv_cast';

// ---- screen ownership ACL (~/.config/cast-browser/screens.json) ----
// Personal screens (sources AND cast destinations) are private to their
// owner: only that speaker may cast to/from them. 'shared' entries are
// communal — any caller (identified or not) may use them.
const SCREENS = (() => {
  try {
    return JSON.parse(fs.readFileSync('/home/tony/.config/cast-browser/screens.json', 'utf8'));
  } catch { return { destinations: {}, sources: {}, speaker_aliases: {} }; }
})();
const SPEAKER_ALIASES = SCREENS.speaker_aliases || {};
function speakerPerson(raw) {
  const s = String(raw || '').trim();
  if (!s) return 'anonymous';
  if (s.startsWith('person.')) return s;
  return SPEAKER_ALIASES[s] || 'anonymous';
}
class AclError extends Error { constructor(m) { super(m); this.httpStatus = 403; } }
function aclCheckSource(sourceId, person) {
  const s = SCREENS.sources[sourceId];
  if (!s || s.owner === 'shared' || s.owner === person) return;
  const who = s.owner.replace(/^person\./, '');
  throw new AclError(person === 'anonymous'
    ? `denied: ${s.label || sourceId} is ${who}'s private screen — identify the speaker first`
    : `denied: ${s.label || sourceId} is ${who}'s private screen`);
}
async function aclCheck(cmdObj) {
  const person = speakerPerson(cmdObj.speaker);
  const c = String(cmdObj.cmd || '').toLowerCase();
  const parts = c.split(/\s+/);
  const t = String(cmdObj.text || parts.slice(1).join(' ') || '').toLowerCase();
  if (parts[0] === 'nav') {
    if (/^(screenlive|screen:|workspace)/.test(t)) aclCheckSource('seat', person);
    if (/^tony-omen:/.test(t)) aclCheckSource('omen', person);
  }
  const entity = await getCastTarget();
  const d = SCREENS.destinations[entity];
  if (d && d.owner !== 'shared' && d.owner !== person) {
    const who = d.owner.replace(/^person\./, '');
    throw new AclError(`denied: ${entity} is ${who}'s screen`);
  }
}

async function getCastTarget() {
  try {
    const r = await fetch(`${HA_BASE}/api/states/input_select.tv_cast_target`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    if (r.ok) {
      const j = await r.json();
      const s = (j.state || '').trim();
      if (s) {
        const resolved = CAST_TARGET_MAP[s]
          || (s.startsWith('media_player.') ? s : `media_player.${s}`);
        if (CAST_ALLOWLIST.has(resolved)) return resolved;
        console.log(`cast target ${resolved} not in allowlist — falling back to ${CAST_DEFAULT}`);
      }
    }
  } catch {}
  return CAST_DEFAULT;
}

async function setCastTarget(option) {
  try {
    await haApi('/api/services/input_select/select_option', {
      entity_id: 'input_select.tv_cast_target',
      option,
    });
  } catch {}
}

async function autoCastTarget(cmdObj) {
  await setCastTarget('TONY-TV Cast');
}

const DBUS_ENV = { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' };

async function stopDesktop() {
  const units = await new Promise((resolve) => {
    let out = '';
    const sp = spawn('systemctl', ['--user', '--no-legend', '--plain', '--state=active', 'list-units', 'cast-desktop@*.service', 'cast-desktop-crop@*.service'], {
      env: DBUS_ENV,
    });
    sp.stdout.on('data', c => { out += c; });
    sp.on('error', () => resolve([]));
    sp.on('close', () => {
      const list = out.split('\n')
        .map(l => l.split(/\s+/)[0])
        .filter(u => u.startsWith('cast-desktop') && u.endsWith('.service'));
      resolve(list);
    });
  });
  if (!units.length) return 'none';
  return await new Promise((resolve) => {
    const sp = spawn('timeout', ['10', 'systemctl', '--user', 'stop', ...units], { env: DBUS_ENV });
    sp.on('error', e => resolve(`err:${e.message}`));
    sp.on('close', c => resolve(`stopped:${units.join(',')}:${c}`));
  });
}

const PLUG_OFF_COOLDOWN_MS = 10 * 60 * 1000;

async function haState(eid) {
  try {
    const r = await haApi(`/api/states/${eid}`);
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

async function haNotify(title, message, id) {
  try {
    await haApi('/api/services/persistent_notification/create', { title, message, notification_id: id });
  } catch {}
}

async function wakeCastTarget(target) {
  const enabled = await haState('input_boolean.cast_enabled');
  if (enabled && enabled.state === 'off') return 'blocked:cast_enabled';
  const plug = await haState('switch.plug_tv');
  if (plug && plug.state !== 'on') {
    const offAgo = Date.now() - new Date(plug.last_changed).getTime();
    if (offAgo < PLUG_OFF_COOLDOWN_MS) {
      const ev = {
        title: 'TV plug power-on suppressed — approve?',
        category: 'cast', source: 'wakeCastTarget', severity: 'warn',
        body: `switch.plug_tv was turned off ${Math.round(offAgo / 60000)} min ago — Ack approves power-on.`,
        requires_response: true,
        action: { domain: 'script', service: 'cast_power_on', data: { target: 'box', force: true } },
      };
      try {
        await haApi('/api/services/shell_command/chaba_event', { payload: Buffer.from(JSON.stringify(ev)).toString('base64') });
      } catch {}
      return 'blocked:plug_cooldown';
    }
    try {
      await haApi('/api/services/switch/turn_on', { entity_id: 'switch.plug_tv' });
    } catch {}
    await haNotify('Cast: auto-powered TV plug',
      'switch.plug_tv turned on automatically — cast target was unavailable.',
      'cast_plug_autopower');
  }
  try {
    await haApi('/api/services/remote/turn_on', { entity_id: 'remote.tony_tv' });
  } catch {}
  try {
    await haApi('/api/services/media_player/turn_on', { entity_id: target });
  } catch {}
  await new Promise(r => setTimeout(r, 1500));
  return 'ok';
}

async function shotAndCast(name) {
  const p = await browser();
  if (viewport.width && viewport.height) await p.setViewportSize(viewport);
  const safe = safeName(name);
  const out = `${OUT_DIR}/${safe}.png`;
  const tmp = `${out}.tmp.png`;
  await p.screenshot({ path: tmp });
  const buf = fs.readFileSync(tmp);
  const hash = crypto.createHash('sha256').update(buf).digest('hex');
  currentName = safe;
  if (fs.existsSync(hashFile(safe)) && fs.readFileSync(hashFile(safe),'utf8') === hash && fs.existsSync(out)) {
    fs.unlinkSync(tmp); return 'unchanged';
  }
  fs.writeFileSync(hashFile(safe), hash);
  fs.renameSync(tmp, out);
  const target = await getCastTarget();
  const wake = await wakeCastTarget(target);
  if (wake.startsWith('blocked')) return wake;
  const r = await fetch(`${HA_BASE}/api/services/media_player/play_media`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      entity_id: target,
      media_content_type: 'image/png',
      media_content_id: `${MEDIA_BASE}/${safe}.png?v=${Date.now()}`,
    }),
  });
  return `cast:${r.status}`;
}

async function waitForVnc(p, timeout=15000) {
  // noVNC app.html auto-connects; wait until the screen canvas is present and connected.
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const canvas = await p.locator('div#screen canvas').first();
    const connected = await canvas.isVisible().catch(() => false);
    if (connected) {
      const status = await p.locator('#status').textContent().catch(() => '');
      if (status.toLowerCase().includes('connected')) return true;
    }
    await new Promise(r => setTimeout(r, 500));
  }
  return false;
}

async function gotoInternal(keyOrUrl, name, pushHistory=true) {
  const p = await browser();
  const resolvedKey = ALIASES[keyOrUrl] || keyOrUrl;
  const keyedUrl = KEYS[resolvedKey];
  let url = keyedUrl
    ? (keyedUrl.startsWith('http') ? keyedUrl : HA_BASE + keyedUrl)
    : /^https?:/.test(resolvedKey) ? resolvedKey : null;
  if (!url) return { ok: false, err: `unknown key ${resolvedKey}` };
  if (url.startsWith(HA_BASE) && !url.includes('?_=')) {
    url += (url.includes('?') ? '&' : '?') + '_=' + Date.now();
  }
  await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(e => ({ navErr: e.message }));
  await p.waitForTimeout(2500);
  await ensureLogin(p);
  await p.waitForTimeout(1500);
  if (url.includes('vnc.html')) {
    await waitForVnc(p, 15000);
    // Give the VMS desktop a moment to paint after the VNC handshake.
    await p.waitForTimeout(4000);
  }
  if (pushHistory) {
    if (navHistory[navHistory.length - 1] !== resolvedKey) navHistory.push(resolvedKey);
    if (navHistory.length > 20) navHistory.shift();
  }
  return { ok: true, cast: await shotAndCast(resolvedKey), url: p.url() };
}
async function gotoTarget(keyOrUrl, name) { return gotoInternal(keyOrUrl, name, true); }

// Grab an X display to a temp PNG via ffmpeg x11grab.
//   'screen'      -> :1 (physical desktop)
//   'screen:N'    -> :N (e.g. 99 = the Xvfb virtual desktop)
//   'screen' alone or 'screen:1' / 'screen:99' / ...
function parseWorkspaceSpec(s) {
  const parts = (s || '').split(':').filter(Boolean);
  let mode = 'pad', n = '1';
  for (const p of parts) {
    if (['pad','crop'].includes(p)) mode = p;
    else if (/^\d+$/.test(p)) n = p;
  }
  return { n, mode };
}

async function getCurrentWorkspace() {
  try {
    const out = await new Promise((resolve, reject) => {
      const p = spawn('xprop', ['-root', '-notype', '32c', '_NET_CURRENT_DESKTOP'], {
        env: { ...process.env, DISPLAY: X_DISPLAY },
      });
      let s = '';
      p.stdout.on('data', c => s += c);
      p.on('close', c => c === 0 ? resolve(s) : reject(new Error('xprop')));
    });
    const m = out.match(/=\s*(\d+)/);
    return m ? Number(m[1]) : 0;
  } catch { return 0; }
}

async function setWorkspace(n, wait=true) {
  const idx = Math.max(0, Number(n) - 1);
  const xauthFile = process.env.XAUTHORITY || '/home/tony/.Xauthority';
  await new Promise((resolve, reject) => {
    const p = spawn('xdotool', ['set_desktop', String(idx)], {
      env: { ...process.env, DISPLAY: X_DISPLAY, XAUTHORITY: xauthFile },
    });
    const t = setTimeout(() => { p.kill('SIGKILL'); reject(new Error('set_workspace timeout')); }, 5000);
    p.on('close', c => { clearTimeout(t); c === 0 ? resolve() : reject(new Error(`set_workspace exit ${c}`)); });
    p.on('error', e => { clearTimeout(t); reject(e); });
  });
  if (wait) {
    // Wait until the window manager reports the requested desktop, then a bit
    // longer so any slide/fade animation finishes.
    const start = Date.now();
    while (Date.now() - start < 3000) {
      try { if (await getCurrentWorkspace() === idx) break; } catch {}
      await new Promise(r => setTimeout(r, 100));
    }
    await new Promise(r => setTimeout(r, 800));
  }
}

async function thumbWorkspace(n, mode='pad') {
  const original = await getCurrentWorkspace();
  try {
    await setWorkspace(n, true);
    const f = await grabX(X_DISPLAY, mode);
    const out = `${OUT_DIR}/desktop/thumb-workspace-${n}.png`;
    fs.copyFileSync(f, out);
    try { fs.unlinkSync(f); } catch {}
    return out;
  } finally {
    try { await setWorkspace(String(original + 1), false); } catch {}
  }
}

function xauthMerge(src, disp, dst) {
  return new Promise((resolve, reject) => {
    const list = spawn('xauth', ['-f', src, 'nlist', disp]);
    let data = '';
    list.stdout.on('data', c => data += c);
    list.on('error', reject);
    list.on('close', () => {
      const merge = spawn('xauth', ['-f', dst, 'nmerge', '-']);
      merge.stdin.write(data); merge.stdin.end();
      merge.on('error', reject);
      merge.on('close', () => resolve());
    });
  });
}

async function grabX(disp, mode='pad') {
  const f = `/tmp/cast-scr-${crypto.randomBytes(4).toString('hex')}.png`;
  const xauthFile = process.env.XAUTHORITY || '/home/tony/.Xauthority';
  await new Promise((resolve, reject) => {
    const vf = mode === 'crop'
      ? 'scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080'
      : 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1';
    const ff = spawn('ffmpeg', ['-f', 'x11grab', '-i', disp, '-vf', vf, '-frames:v', '1', '-y', f], {
      env: { ...process.env, XAUTHORITY: xauthFile },
    });
    const t = setTimeout(() => { ff.kill('SIGKILL'); reject(new Error('x11grab timeout')); }, 15000);
    ff.on('close', c => { clearTimeout(t); c === 0 || fs.existsSync(f) ? resolve() : reject(new Error(`x11grab exit ${c}`)); });
    ff.on('error', e => { clearTimeout(t); reject(e); });
  });
  return f;
}

// Render one compose source to a temp image file.
//   'cam:<entity>'   -> HA camera_proxy still
//   'screen[:N]'     -> X11 display grab (:1 physical, :99 Xvfb)
//   <key|url>        -> fresh Playwright screenshot in a throwaway tab
function parseScreenSpec(src) {
  const parts = src.split(':');
  let mode = 'pad', d = '1';
  if (parts.length === 1) { /* screen */ }
  else if (parts.length === 2) {
    if (['pad','crop'].includes(parts[1])) mode = parts[1];
    else d = parts[1];
  } else if (parts.length === 3) {
    if (['pad','crop'].includes(parts[1])) { mode = parts[1]; d = parts[2]; }
    else { d = parts[1]; }
  }
  return { d, mode };
}

async function renderSource(src) {
  if (src === 'screen' || src.startsWith('screen:')) {
    const { d, mode } = parseScreenSpec(src);
    return grabX(`:${d}`, mode);
  }
  if (src.startsWith('cam:')) {
    const eid = src.slice(4);
    const r = await fetch(`${HA_BASE}/api/camera_proxy/${eid}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    if (!r.ok) throw new Error(`cam ${eid} HTTP ${r.status}`);
    const f = `/tmp/cast-src-${crypto.randomBytes(4).toString('hex')}.jpg`;
    fs.writeFileSync(f, Buffer.from(await r.arrayBuffer()));
    return f;
  }
  const url = KEYS[src] ? HA_BASE + KEYS[src] : (/^https?:/.test(src) ? src : null);
  if (!url) throw new Error(`unknown source: ${src}`);
  await browser();
  const p2 = await ctx.newPage();
  try {
    await p2.setViewportSize(viewport);
    await p2.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    await p2.waitForTimeout(2500);
    await ensureLogin(p2);
    await p2.waitForTimeout(1200);
    const f = `/tmp/cast-src-${crypto.randomBytes(4).toString('hex')}.png`;
    await p2.screenshot({ path: f });
    return f;
  } finally { await p2.close().catch(() => {}); }
}

async function thumbDisplay(d) {
  const f = await grabX(`:${d}`);
  const out = `${OUT_DIR}/desktop/thumb-${d}.png`;
  fs.copyFileSync(f, out);
  try { fs.unlinkSync(f); } catch {}
  return out;
}

async function castImageFile(file, name) {
  const out = `${OUT_DIR}/${name}.png`;
  fs.copyFileSync(file, out);
  try { fs.unlinkSync(file); } catch {}
  currentName = name;
  const target = await getCastTarget();
  const wake = await wakeCastTarget(target);
  if (wake.startsWith('blocked')) return wake;
  const r = await fetch(`${HA_BASE}/api/services/media_player/play_media`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      entity_id: target,
      media_content_type: 'image/png',
      media_content_id: `${MEDIA_BASE}/${safe}.png?v=${Date.now()}`,
    }),
  });
  return `cast:${r.status}`;
}

// 'split:a+b' | 'grid:a+b+c+d' | 'pip:main+cam:camera.x'
async function composeSpec(spec) {
  const m = /^(split|grid|pip):(.+)$/.exec(spec);
  if (!m) return { ok: false, err: `bad compose spec: ${spec}` };
  const layout = m[1];
  const sources = m[2].split('+').map(s => s.trim()).filter(Boolean);
  const files = [];
  for (const s of sources) files.push(await renderSource(s));
  const tmp = `/tmp/cast-compose-${crypto.randomBytes(4).toString('hex')}.png`;
  await new Promise((resolve, reject) => {
    const py = spawn('python3', [
      '/home/tony/.local/bin/cast-compose.py',
      layout, String(viewport.width), String(viewport.height), tmp, ...files,
    ]);
    py.on('close', c => c === 0 ? resolve() : reject(new Error(`compose exit ${c}`)));
    py.on('error', reject);
  });
  files.forEach(f => { try { fs.unlinkSync(f); } catch {} });
  const name = `${layout}-${sources.join('-').replace(/[^\w]+/g, '_').slice(0, 40)}`;
  return { ok: true, layout, sources, cast: await castImageFile(tmp, name) };
}

async function clickElement(p, spec) {
  const { text, selector, role } = spec;
  let loc;
  if (selector) loc = p.locator(selector);
  else if (role) loc = p.getByRole(role, { name: text, exact: false });
  else if (text) {
    loc = p.getByText(text, { exact: false }).first();
    if (!(await loc.isVisible().catch(() => false))) {
      loc = p.locator('button, a, ha-list-item, mwc-list-item, ha-radio-option, ha-button').filter({ hasText: text }).first();
    }
  }
  if (!loc) throw new Error('no click target');
  await loc.scrollIntoViewIfNeeded().catch(() => {});
  await loc.click({ timeout: 6000 });
}

async function runCommand(cmdObj) {
  console.log('runCommand', JSON.stringify(cmdObj));
  await aclCheck(cmdObj);
  await autoCastTarget(cmdObj);
  const { cmd, text, selector, role, key, dx, dy, factor, out } = cmdObj;
  const p = await browser();
  const parts = (cmd || '').toLowerCase().split(/\s+/);
  const verb = parts[0];
  const arg = parts.slice(1).join(' ');
  const targetName = out || currentName;
  switch (verb) {
    case 'scroll': {
      let amount = 600;
      if (factor) amount = Math.round(viewport.height * Number(factor));
      else if (dy !== undefined) amount = Number(dy);
      else amount = ({ up: -Math.round(viewport.height*0.8), down: Math.round(viewport.height*0.8), left: -600, right: 600 }[arg] || 600);
      const h = dx !== undefined ? Number(dx) : 0;
      await p.mouse.wheel(h, amount);
      await p.waitForTimeout(800);
      return { cast: await shotAndCast(targetName) };
    }
    case 'back': {
      if (navHistory.length > 1) navHistory.pop(); // remove current
      const previous = navHistory[navHistory.length - 1] || 'smart-home';
      return await gotoInternal(previous, previous, false);
    }
    case 'nav': {
      const target = text || arg;
      if (!target || target === 'off' || target === 'stop' || target === 'turnoff' || target === 'turn off') {
        const stopped = await stopDesktop();
        return { ok: true, stopped };
      }
      if (!/^screenlive/.test(target)) await stopDesktop();
      if (target === 'screen' || target.startsWith('screen:')) {
        const f = await renderSource(target);
        return { ok: true, cast: await castImageFile(f, 'screen') };
      }
      if (target === 'workspace' || target.startsWith('workspace:')) {
        const { n, mode } = parseWorkspaceSpec(target.replace(/^workspace:?/, ''));
        await setWorkspace(n);
        const f = await grabX(X_DISPLAY, mode);
        return { ok: true, cast: await castImageFile(f, 'screen') };
      }
      if (target === 'tony-omen:workspace' || target.startsWith('tony-omen:workspace:')) {
        const { n, mode } = parseWorkspaceSpec(target.replace(/^tony-omen:workspace:?/, ''));
        await new Promise((res, rej) => {
          const sp = spawn('ssh', ['tony-omen', `~/.local/bin/switch-cast-desktop-workspace.sh ${n} ${mode} 0`], {
            env: { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' },
          });
          sp.on('close', c => res());
          sp.on('error', rej);
        });
        const pl = `http://100.75.102.88:8082/tony-omen/desktop/index0.m3u8`;
        for (let i = 0; i < 30; i++) {
          try { const r = await fetch(pl, { method: 'HEAD' }); if (r.ok) break; } catch {}
          await new Promise(r => setTimeout(r, 500));
        }
        const castTarget = await getCastTarget();
        const wake = await wakeCastTarget(castTarget);
        if (wake.startsWith('blocked')) return { ok: false, cast: wake };
        const r = await fetch(`${HA_BASE}/api/services/camera/play_stream`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entity_id: 'camera.tony_omen_desktop_1',
            media_player: castTarget,
            format: 'hls',
          }),
        });
        return { ok: r.ok, cast: `camera.play_stream:${r.status}`, stream: `tony-omen/index0.m3u8` };
      }
      if (/^screenlive/.test(target)) {
        if (target.includes('workspace')) {
          const { n, mode } = parseWorkspaceSpec(target.replace(/^screenlive:?/, ''));
          await setWorkspace(n);
          const svc = mode === 'crop' ? 'cast-desktop-crop@1' : 'cast-desktop@1';
          await new Promise(res => {
            const sp = spawn('timeout', ['10', 'systemctl', '--user', 'stop', 'cast-desktop@1.service', 'cast-desktop-crop@1.service'], {
              env: { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' },
            });
            sp.on('close', res); sp.on('error', res);
          });
          await new Promise(res => {
            const sp = spawn('systemctl', ['--user', 'start', `${svc}.service`], {
              env: { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' },
            });
            sp.on('close', res); sp.on('error', res);
          });
          const pl = `${OUT_DIR}/desktop/index1.m3u8`;
          for (let i = 0; i < 30 && !fs.existsSync(pl); i++) await new Promise(r => setTimeout(r, 500));
          const castTarget = await getCastTarget();
          const wake = await wakeCastTarget(castTarget);
          if (wake.startsWith('blocked')) return { ok: false, cast: wake };
          const r = await fetch(`${HA_BASE}/api/services/camera/play_stream`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({
              entity_id: 'camera.desktop_1',
              media_player: castTarget,
              format: 'hls',
            }),
          });
          return { ok: r.ok, cast: `camera.play_stream:${r.status}`, stream: `index1.m3u8` };
        }
        const raw = target.replace(/^screenlive:?/, '');
        const parts = raw.split(':').filter(Boolean);
        let mode = 'pad', n = '1';
        for (const p of parts) {
          if (['pad','crop'].includes(p)) mode = p;
          else n = p;
        }
        const svc = mode === 'crop' ? `cast-desktop-crop@${n}` : `cast-desktop@${n}`;
        await new Promise(res => {
          const sp = spawn('timeout', ['10', 'systemctl', '--user', 'stop', `cast-desktop@${n}.service`, `cast-desktop-crop@${n}.service`], {
            env: { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' },
          });
          sp.on('close', res); sp.on('error', res);
        });
        await new Promise(res => {
          const sp = spawn('systemctl', ['--user', 'start', `${svc}.service`], {
            env: { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' },
          });
          sp.on('close', res); sp.on('error', res);
        });
        const pl = `${OUT_DIR}/desktop/index${n}.m3u8`;
        for (let i = 0; i < 30 && !fs.existsSync(pl); i++) await new Promise(r => setTimeout(r, 500));
        const cam = `camera.desktop_${n}`;
        const castTarget = await getCastTarget();
        const wake = await wakeCastTarget(castTarget);
        if (wake.startsWith('blocked')) return { ok: false, cast: wake };
        const r = await fetch(`${HA_BASE}/api/services/camera/play_stream`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entity_id: cam,
            media_player: castTarget,
            format: 'hls',
          }),
        });
        return { ok: r.ok, cast: `camera.play_stream:${r.status}`, stream: `index${n}.m3u8` };
      }
      if (/^(split|grid|pip):/.test(target)) return await composeSpec(target);
      if (target === 'help') {
        try { fs.unlinkSync(hashFile('help')); } catch {}
      }
      const r = await gotoTarget(target, target);
      return r;
    }
    case 'off':
    case 'stop':
    case 'turnoff': {
      const stopped = await stopDesktop();
      return { ok: true, stopped };
    }
    case 'click': {
      await clickElement(p, { text: text || arg, selector, role });
      await p.waitForTimeout(1500);
      return { cast: await shotAndCast(targetName) };
    }
    case 'type': {
      await p.keyboard.type(text || arg);
      await p.waitForTimeout(600);
      return { cast: await shotAndCast(targetName) };
    }
    case 'press': {
      await p.keyboard.press(key || arg || 'Enter');
      await p.waitForTimeout(1000);
      return { cast: await shotAndCast(targetName) };
    }
    case 'shot': {
      return { cast: await shotAndCast(text || arg || targetName) };
    }
    case 'viewport': {
      const m = /^\s*(\d+)\s*x\s*(\d+)\s*$/.exec(text || arg);
      if (m) viewport = { width: Number(m[1]), height: Number(m[2]) };
      else if (key) { const [w,h] = key.split(',').map(Number); if(w&&h) viewport={width:w,height:h}; }
      else if (dx && dy) viewport = { width: Number(dx), height: Number(dy) };
      await p.setViewportSize(viewport);
      return { cast: await shotAndCast(targetName) };
    }
    default: throw new Error(`unknown command: ${cmd}`);
  }
}

async function processQueue() {
  if (processing) return;
  processing = true;
  while (queue.length) {
    const item = queue.shift();
    lastCmd = item;
    try { item.resolve(await runCommand(item)); }
    catch (e) { item.resolve({ err: e.message, __code: e.httpStatus || 0 }); }
  }
  processing = false;
}

function enqueue(cmdObj) {
  return new Promise(resolve => { queue.push({ ...cmdObj, resolve }); processQueue(); });
}

async function haApi(path, body) {
  return fetch(`${HA_BASE}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
}

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  const readBody = () => new Promise(r => { let d=''; req.on('data', c => d+=c); req.on('end', () => { try { r(JSON.parse(d||'{}')); } catch { r({}); } }); });
  const send = (o, code=0) => {
    const c = code || (o && o.__code) || 200;
    if (o && typeof o === 'object') delete o.__code;
    res.writeHead(c, {
      'Content-Type':'application/json',
      'Access-Control-Allow-Origin':'*',
      'Access-Control-Allow-Methods':'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers':'Content-Type',
    });
    res.end(JSON.stringify(o));
  };
  if (req.method === 'OPTIONS') { res.writeHead(204, {'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Allow-Headers':'Content-Type'}); return res.end(); }
  try {
    const b = req.method === 'POST' ? await readBody() : Object.fromEntries(u.searchParams);
    switch (u.pathname) {
      case '/cmd':     return send(await enqueue({ cmd: b.cmd, text: b.text, selector: b.selector, role: b.role, key: b.key, dx: b.dx, dy: b.dy, factor: b.factor, out: b.out, speaker: b.speaker }));
      case '/nav':     return send(await enqueue({ cmd: 'nav', text: b.url || b.key, out: b.out, speaker: b.speaker }));
      case '/select':
      case '/tick':  return send(await enqueue({ cmd: 'nav', text: b.key || b.url || 'smart-home' }));
      case '/shot':    return send({ cast: await shotAndCast(b.out || currentName) });
      case '/scroll':  return send(await enqueue({ cmd: 'scroll', text: b.dir, dx: b.dx, dy: b.dy, factor: b.factor, out: b.out, speaker: b.speaker }));
      case '/click':   return send(await enqueue({ cmd: 'click', text: b.text, selector: b.selector, role: b.role, out: b.out, speaker: b.speaker }));
      case '/type':    return send(await enqueue({ cmd: 'type', text: b.text, out: b.out, speaker: b.speaker }));
      case '/press':   return send(await enqueue({ cmd: 'press', key: b.key, out: b.out, speaker: b.speaker }));
      case '/back':    return send(await enqueue({ cmd: 'back', out: b.out, speaker: b.speaker }));
      case '/viewport':return send(await enqueue({ cmd: 'viewport', text: b.size, dx: b.width, dy: b.height, out: b.out, speaker: b.speaker }));
      case '/displays':{
        const data = fs.existsSync(`${OUT_DIR}/desktop/displays.json`)
          ? JSON.parse(fs.readFileSync(`${OUT_DIR}/desktop/displays.json`))
          : [];
        return send(data);
      }
      case '/start': {
        const d = b.d || u.searchParams.get('d');
        if (!d) return send({ ok: false, err: 'missing d' }, 400);
        await new Promise(res => {
          const sp = spawn('systemctl', ['--user', 'start', `cast-desktop@${d}.service`], {
            env: { ...process.env, DBUS_SESSION_BUS_ADDRESS: 'unix:path=/run/user/1000/bus' },
          });
          sp.on('close', res); sp.on('error', res);
        });
        return send({ ok: true, started: d });
      }
      case '/workspace': {
        const n = b.n || u.searchParams.get('n');
        if (!n) return send({ ok: false, err: 'missing n' }, 400);
        await setWorkspace(n);
        return send({ ok: true, workspace: n });
      }
      case '/thumb': {
        const ws = b.workspace || u.searchParams.get('workspace');
        if (ws) {
          const out = await thumbWorkspace(ws, b.mode || 'pad');
          return send({ ok: true, thumb: out.split('/').pop() });
        }
        const d = b.d || u.searchParams.get('d');
        if (!d) return send({ ok: false, err: 'missing d' }, 400);
        const out = await thumbDisplay(d);
        return send({ ok: true, thumb: out.split('/').pop() });
      }
      case '/state':   {
        const p = page && !page.isClosed() ? page : null;
        return send({
          url: p ? p.url() : null,
          title: p ? await p.title().catch(()=>null) : null,
          lastCmd,
          queue: queue.length,
          viewport,
          currentName,
        });
      }
      default: return send({ err: 'unknown path' }, 404);
    }
  } catch (e) { send({ err: String(e) }, 500); }
});

server.listen(PORT, process.env.BIND || '127.0.0.1', () => console.log(`cast-browser on ${process.env.BIND || '127.0.0.1'}:${PORT}`));

// Voice-command bridge: HA writes to input_text.tv_command; we poll, queue, execute, then clear.
const CMD_ENTITY = 'input_text.tv_command';
let lastProcessedCmd = '';
setInterval(async () => {
  try {
    const r = await haApi(`/api/states/${CMD_ENTITY}`);
    if (!r.ok) return;
    const { state } = await r.json();
    if (!state || state === 'unknown' || state === 'unavailable') return;
    const trimmed = state.trim();
    if (!trimmed || trimmed === lastProcessedCmd) return;
    const cleared = await haApi('/api/services/input_text/set_value', { entity_id: CMD_ENTITY, value: '' });
    if (!cleared.ok) return;
    lastProcessedCmd = trimmed;
    const [cmd, ...rest] = trimmed.split(/\s+/);
    const text = rest.join(' ');
    const out = (cmd === 'nav' || cmd === 'shot') ? (text || currentName) : undefined;
    await enqueue({ cmd, text, out });
  } catch (e) { console.error('cmd err:', e.message); }
}, 1500);

// Refresh the list of active X11 displays into www/ha/desktop/displays.json
// for the /local/ha/desktop/view.html multi-screen launcher.
async function updateDisplaysJson() {
  try {
    const socks = fs.readdirSync('/tmp/.X11-unix/').filter(f => f.startsWith('X')).map(f => f.slice(1));
    const lines = await new Promise(resolve => {
      const p = spawn('pgrep', ['-af', 'Xvfb|Xorg']);
      let out = '';
      p.stdout.on('data', c => { out += c; });
      p.on('error', () => resolve([]));
      p.on('close', () => resolve(out.split('\n').filter(Boolean)));
    });
    const info = {};
    for (const l of lines) {
      const m = l.match(/\B:(\d+)/);
      if (!m) continue;
      const n = m[1];
      info[n] = l.includes('Xvfb') ? 'Xvfb' : l.includes('Xorg') ? 'Xorg' : 'X';
    }
    // Filter :1 screen (covered by workspace cards), GDM greeters (:1024/:1025),
    // and anything we cannot actually capture.
    const skip = new Set(['1', '1024', '1025']);
    const screens = socks
      .filter(n => !skip.has(n))
      .map(n => ({ n, display: `:${n}`, kind: info[n] || 'X', active: true, type: 'screen', order: 0 }));
    // Add GNOME workspace entries on :1 (only if :1 is present)
    const workspaces = [];
    try {
      const numDesktops = Number((await new Promise((resolve, reject) => {
        const p = spawn('xprop', ['-root', '-notype', '32c', '_NET_NUMBER_OF_DESKTOPS']);
        let out = '';
        p.stdout.on('data', c => out += c);
        p.on('close', c => c === 0 ? resolve(out) : reject(new Error('xprop')));
      })).match(/=\s*(\d+)/)?.[1]);
      for (let i = 1; i <= numDesktops; i++) {
        workspaces.push({ n: String(i), display: X_DISPLAY, kind: 'workspace', active: true, type: 'workspace', order: 1, label: `Workspace ${i}` });
      }
    } catch (e) { /* no workspaces */ }
    const displays = [...screens, ...workspaces];
    displays.sort((a, b) => (a.order - b.order) || (Number(a.n) - Number(b.n)));
    fs.mkdirSync(`${OUT_DIR}/desktop`, { recursive: true });
    fs.writeFileSync(`${OUT_DIR}/desktop/displays.json`, JSON.stringify(displays, null, 2));
  } catch (e) { console.error('displays json err', e.message); }
}
updateDisplaysJson();
setInterval(() => updateDisplaysJson(), 30000);

// While the photos view is on screen, re-cast periodically so the TV
// follows the slideshow (the camera advances on its slide interval).
setInterval(async () => {
  if (currentName !== 'photos') return;
  try { await shotAndCast('photos'); } catch (e) { console.error('photos refresh err', e.message); }
}, 30000);

// Auto-refresh help.png when cast-help.html changes on disk.
fs.watchFile(`${OUT_DIR}/cast-help.html`, { interval: 2000 }, async () => {
  if (currentName === 'help') {
    try { await shotAndCast('help'); console.log('help updated'); } catch (e) { console.error('help watch err', e.message); }
  }
});


// Page watchdog: reload the live page every 10 min while idle. Slideshow/
// dashboard pages accumulate DOM and pushed the chromium tree past 3GiB —
// audit-cast was killing the whole service every ~5min (2026-09-29). A
// cheap reload clears the leak before the audit trips.
const PAGE_WATCHDOG_MS = 10 * 60 * 1000;
setInterval(async () => {
  try {
    if (!page || page.isClosed() || queue.length) return;
    const url = page.url();
    if (!url || url === "about:blank") return;
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    console.log("page watchdog: reloaded", url.slice(0, 80));
  } catch (e) { console.error("page watchdog err", e.message); }
}, PAGE_WATCHDOG_MS);
