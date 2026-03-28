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
      void messages;
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
    resumeSentRef.current = true;
  }, [state, hasKey, liveService, resumeSentRef, lastConnStateRef]);
}
