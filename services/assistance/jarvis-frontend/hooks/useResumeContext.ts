import { RefObject, useEffect } from "react";

import { ConnectionState, MessageLog } from "../types";
import { LiveService } from "../services/liveService";

export function useResumeContext(args: {
  messages: MessageLog[];
  hasKey: boolean;
  state: ConnectionState;
  liveService: RefObject<LiveService | null>;
  resumeSentRef: RefObject<boolean>;
  lastConnStateRef: RefObject<ConnectionState>;
}) {
  const { messages, hasKey, state, liveService, resumeSentRef, lastConnStateRef } = args;

  useEffect(() => {
    // Persist recent dialog turns for reconnect resume (local only).
    // We store only user/model messages (exclude system/progress chatter).
    try {
      const MAX_TURNS = 20;
      const items = messages
        .filter((m) => m && (m.role === "user" || m.role === "model") && String(m.text || "").trim())
        .slice(0, MAX_TURNS * 2)
        .map((m) => ({ role: m.role, text: String(m.text || "").trim(), ts: m.timestamp?.getTime?.() || Date.now() }));
      const chron = items.slice().reverse();
      window.localStorage.setItem("jarvis_recent_dialog_v1", JSON.stringify(chron));
    } catch {
      // ignore
    }
  }, [messages]);

  useEffect(() => {
    if (!hasKey) return;
    // Auto-send resume context once per WS connection.
    // We treat a transition into CONNECTED as a new connection.
    const prev = lastConnStateRef.current;
    lastConnStateRef.current = state;
    if (state === ConnectionState.CONNECTED && prev !== ConnectionState.CONNECTED) {
      resumeSentRef.current = false;
    }
    if (state !== ConnectionState.CONNECTED) return;
    if (resumeSentRef.current) return;

    let raw = "";
    try {
      raw = String(window.localStorage.getItem("jarvis_recent_dialog_v1") || "").trim();
    } catch {
      raw = "";
    }
    if (!raw) {
      resumeSentRef.current = true;
      return;
    }

    let parsed: Array<{ role: string; text: string; ts?: number }> = [];
    try {
      const js = JSON.parse(raw);
      if (Array.isArray(js)) parsed = js as any;
    } catch {
      parsed = [];
    }

    const cleaned = parsed
      .filter((it) => it && (it.role === "user" || it.role === "model") && String((it as any).text || "").trim())
      .slice(-60);
    if (!cleaned.length) {
      resumeSentRef.current = true;
      return;
    }

    const lines: string[] = [];
    lines.push("RESUME_CONTEXT (recent dialog; for context only — do not quote verbatim unless asked)");
    lines.push("If the user continues after reconnect, assume this context is still active.");
    lines.push("");
    for (const it of cleaned) {
      const who = it.role === "user" ? "USER" : "ASSISTANT";
      let t = String((it as any).text || "").trim();
      if (t.length > 2000) t = t.slice(0, 2000) + "…";
      lines.push(`${who}: ${t}`);
      lines.push("");
    }
    const payload = lines.join("\n").trim();

    try {
      liveService.current?.sendText(payload);
    } catch {
      // ignore
    }
    resumeSentRef.current = true;
  }, [state, hasKey, liveService, resumeSentRef, lastConnStateRef]);
}
