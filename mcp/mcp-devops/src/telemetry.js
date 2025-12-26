import os from 'os';
import { execFile } from 'child_process';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

const MAX_TEXT_CHARS = Number(process.env.MCP_DEVOPS_TELEMETRY_MAX_TEXT_CHARS || 12000);
const DEFAULT_TIMEOUT_MS = Number(process.env.MCP_DEVOPS_TELEMETRY_TIMEOUT_MS || 6000);

const clampText = (value = '', maxChars = MAX_TEXT_CHARS) => {
  const str = String(value ?? '');
  if (str.length <= maxChars) return str;
  return `${str.slice(0, maxChars)}\n[truncated]`;
};

const safeExec = async (command, args, { timeoutMs = DEFAULT_TIMEOUT_MS, cwd, env, maxChars } = {}) => {
  try {
    const result = await execFileAsync(command, args, {
      timeout: timeoutMs,
      cwd,
      env,
      windowsHide: true,
      maxBuffer: Math.min(1024 * 1024 * 8, Math.max(1024 * 16, (maxChars || MAX_TEXT_CHARS) * 2))
    });
    return {
      ok: true,
      exit_code: 0,
      stdout: clampText(result.stdout || '', maxChars),
      stderr: clampText(result.stderr || '', maxChars)
    };
  } catch (err) {
    return {
      ok: false,
      exit_code: typeof err?.code === 'number' ? err.code : -1,
      stdout: clampText(err?.stdout || '', maxChars),
      stderr: clampText(err?.stderr || err?.message || 'command_failed', maxChars)
    };
  }
};

const bytes = (n) => (typeof n === 'number' ? n : null);

const getBaseTelemetry = () => {
  const cpus = os.cpus() || [];
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const memUsed = totalMem - freeMem;

  return {
    timestamp: new Date().toISOString(),
    platform: {
      platform: process.platform,
      arch: process.arch,
      release: os.release(),
      hostname: os.hostname(),
      uptime_seconds: Math.floor(os.uptime())
    },
    runtime: {
      node: process.version,
      pid: process.pid
    },
    cpu: {
      logical_cores: cpus.length,
      model: cpus[0]?.model || null
    },
    memory: {
      total_bytes: bytes(totalMem),
      free_bytes: bytes(freeMem),
      used_bytes: bytes(memUsed),
      used_percent: totalMem > 0 ? Math.round((memUsed / totalMem) * 1000) / 10 : null
    }
  };
};

const parseTasklistCsv = (text, maxRows) => {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  const rows = [];
  for (const line of lines) {
    if (rows.length >= maxRows) break;
    const trimmed = line.trim();
    if (!trimmed.startsWith('"')) continue;
    const parts = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < trimmed.length; i += 1) {
      const ch = trimmed[i];
      if (ch === '"') {
        inQuotes = !inQuotes;
        continue;
      }
      if (ch === ',' && !inQuotes) {
        parts.push(cur);
        cur = '';
        continue;
      }
      cur += ch;
    }
    parts.push(cur);

    const image = parts[0]?.trim() || null;
    const pid = Number(parts[1]) || null;
    const memRaw = parts[4] || '';
    const memMb = Number(String(memRaw).replace(/[^0-9]/g, '')) || null;
    rows.push({ image, pid, mem_mb: memMb });
  }
  return rows;
};

const getProcesses = async ({ maxProcesses = 15 } = {}) => {
  if (process.platform === 'win32') {
    const tasklist = await safeExec('tasklist', ['/FO', 'CSV', '/NH'], { maxChars: 200000 });
    if (!tasklist.ok) {
      return { ok: false, error: tasklist.stderr || 'tasklist_failed', processes: [] };
    }
    return { ok: true, processes: parseTasklistCsv(tasklist.stdout, maxProcesses) };
  }

  const ps = await safeExec('ps', ['-eo', 'pid,comm,rss', '--no-headers'], { maxChars: 200000 });
  if (!ps.ok) {
    return { ok: false, error: ps.stderr || 'ps_failed', processes: [] };
  }

  const processes = String(ps.stdout || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/);
      const pid = Number(parts[0]) || null;
      const command = parts[1] || null;
      const rssKb = Number(parts[2]) || null;
      return { pid, command, rss_kb: rssKb };
    })
    .slice(0, maxProcesses);

  return { ok: true, processes };
};

const getDisk = async () => {
  if (process.platform === 'win32') {
    const result = await safeExec('wmic', ['logicaldisk', 'get', 'Caption,FreeSpace,Size'], {
      maxChars: 12000
    });
    return result.ok
      ? { ok: true, raw: result.stdout }
      : { ok: false, error: result.stderr || 'wmic_failed' };
  }

  const df = await safeExec('df', ['-h'], { maxChars: 12000 });
  return df.ok ? { ok: true, raw: df.stdout } : { ok: false, error: df.stderr || 'df_failed' };
};

const getDocker = async ({ maxContainers = 20 } = {}) => {
  const info = await safeExec('docker', ['info', '--format', '{{json .}}'], { maxChars: 12000 });
  const ps = await safeExec(
    'docker',
    ['ps', '--no-trunc', '--format', '{{.Names}}\t{{.Status}}\t{{.Image}}', '--limit', String(maxContainers)],
    { maxChars: 20000 }
  );

  const parsedInfo = (() => {
    if (!info.ok) return null;
    try {
      return JSON.parse(info.stdout);
    } catch {
      return null;
    }
  })();

  return {
    ok: Boolean(info.ok || ps.ok),
    info_ok: info.ok,
    ps_ok: ps.ok,
    info: parsedInfo,
    containers_raw: ps.ok ? ps.stdout : null,
    error: !info.ok && !ps.ok ? info.stderr || ps.stderr || 'docker_failed' : null
  };
};

