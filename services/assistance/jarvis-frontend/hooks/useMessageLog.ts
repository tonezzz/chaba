import React, { useCallback, useRef, useState } from "react";
import type { MessageLog } from "../types";

interface UseMessageLogArgs {
  appendUiLogEntry: (msg: MessageLog) => void;
  scheduleUiLogFlush: () => void;
  readinessPhaseRef: React.MutableRefObject<string>;
  showDebugLogsRef: React.MutableRefObject<boolean>;
}

interface UseMessageLogReturn {
  messages: MessageLog[];
  setMessages: React.Dispatch<React.SetStateAction<MessageLog[]>>;
  resumeHydratedRef: React.MutableRefObject<boolean>;
  lastActivityTextRef: React.MutableRefObject<string>;
  lastActivityTsRef: React.MutableRefObject<number>;
  activeMedia: MessageLog | null;
  setActiveMedia: React.Dispatch<React.SetStateAction<MessageLog | null>>;
  handleMessage: (msg: MessageLog) => void;
}

/**
 * Message log processing hook.
 * Handles: sticky progress, session resume hydration, autospeak suppression,
 * chunk merging, activity tracking, and media activation.
 */
export function useMessageLog(args: UseMessageLogArgs): UseMessageLogReturn {
  const { appendUiLogEntry, scheduleUiLogFlush, readinessPhaseRef, showDebugLogsRef } = args;

  const [messages, setMessages] = useState<MessageLog[]>([]);
  const resumeHydratedRef = useRef<boolean>(false);
  const lastActivityTextRef = useRef<string>("");
  const lastActivityTsRef = useRef<number>(0);
  const [activeMedia, setActiveMedia] = useState<MessageLog | null>(null);

  const handleMessage = useCallback(
    (msg: MessageLog) => {
      // UI logging
      try {
        appendUiLogEntry(msg);
        scheduleUiLogFlush();
      } catch {
        // ignore
      }

      // Track activity for disconnect context
      try {
        const txt = String((msg as any)?.text || "").trim();
        const sev = String((msg as any)?.metadata?.severity || "").trim();
        const cat = String((msg as any)?.metadata?.category || "").trim();
        const ts = msg.timestamp instanceof Date ? msg.timestamp.getTime() : Date.now();
        const isActivity = msg.id === "sticky_progress" || (msg.role === "system" && !!txt && (cat === "ws" || cat === "live") && sev !== "debug");
        if (isActivity) {
          lastActivityTextRef.current = txt;
          lastActivityTsRef.current = ts;
        }
      } catch {
        // ignore
      }

      // Policy: suppress autospeak triggers until backend model is ready
      try {
        const txt = String((msg as any)?.text || "").trim();
        if (txt.toLowerCase().startsWith("autospeak:")) {
          if (readinessPhaseRef.current !== "model_ready") {
            return;
          }
        }
      } catch {
        // ignore
      }

      // Session resume hydration
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

      // Debug autospeak filtering
      try {
        const txt = String((msg as any)?.text || "").trim();
        const isAutospeakLine = /\bauto\s*speak\b/i.test(txt) || /\bautospeek\b/i.test(txt);
        if (isAutospeakLine) {
          if (!showDebugLogsRef.current) return;
          if (readinessPhaseRef.current !== "model_ready") return;
        }
      } catch {
        // ignore
      }

      // Main message append with chunk merging
      setMessages((prev) => {
        if (msg.id === "sticky_progress") {
          const without = prev.filter((m) => m.id !== "sticky_progress");
          const txt = String(msg.text || "").trim();
          if (!txt) return without;
          return [...without, msg];
        }

        // Group rapid-fire short text chunks
        try {
          const nextTxt = String(msg.text || "");
          const nextTrim = nextTxt.trim();
          const last = prev.length ? prev[prev.length - 1] : null;
          const nextTs = msg.timestamp instanceof Date ? msg.timestamp.getTime() : Date.now();
          const lastTs = last?.timestamp instanceof Date ? last.timestamp.getTime() : 0;
          const withinWindow = lastTs > 0 && nextTs - lastTs >= 0 && nextTs - lastTs <= 1600;
          const canMergeRole = last && last.role === msg.role && (msg.role === "model" || msg.role === "system");
          const isTimeFragment = /^\d{1,2}:\d{2}(?:\s*(?:น\.|am|pm))?\s*$/i.test(nextTrim);
          const looksLikeChunk = (nextTrim.length > 0 && nextTrim.length <= 40 && !nextTrim.includes("\n")) || isTimeFragment;
          const lastTxt = last ? String(last.text || "") : "";
          const lastTrim = lastTxt.trim();
          const lastLooksLikeChunk = lastTrim.length > 0 && lastTrim.length <= 60 && !lastTrim.includes("\n");
          const lastEndsSentence = /[.!?…。、！？]$/.test(lastTrim);
          const nextStartsNewSentence = /^[A-Z0-9]/.test(nextTrim);
          if (withinWindow && canMergeRole && looksLikeChunk && lastLooksLikeChunk && !lastEndsSentence && !nextStartsNewSentence) {
            const lastEndsThai = /[\u0E00-\u0E7F]$/.test(lastTrim);
            const nextStartsThai = /^[\u0E00-\u0E7F]/.test(nextTrim);
            const isThaiBoundary = lastEndsThai && nextStartsThai;
            const lastEndsWithThaiTimeCue = /เวลา\s*$/.test(lastTrim);
            const joiner = isThaiBoundary ? "" : /\s$/.test(lastTxt) ? "" : " ";
            const joiner2 = lastEndsWithThaiTimeCue && isTimeFragment ? " " : joiner;
            const merged: any = { ...last, text: `${lastTxt}${joiner}${nextTrim}`, timestamp: msg.timestamp };
            merged.text = `${lastTxt}${joiner2}${nextTrim}`;
            return [...prev.slice(0, -1), merged];
          }
        } catch {
          // ignore
        }

        return [...prev, msg];
      });

      // Media activation
      if (msg.metadata) {
        setActiveMedia(msg);
      }
    },
    [appendUiLogEntry, scheduleUiLogFlush, readinessPhaseRef, showDebugLogsRef]
  );

  return {
    messages,
    setMessages,
    resumeHydratedRef,
    lastActivityTextRef,
    lastActivityTsRef,
    activeMedia,
    setActiveMedia,
    handleMessage,
  };
}
