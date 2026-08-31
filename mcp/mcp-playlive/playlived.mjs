#!/usr/bin/env node
/**
 * playlived — multi-AI browser session daemon.
 *
 * Long-running HTTP server that owns Chrome/Playwright sessions and exposes
 * them by session ID.  Multiple MCP clients can talk to the same daemon and
 * share or isolate sessions.
 */
import http from 'http';
import { URL } from 'url';
import { chromium } from 'playwright';
import { randomBytes } from 'crypto';

const PORT = process.env.PLAYLIVED_PORT || 9230;
const DEFAULT_REMOTE_CDP = process.env.PLAYLIVED_REMOTE_CDP || 'http://127.0.0.1:9223';
const DEFAULT_LOCAL_CDP = process.env.PLAYLIVED_LOCAL_CDP || 'http://localhost:9222';

const sessions = new Map();
const stash = new Map();

function fail(res, code, msg) {
  if (res.headersSent) return;
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ ok: false, error: msg }));
}

function success(res, data) {
  if (res.headersSent) return;
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ ok: true, ...data }));
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', d => { body += d; });
    req.on('end', () => {
      if (!body) return resolve(null);
      try { resolve(JSON.parse(body)); } catch { reject(new Error('invalid JSON')); }
    });
  });
}

function sessionSummary(s) {
  return {
    id: s.id,
    type: s.type,
    target: s.target,
    cdpUrl: s.cdpUrl,
    url: s.page && s.page.url ? s.page.url() : null,
    createdAt: s.createdAt,
  };
}

async function getBrowser(cdpUrl) {
  return await chromium.connectOverCDP(cdpUrl, { slowMo: 0 });
}

async function createSession(type, target, remote_url, reuse_context = false, attach_url = null) {
  const cdpUrl = (target === 'remote')
    ? (remote_url || DEFAULT_REMOTE_CDP)
    : (remote_url || DEFAULT_LOCAL_CDP);

  let browser, context, page, attached = false;
  if (type === 'playwright-headless') {
    if (target === 'remote') {
      throw new Error('playwright-headless cannot be remote');
    }
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    page = await context.newPage();
  } else {
    browser = await getBrowser(cdpUrl);
    if (attach_url) {
      const existing = browser.contexts().flatMap(c => c.pages());
      page = existing.find(p => p.url().includes(attach_url));
      if (page) {
        context = page.context();
        attached = true;
      }
    }
    if (!page) {
      if (reuse_context) {
        context = browser.contexts()[0];
        if (!context) context = await browser.newContext({ viewport: null });
      } else {
        context = await browser.newContext({ viewport: null });
      }
      page = await context.newPage();
    }
  }

  const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const session = { id, type, target, cdpUrl, browser, context, page, createdAt: Date.now(), reuse_context, attached };
  sessions.set(id, session);
  return { session_id: id, type, target, cdpUrl, reuse_context, attached };
}

async function closeSession(id) {
  const s = sessions.get(id);
  if (!s) return { closed: false, error: 'session not found' };
  try {
    if (s.attached) {
      // do not close an existing tab/page we attached to
    } else if (s.reuse_context) {
      await s.page.close();
    } else {
      await s.context.close();
      await s.browser.close();
    }
  } catch {}
  sessions.delete(id);
  return { closed: true, id };
}

