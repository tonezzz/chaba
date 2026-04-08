import { arrayBufferToBase64 } from "./audioUtils";
import { ConnectionState, MessageLog, VoiceCmdConfig, ToolPendingEntry, WsReadinessEvent, PendingEventMessage } from "../types";
import { AudioManager, makeAudioManager, setupAudioInput, teardownAudio } from "./liveAudio";
import { buildDefaultVoiceCmdCfg, mergeVoiceCmdCfg, loadVoiceCmdCfg } from "./liveVoiceCmd";
import { handleBackendMessage, HandlerContext } from "./liveMessageHandlers";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TOOL_TIMEOUT_MS = 20_000;
const VOICE_CMD_CFG_CACHE_MS = 60_000;
const KEEPALIVE_INTERVAL_MS = 25_000;
const RECONNECT_BASE_DELAY_MS = 300;
const RECONNECT_JITTER_MS = 500;

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
  // WebSocket
  private ws: WebSocket | null = null;
  private wsSeq: number = 0;
  private connectInFlight: boolean = false;
  private keepaliveTimer: number | null = null;
  private toolPending: Map<string, ToolPendingEntry> = new Map();
  // Identity
  private sessionId: string | null = null;
  private clientId: string | null = null;
  private clientTag: string | null = null;
  // Audio (delegated to liveAudio)
  private audio: AudioManager = makeAudioManager();
  // Voice command state
  private voiceCmdCfg: VoiceCmdConfig | null = null;
  private voiceCmdCfgLoadedAt: number = 0;
  private lastVoiceCommandTs: Record<string, number> = {};
  private lastVoiceCommandName: string | null = null;
  private lastVoiceCommandAt: number = 0;
  // Suppress-filter state
  private lastSysKvSetAt: number = 0;
  private lastSentUtteranceText: string | null = null;
  private lastSentUtteranceAt: number = 0;

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
			const newId = typeof crypto !== "undefined" && typeof (crypto as any).randomUUID === "function"
				? (crypto as any).randomUUID()
				: `${Date.now()}_${Math.random().toString(16).slice(2)}`;
			window.localStorage.setItem(storageKey, newId);
			return newId;
		} catch {
			return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
		}
	}

	private getOrCreateSessionId(): string {
		const storageKey = "jarvis_session_id";
		try {
			const desiredRaw = (import.meta as any).env?.VITE_JARVIS_SESSION_ID as string | undefined;
			const desired = desiredRaw != null ? String(desiredRaw).trim() : "";
			const existing = String(window.localStorage.getItem(storageKey) || "").trim();
			if (desired) {
				if (existing && existing === desired) return existing;
				window.localStorage.setItem(storageKey, desired);
				return desired;
			}
			if (existing) return existing;
			const newId = typeof crypto !== "undefined" && typeof (crypto as any).randomUUID === "function"
				? (crypto as any).randomUUID()
				: `${Date.now()}_${Math.random().toString(16).slice(2)}`;
			window.localStorage.setItem(storageKey, newId);
			return newId;
		} catch {
			return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
		}
	}

	private wsSend(payload: unknown): boolean {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify(payload));
			return true;
		}
		console.warn("[LiveService] wsSend dropped — WebSocket not open", (payload as any)?.type);
		return false;
	}


	public invokeTool(name: string, args?: Record<string, any>): Promise<any> {
		const toolName = String(name || "").trim();
		if (!toolName) return Promise.reject(new Error("missing_tool_name"));
		if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return Promise.reject(new Error("ws_not_connected"));
		const traceId = this.createTraceId(`tool_${toolName}`);
		const payloadArgs = args && typeof args === "object" ? args : {};
		try {
			this.onMessage({
				id: `${Date.now()}_tool_call_${toolName}`,
				role: "system",
				text: `tool_call ${toolName}`,
				timestamp: new Date(),
				metadata: { trace_id: traceId, kind: "tool_call", severity: "info", category: "ws", raw: { type: "tool_call", name: toolName, args: payloadArgs } },
			});
		} catch {
			// ignore
		}
		return new Promise((resolve, reject) => {
			const timeoutId = window.setTimeout(() => {
				const cur = this.toolPending.get(traceId);
				if (!cur) return;
				this.toolPending.delete(traceId);
				reject(new Error("tool_timeout"));
			}, TOOL_TIMEOUT_MS);
			this.toolPending.set(traceId, { resolve, reject, name: toolName, createdAt: Date.now(), timeoutId });
			this.wsSend({ type: "tool", name: toolName, args: payloadArgs, trace_id: traceId });
		});
	}

	private async ensureVoiceCmdCfgLoaded(force?: boolean): Promise<void> {
		const now = Date.now();
		if (!force && this.voiceCmdCfg && now - this.voiceCmdCfgLoadedAt < VOICE_CMD_CFG_CACHE_MS) return;
		this.voiceCmdCfg = await loadVoiceCmdCfg();
		this.voiceCmdCfgLoadedAt = now;
	}

	public getSessionId(): string {
		if (!this.sessionId) this.sessionId = this.getOrCreateSessionId();
		return this.sessionId;
	}

	public async sendCarsIngestImage(file: File, requestId?: string): Promise<string> {
		if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error("ws_not_connected");
		const buf = await file.arrayBuffer();
		const b64 = arrayBufferToBase64(buf);
		const mimeType = String(file.type || "image/png") || "image/png";
		const reqId = String(requestId || `${Date.now()}_${Math.random().toString(16).slice(2)}`);
		this.wsSend({ type: "cars_ingest_image", request_id: reqId, trace_id: this.createTraceId("cars"), mimeType, data: b64 });
		return reqId;
	}

	public onStateChange: (state: ConnectionState) => void = () => {};
	public onMessage: (msg: MessageLog) => void = () => {};
	public onPendingEvent: (ev: PendingEventMessage) => void = () => {};
	public onReadiness: (ev: WsReadinessEvent) => void = () => {};
	public onVolume: (vol: number) => void = () => {};
	public onCarsIngestResult: (ev: CarsIngestResult) => void = () => {};

	constructor() {}

	public startStreaming(): void {
		this.audio.isStreamingAudio = true;
		void this.ensureAudioInput();
	}

	public stopStreaming(): void {
		this.audio.isStreamingAudio = false;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.wsSend({ type: "audio_stream_end", trace_id: this.createTraceId("audio_end") });
		}
	}

	private async ensureAudioInput(): Promise<void> {
		const am = this.audio;
		try {
			if (!am.inputAudioContext) {
				am.inputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
			}
			if (!am.outputAudioContext) {
				am.outputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
			}
			// Resume AudioContexts if suspended (required after user gesture)
			if (am.inputAudioContext.state === "suspended") await am.inputAudioContext.resume();
			if (am.outputAudioContext.state === "suspended") await am.outputAudioContext.resume();
			if (!am.inputStream) {
				am.audioInitError = null;
				am.inputStream = await navigator.mediaDevices.getUserMedia({ audio: true });
			}
			if (am.inputStream) {
				await setupAudioInput(am, am.inputStream, (p) => this.createTraceId(p), (pl) => this.wsSend(pl), (v) => this.onVolume(v));
			}
		} catch (audioErr: any) {
			am.inputStream = null;
			am.isStreamingAudio = false;
			const name = String(audioErr?.name || "unknown");
			const msg = String(audioErr?.message || audioErr || "unknown");
			am.audioInitError = `${name}: ${msg}`;
			try {
				this.onMessage({ id: `${Date.now()}_audio_unavailable`, role: "system", text: `audio_unavailable: ${am.audioInitError}`, timestamp: new Date() });
			} catch {
				// ignore
			}
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

	public updateCameraFrame(_base64: string): void {
		// Reserved for future vision support; no-op until backend protocol is defined.
	}

	public sendSystemReload(mode: "full" | "memory" | "knowledge" | "sys" | "gems" = "full"): void {
		this.wsSend({ type: "system", action: "reload", mode, trace_id: this.createTraceId("sys_reload") });
	}

	public sendSystemClearJob(): void {
		this.wsSend({ type: "system", action: "clear_job", trace_id: this.createTraceId("sys_clear_job") });
	}

	public sendSysKvSet(key: string, value: string, opts?: { dry_run?: boolean }): void {
		const k = String(key || "").trim();
		const v = String(value ?? "");
		if (!k) return;
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.lastSysKvSetAt = Date.now();
			this.wsSend({ type: "system", action: "sys_kv_set", key: k, value: v, dry_run: Boolean(opts?.dry_run), trace_id: this.createTraceId("sys_kv_set") });
		}
	}

	public sendSysKvDedupe(opts?: { dry_run?: boolean; sort?: boolean }): void {
		this.wsSend({ type: "system", action: "sys_kv_dedupe", dry_run: Boolean(opts?.dry_run), sort: Boolean(opts?.sort), trace_id: this.createTraceId("sys_kv_dedupe") });
	}

	public sendRemindersAdd(text: string): void {
		const body = String(text || "").trim();
		if (!body) return;
		this.wsSend({ type: "reminders", action: "add", text: body, trace_id: this.createTraceId("rem_add") });
	}

	public sendGemsList(): void {
		this.wsSend({ type: "gems", action: "list", trace_id: this.createTraceId("gems_ls") });
	}

	public sendGemsUpsert(gem: unknown): void {
		if (!gem || typeof gem !== "object") return;
		this.wsSend({ type: "gems", action: "upsert", gem, trace_id: this.createTraceId("gems_upsert") });
	}

	public sendGemsRemove(id: string): void {
		const gem_id = String(id || "").trim();
		if (!gem_id) return;
		this.wsSend({ type: "gems", action: "remove", gem_id, id: gem_id, trace_id: this.createTraceId("gems_rm") });
	}

	public sendGemsAnalyze(gemId: string, criteria?: string): void {
		const gem_id = String(gemId || "").trim();
		const crit = String(criteria || "").trim();
		if (!gem_id) return;
		this.wsSend({ type: "gems", action: "analyze", gem_id, id: gem_id, criteria: crit, trace_id: this.createTraceId("gems_analyze") });
	}

	public sendGemsDraftApply(draftId: string): void {
		const draft_id = String(draftId || "").trim();
		if (!draft_id) return;
		this.wsSend({ type: "gems", action: "draft_apply", draft_id, trace_id: this.createTraceId("gems_apply") });
	}

	public sendGemsDraftDiscard(draftId: string): void {
		const draft_id = String(draftId || "").trim();
		if (!draft_id) return;
		this.wsSend({ type: "gems", action: "draft_discard", draft_id, trace_id: this.createTraceId("gems_discard") });
	}

	public async connect(): Promise<void> {
		if (this.connectInFlight) return;
		if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
		this.connectInFlight = true;
		this.onStateChange(ConnectionState.CONNECTING);

		try {
			if (this.ws) {
				try { this.ws.onopen = null; this.ws.onclose = null; this.ws.onerror = null; this.ws.onmessage = null; this.ws.close(); } catch { }
				this.ws = null;
			}
			if (this.keepaliveTimer != null) { try { window.clearInterval(this.keepaliveTimer); } catch { } this.keepaliveTimer = null; }

			const mySeq = ++this.wsSeq;
			const am = this.audio;
			// AudioContexts are created lazily in ensureAudioInput() after user gesture

			const backendUrl = (import.meta as any).env?.VITE_JARVIS_WS_URL as string | undefined;
			const proto = location.protocol === "https:" ? "wss" : "ws";
			const isJarvisSubpath = location.pathname.startsWith("/jarvis");
			const defaultWsUrl = isJarvisSubpath ? `${proto}://${location.host}/jarvis/ws/live` : `${proto}://${location.hostname}:8018/ws/live`;
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
					if (this.keepaliveTimer != null) { window.clearInterval(this.keepaliveTimer); this.keepaliveTimer = null; }
					this.keepaliveTimer = window.setInterval(() => {
						try { if (this.ws && this.ws.readyState === WebSocket.OPEN) this.wsSend({ type: "ping", trace_id: this.createTraceId("ping") }); } catch { }
					}, KEEPALIVE_INTERVAL_MS);
				} catch { }
				this.onReadiness({ phase: "ws_open", ts: Date.now() });
				this.onMessage({
					id: `${Date.now()}_ws_open`,
					role: "system",
					text: "connected",
					timestamp: new Date(),
					metadata: { trace_id: this.createTraceId("ws_open"), ws: { type: "ws_open", instance_id: sessionId, client_tag: clientTag, client_id: clientId }, raw: { type: "ws_open" }, severity: "info", category: "ws" },
				});
				try { if (am.outputAudioContext && am.outputAudioContext.state === "suspended") void am.outputAudioContext.resume(); } catch { }
				if (am.inputStream) {
					void setupAudioInput(am, am.inputStream, (p) => this.createTraceId(p), (pl) => this.wsSend(pl), (v) => this.onVolume(v));
				} else {
					this.onMessage({ id: `${Date.now()}_text_only`, role: "system", text: "text_only_mode", timestamp: new Date() });
				}
			};
			this.ws.onclose = (ev) => {
				if (mySeq !== this.wsSeq) return;
				this.connectInFlight = false;
				if (this.keepaliveTimer != null) { try { window.clearInterval(this.keepaliveTimer); } catch { } this.keepaliveTimer = null; }
				const quiet = ev.code === 4000 || String(ev.reason || "").toLowerCase().includes("session_taken_over");
				if (!quiet) { try { console.warn("ws_close", { code: ev.code, reason: ev.reason, wasClean: ev.wasClean }); } catch { } }
				this.onStateChange(ConnectionState.DISCONNECTED);
				try { this.onReadiness({ phase: "ws_closed", detail: { code: ev.code, reason: ev.reason, wasClean: ev.wasClean }, ts: Date.now() }); } catch { }
				if (!quiet) {
					this.onMessage({
						id: `${Date.now()}_ws_close`,
						role: "system",
						text: `disconnected (code=${ev.code}${ev.reason ? ` reason=${ev.reason}` : ""})`,
						timestamp: new Date(),
						metadata: { trace_id: this.createTraceId("ws_close"), ws: { type: "ws_close", instance_id: sessionId, client_tag: clientTag, client_id: clientId }, raw: { type: "ws_close" }, severity: "info", category: "ws" },
					});
				}
			};
			this.ws.onerror = (err) => {
				if (mySeq !== this.wsSeq) return;
				this.connectInFlight = false;
				if (this.keepaliveTimer != null) { try { window.clearInterval(this.keepaliveTimer); } catch { } this.keepaliveTimer = null; }
				console.error(err);
				this.onStateChange(ConnectionState.ERROR);
				try { this.onReadiness({ phase: "ws_error", ts: Date.now() }); } catch { }
				this.onMessage({
					id: `${Date.now()}_ws_error`,
					role: "system",
					text: "connection_error",
					timestamp: new Date(),
					metadata: { trace_id: this.createTraceId("ws_error"), ws: { type: "ws_error", instance_id: sessionId, client_tag: clientTag, client_id: clientId }, raw: { type: "ws_error" }, severity: "info", category: "ws" },
				});
			};
			this.ws.onmessage = (event) => {
				if (mySeq !== this.wsSeq) return;
				try {
					const msg = JSON.parse(event.data);
					void handleBackendMessage(this.makeHandlerCtx(), msg);
				} catch (e) { console.error(e); }
			};
		} catch (error) {
			console.error("Connection failed", error);
			this.onStateChange(ConnectionState.ERROR);
		} finally {
			if (!this.ws || this.ws.readyState === WebSocket.CLOSED) this.connectInFlight = false;
		}
	}

	public async disconnect(): Promise<void> {
		this.wsSeq += 1;
		this.connectInFlight = false;
		if (this.ws) {
			try { this.ws.send(JSON.stringify({ type: "close" })); } catch (e) { console.error(e); }
			this.ws.close();
		}
		if (this.keepaliveTimer != null) { try { window.clearInterval(this.keepaliveTimer); } catch { } this.keepaliveTimer = null; }
		try {
			if (this.audio.inputStream) for (const t of this.audio.inputStream.getTracks()) t.stop();
		} catch { }
		this.audio.inputStream = null;
		await teardownAudio(this.audio);
		this.ws = null;
		for (const [id, entry] of this.toolPending) {
			window.clearTimeout(entry.timeoutId);
			entry.reject(new Error("disconnected"));
			this.toolPending.delete(id);
		}
		this.onStateChange(ConnectionState.DISCONNECTED);
	}

	private async reconnectWithBackoff(): Promise<void> {
		try { await this.disconnect(); } catch { }
		await new Promise((r) => setTimeout(r, RECONNECT_BASE_DELAY_MS + Math.floor(Math.random() * RECONNECT_JITTER_MS)));
		await this.connect();
	}

	private makeHandlerCtx(): HandlerContext {
		return {
			ws: this.ws,
			toolPending: this.toolPending,
			audio: this.audio,
			lastSysKvSetAt: this.lastSysKvSetAt,
			lastVoiceCommandName: this.lastVoiceCommandName,
			lastVoiceCommandAt: this.lastVoiceCommandAt,
			lastSentUtteranceText: this.lastSentUtteranceText,
			lastSentUtteranceAt: this.lastSentUtteranceAt,
			voiceCmdCfg: this.voiceCmdCfg,
			lastVoiceCommandTs: this.lastVoiceCommandTs,
			onMessage: (m) => this.onMessage(m),
			onReadiness: (e) => this.onReadiness(e),
			onPendingEvent: (e) => this.onPendingEvent(e),
			onStateChange: (s) => this.onStateChange(s),
			onCarsIngestResult: (e) => this.onCarsIngestResult(e),
			wsSend: (p) => this.wsSend(p),
			createTraceId: (p) => this.createTraceId(p),
			/**
			 * Bounded reconnect with jitter to prevent recursion storms.
			 * Single attempt with 300ms + random 0-500ms delay.
			 */
			reconnectWithBackoff: () => this.reconnectWithBackoff(),
		};
	}
}
