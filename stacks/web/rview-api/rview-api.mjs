#!/usr/bin/env node
"use strict";

import { createServer } from "http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.RVIEW_API_PORT || "3007", 10);
const STATE_FILE = process.env.RVIEW_STATE_FILE || join(__dirname, "state.json");

let state = { views: {} };

function ensureStateDir() {
  const dir = dirname(STATE_FILE);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function loadState() {
  if (existsSync(STATE_FILE)) {
    try {
      const loaded = JSON.parse(readFileSync(STATE_FILE, "utf8"));
      if (loaded && typeof loaded === "object" && !Array.isArray(loaded) && loaded.views) {
        state = loaded;
      }
    } catch (e) {
      console.error("rview load error:", e.message);
    }
  }
}

function saveState() {
  try {
    ensureStateDir();
    writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (e) {
    console.error("rview save error:", e.message);
  }
}

function now() {
  return new Date().toISOString();
}

function inferMediaType(url, mediaType) {
  if (mediaType && mediaType !== "auto") return mediaType;
  if (!url) return "image";
  const lower = url.toLowerCase();
  if (lower.startsWith("<")) return "html";
  if (/\.(mp4|webm|mov|mkv|m3u8|mpd)$/.test(lower)) return "video";
  if (/\.(mp3|wav|ogg|aac|m4a|flac)$/.test(lower)) return "audio";
  if (/\.(pdf)$/.test(lower)) return "pdf";
  if (/\.(jpg|jpeg|png|gif|webp|svg|bmp)$/.test(lower)) return "image";
  if (lower.includes("youtube") || lower.includes("youtu.be")) return "iframe";
  if (/\.(html?|php)$/.test(lower)) return "iframe";
  return "image";
}

function getOrCreateView(viewId) {
  if (!state.views[viewId]) {
    state.views[viewId] = {
      view_id: viewId,
      display_name: viewId,
      current_item: null,
      queue: [],
      history: [],
      state: "stopped",
      volume: 1.0,
      fullscreen: false,
      loop: false,
      shuffle: false,
      slideshow: false,
      slideshow_interval: 5,
      position: 0,
      created_at: now(),
      updated_at: now(),
    };
  }
  return state.views[viewId];
}

function viewSummary(view) {
  return {
    view_id: view.view_id,
    display_name: view.display_name,
    current_url: view.current_item ? view.current_item.url : null,
    media_type: view.current_item ? view.current_item.media_type : null,
    title: view.current_item ? view.current_item.title : null,
    state: view.state,
  };
}

function fullView(view) {
  return { ...view };
}

function setCurrent(view, item) {
  view.current_item = item;
  view.updated_at = now();
}

function createView(viewId, displayName) {
  const view = getOrCreateView(viewId);
  if (displayName) view.display_name = displayName;
  view.updated_at = now();
  saveState();
  return { ok: true, view: fullView(view) };
}

function show(viewId, url, title, mediaType, enqueue, content) {
  const view = getOrCreateView(viewId);
  const mt = inferMediaType(url, mediaType);
  const item = {
    url,
    title: title || "",
    media_type: mt,
    content: mt === "html" ? (content || url) : undefined,
    added_at: now(),
  };
  if (enqueue) {
    view.queue.push(item);
    if (!view.current_item) {
      setCurrent(view, view.queue.shift());
      view.state = "playing";
    }
  } else {
    if (view.current_item) view.history.push(view.current_item);
    view.queue = [];
    setCurrent(view, item);
    view.state = "playing";
  }
  saveState();
  return { ok: true, view: fullView(view) };
}

function queueView(viewId, items, mode) {
  const view = getOrCreateView(viewId);
  const parsed = (items || []).map((it) => ({
    url: it.url,
    title: it.title || "",
    media_type: inferMediaType(it.url, it.media_type),
    content: it.content,
    added_at: now(),
  }));
  if (mode === "append") {
    view.queue.push(...parsed);
    if (!view.current_item && view.queue.length) {
      setCurrent(view, view.queue.shift());
      view.state = "playing";
    }
  } else {
    if (view.current_item) view.history.push(view.current_item);
    view.queue = parsed;
    setCurrent(view, view.queue.shift() || null);
    view.state = view.current_item ? "playing" : "stopped";
  }
  saveState();
  return { ok: true, view: fullView(view) };
}

function advance(view) {
  if (view.loop && !view.queue.length && view.history.length) {
    view.queue = view.history.splice(0);
  }
  if (!view.queue.length) return;
  if (view.shuffle && view.queue.length > 1) {
    const idx = Math.floor(Math.random() * view.queue.length);
    const [item] = view.queue.splice(idx, 1);
    if (view.current_item) view.history.push(view.current_item);
    setCurrent(view, item);
    view.state = "playing";
    return;
  }
  if (view.current_item) view.history.push(view.current_item);
  setCurrent(view, view.queue.shift());
  view.state = "playing";
}

function retreat(view) {
  if (!view.history.length) return;
  if (view.current_item) view.queue.unshift(view.current_item);
  setCurrent(view, view.history.pop());
  view.state = "playing";
}

function control(viewId, action, value) {
  const view = getOrCreateView(viewId);
  switch (action) {
    case "play":
      view.state = "playing";
      break;
    case "pause":
      view.state = "paused";
      break;
    case "stop":
      view.state = "stopped";
      break;
    case "next":
      advance(view);
      break;
    case "prev":
      retreat(view);
      break;
    case "seek":
      view.position = Number(value) || 0;
      break;
    case "volume":
      if (value !== undefined && value !== null) {
        view.volume = Math.max(0, Math.min(1, Number(value)));
      }
      break;
    case "fullscreen":
      view.fullscreen = value !== undefined && value !== null ? Boolean(value) : !view.fullscreen;
      break;
    case "loop":
      view.loop = value !== undefined && value !== null ? Boolean(value) : !view.loop;
      break;
    case "shuffle":
      view.shuffle = value !== undefined && value !== null ? Boolean(value) : !view.shuffle;
      break;
    case "slideshow":
      view.slideshow = value !== undefined && value !== null ? Boolean(value) : !view.slideshow;
      if (value && !isNaN(Number(value)) && Number(value) > 0) {
        view.slideshow_interval = Number(value);
      }
      break;
    case "stop_slideshow":
      view.slideshow = false;
      break;
    case "clear_queue":
      view.queue = [];
      break;
    default:
      return { ok: false, error: `unknown action: ${action}` };
  }
  view.updated_at = now();
  saveState();
  return { ok: true, view: fullView(view) };
}

function listViews() {
  return { ok: true, views: Object.values(state.views).map(viewSummary) };
}

function statusView(viewId) {
  const view = getOrCreateView(viewId);
  return { ok: true, view: fullView(view) };
}

function deleteView(viewId) {
  if (!state.views[viewId]) return { ok: false, error: "view not found" };
  delete state.views[viewId];
  saveState();
  return { ok: true };
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

function sendJson(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(data));
}

const server = createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (!["/state.php", "/state"].includes(url.pathname)) {
    sendJson(res, 404, { ok: false, error: "not found" });
    return;
  }

  try {
    if (req.method === "GET") {
      const action = url.searchParams.get("action");
      const viewId = url.searchParams.get("view_id");
      if (action === "list") {
        sendJson(res, 200, listViews());
      } else if (action === "status") {
        if (!viewId) {
          sendJson(res, 400, { ok: false, error: "view_id required" });
          return;
        }
        sendJson(res, 200, statusView(viewId));
      } else {
        sendJson(res, 400, { ok: false, error: "unknown GET action" });
      }
      return;
    }

    if (req.method === "POST") {
      const body = await readBody(req);
      const payload = body ? JSON.parse(body) : {};
      const action = payload.action;
      const viewId = payload.view_id;
      let result;

      switch (action) {
        case "create":
          result = createView(viewId, payload.display_name);
          break;
        case "show":
          result = show(viewId, payload.url, payload.title, payload.media_type, payload.enqueue, payload.content);
          break;
        case "queue":
          result = queueView(viewId, payload.items, payload.mode || "replace");
          break;
        case "control":
          result = control(viewId, payload.command, payload.value);
          break;
        case "status":
          result = statusView(viewId);
          break;
        case "delete":
          result = deleteView(viewId);
          break;
        default:
          result = { ok: false, error: `unknown action: ${action}` };
      }
      sendJson(res, result.ok ? 200 : 400, result);
      return;
    }

    sendJson(res, 405, { ok: false, error: "method not allowed" });
  } catch (e) {
    console.error("rview-api request error:", e);
    sendJson(res, 500, { ok: false, error: e.message });
  }
});

loadState();
server.listen(PORT, "0.0.0.0", () => {
  console.log(`rview-api listening on port ${PORT}, state file ${STATE_FILE}`);
});
