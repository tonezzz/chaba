import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const localEnv = path.resolve(__dirname, '..', '.env');
const repoEnv = path.resolve(__dirname, '..', '..', '..', '.env');
dotenv.config({ path: localEnv, override: false });
dotenv.config({ path: repoEnv, override: false });

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const scriptsRoot = path.join(repoRoot, 'scripts');
const stacksRoot = path.join(repoRoot, 'stacks');
const defaultPowerShell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
const defaultWsl = 'wsl';
const defaultBash = 'bash';

const toPosix = (inputPath = '') => inputPath.replace(/\\+/g, '/');
const trimTrailingSlash = (value = '') => value.replace(/\/+$/, '');

const windowsToWsl = (windowsPath = '') => {
  const match = windowsPath.match(/^([A-Za-z]):\\(.*)$/);
  if (!match) {
    return toPosix(windowsPath);
  }
  const drive = match[1].toLowerCase();
  const rest = match[2].replace(/\\+/g, '/');
  return `/mnt/${drive}/${rest}`;
};

const repoRootPosix = process.platform === 'win32' ? windowsToWsl(repoRoot) : repoRoot;
const defaultMcp0BaseUrl = trimTrailingSlash(
  process.env.MCP0_PROXY_BASE_URL || process.env.MCP0_BASE_URL || 'http://mcp0:8310'
);
const defaultPc2Mcp0BaseUrl = trimTrailingSlash(
  process.env.PC2_MCP0_BASE_URL || defaultMcp0BaseUrl
);

const parseArgs = (value = '') =>
  value
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean);

const makeShellConfig = () => {
  if (process.platform === 'win32') {
    const wslArgs = [];
    const wslUser = process.env.MCP_DEVOPS_WSL_USER || 'tonezzz';
    if (wslUser) {
      wslArgs.push('-u', wslUser);
    }
    if (process.env.MCP_DEVOPS_WSL_DISTRO) {
      wslArgs.push('-d', process.env.MCP_DEVOPS_WSL_DISTRO);
    }
    if (process.env.MCP_DEVOPS_WSL_ARGS) {
      wslArgs.push(...parseArgs(process.env.MCP_DEVOPS_WSL_ARGS));
    }
    return {
      type: 'wsl',
      command: process.env.MCP_DEVOPS_WSL || defaultWsl,
      args: wslArgs,
      repoPath: repoRootPosix
    };
  }

  return {
    type: 'bash',
    command: process.env.MCP_DEVOPS_BASH || defaultBash,
    args: parseArgs(process.env.MCP_DEVOPS_BASH_ARGS || ''),
    repoPath: repoRoot
  };
};

const posixShell = makeShellConfig();
const nodeShell = makeShellConfig();

const assertPathExists = (targetPath, label) => {
  if (!targetPath) {
    throw new Error(`Missing path for ${label}`);
  }
  if (!fs.existsSync(targetPath)) {
    throw new Error(`Configured ${label} path does not exist: ${targetPath}`);
  }
};

