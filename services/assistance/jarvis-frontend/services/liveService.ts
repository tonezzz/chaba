import { base64ToUint8Array, float32To16BitPCM, arrayBufferToBase64, pcm16ToAudioBuffer } from "./audioUtils";
import { ConnectionState, MessageLog } from "../types";

export type CarsIngestResult = {
  type: "cars_ingest_result";
  request_id: string;
  ok: boolean;
  original_path?: string;
  detector?: any;
  items?: Array<{
    plate: string;
    json_path: string;
    plate_crop?: string | null;
    car_crop?: string | null;
    confidence?: number | null;
  }>;
  crops_written?: number;
  instance_id?: string;
  error?: string;
};

export class LiveService {
  private ws: WebSocket | null = null;
  private inputAudioContext: AudioContext | null = null;
  private outputAudioContext: AudioContext | null = null;
  private inputSource: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private nextStartTime: number = 0;
  private isStreamingAudio: boolean = false;
  private sessionId: string | null = null;
  private clientId: string | null = null;
  private clientTag: string | null = null;
  private inputStream: MediaStream | null = null;
  private connectInFlight: boolean = false;
  private wsSeq: number = 0;
  private keepaliveTimer: number | null = null;
  private currentCameraFrame: string | null = null;
  private lastVoiceCommandTs: Record<string, number> = {};
  private lastVoiceCommandName: string | null = null;
  private lastVoiceCommandAt: number = 0;
  private lastSysKvSetAt: number = 0;
  private voiceCmdCfg: any | null = null;
  private voiceCmdCfgLoadedAt: number = 0;
  private toolPending: Map<
    string,
    {
      resolve: (v: any) => void;
      reject: (e: any) => void;
      name: string;
      createdAt: number;
    }
  > = new Map();

