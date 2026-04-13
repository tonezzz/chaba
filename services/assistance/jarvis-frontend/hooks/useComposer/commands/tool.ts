import { normalizeComposerText, parseJsonToolRequest, parseToolInvoke } from "../../../lib/appHelpers";
import type { CommandContext, CommandResult } from "../types";

export function handleToolCommand(ctx: CommandContext): CommandResult {
  const { liveService, composerText, setComposerText, setAttachments, setMessages } = ctx;

  if (liveService.current == null) return { handled: false };

  const base = composerText.trim();
  const normalized = normalizeComposerText(base);

  // JSON tool request
  const jsonToolReq = parseJsonToolRequest(base);
  if (jsonToolReq) {
    setComposerText("");
    setAttachments([]);
    const toolName = String(jsonToolReq.name || "").trim();
    const args = jsonToolReq.args && typeof jsonToolReq.args === "object" ? jsonToolReq.args : {};
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}_ui_json_tool_${Math.random().toString(16).slice(2)}`,
        role: "system",
        text: `ui: tool ${toolName}`,
        timestamp: new Date(),
        metadata: {
          severity: "info",
          category: "ws",
          raw: {
            type: "ui",
            kind: "tool",
            title: toolName,
            body: (() => {
              try {
                return JSON.stringify(args, null, 2);
              } catch {
                return String(args);
              }
            })(),
            risk: "low",
            primary: { label: "Run", tool: toolName, args },
          },
        },
      },
    ]);
    return { handled: true };
  }

  // /tool invoke
  const toolInvoke = parseToolInvoke(normalized);
  if (toolInvoke) {
    setComposerText("");
    setAttachments([]);

    if ((toolInvoke.args as any)?.__invalid_tool_prefix) {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_tool_invalid_prefix`,
          role: "system",
          text: `tool rejected (prefix): ${toolInvoke.name}`,
          timestamp: new Date(),
          metadata: { severity: "warn", category: "ws" },
        },
      ]);
      return { handled: true };
    }
    if ((toolInvoke.args as any)?.__invalid_tool_args) {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_tool_invalid_args`,
          role: "system",
          text: `tool args must be a JSON object: ${toolInvoke.name}`,
          timestamp: new Date(),
          metadata: { severity: "warn", category: "ws" },
        },
      ]);
      return { handled: true };
    }
    try {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_tool_ui`,
          role: "system",
          text: `tool: ${toolInvoke.name}`,
          timestamp: new Date(),
          metadata: { severity: "info", category: "ws" },
        },
      ]);
      void liveService.current
        ?.invokeTool(toolInvoke.name, toolInvoke.args)
        .catch((e: any) => {
          setMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}_tool_send_err`,
              role: "system",
              text: `tool failed: ${toolInvoke.name} (${String(e?.message || e || "tool_failed")})`,
              timestamp: new Date(),
              metadata: { severity: "error", category: "ws" },
            },
          ]);
        });
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_tool_send_throw`,
          role: "system",
          text: `tool failed: ${toolInvoke.name} (${String(e?.message || e || "tool_failed")})`,
          timestamp: new Date(),
          metadata: { severity: "error", category: "ws" },
        },
      ]);
    }
    return { handled: true };
  }

  return { handled: false };
}
