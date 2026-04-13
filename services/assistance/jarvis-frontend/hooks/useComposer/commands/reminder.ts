import { extractReminderAddText } from "../../../lib/appHelpers";
import type { CommandContext, CommandResult } from "../types";

export function handleReminderCommand(ctx: CommandContext): CommandResult {
  const { liveService, composerText, setComposerText, setAttachments } = ctx;

  if (liveService.current == null) return { handled: false };

  const base = composerText.trim();

  // Reminder add
  const reminderText = base ? extractReminderAddText(base) : null;
  if (reminderText) {
    liveService.current.sendRemindersAdd(reminderText);
    setComposerText("");
    setAttachments([]);
    return { handled: true };
  }

  return { handled: false };
}
