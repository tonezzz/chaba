import React, { useMemo } from "react";
import type { MessageLog } from "../types";
import { splitSentences } from "../lib/appHelpers";

interface DialogLine {
  id: string;
  text: string;
}

interface UseOutputDialogReturn {
  outputDialog: DialogLine[];
  outputChat: MessageLog[];
}

/**
 * Transform message log into displayable dialog and chat outputs.
 * outputDialog: model output only, with sentence splitting and partial merge
 * outputChat: all user/model/system messages (last 200)
 */
export function useOutputDialog(messages: MessageLog[]): UseOutputDialogReturn {
  const outputDialog = useMemo(() => {
    const ordered = messages
      .filter((m) => {
        if (m.role !== "model") return false;
        const src = String(m.metadata?.source || "");
        const sev = String(m.metadata?.severity || "info");
        const cat = String(m.metadata?.category || "");
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

    const dialog: DialogLine[] = [];
    for (const m of ordered) {
      const sents = splitSentences(String(m.text || ""));
      for (let i = 0; i < sents.length; i++) {
        const sent = sents[i];
        const isLast = i === sents.length - 1;
        const id = `${m.id}_s${i}`;
        if (isLast && !sent.complete && dialog.length) {
          dialog[dialog.length - 1] = { ...dialog[dialog.length - 1], text: sent.t };
        } else {
          dialog.push({ id, text: sent.t });
        }
      }
    }

    return dialog.slice(-200);
  }, [messages]);

  const outputChat = useMemo(() => {
    const ordered = messages
      .filter((m) => {
        const t = String(m.text || "").trim();
        if (!t) return false;
        if (m.role === "user" || m.role === "model") return true;
        if (m.role === "system") return true;
        return false;
      })
      .slice()
      .sort((a, b) => {
        const ta = a.timestamp?.getTime?.() ? a.timestamp.getTime() : 0;
        const tb = b.timestamp?.getTime?.() ? b.timestamp.getTime() : 0;
        if (ta !== tb) return ta - tb;
        return String(a.id || "").localeCompare(String(b.id || ""));
      });
    return ordered.slice(-200);
  }, [messages]);

  return { outputDialog, outputChat };
}
