import { describe, expect, it } from "vitest";
import { LiveService } from "../services/liveService";

function mkService() {
  const svc = new LiveService();
  const logs: Array<{ id: string; text: string; role: string; metadata?: any }> = [];
  svc.onMessage = (msg) => {
    logs.push({ id: msg.id, text: msg.text, role: msg.role, metadata: msg.metadata });
  };
  return { svc, logs };
}

describe("LiveService WS contract", () => {
  it("renders reminder_helper_list with rows", async () => {
    const { svc, logs } = mkService();

    const payload = {
      type: "reminder_helper_list",
      status: "pending",
      include_hidden: false,
      day: "today",
      trace_id: "text_sess_123",
      instance_id: "jarvis_x",
      reminders: [
        { reminder_id: "1", title: "Pay rent", status: "pending", notify_at: 123 },
        { reminder_id: "2", title: "Call mom", status: "pending", due_at: 456 },
      ],
    };

    await (svc as any).handleBackendMessage(payload);

    expect(logs.length).toBe(1);
    expect(logs[0].text).toContain("reminder_helper_list");
    expect(logs[0].text).toContain("Pay rent");
    expect(logs[0].text).toContain("Call mom");
    expect(logs[0].metadata?.trace_id).toBe("text_sess_123");
    expect(logs[0].metadata?.ws?.type).toBe("reminder_helper_list");
    expect(logs[0].metadata?.ws?.instance_id).toBe("jarvis_x");
    expect(logs[0].metadata?.raw?.type).toBe("reminder_helper_list");
  });

  it("renders reminder_helper_list empty state", async () => {
    const { svc, logs } = mkService();

    const payload = {
      type: "reminder_helper_list",
      status: "pending",
      include_hidden: false,
      reminders: [],
    };

    await (svc as any).handleBackendMessage(payload);

    expect(logs.length).toBe(1);
    expect(logs[0].text).toContain("(no results)");
  });

  it("attaches ws metadata for error events", async () => {
    const { svc, logs } = mkService();

    const payload = {
      type: "error",
      message: "gemini_live_model_not_found",
      trace_id: "text_abc",
      instance_id: "jarvis_x",
    };

    await (svc as any).handleBackendMessage(payload);

    expect(logs.length).toBe(1);
    expect(logs[0].role).toBe("system");
    expect(logs[0].metadata?.trace_id).toBe("text_abc");
    expect(logs[0].metadata?.ws?.type).toBe("error");
    expect(logs[0].metadata?.ws?.instance_id).toBe("jarvis_x");
  });
});
