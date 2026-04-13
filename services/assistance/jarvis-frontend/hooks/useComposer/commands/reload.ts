import { isReloadSystemPhrase, extractSystemReloadMode } from "../../../services/liveVoiceCmd";
import type { CommandContext, CommandResult } from "../types";

export function handleReloadCommand(ctx: CommandContext): CommandResult {
  const { liveService, composerText, setComposerText, setAttachments, setActiveRightPanel, setActiveOutputTab, refreshPending } = ctx;

  if (liveService.current == null) return { handled: false };

  const base = composerText.trim();

  // Reload system phrase
  if (base && isReloadSystemPhrase(base)) {
    const mode = extractSystemReloadMode(base);
    try {
      const svc = liveService.current as any;
      if (svc?.invokeTool) {
        void svc.invokeTool("system_reload_queue", { mode }).then(
          () => {
            setActiveRightPanel?.("output");
            setActiveOutputTab?.("pending");
            void refreshPending?.();
          },
          () => {
            liveService.current?.sendSystemReload(mode);
          }
        );
      } else {
        liveService.current?.sendSystemReload(mode);
      }
    } catch {
      liveService.current?.sendSystemReload(mode);
    }
    setComposerText("");
    setAttachments([]);
    return { handled: true };
  }

  return { handled: false };
}
