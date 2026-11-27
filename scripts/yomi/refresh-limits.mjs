// Shared bounds for the idc03 active-refresh sweep (MEM-1510).
// Keep these pure and dependency-free so they can be unit-tested and imported
// from both the HTTP refresh driver and the message-fetching worker.

export function limitFromEnv(name, fallback, { min = 1, max = Number.MAX_SAFE_INTEGER } = {}) {
  const raw = process.env[name];
  if (raw == null || raw === "") return fallback;
  const parsed = parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function truncateMessages(messages, max) {
  if (!Array.isArray(messages) || max < 1) return [];
  return messages.slice(0, max);
}

export function capMediaMessages(messages, max) {
  if (!Array.isArray(messages) || max < 1) return [];
  return messages
    .filter((m) => /^(image|video|audio|file)$/.test(String(m?.mediaType || "").toLowerCase()))
    .slice(0, max);
}

// Env for the mcpb worker spawned through StdioClientTransport. The MCP SDK
// only inherits a safe subset (HOME/LOGNAME/PATH/SHELL/TERM/USER), so the
// NODE_OPTIONS in yomi-api.env reaches yomi-api and its spawnNode() children
// but never run.mjs — the process that actually ballooned to ~2 GiB inside
// the yomi-api cgroup. Pass the heap ceiling explicitly; defaults keep the
// worker well under the container's --memory=2g while leaving headroom for
// yomi-api and the update-conversations parent.
export function mcpbTransportEnv() {
  const mb = limitFromEnv("YOMI_MCPB_MAX_OLD_SPACE_MB", 1024, { min: 256, max: 8192 });
  return { NODE_OPTIONS: `--max-old-space-size=${mb}` };
}
