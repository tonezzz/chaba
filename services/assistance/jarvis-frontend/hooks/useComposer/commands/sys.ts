import {
  normalizeComposerText,
  parseSysSet,
  parseSysDedupe,
} from "../../../lib/appHelpers";
import type { CommandContext, CommandResult } from "../types";

export function handleSysCommand(ctx: CommandContext): CommandResult {
  const { liveService, composerText, setComposerText, setAttachments, setMessages } = ctx;

  if (liveService.current == null) return { handled: false };

  const base = composerText.trim();
  const normalized = normalizeComposerText(base);

  // /sys set key=value
  const sysSet = parseSysSet(normalized);
  if (sysSet) {
    liveService.current.sendSysKvSet(sysSet.key, sysSet.value, { dry_run: sysSet.dryRun });
    setComposerText("");
    setAttachments([]);
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}_sys_set_ui`,
        role: "system",
        text: `${sysSet.dryRun ? "sys_kv_set (dry_run)" : "sys_kv_set"}: ${sysSet.key}=${sysSet.value}`,
        timestamp: new Date(),
        metadata: { severity: "info", category: "ws" },
      },
      {
        id: `${Date.now()}_sys_set_hint`,
        role: "system",
        text: "Hint: run 'reload system' to apply sys changes.",
        timestamp: new Date(),
        metadata: { severity: "debug", category: "ws" },
      },
    ]);
    return { handled: true };
  }

  // /sys dedupe
  const sysDedupe = parseSysDedupe(normalized);
  if (sysDedupe) {
    liveService.current.sendSysKvDedupe({ dry_run: sysDedupe.dryRun, sort: sysDedupe.sort });
    setComposerText("");
    setAttachments([]);
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}_sys_dedupe_ui`,
        role: "system",
        text: `${sysDedupe.dryRun ? "sys_kv_dedupe (dry_run)" : "sys_kv_dedupe"}${sysDedupe.sort ? " (sort)" : ""}`,
        timestamp: new Date(),
        metadata: { severity: "info", category: "ws" },
      },
    ]);
    return { handled: true };
  }

  // system clear job
  if (normalized.toLowerCase() === "system clear job" || normalized.toLowerCase() === "sys clear job") {
    liveService.current.sendSystemClearJob();
    setComposerText("");
    setAttachments([]);
    return { handled: true };
  }

  return { handled: false };
}
