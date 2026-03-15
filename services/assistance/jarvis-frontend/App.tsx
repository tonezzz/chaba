import React, { useState, useEffect, useRef, useCallback } from 'react';
import { LiveService } from './services/liveService';
import { sequentialApplyAndSuggest } from './services/sequentialService';
import { ConnectionState, MessageLog } from './types';
import Visualizer from './components/Visualizer';
import CameraFeed from './components/CameraFeed';
import CarsPanel from './components/CarsPanel';
import { Play, Mic, MicOff, Search, Image as ImageIcon, Camera, Activity, Lock, ChevronRight, Paperclip, Send, X, Link2Off, Copy } from 'lucide-react';

export default function App() {
  const [hasKey, setHasKey] = useState(false);
  const [state, setState] = useState<ConnectionState>(ConnectionState.DISCONNECTED);
  const [volume, setVolume] = useState(0);
  const [messages, setMessages] = useState<MessageLog[]>([]);
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [showDebugLogs, setShowDebugLogs] = useState(false);
  const liveService = useRef<LiveService | null>(null);
  const [activeMedia, setActiveMedia] = useState<MessageLog | null>(null);
  const [isTalking, setIsTalking] = useState(false);
  const [activeRightPanel, setActiveRightPanel] = useState<"output" | "cars" | "checklist">("output");
  const [activeTripId, setActiveTripId] = useState<string>("");
  const [activeTripName, setActiveTripName] = useState<string>("");
  const [tripIdInput, setTripIdInput] = useState<string>("");
  const [tripNameInput, setTripNameInput] = useState<string>("");
  const [composerText, setComposerText] = useState<string>("");
  const [seqNotes, setSeqNotes] = useState<string>("");
  const [seqCompletedNotes, setSeqCompletedNotes] = useState<string>("");
  const [seqNextText, setSeqNextText] = useState<string | null>(null);
  const [seqNextIndex, setSeqNextIndex] = useState<number | null>(null);
  const [seqTemplate, setSeqTemplate] = useState<string[] | null>(null);
  const [seqError, setSeqError] = useState<string>("");
  const [seqBusy, setSeqBusy] = useState<boolean>(false);
  const [attachments, setAttachments] = useState<
    Array<{
      id: string;
      name: string;
      size: number;
      kind: "image" | "pdf" | "text";
      text?: string;
    }>
  >([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const copyText = useCallback(async (text: string) => {
    const t = String(text || "");
    if (!t) return;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(t);
        return;
      }
    } catch {
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = t;
      ta.setAttribute("readonly", "true");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      ta.style.left = "-9999px";
      ta.style.top = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch {
    }
  }, []);

  useEffect(() => {
    const checkKey = async () => {
      if ((window as any).aistudio && await (window as any).aistudio.hasSelectedApiKey()) {
        setHasKey(true);
      }
    };
    checkKey();
  }, []);

  useEffect(() => {
    if (!hasKey) return;

    liveService.current = new LiveService();
    liveService.current.onStateChange = setState;
    liveService.current.onVolume = setVolume;
    liveService.current.onActiveTrip = (trip) => {
      setActiveTripId(trip.active_trip_id || "");
      setActiveTripName(trip.active_trip_name || "");
    };
    liveService.current.onCarsIngestResult = (ev) => {
      setMessages((prev) => [
        {
          id: `${Date.now()}_cars_ingest`,
          role: "system",
          text: `cars_ingest_result ok=${String((ev as any)?.ok)} items=${Array.isArray((ev as any)?.items) ? (ev as any).items.length : 0}`,
          timestamp: new Date(),
        },
        ...prev,
      ]);
      setActiveRightPanel("cars");
    };
    liveService.current.onMessage = (msg) => {
      setMessages((prev) => {
        if (msg.id === "sticky_progress") {
          const without = prev.filter((m) => m.id !== "sticky_progress");
          const txt = String(msg.text || "").trim();
          if (!txt) {
            return without;
          }
          return [msg, ...without];
        }

        const dedupeKeyForStatusText = (t: string): string | null => {
          const s = String(t || "").trim().toLowerCase();
          if (!s) return null;
          if (s.includes("sheets are not auto-loaded")) return "sheets_not_auto_loaded";
          if (s.startsWith("reload system: ok") || s.startsWith("reload system สำเร็จ")) return "reload_system_ok";
          if (s.includes("โหลด memory") && s.includes("knowledge")) return "loaded_memory_th";
          if (s.includes("loaded memory") && s.includes("knowledge")) return "loaded_memory_en";
          return null;
        };

        const isErr = msg.id.endsWith('_err') || msg.id.includes('_attach_err_');
        const isConnectedState = msg.id.endsWith('_state') && String(msg.text || '').toLowerCase() === 'connected';
        const shouldClearStickyErrors = isConnectedState || (!isErr && prev.length > 0);

        const cleanedPrev = shouldClearStickyErrors
          ? prev.filter((m) => {
              const isPrevErr = m.id.endsWith('_err');
              const txt = String(m.text || '').toLowerCase();
              if (!isPrevErr) return true;
              // Clear stale live-model errors once we've reconnected or received normal traffic.
              if (txt.includes('gemini_live_model_not_found') || txt.includes('gemini_live_model_not_found'.replace(/_/g, ' '))) {
                return false;
              }
              if (txt === 'gemini_live_model_not_found') return false;
              return true;
            })
          : prev;

        const msgTextNorm = String(msg.text || "").trim().replace(/\s+/g, " ");
        const shouldDedupeSystemExact = !isErr && msg.role === "system" && msgTextNorm.length > 0;
        const msgKey = !isErr && msgTextNorm.length > 0 ? dedupeKeyForStatusText(msgTextNorm) : null;
        const dedupedPrev = (shouldDedupeSystemExact || !!msgKey)
          ? cleanedPrev.filter((m) => {
              const t = String(m.text || "").trim().replace(/\s+/g, " ");
              if (!t) return true;
              if (shouldDedupeSystemExact) {
                if (m.role === "system" && t === msgTextNorm) return false;
              }
              if (msgKey) {
                const k2 = dedupeKeyForStatusText(t);
                if (k2 && k2 === msgKey) return false;
              }
              return true;
            })
          : cleanedPrev;

        const isTranscript = msg.id.endsWith('_tr');
        if (!isTranscript || dedupedPrev.length === 0) {
          return [msg, ...dedupedPrev];
        }

        const head = dedupedPrev[0];
        const headIsTranscript = head.id.endsWith('_tr');
        const sameSource = (head.metadata?.source || 'input') === (msg.metadata?.source || 'input');
        const closeInTime = Math.abs(msg.timestamp.getTime() - head.timestamp.getTime()) < 5000;

        if (headIsTranscript && sameSource && closeInTime) {
          const prevText = String(head.text || '');
          const nextText = String(msg.text || '');
          const merged = prevText.endsWith(nextText) ? prevText : `${prevText} ${nextText}`.trim();
          return [{ ...head, text: merged, timestamp: msg.timestamp }, ...dedupedPrev.slice(1)];
        }

        return [msg, ...dedupedPrev];
      });
      if (msg.metadata) {
        setActiveMedia(msg);
      }
    };

    return () => {
      liveService.current?.disconnect();
    };
  }, [hasKey]);

  useEffect(() => {
    if (state !== ConnectionState.CONNECTED && isTalking) {
      setIsTalking(false);
    }
  }, [state, isTalking]);

  const handleConnect = () => {
    if (state === ConnectionState.DISCONNECTED || state === ConnectionState.ERROR) {
      liveService.current?.connect();
    } else {
      liveService.current?.stopStreaming();
      setIsTalking(false);
      liveService.current?.disconnect();
    }
  };

  const handleRefreshTrip = () => {
    liveService.current?.requestActiveTrip();
  };

  const handleSetTrip = () => {
    const id = tripIdInput.trim();
    const name = tripNameInput.trim();
    liveService.current?.setActiveTrip(id || null, name || null);
  };

  const handlePickFiles = () => {
    if (state !== ConnectionState.CONNECTED) return;
    fileInputRef.current?.click();
  };

  const handleFilesSelected = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const next: Array<{
      id: string;
      name: string;
      size: number;
      kind: "image" | "pdf" | "text";
      text?: string;
    }> = [];
    for (const f of Array.from(files)) {
      const name = String(f.name || "file");
      const size = Number(f.size || 0);
      const type = String(f.type || "");
      const isPdf = type === "application/pdf" || name.toLowerCase().endsWith(".pdf");
      const isImage = type.startsWith("image/");
      const isText = type.startsWith("text/") || name.toLowerCase().endsWith(".md") || name.toLowerCase().endsWith(".json");
      if (!isPdf && !isImage && !isText) {
        setMessages((prev) => [
          {
            id: `${Date.now()}_attach_err_${Math.random().toString(16).slice(2)}`,
            role: "system",
            text: `unsupported_file_type: ${name}`,
            timestamp: new Date(),
          },
          ...prev,
        ]);
        continue;
      }
      if (isImage && size > 5 * 1024 * 1024) {
        setMessages((prev) => [
          {
            id: `${Date.now()}_attach_err_${Math.random().toString(16).slice(2)}`,
            role: "system",
            text: `image_too_large(5MB): ${name}`,
            timestamp: new Date(),
          },
          ...prev,
        ]);
        continue;
      }
      if (isPdf && size > 10 * 1024 * 1024) {
        setMessages((prev) => [
          {
            id: `${Date.now()}_attach_err_${Math.random().toString(16).slice(2)}`,
            role: "system",
            text: `pdf_too_large(10MB): ${name}`,
            timestamp: new Date(),
          },
          ...prev,
        ]);
        continue;
      }
      let text: string | undefined = undefined;
      let kind: "image" | "pdf" | "text" = isPdf ? "pdf" : isImage ? "image" : "text";
      if (kind === "text") {
        try {
          text = await f.text();
        } catch {
          text = "";
        }
      }
      next.push({
        id: `${Date.now()}_${Math.random().toString(16).slice(2)}`,
        name,
        size,
        kind,
        text,
      });
    }
    if (next.length) setAttachments((prev) => [...next, ...prev]);
  };

  const handleRemoveAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const handleSendComposer = () => {
    if (state !== ConnectionState.CONNECTED) return;
    const base = composerText.trim();
    const textAttachments = attachments.filter((a) => a.kind === "text" && typeof a.text === "string");
    const pendingAttachments = attachments.filter((a) => a.kind !== "text");
    const blocks: string[] = [];
    if (base) blocks.push(base);
    for (const a of textAttachments) {
      const body = String(a.text || "");
      blocks.push(`Attached file: ${a.name}\n\n\`\`\`\n${body}\n\`\`\``);
    }
    if (pendingAttachments.length) {
      const summary = pendingAttachments
        .map((a) => `${a.name} (${a.kind}, ${Math.round(a.size / 1024)}KB)`)
        .join(", ");
      blocks.push(`Attachments pending (not extracted yet): ${summary}`);
    }
    const finalText = blocks.join("\n\n").trim();
    if (!finalText) return;
    const traceId = liveService.current?.sendText(finalText) || undefined;
    setComposerText("");
    setAttachments([]);
    setMessages((prev) => [
      {
        id: `${Date.now()}_user_text`,
        role: "user",
        text: base || "(sent attachments)",
        timestamp: new Date(),
        metadata: {
          trace_id: traceId,
          ws: { type: "text" },
          raw: { type: "text", text: finalText, trace_id: traceId },
        },
      },
      ...prev,
    ]);
  };

  const handleToggleTalk = () => {
    if (state !== ConnectionState.CONNECTED) return;
    if (!isTalking) {
      liveService.current?.startStreaming();
      setIsTalking(true);
    } else {
      liveService.current?.stopStreaming();
      setIsTalking(false);
    }
  };

  const handleFrame = useCallback((base64: string) => {
    liveService.current?.updateCameraFrame(base64);
  }, []);

  const handleSelectKey = async () => {
    if ((window as any).aistudio) {
      try {
        await (window as any).aistudio.openSelectKey();
      } catch (e) {
        console.error("Key selection failed", e);
      }
    }
    setHasKey(true);
  };

  const getSeqCompletedTasks = () => {
    const completedBlocks = String(seqCompletedNotes || "")
      .split(/\n\s*---\s*\n/g)
      .map((b) => b.trim())
      .filter(Boolean);
    return completedBlocks.length ? completedBlocks.map((notes) => ({ notes })) : undefined;
  };

  const applySeqResponse = (res: any) => {
    setSeqNotes(res.notes);
    setSeqNextText(res.next_step_text);
    setSeqNextIndex(res.next_step_index);
    setSeqTemplate(res.template);
  };

  const handleSeqSuggest = async () => {
    setSeqBusy(true);
    setSeqError("");
    try {
      const completed_tasks = getSeqCompletedTasks();
      const res = await sequentialApplyAndSuggest({ mode: "suggest", notes: seqNotes, completed_tasks });
      applySeqResponse(res);
    } catch (e: any) {
      setSeqError(String(e?.message || e || "suggest_failed"));
      setSeqNextText(null);
      setSeqNextIndex(null);
      setSeqTemplate(null);
    } finally {
      setSeqBusy(false);
    }
  };

  const handleSeqApply = async () => {
    if (seqNextIndex == null) return;
    setSeqBusy(true);
    setSeqError("");
    try {
      const completed_tasks = getSeqCompletedTasks();

      const res = await sequentialApplyAndSuggest({
        mode: "index",
        notes: seqNotes,
        step_index: seqNextIndex,
        completed_tasks,
      });
      applySeqResponse(res);
    } catch (e: any) {
      setSeqError(String(e?.message || e || "apply_failed"));
    } finally {
      setSeqBusy(false);
    }
  };

  const handleSeqApplyByText = async () => {
    const stepText = String(seqNextText || "").trim();
    if (!stepText) return;
    setSeqBusy(true);
    setSeqError("");
    try {
      const completed_tasks = getSeqCompletedTasks();

      const res = await sequentialApplyAndSuggest({
        mode: "text",
        notes: seqNotes,
        step_text: stepText,
        completed_tasks,
      });
      applySeqResponse(res);
    } catch (e: any) {
      setSeqError(String(e?.message || e || "apply_by_text_failed"));
    } finally {
      setSeqBusy(false);
    }
  };

  const handleSeqApplyAll = async () => {
    setSeqBusy(true);
    setSeqError("");
    try {
      const completed_tasks = getSeqCompletedTasks();
      const res = await sequentialApplyAndSuggest({ mode: "all", notes: seqNotes, completed_tasks });
      applySeqResponse(res);
    } catch (e: any) {
      setSeqError(String(e?.message || e || "apply_all_failed"));
    } finally {
      setSeqBusy(false);
    }
  };

  if (!hasKey) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 z-0 opacity-20" 
             style={{ 
               backgroundImage: 'linear-gradient(rgba(14, 165, 233, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(14, 165, 233, 0.1) 1px, transparent 1px)', 
               backgroundSize: '40px 40px' 
             }}>
        </div>
        
        <div className="z-10 bg-slate-900/80 p-8 rounded-2xl border border-slate-700 shadow-2xl max-w-md w-full text-center backdrop-blur-md">
           <div className="w-16 h-16 bg-cyan-500/10 rounded-full flex items-center justify-center mx-auto mb-6 border border-cyan-500/30">
              <Lock className="w-8 h-8 text-cyan-400" />
           </div>
           
           <h1 className="text-3xl font-bold font-hud text-white mb-2 tracking-wide">JARVIS SYSTEM</h1>
           <p className="text-slate-400 mb-8 font-mono text-sm">Authentication Required for Neural Link</p>
           
           <button 
             onClick={handleSelectKey}
             className="w-full py-4 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl font-bold tracking-widest uppercase transition-all shadow-lg hover:shadow-cyan-500/25 flex items-center justify-center gap-2 group"
           >
             <span>Authenticate</span>
             <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
           </button>
           
           <div className="mt-6 text-xs text-slate-500">
             <p>Access requires a valid Google Cloud API Key with billing enabled for Gemini 2.5 and Imagen 3 models.</p>
             <a href="https://ai.google.dev/gemini-api/docs/billing" target="_blank" rel="noreferrer" className="text-cyan-600 hover:text-cyan-400 underline mt-2 inline-block">View Billing Documentation</a>
           </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-slate-950 text-slate-100 flex flex-col md:flex-row relative selection:bg-cyan-500/30">
      
      {/* Background Grid Animation */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-20" 
           style={{ 
             backgroundImage: 'linear-gradient(rgba(14, 165, 233, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(14, 165, 233, 0.1) 1px, transparent 1px)', 
             backgroundSize: '40px 40px' 
           }}>
      </div>

      {/* LEFT COLUMN: Controls & Logs */}
      <div className="w-full md:w-1/3 lg:w-1/4 p-4 md:p-6 flex flex-col gap-6 z-10 bg-slate-900/80 backdrop-blur-md border-r border-slate-800 overflow-hidden h-[100dvh]">
        <header>
          <h1 className="text-4xl font-bold font-hud text-cyan-400 tracking-tighter mb-1">JARVIS</h1>
          <p className="text-xs text-cyan-600 font-mono uppercase tracking-[0.2em]">Live Interface System</p>
        </header>
        
        <div className="flex-1 flex flex-col gap-4 min-h-0">
          {/* Connection Status */}
          <div className={`p-4 rounded-lg border ${state === ConnectionState.CONNECTED ? 'border-cyan-500/30 bg-cyan-950/20' : 'border-red-500/30 bg-red-950/20'} transition-colors duration-500`}>
             <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-slate-400 uppercase">System Status</span>
                <span
                  className={`inline-flex items-center gap-2 px-2 py-1 rounded-full border text-[11px] font-mono uppercase tracking-wide ${
                    state === ConnectionState.CONNECTED
                      ? 'border-cyan-500/40 bg-cyan-950/20 text-cyan-200'
                      : state === ConnectionState.CONNECTING
                        ? 'border-yellow-500/40 bg-yellow-950/10 text-yellow-200'
                        : state === ConnectionState.ERROR
                          ? 'border-red-500/40 bg-red-950/20 text-red-200'
                          : 'border-slate-700 bg-slate-950/20 text-slate-300'
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      state === ConnectionState.CONNECTED
                        ? 'bg-cyan-400'
                        : state === ConnectionState.CONNECTING
                          ? 'bg-yellow-400 animate-pulse'
                          : state === ConnectionState.ERROR
                            ? 'bg-red-400'
                            : 'bg-slate-400'
                    }`}
                  />
                  {state === ConnectionState.CONNECTED
                    ? 'Live'
                    : state === ConnectionState.CONNECTING
                      ? 'Connecting'
                      : state === ConnectionState.ERROR
                        ? 'Error'
                        : 'Offline'}
                </span>
             </div>
             <div className="flex items-center justify-end">
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
                   className="px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-950/40 text-xs font-mono disabled:opacity-50"
                 >
                   {state === ConnectionState.CONNECTING ? "Connecting..." : "Connect"}
                 </button>
               )}
             </div>
             {state === ConnectionState.CONNECTED && (
               <div className="h-1 w-full bg-slate-800 rounded-full overflow-hidden">
                  <div className="h-full bg-cyan-500 animate-pulse w-full"></div>
               </div>
             )}
          </div>

          {/* Activity Log */}
          <div className="flex-1 overflow-y-auto pr-2 space-y-3 mask-image-b pb-40 md:pb-0">
             <div className="text-xs font-mono text-slate-500 uppercase tracking-widest sticky top-0 bg-slate-900/90 py-1 mb-2 flex items-center justify-between">
               <span>Operation Log</span>
              <div className="flex items-center gap-2">
                <button
                  className="text-[10px] font-mono text-slate-600 hover:text-slate-400 normal-case"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const visible = (showDebugLogs ? messages : messages.filter((m) => (m.metadata?.severity || "info") !== "debug"));
                    const lines = visible
                      .slice()
                      .reverse()
                      .map((m) => {
                        const ts = m.timestamp.toLocaleTimeString();
                        const role = String(m.role || "");
                        const txt = String(m.text || "");
                        return `[${ts}] ${role}: ${txt}`;
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
                  className="text-[10px] font-mono text-slate-600 hover:text-slate-400 normal-case"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setShowDebugLogs((v) => !v);
                  }}
                >
                  {showDebugLogs ? "hide debug" : "show debug"}
                </button>
              </div>
             </div>
             {messages.length === 0 && (
               <div className="text-sm text-slate-600 italic mt-10 text-center">Awaiting inputs...</div>
             )}
             {(() => {
               const visible = (showDebugLogs ? messages : messages.filter((m) => (m.metadata?.severity || "info") !== "debug"));
               const seenKeys = new Set<string>();
               const dedupeKeyForRender = (t: string): string | null => {
                 const s = String(t || "").trim().toLowerCase().replace(/\s+/g, " ");
                 if (!s) return null;
                 if (s.includes("sheets are not auto-loaded")) return "sheets_not_auto_loaded";
                 if (s.startsWith("reload system: start") || s.startsWith("reload system: ok") || s.startsWith("reload system สำเร็จ")) return "reload_system";
                 if (s.includes("โหลด memory") && s.includes("knowledge")) return "loaded_memory_th";
                 if (s.includes("loaded memory") && s.includes("knowledge")) return "loaded_memory_en";
                 // Time injection lines (Thai and ISO-ish).
                 if (s.startsWith("อา.") || /^\d{4}-\d{2}-\d{2}\b/.test(s)) return "time_injection";
                 return null;
               };
               const filtered = visible.filter((m) => {
                 const k = dedupeKeyForRender(String(m.text || ""));
                 if (!k) return true;
                 if (seenKeys.has(k)) return false;
                 seenKeys.add(k);
                 return true;
               });
               return filtered.map((m) => {
               const canExpand = Boolean(m.metadata?.raw || m.metadata?.trace_id || m.metadata?.ws?.type || m.metadata?.ws?.instance_id);
               const expanded = expandedLogId === m.id;
               let rawText = "";
               if (expanded && m.metadata?.raw != null) {
                 try {
                   rawText = JSON.stringify(m.metadata.raw, null, 2);
                 } catch {
                   rawText = String(m.metadata.raw);
                 }
               }
               const traceLine = m.metadata?.trace_id ? `trace_id=${String(m.metadata.trace_id)}` : "";
               const typeLine = m.metadata?.ws?.type ? `type=${String(m.metadata.ws.type)}` : "";
               const instLine = m.metadata?.ws?.instance_id ? `instance_id=${String(m.metadata.ws.instance_id)}` : "";
               const metaLine = [typeLine, instLine, traceLine].filter(Boolean).join(" ");
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
                      {m.role === 'model' && <Activity className="w-3 h-3 text-cyan-400" />}
                      {m.metadata?.type === 'search' && <Search className="w-3 h-3 text-yellow-400" />}
                      {m.metadata?.type === 'image_gen' && <ImageIcon className="w-3 h-3 text-purple-400" />}
                      {m.metadata?.type === 'reimagine' && <Camera className="w-3 h-3 text-pink-400" />}
                      <span className="text-xs text-slate-500 font-mono">{m.timestamp.toLocaleTimeString()}</span>
                      <button
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-slate-300"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          const ts = m.timestamp.toLocaleTimeString();
                          const role = String(m.role || "");
                          const txt = String(m.text || "");
                          void copyText(`[${ts}] ${role}: ${txt}`);
                        }}
                        title="Copy"
                        aria-label="Copy"
                      >
                        <Copy className="w-3 h-3" />
                      </button>
                     {canExpand && (
                       <span className="text-[10px] text-slate-600 font-mono">{expanded ? "hide" : "details"}</span>
                     )}
                  </div>
                   <div className="text-slate-300 pl-5 border-l border-slate-700 py-1 whitespace-pre-wrap">
                      {m.text}
                      {expanded && metaLine && (
                        <div className="mt-2 text-[11px] font-mono text-slate-500 whitespace-pre-wrap">{metaLine}</div>
                      )}
                      {expanded && rawText && (
                        <pre className="mt-2 text-[11px] font-mono text-slate-400 whitespace-pre-wrap">{rawText}</pre>
                      )}
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
                className="shrink-0 w-10 h-10 rounded-xl border border-slate-700 bg-slate-950/40 text-slate-200 hover:bg-slate-800/60 disabled:opacity-50 disabled:hover:bg-slate-950/40 flex items-center justify-center"
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
                ? 'bg-slate-800/50 text-slate-500 border border-slate-700 cursor-not-allowed'
                : isTalking
                  ? 'bg-yellow-500/10 text-yellow-300 border border-yellow-500/50 hover:bg-yellow-500/20 shadow-yellow-500/20'
                  : 'bg-slate-900/50 text-cyan-200 border border-cyan-500/30 hover:bg-slate-900/70 shadow-cyan-500/10'}
            `}
          >
            {isTalking ? (
              <><MicOff className="w-4 h-4" /> Stop</>
            ) : (
              <><Mic className="w-4 h-4" /> Talk</>
            )}
          </button>
        </div>
      </div>

      {/* RIGHT COLUMN: Visualizer & Output */}
      <div className="flex-1 p-4 md:p-6 flex flex-col gap-6 relative z-10">
         
         {/* Top Section: Visualizer & Camera */}
         <div className="grid grid-cols-1 md:grid-cols-2 gap-6 h-[320px]">
            {/* Audio Visualizer */}
            <div className="relative rounded-2xl border border-slate-700 bg-slate-900/50 flex items-center justify-center overflow-hidden">
               <div className="absolute top-3 left-4 text-[10px] text-cyan-500 font-hud tracking-widest uppercase">Audio Input Matrix</div>
               <Visualizer volume={volume} active={state === ConnectionState.CONNECTED} />
            </div>

            {/* Camera Feed */}
            <div className="relative rounded-2xl border border-slate-700 bg-slate-900/50 flex items-center justify-center p-2">
               <div className="absolute top-3 left-4 text-[10px] text-cyan-500 font-hud tracking-widest uppercase z-10">&nbsp;</div>
               <div className="w-full h-full relative rounded-lg overflow-hidden">
                 <CameraFeed active={state === ConnectionState.CONNECTED} onFrame={handleFrame} />
                 {!state && <div className="absolute inset-0 flex items-center justify-center text-slate-600 font-mono text-sm">System Offline</div>}
               </div>
            </div>
         </div>

         {/* Bottom Section: Media Output */}
         <div className="flex-1 rounded-2xl border border-slate-700 bg-slate-900/50 p-6 relative overflow-hidden min-h-[300px]">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-cyan-500/50 to-transparent"></div>
            <div className="absolute top-4 left-6 right-6 flex items-center justify-between gap-3">
              <div className="text-[10px] text-cyan-500 font-hud tracking-widest uppercase flex items-center gap-2">
                <span>{activeRightPanel === "cars" ? "Cars" : "Main Output Display"}</span>
                {activeRightPanel === "output" && activeMedia && (
                  <span className="px-2 py-0.5 rounded bg-cyan-900/50 text-cyan-200 border border-cyan-700/50 text-[9px]">{activeMedia.metadata?.type}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setActiveRightPanel("output")}
                  className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                    activeRightPanel === "output"
                      ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                      : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                  }`}
                >
                  Output
                </button>
                <button
                  onClick={() => setActiveRightPanel("cars")}
                  className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                    activeRightPanel === "cars"
                      ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                      : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                  }`}
                >
                  Cars
                </button>
                <button
                  onClick={() => setActiveRightPanel("checklist")}
                  className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                    activeRightPanel === "checklist"
                      ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                      : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                  }`}
                >
                  Checklist
                </button>
              </div>
            </div>
            
            <div className="h-full w-full flex items-center justify-center overflow-auto mt-6">
               {activeRightPanel === "cars" ? (
                 <div className="w-full h-full">
                   <CarsPanel liveService={liveService.current} connectionState={state} />
                 </div>
               ) : activeRightPanel === "checklist" ? (
                 <div className="w-full h-full">
                   <div className="text-[10px] text-cyan-500 font-hud tracking-widest uppercase mb-3">Sequential Checklist</div>
                   <textarea
                     value={seqNotes}
                     onChange={(e) => setSeqNotes(e.target.value)}
                     placeholder="Paste task notes with checklist here (e.g. - [ ] step)"
                     className="w-full h-40 px-3 py-2 rounded-xl text-sm font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600"
                   />
                   <textarea
                     value={seqCompletedNotes}
                     onChange={(e) => setSeqCompletedNotes(e.target.value)}
                     placeholder="Optional: paste completed task notes blocks for template inference (separate blocks with a line containing ---)"
                     className="w-full h-28 mt-3 px-3 py-2 rounded-xl text-sm font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600"
                   />
                   <div className="mt-3 flex items-center flex-wrap gap-2">
                     <button
                       onClick={() => void handleSeqSuggest()}
                       disabled={seqBusy}
                       className="px-3 py-2 rounded-xl border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-950/40 disabled:opacity-50 text-xs font-mono"
                     >
                       Suggest
                     </button>
                     <button
                       onClick={() => void handleSeqApply()}
                       disabled={seqBusy || seqNextIndex == null}
                       className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 disabled:opacity-50 text-xs font-mono"
                     >
                       Apply
                     </button>
                     <button
                       onClick={() => void handleSeqApplyByText()}
                       disabled={seqBusy || !seqNextText}
                       className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 disabled:opacity-50 text-xs font-mono"
                     >
                       Apply by text
                     </button>
                     <button
                       onClick={() => void handleSeqApplyAll()}
                       disabled={seqBusy}
                       className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 disabled:opacity-50 text-xs font-mono"
                     >
                       Apply all
                     </button>
                     {seqError && <div className="text-xs font-mono text-red-400 truncate">{seqError}</div>}
                   </div>
                   <div className="mt-3 text-xs font-mono text-slate-300">
                     <div>next_step: {seqNextText ?? "(none)"}{seqNextIndex != null ? ` (index=${seqNextIndex})` : ""}</div>
                     <div>template: {seqTemplate ? seqTemplate.join(" | ") : "(none)"}</div>
                   </div>
                 </div>
               ) : !activeMedia ? (
                 <div className="flex flex-col items-center justify-center text-slate-600 gap-4">
                    <Activity className="w-16 h-16 opacity-20" />
                    <p className="font-mono text-sm tracking-wide">Waiting for system output...</p>
                 </div>
               ) : (
                 <div className="w-full h-full flex flex-col items-center animate-in zoom-in-95 duration-500">
                    {activeMedia.metadata?.image && (
                      <div className="relative group max-w-full max-h-full">
                         <img 
                           src={activeMedia.metadata.image} 
                           alt="Generated content" 
                           className="max-h-[400px] w-auto rounded-lg shadow-2xl border border-slate-600"
                         />
                         <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded backdrop-blur font-mono">
                            Generated by Gemini
                         </div>
                      </div>
                    )}

                    {activeMedia.metadata?.sources && (
                      <div className="w-full max-w-2xl bg-slate-800/50 rounded-lg border border-slate-700 p-4">
                         <h3 className="text-cyan-400 font-hud text-sm mb-3 uppercase tracking-wider">Grounding Sources</h3>
                         <ul className="space-y-2">
                           {activeMedia.metadata.sources.map((src, i) => (
                             <li key={i} className="flex items-start gap-3 p-2 rounded hover:bg-slate-700/50 transition-colors">
                                <span className="bg-slate-700 text-slate-300 text-xs w-5 h-5 flex items-center justify-center rounded-full flex-shrink-0 font-mono">{i + 1}</span>
                                <a href={src.uri} target="_blank" rel="noopener noreferrer" className="text-sm text-cyan-300 hover:text-cyan-200 hover:underline truncate">
                                  {src.title}
                                </a>
                             </li>
                           ))}
                         </ul>
                      </div>
                    )}
                 </div>
               )}
            </div>
         </div>
         
      </div>

    </div>
  );
}