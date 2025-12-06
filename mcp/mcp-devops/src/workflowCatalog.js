import path from 'path';
import { config } from './config.js';

const previewTestTags = ['preview', 'dev-host', 'test'];
const toPosixIfNeeded = (value) =>
  process.platform === 'win32' ? config.windowsToWsl(value) : value;

const workflows = [
  {
    id: 'preview-detects',
    label: 'Preview /test/detects',
    description: 'Brings up dev-host and the detects API via PowerShell script, then validates the proxy.',
    tags: [...previewTestTags, 'detects'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'preview-detects.ps1'),
      args: ['-DevHostBaseUrl', config.devHostBaseUrl],
      cwd: config.repoRoot
    },
    outputs: {
      previewUrl: `${config.devHostBaseUrl}/test/detects/`,
      docs: 'scripts/preview-detects.ps1'
    }
  },
  {
    id: 'preview-test-suite',
    label: 'Preview /test (chat + agents + detects)',
    description:
      'Boots Glama/chat, agents, and detects APIs via PM2, validates all dev-host proxies, and confirms /test landing readiness.',
    tags: [...previewTestTags, 'chat', 'agents'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'preview-test.ps1'),
      args: ['-DevHostBaseUrl', config.devHostBaseUrl],
      cwd: config.repoRoot
    },
    outputs: {
      previewUrl: `${config.devHostBaseUrl}/test/`,
      docs: 'scripts/preview-test.ps1'
    }
  },
  {
    id: 'preview-vaja',
    label: 'Preview VAJA MCP demo',
    description:
      'Starts the dev proxy + mcp-vaja containers for PC2, validates the VAJA MCP health endpoint, and confirms the dev-host proxy.',
    tags: ['preview', 'dev-host', 'vaja'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'preview-vaja.ps1'),
      args: ['-DevHostBaseUrl', config.devHostPc2BaseUrl],
      cwd: config.repoRoot
    },
    outputs: {
      previewUrl: `${config.devHostPc2BaseUrl}/test/vaja`,
      docs: 'scripts/preview-vaja.ps1'
    }
  },
  {
    id: 'deploy-a1-idc1',
    label: 'Deploy a1-idc1 production site',
    description:
      'Wraps scripts/deploy-a1-idc1.sh via Bash/WSL to rsync site assets, push env files, install dependencies, and promote the new release.',
    tags: ['deploy', 'publish', 'production'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/deploy-a1-idc1.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: config.deploy.sshUser,
        SSH_HOST: config.deploy.sshHost,
        SSH_PORT: config.deploy.sshPort,
        SSH_KEY_PATH: toPosixIfNeeded(config.deploy.sshKeyPath),
        REMOTE_BASE: config.deploy.remoteBase,
        LOCAL_BASE: toPosixIfNeeded(path.join(config.repoRoot, 'sites')),
        ENV_DIR: toPosixIfNeeded(config.deploy.envDir),
        APPS: 'a1-idc1',
        RELEASES_TO_KEEP: config.deploy.releasesToKeep
      },
      shell: config.deployShell
    },
    outputs: {
      publicUrl: 'https://a1.idc1.surf-thailand.com',
      docs: 'scripts/deploy-a1-idc1.sh'
    }
  },
  {
    id: 'build-ui',
    label: 'Build UI bundle',
    description:
      'Runs npm run build:deploy at repo root (assumes npm run build:deploy is defined to build + sync client assets).',
    tags: ['build', 'ui'],
    runner: {
      type: 'posix',
      scriptRelative: 'npm run build:deploy',
      cwd: config.repoRoot,
      shell: config.shells.node,
      env: {}
    },
    outputs: {
      docs: config.uiBuild.docs
    }
  },
  {
    id: 'sync-env-a1-idc1',
    label: 'Sync a1-idc1 environment files only',
    description:
      'Uploads latest .env for a1-idc1 to the remote server without rsyncing site files or promoting releases.',
    tags: ['deploy', 'env', 'sync'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/sync-env-a1-idc1.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: config.deploy.sshUser,
        SSH_HOST: config.deploy.sshHost,
        SSH_PORT: config.deploy.sshPort,
        SSH_KEY_PATH: toPosixIfNeeded(config.deploy.sshKeyPath),
        REMOTE_BASE: config.deploy.remoteBase,
        ENV_DIR: toPosixIfNeeded(config.deploy.envDir),
        APP: 'a1-idc1'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/sync-env-a1-idc1.sh'
    }
  },
  {
    id: 'verify-a1-idc1-test',
    label: 'Verify a1-idc1 /test endpoint',
    description:
      'Curls https://a1.idc1.surf-thailand.com/test multiple times with backoff to confirm post-deploy readiness.',
    tags: ['verify', 'deploy', 'publish'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/verify-a1-idc1-test.sh',
      cwd: config.repoRoot,
      env: {
        TARGET_URL: config.verify.a1Idc1TestUrl
      },
      shell: config.deployShell
    },
    outputs: {
      publicUrl: config.verify.a1Idc1TestUrl,
      docs: 'scripts/verify-a1-idc1-test.sh'
    }
  },
  {
    id: 'diagnostics-a1-idc1',
    label: 'Capture diagnostics from a1-idc1 host',
    description:
      'Runs a set of SSH commands (uptime, disk, releases, processes) and curls the public endpoint to aid troubleshooting.',
    tags: ['diagnostics', 'deploy', 'ssh'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/diagnostics-a1-idc1.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: config.deploy.sshUser,
        SSH_HOST: config.deploy.sshHost,
        SSH_PORT: config.deploy.sshPort,
        SSH_KEY_PATH: toPosixIfNeeded(config.deploy.sshKeyPath),
        REMOTE_TEST_URL: config.verify.a1Idc1TestUrl
      },
      shell: config.deployShell
    },
    outputs: {
      publicUrl: config.verify.a1Idc1TestUrl,
      docs: 'scripts/diagnostics-a1-idc1.sh'
    }
  }
];

export const listWorkflowMetadata = () =>
  workflows.map(({ runner, ...rest }) => ({
    ...rest
  }));

export const findWorkflow = (id) => workflows.find((wf) => wf.id === id);
