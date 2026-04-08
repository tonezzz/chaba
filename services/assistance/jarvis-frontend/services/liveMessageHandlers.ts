import { ConnectionState, MessageLog, ToolPendingEntry, WsReadinessEvent, PendingEventMessage } from "../types";
import { CarsIngestResult } from "./liveService";
import { AudioManager, playPcmAudio } from "./liveAudio";
import {
	buildDefaultVoiceCmdCfg,
	extractSystemReloadMode,
	isModuleStatusReportPhrase,
	extractReminderAddText,
	isGemsListPhrase,
	extractGemsRemoveId,
	extractGemsUpsertJson,
	extractGemsCreateId,
	extractGemsAnalyze,
	extractGemsDraftAction,
} from "./liveVoiceCmd";
import { VoiceCmdConfig } from "../types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYS_KV_QUIET_WINDOW_MS = 8_000;
const SYS_KV_SET_QUIET_WINDOW_MS = 6_000;
const UTTERANCE_DEDUP_WINDOW_MS = 3_000;
const DEFAULT_VOICE_CMD_DEBOUNCE_MS = 10_000;

// ---------------------------------------------------------------------------
// Shared context passed into every handler
// ---------------------------------------------------------------------------

/**
 * HandlerContext provides isolated dependencies to message handlers.
 *
 * MUTABILITY CONTRACT:
 * - Primitive state fields (numbers, strings) are mutated directly by handlers
 *   (lastSysKvSetAt, lastVoiceCommandAt, lastSentUtteranceAt, etc.)
 * - Object refs (audio, toolPending) are NOT replaced; only their contents modified
 * - Callbacks (onMessage, onStateChange) are fire-and-forget; never awaited
 *
 * RECONNECT SAFETY:
 * - Use reconnectWithBackoff() instead of raw connect/disconnect to prevent
 *   recursion storms. It includes jitter and a single retry attempt.
 */
export interface HandlerContext {
	// WebSocket state (readonly ref; check readyState before use)
	ws: WebSocket | null;
	toolPending: Map<string, ToolPendingEntry>;

	// Audio (mutable contents, stable ref)
	audio: AudioManager;

	// Suppress-filter state (mutated by handlers)
	lastSysKvSetAt: number;
	lastVoiceCommandName: string | null;
	lastVoiceCommandAt: number;

	// Utterance dedup state (mutated by handlers)
	lastSentUtteranceText: string | null;
	lastSentUtteranceAt: number;

	// Voice cmd state (mutable)
	voiceCmdCfg: VoiceCmdConfig | null;
	lastVoiceCommandTs: Record<string, number>;

	// Callbacks (fire-and-forget)
	onMessage: (msg: MessageLog) => void;
	onReadiness: (ev: WsReadinessEvent) => void;
	onPendingEvent: (ev: PendingEventMessage) => void;
	onStateChange: (state: ConnectionState) => void;
	onCarsIngestResult: (ev: CarsIngestResult) => void;

	// Helpers
	wsSend: (payload: unknown) => boolean;
	createTraceId: (prefix: string) => string;

