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
