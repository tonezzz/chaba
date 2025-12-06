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
const defaultPowerShell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
const defaultWsl = 'wsl';
const defaultBash = 'bash';

const toPosix = (inputPath = '') => inputPath.replace(/\\+/g, '/');

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

export const config = {
  port: Number(process.env.MCP_DEVOPS_PORT || 8320),
  repoRoot,
  scriptsRoot,
  repoRootPosix,
  powershellExe: process.env.MCP_DEVOPS_POWERSHELL || defaultPowerShell,
  devHostBaseUrl: process.env.DEV_HOST_BASE_URL || 'http://dev-host.pc1:3000',
  devHostPc2BaseUrl: process.env.DEV_HOST_PC2_BASE_URL || 'http://dev-host.pc2:3000',
  deploy: {
    scriptRelative: path.join('scripts', 'deploy-a1-idc1.sh'),
    sshUser: process.env.A1_DEPLOY_SSH_USER || 'chaba',
    sshHost: process.env.A1_DEPLOY_SSH_HOST || 'a1.idc1.surf-thailand.com',
    sshPort: process.env.A1_DEPLOY_SSH_PORT || '22',
    sshKeyPath:
      process.env.A1_DEPLOY_SSH_KEY_PATH ||
      path.join(repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519'),
    remoteBase: process.env.A1_DEPLOY_REMOTE_BASE || '/www/a1.idc-1.surf-thailand.com',
    envDir: process.env.A1_DEPLOY_ENV_DIR || path.join(repoRoot, '.secrets', 'dev-host'),
    releasesToKeep: process.env.A1_DEPLOY_RELEASES || '5'
  },
  verify: {
    a1Idc1TestUrl:
      process.env.A1_IDC1_TEST_URL || 'https://a1.idc1.surf-thailand.com/test'
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