async function doAction(id, action, body) {
  const s = sessions.get(id);
  if (!s) throw new Error('session not found');
  const page = s.page;

  switch (action) {
    case 'state':
      return { url: page.url(), title: await page.title() };
    case 'navigate':
      await page.goto(body.url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      return { url: page.url(), title: await page.title() };
    case 'click':
      await page.locator(body.selector).click();
      return { clicked: body.selector };
    case 'fill':
      await page.locator(body.selector).fill(body.value);
      return { filled: body.selector };
    case 'select':
      await page.selectOption(body.selector, body.value);
      return { selected: body.selector };
    case 'eval':
      return { result: await page.evaluate(body.script) };
    case 'screenshot':
      if (body.path) {
        await page.screenshot({ path: body.path, fullPage: body.fullPage || false });
        return { path: body.path };
      }
      const buf = await page.screenshot({ fullPage: body.fullPage || false });
      return { base64: buf.toString('base64'), mimeType: 'image/png' };
    case 'upload': {
      const { selector, base64: b64, filename, mimeType, stash_id } = body || {};
      if (!selector || typeof selector !== 'string') throw new Error('upload requires a string selector');
      
      let buf;
      if (stash_id) {
        const entry = stash.get(stash_id);
        if (!entry) throw new Error(`stash_id ${stash_id} not found`);
        buf = Buffer.from(entry.base64, 'base64');
      } else if (b64) {
        if (typeof b64 !== 'string') throw new Error('upload requires a base64 string');
        buf = Buffer.from(b64, 'base64');
      } else {
        throw new Error('upload requires either base64 or stash_id');
      }
      
      const uploadFilename = filename || (stash_id ? stash.get(stash_id).filename : 'upload.bin');
      const uploadMimeType = mimeType || (stash_id ? stash.get(stash_id).mimeType : 'application/octet-stream');
      
      await page.locator(selector).setInputFiles([{ name: uploadFilename, mimeType: uploadMimeType, buffer: buf }]);
      return { uploaded: selector, filename: uploadFilename, mimeType: uploadMimeType, size: buf.length };
    }
    case 'drop': {
      const { selector, base64: b64, filename, mimeType, stash_id } = body || {};
      if (!selector || typeof selector !== 'string') throw new Error('drop requires a string selector');

      let buf;
      if (stash_id) {
        const entry = stash.get(stash_id);
        if (!entry) throw new Error(`stash_id ${stash_id} not found`);
        buf = Buffer.from(entry.base64, 'base64');
      } else if (b64) {
        if (typeof b64 !== 'string') throw new Error('drop requires a base64 string');
        buf = Buffer.from(b64, 'base64');
      } else {
        throw new Error('drop requires either base64 or stash_id');
      }

      const dropFilename = filename || (stash_id ? stash.get(stash_id).filename : 'drop.bin');
      const dropMimeType = mimeType || (stash_id ? stash.get(stash_id).mimeType : 'application/octet-stream');
      const dataUrl = `data:${dropMimeType};base64,${buf.toString('base64')}`;

      const script = `
        (async () => {
          const sel = ${JSON.stringify(selector)};
          const url = ${JSON.stringify(dataUrl)};
          const fname = ${JSON.stringify(dropFilename)};
          const mtype = ${JSON.stringify(dropMimeType)};
          const el = document.querySelector(sel);
          if (!el) throw new Error('drop target not found: ' + sel);
          const blob = await (await fetch(url)).blob();
          const file = new File([blob], fname, { type: mtype });
          const dt = new DataTransfer();
          dt.items.add(file);
          for (const type of ['dragenter', 'dragover', 'drop']) {
            const ev = new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt });
            el.dispatchEvent(ev);
          }
          return { dropped: sel, filename: fname, size: file.size };
        })()
      `;
      const result = await page.evaluate(script);
      return result;
    }
    default:
      throw new Error(`unknown action: ${action}`);
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  let body = null;
  try { body = await parseBody(req); } catch (e) { return fail(res, 400, e.message); }

  try {
    if (req.method === 'POST' && url.pathname === '/sessions') {
      const { type = 'chrome-live', target = 'remote', remote_url, reuse_context, attach_url } = body || {};
      if (!['chrome-live', 'playwright-chrome', 'playwright-headless'].includes(type)) {
        return fail(res, 400, 'type must be chrome-live, playwright-chrome, or playwright-headless');
      }
      if (!['local', 'remote'].includes(target)) {
        return fail(res, 400, 'target must be local or remote');
      }
      const result = await createSession(type, target, remote_url, !!reuse_context, attach_url || null);
      return success(res, result);
    }

    if (req.method === 'GET' && url.pathname === '/sessions') {
      return success(res, { sessions: Array.from(sessions.values()).map(sessionSummary) });
    }

    const mDelete = url.pathname.match(/^\/sessions\/([^/]+)$/);
    if (req.method === 'DELETE' && mDelete) {
      return success(res, await closeSession(mDelete[1]));
    }

    const mAction = url.pathname.match(/^\/sessions\/([^/]+)\/(.+)$/);
    if (req.method === 'POST' && mAction) {
      const [, id, action] = mAction;
      const result = await doAction(id, action, body || {});
      return success(res, result);
    }

    if (req.method === 'POST' && url.pathname === '/stash') {
      const { base64, filename, mimeType } = body || {};
      if (!base64 || typeof base64 !== 'string') throw new Error('stash requires a base64 string');
      if (!filename || typeof filename !== 'string') throw new Error('stash requires a filename');
      if (!mimeType || typeof mimeType !== 'string') throw new Error('stash requires a mimeType');
      const id = randomBytes(16).toString('hex');
      stash.set(id, { base64, filename, mimeType, createdAt: Date.now() });
      return success(res, { stash_id: id, filename, mimeType });
    }

    const mStash = url.pathname.match(/^\/stash\/([^/]+)$/);
    if (req.method === 'GET' && mStash) {
      const id = mStash[1];
      const entry = stash.get(id);
      if (!entry) return fail(res, 404, 'stash entry not found');
      return success(res, { stash_id: id, filename: entry.filename, mimeType: entry.mimeType, base64: entry.base64 });
    }

    if (req.method === 'DELETE' && mStash) {
      const id = mStash[1];
      const deleted = stash.delete(id);
      return success(res, { deleted, stash_id: id });
    }

    return fail(res, 404, 'not found');
  } catch (e) { fail(res, 500, e.message); }
});

function closeAll() {
  for (const s of sessions.values()) {
    try { s.context.close().catch(() => {}); } catch {}
    try { s.browser.close().catch(() => {}); } catch {}
  }
  sessions.clear();
}

server.listen(PORT, () => {
  console.log(`playlived listening on http://0.0.0.0:${PORT}`);
});

['SIGTERM', 'SIGINT'].forEach(sig => process.on(sig, () => {
  closeAll();
  server.close(() => process.exit(0));
}));
