import { useCallback, useEffect, useRef, useState } from "react";

import { MessageLog } from "../types";

export function useUiLog(args: { backendCandidates: () => string[] }) {
  const { backendCandidates } = args;

  const uiLogPendingRef = useRef<Array<{ ts: number; entry: any }>>([]);
  const uiLogFlushTimerRef = useRef<number | null>(null);
  const [uiLogText, setUiLogText] = useState<string>("");

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

  const persistUiLogLine = useCallback(
    (line: string) => {
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
    },
    [uiLogStorageKey]
  );

  const appendUiLogEntry = useCallback(
    (msg: MessageLog) => {
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
    },
    [persistUiLogLine]
  );

  const flushUiLogToBackend = useCallback(async () => {
    const pending = uiLogPendingRef.current;
    if (!pending.length) return;
    const batch = pending.splice(0, 100);
    const entries = batch.map((b) => b.entry);
    for (const base of backendCandidates()) {
      try {
        const effectiveBase = base ? base : "/jarvis/api";
        const res = await fetch(`${effectiveBase}/logs/ui/append`, {
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

  return {
    uiLogText,
    setUiLogText,
    loadUiLogFromLocalStorage,
    appendUiLogEntry,
    scheduleUiLogFlush,
  };
}
