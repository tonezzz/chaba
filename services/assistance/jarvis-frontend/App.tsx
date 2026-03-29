import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { LiveService } from './services/liveService';
import { sequentialApplyAndSuggest } from './services/sequentialService';
import { ConnectionState, MessageLog } from './types';
import { useFullscreenEscape } from './hooks/useFullscreenEscape';

import { useAutoScroll } from './hooks/useAutoScroll';
import { useUiLog } from './hooks/useUiLog';
import { usePending } from './hooks/usePending';

import Visualizer from './components/Visualizer';
import CameraFeed from './components/CameraFeed';
import CarsPanel from './components/CarsPanel';
import { LeftPanel } from './components/app/LeftPanel';
import { OutputPanel } from './components/app/OutputPanel';
import { Play, Mic, MicOff, Search, Image as ImageIcon, Camera, Activity, Lock, ChevronRight, Paperclip, Send, X, Link2Off, Copy, CheckCircle2, AlertTriangle, XCircle, HeartPulse, Maximize2, Minimize2 } from 'lucide-react';

import { extractReminderAddText, normalizeComposerText, parseSysDedupe, parseSysSet, parseToolInvoke, splitSentences } from './lib/appHelpers';

export default function App() {
  const [hasKey, setHasKey] = useState(false);
  const [state, setState] = useState<ConnectionState>(ConnectionState.DISCONNECTED);
  const [volume, setVolume] = useState(0);

  const [messages, setMessages] = useState<MessageLog[]>([]);
  const resumeHydratedRef = useRef<boolean>(false);
  const [statusDetailsOpen, setStatusDetailsOpen] = useState<boolean>(() => {
    try {
      const raw = String(window.localStorage.getItem("jarvis_status_details_open") || "").trim();
      if (!raw) return false;
      return raw === "1" || raw.toLowerCase() === "true";
    } catch {
      return false;
    }
  });
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [showDebugLogs, setShowDebugLogs] = useState(false);
  const liveService = useRef<LiveService | null>(null);
  const [activeMedia, setActiveMedia] = useState<MessageLog | null>(null);
  const [isTalking, setIsTalking] = useState(false);
  const [leftFullscreen, setLeftFullscreen] = useState(false);
  const [activeRightPanel, setActiveRightPanel] = useState<"output" | "cars" | "checklist">("output");
  const [activeOutputTab, setActiveOutputTab] = useState<"dialog" | "ui_log" | "ws_log" | "pending">("dialog");
  const [wsLogText, setWsLogText] = useState<string>("");
  const [wsLogErr, setWsLogErr] = useState<string>("");

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
  const logScrollRef = useRef<HTMLDivElement | null>(null);
  const logStickToBottomRef = useRef<boolean>(true);
  const outputScrollRef = useRef<HTMLDivElement | null>(null);
  const outputStickToBottomRef = useRef<boolean>(true);

  const systemCounts = useMemo(() => {
    const out = { memory: 0, knowledge: 0, ok: false };
    const rxOk = /\bmemory\s*=\s*(\d+)\b[^\d]+\bknowledge\s*=\s*(\d+)\b/i;
    const rxMemKnowParen = /\bmemory\s*\(\s*(\d+)\s*:\s*(\d+)\s*\)[\s\S]*?\bknowledge\s*\(\s*(\d+)\s*:\s*(\d+)\s*\)/i;
    const rxLoadedEn = /\bloaded\s+memory\b[\s\S]*?\b(\d+)\b[\s\S]*?\bknowledge\b[\s\S]*?\b(\d+)\b/i;
    const rxLoadedTh = /โหลด\s*memory[\s\S]*?(\d+)[\s\S]*?knowledge[\s\S]*?(\d+)/i;
    for (const m of messages) {
      const t = String(m.text || "");
      let mm: RegExpMatchArray | null = null;
      mm = t.match(rxOk);
      if (!mm) {
        const mm2 = t.match(rxMemKnowParen);
        if (mm2) {
          const memLoaded = Number(mm2[2] || 0);
          const knowLoaded = Number(mm2[4] || 0);
          if (Number.isFinite(memLoaded) && Number.isFinite(knowLoaded)) {
            out.memory = memLoaded;
            out.knowledge = knowLoaded;
            out.ok = true;
            break;
          }
        }
      }
      if (!mm) mm = t.match(rxLoadedEn);
      if (!mm) mm = t.match(rxLoadedTh);
      if (!mm) continue;
      const mem = Number(mm[1] || 0);
      const know = Number(mm[2] || 0);
      if (!Number.isFinite(mem) || !Number.isFinite(know)) continue;
      out.memory = mem;
      out.knowledge = know;
      out.ok = true;
      break;
    }
    return out;
  }, [messages]);

  const backendCandidates = useCallback((): string[] => {
    const override = String((import.meta as any).env?.VITE_JARVIS_HTTP_URL as string | undefined || "").trim();
    const normOverride = override ? override.trim().replace(/\/+$/, "").replace(/^\s+|\s+$/g, "") : "";
    const isJarvisSubpath = location.pathname.startsWith("/jarvis");
    const defaults = isJarvisSubpath ? ["/jarvis/api", "/jarvis", ""] : ["", "/jarvis/api", "/jarvis"];
    const out = normOverride ? [normOverride, ...defaults] : defaults;

    const seen = new Set<string>();
    return out.filter((v) => {
      const k = String(v || "");
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }, []);

  const { uiLogText, setUiLogText, loadUiLogFromLocalStorage, appendUiLogEntry, scheduleUiLogFlush } = useUiLog({
    backendCandidates,
  });

  const {
    pendingItems,
    pendingSelectedId,
    pendingPreview,
    pendingActionBusy,
    pendingActionResult,
    pendingErr,
    pendingAuthCode,
    setPendingAuthCode,
    refreshPending,
    copyPendingJson,
    previewPending,
    queueGoogleRelink,
    confirmPending,
    cancelPending,
    queueBundlePublishReload,
  } = usePending({
    liveService,
    setActiveRightPanel,
    setActiveOutputTab,
  });

  const refreshWsLog = useCallback(async () => {
    setWsLogErr("");
    for (const base of backendCandidates()) {
      try {
        const res = await fetch(`${base}/logs/ws/today?max_bytes=200000`, { method: "GET" });
        if (!res.ok) continue;
        const j = await res.json();
        const txt = j?.text != null ? String(j.text) : "";
        setWsLogText(txt);
        return;
      } catch {
        // try next
      }
    }
    setWsLogErr("failed_to_fetch_ws_log");
  }, [backendCandidates]);

  const audioStatus = useMemo(() => {
    let lastConn = 0;
    let lastAudioUnavailable = 0;

    for (const m of messages) {
      const id = String(m.id || "");
      const txt = String(m.text || "").toLowerCase();
      const ts = m.timestamp?.getTime?.() ? m.timestamp.getTime() : 0;
      if (id.endsWith("_state") && txt === "connected") lastConn = Math.max(lastConn, ts);
      if (id.includes("_audio_unavailable") || txt.startsWith("audio_unavailable")) {
        lastAudioUnavailable = Math.max(lastAudioUnavailable, ts);
      }
    }
    const ok = state === ConnectionState.CONNECTED && (!lastAudioUnavailable || lastAudioUnavailable < lastConn);
    return { ok, lastConn, lastAudioUnavailable };
  }, [messages, state]);

  const outputDialog = useMemo(() => {
    const ordered = messages
      .filter((m) => {
        if (m.role !== "model") return false;
        const src = String(m.metadata?.source || "");
        const sev = String(m.metadata?.severity || "info");
        const cat = String(m.metadata?.category || "");
        // Include explicit output transcripts and normal assistant text. Exclude debug.
        if (sev === "debug") return false;
        if (src === "output") return true;
        if (cat === "live") return true;
        return false;
      })
      .slice()
      .sort((a, b) => {
        const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
        const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
        if (ta !== tb) return ta - tb;
        return String(a.id || "").localeCompare(String(b.id || ""));
      });

    const dialog: Array<{ id: string; text: string }> = [];
    for (const m of ordered) {
      const sents = splitSentences(String(m.text || ""));
      for (let i = 0; i < sents.length; i++) {
        const sent = sents[i];
        const isLast = i === sents.length - 1;
        const id = `${m.id}_s${i}`;
        if (isLast && !sent.complete && dialog.length) {
          // Update the last line (merge partials) so live streaming doesn't spam.
          dialog[dialog.length - 1] = { ...dialog[dialog.length - 1], text: sent.t };
        } else {
          dialog.push({ id, text: sent.t });
        }
      }
    }
    return dialog.slice(-200);
  }, [messages]);

  const outputChat = useMemo(() => {
    const ordered = messages
      .filter((m) => {
        const t = String(m.text || "").trim();

        if (!t) return false;
        if (m.role === "user" || m.role === "model") return true;
        if (m.role === "system") return true;
        return false;
      })
      .slice()
      .sort((a, b) => {
        const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
        const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
        if (ta !== tb) return ta - tb;
        return String(a.id || "").localeCompare(String(b.id || ""));
      });
    return ordered.slice(-200);
  }, [messages]);

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

  const clientLabelForMsg = useCallback((m: MessageLog): string => {
    const tag = String((m.metadata as any)?.ws?.client_tag || "").trim();
    const id = String((m.metadata as any)?.ws?.client_id || "").trim();
    const suffix = id ? id.slice(-6) : "";
    if (tag && suffix) return `${tag}:${suffix}`;
    if (tag) return tag;
    if (suffix) return suffix;
    return "";
  }, []);

  useEffect(() => {
    const checkKey = async () => {
      try {
        if ((window as any).aistudio && (await (window as any).aistudio.hasSelectedApiKey())) {
          setHasKey(true);
        }
      } catch {
        // ignore
      }
    };
    void checkKey();
  }, []);

  useEffect(() => {
    if (!hasKey) return;

    liveService.current = new LiveService();
    liveService.current.onStateChange = setState;
    liveService.current.onVolume = setVolume;
    liveService.current.onPendingEvent = (ev) => {
      try {
        const event = String((ev as any)?.event || "").trim();
        const cid = String((ev as any)?.confirmation_id || "").trim();
        if (event === "awaiting_user" && cid) {
          setActiveRightPanel("output");
          setActiveOutputTab("pending");
        }
        (async () => {
          try {
            await refreshPending();
            if (event === "awaiting_user" && cid) {
              await previewPending(cid);
            }
          } catch {
            // ignore
          }
        })();
      } catch {
        // ignore
      }
    };
    liveService.current.onCarsIngestResult = (ev) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_cars_ingest_${Math.random().toString(16).slice(2)}`,
          role: "system",
          text: `cars_ingest_result ok=${String((ev as any)?.ok)} items=${Array.isArray((ev as any)?.items) ? (ev as any).items.length : 0}`,
          timestamp: new Date(),
        },
      ]);
      setActiveRightPanel("cars");
    };

    liveService.current.onMessage = (msg) => {
      try {
        appendUiLogEntry(msg);
        scheduleUiLogFlush();
      } catch {
        // ignore
      }

      try {
        const resume = (msg as any)?.metadata?.resume;
        const ok = resume?.ok === true;
        const turns = Array.isArray(resume?.turns) ? resume.turns : [];
        if (ok && turns.length && !resumeHydratedRef.current) {
          resumeHydratedRef.current = true;
          const resumed: MessageLog[] = turns
            .map((t: any, i: number) => {
              const role = String(t?.role || "").trim() === "user" ? "user" : "model";
              const text = String(t?.text || "");
              const ts = typeof t?.ts === "number" ? t.ts : Date.now();
              return {
                id: `resume_${i}_${ts}`,
                role: role as any,
                text,
                timestamp: new Date(ts),
              };
            })
            .filter((m) => String(m.text || "").trim());

          setMessages((prev) => {
            const keepSystem = prev.filter((m) => m.role === "system");
            return [...keepSystem, ...resumed];
          });
        }
      } catch {
        // ignore
      }

      setMessages((prev) => {
        if (msg.id === "sticky_progress") {
          const without = prev.filter((m) => m.id !== "sticky_progress");
          const txt = String(msg.text || "").trim();
          if (!txt) return without;
          return [...without, msg];
        }
        return [...prev, msg];
      });

      if (msg.metadata) {
        setActiveMedia(msg);
      }
    };

    return () => {
      try {
        void liveService.current?.disconnect();
      } catch {
        // ignore
      }
    };
  }, [hasKey, appendUiLogEntry, previewPending, refreshPending, scheduleUiLogFlush]);

  useAutoScroll(logScrollRef, logStickToBottomRef, [messages, showDebugLogs]);
  useAutoScroll(outputScrollRef, outputStickToBottomRef, [outputDialog]);

  useEffect(() => {
    try {
      window.localStorage.setItem("jarvis_status_details_open", statusDetailsOpen ? "1" : "0");
    } catch {
      // ignore
    }
  }, [statusDetailsOpen]);

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
    const normalized = normalizeComposerText(base);

    const sysSet = parseSysSet(normalized);
    if (sysSet) {
      liveService.current?.sendSysKvSet(sysSet.key, sysSet.value, { dry_run: sysSet.dryRun });
      setComposerText("");
      setAttachments([]);
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_sys_set_ui`,
          role: "system",
          text: `${sysSet.dryRun ? "sys_kv_set (dry_run)" : "sys_kv_set"}: ${sysSet.key}=${sysSet.value}`,
          timestamp: new Date(),
          metadata: { severity: "info", category: "ws" },
        },
        {
          id: `${Date.now()}_sys_set_hint`,
          role: "system",
          text: "Hint: run 'reload system' to apply sys changes.",
          timestamp: new Date(),
          metadata: { severity: "debug", category: "ws" },
        },
      ]);
      return;
    }

    const sysDedupe = parseSysDedupe(normalized);
    if (sysDedupe) {
      liveService.current?.sendSysKvDedupe({ dry_run: sysDedupe.dryRun, sort: sysDedupe.sort });
      setComposerText("");
      setAttachments([]);
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_sys_dedupe_ui`,
          role: "system",
          text: `${sysDedupe.dryRun ? "sys_kv_dedupe (dry_run)" : "sys_kv_dedupe"}${sysDedupe.sort ? " (sort)" : ""}`,
          timestamp: new Date(),
          metadata: { severity: "info", category: "ws" },
        },
      ]);
      return;
    }

    if (normalized.toLowerCase() === "system clear job" || normalized.toLowerCase() === "sys clear job") {
      liveService.current?.sendSystemClearJob();
      setComposerText("");
      setAttachments([]);
      return;
    }

    const toolInvoke = parseToolInvoke(normalized);
    if (toolInvoke) {
      setComposerText("");
      setAttachments([]);
      if ((toolInvoke.args as any)?.__invalid_tool_prefix) {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}_tool_invalid_prefix`,
            role: "system",
            text: `tool rejected (prefix): ${toolInvoke.name}`,
            timestamp: new Date(),
            metadata: { severity: "warn", category: "ws" },
          },
        ]);
        return;
      }
      if ((toolInvoke.args as any)?.__invalid_tool_args) {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}_tool_invalid_args`,
            role: "system",
            text: `tool args must be a JSON object: ${toolInvoke.name}`,
            timestamp: new Date(),
            metadata: { severity: "warn", category: "ws" },
          },
        ]);
        return;
      }
      try {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}_tool_ui`,
            role: "system",
            text: `tool: ${toolInvoke.name}`,
            timestamp: new Date(),
            metadata: { severity: "info", category: "ws" },
          },
        ]);
        void liveService.current
          ?.invokeTool(toolInvoke.name, toolInvoke.args)
          .catch((e: any) => {
            setMessages((prev) => [
              ...prev,
              {
                id: `${Date.now()}_tool_send_err`,
                role: "system",
                text: `tool failed: ${toolInvoke.name} (${String(e?.message || e || "tool_failed")})`,
                timestamp: new Date(),
                metadata: { severity: "error", category: "ws" },
              },
            ]);
          });
      } catch (e: any) {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}_tool_send_throw`,
            role: "system",
            text: `tool failed: ${toolInvoke.name} (${String(e?.message || e || "tool_failed")})`,
            timestamp: new Date(),
            metadata: { severity: "error", category: "ws" },
          },
        ]);
      }
      return;
    }

    const isReloadSystemPhrase = (text: string): boolean => {
      const s = String(text || "").trim().toLowerCase();
      if (!s) return false;

      const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
      if (!compact) return false;
      // Keep permissive matching (voice + typed).
      if (compact === "reload" || compact === "reset" || compact === "restart" || compact === "reboot") return true;
      if (compact.includes("reload system") || compact.includes("reload sheets")) return true;
      if ((compact.includes("reload") || compact.includes("reset") || compact.includes("restart") || compact.includes("reboot")) && (compact.includes("system") || compact.includes("sheets") || compact.includes("sheet") || compact.includes("sys"))) {
        return true;
      }
      // Thai triggers.
      if (compact.includes("รีโหลด") || compact.includes("โหลดใหม่") || compact.includes("รีเซ็ต") || compact.includes("เริ่มใหม่")) {
        if (compact.includes("ระบบ") || compact.includes("ชีต") || compact.includes("ชีท") || compact.includes("sheet") || compact.includes("sheets")) return true;
      }
      return false;
    };

    const extractSystemReloadMode = (text: string): "full" | "memory" | "knowledge" | "sys" => {
      const s = String(text || "").trim().toLowerCase();
      const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
      const has = (w: string) => compact.includes(w);
      if (has("knowledge") || has("kb") || has("know") || has("ความรู้")) return "knowledge";
      if (has("memory") || has("mem") || has("เมม") || has("เมมโม")) return "memory";
      return "full";
    };

    if (base && isReloadSystemPhrase(base)) {
      const mode = extractSystemReloadMode(base);
      try {
        const svc = liveService.current as any;
        if (svc?.invokeTool) {
          void svc.invokeTool("system_reload_queue", { mode }).then(
            () => {
              setActiveRightPanel("output");
              setActiveOutputTab("pending");
              void refreshPending();
            },
            () => {
              liveService.current?.sendSystemReload(mode);
            }
          );
        } else {
          liveService.current?.sendSystemReload(mode);
        }
      } catch {
        liveService.current?.sendSystemReload(mode);
      }
      setComposerText("");
      setAttachments([]);
      return;
    }

    const reminderText = base ? extractReminderAddText(base) : null;
    if (reminderText) {
      liveService.current?.sendRemindersAdd(reminderText);
      setComposerText("");
      setAttachments([]);
      return;
    }

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

  const [containerStatus, setContainerStatus] = useState<any>(null);
  const [containerStatusError, setContainerStatusError] = useState<string>("");
  const [uiCardInputByMsgId, setUiCardInputByMsgId] = useState<Record<string, string>>({});

  const [depsStatus, setDepsStatus] = useState<any>(null);
  const [depsStatusError, setDepsStatusError] = useState<string>("");
  const [depsStatusRefreshNonce, setDepsStatusRefreshNonce] = useState<number>(0);

  useEffect(() => {
    if (hasKey) return;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        setContainerStatusError("");
        const joinUrl = (base: string, path: string): string => {
          const b = String(base || "").replace(/\/+$/, "");
          const p = String(path || "");
          if (!b) return p;
          return `${b}${p}`;
        };

        const pathsToTry = ["/api/status", "/status", "/jarvis/api/status", "/jarvis/status", "/status"];
        let lastErr = "status_fetch_failed";
        let okJson: any = null;

        outer: for (const base of backendCandidates()) {
          for (const p of pathsToTry) {
            try {
              const attempt = await fetch(joinUrl(base, p), { cache: "no-store" });
              if (!attempt || !attempt.ok) {
                if (attempt) lastErr = `status_fetch_failed (http ${attempt.status})`;
                continue;
              }

              // If the server returns HTML (e.g. /jarvis/ index), do NOT accept it.
              const ct = String(attempt.headers.get("content-type") || "").toLowerCase();
              const bodyText = await attempt.text();
              const trimmed = String(bodyText || "").trim();
              if (!trimmed) {
                lastErr = `status_error: empty response (http ${attempt.status})`;
                continue;
              }

              // Prefer explicit JSON content-type, but also allow valid JSON even if content-type is wrong.
              if (ct && !ct.includes("json") && (trimmed.startsWith("<!doctype") || trimmed.startsWith("<html") || trimmed.startsWith("<"))) {
                const preview = trimmed.length > 220 ? trimmed.slice(0, 220) + "…" : trimmed;
                lastErr = `status_error: non_json_response (http ${attempt.status}) preview=${preview}`;
                continue;
              }

              try {
                okJson = JSON.parse(trimmed);
                break outer;
              } catch {
                const preview = trimmed.length > 220 ? trimmed.slice(0, 220) + "…" : trimmed;
                lastErr = `status_error: invalid json (http ${attempt.status}) preview=${preview}`;
                continue;
              }
            } catch (e: any) {
              lastErr = String(e?.message || e || "status_fetch_failed");
              continue;
            }
          }
        }

        if (okJson == null) throw new Error(lastErr);
        if (!cancelled) setContainerStatus(okJson);
      } catch (e: any) {
        if (!cancelled) {
          setContainerStatus(null);
          setContainerStatusError(String(e?.message || e || "status_fetch_failed"));
        }
      }
    };
    void fetchOnce();
    const t = window.setInterval(fetchOnce, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [hasKey, backendCandidates]);

  useEffect(() => {
    if (!hasKey) return;
    if (!statusDetailsOpen) return;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        setDepsStatusError("");
        let res: Response | null = null;
        try {
          res = await fetch("/jarvis/api/debug/status", { cache: "no-store" });
        } catch {
          res = null;
        }
        if (!res || !res.ok) {
          try {
            res = await fetch("/jarvis/debug/status", { cache: "no-store" });
          } catch {
            res = null;
          }
        }
        if (!res || !res.ok) {
          res = await fetch("/debug/status", { cache: "no-store" });
        }
        if (!res) throw new Error("deps_status_fetch_failed");

        const bodyText = await res.text();
        const trimmed = String(bodyText || "").trim();
        if (!trimmed) {
          throw new Error(`deps_status_error: empty response (http ${res.status})`);
        }
        let js: any = null;
        try {
          js = JSON.parse(trimmed);
        } catch {
          const preview = trimmed.length > 220 ? trimmed.slice(0, 220) + "…" : trimmed;
          throw new Error(`deps_status_error: invalid json (http ${res.status}) preview=${preview}`);
        }
        if (!cancelled) setDepsStatus(js);
      } catch (e: any) {
        if (!cancelled) {
          setDepsStatus(null);
          setDepsStatusError(String(e?.message || e || "deps_status_fetch_failed"));
        }
      }
    };
    void fetchOnce();
    const t = window.setInterval(fetchOnce, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [hasKey, statusDetailsOpen, depsStatusRefreshNonce]);

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

  useFullscreenEscape(leftFullscreen, setLeftFullscreen);

  if (!hasKey) {
    const renderHealthIcon = (healthRaw: any) => {
      const h = String(healthRaw || "").trim().toLowerCase();
      if (!h) return <HeartPulse className="w-3.5 h-3.5 text-slate-500" />;
      if (h === "healthy" || h === "ok") return <HeartPulse className="w-3.5 h-3.5 text-emerald-400" />;
      if (h === "starting" || h === "pending" || h === "unknown") return <HeartPulse className="w-3.5 h-3.5 text-yellow-400" />;
      return <HeartPulse className="w-3.5 h-3.5 text-red-400" />;
    };

    const renderStatusIcon = (statusRaw: any) => {
      const s = String(statusRaw || "").trim().toLowerCase();
      if (!s) return <AlertTriangle className="w-3.5 h-3.5 text-slate-500" />;
      if (s === "running" || s === "up" || s === "online") return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
      if (s === "starting" || s === "restarting" || s === "pending") return <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" />;
      return <XCircle className="w-3.5 h-3.5 text-red-400" />;
    };

    const deriveRows = (): Array<{ name: string; status: string; health: string; detail?: string }> => {
      const out: Array<{ name: string; status: string; health: string; detail?: string }> = [];

      const js = containerStatus;
      const arr = js && Array.isArray(js.containers) ? js.containers : null;
      if (arr) {
        for (const c of arr) {
          if (!c || typeof c !== "object") continue;
          const name = String((c as any).name || (c as any).service || (c as any).id || "").trim();
          if (!name) continue;
          const status = String((c as any).status || (c as any).state || "").trim();
          const health = String((c as any).health || "").trim();
          const detail = String((c as any).detail || "").trim();
          out.push({ name, status, health, detail: detail || undefined });
        }
        return out;
      }

      // Fallback: current backend /status only reports jarvis-backend process status.
      if (js && typeof js === "object") {
        const name = String(js.service || "jarvis-backend").trim() || "jarvis-backend";
        const status = js.ok ? "running" : "error";
        const health = js.ok ? "healthy" : "unhealthy";
        let detail = "";
        if (js.startup_prewarm && typeof js.startup_prewarm === "object") {
          const p = js.startup_prewarm;
          const prewarm = p.running ? "prewarm=running" : p.ok ? `prewarm=ok (memory=${p.memory_n} knowledge=${p.knowledge_n})` : p.error ? `prewarm=error (${p.error})` : "prewarm=pending";
          detail = [prewarm, `weaviate=${js.weaviate_enabled ? "enabled" : "disabled"}`].join(" ");
        }
        out.push({ name, status, health, detail: detail || undefined });
      }

      return out;
    };

    const rows = deriveRows();

    const overall = (() => {
      let hasBad = false;
      let hasWarn = false;
      let ok = 0;
      let warn = 0;
      let bad = 0;
      for (const r of rows) {
        const s = String(r.status || "").trim().toLowerCase();
        const h = String(r.health || "").trim().toLowerCase();
        const badish = s === "exited" || s === "dead" || h === "unhealthy";
        const okish = s === "running" || s === "up" || s === "online" || h === "healthy" || h === "ok";
        const warnish = !badish && !okish;
        if (badish) {
          hasBad = true;
          bad += 1;
          continue;
        }
        if (warnish) {
          hasWarn = true;
          warn += 1;
          continue;
        }
        ok += 1;
      }
      return {
        kind: hasBad ? "bad" : hasWarn ? "warn" : "ok",
        ok,
        warn,
        bad,
        total: rows.length,
      };
    })();

    const renderOverallIcon = () => {
      if (overall.kind === "bad") return <XCircle className="w-4 h-4 text-red-400" />;
      if (overall.kind === "warn") return <AlertTriangle className="w-4 h-4 text-yellow-400" />;
      return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    };

    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center relative overflow-hidden">
        <div
          className="absolute inset-0 z-0 opacity-20"
          style={{
            backgroundImage:
              'linear-gradient(rgba(14, 165, 233, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(14, 165, 233, 0.1) 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />

        <div className="z-10 bg-slate-900/80 p-8 rounded-2xl border border-slate-700 shadow-2xl max-w-md w-full text-center backdrop-blur-md max-h-[90dvh] overflow-y-auto">
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
            <a
              href="https://ai.google.dev/gemini-api/docs/billing"
              target="_blank"
              rel="noreferrer"
              className="text-cyan-600 hover:text-cyan-400 underline mt-2 inline-block"
            >
              View Billing Documentation
            </a>
          </div>

          <div className="mt-6 text-left text-xs font-mono text-slate-400 border-t border-slate-700/60 pt-4">
            <button
              type="button"
              onClick={() => {
                const next = !statusDetailsOpen;
                setStatusDetailsOpen(next);
                try {
                  window.localStorage.setItem("jarvis_status_details_open", next ? "1" : "0");
                } catch {
                  // ignore
                }
              }}
              className="w-full flex items-center justify-between gap-2"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[10px] text-cyan-500 font-hud tracking-widest uppercase">Container Status</span>
                <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
                  {renderOverallIcon()}
                  <span>
                    {overall.total ? `${overall.ok} ok` : "n/a"}
                    {overall.warn ? `, ${overall.warn} warn` : ""}
                    {overall.bad ? `, ${overall.bad} bad` : ""}
                  </span>
                </span>
              </div>
              <ChevronRight className={`w-4 h-4 text-slate-500 transition-transform ${statusDetailsOpen ? "rotate-90" : ""}`} />
            </button>
            {containerStatusError ? (
              <div className="text-red-400">status_error: {containerStatusError}</div>
            ) : containerStatus ? (
              statusDetailsOpen ? (
                <div className="space-y-1 mt-2">
                  {String(containerStatus.instance_id || "").trim() ? (
                    <div className="text-slate-500">instance_id: {String(containerStatus.instance_id || "")}</div>
                  ) : null}
                  {String(containerStatus.hostname || "").trim() ? (
                    <div className="text-slate-500">hostname: {String(containerStatus.hostname || "")}</div>
                  ) : null}

                  <div className="mt-2 space-y-1">
                    {rows.length ? (
                      rows.map((r) => (
                        <div key={r.name} className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            {renderStatusIcon(r.status)}
                            {renderHealthIcon(r.health)}
                          </div>
                          <div className="min-w-0">
                            <div className="text-slate-300 truncate">
                              {r.name}
                              <span className="text-slate-500"> — {r.status || "unknown"}</span>
                              {r.health ? <span className="text-slate-500"> / {r.health}</span> : null}
                            </div>
                            {r.detail ? <div className="text-slate-500 break-words">{r.detail}</div> : null}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-slate-500">no status rows</div>
                    )}
                  </div>
                </div>
              ) : null
            ) : (
              <div className="text-slate-500">loading…</div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[100dvh] bg-slate-950 text-slate-100 flex flex-col md:flex-row relative selection:bg-cyan-500/30 overflow-hidden">
      
      {/* Background Grid Animation */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-20" 
           style={{ 
             backgroundImage: 'linear-gradient(rgba(14, 165, 233, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(14, 165, 233, 0.1) 1px, transparent 1px)', 
             backgroundSize: '40px 40px' 
           }}>
      </div>

      {/* LEFT COLUMN: Controls & Logs */}
      <LeftPanel
        leftFullscreen={leftFullscreen}
        setLeftFullscreen={setLeftFullscreen}
        state={state}
        statusDetailsOpen={statusDetailsOpen}
        setStatusDetailsOpen={setStatusDetailsOpen}
        systemCounts={systemCounts}
        audioStatus={audioStatus}
        depsStatusError={depsStatusError}
        depsStatus={depsStatus}
        setDepsStatusRefreshNonce={setDepsStatusRefreshNonce}
        handleConnect={handleConnect}
        logScrollRef={logScrollRef}
        logStickToBottomRef={logStickToBottomRef}
        messages={messages}
        showDebugLogs={showDebugLogs}
        setShowDebugLogs={setShowDebugLogs}
        expandedLogId={expandedLogId}
        setExpandedLogId={setExpandedLogId}
        uiCardInputByMsgId={uiCardInputByMsgId}
        setUiCardInputByMsgId={setUiCardInputByMsgId}
        copyText={copyText}
        clientLabelForMsg={clientLabelForMsg}
        liveServiceCurrent={liveService.current}
        setMessages={setMessages}
        attachments={attachments}
        handlePickFiles={handlePickFiles}
        fileInputRef={fileInputRef}
        handleFilesSelected={handleFilesSelected}
        composerText={composerText}
        setComposerText={setComposerText}
        handleSendComposer={handleSendComposer}
        handleRemoveAttachment={handleRemoveAttachment}
        isTalking={isTalking}
        handleToggleTalk={handleToggleTalk}
      />

      <OutputPanel
        leftFullscreen={leftFullscreen}
        volume={volume}
        state={state}
        handleFrame={handleFrame}
        Visualizer={Visualizer}
        CameraFeed={CameraFeed}
        activeRightPanel={activeRightPanel}
        setActiveRightPanel={setActiveRightPanel}
        activeMedia={activeMedia}
        seqNotes={seqNotes}
        setSeqNotes={setSeqNotes}
        seqCompletedNotes={seqCompletedNotes}
        setSeqCompletedNotes={setSeqCompletedNotes}
        seqNextText={seqNextText}
        seqNextIndex={seqNextIndex}
        seqTemplate={seqTemplate}
        seqError={seqError}
        seqBusy={seqBusy}
        handleSeqSuggest={handleSeqSuggest}
        handleSeqApply={handleSeqApply}
        handleSeqApplyByText={handleSeqApplyByText}
        handleSeqApplyAll={handleSeqApplyAll}
        liveServiceCurrent={liveService.current}
        activeOutputTab={activeOutputTab}
        setActiveOutputTab={setActiveOutputTab}
        outputScrollRef={outputScrollRef}
        outputStickToBottomRef={outputStickToBottomRef}
        outputChat={outputChat as any}
        uiLogText={uiLogText}
        loadUiLogFromLocalStorage={loadUiLogFromLocalStorage}
        setUiLogText={setUiLogText}
        wsLogErr={wsLogErr}
        wsLogText={wsLogText}
        refreshWsLog={refreshWsLog}
        pendingErr={pendingErr}
        pendingActionBusy={pendingActionBusy}
        pendingItems={pendingItems}
        pendingSelectedId={pendingSelectedId}
        pendingPreview={pendingPreview}
        pendingAuthCode={pendingAuthCode}
        setPendingAuthCode={setPendingAuthCode}
        pendingActionResult={pendingActionResult}
        queueGoogleRelink={queueGoogleRelink}
        refreshPending={refreshPending}
        queueBundlePublishReload={queueBundlePublishReload}
        previewPending={previewPending}
        confirmPending={confirmPending}
        cancelPending={cancelPending}
        copyPendingJson={copyPendingJson}
      />
    </div>
  );
}