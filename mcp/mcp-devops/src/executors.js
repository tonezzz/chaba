import { spawn } from 'child_process';
import { performance } from 'perf_hooks';
import { config } from './config.js';

const MAX_PROCESS_LOGS = Number(process.env.MCP_DEVOPS_MAX_PROCESS_LOGS || 400);
const MAX_LOG_MESSAGE_CHARS = Number(process.env.MCP_DEVOPS_MAX_LOG_MESSAGE_CHARS || 4000);
const NETWORK_RETRY_MAX = Number(process.env.MCP_DEVOPS_NETWORK_RETRY_MAX || 1);
const NETWORK_RETRY_BASE_MS = Number(process.env.MCP_DEVOPS_NETWORK_RETRY_BASE_MS || 1250);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const truncateMessage = (value = '') => {
  const str = String(value);
  if (str.length <= MAX_LOG_MESSAGE_CHARS) return str;
  return `${str.slice(0, MAX_LOG_MESSAGE_CHARS)}\n[truncated]`;
};

const collectLogsText = (logs = []) =>
  logs
    .map((entry) => `${entry.stream}:${entry.message}`)
    .join('\n');

const classifyFailure = ({ exitCode, logs, error }) => {
  if (error) {
    if (error.code === 'ENOENT') return 'ERR_COMMAND_NOT_FOUND';
    if (error.code === 'EACCES') return 'ERR_PERMISSION_DENIED';
    return 'ERR_SPAWN_FAILED';
  }

  if (typeof exitCode === 'number' && exitCode === 0) return null;

  const text = collectLogsText(logs).toLowerCase();
  if (
    text.includes('enotfound') ||
    text.includes('etimedout') ||
    text.includes('econnreset') ||
    text.includes('eai_again') ||
    text.includes('could not resolve host') ||
    text.includes('temporary failure in name resolution')
  ) {
    return 'ERR_NETWORK';
  }

  if (
    text.includes('unexpected eof while looking for matching') ||
    text.includes('syntax error near unexpected token') ||
    text.includes('parsererror') ||
    text.includes('missing the terminator')
  ) {
    return 'ERR_QUOTING_PARSE';
  }

  if (text.includes('permission denied') || text.includes('access is denied')) {
    return 'ERR_PERMISSION_DENIED';
  }

  return 'ERR_NONZERO_EXIT';
};

const makePosixCommand = (runner) => {
  const { shell = config.deployShell } = runner;
  const repoPath = shell.repoPath || runner.cwd || config.repoRootPosix;
  const scriptRefRaw = runner.scriptRelative || '';
  const shouldPrefix =
    !!scriptRefRaw &&
    !scriptRefRaw.startsWith('./') &&
    !scriptRefRaw.startsWith('/') &&
    !/\s/.test(scriptRefRaw);
  const scriptRef = shouldPrefix ? `./${scriptRefRaw}`.replace(/\/{2,}/g, '/') : scriptRefRaw;

  const commandParts = [`cd ${repoPath}`];
  commandParts.push(scriptRef);

  const commandBody = commandParts.join(' && ');

  const shellArgs = [...(shell.args || [])];

  if (shell.type === 'wsl') {
    return {
      command: shell.command || 'wsl',
      args: [...shellArgs, 'bash', '-lc', commandBody]
    };
  }

  return {
    command: shell.command || 'bash',
    args: [...shellArgs, '-lc', commandBody]
  };
};

const runProcess = ({ command, args, options, hooks, phase }) =>
  new Promise((resolve) => {
    const logs = [];
    let logTruncated = false;
    const start = performance.now();
    const child = spawn(command, args, options);

    const appendLog = (entry) => {
      if (logs.length >= MAX_PROCESS_LOGS) {
        logTruncated = true;
        return;
      }
      const normalized = { stream: entry.stream, message: truncateMessage(entry.message) };
      logs.push(normalized);
      hooks?.onLog?.({ ...normalized, phase });
    };

    child.stdout.on('data', (data) => {
      appendLog({ stream: 'stdout', message: data.toString() });
    });

    child.stderr.on('data', (data) => {
      appendLog({ stream: 'stderr', message: data.toString() });
    });

    child.on('error', (err) => {
      const durationMs = Math.round(performance.now() - start);
      const errorCode = classifyFailure({ exitCode: -1, logs, error: err });
      resolve({ exitCode: -1, logs, durationMs, errorCode, logTruncated, error: err });
    });

    child.on('close', (code) => {
      const durationMs = Math.round(performance.now() - start);
      const exitCode = code ?? -1;
      const errorCode = classifyFailure({ exitCode, logs, error: null });
      resolve({ exitCode, logs, durationMs, errorCode, logTruncated });
    });
  });

const runWithRetry = async ({ command, args, options, hooks, phase }) => {
  const attempts = [];
  let attempt = 0;
  while (true) {
    const result = await runProcess({ command, args, options, hooks, phase });
    const commandString = `${command} ${args.join(' ')}`;
    attempts.push({
      attempt: attempt + 1,
      command: commandString,
      exit_code: result.exitCode,
      duration_ms: result.durationMs,
      error_code: result.errorCode || null,
      log_truncated: Boolean(result.logTruncated)
    });

    if (!result.errorCode) {
      return { ...result, attempts, command: commandString };
    }

    if (result.errorCode === 'ERR_NETWORK' && attempt < NETWORK_RETRY_MAX) {
      const delay = NETWORK_RETRY_BASE_MS * Math.pow(2, attempt);
      await sleep(delay);
      attempt += 1;
      continue;
    }

    return { ...result, attempts, command: commandString };
  }
};

export const executeWorkflow = async (workflow, { dryRun = false, hooks = {}, phase = 'main' } = {}) => {
  if (!workflow?.runner) {
    throw new Error('Workflow runner configuration missing.');
  }

  if (workflow.runner.type === 'powershell') {
    const scriptPath = workflow.runner.scriptPath;
    if (!scriptPath) {
      throw new Error('PowerShell workflow missing scriptPath.');
    }
    const baseArgs = [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      scriptPath,
      ...(workflow.runner.args || [])
    ];

    const commandString = `${config.powershellExe} ${baseArgs.join(' ')}`;
    hooks?.setCommand?.(commandString, phase);

    if (dryRun) {
      return {
        dryRun: true,
        command: commandString,
        logs: [],
        exitCode: null,
        durationMs: 0,
        errorCode: null,
        attempts: []
      };
    }

    const result = await runWithRetry({
      command: config.powershellExe,
      args: baseArgs,
      options: {
        cwd: workflow.runner.cwd || config.repoRoot,
        env: { ...process.env, ...(workflow.runner.env || {}) },
        stdio: 'pipe'
      },
      hooks,
      phase
    });
    return { ...result, command: commandString };
  }

  if (workflow.runner.type === 'posix') {
    const posix = makePosixCommand(workflow.runner);
    const commandString = `${posix.command} ${posix.args.join(' ')}`;
    hooks?.setCommand?.(commandString, phase);

    if (dryRun) {
      return {
        dryRun: true,
        command: commandString,
        logs: [],
        exitCode: null,
        durationMs: 0,
        errorCode: null,
        attempts: []
      };
    }

    const result = await runWithRetry({
      command: posix.command,
      args: posix.args,
      options: {
        cwd: workflow.runner.cwd || config.repoRoot,
        env: { ...process.env, ...(workflow.runner.env || {}) },
        stdio: 'pipe'
      },
      hooks,
      phase
    });
    return { ...result, command: commandString };
  }

  throw new Error(`Unsupported runner type: ${workflow.runner.type}`);
};