	/**
	 * Bounded reconnect with jitter (300ms + 0-500ms random).
	 * Use this instead of manual disconnect+connect to prevent recursion.
	 */
	reconnectWithBackoff: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Suppress helper
// ---------------------------------------------------------------------------

export function shouldSuppressOutputMessage(
	ctx: HandlerContext,
	text: string,
	quietAfterSysKvSet: number | boolean,
	isTextMsg = false,
): boolean {
	const t = text.trim().toLowerCase();
	if (quietAfterSysKvSet) {
		if (isTextMsg && t.startsWith("sys_kv_set ok")) return false;
		return true;
	}
	if (ctx.lastSysKvSetAt && Date.now() - ctx.lastSysKvSetAt < SYS_KV_QUIET_WINDOW_MS && t.includes("syskvs")) return true;
	if (ctx.lastVoiceCommandName === "reload_system" && Date.now() - ctx.lastVoiceCommandAt < SYS_KV_QUIET_WINDOW_MS) {
		if ((t.includes("reload") || t.includes("reload system")) && t.includes("ambig")) return true;
	}
	return false;
}

// ---------------------------------------------------------------------------
// shouldAutoTriggerVoiceCommand (mutates ctx)
// ---------------------------------------------------------------------------

function shouldAutoTriggerVoiceCommand(ctx: HandlerContext, key: string, debounceMs: number): boolean {
	const now = Date.now();
	const prev = ctx.lastVoiceCommandTs[key] || 0;
	if (now - prev < debounceMs) return false;
	ctx.lastVoiceCommandTs[key] = now;
	ctx.lastVoiceCommandName = key;
	ctx.lastVoiceCommandAt = now;
	return true;
}

// ---------------------------------------------------------------------------
// Main dispatcher
// ---------------------------------------------------------------------------

export async function handleBackendMessage(ctx: HandlerContext, message: any): Promise<void> {
	const traceId = message?.trace_id != null ? String(message.trace_id) : undefined;
	const quietAfterSysKvSet = ctx.lastSysKvSetAt && Date.now() - ctx.lastSysKvSetAt < SYS_KV_SET_QUIET_WINDOW_MS;
	const wsMeta = {
		type: message?.type != null ? String(message.type) : undefined,
		instance_id: message?.instance_id != null ? String(message.instance_id) : undefined,
		client_tag: message?.client_tag != null ? String(message.client_tag) : undefined,
		client_id: message?.client_id != null ? String(message.client_id) : undefined,
	};

	if (message?.type === "readiness") {
		try {
			const phase = message?.phase != null ? String(message.phase) : "";
			ctx.onReadiness({ phase, detail: message as unknown, ts: Date.now() });
		} catch {
			// ignore
		}
		return;
	}

	if (message?.type === "session_resume") {
		const ok = message?.ok === true;
		const turns = Array.isArray(message?.turns) ? message.turns : [];
		ctx.onMessage({
			id: `${Date.now()}_session_resume`,
			role: "system",
			text: ok ? `session_resume ok turns=${turns.length}` : "session_resume empty",
			timestamp: new Date(),
			metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws", resume: { ok, turns } },
		});
		return;
	}

	if (message?.type === "ui") {
		const kind = message?.kind != null ? String(message.kind) : "ui";
		const title = message?.title != null ? String(message.title) : "";
		const summary = title ? `${kind}: ${title}` : String(kind);
		ctx.onMessage({
			id: `${Date.now()}_ui_${Math.random().toString(16).slice(2)}`,
			role: "system",
			text: summary,
			timestamp: new Date(),
			metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
		});
		return;
	}

	if (message?.type === "tool_result") {
		const toolName = message?.name != null ? String(message.name) : "tool";
		const ok = message?.ok === true;
		if (traceId) {
			const pending = ctx.toolPending.get(traceId);
			if (pending) {
				window.clearTimeout(pending.timeoutId);
				ctx.toolPending.delete(traceId);
				if (ok) pending.resolve(message?.result);
				else pending.reject(message?.error ?? "tool_failed");
			}
		}
		ctx.onMessage({
			id: `${Date.now()}_tool_result_${toolName}`,
			role: "system",
			text: `tool_result ${toolName}: ${ok ? "ok" : "error"}`,
			timestamp: new Date(),
			metadata: { trace_id: traceId, kind: "tool_result", ws: wsMeta, raw: message, severity: ok ? "info" : "warn", category: "ws" },
		});
		return;
	}

	if (message?.type === "pending_event") {
		try { ctx.onPendingEvent(message as PendingEventMessage); } catch { }
		try {
			const evRaw = String(message?.event || "pending").trim() || "pending";
			const ev = evRaw.toLowerCase();
			const evNorm = ev.replace(/\s+/g, "_");
			const cid = String(message?.confirmation_id || "").trim();
			const action = String(message?.action || "").trim();
			if (evNorm === "awaiting_user" && cid) {
				const payload = (message as any)?.payload;
				let body = "";
				try { if (payload != null) body = JSON.stringify(payload, null, 2); } catch { body = String(payload ?? ""); }
				ctx.onMessage({
					id: `${Date.now()}_pending_await_${Math.random().toString(16).slice(2)}`,
					role: "system",
					text: `pending: ${action || "confirm"}`,
					timestamp: new Date(),
					metadata: {
						trace_id: traceId, ws: wsMeta,
						raw: {
							type: "ui", kind: "pending",
							title: action ? `Confirm: ${action}` : "Confirm pending action",
							body, risk: "high", confirmation_id: cid,
							primary: { label: "Confirm", tool: "pending_confirm", args: {} },
							secondary: { label: "Cancel", tool: "pending_cancel", args: {} },
							tertiary: { label: "Preview", tool: "pending_preview", args: {} },
						},
						severity: "info", category: "ws",
					},
				});
				return;
			}
			ctx.onMessage({
				id: `${Date.now()}_pending_event_${ev}`,
				role: "system",
				text: `pending_event ${evRaw}${action ? ` action=${action}` : ""}${cid ? ` id=${cid}` : ""}`,
				timestamp: new Date(),
				metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
			});
		} catch { }
		return;
	}

	if (message?.type === "reconnect") {
		const reason = message?.reason != null ? String(message.reason) : "";
		if (reason.toLowerCase().includes("session_taken_over")) return;
		ctx.onMessage({
			id: `${Date.now()}_reconnect`,
			role: "system",
			text: `reconnect_requested${reason ? `: ${reason}` : ""}`,
			timestamp: new Date(),
			metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" },
		});
		// Use bounded reconnect helper to prevent recursion storms
		try { await ctx.reconnectWithBackoff(); } catch { }
		return;
	}

	// After a deterministic /sys set, suppress progress noise but keep the ok text visible.
	if (quietAfterSysKvSet && message?.type === "progress") return;

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
			ctx.onMessage({ id: "sticky_progress", role: "system", text: "", timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "debug", category: "ws" } });
			if (text) ctx.onMessage({ id: `${Date.now()}_progress_${phase}`, role: "system", text, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: phase === "error" ? "warn" : "info", category: "ws" } });
		} else {
			ctx.onMessage({ id: "sticky_progress", role: "system", text: text || "working…", timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" } });
		}
		return;
	}

	if (message?.type === "state" && message?.state) {
		ctx.onMessage({ id: `${Date.now()}_state`, role: "system", text: String(message.state), timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" } });
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
		ctx.onMessage({ id: `${Date.now()}_reminder_setup`, role: "model", text: `reminder_setup: ${title}${rid ? ` [${rid}]` : ""} (${status})${hint ? ` — ${hint}` : ""}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (message?.type === "reminder_setup_draft") {
		const title = message?.title != null ? String(message.title) : "Reminder";
		const hint = message?.result?.hint != null ? String(message.result.hint) : "";
		ctx.onMessage({ id: `${Date.now()}_reminder_draft`, role: "model", text: `reminder_draft: ${title}${hint ? ` — ${hint}` : ""}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (message?.type === "reminder_setup_cancelled") {
		ctx.onMessage({ id: `${Date.now()}_reminder_cancelled`, role: "model", text: "reminder_draft_cancelled", timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (message?.type === "planning_item_created") {
		const kind = message?.kind != null ? String(message.kind) : "";
		const title = message?.title != null ? String(message.title) : "";
		const ok = (message as any)?.result?.ok === true;
		const localTime = (message as any)?.result?.local_time != null ? String((message as any).result.local_time) : "";
		ctx.onMessage({ id: `${Date.now()}_planning_item_created`, role: "model", text: `planning_item_created: ${kind || "item"}${title ? ` — ${title}` : ""}${ok ? " (ok)" : ""}${localTime ? ` @ ${localTime}` : ""}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: ok ? "info" : "warn", category: "reminder" } });
		return;
	}

	if (message?.type === "reminders_list") {
		const status = message?.status != null ? String(message.status) : "";
		const day = message?.day != null ? String(message.day) : "";
		const items: any[] = Array.isArray((message as any)?.items) ? (message as any).items : [];
		const lines: string[] = [`reminders_list${day ? ` (${day})` : ""}${status ? ` status=${status}` : ""}`];
		if (!items.length) { lines.push("(no results)"); } else {
			for (const r of items.slice(0, 50)) {
				const rid = r?.reminder_id != null ? String(r.reminder_id) : "";
				const t = r?.title != null ? String(r.title) : "Reminder";
				const st = r?.status != null ? String(r.status) : "";
				const ts = r?.notify_at != null ? ` notify_at=${String(r.notify_at)}` : r?.due_at != null ? ` due_at=${String(r.due_at)}` : "";
				lines.push(`- ${t}${rid ? ` [${rid}]` : ""}${st ? ` (${st})` : ""}${ts}`);
			}
		}
		ctx.onMessage({ id: `${Date.now()}_reminders_list`, role: "model", text: lines.join("\n"), timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (typeof message?.type === "string" && message.type.startsWith("reminders_")) {
		const t = String(message.type);
		const rid = (message as any)?.reminder_id != null ? String((message as any).reminder_id) : "";
		const changed = (message as any)?.changed;
		const extra = typeof changed === "boolean" ? ` changed=${changed}` : "";
		ctx.onMessage({ id: `${Date.now()}_${t}`, role: "model", text: `${t}${rid ? ` [${rid}]` : ""}${extra}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (message?.type === "gems_list") {
		const items: any[] = Array.isArray((message as any)?.items) ? (message as any).items : [];
		const lines: string[] = ["gems_list"];
		if (!items.length) { lines.push("(no results)"); } else {
			for (const g of items.slice(0, 50)) {
				const id = g?.id != null ? String(g.id) : "";
				const name = g?.name != null ? String(g.name) : "";
				const purpose = g?.purpose != null ? String(g.purpose) : "";
				lines.push(`- ${id}${name ? ` — ${name}` : ""}${purpose ? ` (${purpose})` : ""}`);
			}
		}
		ctx.onMessage({ id: `${Date.now()}_gems_list`, role: "model", text: lines.join("\n"), timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" } });
		return;
	}

	if (message?.type === "gems_draft_created") {
		const gemId = (message as any)?.gem_id != null ? String((message as any).gem_id) : "";
		const draftId = (message as any)?.draft_id != null ? String((message as any).draft_id) : "";
		const changed: string[] = Array.isArray((message as any)?.changed) ? (message as any).changed.map(String) : [];
		ctx.onMessage({ id: `${Date.now()}_gems_draft_created`, role: "model", text: `gems_draft_created${gemId ? ` [${gemId}]` : ""}${draftId ? ` draft=${draftId}` : ""}${changed.length ? ` changed=${changed.join(",")}` : ""}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" } });
		return;
	}

	if (typeof message?.type === "string" && message.type.startsWith("gems_")) {
		const t = String(message.type);
		const gemId = (message as any)?.gem_id != null ? String((message as any).gem_id) : "";
		const op = (message as any)?.op != null ? String((message as any).op) : "";
		ctx.onMessage({ id: `${Date.now()}_${t}`, role: "model", text: `${t}${gemId ? ` [${gemId}]` : ""}${op ? ` op=${op}` : ""}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "ws" } });
		return;
	}

	if (message?.type === "reminder_helper_list") {
		const status = message?.status != null ? String(message.status) : "";
		const includeHidden = message?.include_hidden === true;
		const day = message?.day != null ? String(message.day) : "";
		const reminders: any[] = Array.isArray((message as any)?.reminders) ? (message as any).reminders : [];
		const lines: string[] = [`reminder_helper_list${day ? ` (${day})` : ""}${status ? ` status=${status}` : ""}${includeHidden ? " include_hidden" : ""}`];
		if (!reminders.length) {
			lines.push(day === "today" ? "No reminders today." : day === "yesterday" ? "No reminders yesterday." : "(no results)");
		} else {
			for (const r of reminders.slice(0, 50)) {
				const rid = r?.reminder_id != null ? String(r.reminder_id) : "";
				const t = r?.title != null ? String(r.title) : "Reminder";
				const st = r?.status != null ? String(r.status) : "";
				const ts = r?.notify_at != null ? ` notify_at=${String(r.notify_at)}` : r?.due_at != null ? ` due_at=${String(r.due_at)}` : "";
				lines.push(`- ${t}${rid ? ` [${rid}]` : ""}${st ? ` (${st})` : ""}${ts}`);
			}
		}
		ctx.onMessage({ id: `${Date.now()}_reminder_helper_list`, role: "model", text: lines.join("\n"), timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (typeof message?.type === "string" && message.type.startsWith("reminder_helper_")) {
		const t = String(message.type);
		const rid = message?.reminder_id != null ? String(message.reminder_id) : "";
		const summary = message?.message != null ? String(message.message) : "";
		ctx.onMessage({ id: `${Date.now()}_${t}`, role: "model", text: `${t}${rid ? ` [${rid}]` : ""}${summary ? ` — ${summary}` : ""}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (message?.type === "reminder" && message?.reminder) {
		const r = message.reminder;
		const title = r?.title != null ? String(r.title) : "Reminder";
		const schedule = r?.schedule_type != null ? String(r.schedule_type) : "";
		ctx.onMessage({ id: `${Date.now()}_reminder`, role: "model", text: schedule ? `reminder: ${title} (${schedule})` : `reminder: ${title}`, timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "reminder" } });
		return;
	}

	if (message?.type === "cars_ingest_result" && message?.request_id) {
		try { ctx.onCarsIngestResult(message as CarsIngestResult); } catch { }
		return;
	}

	if (message?.type === "audio" && message?.data) {
		await playPcmAudio(ctx.audio, String(message.data), Number(message.sampleRate) || 24000);
		return;
	}

	if (message?.type === "transcript" && message?.text) {
		const src = message?.source === "output" ? "output" : "input";
		if (src === "output" && shouldSuppressOutputMessage(ctx, String(message.text || ""), quietAfterSysKvSet)) return;

		// Finalized input transcript → forward as text to Jarvis.
		if (src === "input" && message?.partial !== true) {
			const utterance = String(message.text || "").trim();
			if (utterance) {
				const now = Date.now();
				const sameAsLast = ctx.lastSentUtteranceText && utterance === ctx.lastSentUtteranceText;
				const recentlySent = now - ctx.lastSentUtteranceAt < UTTERANCE_DEDUP_WINDOW_MS;
				if (!(sameAsLast && recentlySent)) {
					ctx.lastSentUtteranceText = utterance;
					ctx.lastSentUtteranceAt = now;
					try { ctx.wsSend({ type: "text", text: utterance, trace_id: ctx.createTraceId("stt_text") }); } catch { }
				}
			}
		}

		// Voice UX fallback: auto-trigger local commands from input transcripts.
		if (src === "input") {
			const trText = String(message.text);
			const cfg = ctx.voiceCmdCfg || buildDefaultVoiceCmdCfg();
			const debounce = typeof cfg?.debounce_ms === "number" ? cfg.debounce_ms : DEFAULT_VOICE_CMD_DEBOUNCE_MS;
			if (cfg?.enabled ?? true) {
				const reloadMode = extractSystemReloadMode(trText, cfg);
				if (reloadMode && shouldAutoTriggerVoiceCommand(ctx, "reload_system", debounce)) {
					ctx.wsSend({ type: "system", action: "reload", mode: reloadMode, trace_id: ctx.createTraceId("voice_reload") });
				}
				if (isModuleStatusReportPhrase(trText) && shouldAutoTriggerVoiceCommand(ctx, "module_status_report", debounce)) {
					ctx.wsSend({ type: "system", action: "module_status_report", trace_id: ctx.createTraceId("voice_mod_status") });
				}
				if ((cfg?.reminders_add?.enabled ?? true)) {
					const remText = extractReminderAddText(trText);
					if (remText && shouldAutoTriggerVoiceCommand(ctx, "reminders_add", debounce)) {
						ctx.wsSend({ type: "reminders", action: "add", text: remText, trace_id: ctx.createTraceId("voice_rem_add") });
					}
				}
				if ((cfg?.gems_list?.enabled ?? true) && isGemsListPhrase(trText) && shouldAutoTriggerVoiceCommand(ctx, "gems_list", debounce)) {
					ctx.wsSend({ type: "gems", action: "list", trace_id: ctx.createTraceId("voice_gems_ls") });
				}
			}
			const gemRemoveId = extractGemsRemoveId(trText);
			if (gemRemoveId && shouldAutoTriggerVoiceCommand(ctx, "gems_remove", debounce ?? DEFAULT_VOICE_CMD_DEBOUNCE_MS)) {
				ctx.wsSend({ type: "gems", action: "remove", gem_id: gemRemoveId, id: gemRemoveId, trace_id: ctx.createTraceId("voice_gems_rm") });
			}
			const gemUpsert = extractGemsUpsertJson(trText);
			if (gemUpsert && shouldAutoTriggerVoiceCommand(ctx, "gems_upsert", debounce ?? DEFAULT_VOICE_CMD_DEBOUNCE_MS)) {
				ctx.wsSend({ type: "gems", action: "upsert", gem: gemUpsert, trace_id: ctx.createTraceId("voice_gems_upsert") });
			}
			const gemCreateId = extractGemsCreateId(trText);
			if (gemCreateId && shouldAutoTriggerVoiceCommand(ctx, "gems_create", debounce ?? DEFAULT_VOICE_CMD_DEBOUNCE_MS)) {
				ctx.wsSend({ type: "gems", action: "upsert", gem: { id: gemCreateId, name: gemCreateId }, trace_id: ctx.createTraceId("voice_gems_create") });
			}
			const analyze = extractGemsAnalyze(trText);
			if (analyze && shouldAutoTriggerVoiceCommand(ctx, "gems_analyze", debounce ?? DEFAULT_VOICE_CMD_DEBOUNCE_MS)) {
				ctx.wsSend({ type: "gems", action: "analyze", gem_id: analyze.gem_id, id: analyze.gem_id, criteria: analyze.criteria, trace_id: ctx.createTraceId("voice_gems_analyze") });
			}
			const draftAct = extractGemsDraftAction(trText);
			if (draftAct && shouldAutoTriggerVoiceCommand(ctx, "gems_draft_action", debounce ?? DEFAULT_VOICE_CMD_DEBOUNCE_MS)) {
				if (draftAct.action === "apply") {
					ctx.wsSend({ type: "gems", action: "draft_apply", draft_id: draftAct.draft_id, trace_id: ctx.createTraceId("voice_gems_apply") });
				} else {
					ctx.wsSend({ type: "gems", action: "draft_discard", draft_id: draftAct.draft_id, trace_id: ctx.createTraceId("voice_gems_discard") });
				}
			}
		}

		ctx.onMessage({
			id: `${traceId || Date.now()}_${src}_tr`,
			role: src === "output" ? "model" : "system",
			text: String(message.text),
			timestamp: new Date(),
			metadata: { type: "text", source: src, trace_id: traceId, ws: wsMeta, raw: message, severity: src === "output" ? "info" : "debug", category: "live" },
		});
		return;
	}

	if (message?.type === "text" && message?.text) {
		if (shouldSuppressOutputMessage(ctx, String(message.text || ""), quietAfterSysKvSet, true)) return;
		ctx.onMessage({ id: `${Date.now()}`, role: "model", text: String(message.text), timestamp: new Date(), metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "info", category: "live" } });
		return;
	}

	if (message?.type === "error" && message?.message) {
		const kind = message?.kind != null ? String(message.kind) : "";
		let detail = "";
		try {
			const d = (message as any)?.detail;
			if (d == null) detail = "";
			else if (typeof d === "string") detail = d;
			else detail = JSON.stringify(d, null, 2);
		} catch { detail = (message as any)?.detail != null ? String((message as any).detail) : ""; }
		const gemId = (message as any)?.gem_id != null ? String((message as any).gem_id) : "";
		const category = kind.startsWith("gemini_") ? "live" : "ws";
		ctx.onMessage({
			id: `${Date.now()}_err`,
			role: "system",
			text: `${String(message.message)}${kind ? ` (kind=${kind})` : ""}${gemId ? ` [${gemId}]` : ""}${detail ? `\n${detail}` : ""}`,
			timestamp: new Date(),
			metadata: { trace_id: traceId, ws: wsMeta, raw: message, severity: "error", category },
		});
		// Backend errors don't necessarily mean transport disconnect.
		try {
			if (ctx.ws && ctx.ws.readyState === WebSocket.OPEN) ctx.onStateChange(ConnectionState.CONNECTED);
		} catch { }
		return;
	}
}