	private createTraceId(prefix?: string): string {
		const p = String(prefix || "tr").trim() || "tr";
		const sid = this.getSessionId();
		return `${p}_${sid}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
	}

	private inferClientTag(): string {
		try {
			const ua = String(navigator.userAgent || "").toLowerCase();
			const isIpad = ua.includes("ipad") || (ua.includes("macintosh") && typeof (navigator as any).maxTouchPoints === "number" && (navigator as any).maxTouchPoints > 1);
			if (isIpad) return "ipad";
			if (ua.includes("iphone")) return "iphone";
			if (ua.includes("android") && ua.includes("mobile")) return "android";
		} catch {
			// ignore
		}
		return "pc";
	}

	private getOrCreateClientId(): string {
		const storageKey = "jarvis_client_id";
		try {
			const existing = String(window.localStorage.getItem(storageKey) || "").trim();
			if (existing) return existing;
			const newId =
				(typeof crypto !== "undefined" && typeof (crypto as any).randomUUID === "function"
					? (crypto as any).randomUUID()
					: `${Date.now()}_${Math.random().toString(16).slice(2)}`);
			window.localStorage.setItem(storageKey, newId);
			return newId;
		} catch {
			return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
		}
	}

	private extractGemsAnalyze(text: string): { gem_id: string; criteria: string } | null {
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

	private extractGemsDraftAction(text: string): { action: "apply" | "discard"; draft_id: string } | null {
		const raw = String(text || "").trim();
		if (!raw) return null;
		const m = raw.match(/^gems\s+draft\s+(apply|discard)\s*[:\-]?\s*(\w+)$/i);
		if (m && String(m[2] || "").trim()) {
			const a = String(m[1]).toLowerCase() === "apply" ? "apply" : "discard";
			return { action: a as any, draft_id: String(m[2]).trim() };
		}
		const m2 = raw.match(/^ยืนยัน\s*ดราฟท์\s*[:\-]?\s*(\w+)$/);
		if (m2 && String(m2[1] || "").trim()) return { action: "apply", draft_id: String(m2[1]).trim() };
		const m3 = raw.match(/^ยกเลิก\s*ดราฟท์\s*[:\-]?\s*(\w+)$/);
		if (m3 && String(m3[1] || "").trim()) return { action: "discard", draft_id: String(m3[1]).trim() };
		return null;
	}

	private wsSend(payload: any) {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify(payload));
		}
	}

	public invokeTool(name: string, args?: Record<string, any>): Promise<any> {
		const toolName = String(name || "").trim();
		if (!toolName) return Promise.reject(new Error("missing_tool_name"));
		if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return Promise.reject(new Error("ws_not_connected"));
		const traceId = this.createTraceId(`tool_${toolName}`);
		const payloadArgs = args && typeof args === "object" ? args : {};
		return new Promise((resolve, reject) => {
			this.toolPending.set(traceId, { resolve, reject, name: toolName, createdAt: Date.now() });
			this.wsSend({ type: "tool", name: toolName, args: payloadArgs, trace_id: traceId });
			// Timeout (best-effort)
			window.setTimeout(() => {
				const cur = this.toolPending.get(traceId);
				if (!cur) return;
				this.toolPending.delete(traceId);
				reject(new Error("tool_timeout"));
			}, 20_000);
		});
	}

	private buildDefaultVoiceCmdCfg(): any {
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

	private mergeVoiceCmdCfg(cfg: any | null): any {
		const d = this.buildDefaultVoiceCmdCfg();
		if (!cfg || typeof cfg !== "object") return d;
		const out: any = { ...d, ...cfg };
		out.reload = { ...d.reload, ...(cfg.reload || {}) };
		out.reload.mode_keywords = { ...d.reload.mode_keywords, ...((cfg.reload || {}).mode_keywords || {}) };
		out.reminders_add = { ...d.reminders_add, ...(cfg.reminders_add || {}) };
		out.gems_list = { ...d.gems_list, ...(cfg.gems_list || {}) };
		return out;
	}

	private async ensureVoiceCmdCfgLoaded(force?: boolean) {
		const now = Date.now();
		if (!force && this.voiceCmdCfg && now - this.voiceCmdCfgLoadedAt < 60_000) return;
		const isJarvisSubpath = location.pathname.startsWith("/jarvis");
		try {
			const candidates = isJarvisSubpath
				? ["/jarvis/api/config/voice_commands", "/jarvis/config/voice_commands", "/config/voice_commands"]
				: ["/config/voice_commands", "/jarvis/api/config/voice_commands", "/jarvis/config/voice_commands"];
			let j: any = null;
			for (const u of candidates) {
				try {
					const res = await fetch(u, { method: "GET" });
					if (!res.ok) continue;
					j = await res.json();
					break;
				} catch {
					// try next
				}
			}
			this.voiceCmdCfg = this.mergeVoiceCmdCfg(j && j.config);
			this.voiceCmdCfgLoadedAt = now;
		} catch {
			this.voiceCmdCfg = this.buildDefaultVoiceCmdCfg();
			this.voiceCmdCfgLoadedAt = now;
		}
	}

	private compactVoiceText(text: string): string {
		const s = String(text || "").trim().toLowerCase();
		if (!s) return "";
		return s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
	}

	private includesAny(compact: string, phrases: any): boolean {
		if (!compact) return false;
		if (!Array.isArray(phrases) || !phrases.length) return false;
		for (const p of phrases) {
			const ps = this.compactVoiceText(String(p || ""));
			if (ps && compact.includes(ps)) return true;
		}
		return false;
	}

	public sendSystemReload(mode: "full" | "memory" | "knowledge" | "sys" | "gems" = "full") {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "system", action: "reload", mode, trace_id: this.createTraceId("sys_reload") });
		}
	}

	public sendSystemClearJob() {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "system", action: "clear_job", trace_id: this.createTraceId("sys_clear_job") });
		}
	}

	public sendSysKvSet(key: string, value: string, opts?: { dry_run?: boolean }) {
		const k = String(key || "").trim();
		const v = String(value ?? "");
		if (!k) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.lastSysKvSetAt = Date.now();
			this.wsSend({
				type: "system",
				action: "sys_kv_set",
				key: k,
				value: v,
				dry_run: Boolean(opts?.dry_run),
				trace_id: this.createTraceId("sys_kv_set"),
			});
		}
	}

	public sendRemindersAdd(text: string) {
		const body = String(text || "").trim();
		if (!body) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "reminders", action: "add", text: body, trace_id: this.createTraceId("rem_add") });
		}
	}

	public sendGemsList() {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "gems", action: "list", trace_id: this.createTraceId("gems_ls") });
		}
	}

	public sendGemsUpsert(gem: any) {
		if (!gem || typeof gem !== "object") return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "gems", action: "upsert", gem, trace_id: this.createTraceId("gems_upsert") });
		}
	}

	public sendGemsRemove(id: string) {
		const gem_id = String(id || "").trim();
		if (!gem_id) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "gems", action: "remove", gem_id, id: gem_id, trace_id: this.createTraceId("gems_rm") });
		}
	}

	public sendGemsAnalyze(gemId: string, criteria?: string) {
		const gem_id = String(gemId || "").trim();
		const crit = String(criteria || "").trim();
		if (!gem_id) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "gems", action: "analyze", gem_id, id: gem_id, criteria: crit, trace_id: this.createTraceId("gems_analyze") });
		}
	}

	public sendGemsDraftApply(draftId: string) {
		const draft_id = String(draftId || "").trim();
		if (!draft_id) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "gems", action: "draft_apply", draft_id, trace_id: this.createTraceId("gems_apply") });
		}
	}

	public sendGemsDraftDiscard(draftId: string) {
		const draft_id = String(draftId || "").trim();
		if (!draft_id) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "gems", action: "draft_discard", draft_id, trace_id: this.createTraceId("gems_discard") });
		}
	}

	private shouldAutoTriggerVoiceCommand(key: string, debounceMs: number): boolean {
		const now = Date.now();
		const prev = this.lastVoiceCommandTs[key] || 0;
		if (now - prev < debounceMs) return false;
		this.lastVoiceCommandTs[key] = now;
		this.lastVoiceCommandName = key;
		this.lastVoiceCommandAt = now;
		return true;
	}

	private isReloadSystemPhrase(text: string): boolean {
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
		// Thai common variants.
		if (/[\u0E00-\u0E7F]/.test(compact)) {
			const th = compact;
			const hasReloadWord = th.includes("รีโหลด") || th.includes("รีเฟรช") || th.includes("โหลด") || th.includes("รีเซ็ต") || th.includes("รีสตาร์ท") || th.includes("เริ่ม") || th.includes("restart") || th.includes("reset");
			const hasTargetWord = th.includes("ระบบ") || th.includes("ชีต") || th.includes("ชีท") || th.includes("ซิส") || th.includes("ซิสเต็ม") || th.includes("system") || th.includes("sheets");
			if (hasReloadWord && hasTargetWord) return true;
		}
		return false;
	}

	private extractGemsRemoveId(text: string): string | null {
		const raw = String(text || "").trim();
		if (!raw) return null;
		const m = raw.match(/^gems\s+(?:remove|delete)\s*[:\-]?\s*(.+)$/i);
		if (m && String(m[1] || "").trim()) return String(m[1]).trim();
		const m2 = raw.match(/^ลบ\s*(?:เจม|โมเดล)\s*[:\-]?\s*(.+)$/);
		if (m2 && String(m2[1] || "").trim()) return String(m2[1]).trim();
		return null;
	}

	private extractGemsUpsertJson(text: string): any | null {
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

	private extractGemsCreateId(text: string): string | null {
		const raw = String(text || "").trim();
		if (!raw) return null;
		const m = raw.match(/^gems\s+create\s+([a-z0-9_-]+)\s*$/i);
		if (m && String(m[1] || "").trim()) return String(m[1]).trim();
		const m2 = raw.match(/^สร้าง\s*(?:เจม|โมเดล)\s+([a-z0-9_-]+)\s*$/i);
		if (m2 && String(m2[1] || "").trim()) return String(m2[1]).trim();
		return null;
	}

	private extractSystemReloadMode(text: string): "full" | "memory" | "knowledge" | "sys" | "gems" | null {
		const compact = this.compactVoiceText(text);
		if (!compact) return null;
		const cfg = this.voiceCmdCfg || this.buildDefaultVoiceCmdCfg();
		if (!(cfg?.enabled ?? true)) return null;
		if (!(cfg?.reload?.enabled ?? true)) return null;
		if (Array.isArray(cfg?.reload?.phrases) && cfg.reload.phrases.length) {
			if (!this.includesAny(compact, cfg.reload.phrases)) return null;
		} else {
		if (!this.isReloadSystemPhrase(compact)) return null;
		}

		const has = (w: string) => compact.includes(w);
		// Prefer more specific targets first.
		const kws: any = cfg?.reload?.mode_keywords || {};
		const gemsK = Array.isArray(kws?.gems) ? kws.gems : ["gems", "gem", "models", "model", "เจม", "โมเดล"];
		const knowK = Array.isArray(kws?.knowledge) ? kws.knowledge : ["knowledge", "kb", "know", "ความรู้"];
		const memK = Array.isArray(kws?.memory) ? kws.memory : ["memory", "mem", "เมม", "เมมโม"];
		for (const w of gemsK) {
			const ww = this.compactVoiceText(String(w || ""));
			if (ww && has(ww)) return "gems";
		}
		for (const w of knowK) {
			const ww = this.compactVoiceText(String(w || ""));
			if (ww && has(ww)) return "knowledge";
		}
		for (const w of memK) {
			const ww = this.compactVoiceText(String(w || ""));
			if (ww && has(ww)) return "memory";
		}
		if (has("sys") || has("system") || has("sheets") || has("sheet") || has("ระบบ") || has("ชีต") || has("ชีท")) return "full";
		return "full";
	}

	private isModuleStatusReportPhrase(text: string): boolean {
		const raw = String(text || "").trim();
		if (!raw) return false;
		const compact = this.compactVoiceText(raw);
		if (!compact) return false;
		// English
		if (compact === "system module status report") return true;
		if (compact.includes("module status") && compact.includes("report")) return true;
		if (compact.includes("system") && compact.includes("module") && compact.includes("status")) return true;
		// Thai (permissive)
		if ((compact.includes("รายงาน") || compact.includes("สรุป")) && compact.includes("สถานะ") && (compact.includes("ระบบ") || compact.includes("โมดูล"))) return true;
		return false;
	}

	private extractReminderAddText(text: string): string | null {
		const raw = String(text || "").trim();
		if (!raw) return null;
		const low = raw.toLowerCase();

		// English patterns
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

		// Thai patterns (keep permissive)
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

		// Extra: if the user explicitly says "reminder" and has content after it.
		if (low.startsWith("reminder ")) {
			const tail = raw.slice("reminder".length).trim();
			if (tail && !tail.toLowerCase().startsWith("list") && !tail.toLowerCase().startsWith("done") && !tail.toLowerCase().startsWith("delete")) {
				return tail;
			}
		}

		return null;
	}

	private isGemsListPhrase(text: string): boolean {
		const s = String(text || "").trim().toLowerCase();
		if (!s) return false;
		const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
		if (!compact) return false;
		if (compact === "gems" || compact === "list gems" || compact === "gems list") return true;
		if (compact === "models" || compact === "list models" || compact === "models list") return true;
		if (compact.includes("list gems") || compact.includes("gems list")) return true;
		if (compact.includes("list models") || compact.includes("models list")) return true;
		// Thai
		if (compact.includes("ลิส") || compact.includes("รายการ") || compact.includes("ดู")) {
			if (compact.includes("เจม") || compact.includes("โมเดล") || compact.includes("รุ่น")) return true;
		}
		return false;
	}

	private getOrCreateSessionId(): string {
		const storageKey = "jarvis_session_id";
		try {
			const existing = String(window.localStorage.getItem(storageKey) || "").trim();
			if (existing) return existing;
			const newId =
				(typeof crypto !== "undefined" && typeof (crypto as any).randomUUID === "function"
					? (crypto as any).randomUUID()
					: `${Date.now()}_${Math.random().toString(16).slice(2)}`);
			window.localStorage.setItem(storageKey, newId);
			return newId;
		} catch {
			return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
		}
	}

  public getSessionId(): string {
    if (!this.sessionId) this.sessionId = this.getOrCreateSessionId();
    return this.sessionId;
  }

  public async sendCarsIngestImage(file: File, requestId?: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("ws_not_connected");
    }
    const buf = await file.arrayBuffer();
    const b64 = arrayBufferToBase64(buf);
    const mimeType = String(file.type || "image/png") || "image/png";
    const reqId = String(requestId || `${Date.now()}_${Math.random().toString(16).slice(2)}`);
    this.wsSend({
      type: "cars_ingest_image",
      request_id: reqId,
      trace_id: this.createTraceId("cars"),
      mimeType,
      data: b64,
    });
    return reqId;
  }

  public onStateChange: (state: ConnectionState) => void = () => {};
  public onMessage: (msg: MessageLog) => void = () => {};
  public onVolume: (vol: number) => void = () => {};
  public onCarsIngestResult: (ev: CarsIngestResult) => void = () => {};

  constructor() {}

  public startStreaming() {
    this.isStreamingAudio = true;
  }

  public stopStreaming() {
    this.isStreamingAudio = false;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "audio_stream_end", trace_id: this.createTraceId("audio_end") });
    }
  }

  public sendText(text: string): string | null {
    const trimmed = String(text || "").trim();
    if (!trimmed) return null;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			const traceId = this.createTraceId("text");
			this.wsSend({ type: "text", text: trimmed, trace_id: traceId });
			return traceId;
    }
		return null;
  }

  public updateCameraFrame(base64: string) {
    this.currentCameraFrame = base64;
    // Push frame to model to give it vision
    return;
  }

  public async connect() {
    // Idempotent connect: prevent double WebSockets (common on iPad due to tap/reload/reconnect races).
    if (this.connectInFlight) return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.connectInFlight = true;
    this.onStateChange(ConnectionState.CONNECTING);

    try {
      // Ensure any stale socket is fully closed before we create a new one.
      if (this.ws) {
        try {
          this.ws.onopen = null;
          this.ws.onclose = null;
          this.ws.onerror = null;
          this.ws.onmessage = null;
          this.ws.close();
        } catch {
        }
        this.ws = null;
      }
		if (this.keepaliveTimer != null) {
			try { window.clearInterval(this.keepaliveTimer); } catch {}
			this.keepaliveTimer = null;
		}

      const mySeq = ++this.wsSeq;
      // Always try to establish the WebSocket connection even if audio init fails.
      // This enables text-only mode (useful on servers/browsers where mic access is unavailable).
      let stream: MediaStream | null = null;
      try {
        this.inputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
        this.outputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.inputStream = stream;
      } catch (audioErr: any) {
        this.inputStream = null;
        this.isStreamingAudio = false;
        try {
          this.onMessage({
            id: `${Date.now()}_audio_unavailable`,
            role: "system",
            text: `audio_unavailable: ${String(audioErr?.name || audioErr || "unknown")}`,
            timestamp: new Date(),
          });
        } catch {
          // ignore
        }
      }

      const backendUrl = (import.meta as any).env?.VITE_JARVIS_WS_URL as string | undefined;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const isJarvisSubpath = location.pathname.startsWith("/jarvis");
      const defaultWsUrl = isJarvisSubpath
        ? `${proto}://${location.host}/jarvis/ws/live`
        : `${proto}://${location.hostname}:8018/ws/live`;
      const baseWsUrl = (backendUrl || defaultWsUrl).trim();
		const sessionId = this.getSessionId();
		const clientId = this.clientId || this.getOrCreateClientId();
		const clientTag = this.clientTag || this.inferClientTag();
		this.clientId = clientId;
		this.clientTag = clientTag;
		let wsUrl = baseWsUrl;
		try {
			const u = new URL(baseWsUrl);
			u.searchParams.set("session_id", sessionId);
			u.searchParams.set("client_id", clientId);
			u.searchParams.set("client_tag", clientTag);
			wsUrl = u.toString();
		} catch {
			// If URL parsing fails, fall back to appending query param.
			const q = `session_id=${encodeURIComponent(sessionId)}&client_id=${encodeURIComponent(clientId)}&client_tag=${encodeURIComponent(clientTag)}`;
			wsUrl = baseWsUrl.includes("?") ? `${baseWsUrl}&${q}` : `${baseWsUrl}?${q}`;
		}

      this.ws = new WebSocket(wsUrl);
      this.ws.onopen = () => {
        if (mySeq !== this.wsSeq) return;
        this.connectInFlight = false;
			void this.ensureVoiceCmdCfgLoaded();
        this.onStateChange(ConnectionState.CONNECTED);
			try {
				if (this.keepaliveTimer != null) {
					window.clearInterval(this.keepaliveTimer);
					this.keepaliveTimer = null;
				}
				this.keepaliveTimer = window.setInterval(() => {
					try {
						if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
						this.wsSend({ type: "ping", trace_id: this.createTraceId("ping") });
					} catch {
					}
				}, 25000);
			} catch {
			}
        this.onMessage({
          id: `${Date.now()}_ws_open`,
          role: "system",
          text: "connected",
          timestamp: new Date(),
        });
        try {
          if (this.outputAudioContext && this.outputAudioContext.state === "suspended") {
            void this.outputAudioContext.resume();
          }
        } catch {
          // ignore
        }
        if (this.inputStream) {
          this.setupAudioInput(this.inputStream);
        } else {
          this.onMessage({
            id: `${Date.now()}_text_only`,
            role: "system",
            text: "text_only_mode",
            timestamp: new Date(),
          });
        }
      };
      this.ws.onclose = (ev) => {
        if (mySeq !== this.wsSeq) return;
        this.connectInFlight = false;
			if (this.keepaliveTimer != null) {
				try { window.clearInterval(this.keepaliveTimer); } catch {}
				this.keepaliveTimer = null;
			}
        try {
          console.warn("ws_close", { code: ev.code, reason: ev.reason, wasClean: ev.wasClean });
        } catch {
          // ignore
        }
        this.onStateChange(ConnectionState.DISCONNECTED);
        this.onMessage({
          id: `${Date.now()}_ws_close`,
          role: "system",
          text: `disconnected (code=${ev.code}${ev.reason ? ` reason=${ev.reason}` : ""})`,
          timestamp: new Date(),
        });
      };
      this.ws.onerror = (err) => {
        if (mySeq !== this.wsSeq) return;
        this.connectInFlight = false;
			if (this.keepaliveTimer != null) {
				try { window.clearInterval(this.keepaliveTimer); } catch {}
				this.keepaliveTimer = null;
			}
        console.error(err);
        this.onStateChange(ConnectionState.ERROR);
        this.onMessage({
          id: `${Date.now()}_ws_error`,
          role: "system",
          text: "connection_error",
          timestamp: new Date(),
        });
      };
      this.ws.onmessage = (event) => {
        if (mySeq !== this.wsSeq) return;
        try {
          const msg = JSON.parse(event.data);
          this.handleBackendMessage(msg);
        } catch (e) {
          console.error(e);
        }
      };

    } catch (error) {
      console.error("Connection failed", error);
      this.onStateChange(ConnectionState.ERROR);
    } finally {
      // If connect failed before WS callbacks ran, allow retry.
      if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
        this.connectInFlight = false;
      }
    }
  }

  public async disconnect() {
    // Invalidate any pending callbacks from the current socket.
    this.wsSeq += 1;
    this.connectInFlight = false;
    if (this.ws) {
      try {
        this.ws.send(JSON.stringify({ type: "close" }));
      } catch (e) {
        console.error(e);
      }
      this.ws.close();
    }
		if (this.keepaliveTimer != null) {
			try { window.clearInterval(this.keepaliveTimer); } catch {}
			this.keepaliveTimer = null;
		}

    try {
      if (this.inputStream) {
        for (const t of this.inputStream.getTracks()) t.stop();
      }
    } catch {
      // ignore
    }
    this.inputStream = null;
    
    if (this.inputSource) this.inputSource.disconnect();
    if (this.processor) {
        this.processor.disconnect();
        this.processor.onaudioprocess = null;
    }
    if (this.inputAudioContext) await this.inputAudioContext.close();
    if (this.outputAudioContext) await this.outputAudioContext.close();
    
    this.inputAudioContext = null;
    this.outputAudioContext = null;
    this.ws = null;
    this.onStateChange(ConnectionState.DISCONNECTED);
  }

  private setupAudioInput(stream: MediaStream) {
    if (!this.inputAudioContext) return;
    
    this.inputSource = this.inputAudioContext.createMediaStreamSource(stream);
    this.processor = this.inputAudioContext.createScriptProcessor(4096, 1, 1);
    
    this.processor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0);
      
      // Calculate volume for visualizer
      let sum = 0;
      for (let i = 0; i < inputData.length; i++) {
        sum += inputData[i] * inputData[i];
      }
      const rms = Math.sqrt(sum / inputData.length);
      this.onVolume(rms);

      const pcm16 = float32To16BitPCM(inputData);
      const base64 = arrayBufferToBase64(pcm16);

      if (this.isStreamingAudio && this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.wsSend({
          type: "audio",
          trace_id: this.createTraceId("audio"),
          mimeType: "audio/pcm;rate=16000",
          data: base64,
        });
      }
    };

    this.inputSource.connect(this.processor);
    this.processor.connect(this.inputAudioContext.destination);
  }

  private async handleBackendMessage(message: any) {
    const traceId = message?.trace_id != null ? String(message.trace_id) : undefined;
    const quietAfterSysKvSet = this.lastSysKvSetAt && Date.now() - this.lastSysKvSetAt < 6_000;
    const wsMeta = {
      type: message?.type != null ? String(message.type) : undefined,
      instance_id: message?.instance_id != null ? String(message.instance_id) : undefined,
      client_tag: message?.client_tag != null ? String(message.client_tag) : undefined,
      client_id: message?.client_id != null ? String(message.client_id) : undefined,
    };

		if (message?.type === "tool_result") {
			const toolName = message?.name != null ? String(message.name) : "tool";
			const ok = message?.ok === true;
			// Resolve any pending invokeTool promises.
			if (traceId) {
				const pending = this.toolPending.get(traceId);
				if (pending) {
					this.toolPending.delete(traceId);
					if (ok) pending.resolve(message?.result);
					else pending.reject(message?.error ?? "tool_failed");
				}
			}
			// Also emit a UI log line.
			const summary = ok ? "ok" : "error";
			this.onMessage({
				id: `${Date.now()}_tool_result_${toolName}`,
				role: "system",
				text: `tool_result ${toolName}: ${summary}`,
				timestamp: new Date(),
				metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: ok ? "info" : "warn", category: "ws" },
			});
			return;
		}

		if (message?.type === "reconnect") {
			const reason = message?.reason != null ? String(message.reason) : "";
			this.onMessage({
				id: `${Date.now()}_reconnect`,
				role: "system",
				text: `reconnect_requested${reason ? `: ${reason}` : ""}`,
				timestamp: new Date(),
				metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
			});
			try {
				await this.disconnect();
			} catch {
				// ignore
			}
			try {
				await new Promise((r) => setTimeout(r, 300));
				await this.connect();
			} catch {
				// ignore
			}
			return;
		}

		// After a deterministic /sys set, ignore tool/progress chatter and late model turns.
		// This prevents confusing follow-up actions like google_tasks_list_tasks showing up right after sys_kv_set.
		// Keep the real sys_kv_set ok response (a text message) visible.
		if (quietAfterSysKvSet && message?.type === "progress") {
			return;
		}

    if (message?.type === "progress") {
      const phase = message?.phase != null ? String(message.phase) : "";
      const tool = message?.tool != null ? String(message.tool) : "";
      const step = message?.step != null ? Number(message.step) : null;
      const total = message?.total != null ? Number(message.total) : null;
      const baseMsg = message?.message != null ? String(message.message) : "";
      const prefix = tool ? `[${tool}] ` : "";
      const stepText = step != null && total != null ? ` (${step}/${total})` : "";
      const text = `${prefix}${baseMsg}${stepText}`.trim();

      if (phase === "done" || phase === "error") {
        // Clear sticky progress line.
        this.onMessage({
          id: "sticky_progress",
          role: "system",
          text: "",
          timestamp: new Date(),
          metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "debug", category: "ws" },
        });
        // Emit a short final line.
        if (text) {
          this.onMessage({
            id: `${Date.now()}_progress_${phase}`,
            role: "system",
            text,
            timestamp: new Date(),
            metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: phase === "error" ? "warn" : "info", category: "ws" },
          });
        }
        return;
      }

      // Sticky progress line that updates in-place.
      this.onMessage({
        id: "sticky_progress",
        role: "system",
        text: text || "working…",
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
      });
      return;
    }
    if (message?.type === "state" && message?.state) {
      this.onMessage({
        id: `${Date.now()}_state`,
        role: "system",
        text: String(message.state),
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
      });
      return;
    }

    if (message?.type === "reminder_setup") {
      const title = message?.title != null ? String(message.title) : "Reminder";
      const rid = message?.reminder_id != null ? String(message.reminder_id) : "";
      const res = message?.result;
      const ok = res?.ok === true;
      const needsTime = res?.needs_time === true;
      const hint = res?.hint != null ? String(res.hint) : "";
      const status = ok ? (needsTime ? "created (needs time)" : "created") : "failed";
      const line = `reminder_setup: ${title}${rid ? ` [${rid}]` : ""} (${status})${hint ? ` — ${hint}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_reminder_setup`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (message?.type === "reminder_setup_draft") {
      const title = message?.title != null ? String(message.title) : "Reminder";
      const res = message?.result;
      const hint = res?.hint != null ? String(res.hint) : "";
      const line = `reminder_draft: ${title}${hint ? ` — ${hint}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_reminder_draft`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (message?.type === "reminder_setup_cancelled") {
      this.onMessage({
        id: `${Date.now()}_reminder_cancelled`,
        role: "model",
        text: "reminder_draft_cancelled",
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (message?.type === "planning_item_created") {
      const kind = message?.kind != null ? String(message.kind) : "";
      const title = message?.title != null ? String(message.title) : "";
      const ok = (message as any)?.result?.ok === true;
      const localTime = (message as any)?.result?.local_time != null ? String((message as any).result.local_time) : "";
      const line = `planning_item_created: ${kind || "item"}${title ? ` — ${title}` : ""}${ok ? " (ok)" : ""}${localTime ? ` @ ${localTime}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_planning_item_created`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: ok ? "info" : "warn", category: "reminder" },
      });
      return;
    }

    if (message?.type === "reminders_list") {
      const status = message?.status != null ? String(message.status) : "";
      const day = message?.day != null ? String(message.day) : "";
      const items = Array.isArray((message as any)?.items) ? ((message as any).items as any[]) : [];
      const header = `reminders_list${day ? ` (${day})` : ""}${status ? ` status=${status}` : ""}`;
      const lines: string[] = [header];
      if (!items.length) {
        lines.push("(no results)");
      } else {
        for (const r of items.slice(0, 50)) {
          const rid = r?.reminder_id != null ? String(r.reminder_id) : "";
          const title = r?.title != null ? String(r.title) : "Reminder";
          const st = r?.status != null ? String(r.status) : "";
          const t = r?.notify_at != null ? ` notify_at=${String(r.notify_at)}` : r?.due_at != null ? ` due_at=${String(r.due_at)}` : "";
          lines.push(`- ${title}${rid ? ` [${rid}]` : ""}${st ? ` (${st})` : ""}${t}`);
        }
      }
      this.onMessage({
        id: `${Date.now()}_reminders_list`,
        role: "model",
        text: lines.join("\n"),
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (typeof message?.type === "string" && message.type.startsWith("reminders_")) {
      const t = String(message.type);
      const rid = (message as any)?.reminder_id != null ? String((message as any).reminder_id) : "";
      const changed = (message as any)?.changed;
      const extra = typeof changed === "boolean" ? ` changed=${changed}` : "";
      const line = `${t}${rid ? ` [${rid}]` : ""}${extra}`;
      this.onMessage({
        id: `${Date.now()}_${t}`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (message?.type === "gems_list") {
      const items = Array.isArray((message as any)?.items) ? ((message as any).items as any[]) : [];
      const lines: string[] = ["gems_list"];
      if (!items.length) {
        lines.push("(no results)");
      } else {
        for (const g of items.slice(0, 50)) {
          const id = g?.id != null ? String(g.id) : "";
          const name = g?.name != null ? String(g.name) : "";
          const purpose = g?.purpose != null ? String(g.purpose) : "";
          lines.push(`- ${id}${name ? ` — ${name}` : ""}${purpose ? ` (${purpose})` : ""}`);
        }
      }
      this.onMessage({
        id: `${Date.now()}_gems_list`,
        role: "model",
        text: lines.join("\n"),
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
      });
      return;
    }

    if (typeof message?.type === "string" && message.type.startsWith("gems_")) {
      const t = String(message.type);
      const gemId = (message as any)?.gem_id != null ? String((message as any).gem_id) : "";
      const op = (message as any)?.op != null ? String((message as any).op) : "";
      const draftId = (message as any)?.draft_id != null ? String((message as any).draft_id) : "";
      const line = `${t}${gemId ? ` [${gemId}]` : ""}${op ? ` op=${op}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_${t}`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
      });
      return;
    }

    if (message?.type === "gems_draft_created") {
      const gemId = (message as any)?.gem_id != null ? String((message as any).gem_id) : "";
      const draftId = (message as any)?.draft_id != null ? String((message as any).draft_id) : "";
      const changed = Array.isArray((message as any)?.changed) ? ((message as any).changed as any[]).map(String) : [];
      const line = `gems_draft_created${gemId ? ` [${gemId}]` : ""}${draftId ? ` draft=${draftId}` : ""}${changed.length ? ` changed=${changed.join(",")}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_gems_draft_created`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
      });
      return;
    }

    if (message?.type === "reminder_helper_list") {
      const status = message?.status != null ? String(message.status) : "";
      const includeHidden = message?.include_hidden === true;
      const day = message?.day != null ? String(message.day) : "";
      const reminders = Array.isArray((message as any)?.reminders) ? ((message as any).reminders as any[]) : [];
      const header = `reminder_helper_list${day ? ` (${day})` : ""}${status ? ` status=${status}` : ""}${includeHidden ? " include_hidden" : ""}`;
      const lines: string[] = [header];
      if (!reminders.length) {
        if (day === "today") {
          lines.push("No reminders today.");
        } else if (day === "yesterday") {
          lines.push("No reminders yesterday.");
        } else {
          lines.push("(no results)");
        }
      } else {
        for (const r of reminders.slice(0, 50)) {
          const rid = r?.reminder_id != null ? String(r.reminder_id) : "";
          const title = r?.title != null ? String(r.title) : "Reminder";
          const st = r?.status != null ? String(r.status) : "";
          const t = r?.notify_at != null ? ` notify_at=${String(r.notify_at)}` : r?.due_at != null ? ` due_at=${String(r.due_at)}` : "";
          lines.push(`- ${title}${rid ? ` [${rid}]` : ""}${st ? ` (${st})` : ""}${t}`);
        }
      }
      this.onMessage({
        id: `${Date.now()}_reminder_helper_list`,
        role: "model",
        text: lines.join("\n"),
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (typeof message?.type === "string" && message.type.startsWith("reminder_helper_")) {
      const t = String(message.type);
      const rid = message?.reminder_id != null ? String(message.reminder_id) : "";
      const summary = message?.message != null ? String(message.message) : "";
      const line = `${t}${rid ? ` [${rid}]` : ""}${summary ? ` — ${summary}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_${t}`,
        role: "model",
        text: line,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (message?.type === "reminder" && message?.reminder) {
      const r = message.reminder;
      const title = r?.title != null ? String(r.title) : "Reminder";
      const schedule = r?.schedule_type != null ? String(r.schedule_type) : "";
      const text = schedule ? `reminder: ${title} (${schedule})` : `reminder: ${title}`;
      this.onMessage({
        id: `${Date.now()}_reminder`,
        role: "model",
        text,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" },
      });
      return;
    }

    if (message?.type === "cars_ingest_result" && message?.request_id) {
      try {
        this.onCarsIngestResult(message as CarsIngestResult);
      } catch {
        // ignore
      }
      return;
    }

    if (message?.type === "audio" && message?.data && this.outputAudioContext) {
      try {
        if (this.outputAudioContext.state === "suspended") {
          await this.outputAudioContext.resume();
        }
      } catch {
        // ignore
      }
      this.nextStartTime = Math.max(this.nextStartTime, this.outputAudioContext.currentTime);
      const pcmBytes = base64ToUint8Array(message.data);
      const audioBuffer = await pcm16ToAudioBuffer(pcmBytes, this.outputAudioContext, message.sampleRate || 24000);

      const source = this.outputAudioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.outputAudioContext.destination);
      source.start(this.nextStartTime);
      this.nextStartTime += audioBuffer.duration;
      return;
    }

    if (message?.type === "transcript" && message?.text) {
      const src = message?.source === "output" ? "output" : "input";
			if (quietAfterSysKvSet && src === "output") {
				return;
			}
			if (src === "output" && this.lastSysKvSetAt && Date.now() - this.lastSysKvSetAt < 8_000) {
				const t = String(message.text || "").trim().toLowerCase();
				if (t.includes("syskvs")) return;
			}
			if (src === "output" && this.lastVoiceCommandName === "reload_system" && Date.now() - this.lastVoiceCommandAt < 8_000) {
				const t = String(message.text || "").trim().toLowerCase();
				if ((t.includes("reload") || t.includes("reload system")) && t.includes("ambig")) return;
			}
      // Voice UX fallback: auto-trigger local commands from input transcripts.
      // This helps when Gemini doesn't emit a tool call for simple control commands.
      if (src === "input") {
				const trText = String(message.text);
				const cfg = this.voiceCmdCfg || this.buildDefaultVoiceCmdCfg();
				const debounce = typeof cfg?.debounce_ms === "number" ? cfg.debounce_ms : 10_000;
				if (cfg?.enabled ?? true) {
					const reloadMode = this.extractSystemReloadMode(trText);
					if (reloadMode && this.shouldAutoTriggerVoiceCommand("reload_system", debounce)) {
						this.wsSend({ type: "system", action: "reload", mode: reloadMode, trace_id: this.createTraceId("voice_reload") });
					}
					if (this.isModuleStatusReportPhrase(trText) && this.shouldAutoTriggerVoiceCommand("module_status_report", debounce)) {
						this.wsSend({ type: "system", action: "module_status_report", trace_id: this.createTraceId("voice_mod_status") });
					}
					if (cfg?.reminders_add?.enabled ?? true) {
						const remText = this.extractReminderAddText(trText);
						if (remText && this.shouldAutoTriggerVoiceCommand("reminders_add", debounce)) {
							this.wsSend({ type: "reminders", action: "add", text: remText, trace_id: this.createTraceId("voice_rem_add") });
						}
					}
					if (cfg?.gems_list?.enabled ?? true) {
						if (this.isGemsListPhrase(trText) && this.shouldAutoTriggerVoiceCommand("gems_list", debounce)) {
							this.wsSend({ type: "gems", action: "list", trace_id: this.createTraceId("voice_gems_ls") });
						}
					}
				}
				const gemRemoveId = this.extractGemsRemoveId(trText);
				if (gemRemoveId && this.shouldAutoTriggerVoiceCommand("gems_remove", debounce)) {
					this.wsSend({ type: "gems", action: "remove", gem_id: gemRemoveId, id: gemRemoveId, trace_id: this.createTraceId("voice_gems_rm") });
				}
				const gemUpsert = this.extractGemsUpsertJson(trText);
				if (gemUpsert && this.shouldAutoTriggerVoiceCommand("gems_upsert", debounce)) {
					this.wsSend({ type: "gems", action: "upsert", gem: gemUpsert, trace_id: this.createTraceId("voice_gems_upsert") });
				}
				const gemCreateId = this.extractGemsCreateId(trText);
				if (gemCreateId && this.shouldAutoTriggerVoiceCommand("gems_create", debounce)) {
					this.wsSend({ type: "gems", action: "upsert", gem: { id: gemCreateId, name: gemCreateId }, trace_id: this.createTraceId("voice_gems_create") });
				}
				const analyze = this.extractGemsAnalyze(trText);
				if (analyze && this.shouldAutoTriggerVoiceCommand("gems_analyze", debounce)) {
					this.wsSend({ type: "gems", action: "analyze", gem_id: analyze.gem_id, id: analyze.gem_id, criteria: analyze.criteria, trace_id: this.createTraceId("voice_gems_analyze") });
				}
				const draftAct = this.extractGemsDraftAction(trText);
				if (draftAct && this.shouldAutoTriggerVoiceCommand("gems_draft_action", debounce)) {
					if (draftAct.action === "apply") {
						this.wsSend({ type: "gems", action: "draft_apply", draft_id: draftAct.draft_id, trace_id: this.createTraceId("voice_gems_apply") });
					} else {
						this.wsSend({ type: "gems", action: "draft_discard", draft_id: draftAct.draft_id, trace_id: this.createTraceId("voice_gems_discard") });
					}
				}
      }
      this.onMessage({
        id: `${traceId || Date.now()}_${src}_tr`,
        role: src === "output" ? "model" : "system",
        text: String(message.text),
        timestamp: new Date(),
        metadata: {
          type: "text",
          source: src,
          trace_id: traceId,
          ws: wsMeta,
          raw: message,
          severity: src === "output" ? "info" : "debug",
          category: "live",
        },
      });
      return;
    }

    if (message?.type === "text" && message?.text) {
			if (quietAfterSysKvSet) {
				const t0 = String(message.text || "");
				const t = t0.trim().toLowerCase();
				if (!t.startsWith("sys_kv_set ok")) {
					return;
				}
			}
			if (this.lastSysKvSetAt && Date.now() - this.lastSysKvSetAt < 8_000) {
				const t = String(message.text || "").trim().toLowerCase();
				if (t.includes("syskvs")) return;
			}
			if (this.lastVoiceCommandName === "reload_system" && Date.now() - this.lastVoiceCommandAt < 8_000) {
				const t = String(message.text || "").trim().toLowerCase();
				if ((t.includes("reload") || t.includes("reload system")) && t.includes("ambig")) return;
			}
      this.onMessage({
        id: `${Date.now()}`,
        role: "model",
        text: String(message.text),
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "live" },
      });
      return;
    }

    if (message?.type === "error" && message?.message) {
      const kind = message?.kind != null ? String(message.kind) : "";
      let detail = "";
      try {
        const d: any = (message as any)?.detail;
        if (d == null) {
          detail = "";
        } else if (typeof d === "string") {
          detail = d;
        } else {
          detail = JSON.stringify(d, null, 2);
        }
      } catch {
        detail = (message as any)?.detail != null ? String((message as any).detail) : "";
      }
      const gemId = (message as any)?.gem_id != null ? String((message as any).gem_id) : "";
      const category = kind.startsWith("gemini_") ? "live" : "ws";
      const text = `${String(message.message)}${kind ? ` (kind=${kind})` : ""}${gemId ? ` [${gemId}]` : ""}${detail ? `\n${detail}` : ""}`;
      this.onMessage({
        id: `${Date.now()}_err`,
        role: "system",
        text,
        timestamp: new Date(),
        metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "error", category },
      });
      // Backend can emit error events even while keeping the websocket open (e.g. Gemini Live session failed).
      // Do not treat these as transport disconnects.
      try {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.onStateChange(ConnectionState.CONNECTED);
        }
      } catch {
        // ignore
      }
      return;
    }
  }
}