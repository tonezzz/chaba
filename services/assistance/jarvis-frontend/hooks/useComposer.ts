import React, { useCallback, useRef, useState } from "react";
import { LiveService } from "../services/liveService";
import { ConnectionState } from "../types";
import type { MessageLog } from "../types";
import { normalizeComposerText } from "../lib/appHelpers";
import {
  handleSysCommand,
  handleToolCommand,
  handleReloadCommand,
  handleReminderCommand,
} from "./useComposer/commands";
import type { Attachment } from "./useComposer/types";

interface UseComposerArgs {
  liveService: React.RefObject<LiveService | null>;
  state: ConnectionState;
  setMessages: React.Dispatch<React.SetStateAction<MessageLog[]>>;
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  attachments: Attachment[];
  setActiveRightPanel: (panel: "output" | "cars" | "checklist") => void;
  setActiveOutputTab: (tab: "dialog" | "ui_log" | "ws_log" | "pending") => void;
  refreshPending: () => Promise<void>;
}

interface UseComposerReturn {
  composerText: string;
  setComposerText: React.Dispatch<React.SetStateAction<string>>;
  handleSendComposer: () => void;
  handlePickFiles: () => void;
  handleFilesSelected: (files: FileList | null) => Promise<void>;
  handleRemoveAttachment: (id: string) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
}

/**
 * Composer input handling hook.
 * Parses commands (/sys, /tool, system reload phrases, reminders)
 * and dispatches to LiveService.
 */
export function useComposer(args: UseComposerArgs): UseComposerReturn {
  const {
    liveService,
    state,
    setMessages,
    setAttachments,
    attachments,
    setActiveRightPanel,
    setActiveOutputTab,
    refreshPending,
  } = args;

  const [composerText, setComposerText] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handlePickFiles = useCallback(() => {
    if (state !== ConnectionState.CONNECTED) return;
    fileInputRef.current?.click();
  }, [state]);

  const handleRemoveAttachment = useCallback(
    (id: string) => {
      setAttachments((prev) => prev.filter((a) => a.id !== id));
    },
    [setAttachments]
  );

  const handleFilesSelected = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const next: Attachment[] = [];

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
        const kind: Attachment["kind"] = isPdf ? "pdf" : isImage ? "image" : "text";
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
    },
    [setMessages, setAttachments]
  );

  const handleSendComposer = useCallback(() => {
    if (state !== ConnectionState.CONNECTED) return;
    const base = composerText.trim();

    // Build command context for handlers
    const ctx = {
      liveService,
      state,
      composerText,
      setComposerText: (v: string) => setComposerText(v),
      setAttachments,
      setMessages,
      attachments,
      setActiveRightPanel,
      setActiveOutputTab,
      refreshPending,
    };

    // Try command handlers in order
    const handlers = [
      handleSysCommand,
      handleToolCommand,
      handleReloadCommand,
      handleReminderCommand,
    ];

    for (const handler of handlers) {
      const result = handler(ctx);
      if (result.handled) return;
    }

    // Default: send as text
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
  }, [
    state,
    composerText,
    attachments,
    liveService,
    setMessages,
    setAttachments,
    setActiveRightPanel,
    setActiveOutputTab,
    refreshPending,
  ]);

  return {
    composerText,
    setComposerText,
    handleSendComposer,
    handlePickFiles,
    handleFilesSelected,
    handleRemoveAttachment,
    fileInputRef,
  };
}
