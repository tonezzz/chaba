#!/usr/bin/env node
"use strict";

import { createServer } from "http";
import { WebSocket, WebSocketServer } from "ws";

const PORT = parseInt(process.env.GEMINI_MIC_PORT || "3009", 10);
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_LIVE_MODEL = process.env.GEMINI_LIVE_MODEL || "gemini-3.1-flash-live-preview";

const GEMINI_WS_URL = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=${GEMINI_API_KEY}`;

function log(...args) {
  console.log("[gemini-mic]", ...args);
}

class GeminiSession {
  constructor(clientWs) {
    this.clientWs = clientWs;
    this.geminiWs = null;
  }

  connect() {
    if (!GEMINI_API_KEY) {
      this.sendToClient({ type: "error", message: "GEMINI_API_KEY not configured" });
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      this.geminiWs = new WebSocket(GEMINI_WS_URL);
      this.geminiWs.on("open", () => {
        log("connected to Gemini Live API");
        this.geminiWs.send(
          JSON.stringify({
            setup: {
              model: `models/${GEMINI_LIVE_MODEL}`,
              generationConfig: { responseModalities: ["AUDIO"] },
              inputAudioTranscription: {},
              outputAudioTranscription: {},
            },
          })
        );
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
        this.sendToClient({
          type: "status",
          message: "disconnected",
          code,
          reason: reason?.toString?.(),
        });
      });
    });
  }

  sendToClient(msg) {
    if (this.clientWs.readyState === 1) this.clientWs.send(JSON.stringify(msg));
  }

  onGeminiMessage(data) {
    const text = data.toString("utf8");
    let msg;
    try {
      msg = JSON.parse(text);
    } catch {
      log("non-JSON Gemini message", text.slice(0, 200));
      return;
    }
    if (msg.toolCall) {
      const responses = (msg.toolCall.functionCalls || []).map((fc) => ({
        id: fc.id,
        name: fc.name,
        response: { error: "No tools available in gemini-mic-test" },
      }));
      this.geminiWs.send(JSON.stringify({ toolResponse: { functionResponses: responses } }));
      this.sendToClient({ type: "tool-call", calls: msg.toolCall.functionCalls, responses });
      return;
    }
    if (msg.serverContent) {
      this.sendToClient({ type: "server-content", content: msg.serverContent });
    }
  }

  onClientMessage(msg) {
    if (!this.geminiWs || this.geminiWs.readyState !== WebSocket.OPEN) return;
    if (msg.type === "audio") {
      this.geminiWs.send(
        JSON.stringify({
          realtimeInput: { audio: { data: msg.data, mimeType: "audio/pcm;rate=16000" } },
        })
      );
    } else if (msg.type === "text") {
      this.geminiWs.send(JSON.stringify({ realtimeInput: { text: msg.text } }));
    } else if (msg.type === "activity-start") {
      this.geminiWs.send(JSON.stringify({ realtimeInput: { activityStart: {} } }));
    } else if (msg.type === "activity-end") {
      this.geminiWs.send(JSON.stringify({ realtimeInput: { activityEnd: {} } }));
    }
  }

  close() {
    if (this.geminiWs) {
      this.geminiWs.terminate();
      this.geminiWs = null;
    }
  }
}

const server = createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  res.writeHead(404);
  res.end("not found");
});

const wss = new WebSocketServer({ server, path: "/ws" });

wss.on("connection", (ws) => {
  log("client connected");
  const session = new GeminiSession(ws);
  session.connect().catch((err) => log("session connect error:", err.message));

  ws.on("message", (data) => {
    try {
      session.onClientMessage(JSON.parse(data.toString("utf8")));
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
