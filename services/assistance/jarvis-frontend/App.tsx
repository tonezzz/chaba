import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
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
  const [activeRightPanel, setActiveRightPanel] = useState<"output" | "cars" | "checklist">("output");
  const [activeOutputTab, setActiveOutputTab] = useState<"dialog" | "ui_log" | "ws_log">("dialog");
  const [uiLogText, setUiLogText] = useState<string>("");
  const [wsLogText, setWsLogText] = useState<string>("");
  const [wsLogErr, setWsLogErr] = useState<string>("");
  const uiLogPendingRef = useRef<Array<{ ts: number; entry: any }>>([]);
  const uiLogFlushTimerRef = useRef<number | null>(null);
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

  const todayLocalYmd = useCallback((): string => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${dd}`;
  }, []);

  const uiLogStorageKey = useCallback((): string => {
    return `jarvis_ui_log_${todayLocalYmd()}`;
  }, [todayLocalYmd]);

  const loadUiLogFromLocalStorage = useCallback((): string => {
    try {
      return String(window.localStorage.getItem(uiLogStorageKey()) || "");
    } catch {
      return "";
    }
  }, [uiLogStorageKey]);

  const persistUiLogLine = useCallback((line: string) => {
    const s = String(line || "");
    if (!s) return;
    try {
      const k = uiLogStorageKey();
      const prev = String(window.localStorage.getItem(k) || "");
      const next = prev ? `${prev}\n${s}` : s;
      window.localStorage.setItem(k, next);
      setUiLogText(next);
    } catch {
      // ignore
    }
  }, [uiLogStorageKey]);

  const appendUiLogEntry = useCallback((msg: MessageLog) => {
    try {
      const ts = msg.timestamp?.getTime?.() ? msg.timestamp.getTime() : Date.now();
      const safeRaw = msg.metadata?.raw != null ? msg.metadata.raw : undefined;
      const entry = {
        ts,
        id: String(msg.id || ""),
        role: msg.role,
        text: String(msg.text || ""),
        metadata: {
          severity: msg.metadata?.severity,
          category: msg.metadata?.category,
          source: msg.metadata?.source,
          trace_id: msg.metadata?.trace_id,
          ws: msg.metadata?.ws,
          raw: safeRaw,
        },
      };
      persistUiLogLine(JSON.stringify(entry));
      uiLogPendingRef.current.push({ ts, entry });
    } catch {
      // ignore
    }
  }, [persistUiLogLine]);

  const backendCandidates = useCallback((): string[] => {
    const isJarvisSubpath = location.pathname.startsWith("/jarvis");
    return isJarvisSubpath
      ? ["/jarvis/logs"]
      : ["/logs", "/jarvis/logs"];
  }, []);

  const flushUiLogToBackend = useCallback(async () => {
    const pending = uiLogPendingRef.current;
    if (!pending.length) return;
    const batch = pending.splice(0, 100);
    const entries = batch.map((b) => b.entry);
    for (const base of backendCandidates()) {
      try {
        const res = await fetch(`${base}/ui/append`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ entries }),
        });
        if (res.ok) return;
      } catch {
        // try next
      }
    }
    // Failed to send; put back (best-effort)
    uiLogPendingRef.current = [...entries.map((entry) => ({ ts: Date.now(), entry })), ...uiLogPendingRef.current];
  }, [backendCandidates]);

  const scheduleUiLogFlush = useCallback(() => {
    if (uiLogFlushTimerRef.current != null) return;
    uiLogFlushTimerRef.current = window.setTimeout(() => {
      uiLogFlushTimerRef.current = null;
      void flushUiLogToBackend();
    }, 1500);
  }, [flushUiLogToBackend]);

  const refreshWsLog = useCallback(async () => {
    setWsLogErr("");
    for (const base of backendCandidates()) {
      try {
        const res = await fetch(`${base}/ws/today?max_bytes=200000`, { method: "GET" });
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

  useEffect(() => {
    // Load today's persisted UI log into the UI (without polluting the WS message list).
    const txt = loadUiLogFromLocalStorage();
    if (txt) setUiLogText(txt);
  }, [loadUiLogFromLocalStorage]);

  useEffect(() => {
    return () => {
      try {
        if (uiLogFlushTimerRef.current != null) {
          window.clearTimeout(uiLogFlushTimerRef.current);
          uiLogFlushTimerRef.current = null;
        }
      } catch {
      }
    };
  }, []);

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

    const splitSentences = (text: string): Array<{ t: string; complete: boolean }> => {
      const raw = String(text || "").replace(/\r\n/g, "\n");
      const parts = raw.split(/\n+/g);
      const out: Array<{ t: string; complete: boolean }> = [];
      for (const p of parts) {
        const s = String(p || "").trim();
        if (!s) continue;
        // Basic multilingual sentence splitter.
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
    };

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

  useEffect(() => {
    try {
      window.localStorage.setItem("jarvis_status_details_open", statusDetailsOpen ? "1" : "0");
    } catch {
    }
  }, [statusDetailsOpen]);

  useEffect(() => {
    // Auto-open the details once per session when we connect (helps with quick visibility),
    // but keep respecting user preference after that.
    if (state === ConnectionState.CONNECTED) {
      try {
        const seen = String(window.sessionStorage.getItem("jarvis_status_details_autoshown") || "").trim();
        if (!seen) {
          window.sessionStorage.setItem("jarvis_status_details_autoshown", "1");
          setStatusDetailsOpen(true);
        }
      } catch {
      }
    }
  }, [state]);

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
    liveService.current.onCarsIngestResult = (ev) => {
      setMessages((prev) => [
        {
          id: `${Date.now()}_cars_ingest_${Math.random().toString(16).slice(2)}`,
          role: "system",
          text: `cars_ingest_result ok=${String((ev as any)?.ok)} items=${Array.isArray((ev as any)?.items) ? (ev as any).items.length : 0}`,
          timestamp: new Date(),
        },
        ...prev,
      ]);
      setActiveRightPanel("cars");
    };
    liveService.current.onMessage = (msg) => {
      try {
        appendUiLogEntry(msg);
        scheduleUiLogFlush();
      } catch {
      }
      setMessages((prev) => {
        const isWsClose = msg.id.includes('_ws_close') || String(msg.text || '').toLowerCase().startsWith('disconnected');
        const isWsConnErr = msg.id.includes('_ws_error') || String(msg.text || '').toLowerCase() === 'connection_error';

        if (isWsClose || isWsConnErr) {
          const withoutSticky = prev.filter((m) => m.id !== "sticky_progress");
          // Keep only the newest connection error/close indicator.
          const cleaned = withoutSticky.filter((m) => {
            if (isWsClose && (m.id.includes('_ws_close') || String(m.text || '').toLowerCase().startsWith('disconnected'))) return false;
            if (isWsConnErr && (m.id.includes('_ws_error') || String(m.text || '').toLowerCase() === 'connection_error')) return false;
            return true;
          });
          return [msg, ...cleaned];
        }

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
    const el = logScrollRef.current;
    if (!el) return;
    if (!logStickToBottomRef.current) return;
    try {
      el.scrollTop = el.scrollHeight;
    } catch {
      // ignore
    }
  }, [messages, showDebugLogs]);

  useEffect(() => {
    const el = outputScrollRef.current;
    if (!el) return;
    if (!outputStickToBottomRef.current) return;
    try {
      el.scrollTop = el.scrollHeight;
    } catch {
      // ignore
    }
  }, [outputDialog]);

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
		const normalized = String(base || "")
			.replace(/[\u00A0\u200B-\u200D\uFEFF]/g, "")
			.replace(/\s+/g, " ")
			.trim();

		const parseSysSet = (raw: string): { key: string; value: string; dryRun: boolean } | null => {
			const s = String(raw || "")
				.replace(/[\u00A0\u200B-\u200D\uFEFF]/g, "")
				.replace(/\s+/g, " ")
				.trim();
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
		};

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

		if (normalized.toLowerCase() === "system clear job" || normalized.toLowerCase() === "sys clear job") {
			liveService.current?.sendSystemClearJob();
			setComposerText("");
			setAttachments([]);
			return;
		}

		// Never send slash-commands to Gemini; handle locally to avoid confusing "task not found" replies.
		if (normalized.startsWith("/")) {
			const s2 = normalized.toLowerCase();
			if (s2 === "/system clear job" || s2 === "/sys clear job" || s2 === "/system clear" || s2 === "/sys clear") {
				liveService.current?.sendSystemClearJob();
				setComposerText("");
				setAttachments([]);
				return;
			}
			setComposerText("");
			setAttachments([]);
			setMessages((prev) => [
				...prev,
				{
					id: `${Date.now()}_slash_unknown`,
					role: "system",
					text: `unknown_command: ${normalized}`,
					timestamp: new Date(),
					metadata: { severity: "info", category: "ws" },
				},
			]);
			return;
		}

    const extractReminderAddText = (text: string): string | null => {
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
    };

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

    const extractSystemReloadMode = (text: string): "full" | "memory" | "knowledge" | "sys" | "gems" => {
      const s = String(text || "").trim().toLowerCase();
      const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
      const has = (w: string) => compact.includes(w);
      if (has("gems") || has("gem") || has("models") || has("model") || has("เจม") || has("โมเดล")) return "gems";
      if (has("knowledge") || has("kb") || has("know") || has("ความรู้")) return "knowledge";
      if (has("memory") || has("mem") || has("เมม") || has("เมมโม")) return "memory";
      return "full";
    };

    if (base && isReloadSystemPhrase(base)) {
      const mode = extractSystemReloadMode(base);
      liveService.current?.sendSystemReload(mode);
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

    const isGemsListPhrase = (text: string): boolean => {
      const s = String(text || "").trim().toLowerCase();
      if (!s) return false;
      const compact = s.replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ").trim().replace(/\s+/g, " ");
      if (!compact) return false;
      if (compact === "gems" || compact === "list gems" || compact === "gems list") return true;
      if (compact === "models" || compact === "list models" || compact === "models list") return true;
      if (compact.includes("list gems") || compact.includes("gems list")) return true;
      if (compact.includes("list models") || compact.includes("models list")) return true;
      if ((compact.includes("ลิส") || compact.includes("รายการ") || compact.includes("ดู")) && (compact.includes("เจม") || compact.includes("โมเดล") || compact.includes("รุ่น"))) return true;
      return false;
    };

    const extractGemsRemoveId = (text: string): string | null => {
      const raw = String(text || "").trim();
      if (!raw) return null;
      const m = raw.match(/^gems\s+(?:remove|delete)\s*[:\-]?\s*(.+)$/i);
      if (m && String(m[1] || "").trim()) return String(m[1]).trim();
      const m2 = raw.match(/^ลบ\s*(?:เจม|โมเดล)\s*[:\-]?\s*(.+)$/);
      if (m2 && String(m2[1] || "").trim()) return String(m2[1]).trim();
      return null;
    };

    const extractGemsUpsertJson = (text: string): any | null => {
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
    };

    const extractGemsCreateId = (text: string): string | null => {
      const raw = String(text || "").trim();
      if (!raw) return null;
      // Support: "gems create noble-a-unit" (without JSON payload)
      const m = raw.match(/^gems\s+create\s+([a-z0-9_-]+)\s*$/i);
      if (m && String(m[1] || "").trim()) return String(m[1]).trim();
      const m2 = raw.match(/^สร้าง\s*(?:เจม|โมเดล)\s+([a-z0-9_-]+)\s*$/i);
      if (m2 && String(m2[1] || "").trim()) return String(m2[1]).trim();
      return null;
    };

    const extractGemsAnalyze = (text: string): { gem_id: string; criteria: string } | null => {
      const raw = String(text || "").trim();
      if (!raw) return null;
      const m = raw.match(/^gems\s+analy[sz]e\s+([a-z0-9_-]+)(?:\s*(?::|\s-\s)\s*(.+))?$/i);
      if (m && String(m[1] || "").trim()) return { gem_id: String(m[1]).trim(), criteria: String(m[2] || "").trim() };
      const m2 = raw.match(/^วิเคราะห์\s*(?:เจม|โมเดล)\s+([a-z0-9_-]+)(?:\s*(?::|\s-\s)\s*(.+))?$/i);
      if (m2 && String(m2[1] || "").trim()) return { gem_id: String(m2[1]).trim(), criteria: String(m2[2] || "").trim() };
      return null;
    };

    const extractGemsDraftAction = (text: string): { action: "apply" | "discard"; draft_id: string } | null => {
      const raw = String(text || "").trim();
      if (!raw) return null;
      const m = raw.match(/^gems\s+draft\s+(apply|discard)\s*[:\-]?\s*(\w+)$/i);
      if (m && String(m[2] || "").trim()) return { action: String(m[1]).toLowerCase() === "apply" ? "apply" : "discard", draft_id: String(m[2]).trim() };
      const m2 = raw.match(/^ยืนยัน\s*ดราฟท์\s*[:\-]?\s*(\w+)$/);
      if (m2 && String(m2[1] || "").trim()) return { action: "apply", draft_id: String(m2[1]).trim() };
      const m3 = raw.match(/^ยกเลิก\s*ดราฟท์\s*[:\-]?\s*(\w+)$/);
      if (m3 && String(m3[1] || "").trim()) return { action: "discard", draft_id: String(m3[1]).trim() };
      return null;
    };

    if (base && isGemsListPhrase(base)) {
      liveService.current?.sendGemsList();
      setComposerText("");
      setAttachments([]);
      return;
    }

    const gemRemoveId = base ? extractGemsRemoveId(base) : null;
    if (gemRemoveId) {
      liveService.current?.sendGemsRemove(gemRemoveId);
      setComposerText("");
      setAttachments([]);
      return;
    }

    const gemUpsert = base ? extractGemsUpsertJson(base) : null;
    if (gemUpsert) {
      liveService.current?.sendGemsUpsert(gemUpsert);
      setComposerText("");
      setAttachments([]);
      return;
    }

    const gemCreateId = base ? extractGemsCreateId(base) : null;
    if (gemCreateId) {
      liveService.current?.sendGemsUpsert({ id: gemCreateId, name: gemCreateId });
      setComposerText("");
      setAttachments([]);
      return;
    }

    const gemAnalyze = base ? extractGemsAnalyze(base) : null;
    if (gemAnalyze) {
      liveService.current?.sendGemsAnalyze(gemAnalyze.gem_id, gemAnalyze.criteria);
      setComposerText("");
      setAttachments([]);
      return;
    }

    const gemDraft = base ? extractGemsDraftAction(base) : null;
    if (gemDraft) {
      if (gemDraft.action === "apply") liveService.current?.sendGemsDraftApply(gemDraft.draft_id);
      else liveService.current?.sendGemsDraftDiscard(gemDraft.draft_id);
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

  useEffect(() => {
    if (hasKey) return;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        setContainerStatusError("");
        let res: Response | null = null;
        try {
          res = await fetch("/jarvis/status", { cache: "no-store" });
        } catch {
          res = null;
        }
        if (!res || !res.ok) {
          res = await fetch("/status", { cache: "no-store" });
        }
        const js = await res.json();
        if (!cancelled) setContainerStatus(js);
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
  }, [hasKey]);

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

           <div className="mt-6 text-left text-xs font-mono text-slate-400 border-t border-slate-700/60 pt-4">
             <div className="text-[10px] text-cyan-500 font-hud tracking-widest uppercase mb-2">Container Status</div>
             {containerStatusError ? (
               <div className="text-red-400">status_error: {containerStatusError}</div>
             ) : containerStatus ? (
               <div className="space-y-1">
                 <div>instance_id: {String(containerStatus.instance_id || "")}</div>
                 <div>hostname: {String(containerStatus.hostname || "")}</div>
                 <div>uptime_s: {typeof containerStatus.uptime_s === "number" ? containerStatus.uptime_s.toFixed(0) : String(containerStatus.uptime_s || "")}</div>
                 {containerStatus.startup_prewarm && (
                   <div>
                     prewarm: {containerStatus.startup_prewarm.running ? "running" : containerStatus.startup_prewarm.ok ? "ok" : containerStatus.startup_prewarm.error ? "error" : "pending"}
                     {containerStatus.startup_prewarm.ok ? ` (memory=${containerStatus.startup_prewarm.memory_n} knowledge=${containerStatus.startup_prewarm.knowledge_n})` : ""}
                   </div>
                 )}
               </div>
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
      <div className="w-full md:w-1/3 lg:w-1/4 p-4 md:p-6 flex flex-col gap-6 z-10 bg-slate-900/80 backdrop-blur-md border-r border-slate-800 overflow-hidden h-[100dvh]">
        <header>
          <h1 className="text-4xl font-bold font-hud text-cyan-400 tracking-tighter mb-1">JARVIS</h1>
          <p className="text-xs text-cyan-600 font-mono uppercase tracking-[0.2em]">Live Interface System</p>
        </header>
        
        <div className="flex-1 flex flex-col gap-4 min-h-0">
          {/* Connection Status */}
          <div className={`p-3 rounded-lg border ${state === ConnectionState.CONNECTED ? 'border-cyan-500/30 bg-cyan-950/20' : 'border-red-500/30 bg-red-950/20'} transition-colors duration-500`}>
             <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs font-mono text-slate-400 uppercase whitespace-nowrap">System</span>
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
                          ? 'bg-cyan-400 animate-pulse'
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

                <button
                  onClick={() => setStatusDetailsOpen((v) => !v)}
                  className="shrink-0 ml-2 w-8 h-8 rounded-lg border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 flex items-center justify-center"
                  title={statusDetailsOpen ? "Hide status details" : "Show status details"}
                  aria-label={statusDetailsOpen ? "Hide status details" : "Show status details"}
                >
                  <ChevronRight className={`w-4 h-4 transition-transform ${statusDetailsOpen ? "rotate-90" : ""}`} />
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
                   className="px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-950/40 text-xs font-mono disabled:opacity-50"
                 >
                   {state === ConnectionState.CONNECTING ? "Connecting..." : "Connect"}
                 </button>
               )}
             </div>

             {statusDetailsOpen && (
               <div className="flex items-center justify-between mt-2 gap-2">
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
                       ? 'border-cyan-500/30 bg-cyan-950/10 text-cyan-200'
                       : 'border-slate-700 bg-slate-950/20 text-slate-300'
                   }`}
                   title={audioStatus.ok ? 'audio_ok' : 'audio_unavailable'}
                 >
                   {audioStatus.ok ? <Mic className="w-3 h-3" /> : <MicOff className="w-3 h-3" />}
                   audio
                 </span>
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
             <div className="text-xs font-mono text-slate-500 uppercase tracking-widest sticky top-0 bg-slate-900/90 py-1 mb-2 flex items-center justify-between">
               <span>Operation Log</span>
              <div className="flex items-center gap-2">
                <button
                  className="text-[10px] font-mono text-slate-600 hover:text-slate-400 normal-case"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const visible = (showDebugLogs ? messages : messages.filter((m) => (m.metadata?.severity || "info") !== "debug"));
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
               const ordered = visible
                 .slice()
                 .sort((a, b) => {
                   const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
                   const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
                   if (ta !== tb) return ta - tb;
                   return String(a.id || "").localeCompare(String(b.id || ""));
                 });
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
               const filtered = ordered.filter((m) => {
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
                      {clientLabelForMsg(m) && (
                        <span className="text-[10px] text-slate-600 font-mono">[{clientLabelForMsg(m)}]</span>
                      )}
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
                          void copyText(`[${ts}] ${tagText}${role}: ${txt}`);
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
      <div className="flex-1 p-4 md:p-6 flex flex-col gap-4 relative z-10 min-h-0 overflow-hidden">
         
         {/* Top Section: Visualizer & Camera */}
         <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-none h-[64px] min-h-[64px] max-h-[64px]">
            {/* Audio Visualizer */}
            <div className="relative rounded-2xl border border-slate-700 bg-slate-900/50 flex items-center justify-center overflow-hidden">
               <div className="absolute top-3 left-4 text-[10px] text-cyan-500 font-hud tracking-widest uppercase">Audio Input Matrix</div>
               <div className="h-full aspect-square max-w-full">
                 <Visualizer volume={volume} active={state === ConnectionState.CONNECTED} />
               </div>
            </div>

            {/* Camera Feed */}
            <div className="relative rounded-2xl border border-slate-700 bg-slate-900/50 flex items-center justify-center p-1 overflow-hidden">
               <div className="absolute top-2 left-3 text-[10px] text-cyan-500 font-hud tracking-widest uppercase z-10">&nbsp;</div>
               <div className="w-full h-full flex items-center justify-center overflow-hidden">
                 <div className="h-full aspect-video max-w-full">
                   <CameraFeed active={state === ConnectionState.CONNECTED} onFrame={handleFrame} />
                 </div>
                 {!state && <div className="absolute inset-0 flex items-center justify-center text-slate-600 font-mono text-sm">System Offline</div>}
               </div>
            </div>
         </div>

         {/* Bottom Section: Media Output */}
         <div className="flex-1 rounded-2xl border border-slate-700 bg-slate-900/50 p-6 relative overflow-hidden min-h-0 flex flex-col">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-cyan-500/50 to-transparent"></div>
            <div className="flex items-center justify-between gap-3">
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
            
            <div className="flex-1 w-full flex flex-col mt-4 min-h-0">
               {activeRightPanel === "cars" ? (
                 <div className="w-full h-full min-h-0 overflow-auto">
                   <CarsPanel liveService={liveService.current} connectionState={state} />
                 </div>
               ) : activeRightPanel === "checklist" ? (
                 <div className="w-full h-full min-h-0 overflow-auto">
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
               ) : (
                 <div className="w-full flex-1 min-h-0 flex flex-col animate-in zoom-in-95 duration-500">
                   {activeMedia?.metadata?.image && (
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
                   {activeMedia?.metadata?.sources && (
                     <div className="w-full bg-slate-800/50 rounded-lg border border-slate-700 p-4 overflow-auto">
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
                   {!activeMedia?.metadata?.image && !activeMedia?.metadata?.sources && (
                     <div
                       ref={outputScrollRef}
                       className="w-full bg-slate-950/40 rounded-lg border border-slate-700 p-4 overflow-auto flex-1 min-h-0"
                       onScroll={(e) => {
                         const el = e.currentTarget;
                         const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
                         outputStickToBottomRef.current = remaining < 40;
                       }}
                     >
                       <div className="flex items-center justify-between mb-2">
                         <div className="flex items-center gap-2">
                           <button
                             onClick={() => setActiveOutputTab("dialog")}
                             className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                               activeOutputTab === "dialog"
                                 ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                                 : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                             }`}
                           >
                             Dialog
                           </button>
                           <button
                             onClick={() => setActiveOutputTab("ui_log")}
                             className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                               activeOutputTab === "ui_log"
                                 ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                                 : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                             }`}
                           >
                             UI Log
                           </button>
                           <button
                             onClick={() => {
                               setActiveOutputTab("ws_log");
                               void refreshWsLog();
                             }}
                             className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                               activeOutputTab === "ws_log"
                                 ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                                 : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                             }`}
                           >
                             Backend WS Log
                           </button>
                         </div>
                         <div className="flex items-center gap-2">
                           {activeOutputTab === "ui_log" && (
                             <button
                               onClick={() => {
                                 const txt = loadUiLogFromLocalStorage();
                                 setUiLogText(txt);
                               }}
                               className="text-[11px] font-mono px-3 py-1 rounded-lg border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                             >
                               refresh
                             </button>
                           )}
                           {activeOutputTab === "ws_log" && (
                             <button
                               onClick={() => void refreshWsLog()}
                               className="text-[11px] font-mono px-3 py-1 rounded-lg border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                             >
                               refresh
                             </button>
                           )}
                         </div>
                       </div>

                       {activeOutputTab === "dialog" ? (
                        <div className="flex flex-col gap-4">
                          {outputDialog.length === 0 ? (
                            <div className="text-slate-600 font-mono text-sm">(no text yet)</div>
                          ) : (
                            outputDialog.map((d) => (
                              <div key={d.id} className="text-slate-100 font-mono text-sm whitespace-pre-wrap break-words leading-relaxed py-1">
                                {d.text}
                              </div>
                            ))
                          )}
                        </div>
                      ) : activeOutputTab === "ui_log" ? (
                         <pre className="text-[12px] font-mono text-slate-200 whitespace-pre-wrap">{uiLogText || "(empty)"}</pre>
                       ) : (
                         <>
                           {wsLogErr && <div className="text-[12px] font-mono text-red-300 mb-2">{wsLogErr}</div>}
                           <pre className="text-[12px] font-mono text-slate-200 whitespace-pre-wrap">{wsLogText || "(empty)"}</pre>
                         </>
                       )}
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