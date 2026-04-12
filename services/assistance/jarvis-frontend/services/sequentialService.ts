export type SequentialSuggestRequest = {
  task: { notes?: string };
  completed_tasks?: Array<{ notes?: string }>;
};

export type SequentialSuggestResponse = {
  ok: boolean;
  next_step_text: string | null;
  next_step_index: number | null;
  template: string[] | null;
};

export type SequentialApplyRequest = {
  notes: string;
  step_index: number;
};

export type SequentialApplyResponse = {
  ok: boolean;
  changed: boolean;
  notes: string;
};

export type SequentialApplyByTextRequest = {
  notes: string;
  step_text: string;
};

export type SequentialApplyByTextResponse = {
  ok: boolean;
  changed: boolean;
  notes: string;
  matched_step_index: number | null;
};

export type SequentialApplyAllRequest = {
  notes: string;
};

export type SequentialApplyAllResponse = {
  ok: boolean;
  changed: boolean;
  changed_count: number;
  notes: string;
};

export type SequentialApplyAndSuggestMode = "suggest" | "index" | "text" | "all";

export type SequentialApplyAndSuggestRequest = {
  mode: SequentialApplyAndSuggestMode;
  notes: string;
  step_index?: number | null;
  step_text?: string;
  completed_tasks?: Array<{ notes?: string }>;
};

export type SequentialApplyAndSuggestResponse = {
  ok: boolean;
  mode: string;
  notes: string;
  changed: boolean;
  changed_count: number | null;
  matched_step_index: number | null;
  next_step_text: string | null;
  next_step_index: number | null;
  template: string[] | null;
};

function getBackendHttpBaseUrl(): string {
  const envUrl = (import.meta as any).env?.VITE_JARVIS_HTTP_URL as string | undefined;
  if (envUrl && String(envUrl).trim()) return String(envUrl).trim().replace(/\/+$/, "");
  return `${location.origin}/jarvis/api`;
}

export async function sequentialSuggest(req: SequentialSuggestRequest): Promise<SequentialSuggestResponse> {
  const base = getBackendHttpBaseUrl();
  const res = await fetch(`${base}/tasks/sequential/suggest`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`sequential_suggest_failed status=${res.status}`);
  }
  return (await res.json()) as SequentialSuggestResponse;
}

export async function sequentialApply(req: SequentialApplyRequest): Promise<SequentialApplyResponse> {
  const base = getBackendHttpBaseUrl();
  const res = await fetch(`${base}/tasks/sequential/apply`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`sequential_apply_failed status=${res.status}`);
  }
  return (await res.json()) as SequentialApplyResponse;
}

export async function sequentialApplyByText(req: SequentialApplyByTextRequest): Promise<SequentialApplyByTextResponse> {
  const base = getBackendHttpBaseUrl();
  const res = await fetch(`${base}/tasks/sequential/apply_by_text`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`sequential_apply_by_text_failed status=${res.status}`);
  }
  return (await res.json()) as SequentialApplyByTextResponse;
}

export async function sequentialApplyAll(req: SequentialApplyAllRequest): Promise<SequentialApplyAllResponse> {
  const base = getBackendHttpBaseUrl();
  const res = await fetch(`${base}/tasks/sequential/apply_all`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`sequential_apply_all_failed status=${res.status}`);
  }
  return (await res.json()) as SequentialApplyAllResponse;
}

export async function sequentialApplyAndSuggest(req: SequentialApplyAndSuggestRequest): Promise<SequentialApplyAndSuggestResponse> {
  const base = getBackendHttpBaseUrl();
  const res = await fetch(`${base}/tasks/sequential/apply_and_suggest`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`sequential_apply_and_suggest_failed status=${res.status}`);
  }
  return (await res.json()) as SequentialApplyAndSuggestResponse;
}
