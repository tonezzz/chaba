import React from "react";
import {
  Activity,
  AlertTriangle,
  Camera,
  CheckCircle2,
  ChevronRight,
  Copy,
  Image as ImageIcon,
  Link2Off,
  Maximize2,
  Mic,
  MicOff,
  Minimize2,
  Paperclip,
  Search,
  Send,
  X,
  XCircle,
} from "lucide-react";

import type { LiveService } from "../../services/liveService";
import { ConnectionState, type MessageLog } from "../../types";

export function LeftPanel(props: {
  leftFullscreen: boolean;
  setLeftFullscreen: React.Dispatch<React.SetStateAction<boolean>>;

  state: ConnectionState;
  statusDetailsOpen: boolean;
  setStatusDetailsOpen: React.Dispatch<React.SetStateAction<boolean>>;

  systemCounts: { memory: number; knowledge: number; ok: boolean };
  audioStatus: { ok: boolean; lastConn: number; lastAudioUnavailable: number };

  depsStatusError: string;
  depsStatus: any;
  setDepsStatusRefreshNonce: React.Dispatch<React.SetStateAction<number>>;

  handleConnect: () => void;

  logScrollRef: React.RefObject<HTMLDivElement | null>;
  logStickToBottomRef: React.MutableRefObject<boolean>;

  messages: MessageLog[];
  showDebugLogs: boolean;
  setShowDebugLogs: React.Dispatch<React.SetStateAction<boolean>>;

  expandedLogId: string | null;
  setExpandedLogId: React.Dispatch<React.SetStateAction<string | null>>;

  uiCardInputByMsgId: Record<string, string>;
  setUiCardInputByMsgId: React.Dispatch<React.SetStateAction<Record<string, string>>>;

  copyText: (text: string) => Promise<void>;
  clientLabelForMsg: (m: MessageLog) => string;

  liveServiceCurrent: LiveService | null;
  setMessages: React.Dispatch<React.SetStateAction<MessageLog[]>>;

  attachments: Array<{
    id: string;
    name: string;
    size: number;
    kind: "image" | "pdf" | "text";
    text?: string;
  }>;
  handlePickFiles: () => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleFilesSelected: (files: FileList | null) => Promise<void>;
  composerText: string;
  setComposerText: React.Dispatch<React.SetStateAction<string>>;
  handleSendComposer: () => void;
  handleRemoveAttachment: (id: string) => void;

  isTalking: boolean;
  handleToggleTalk: () => void;
}) {
  const {
    leftFullscreen,
    setLeftFullscreen,
    state,
    statusDetailsOpen,
    setStatusDetailsOpen,
    systemCounts,
    audioStatus,
    depsStatusError,
    depsStatus,
    setDepsStatusRefreshNonce,
    handleConnect,
    logScrollRef,
    logStickToBottomRef,
    messages,
    showDebugLogs,
    setShowDebugLogs,
    expandedLogId,
    setExpandedLogId,
    uiCardInputByMsgId,
    setUiCardInputByMsgId,
    copyText,
    clientLabelForMsg,
    liveServiceCurrent,
    setMessages,
    attachments,
    handlePickFiles,
    fileInputRef,
    handleFilesSelected,
    composerText,
    setComposerText,
    handleSendComposer,
    handleRemoveAttachment,
    isTalking,
    handleToggleTalk,
  } = props;

  const [uiCardActionByMsgId, setUiCardActionByMsgId] = React.useState<
    Record<string, { busy: boolean; status: "idle" | "ok" | "error"; message?: string }>
  >({});

  return (
    <div
      className={`p-4 md:p-6 flex flex-col gap-6 bg-slate-900/80 backdrop-blur-md overflow-hidden h-[100dvh] ${
        leftFullscreen
          ? "fixed inset-0 z-50 w-screen border-0"
          : "w-full md:w-1/3 lg:w-1/4 z-10 border-r border-slate-800"
      }`}
    >
      <header>
        <h1 className="text-4xl font-bold font-hud text-cyan-400 tracking-tighter mb-1">JARVIS</h1>
        <p className="text-xs text-cyan-600 font-mono uppercase tracking-[0.2em]">Live Interface System</p>
      </header>

      <div className="flex-1 flex flex-col gap-4 min-h-0">
        {/* Connection Status */}
        <div
          className={`p-3 rounded-lg border ${
            state === ConnectionState.CONNECTED
              ? "border-cyan-500/30 bg-cyan-950/20"
              : "border-red-500/30 bg-red-950/20"
          } transition-colors duration-500`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs font-mono text-slate-400 uppercase whitespace-nowrap">System</span>
              <span
                className={`inline-flex items-center gap-2 px-2 py-1 rounded-full border text-[11px] font-mono uppercase tracking-wide ${
                  state === ConnectionState.CONNECTED
                    ? "border-cyan-500/40 bg-cyan-950/10 text-cyan-200"
                    : state === ConnectionState.CONNECTING
                      ? "border-yellow-500/40 bg-yellow-950/10 text-yellow-200"
                      : state === ConnectionState.ERROR
                        ? "border-red-500/40 bg-red-950/20 text-red-200"
                        : "border-slate-700 bg-slate-950/20 text-slate-300"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    state === ConnectionState.CONNECTED
                      ? "bg-cyan-400 animate-pulse"
                      : state === ConnectionState.CONNECTING
                        ? "bg-yellow-400 animate-pulse"
                        : state === ConnectionState.ERROR
                          ? "bg-red-400"
                          : "bg-slate-400"
                  }`}
                />
                {state === ConnectionState.CONNECTED
                  ? "Live"
                  : state === ConnectionState.CONNECTING
                    ? "Connecting"
                    : state === ConnectionState.ERROR
                      ? "Error"
                      : "Offline"}
              </span>
            </div>

            <button
              onClick={() => setStatusDetailsOpen((v) => !v)}
              className="shrink-0 ml-2 w-8 h-8 rounded-lg border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 flex items-center justify-center"
              title={statusDetailsOpen ? "Hide status details" : "Show status details"}
              aria-label={statusDetailsOpen ? "Hide status details" : "Show status details"}
            >
              <ChevronRight
                className={`w-4 h-4 text-slate-500 transition-transform ${statusDetailsOpen ? "rotate-90" : ""}`}
              />
            </button>

            {state === ConnectionState.CONNECTED ? (
              <button
                onClick={handleConnect}
                title="Disconnect"
                className="px-2 py-1.5 rounded-lg border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 text-xs font-mono"
                aria-label="Disconnect"
              >
                <Link2Off className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={handleConnect}
                disabled={state === ConnectionState.CONNECTING}
                className="px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-950/40 disabled:opacity-50"
              >
                {state === ConnectionState.CONNECTING ? "Connecting..." : "Connect"}
              </button>
            )}
          </div>

          {statusDetailsOpen && (
            <div className="mt-2 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono px-2 py-1 rounded-full border border-slate-700 bg-slate-950/20 text-slate-300">
                    mem:{systemCounts.memory}
                  </span>
                  <span className="text-[11px] font-mono px-2 py-1 rounded-full border border-slate-700 bg-slate-950/20 text-slate-300">
                    know:{systemCounts.knowledge}
                  </span>
                </div>
                <span
                  className={`inline-flex items-center gap-1 text-[11px] font-mono px-2 py-1 rounded-full border ${
                    audioStatus.ok
                      ? "border-cyan-500/30 bg-cyan-950/10 text-cyan-200"
                      : "border-slate-700 bg-slate-950/20 text-slate-300"
                  }`}
                  title={audioStatus.ok ? "audio_ok" : "audio_unavailable"}
                >
                  {audioStatus.ok ? <Mic className="w-3 h-3" /> : <MicOff className="w-3 h-3" />}
                  audio
                </span>
              </div>

              <div className="text-[11px] font-mono text-slate-400 border border-slate-800 rounded-lg bg-slate-950/20 px-2 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-slate-500 uppercase tracking-widest">deps</span>
                    <button
                      className="text-[10px] font-mono px-2 py-[2px] rounded border border-slate-800 bg-slate-950/40 text-slate-400 hover:text-slate-200 hover:bg-slate-900/40"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDepsStatusRefreshNonce((v) => (Number.isFinite(v) ? v + 1 : Date.now()));
                      }}
                      title="Refresh dependency status"
                    >
                      refresh
                    </button>
                  </div>
                  {depsStatusError ? (
                    <span className="text-red-300">error</span>
                  ) : depsStatus ? (
                    <span className="text-slate-300">ok</span>
                  ) : (
                    <span className="text-slate-500">loading…</span>
                  )}
                </div>

                {depsStatusError ? (
                  <div className="mt-1 text-red-300 break-words">{depsStatusError}</div>
                ) : Array.isArray((depsStatus as any)?.checks) ? (
                  <div className="mt-1 space-y-1">
                    {(depsStatus as any).checks.map((c: any) => {
                      const name = String(c?.name || "").trim() || "(unknown)";
                      const skipped = Boolean(c?.skipped);
                      const ok = Boolean(c?.ok);
                      const latency = c?.latency_ms;
                      const latencyTxt =
                        typeof latency === "number" && Number.isFinite(latency) ? `${Math.floor(latency)}ms` : "";
                      const icon = skipped ? (
                        <AlertTriangle className="w-3.5 h-3.5 text-slate-500" />
                      ) : ok ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5 text-red-400" />
                      );
                      return (
                        <div key={name} className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            {icon}
                            <span className="text-slate-300 break-words">{name}</span>
                          </div>
                          <div className="shrink-0 text-slate-500">{latencyTxt}</div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </div>

        {/* Activity Log */}
        <div
          ref={logScrollRef}
          className="flex-1 overflow-y-auto pr-2 space-y-3 mask-image-b pb-40 md:pb-0"
          onScroll={(e) => {
            const el = e.currentTarget;
            const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
            logStickToBottomRef.current = remaining < 40;
          }}
        >
          <div className="text-xs font-mono text-slate-500 uppercase tracking-widest sticky top-0 bg-slate-900/90 py-1 mb-2 flex items-center justify-between gap-2">
            <span>Operation Log</span>
            <div className="flex flex-wrap items-center justify-end gap-2 shrink-0">
              <button
                className="text-[10px] font-mono text-slate-600 hover:text-slate-400 normal-case whitespace-nowrap"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const visible = showDebugLogs
                    ? messages
                    : messages.filter((m) => (m.metadata?.severity || "info") !== "debug");
                  const ordered = visible
                    .slice()
                    .sort((a, b) => {
                      const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
                      const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
                      if (ta !== tb) return ta - tb;
                      return String(a.id || "").localeCompare(String(b.id || ""));
                    });
                  const lines = ordered
                    .map((m) => {
                      const ts = m.timestamp.toLocaleTimeString();
                      const label = clientLabelForMsg(m);
                      const tagText = label ? `[${label}] ` : "";
                      const role = String(m.role || "");
                      const txt = String(m.text || "");
                      return `[${ts}] ${tagText}${role}: ${txt}`;
                    })
                    .join("\n");
                  void copyText(lines);
                }}
                title="Copy all visible logs"
                aria-label="Copy all visible logs"
              >
                copy all
              </button>
              <button
                className="text-[10px] font-mono text-slate-600 hover:text-slate-400 normal-case whitespace-nowrap"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowDebugLogs((v) => !v);
                }}
              >
                {showDebugLogs ? "hide debug" : "show debug"}
              </button>
              <button
                className="w-7 h-7 rounded-lg border border-slate-800 bg-slate-950/30 text-slate-400 hover:text-slate-200 hover:bg-slate-800/40 flex items-center justify-center"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setLeftFullscreen((v) => !v);
                }}
                title={leftFullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
                aria-label={leftFullscreen ? "Exit fullscreen" : "Fullscreen"}
              >
                {leftFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
              </button>
            </div>
          </div>
          {messages.length === 0 && <div className="text-sm text-slate-600 italic mt-10 text-center">Awaiting inputs...</div>}
          {(() => {
            const visible = showDebugLogs
              ? messages
              : messages.filter((m) => (m.metadata?.severity || "info") !== "debug");
            const ordered = visible
              .slice()
              .sort((a, b) => {
                const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
                const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
                if (ta !== tb) return ta - tb;
                return String(a.id || "").localeCompare(String(b.id || ""));
              });

            const toolCallsByTraceId = new Set<string>();
            const toolResultsByTraceId = new Map<string, MessageLog>();
            for (const m of ordered) {
              const tr = m.metadata?.trace_id ? String(m.metadata.trace_id) : "";
              if (!tr) continue;
              const kind = String((m.metadata as any)?.kind || "").trim();
              if (kind === "tool_call") toolCallsByTraceId.add(tr);
              if (kind === "tool_result") toolResultsByTraceId.set(tr, m);
            }
            const seenKeys = new Set<string>();
            const dedupeKeyForRender = (t: string): string | null => {
              const s = String(t || "")
                .trim()
                .toLowerCase()
                .replace(/\s+/g, " ");
              if (!s) return null;
              if (s.includes("sheets are not auto-loaded")) return "sheets_not_auto_loaded";
              if (s.startsWith("reload system: start") || s.startsWith("reload system: ok") || s.startsWith("reload system สำเร็จ"))
                return "reload_system";
              if (s.includes("โหลด memory") && s.includes("knowledge")) return "loaded_memory_th";
              if (s.includes("loaded memory") && s.includes("knowledge")) return "loaded_memory_en";
              if (s.startsWith("อา.") || /^\d{4}-\d{2}-\d{2}\b/.test(s)) return "time_injection";
              return null;
            };
            const filtered = ordered.filter((m) => {
              const kind = String((m.metadata as any)?.kind || "").trim();
              if (kind === "tool_result") {
                const tr = m.metadata?.trace_id ? String(m.metadata.trace_id) : "";
                if (tr && toolCallsByTraceId.has(tr)) return false;
              }
              const k = dedupeKeyForRender(String(m.text || ""));
              if (!k) return true;
              if (seenKeys.has(k)) return false;
              seenKeys.add(k);
              return true;
            });
            const coalesced: MessageLog[] = [];
            for (const m of filtered) {
              const prev = coalesced.length ? coalesced[coalesced.length - 1] : null;
              const role = String((m as any)?.role || "");
              const prevRole = prev ? String((prev as any)?.role || "") : "";
              const ts = m.timestamp?.getTime?.() ? m.timestamp.getTime() : 0;
              const prevTs = prev && prev.timestamp?.getTime?.() ? prev.timestamp.getTime() : 0;
              const gap = prev ? ts - prevTs : Number.POSITIVE_INFINITY;
              const txt = String(m.text || "").trim();
              const prevTxt = prev ? String(prev.text || "").trim() : "";
              const tr = m.metadata?.trace_id ? String(m.metadata.trace_id) : "";
              const prevTr = prev?.metadata?.trace_id ? String(prev.metadata.trace_id) : "";
              const kind = String((m.metadata as any)?.kind || "").trim();
              const prevKind = String((prev?.metadata as any)?.kind || "").trim();
              const uiRaw: any = (m.metadata?.raw as any) ?? (m.metadata?.ws as any) ?? null;
              const prevUiRaw: any = (prev?.metadata?.raw as any) ?? (prev?.metadata?.ws as any) ?? null;
              const isUiCard = String(uiRaw?.type || "").toLowerCase() === "ui";
              const prevIsUiCard = String(prevUiRaw?.type || "").toLowerCase() === "ui";

              const mergeable =
                role === "user" &&
                prev &&
                prevRole === "user" &&
                gap >= 0 &&
                gap <= 2500 &&
                txt &&
                prevTxt &&
                txt.length <= 80 &&
                prevTxt.length <= 200;

              if (mergeable) {
                const mergedText = `${prevTxt} ${txt}`.replace(/\s+/g, " ").trim();
                coalesced[coalesced.length - 1] = {
                  ...(prev as any),
                  text: mergedText,
                } as MessageLog;
                continue;
              }

              const mergeableTraceGroup =
                Boolean(tr) &&
                prev &&
                Boolean(prevTr) &&
                tr === prevTr &&
                gap >= 0 &&
                gap <= 2500 &&
                role === prevRole &&
                (role === "model" || role === "system") &&
                !isUiCard &&
                !prevIsUiCard &&
                kind !== "tool_call" &&
                kind !== "tool_result" &&
                prevKind !== "tool_call" &&
                prevKind !== "tool_result" &&
                txt &&
                prevTxt &&
                txt.length <= 200 &&
                prevTxt.length <= 600;

              if (mergeableTraceGroup) {
                const mergedText = `${prevTxt}\n${txt}`.trim();
                coalesced[coalesced.length - 1] = {
                  ...(prev as any),
                  text: mergedText,
                } as MessageLog;
                continue;
              }

              coalesced.push(m);
            }

            return coalesced.map((m) => {
              const uiRaw: any = (m.metadata?.raw as any) ?? (m.metadata?.ws as any) ?? null;
              const isUiCard = String(uiRaw?.type || "").toLowerCase() === "ui";
              const toolKind = String((m.metadata as any)?.kind || "").trim();
              const isToolCall = toolKind === "tool_call";
              const tr = m.metadata?.trace_id ? String(m.metadata.trace_id) : "";
              const toolResult = isToolCall && tr ? toolResultsByTraceId.get(tr) : undefined;
              const toolResultRaw: any = toolResult?.metadata?.raw ?? null;
              const toolResultOk = toolResultRaw && typeof toolResultRaw === "object" ? toolResultRaw.ok === true : null;
              const toolResultSummary = toolResultOk == null ? "" : toolResultOk ? "ok" : "error";
              const canExpand = Boolean(m.metadata?.raw || m.metadata?.trace_id || m.metadata?.ws?.type || m.metadata?.ws?.instance_id);
              const expanded = expandedLogId === m.id;
              let rawText = "";
              if (expanded && m.metadata?.raw != null) {
                try {
                  const rawAny: any = m.metadata.raw;
                  if (rawAny && typeof rawAny === "object" && !Array.isArray(rawAny)) {
                    const copy: any = { ...rawAny };
                    delete copy.client_id;
                    delete copy.client_tag;
                    rawText = JSON.stringify(copy, null, 2);
                  } else {
                    rawText = JSON.stringify(rawAny, null, 2);
                  }
                } catch {
                  rawText = String(m.metadata.raw);
                }
              }
              const traceLine = m.metadata?.trace_id ? `trace_id=${String(m.metadata.trace_id)}` : "";
              const typeLine = m.metadata?.ws?.type ? `type=${String(m.metadata.ws.type)}` : "";
              const instLine = m.metadata?.ws?.instance_id ? `instance_id=${String(m.metadata.ws.instance_id)}` : "";
              const metaLine = [typeLine, instLine, traceLine].filter(Boolean).join(" ");

              const renderUiCard = () => {
                const kind = String(uiRaw?.kind || "ui");
                const title = uiRaw?.title != null ? String(uiRaw.title) : "";
                const body = uiRaw?.body != null ? String(uiRaw.body) : "";
                const risk = uiRaw?.risk != null ? String(uiRaw.risk) : "";
                const confirmationId = uiRaw?.confirmation_id != null ? String(uiRaw.confirmation_id) : "";
                const primary = uiRaw?.primary && typeof uiRaw.primary === "object" ? uiRaw.primary : null;
                const secondary = uiRaw?.secondary && typeof uiRaw.secondary === "object" ? uiRaw.secondary : null;
                const tertiary = uiRaw?.tertiary && typeof uiRaw.tertiary === "object" ? uiRaw.tertiary : null;
                const input = uiRaw?.input && typeof uiRaw.input === "object" ? uiRaw.input : null;
                const inputName = input?.name != null ? String(input.name) : "";
                const inputLabel = input?.label != null ? String(input.label) : "";
                const inputPlaceholder = input?.placeholder != null ? String(input.placeholder) : "";
                const inputValue = uiCardInputByMsgId[m.id] ?? "";

                const actionState = uiCardActionByMsgId[m.id] || { busy: false, status: "idle" as const };

                const riskClass =
                  risk === "high" ? "border-red-500/40" : risk === "medium" ? "border-yellow-500/40" : "border-cyan-500/30";
                const badgeClass =
                  risk === "high"
                    ? "text-red-300 bg-red-950/30 border-red-500/30"
                    : risk === "medium"
                      ? "text-yellow-300 bg-yellow-950/30 border-yellow-500/30"
                      : "text-cyan-200 bg-cyan-950/30 border-cyan-500/30";

                const invokeUiTool = async (tool: string, extraArgs?: any) => {
                  const toolName = String(tool || "").trim();
                  if (!toolName) return;
                  setUiCardActionByMsgId((prev) => ({ ...prev, [m.id]: { busy: true, status: "idle" } }));
                  const okPrefix =
                    toolName.startsWith("system_") ||
                    toolName.startsWith("pending_") ||
                    toolName.startsWith("macro_") ||
                    toolName.startsWith("news_") ||
                    toolName.startsWith("gnews_") ||
                    toolName.startsWith("current_news_") ||
                    toolName.startsWith("reminders_") ||
                    toolName.startsWith("gems_") ||
                    toolName === "time_now";
                  if (!okPrefix) {
                    setUiCardActionByMsgId((prev) => ({
                      ...prev,
                      [m.id]: { busy: false, status: "error", message: `tool_not_allowed: ${toolName}` },
                    }));
                    return;
                  }
                  const args: any = extraArgs && typeof extraArgs === "object" ? { ...extraArgs } : {};
                  if (confirmationId && (toolName === "pending_confirm" || toolName === "pending_cancel" || toolName === "pending_preview" || toolName === "pending_get")) {
                    if (args.confirmation_id == null) args.confirmation_id = confirmationId;
                  }
                  if (toolName === "pending_confirm" && confirmationId && inputName) {
                    const v = String(inputValue || "").trim();
                    if (v) args.input = { ...(args.input && typeof args.input === "object" ? args.input : {}), [inputName]: v };
                  }

                  try {
                    await liveServiceCurrent?.invokeTool(toolName, args);
                    setUiCardActionByMsgId((prev) => ({
                      ...prev,
                      [m.id]: { busy: false, status: "ok", message: `ok: ${toolName}` },
                    }));
                  } catch (e: any) {
                    setUiCardActionByMsgId((prev) => ({
                      ...prev,
                      [m.id]: { busy: false, status: "error", message: String(e?.message || e || "error") },
                    }));
                  }
                };

                return (
                  <div
                    className={`pl-5 border-l ${riskClass} py-2 rounded-md bg-slate-950/30`}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-mono text-slate-400">{kind}</span>
                          {risk ? <span className={`text-[10px] font-mono px-2 py-[2px] rounded border ${badgeClass}`}>{risk}</span> : null}
                        </div>
                        {title ? <div className="text-slate-100 font-mono text-sm mt-1">{title}</div> : null}
                      </div>
                      {confirmationId ? <span className="text-[10px] font-mono text-slate-500 shrink-0">{confirmationId}</span> : null}
                    </div>
                    {body ? <div className="mt-2 text-slate-300 whitespace-pre-wrap text-sm">{body}</div> : null}
                    {inputName ? (
                      <div className="mt-3">
                        {inputLabel ? <div className="text-[11px] font-mono text-slate-400 mb-1">{inputLabel}</div> : null}
                        <input
                          value={inputValue}
                          onChange={(e) => setUiCardInputByMsgId((prev) => ({ ...prev, [m.id]: e.target.value }))}
                          placeholder={inputPlaceholder}
                          className="w-full px-3 py-2 rounded-lg text-sm font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600"
                        />
                      </div>
                    ) : null}
                    <div className="mt-3 flex items-center gap-2">
                      {tertiary?.label && tertiary?.tool ? (
                        <button
                          disabled={actionState.busy}
                          className={`px-3 py-2 rounded-lg border border-slate-700 bg-slate-950/40 text-slate-200 text-xs font-mono ${
                            actionState.busy ? "opacity-50 cursor-not-allowed" : "hover:bg-slate-800/60"
                          }`}
                          onClick={() => void invokeUiTool(String(tertiary.tool), tertiary.args)}
                        >
                          {String(tertiary.label)}
                        </button>
                      ) : null}
                      {secondary?.label && secondary?.tool ? (
                        <button
                          disabled={actionState.busy}
                          className={`px-3 py-2 rounded-lg border border-slate-700 bg-slate-950/40 text-slate-200 text-xs font-mono ${
                            actionState.busy ? "opacity-50 cursor-not-allowed" : "hover:bg-slate-800/60"
                          }`}
                          onClick={() => void invokeUiTool(String(secondary.tool), secondary.args)}
                        >
                          {String(secondary.label)}
                        </button>
                      ) : null}
                      {primary?.label && primary?.tool ? (
                        <button
                          disabled={actionState.busy}
                          className={`px-3 py-2 rounded-lg border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 text-xs font-mono ${
                            actionState.busy ? "opacity-50 cursor-not-allowed" : "hover:bg-cyan-950/40"
                          }`}
                          onClick={() => void invokeUiTool(String(primary.tool), primary.args)}
                        >
                          {String(primary.label)}
                        </button>
                      ) : null}
                    </div>

                    {actionState.busy || actionState.status !== "idle" ? (
                      <div
                        className={`mt-2 text-[11px] font-mono ${
                          actionState.busy
                            ? "text-slate-500"
                            : actionState.status === "ok"
                              ? "text-emerald-300"
                              : "text-amber-300"
                        }`}
                      >
                        {actionState.busy ? "working…" : actionState.message || (actionState.status === "ok" ? "ok" : "error")}
                      </div>
                    ) : null}
                  </div>
                );
              };

              return (
                <div
                  key={m.id}
                  className={`text-sm group animate-in fade-in slide-in-from-left-2 duration-300 ${canExpand ? "cursor-pointer" : ""}`}
                  onClick={() => {
                    if (!canExpand) return;
                    setExpandedLogId((prev) => (prev === m.id ? null : m.id));
                  }}
                >
                  <div className="flex items-center gap-2 mb-1">
                    {m.role === "model" && <Activity className="w-3 h-3 text-cyan-400" />}
                    {m.metadata?.type === "search" && <Search className="w-3 h-3 text-yellow-400" />}
                    {m.metadata?.type === "image_gen" && <ImageIcon className="w-3 h-3 text-purple-400" />}
                    {m.metadata?.type === "reimagine" && <Camera className="w-3 h-3 text-pink-400" />}
                    <span className="text-xs text-slate-500 font-mono">{m.timestamp.toLocaleTimeString()}</span>
                    {clientLabelForMsg(m) && <span className="text-[10px] text-slate-600 font-mono">[{clientLabelForMsg(m)}]</span>}
                    <button
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-slate-300"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const ts = m.timestamp.toLocaleTimeString();
                        const label = clientLabelForMsg(m);
                        const tagText = label ? `[${label}] ` : "";
                        const role = String(m.role || "");
                        const txt = String(m.text || "");
                        const forceText = (e as any)?.shiftKey === true;
                        const rawAny: any = (m.metadata as any)?.raw;
                        const traceId = m.metadata?.trace_id ? String(m.metadata.trace_id) : "";
                        if (!forceText && traceId) {
                          try {
                            const grouped = messages
                              .filter((mm) => (mm.metadata?.trace_id ? String(mm.metadata.trace_id) : "") === traceId)
                              .slice()
                              .sort((a, b) => {
                                const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
                                const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
                                if (ta !== tb) return ta - tb;
                                return String(a.id || "").localeCompare(String(b.id || ""));
                              });
                            if (grouped.length > 1) {
                              const parts = grouped.map((mm) => {
                                const mts = mm.timestamp.toLocaleTimeString();
                                const mlabel = clientLabelForMsg(mm);
                                const mtagText = mlabel ? `[${mlabel}] ` : "";
                                const mrole = String(mm.role || "");
                                const mtxt = String(mm.text || "");
                                const mraw: any = (mm.metadata as any)?.raw;
                                if (mraw != null) {
                                  try {
                                    if (mraw && typeof mraw === "object" && !Array.isArray(mraw)) {
                                      const copy: any = { ...mraw };
                                      delete copy.client_id;
                                      delete copy.client_tag;
                                      return JSON.stringify(copy, null, 2);
                                    }
                                    return JSON.stringify(mraw, null, 2);
                                  } catch {
                                    return String(mraw);
                                  }
                                }
                                return `[${mts}] ${mtagText}${mrole}: ${mtxt}`;
                              });
                              void copyText(parts.join("\n\n"));
                              return;
                            }
                          } catch {
                            // ignore
                          }
                        }
                        if (!forceText && rawAny != null) {
                          try {
                            if (rawAny && typeof rawAny === "object" && !Array.isArray(rawAny)) {
                              const copy: any = { ...rawAny };
                              delete copy.client_id;
                              delete copy.client_tag;
                              void copyText(JSON.stringify(copy, null, 2));
                              return;
                            }
                            void copyText(JSON.stringify(rawAny, null, 2));
                            return;
                          } catch {
                          }
                        }
                        void copyText(`[${ts}] ${tagText}${role}: ${txt}`);
                      }}
                      title="Copy (JSON if available; Shift+Click to copy text)"
                      aria-label="Copy"
                    >
                      <Copy className="w-3 h-3" />
                    </button>
                    {canExpand && <span className="text-[10px] text-slate-600 font-mono">{expanded ? "hide" : "details"}</span>}
                  </div>
                  <div className="text-slate-300 pl-5 border-l border-slate-700 py-1 whitespace-pre-wrap">
                    {isUiCard ? renderUiCard() : m.text}
                    {isToolCall && toolResultSummary ? (
                      <div className={`mt-1 text-[11px] font-mono ${toolResultOk ? "text-emerald-300" : "text-amber-300"}`}>
                        {`result: ${toolResultSummary}`}
                      </div>
                    ) : null}
                    {expanded && metaLine && <div className="mt-2 text-[11px] font-mono text-slate-500 whitespace-pre-wrap">{metaLine}</div>}
                    {expanded && rawText && <pre className="mt-2 text-[11px] font-mono text-slate-400 whitespace-pre-wrap">{rawText}</pre>}
                    {expanded && isToolCall && toolResultRaw != null ? (
                      <pre className="mt-2 text-[11px] font-mono text-slate-400 whitespace-pre-wrap">
                        {(() => {
                          try {
                            return JSON.stringify(toolResultRaw, null, 2);
                          } catch {
                            return String(toolResultRaw);
                          }
                        })()}
                      </pre>
                    ) : null}
                  </div>
                </div>
              );
            });
          })()}
        </div>
      </div>

      <div className="shrink-0 mt-auto -mx-4 md:-mx-6 px-4 md:px-6 pt-4 pb-4 bg-slate-900/95 backdrop-blur-md border-t border-slate-800">
        <div className="mb-3">
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {attachments.map((a) => (
                <div key={a.id} className="flex items-center gap-2 px-2 py-1 rounded-md bg-slate-950/40 border border-slate-800">
                  <span className="text-[11px] font-mono text-slate-200 max-w-[220px] truncate">{a.name}</span>
                  <button
                    onClick={() => handleRemoveAttachment(a.id)}
                    className="text-slate-400 hover:text-slate-200"
                    disabled={state !== ConnectionState.CONNECTED}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={handlePickFiles}
              disabled={state !== ConnectionState.CONNECTED}
              className="shrink-0 w-10 h-10 rounded-xl border border-slate-700 bg-slate-950/40 text-slate-200 hover:bg-slate-800/60 disabled:opacity-50"
              aria-label="Attach files"
            >
              <Paperclip className="w-4 h-4" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              accept="image/*,application/pdf,text/plain,text/markdown,application/json,.md,.txt,.json,.pdf"
              onChange={(e) => {
                void handleFilesSelected(e.target.files);
                e.currentTarget.value = "";
              }}
            />
            <input
              value={composerText}
              onChange={(e) => setComposerText(e.target.value)}
              placeholder="Type a message..."
              disabled={state !== ConnectionState.CONNECTED}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendComposer();
                }
              }}
              className="flex-1 min-w-0 px-3 py-2 rounded-xl text-sm font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600 disabled:opacity-50"
            />
            <button
              onClick={handleSendComposer}
              disabled={state !== ConnectionState.CONNECTED}
              className="shrink-0 w-10 h-10 rounded-xl border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-950/40 disabled:opacity-50 disabled:hover:bg-cyan-950/20 flex items-center justify-center"
              aria-label="Send"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>

        <button
          onClick={handleToggleTalk}
          disabled={state !== ConnectionState.CONNECTED}
          className={`
              w-full py-3 mt-3 rounded-xl font-hud text-sm tracking-widest uppercase transition-all duration-300 shadow-lg
              flex items-center justify-center gap-3
              ${state !== ConnectionState.CONNECTED
                ? "bg-slate-800/50 text-slate-500 border border-slate-700 cursor-not-allowed"
                : isTalking
                  ? "bg-yellow-500/10 text-yellow-300 border border-yellow-500/50 hover:bg-yellow-500/20 shadow-yellow-500/20"
                  : "bg-slate-900/50 text-cyan-200 border border-cyan-500/30 hover:bg-slate-900/70 shadow-cyan-500/10"}
            `}
        >
          {isTalking ? (
            <>
              <MicOff className="w-4 h-4" /> Stop
            </>
          ) : (
            <>
              <Mic className="w-4 h-4" /> Talk
            </>
          )}
        </button>
      </div>
    </div>
  );
}
