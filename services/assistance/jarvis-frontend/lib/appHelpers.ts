export type SysSetCommand = { key: string; value: string; dryRun: boolean };
export type SysDedupeCommand = { dryRun: boolean; sort: boolean };
export type ToolInvoke = { name: string; args: Record<string, any> };
export type JsonToolRequest = { name: string; args: Record<string, any> };

export function normalizeComposerText(text: string): string {
  return String(text || "")
    .replace(/[\u00A0\u200B-\u200D\uFEFF]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function splitSentences(text: string): Array<{ t: string; complete: boolean }> {
  const raw = String(text || "").replace(/\r\n/g, "\n");
  const parts = raw.split(/\n+/g);
  const out: Array<{ t: string; complete: boolean }> = [];
  for (const p of parts) {
    const s = String(p || "").trim();
    if (!s) continue;
    const chunks = s.split(/(?<=[.!?。！？])\s+/g);
    for (const c of chunks) {
      const cc = String(c || "").trim();
      if (!cc) continue;
      const complete = /[.!?。！？]$/.test(cc);
      out.push({ t: cc, complete });
    }
  }
  if (!out.length && raw.trim()) out.push({ t: raw.trim(), complete: /[.!?。！？]$/.test(raw.trim()) });
  return out;
}

export function parseSysSet(raw: string): SysSetCommand | null {
  const s = normalizeComposerText(raw);
  const m = s.match(/^\/(?:sys|system)\s+(set|dry)\s+(.+)$/i);
  if (!m) return null;
  const dryRun = String(m[1] || "").toLowerCase() === "dry";
  const rest = String(m[2] || "").trim();
  const eq = rest.indexOf("=");
  if (eq < 1) return null;
  const key = rest.slice(0, eq).trim();
  const value = rest.slice(eq + 1).trim();
  if (!key) return null;
  return { key, value, dryRun };
}

export function parseSysDedupe(raw: string): SysDedupeCommand | null {
  const s = normalizeComposerText(raw);
  const m = s.match(/^\/(?:sys|system)\s+dedupe(?:\s+(sort))?(?:\s+(dry))?$/i);
  if (!m) return null;
  const sort = String(m[1] || "").toLowerCase() === "sort";
  const dryRun = String(m[2] || "").toLowerCase() === "dry";
  return { dryRun, sort };
}

export function parseToolInvoke(raw: string): ToolInvoke | null {
  const s = normalizeComposerText(raw);
  const m = s.match(/^\/(?:tool)\s+([^\s]+)(?:\s+(.+))?$/i);
  if (!m) return null;
  const name = String(m[1] || "").trim();
  const rest = String(m[2] || "").trim();
  if (!name) return null;

  const okPrefix =
    name.startsWith("system_") ||
    name.startsWith("pending_") ||
    name.startsWith("macro_") ||
    name.startsWith("current_news_") ||
    name.startsWith("news_follow_");
  if (!okPrefix) return { name, args: { __invalid_tool_prefix: true } };
  if (!rest) return { name, args: {} };

  try {
    const parsed = JSON.parse(rest);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { name, args: parsed as Record<string, any> };
    }
    return { name, args: { __invalid_tool_args: true } };
  } catch {
    return { name, args: { __invalid_tool_args: true } };
  }
}

export function parseJsonToolRequest(raw: string): JsonToolRequest | null {
  const s = String(raw || "").trim();
  if (!s.startsWith("{") || !s.endsWith("}")) return null;
  if (s.length > 200_000) return null;
  try {
    const js = JSON.parse(s);
    if (!js || typeof js !== "object" || Array.isArray(js)) return null;
    const typ = String((js as any).type || "").trim().toLowerCase();
    const isToolEnvelope = typ === "tool_call" || typ === "toolcall" || typ === "tool";

    const name = String(
      (js as any).name ||
        (js as any).tool ||
        (isToolEnvelope ? (js as any).tool_name : "") ||
        ""
    ).trim();
    const args = (js as any).args != null ? (js as any).args : (isToolEnvelope ? (js as any).parameters : undefined);
    if (!name) return null;
    if (!args || typeof args !== "object" || Array.isArray(args)) return null;
    return { name, args: args as Record<string, any> };
  } catch {
    return null;
  }
}

export function extractReminderAddText(text: string): string | null {
  const raw = String(text || "").trim();
  if (!raw) return null;

  const eng = [
    /^remind\s+me\s+to\s+(.+)$/i,
    /^remind\s+me\s+(.+)$/i,
    /^set\s+(?:a\s+)?reminder\s*[:\-]?\s*(.+)$/i,
    /^create\s+(?:a\s+)?reminder\s*[:\-]?\s*(.+)$/i,
    /^reminder\s+add\s*[:\-]?\s*(.+)$/i,
  ];
  for (const re of eng) {
    const m = raw.match(re);
    if (m && String(m[1] || "").trim()) return String(m[1]).trim();
  }

  const thai = [
    /^เตือนฉัน\s*(?:ว่า|ให้)?\s*(.+)$/,
    /^ช่วยเตือน(?:ฉัน)?\s*(?:ว่า|ให้)?\s*(.+)$/,
    /^ตั้ง(?:การ)?แจ้งเตือน\s*[:\-]?\s*(.+)$/,
    /^ตั้งเตือน\s*[:\-]?\s*(.+)$/,
    /^อย่าลืม\s*(.+)$/,
    /^เตือน\s*[:\-]?\s*(.+)$/,
  ];
  for (const re of thai) {
    const m = raw.match(re);
    if (m && String(m[1] || "").trim()) return String(m[1]).trim();
  }

  return null;
}
