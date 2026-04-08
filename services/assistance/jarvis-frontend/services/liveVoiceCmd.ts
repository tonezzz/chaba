import { VoiceCmdConfig } from "../types";

/**
 * Voice Command Parser Module
 *
 * All functions in this module are PURE (no side effects, no external dependencies):
 * - Input: string (voice transcript)
 * - Output: structured result or null
 *
 * This makes them trivial to unit test without mocking:
 *   expect(extractGemsCreateId("create model foo")).toBe("foo")
 *
 * No function accesses `this`, `window`, or any global state.
 */

// ---------------------------------------------------------------------------
// Text normalisation helpers
// ---------------------------------------------------------------------------

export function compactVoiceText(text: string): string {
	const s = String(text || "").trim().toLowerCase();
	if (!s) return "";
	return s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
}

export function includesAny(compact: string, phrases: unknown[]): boolean {
	if (!compact) return false;
	if (!Array.isArray(phrases) || !phrases.length) return false;
	for (const p of phrases) {
		const ps = compactVoiceText(String(p || ""));
		if (ps && compact.includes(ps)) return true;
	}
	return false;
}

// ---------------------------------------------------------------------------
// Config helpers
// ---------------------------------------------------------------------------

export function buildDefaultVoiceCmdCfg(): VoiceCmdConfig {
	return {
		enabled: true,
		debounce_ms: 10_000,
		reload: {
			enabled: true,
			phrases: [],
			mode_keywords: {
				gems: ["gems", "gem", "models", "model", "เจม", "โมเดล"],
				knowledge: ["knowledge", "kb", "know", "ความรู้"],
				memory: ["memory", "mem", "เมม", "เมมโม"],
			},
		},
		reminders_add: { enabled: true, phrases: [] },
		gems_list: { enabled: true, phrases: [] },
	};
}

export function mergeVoiceCmdCfg(cfg: unknown): VoiceCmdConfig {
	const d = buildDefaultVoiceCmdCfg();
	if (!cfg || typeof cfg !== "object") return d;
	const c = cfg as any;
	const out: any = { ...d, ...c };
	out.reload = { ...d.reload, ...(c.reload || {}) };
	out.reload.mode_keywords = { ...d.reload?.mode_keywords, ...((c.reload || {}).mode_keywords || {}) };
	out.reminders_add = { ...d.reminders_add, ...(c.reminders_add || {}) };
	out.gems_list = { ...d.gems_list, ...(c.gems_list || {}) };
	return out as VoiceCmdConfig;
}

export async function loadVoiceCmdCfg(): Promise<VoiceCmdConfig> {
	const isJarvisSubpath = location.pathname.startsWith("/jarvis");
	const candidates = isJarvisSubpath
		? ["/jarvis/api/config/voice_commands", "/config/voice_commands"]
		: ["/config/voice_commands", "/jarvis/api/config/voice_commands"];
	for (const u of candidates) {
		try {
			const res = await fetch(u, { method: "GET" });
			if (!res.ok) continue;
			const j = await res.json();
			return mergeVoiceCmdCfg(j?.config);
		} catch {
			// try next
		}
	}
	return buildDefaultVoiceCmdCfg();
}

// ---------------------------------------------------------------------------
// Phrase detection
// ---------------------------------------------------------------------------