const computeInsights = ({ telemetry, question }) => {
  const insights = [];
  const mem = telemetry.memory;

  if (typeof mem?.used_percent === 'number') {
    if (mem.used_percent >= 90) {
      insights.push({ severity: 'high', title: 'Memory pressure', detail: `RAM usage is ${mem.used_percent}%` });
    } else if (mem.used_percent >= 75) {
      insights.push({ severity: 'medium', title: 'Elevated RAM usage', detail: `RAM usage is ${mem.used_percent}%` });
    }
  }

  if (telemetry.docker && telemetry.docker.ps_ok && typeof telemetry.docker.containers_raw === 'string') {
    const lines = telemetry.docker.containers_raw
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    const unhealthy = lines.filter((l) => l.toLowerCase().includes('unhealthy'));
    if (unhealthy.length > 0) {
      insights.push({
        severity: 'high',
        title: 'Unhealthy containers',
        detail: `Detected ${unhealthy.length} unhealthy container(s) in docker ps output.`
      });
    }
  }

  if (question && typeof question === 'string' && question.trim()) {
    insights.unshift({ severity: 'info', title: 'Question', detail: question.trim() });
  }

  return insights;
};

export const getSystemTelemetry = async ({
  question,
  include_docker = false,
  include_processes = false,
  max_containers = 20,
  max_processes = 15
} = {}) => {
  const telemetry = getBaseTelemetry();

  telemetry.disk = await getDisk();

  if (include_processes) {
    telemetry.processes = await getProcesses({ maxProcesses: max_processes });
  }

  if (include_docker) {
    telemetry.docker = await getDocker({ maxContainers: max_containers });
  }

  telemetry.insights = computeInsights({ telemetry, question });

  return telemetry;
};

const formatBytes = (value) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = value;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${Math.round(v * 10) / 10} ${units[i]}`;
};

export const formatTelemetryReport = (telemetry, { question } = {}) => {
  const lines = [];
  const t = telemetry || {};

  lines.push('System Telemetry Report');
  lines.push('');
  lines.push(`Timestamp: ${t.timestamp || 'n/a'}`);

  if (question && String(question).trim()) {
    lines.push('');
    lines.push(`Asked: ${String(question).trim()}`);
  }

  lines.push('');
  lines.push('Summary');
  lines.push(`- Host: ${t.platform?.hostname || 'n/a'} (${t.platform?.platform || 'n/a'} ${t.platform?.release || ''} ${t.platform?.arch || ''})`);
  lines.push(`- Uptime: ${typeof t.platform?.uptime_seconds === 'number' ? `${t.platform.uptime_seconds}s` : 'n/a'}`);
  lines.push(`- CPU: ${t.cpu?.logical_cores || 'n/a'} cores${t.cpu?.model ? ` (${t.cpu.model})` : ''}`);
  lines.push(
    `- Memory: ${formatBytes(t.memory?.used_bytes)} used / ${formatBytes(t.memory?.total_bytes)} total` +
      (typeof t.memory?.used_percent === 'number' ? ` (${t.memory.used_percent}%)` : '')
  );
  lines.push(`- Runtime: node ${t.runtime?.node || 'n/a'} (pid ${t.runtime?.pid || 'n/a'})`);

  if (Array.isArray(t.insights) && t.insights.length > 0) {
    lines.push('');
    lines.push('Insights');
    for (const item of t.insights) {
      const sev = item.severity ? String(item.severity).toUpperCase() : 'INFO';
      lines.push(`- [${sev}] ${item.title}: ${item.detail}`);
    }
  }

  if (t.disk) {
    lines.push('');
    lines.push('Disk');
    if (t.disk.ok) {
      lines.push(clampText(t.disk.raw || '', 8000));
    } else {
      lines.push(`Disk telemetry unavailable: ${t.disk.error || 'unknown_error'}`);
    }
  }

  if (t.docker) {
    lines.push('');
    lines.push('Docker');
    if (!t.docker.ok) {
      lines.push(`Docker telemetry unavailable: ${t.docker.error || 'unknown_error'}`);
    } else {
      if (t.docker.info) {
        const server = t.docker.info?.ServerVersion || t.docker.info?.ServerVersion;
        const osType = t.docker.info?.OSType || null;
        lines.push(`- Engine: ${server || 'n/a'}${osType ? ` (${osType})` : ''}`);
      }
      if (t.docker.ps_ok && typeof t.docker.containers_raw === 'string') {
        lines.push('');
        lines.push('Containers (bounded)');
        lines.push(clampText(t.docker.containers_raw, 8000));
      }
    }
  }

  if (t.processes) {
    lines.push('');
    lines.push('Processes (bounded)');
    if (!t.processes.ok) {
      lines.push(`Process telemetry unavailable: ${t.processes.error || 'unknown_error'}`);
    } else {
      for (const p of t.processes.processes || []) {
        if (process.platform === 'win32') {
          lines.push(`- ${p.image || 'n/a'} (pid ${p.pid || 'n/a'}) mem ${p.mem_mb ?? 'n/a'} MB`);
        } else {
          lines.push(`- ${p.command || 'n/a'} (pid ${p.pid || 'n/a'}) rss ${p.rss_kb ?? 'n/a'} KB`);
        }
      }
    }
  }

  return clampText(lines.join('\n'), MAX_TEXT_CHARS);
};
