import { EventEmitter } from 'events';
import { randomUUID } from 'crypto';

const MAX_RUNS = Number(process.env.MCP_DEVOPS_MAX_RUNS || 25);
const MAX_LOGS = Number(process.env.MCP_DEVOPS_MAX_LOGS || 2000);

const clone = (value) => JSON.parse(JSON.stringify(value));

const makeLogEntry = (entry = {}) => ({
  stream: entry.stream || 'stdout',
  message: entry.message || '',
  phase: entry.phase || 'main',
  timestamp: entry.timestamp || new Date().toISOString()
});

class RunStore extends EventEmitter {
  constructor() {
    super();
    this.runs = new Map();
  }

  createRun({ workflowId, workflowLabel, dryRun }) {
    const now = new Date().toISOString();
    const id = randomUUID();
    const record = {
      id,
      workflow_id: workflowId,
      workflow_label: workflowLabel || workflowId,
      dry_run: Boolean(dryRun),
      status: 'running',
      started_at: now,
      updated_at: now,
      finished_at: null,
      exit_code: null,
      duration_ms: null,
      command: null,
      outputs: null,
      logs: [],
      segments: {}
    };
    this.runs.set(id, record);
    this.#trimRuns();
    this.emit('created', clone(record));
    return record;
  }

  setCommand(runId, command, phase = 'main') {
    const run = this.runs.get(runId);
    if (!run) return;
    if (!run.segments[phase]) {
      run.segments[phase] = {};
    }
    run.segments[phase].command = command;
    if (phase === 'main') {
      run.command = command;
    }
  }

  appendLog(runId, entry) {
    const run = this.runs.get(runId);
    if (!run) return;
    const logEntry = makeLogEntry(entry);
    run.logs.push(logEntry);
    if (run.logs.length > MAX_LOGS) {
      run.logs.splice(0, run.logs.length - MAX_LOGS);
    }
    run.updated_at = new Date().toISOString();
    this.emit('log', { runId, entry: clone(logEntry) });
  }

  appendSegment(runId, phase, info) {
    const run = this.runs.get(runId);
    if (!run) return;
    if (!run.segments[phase]) {
      run.segments[phase] = {};
    }
    run.segments[phase] = {
      ...run.segments[phase],
      ...info,
      phase
    };
    run.updated_at = new Date().toISOString();
    this.emit('segment', { runId, phase, info: clone(run.segments[phase]) });
  }

  completeRun(runId, { exitCode, durationMs, outputs, status }) {
    const run = this.runs.get(runId);
    if (!run) return;
    const now = new Date().toISOString();
    run.exit_code = typeof exitCode === 'number' ? exitCode : null;
    run.duration_ms = typeof durationMs === 'number' ? durationMs : null;
    run.outputs = outputs ?? run.outputs ?? null;
    run.finished_at = now;
    run.updated_at = now;
    if (status) {
      run.status = status;
    } else if (run.exit_code === null) {
      run.status = 'dry-run';
    } else {
      run.status = run.exit_code === 0 ? 'succeeded' : 'failed';
    }
    this.emit('completed', { runId, run: clone(run) });
  }

  failRun(runId, error) {
    const run = this.runs.get(runId);
    if (!run) return;
    run.status = 'failed';
    run.exit_code = -1;
    run.finished_at = new Date().toISOString();
    run.updated_at = run.finished_at;
    this.appendLog(runId, { stream: 'stderr', message: error?.message || String(error || 'failed') });
    this.emit('completed', { runId, run: clone(run) });
  }

  listRuns() {
    return Array.from(this.runs.values())
      .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
      .map((run) => clone(run));
  }

  getRun(runId) {
    const run = this.runs.get(runId);
    return run ? clone(run) : null;
  }

  onLog(runId, listener) {
    const handler = (payload) => {
      if (payload.runId === runId) {
        listener(payload.entry);
      }
    };
    this.on('log', handler);
    return () => this.off('log', handler);
  }

  onCompletion(runId, listener) {
    const handler = (payload) => {
      if (payload.runId === runId) {
        listener(payload.run);
      }
    };
    this.on('completed', handler);
    return () => this.off('completed', handler);
  }

  #trimRuns() {
    if (this.runs.size <= MAX_RUNS) return;
    const sorted = Array.from(this.runs.entries()).sort(
      (a, b) => new Date(a[1].started_at).getTime() - new Date(b[1].started_at).getTime()
    );
    while (sorted.length > MAX_RUNS) {
      const [id] = sorted.shift();
      this.runs.delete(id);
    }
  }
}

export const runStore = new RunStore();
