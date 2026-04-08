import React, { useMemo } from "react";
import type { MessageLog } from "../types";

interface SystemCounts {
  memory: number;
  knowledge: number;
  ok: boolean;
}

/**
 * Derive system memory/knowledge counts from message log.
 * Searches for patterns like "memory=123 knowledge=456" in system messages.
 */
export function useSystemCounts(messages: MessageLog[]): SystemCounts {
  return useMemo(() => {
    const out: SystemCounts = { memory: 0, knowledge: 0, ok: false };
    const rxOk = /\bmemory\s*=\s*(\d+)\b[^\d]+\bknowledge\s*=\s*(\d+)\b/i;
    const rxMemKnowParen = /\bmemory\s*\(\s*(\d+)\s*:\s*(\d+)\s*\)[\s\S]*?\bknowledge\s*\(\s*(\d+)\s*:\s*(\d+)\s*\)/i;
    const rxLoadedEn = /\bloaded\s+memory\b[\s\S]*?\b(\d+)\b[\s\S]*?\bknowledge\b[\s\S]*?\b(\d+)\b/i;
    const rxLoadedTh = /โหลด\s*memory[\s\S]*?(\d+)[\s\S]*?knowledge[\s\S]*?(\d+)/i;

    for (const m of messages) {
      const t = String(m.text || "");
      let mm: RegExpMatchArray | null = null;
      mm = t.match(rxOk);
      if (!mm) {
        const mm2 = t.match(rxMemKnowParen);
        if (mm2) {
          const memLoaded = Number(mm2[2] || 0);
          const knowLoaded = Number(mm2[4] || 0);
          if (Number.isFinite(memLoaded) && Number.isFinite(knowLoaded)) {
            out.memory = memLoaded;
            out.knowledge = knowLoaded;
            out.ok = true;
            break;
          }
        }
      }
      if (!mm) mm = t.match(rxLoadedEn);
      if (!mm) mm = t.match(rxLoadedTh);
      if (!mm) continue;
      const mem = Number(mm[1] || 0);
      const know = Number(mm[2] || 0);
      if (!Number.isFinite(mem) || !Number.isFinite(know)) continue;
      out.memory = mem;
      out.knowledge = know;
      out.ok = true;
      break;
    }
    return out;
  }, [messages]);
}
