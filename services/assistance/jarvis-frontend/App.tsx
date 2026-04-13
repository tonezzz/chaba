import React, { useState, useEffect, useRef, useCallback } from 'react';
import { sequentialApplyAndSuggest } from './services/sequentialService';
import { ConnectionState, MessageLog, WsReadinessEvent } from './types';
import { useFullscreenEscape } from './hooks/useFullscreenEscape';
import { useAutoScroll } from './hooks/useAutoScroll';
import { useUiLog } from './hooks/useUiLog';
import { usePending } from './hooks/usePending';
import { useMessageLog } from './hooks/useMessageLog';
import { useLiveService } from './hooks/useLiveService';
import { useSystemCounts } from './hooks/useSystemCounts';
import { useAudioStatus } from './hooks/useAudioStatus';
import { useOutputDialog } from './hooks/useOutputDialog';
import { useComposer } from './hooks/useComposer';

import Visualizer from './components/Visualizer';
import CameraFeed from './components/CameraFeed';
import { LeftPanel } from './components/app/LeftPanel';
import { OutputPanel } from './components/app/OutputPanel';
import { Lock, ChevronRight, HeartPulse, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

export default function App() {
  const [hasKey, setHasKey] = useState(false);
  const [state, setState] = useState<ConnectionState>(ConnectionState.DISCONNECTED);
  const [volume, setVolume] = useState(0);

  // UI state
  const [statusDetailsOpen, setStatusDetailsOpen] = useState<boolean>(() => {
    try {
      const raw = String(window.localStorage.getItem("jarvis_status_details_open") || "").trim();
      return raw === "1" || raw.toLowerCase() === "true";
    } catch {
      return false;
    }
  });
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [showDebugLogs, setShowDebugLogs] = useState(false);
  const showDebugLogsRef = useRef<boolean>(false);
  const [leftFullscreen, setLeftFullscreen] = useState(false);
  const [activeRightPanel, setActiveRightPanel] = useState<"output" | "cars" | "checklist">("output");
  const [activeOutputTab, setActiveOutputTab] = useState<"dialog" | "ui_log" | "ws_log" | "pending">("dialog");

  // Sequential task state
  const [seqNotes, setSeqNotes] = useState<string>("");
  const [seqCompletedNotes, setSeqCompletedNotes] = useState<string>("");
  const [seqNextText, setSeqNextText] = useState<string | null>(null);
  const [seqNextIndex, setSeqNextIndex] = useState<number | null>(null);
  const [seqTemplate, setSeqTemplate] = useState<string[] | null>(null);
  const [seqError, setSeqError] = useState<string>("");
  const [seqBusy, setSeqBusy] = useState<boolean>(false);

  // Readiness state
  const [readinessPhase, setReadinessPhase] = useState<string>("");
  const [readinessSinceMs, setReadinessSinceMs] = useState<number>(0);
  const readinessPhaseRef = useRef<string>("");

  // Container status state
  const [containerStatus, setContainerStatus] = useState<any>(null);
  const [containerStatusError, setContainerStatusError] = useState<string>("");
  const [depsStatus, setDepsStatus] = useState<any>(null);
  const [depsStatusError, setDepsStatusError] = useState<string>("");
  const [depsStatusRefreshNonce, setDepsStatusRefreshNonce] = useState<number>(0);

  // UI card input state
  const [uiCardInputByMsgId, setUiCardInputByMsgId] = useState<Record<string, string>>({});

  // Refs for scrolling
  const logScrollRef = useRef<HTMLDivElement | null>(null);
  const logStickToBottomRef = useRef<boolean>(true);
  const outputScrollRef = useRef<HTMLDivElement | null>(null);
  const outputStickToBottomRef = useRef<boolean>(true);

  // Backend candidates helper
  const backendCandidates = useCallback((): string[] => {
    const override = String((import.meta as any).env?.VITE_JARVIS_HTTP_URL as string | undefined || "").trim();
    let normOverride = override ? override.trim().replace(/\/+$/, "").replace(/^\s+|\s+$/g, "") : "";
    const isJarvisSubpath = location.pathname.startsWith("/jarvis");
    const defaults = ["/jarvis/api"];
    const out = normOverride ? [normOverride, ...defaults] : defaults;

    const seen = new Set<string>();
    return out.filter((v) => {
      const k = String(v || "");
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }, []);

  // UI Log hook
  const { uiLogText, setUiLogText, loadUiLogFromLocalStorage, appendUiLogEntry, scheduleUiLogFlush } = useUiLog({
    backendCandidates,
  });

  // LiveService ref (declared early for usePending)
  const liveServiceRef = useRef<import("./services/liveService").LiveService | null>(null);

  // Pending actions hook
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
    liveService: liveServiceRef,
    setActiveRightPanel,
    setActiveOutputTab,
  });

  // Readiness handler
  const handleReadiness = useCallback((ev: WsReadinessEvent) => {
    try {
      const phase = String(ev?.phase || "").trim();
      if (!phase) return;
      readinessPhaseRef.current = phase;
      setReadinessPhase(phase);
      setReadinessSinceMs((prev) => (prev ? prev : typeof ev?.ts === "number" ? ev.ts : Date.now()));
    } catch {
      // ignore
    }
  }, []);

  // Message log hook
  const {
    messages,
    setMessages,
    resumeHydratedRef,
    lastActivityTextRef,
    lastActivityTsRef,
    activeMedia,
    setActiveMedia,
    handleMessage,
  } = useMessageLog({
    appendUiLogEntry,
    scheduleUiLogFlush,
    readinessPhaseRef,
    showDebugLogsRef,
  });

  // Derived state hooks
  const systemCounts = useSystemCounts(messages);
  const audioStatus = useAudioStatus(messages, state);
  const { outputDialog, outputChat } = useOutputDialog(messages);

  // LiveService hook
  const { liveService, handleConnect } = useLiveService({
    hasKey,
    onMessage: handleMessage,
    onReadiness: handleReadiness,
    onPendingEvent: useCallback((ev) => {
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
    }, [refreshPending, previewPending]),
    onCarsIngestResult: useCallback((ev) => {
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
    }, [setMessages]),
    setState,
    setVolume,
    setActiveRightPanel,
    setActiveOutputTab,
    refreshPending,
    previewPending,
  });


  // Composer hook
  const [attachments, setAttachments] = useState<
    Array<{ id: string; name: string; size: number; kind: "image" | "pdf" | "text"; text?: string }>
  >([]);

  const {
    composerText,
    setComposerText,
    handleSendComposer,
    handlePickFiles,
    handleFilesSelected,
    handleRemoveAttachment,
    fileInputRef,
  } = useComposer({
    liveService,
    state,
    setMessages,
    setAttachments,
    attachments,
    setActiveRightPanel,
    setActiveOutputTab,
    refreshPending,
  });

  // Talking state
  const [isTalking, setIsTalking] = useState(false);
  const handleToggleTalk = useCallback(() => {
    if (state !== ConnectionState.CONNECTED) return;
    if (!isTalking) {
      liveService.current?.startStreaming();
      setIsTalking(true);
    } else {
      liveService.current?.stopStreaming();
      setIsTalking(false);
    }
  }, [state, isTalking, liveService]);

  // Camera frame handler
  const handleFrame = useCallback((base64: string) => {
    liveService.current?.updateCameraFrame(base64);
  }, [liveService]);

  // Copy text helper
  const copyText = useCallback(async (text: string) => {
    const t = String(text || "");
    if (!t) return;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(t);
        return;
      }
    } catch {
      // ignore
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
      // ignore
    }
  }, []);

  // Client label helper
  const clientLabelForMsg = useCallback((m: MessageLog): string => {
    const tag = String((m.metadata as any)?.ws?.client_tag || "").trim();
    const id = String((m.metadata as any)?.ws?.client_id || "").trim();
    const suffix = id ? id.slice(-6) : "";
    if (tag && suffix) return `${tag}:${suffix}`;
    if (tag) return tag;
    if (suffix) return suffix;
    return "";
  }, []);

  // Check API key on mount
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

  // Reset readiness on disconnect
  useEffect(() => {
    if (state !== ConnectionState.CONNECTED) {
      readinessPhaseRef.current = "";
      setReadinessPhase("");
      setReadinessSinceMs(0);
    }
  }, [state]);

  // Show disconnect context
  const prevConnStateRef = useRef<ConnectionState>(ConnectionState.DISCONNECTED);
  useEffect(() => {
    const prev = prevConnStateRef.current;
    prevConnStateRef.current = state;
    if (prev !== ConnectionState.CONNECTED) return;
    if (state !== ConnectionState.DISCONNECTED && state !== ConnectionState.ERROR) return;

    try {
      const activity = String(lastActivityTextRef.current || "").trim();
      const activityAgeMs = lastActivityTsRef.current ? Date.now() - lastActivityTsRef.current : Number.POSITIVE_INFINITY;
      const activityOk = !!activity && Number.isFinite(activityAgeMs) && activityAgeMs >= 0 && activityAgeMs <= 45000;
      const suffix = activityOk ? ` (was: ${activity})` : "";
      setMessages((prevMsgs) => [
        ...prevMsgs,
        {
          id: `${Date.now()}_disconnect_context_${Math.random().toString(16).slice(2)}`,
          role: "system",
          text: `${state}${suffix}`,
          timestamp: new Date(),
        },
      ]);
    } catch {
      // ignore
    }
  }, [state, setMessages]);

  // Auto scroll
  useAutoScroll(logScrollRef, logStickToBottomRef, [messages, showDebugLogs]);
  useAutoScroll(outputScrollRef, outputStickToBottomRef, [outputDialog]);

  // Persist status details open
  useEffect(() => {
    try {
      window.localStorage.setItem("jarvis_status_details_open", statusDetailsOpen ? "1" : "0");
    } catch {
      // ignore
    }
  }, [statusDetailsOpen]);

  // Update showDebugLogs ref
  useEffect(() => {
    showDebugLogsRef.current = !!showDebugLogs;
  }, [showDebugLogs]);

  // Reset talking state on disconnect
  useEffect(() => {
    if (state !== ConnectionState.CONNECTED && isTalking) {
      setIsTalking(false);
    }
  }, [state, isTalking]);

  // Fullscreen escape
  useFullscreenEscape(leftFullscreen, setLeftFullscreen);

  // Sequential task handlers
  const getSeqCompletedTasks = useCallback((): Array<{ notes?: string }> => {
    const raw = String(seqCompletedNotes || "").trim();
    if (!raw) return [];
    return [{ notes: raw }];
  }, [seqCompletedNotes]);

  const applySeqResponse = useCallback(
    (res: any) => {
      if (!res || res.ok === false) {
        setSeqError(String(res?.error || "sequential_failed"));
        return;
      }
      if (typeof res.notes === "string") setSeqNotes(res.notes);
      setSeqNextText(res.next_step_text != null ? String(res.next_step_text) : null);
      setSeqNextIndex(res.next_step_index != null ? Number(res.next_step_index) : null);
      setSeqTemplate(Array.isArray(res.template) ? res.template.map((v: any) => String(v)) : null);
    },
    [setSeqError, setSeqNotes, setSeqNextText, setSeqNextIndex, setSeqTemplate]
  );

  const handleSeqSuggest = useCallback(async () => {
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
  }, [applySeqResponse, getSeqCompletedTasks, seqNotes]);

  const handleSeqApply = useCallback(async () => {
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
  }, [applySeqResponse, getSeqCompletedTasks, seqNotes, seqNextIndex]);

  const handleSeqApplyByText = useCallback(async () => {
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
  }, [applySeqResponse, getSeqCompletedTasks, seqNotes, seqNextText]);

  const handleSeqApplyAll = useCallback(async () => {
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
  }, [applySeqResponse, getSeqCompletedTasks, seqNotes]);

  // WS Log fetch
  const [wsLogText, setWsLogText] = useState<string>("");
  const [wsLogErr, setWsLogErr] = useState<string>("");
  const refreshWsLog = useCallback(async () => {
    setWsLogErr("");
    for (const base of backendCandidates()) {
      try {
        const effectiveBase = base ? base : "/jarvis/api";
        const res = await fetch(`${effectiveBase}/logs/ws/today?max_bytes=200000`, { method: "GET" });
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

  // Container status fetch
  useEffect(() => {
    if (hasKey) return;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        setContainerStatusError("");
        const joinUrl = (base: string, path: string): string => {
          const b = String(base || "").replace(/\/+$/, "");
          let p = String(path || "");
          if (!b) return p;
          if (b.endsWith("/api") && p.startsWith("/api/")) p = p.slice("/api".length);
          if (b.endsWith("/jarvis") && p.startsWith("/jarvis/")) p = p.slice("/jarvis".length);
          if (b.endsWith("/jarvis/api") && p.startsWith("/jarvis/api/")) p = p.slice("/jarvis/api".length);
          return `${b}${p}`;
        };

        const pathsToTry = ["/status"];
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
              const ct = String(attempt.headers.get("content-type") || "").toLowerCase();
              const bodyText = await attempt.text();
              const trimmed = String(bodyText || "").trim();
              if (!trimmed) {
                lastErr = `status_error: empty response (http ${attempt.status})`;
                continue;
              }
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

  // Deps status fetch
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
          throw new Error(`status_http_${res ? res.status : "fetch_failed"}`);
        }
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

  // Select key handler
  const handleSelectKey = useCallback(async () => {
    if ((window as any).aistudio) {
      try {
        await (window as any).aistudio.openSelectKey();
      } catch (e) {
        console.error("Key selection failed", e);
      }
    }
    setHasKey(true);
  }, []);

  // Auth gate
  if (!hasKey) {
    // Status icon helpers
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
        readinessPhase={readinessPhase}
        readinessSinceMs={readinessSinceMs}
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