export function isReloadSystemPhrase(text: string): boolean {
	const s = String(text || "").trim().toLowerCase();
	if (!s) return false;
	const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
	if (!compact) return false;
	if (compact.includes("reload system") || compact.includes("reload sheets")) return true;
	if (
		((compact.includes("reload") || compact.includes("reset") || compact.includes("restart") || compact.includes("reboot")) &&
			(compact.includes("system") || compact.includes("sheets") || compact.includes("sheet") || compact.includes("sys"))) ||
		compact.startsWith("reload system") ||
		compact.startsWith("reload sheets") ||
		compact.startsWith("reset system") ||
		compact.startsWith("restart system")
	) {
		return true;
	}
	if (/[\u0E00-\u0E7F]/.test(compact)) {
		const th = compact;
		const hasReloadWord = th.includes("รีโหลด") || th.includes("รีเฟรช") || th.includes("โหลด") || th.includes("รีเซ็ต") || th.includes("รีสตาร์ท") || th.includes("เริ่ม") || th.includes("restart") || th.includes("reset");
		const hasTargetWord = th.includes("ระบบ") || th.includes("ชีต") || th.includes("ชีท") || th.includes("ซิส") || th.includes("ซิสเต็ม") || th.includes("system") || th.includes("sheets");
		if (hasReloadWord && hasTargetWord) return true;
	}
	return false;
}

export function isModuleStatusReportPhrase(text: string): boolean {
	const raw = String(text || "").trim();
	if (!raw) return false;
	const compact = compactVoiceText(raw);
	if (!compact) return false;
	if (compact === "system module status report") return true;
	if (compact.includes("module status") && compact.includes("report")) return true;
	if (compact.includes("system") && compact.includes("module") && compact.includes("status")) return true;
	if ((compact.includes("รายงาน") || compact.includes("สรุป")) && compact.includes("สถานะ") && (compact.includes("ระบบ") || compact.includes("โมดูล"))) return true;
	return false;
}

export function isGemsListPhrase(text: string): boolean {
	const s = String(text || "").trim().toLowerCase();
	if (!s) return false;
	const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
	if (!compact) return false;
	if (compact === "gems" || compact === "list gems" || compact === "gems list") return true;
	if (compact === "models" || compact === "list models" || compact === "models list") return true;
	if (compact.includes("list gems") || compact.includes("gems list")) return true;
	if (compact.includes("list models") || compact.includes("models list")) return true;
	if (compact.includes("ลิส") || compact.includes("รายการ") || compact.includes("ดู")) {
		if (compact.includes("เจม") || compact.includes("โมเดล") || compact.includes("รุ่น")) return true;
	}
	return false;
}

// ---------------------------------------------------------------------------
// Text extractors
// ---------------------------------------------------------------------------

export function extractSystemReloadMode(
	text: string,
	cfg?: VoiceCmdConfig,
): "full" | "memory" | "knowledge" | "sys" | "gems" | null {
	const compact = compactVoiceText(text);
	if (!compact) return null;
	if (!(cfg?.enabled ?? true)) return null;
	if (!(cfg?.reload?.enabled ?? true)) return null;
	if (Array.isArray(cfg?.reload?.phrases) && cfg.reload!.phrases!.length) {
		if (!includesAny(compact, cfg.reload!.phrases!)) return null;
	} else {
		if (!isReloadSystemPhrase(compact)) return null;
	}
	const has = (w: string) => compact.includes(w);
	const kws: any = cfg?.reload?.mode_keywords || {};
	const gemsK: string[] = Array.isArray(kws?.gems) ? kws.gems : ["gems", "gem", "models", "model", "เจม", "โมเดล"];
	const knowK: string[] = Array.isArray(kws?.knowledge) ? kws.knowledge : ["knowledge", "kb", "know", "ความรู้"];
	const memK: string[] = Array.isArray(kws?.memory) ? kws.memory : ["memory", "mem", "เมม", "เมมโม"];
	for (const w of gemsK) { const ww = compactVoiceText(w); if (ww && has(ww)) return "gems"; }
	for (const w of knowK) { const ww = compactVoiceText(w); if (ww && has(ww)) return "knowledge"; }
	for (const w of memK)  { const ww = compactVoiceText(w); if (ww && has(ww)) return "memory"; }
	if (has("sys") || has("system") || has("sheets") || has("sheet") || has("ระบบ") || has("ชีต") || has("ชีท")) return "full";
	return "full";
}

