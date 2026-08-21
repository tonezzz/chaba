#!/usr/bin/env node
"use strict";

import { createServer } from "http";
import { spawn } from "child_process";
import { WebSocket, WebSocketServer } from "ws";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { searchWeb } from "./search.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.GEMINI_LIVE_PORT || "3002", 10);
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_LIVE_MODEL = process.env.GEMINI_LIVE_MODEL || "gemini-3.1-flash-live-preview";
const RVIEW_API_URL = process.env.RVIEW_API_URL || "http://localhost:8080/apps/rview/api/state";

const GEMINI_WS_URL = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=${GEMINI_API_KEY}`;

function log(...args) {
  console.log("[gemini-live]", ...args);
}

const FUNCTION_DECLARATIONS = [
  {
    name: "rview_list_views",
    description: "List all rview sessions/views.",
    parameters: { type: "object", properties: {} },
  },
  {
    name: "rview_create_view",
    description: "Create a new view session.",
    parameters: {
      type: "object",
      properties: {
        view_id: { type: "string" },
        display_name: { type: "string" },
      },
      required: ["view_id"],
    },
  },
  {
    name: "rview_show",
    description: "Show media, a URL, or raw HTML in a view. Use media_type html with content for raw HTML. If the user asks to find or search for content, call web_search first, then pass the chosen result URL to rview_show. Otherwise, use only URLs the user provides or URLs you are certain are publicly reachable.",
    parameters: {
      type: "object",
      properties: {
        view_id: { type: "string" },
        url: { type: "string" },
        title: { type: "string" },
        media_type: { type: "string", enum: ["auto", "image", "video", "audio", "iframe", "pdf", "html"], default: "auto" },
        content: { type: "string", description: "Raw HTML content when media_type is html" },
        enqueue: { type: "boolean", default: false },
      },
      required: ["view_id", "url"],
    },
  },
  {
    name: "rview_queue",
    description: "Set or append to a view's playlist.",
    parameters: {
      type: "object",
      properties: {
        view_id: { type: "string" },
        items: { type: "array", items: { type: "object" } },
        mode: { type: "string", enum: ["replace", "append"], default: "replace" },
      },
      required: ["view_id", "items"],
    },
  },
  {
    name: "rview_control",
    description: "Control playback for a view.",
    parameters: {
      type: "object",
      properties: {
        view_id: { type: "string" },
        action: { type: "string", enum: ["play", "pause", "stop", "next", "prev", "seek", "volume", "fullscreen", "loop", "shuffle", "slideshow", "stop_slideshow", "clear_queue"] },
        value: {},
      },
      required: ["view_id", "action"],
    },
  },
  {
    name: "rview_status",
    description: "Get the current state of a view.",
    parameters: {
      type: "object",
      properties: { view_id: { type: "string" } },
      required: ["view_id"],
    },
  },
  {
    name: "rview_delete_view",
    description: "Delete a view session.",
    parameters: {
      type: "object",
      properties: { view_id: { type: "string" } },
      required: ["view_id"],
    },
  },
  {
    name: "web_search",
    description: "Search the web for content. Returns result URLs that can be passed to rview_show or rview_queue. For images, use the 'image' field of a result as the URL for rview_show with media_type 'image'. For videos, use embed_url as an iframe or a direct .mp4 url with media_type 'video'. For web pages, use media_type 'iframe'.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query" },
        type: { type: "string", enum: ["web", "images", "videos"], default: "web" },
        max_results: { type: "integer", default: 5, description: "Number of results, 1-20" },
      },
      required: ["query"],
    },
  },
];

class McpRviewClient {
  constructor() {
    this.proc = null;
    this.pending = new Map();
    this.id = 0;
    this.ready = false;
    this.buffer = "";
  }

  start() {
    return new Promise((resolve, reject) => {
      const proc = spawn("python3", [join(__dirname, "..", "..", "..", "scripts", "mcp_rview", "server.py")], {
        env: { ...process.env, RVIEW_API_URL: RVIEW_API_URL },
        stdio: ["pipe", "pipe", "pipe"],
      });
      this.proc = proc;
      proc.stdout.on("data", (data) => this._onData(data));
      proc.stderr.on("data", (data) => log("mcp-rview stderr:", data.toString().trim()));
      proc.on("error", reject);
      proc.on("close", (code) => log("mcp-rview exited", code));

      // initialize
      this.call("initialize", {}).then(() => {
        this.ready = true;
        resolve();
      });
    });
  }

  _onData(chunk) {
    this.buffer += chunk.toString("utf8");
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop();
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const msg = JSON.parse(trimmed);
        if (msg.id !== undefined && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) {
            reject(new Error(msg.error.message));
          } else {
            resolve(msg.result);
          }
        }
      } catch (e) {
        log("mcp-rview non-JSON line:", trimmed);
      }
    }
  }

  call(method, params) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      const msg = { jsonrpc: "2.0", id, method, params };
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify(msg) + "\n");
      // timeout
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error("mcp-rview timeout"));
        }
      }, 10000);
    });
  }

  async invokeTool(name, arguments_) {
    const result = await this.call("tools/call", { name, arguments: arguments_ });
    const text = result?.content?.[0]?.text;
    if (!text) return { ok: false, error: "no text result from mcp-rview" };
    try {
      return JSON.parse(text);
    } catch (e) {
      return { ok: true, raw: text };
    }
  }

  stop() {
    if (this.proc && !this.proc.killed) this.proc.kill();
  }
}

class GeminiSession {
  constructor(clientWs, mcp) {
    this.clientWs = clientWs;
    this.mcp = mcp;
    this.geminiWs = null;
    this.model = GEMINI_LIVE_MODEL;
  }

  connect() {
    if (!GEMINI_API_KEY) {
      this.sendToClient({ type: "error", message: "GEMINI_API_KEY not configured" });
      return;
    }
    return new Promise((resolve, reject) => {
      this.geminiWs = new WebSocket(GEMINI_WS_URL);
      this.geminiWs.on("open", () => {
        log("connected to Gemini Live API");
        const setup = {
          setup: {
            model: `models/${this.model}`,
            generationConfig: {
              responseModalities: ["AUDIO"],
            },
            inputAudioTranscription: {},
            outputAudioTranscription: {},
            systemInstruction: {
              parts: [
                {
                  text: `You are a voice assistant controlling a remote media view called RView.
