#!/usr/bin/env node
"use strict";

import { WebSocketServer } from "ws";

const PORT = parseInt(process.env.INPUT_BRIDGE_PORT || "3010", 10);
const PING_INTERVAL_MS = 30000;

const rooms = new Map();

function leaveRoom(ws) {
  const room = ws.room;
  if (!room || !rooms.has(room)) return;
  const clients = rooms.get(room);
  clients.delete(ws);
  if (clients.size === 0) rooms.delete(room);
  ws.room = null;
}

function joinRoom(ws, room) {
  leaveRoom(ws);
  room = String(room || "default");
  ws.room = room;
  if (!rooms.has(room)) rooms.set(room, new Set());
  rooms.get(room).add(ws);
}

function broadcast(ws, data) {
  const room = ws.room || "default";
  const clients = rooms.get(room);
  if (!clients) return;
  const msg = typeof data === "string" ? data : JSON.stringify(data);
  for (const client of clients) {
    if (client !== ws && client.readyState === 1) {
      client.send(msg);
    }
  }
}

function presence(room) {
  const clients = rooms.get(room);
  return clients ? clients.size : 0;
}

const wss = new WebSocketServer({ port: PORT });

wss.on("connection", (ws) => {
  joinRoom(ws, "default");

  ws.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw.toString("utf8"));
    } catch (e) {
      return;
    }

    if (msg && msg.type === "join") {
      const room = msg.room || "default";
      joinRoom(ws, room);
      ws.send(JSON.stringify({ type: "presence", room, count: presence(room) }));
      return;
    }

    broadcast(ws, msg);
  });

  ws.on("close", () => leaveRoom(ws));
  ws.on("error", (e) => console.error("[input-bridge] client error", e.message));
});

setInterval(() => {
  for (const [, clients] of rooms) {
    for (const ws of clients) {
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }
  }
}, PING_INTERVAL_MS);

console.log(`[input-bridge] WebSocket relay listening on ws://0.0.0.0:${PORT}`);
console.log(`[input-bridge] Rooms: default; set room via {type:"join", room:"..."}`);