export function extractReminderAddText(text: string): string | null {
	const raw = String(text || "").trim();
	if (!raw) return null;
	const low = raw.toLowerCase();
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
	if (low.startsWith("reminder ")) {
		const tail = raw.slice("reminder".length).trim();
		if (tail && !tail.toLowerCase().startsWith("list") && !tail.toLowerCase().startsWith("done") && !tail.toLowerCase().startsWith("delete")) {
			return tail;
		}
	}
	return null;
}

export function extractGemsRemoveId(text: string): string | null {
	const raw = String(text || "").trim();
	if (!raw) return null;
	const m = raw.match(/^gems\s+(?:remove|delete)\s*[:\-]?\s*(.+)$/i);
	if (m && String(m[1] || "").trim()) return String(m[1]).trim();
	const m2 = raw.match(/^ลบ\s*(?:เจม|โมเดล)\s*[:\-]?\s*(.+)$/);
	if (m2 && String(m2[1] || "").trim()) return String(m2[1]).trim();
	return null;
}

export function extractGemsUpsertJson(text: string): unknown | null {
	const raw = String(text || "").trim();
	if (!raw) return null;
	const m = raw.match(/^gems\s+(?:add|create|update|upsert)\s*[:\-]?\s*(\{[\s\S]+\})\s*$/i);
	if (!m) return null;
	try {
		const obj = JSON.parse(String(m[1] || ""));
		return obj && typeof obj === "object" ? obj : null;
	} catch {
		return null;
	}
}

export function extractGemsCreateId(text: string): string | null {
	const raw = String(text || "").trim();
	if (!raw) return null;
	const m = raw.match(/^gems\s+create\s+([a-z0-9_-]+)\s*$/i);
	if (m && String(m[1] || "").trim()) return String(m[1]).trim();
	const m2 = raw.match(/^สร้าง\s*(?:เจม|โมเดล)\s+([a-z0-9_-]+)\s*$/i);
	if (m2 && String(m2[1] || "").trim()) return String(m2[1]).trim();
	return null;
}

export function extractGemsAnalyze(text: string): { gem_id: string; criteria: string } | null {
	const raw = String(text || "").trim();
	if (!raw) return null;
	const m = raw.match(/^gems\s+analy[sz]e\s+([a-z0-9_-]+)(?:\s*(?::|\s-\s)\s*(.+))?$/i);
	if (m && String(m[1] || "").trim()) {
		return { gem_id: String(m[1]).trim(), criteria: String(m[2] || "").trim() };
	}
	const m2 = raw.match(/^วิเคราะห์\s*(?:เจม|โมเดล)\s+([a-z0-9_-]+)(?:\s*(?::|\s-\s)\s*(.+))?$/i);
	if (m2 && String(m2[1] || "").trim()) {
		return { gem_id: String(m2[1]).trim(), criteria: String(m2[2] || "").trim() };
	}
	return null;
}

export function extractGemsDraftAction(text: string): { action: "apply" | "discard"; draft_id: string } | null {
	const raw = String(text || "").trim();
	if (!raw) return null;
	const m = raw.match(/^gems\s+draft\s+(apply|discard)\s*[:\-]?\s*(\w+)$/i);
	if (m && String(m[2] || "").trim()) {
		const a = String(m[1]).toLowerCase() === "apply" ? "apply" : "discard";
		return { action: a, draft_id: String(m[2]).trim() };
	}
	const m2 = raw.match(/^ยืนยัน\s*ดราฟท์\s*[:\-]?\s*(\w+)$/);
	if (m2 && String(m2[1] || "").trim()) return { action: "apply", draft_id: String(m2[1]).trim() };
	const m3 = raw.match(/^ยกเลิก\s*ดราฟท์\s*[:\-]?\s*(\w+)$/);
	if (m3 && String(m3[1] || "").trim()) return { action: "discard", draft_id: String(m3[1]).trim() };
	return null;
}