You can create views, show media URLs, queue playlists, control playback, render raw HTML, and run slideshows using the provided tools.
Rules:
- If the user asks to search for or find content, call web_search first, then use rview_show or rview_queue with a result URL.
- For image search results, use the "image" field as the URL and set media_type "image"; for video results use embed_url as iframe or a direct .mp4 URL as video; for web pages use media_type "iframe".
- Otherwise, use only URLs the user provides or URLs you are certain are publicly reachable. Do not invent URLs.
- For raw HTML or dashboards, call rview_show with media_type "html" and pass the HTML in the "content" field.
- For a slideshow, queue multiple images with rview_queue then call rview_control with action "slideshow" and value as seconds per slide.
- When the user asks to show, play, pause, stop, queue, or start a slideshow, call the matching rview_* tool.
- Always confirm briefly what you are doing, then wait for further instructions.`,
                },
              ],
            },
            tools: [{ functionDeclarations: FUNCTION_DECLARATIONS }],
          },
        };
        this.geminiWs.send(JSON.stringify(setup));
        this.sendToClient({ type: "status", message: "connected" });
        resolve();
      });
      this.geminiWs.on("message", (data) => this.onGeminiMessage(data));
      this.geminiWs.on("error", (err) => {
        log("Gemini WS error:", err.message);
        this.sendToClient({ type: "error", message: err.message });
        reject(err);
      });
      this.geminiWs.on("close", (code, reason) => {
        log("Gemini WS closed", code, reason?.toString?.() || "");
        this.sendToClient({ type: "status", message: "disconnected", code, reason: reason?.toString?.() });
      });
    });
  }

  sendToClient(msg) {
    if (this.clientWs.readyState === 1) {
      this.clientWs.send(JSON.stringify(msg));
    }
  }

  async onGeminiMessage(data) {
    const text = data.toString("utf8");
    let msg;
    try {
      msg = JSON.parse(text);
    } catch (e) {
      log("non-JSON Gemini message", text.slice(0, 200));
      return;
    }
    if (msg.toolCall) {
      const functionResponses = [];
      for (const fc of msg.toolCall.functionCalls || []) {
        try {
          const result = await this.invokeTool(fc.name, fc.args || {});
          functionResponses.push({ id: fc.id, name: fc.name, response: { result } });
        } catch (e) {
          functionResponses.push({ id: fc.id, name: fc.name, response: { error: e.message } });
        }
      }
      const toolResponse = { toolResponse: { functionResponses } };
      this.geminiWs.send(JSON.stringify(toolResponse));
      this.sendToClient({ type: "tool-call", calls: msg.toolCall.functionCalls, responses: functionResponses });
      return;
    }
    // forward server content to client
    if (msg.serverContent) {
      this.sendToClient({ type: "server-content", content: msg.serverContent });
    }
  }

  onClientMessage(msg) {
    if (!this.geminiWs || this.geminiWs.readyState !== WebSocket.OPEN) return;
    if (msg.type === "audio") {
      this.geminiWs.send(
        JSON.stringify({
          realtimeInput: {
            audio: { data: msg.data, mimeType: "audio/pcm;rate=16000" },
          },
        })
      );
    } else if (msg.type === "video") {
      this.geminiWs.send(
        JSON.stringify({
          realtimeInput: {
            video: { data: msg.data, mimeType: "image/jpeg" },
          },
        })
      );
    } else if (msg.type === "text") {
      this.geminiWs.send(
        JSON.stringify({
          realtimeInput: { text: msg.text },
        })
      );
    } else if (msg.type === "activity-start") {
      this.geminiWs.send(JSON.stringify({ realtimeInput: { activityStart: {} } }));
    } else if (msg.type === "activity-end") {
      this.geminiWs.send(JSON.stringify({ realtimeInput: { activityEnd: {} } }));
    } else if (msg.type === "client-content") {
      this.geminiWs.send(JSON.stringify({ clientContent: msg.clientContent }));
    }
  }

  async invokeTool(name, args) {
    if (name === "web_search") {
      return searchWeb(args);
    }
    return this.mcp.invokeTool(name, args);
  }

  close() {
    if (this.geminiWs) {
      this.geminiWs.terminate();
      this.geminiWs = null;
    }
  }
}

async function main() {
  const mcp = new McpRviewClient();
  await mcp.start();

  const server = createServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, ready: mcp.ready }));
      return;
    }
    res.writeHead(404);
    res.end("not found");
  });

  const wss = new WebSocketServer({ server, path: "/ws" });

  wss.on("connection", (ws) => {
    log("client connected");
    const session = new GeminiSession(ws, mcp);
    session.connect().catch((err) => log("session connect error:", err.message));

    ws.on("message", (data) => {
      try {
        const msg = JSON.parse(data.toString("utf8"));
        session.onClientMessage(msg);
      } catch (e) {
        log("client non-JSON message", e.message);
      }
    });

    ws.on("close", () => {
      log("client disconnected");
      session.close();
    });
  });

  server.listen(PORT, "0.0.0.0", () => {
    log("listening on port", PORT, "model", GEMINI_LIVE_MODEL);
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