export const config = {
  port: Number(process.env.MCP_DEVOPS_PORT || 8320),
  host: process.env.MCP_DEVOPS_HOST || '127.0.0.1',
  repoRoot,
  scriptsRoot,
  stacksRoot,
  repoRootPosix,
  powershellExe: process.env.MCP_DEVOPS_POWERSHELL || defaultPowerShell,
  devHostBaseUrl: process.env.DEV_HOST_BASE_URL || 'http://dev-host.pc1',
  devHostPc2BaseUrl: process.env.DEV_HOST_PC2_BASE_URL || 'http://dev-host.pc2:3000',
  pcWorker: (() => {
    const composeFile = path.join(stacksRoot, 'pc2-worker', 'docker-compose.yml');
    const scriptsDir = path.join(repoRoot, 'scripts', 'pc2-worker');
    const imagenDir = path.join(repoRoot, 'mcp', 'mcp-imagen');
    try {
      assertPathExists(composeFile, 'pc2-worker compose');
      assertPathExists(scriptsDir, 'pc2-worker scripts');
      assertPathExists(imagenDir, 'mcp-imagen');
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[mcp-devops] configuration warning:', err.message);
    }
    return {
      composeFile,
      scriptsDir,
      imagenDir,
      imagenServicePort: process.env.MCP_IMAGEN_GPU_PORT || '8001',
      modelosRoot: process.env.VOICE_CHAT_MODEL_ROOT || 'C:/_dev/_models/diffusers'
    };
  })(),
  deploy: {
    scriptRelative: path.join('scripts', 'deploy-a1-idc1.sh'),
    sshUser: process.env.A1_DEPLOY_SSH_USER || 'chaba',
    sshHost: process.env.A1_DEPLOY_SSH_HOST || 'a1.idc1.surf-thailand.com',
    sshPort: process.env.A1_DEPLOY_SSH_PORT || '22',
    sshKeyPath:
      process.env.A1_DEPLOY_SSH_KEY_PATH ||
      path.join(repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519'),
    remoteBase: process.env.A1_DEPLOY_REMOTE_BASE || '/www/a1.idc1.surf-thailand.com',
    envDir: process.env.A1_DEPLOY_ENV_DIR || path.join(repoRoot, '.secrets', 'dev-host'),
    releasesToKeep: process.env.A1_DEPLOY_RELEASES || '5'
  },
  devHostDeploy: {
    sshUser: process.env.DEV_HOST_DEPLOY_SSH_USER || 'tonezzz',
    sshHost: process.env.DEV_HOST_DEPLOY_SSH_HOST || 'dev-host.pc1',
    sshPort: process.env.DEV_HOST_DEPLOY_SSH_PORT || '22',
    sshKeyPath:
      process.env.DEV_HOST_DEPLOY_SSH_KEY_PATH ||
      (process.platform === 'win32'
        ? '/home/tonezzz/.ssh/chaba_ed25519'
        : path.join(process.env.HOME || '/home/tonezzz', '.ssh', 'chaba_ed25519')),
    remoteBase: process.env.DEV_HOST_DEPLOY_REMOTE_BASE || '/var/www/a1',
    envDir: process.env.DEV_HOST_DEPLOY_ENV_DIR || path.join(repoRoot, '.secrets', 'dev-host'),
    releasesToKeep: process.env.DEV_HOST_DEPLOY_RELEASES || '10'
  },
  verify: {
    a1Idc1TestUrl:
      process.env.A1_IDC1_TEST_URL || 'https://a1.idc1.surf-thailand.com/test'
  },
  mcp0: {
    baseUrl: trimTrailingSlash(
      process.env.MCP0_PROXY_BASE_URL || process.env.MCP0_BASE_URL || 'http://mcp0:8310'
    ),
    adminToken: process.env.MCP0_ADMIN_TOKEN || '',
    dockerProvider: process.env.MCP0_DOCKER_PROVIDER || 'mcp-docker',
    dockerLogContainers: process.env.MCP_DOCKER_LOG_CONTAINERS || 'dev-host'
  },
  pc2Host: {
    sshUser: process.env.PC2_SSH_USER || 'chaba',
    sshHost: process.env.PC2_SSH_HOST || 'pc2',
    sshPort: process.env.PC2_SSH_PORT || '22',
    sshKeyPath:
      process.env.PC2_SSH_KEY_PATH ||
      (process.platform === 'win32'
        ? '/home/tonezzz/.ssh/chaba_ed25519'
        : path.join(process.env.HOME || '/home/tonezzz', '.ssh', 'chaba_ed25519')),
    wslUser: process.env.PC2_WSL_USER || process.env.MCP_DEVOPS_WSL_USER || 'tonezzz',
    remoteStacksDir: process.env.PC2_STACKS_DIR || '/home/chaba/chaba/stacks',
    workerDirName: process.env.PC2_WORKER_DIR || 'pc2-worker',
    dockerHost: process.env.PC2_DOCKER_HOST || 'unix:///var/run/docker.sock'
  },
  uiBuild: {
    docs: 'README.md#mcp-tools',
    cwd: repoRoot
  },
  shells: {
    posix: posixShell,
    node: nodeShell
  },
  deployShell: posixShell,
  toPosix,
  windowsToWsl
};