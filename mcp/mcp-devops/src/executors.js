import { spawn } from 'child_process';
import { performance } from 'perf_hooks';
import path from 'path';
import { config } from './config.js';

const escapeDoubleQuotes = (value = '') =>
  String(value).replace(/(["$`\\])/g, (match) => `\\${match}`);

const makePosixCommand = (runner) => {
  const { shell = config.deployShell, env = {} } = runner;
  const repoPath = shell.repoPath || runner.cwd || config.repoRootPosix;
  const exports =
    Object.entries(env).length > 0
      ? Object.entries(env)
          .map(([key, value]) => `export ${key}="${escapeDoubleQuotes(value)}"`)
          .join(' && ')
      : '';
  const scriptRef = runner.scriptRelative?.startsWith('./')
    ? runner.scriptRelative
    : `./${runner.scriptRelative || ''}`.replace(/\/{2,}/g, '/');

  const commandParts = [`cd ${repoPath}`];
  if (exports) {
    commandParts.push(exports);
  }
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
  new Promise((resolve, reject) => {
    const logs = [];
    const start = performance.now();
    const child = spawn(command, args, options);

    child.stdout.on('data', (data) => {
      const message = data.toString();
      const entry = { stream: 'stdout', message };
      logs.push(entry);
      hooks?.onLog?.({ ...entry, phase });
    });

    child.stderr.on('data', (data) => {
      const message = data.toString();
      const entry = { stream: 'stderr', message };
      logs.push(entry);
      hooks?.onLog?.({ ...entry, phase });
    });

    child.on('error', (err) => {
      reject(err);
    });

    child.on('close', (code) => {
      const durationMs = Math.round(performance.now() - start);
      resolve({ exitCode: code ?? -1, logs, durationMs });
    });
  });

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
        durationMs: 0
      };
    }

    return runProcess({
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
        durationMs: 0
      };
    }

    return runProcess({
      command: posix.command,
      args: posix.args,
      options: {
        cwd: workflow.runner.cwd || config.repoRoot,
        env: { ...process.env },
        stdio: 'pipe'
      },
      hooks,
      phase
    });
  }

  throw new Error(`Unsupported runner type: ${workflow.runner.type}`);
};
