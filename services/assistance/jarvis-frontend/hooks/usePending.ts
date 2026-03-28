import { RefObject, useCallback, useState } from "react";

import { LiveService } from "../services/liveService";

export function usePending(args: {
  liveService: RefObject<LiveService | null>;
  setActiveRightPanel: (v: "output" | "cars" | "checklist") => void;
  setActiveOutputTab: (v: "dialog" | "ui_log" | "ws_log" | "pending") => void;
}) {
  const { liveService, setActiveRightPanel, setActiveOutputTab } = args;

  const [pendingItems, setPendingItems] = useState<any[]>([]);
  const [pendingSelectedId, setPendingSelectedId] = useState<string | null>(null);
  const [pendingPreview, setPendingPreview] = useState<any | null>(null);
  const [pendingActionBusy, setPendingActionBusy] = useState<boolean>(false);
  const [pendingActionResult, setPendingActionResult] = useState<any | null>(null);
  const [pendingErr, setPendingErr] = useState<string>("");
  const [pendingAuthCode, setPendingAuthCode] = useState<string>("");

  const refreshPending = useCallback(async () => {
    setPendingErr("");
    try {
      const res = await liveService.current?.invokeTool("pending_list", {});
      if (Array.isArray(res)) {
        const prio = (it: any): number => {
          const a = String(it?.action || "").trim();
          if (a === "system_reload") return 0;
          if (a === "mcp_tools_call") return 1;
          return 2;
        };
        const ts = (it: any): number => {
          const v = Number(it?.created_at || 0);
          return Number.isFinite(v) ? v : 0;
        };
        const sorted = [...res].sort((a, b) => {
          const pa = prio(a);
          const pb = prio(b);
          if (pa !== pb) return pa - pb;
          return ts(b) - ts(a);
        });
        setPendingItems(sorted);
      } else {
        setPendingItems([]);
      }
    } catch (e: any) {
      setPendingErr(String(e?.message || e || "pending_list_failed"));
      setPendingItems([]);
    }
  }, [liveService]);

  const copyPendingJson = useCallback(async (value: any) => {
    try {
      const txt = typeof value === "string" ? value : JSON.stringify(value ?? null, null, 2);
      await navigator.clipboard.writeText(txt);
    } catch (e: any) {
      setPendingErr(String(e?.message || e || "copy_failed"));
    }
  }, []);

  const previewPending = useCallback(
    async (confirmationId: string) => {
      const cid = String(confirmationId || "").trim();
      if (!cid) return;
      setPendingSelectedId(cid);
      setPendingPreview(null);
      setPendingActionResult(null);
      setPendingErr("");
      try {
        const res = await liveService.current?.invokeTool("pending_preview", { confirmation_id: cid });
        setPendingPreview(res);
      } catch (e: any) {
        setPendingErr(String(e?.message || e || "pending_preview_failed"));
      }
    },
    [liveService]
  );

  const queueGoogleRelink = useCallback(async () => {
    setPendingErr("");
    setPendingActionBusy(true);
    try {
      const res: any = await liveService.current?.invokeTool("google_account_relink_queue", {});
      const cid = String(res?.confirmation_id || "").trim();
      setActiveRightPanel("output");
      setActiveOutputTab("pending");
      await refreshPending();
      if (cid) {
        await previewPending(cid);
      }
    } catch (e: any) {
      setPendingErr(String(e?.message || e || "google_account_relink_queue_failed"));
    } finally {
      setPendingActionBusy(false);
    }
  }, [liveService, previewPending, refreshPending, setActiveOutputTab, setActiveRightPanel]);

  const confirmPending = useCallback(
    async (confirmationId: string) => {
      const cid = String(confirmationId || "").trim();
      if (!cid) return;
      setPendingActionBusy(true);
      setPendingErr("");
      try {
        const isAuth = String(pendingPreview?.action || "") === "google_account_relink";
        const input = isAuth ? { code_or_redirected_url: String(pendingAuthCode || "").trim() } : undefined;
        const res = await liveService.current?.invokeTool(
          "pending_confirm",
          input ? { confirmation_id: cid, input } : { confirmation_id: cid }
        );
        setPendingActionResult(res);
        await refreshPending();
      } catch (e: any) {
        setPendingErr(String(e?.message || e || "pending_confirm_failed"));
      } finally {
        setPendingActionBusy(false);
      }
    },
    [liveService, pendingAuthCode, pendingPreview?.action, refreshPending]
  );

  const cancelPending = useCallback(
    async (confirmationId: string) => {
      const cid = String(confirmationId || "").trim();
      if (!cid) return;
      setPendingActionBusy(true);
      setPendingErr("");
      try {
        const res = await liveService.current?.invokeTool("pending_cancel", { confirmation_id: cid });
        setPendingActionResult(res);
        await refreshPending();
      } catch (e: any) {
        setPendingErr(String(e?.message || e || "pending_cancel_failed"));
      } finally {
        setPendingActionBusy(false);
      }
    },
    [liveService, refreshPending]
  );

  const queueBundlePublishReload = useCallback(async () => {
    setPendingActionBusy(true);
    setPendingErr("");
    setPendingActionResult(null);
    try {
      const res = await liveService.current?.invokeTool("system_macro_upsert_bundle_queue", {
        name: "macro_system_reload",
        enabled: true,
        description: "Reload system sheet KV and reload macros from sheet.",
        parameters_json: "{\"type\":\"object\",\"properties\":{}}",
        steps_json: "[{\"tool\":\"system_reload\",\"args\":{}}]",
        reload_mode: "full",
      });
      setPendingActionResult(res);
      await refreshPending();
    } catch (e: any) {
      setPendingErr(String(e?.message || e || "bundle_queue_failed"));
    } finally {
      setPendingActionBusy(false);
    }
  }, [liveService, refreshPending]);

  return {
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
  };
}
