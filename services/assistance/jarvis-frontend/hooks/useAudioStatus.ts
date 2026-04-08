import React, { useMemo } from "react";
import type { MessageLog } from "../types";
import { ConnectionState } from "../types";

interface AudioStatus {
  ok: boolean;
  lastConn: number;
  lastAudioUnavailable: number;
}

/**
 * Derive audio status from message log and connection state.
 * Audio is OK only when connected AND no recent audio_unavailable error.
 */
export function useAudioStatus(messages: MessageLog[], state: ConnectionState): AudioStatus {
  return useMemo(() => {
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
}
