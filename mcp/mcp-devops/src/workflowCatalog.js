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
    id: 'deploy-dev-host-mirror',
    label: 'Deploy dev-host mirror (pc1)',
    description:
      'Mirrors the latest a1-idc1 site assets to dev-host.pc1 using the deploy-node-1 pipeline with dev-host credentials.',
    tags: ['deploy', 'dev-host', 'mirror'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/deploy-dev-host-mirror.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: config.devHostDeploy.sshUser,
        SSH_HOST: config.devHostDeploy.sshHost,
        SSH_PORT: config.devHostDeploy.sshPort,
        SSH_KEY_PATH: toPosixIfNeeded(config.devHostDeploy.sshKeyPath),
        REMOTE_BASE: config.devHostDeploy.remoteBase,
        LOCAL_BASE: toPosixIfNeeded(path.join(config.repoRoot, 'sites')),
        ENV_DIR: toPosixIfNeeded(config.devHostDeploy.envDir),
        APPS: 'a1-idc1',
        RELEASES_TO_KEEP: config.devHostDeploy.releasesToKeep
      },
      shell: config.deployShell
    },
    outputs: {
      previewUrl: 'http://dev-host.pc1:80/test/',
      docs: 'scripts/deploy-dev-host-mirror.sh'
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
      scriptRelative: './scripts/build-ui.sh',
      cwd: config.repoRoot,
      shell: config.shells.node,
      env: {
        VOICE_CHAT_REPO: config.pcWorker?.voiceChatRepo || '',
        VOICE_CHAT_MODEL_ROOT: config.pcWorker?.modelosRoot || ''
      }
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
  },
  {
    id: 'diagnostics-dev-host',
    label: 'Collect dev-host container diagnostics',
    description:
      'Invokes MCP0/mcp-docker to list containers and fetch logs for configured dev-host services to unblock preview issues.',
    tags: ['diagnostics', 'dev-host', 'mcp0'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/diagnostics-dev-host.sh',
      cwd: config.repoRoot,
      docs: 'scripts/diagnostics-dev-host.mjs'
    }
  },
  {
    id: 'pc2-stack-status',
    label: 'PC2 stack status',
    description: 'Uses wsl+ssh to run `docker compose ps` for the pc2-worker stack on host pc2.',
    tags: ['pc2', 'docker', 'status'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc2-worker', 'pc2-stack.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot,
      env: {
        PC2_SSH_USER: config.pc2Host.sshUser,
        PC2_SSH_HOST: config.pc2Host.sshHost,
        PC2_SSH_PORT: config.pc2Host.sshPort,
        PC2_SSH_KEY_PATH: config.pc2Host.sshKeyPath,
        PC2_WSL_USER: config.pc2Host.wslUser,
        PC2_STACKS_DIR: config.pc2Host.remoteStacksDir,
        PC2_WORKER_DIR: config.pc2Host.workerDirName,
        PC2_DOCKER_HOST: config.pc2Host.dockerHost
      }
    },
    outputs: {
      docs: 'scripts/pc2-worker/pc2-stack.ps1'
    }
  },
  {
    id: 'pc2-stack-up',
    label: 'PC2 stack up (mcp-suite)',
    description:
      'Brings up the pc2-worker Docker compose stack on host pc2 using the configured profile (default mcp-suite).',
    tags: ['pc2', 'docker', 'up'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc2-worker', 'pc2-stack.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot,
      env: {
        PC2_SSH_USER: config.pc2Host.sshUser,
        PC2_SSH_HOST: config.pc2Host.sshHost,
        PC2_SSH_PORT: config.pc2Host.sshPort,
        PC2_SSH_KEY_PATH: config.pc2Host.sshKeyPath,
        PC2_WSL_USER: config.pc2Host.wslUser,
        PC2_STACKS_DIR: config.pc2Host.remoteStacksDir,
        PC2_WORKER_DIR: config.pc2Host.workerDirName
      }
    },
    outputs: {
      docs: 'scripts/pc2-worker/pc2-stack.ps1'
    }
  },
  {
    id: 'pc2-stack-down',
    label: 'PC2 stack down',
    description: 'Stops the pc2-worker Docker compose stack on host pc2.',
    tags: ['pc2', 'docker', 'down'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc2-worker', 'pc2-stack.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot,
      env: {
        PC2_SSH_USER: config.pc2Host.sshUser,
        PC2_SSH_HOST: config.pc2Host.sshHost,
        PC2_SSH_PORT: config.pc2Host.sshPort,
        PC2_SSH_KEY_PATH: config.pc2Host.sshKeyPath,
        PC2_WSL_USER: config.pc2Host.wslUser,
        PC2_STACKS_DIR: config.pc2Host.remoteStacksDir,
        PC2_WORKER_DIR: config.pc2Host.workerDirName
      }
    },
    outputs: {
      docs: 'scripts/pc2-worker/pc2-stack.ps1'
    }
  }
];

export const listWorkflowMetadata = () =>
  workflows.map(({ runner, ...rest }) => ({
    ...rest
  }));

export const findWorkflow = (id) => workflows.find((wf) => wf.id === id);
