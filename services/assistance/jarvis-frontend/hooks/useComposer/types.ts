import React from "react";
import type { LiveService } from "../../services/liveService";
import type { ConnectionState, MessageLog } from "../../types";

export interface Attachment {
  id: string;
  name: string;
  size: number;
  kind: "image" | "pdf" | "text";
  text?: string;
}

export interface UseComposerArgs {
  liveService: React.RefObject<LiveService | null>;
  state: ConnectionState;
  setMessages: React.Dispatch<React.SetStateAction<MessageLog[]>>;
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  attachments: Attachment[];
  setActiveRightPanel: (panel: "output" | "cars" | "checklist") => void;
  setActiveOutputTab: (tab: "dialog" | "ui_log" | "ws_log" | "pending") => void;
  refreshPending: () => Promise<void>;
}

export interface UseComposerReturn {
  composerText: string;
  setComposerText: React.Dispatch<React.SetStateAction<string>>;
  handleSendComposer: () => void;
  handlePickFiles: () => void;
  handleFilesSelected: (files: FileList | null) => Promise<void>;
  handleRemoveAttachment: (id: string) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
}

export interface CommandContext {
  liveService: React.RefObject<LiveService | null>;
  state: ConnectionState;
  composerText: string;
  setComposerText: (v: string) => void;
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  setMessages: React.Dispatch<React.SetStateAction<MessageLog[]>>;
  attachments: Attachment[];
  setActiveRightPanel?: (panel: "output" | "cars" | "checklist") => void;
  setActiveOutputTab?: (tab: "dialog" | "ui_log" | "ws_log" | "pending") => void;
  refreshPending?: () => Promise<void>;
}

export type CommandResult =
  | { handled: true; stopPropagation?: boolean }
  | { handled: false };

export type CommandHandler = (ctx: CommandContext) => CommandResult;
