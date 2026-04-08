import React, { useRef, useCallback, useEffect } from "react";
import { LiveService } from "../services/liveService";
import { ConnectionState } from "../types";
import type { MessageLog, PendingEventMessage, WsReadinessEvent, CarsIngestResult } from "../types";

interface UseLiveServiceArgs {
  hasKey: boolean;
  onMessage: (msg: MessageLog) => void;
  onReadiness?: (ev: WsReadinessEvent) => void;
  onPendingEvent?: (ev: PendingEventMessage) => void;
  onCarsIngestResult?: (ev: CarsIngestResult) => void;
  setState: (state: ConnectionState) => void;
  setVolume: (vol: number) => void;
  setActiveRightPanel?: (panel: "output" | "cars" | "checklist") => void;
  setActiveOutputTab?: (tab: "dialog" | "ui_log" | "ws_log" | "pending") => void;
  refreshPending?: () => Promise<void>;
  previewPending?: (cid: string) => Promise<void>;
}

interface UseLiveServiceReturn {
  liveService: React.RefObject<LiveService | null>;
  handleConnect: () => void;
}

/**
 * LiveService lifecycle hook.
 * Constructs service, wires callbacks, handles cleanup.
 */
export function useLiveService(args: UseLiveServiceArgs): UseLiveServiceReturn {
  const {
    hasKey,
    onMessage,
    onReadiness,
    onPendingEvent,
    onCarsIngestResult,
    setState,
    setVolume,
    setActiveRightPanel,
    setActiveOutputTab,
    refreshPending,
    previewPending,
  } = args;

  const liveService = useRef<LiveService | null>(null);
  const stateRef = useRef<ConnectionState>(ConnectionState.DISCONNECTED);

  const handleConnect = useCallback(() => {
    if (stateRef.current === ConnectionState.DISCONNECTED || stateRef.current === ConnectionState.ERROR) {
      liveService.current?.connect();
    } else {
      liveService.current?.stopStreaming();
      liveService.current?.disconnect();
    }
  }, []);

  useEffect(() => {
    if (!hasKey) return;

    liveService.current = new LiveService();
    liveService.current.onStateChange = (s) => {
      stateRef.current = s;
      setState(s);
    };
    liveService.current.onVolume = setVolume;
    liveService.current.onReadiness = (ev) => {
      try {
        onReadiness?.(ev);
      } catch {
        // ignore
      }
    };
    liveService.current.onPendingEvent = (ev) => {
      try {
        const event = String((ev as any)?.event || "").trim();
        const cid = String((ev as any)?.confirmation_id || "").trim();
        if (event === "awaiting_user" && cid) {
          setActiveRightPanel?.("output");
          setActiveOutputTab?.("pending");
        }
        (async () => {
          try {
            await refreshPending?.();
            if (event === "awaiting_user" && cid) {
              await previewPending?.(cid);
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
      try {
        onCarsIngestResult?.(ev);
      } catch {
        // ignore
      }
    };
    liveService.current.onMessage = onMessage;

    return () => {
      try {
        void liveService.current?.disconnect();
      } catch {
        // ignore
      }
    };
  }, [hasKey, onMessage, onReadiness, onPendingEvent, onCarsIngestResult, setState, setVolume, setActiveRightPanel, setActiveOutputTab, refreshPending, previewPending]);

  return { liveService, handleConnect };
}
