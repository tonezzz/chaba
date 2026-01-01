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
    id: 'pc1-caddy-reload',
    label: 'pc1 Caddy validate + reload',
    description: 'Validates stacks/pc1-stack/Caddyfile inside the pc1-caddy container and reloads it.',
    tags: ['pc1', 'caddy', 'reload', 'tls'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-caddy-reload.ps1'),
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-caddy-reload.ps1'
    }
  },
  {
    id: 'pc1-caddy-status',
    label: 'pc1 Caddy status',
    description: 'Shows pc1-caddy container status (docker ps) in a concise table.',
    tags: ['pc1', 'caddy', 'status'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-caddy-status.ps1'),
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-caddy-status.ps1'
    }
  },
  {
    id: 'pc1-caddy-logs',
    label: 'pc1 Caddy logs (tail)',
    description: 'Prints the last N lines of pc1-caddy logs (non-follow).',
    tags: ['pc1', 'caddy', 'logs'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-caddy-logs.ps1'),
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-caddy-logs.ps1'
    }
  },
  {
    id: 'pc1-caddy-restart',
    label: 'pc1 Caddy restart + validate',
    description: 'Restarts the pc1-caddy container and validates /etc/caddy/Caddyfile.',
    tags: ['pc1', 'caddy', 'restart', 'tls'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-caddy-restart.ps1'),
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-caddy-restart.ps1'
    }
  },
  {
    id: 'pc1-stack-status',
    label: 'pc1-stack status (docker compose ps)',
    description: 'Shows pc1-stack container status for the configured profile.',
    tags: ['pc1', 'stack', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-stack.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-stack.ps1'
    }
  },
  {
    id: 'pc1-stack-up',
    label: 'pc1-stack up (mcp-suite)',
    description: 'Brings up pc1-stack containers in the mcp-suite profile (docker compose up -d).',
    tags: ['pc1', 'stack', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-stack.ps1'),
      args: ['-Action', 'up', '-Profile', 'mcp-suite'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-stack.ps1'
    }
  },
  {
    id: 'pc1-stack-down',
    label: 'pc1-stack down',
    description: 'Stops pc1-stack containers (docker compose down).',
    tags: ['pc1', 'stack', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-stack.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-stack.ps1'
    }
  },
  {
    id: 'pc1-ai-status',
    label: 'pc1-ai status (docker compose ps)',
    description: 'Shows pc1-ai container status (docker compose ps).',
    tags: ['pc1', 'stack', 'pc1-ai', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-ai.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-ai.ps1'
    }
  },
  {
    id: 'pc1-ai-up',
    label: 'pc1-ai up',
    description: 'Brings up pc1-ai containers (docker compose up -d).',
    tags: ['pc1', 'stack', 'pc1-ai', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-ai.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-ai.ps1'
    }
  },
  {
    id: 'pc1-ai-down',
    label: 'pc1-ai down',
    description: 'Stops pc1-ai containers (docker compose down).',
    tags: ['pc1', 'stack', 'pc1-ai', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-ai.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-ai.ps1'
    }
  },
  {
    id: 'pc1-ai-pull',
    label: 'pc1-ai pull images',
    description: 'Runs docker compose pull for pc1-ai.',
    tags: ['pc1', 'stack', 'pc1-ai', 'pull', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-ai.ps1'),
      args: ['-Action', 'pull'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-ai.ps1'
    }
  },
  {
    id: 'pc1-ai-pull-up',
    label: 'pc1-ai pull + up',
    description: 'Runs docker compose pull then up -d for pc1-ai.',
    tags: ['pc1', 'stack', 'pc1-ai', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-ai.ps1'),
      args: ['-Action', 'pull-up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-ai.ps1'
    }
  },
  {
    id: 'pc1-db-status',
    label: 'pc1-db status (docker compose ps)',
    description: 'Shows pc1-db container status (docker compose ps).',
    tags: ['pc1', 'stack', 'pc1-db', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-db.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-db.ps1'
    }
  },
  {
    id: 'pc1-db-up',
    label: 'pc1-db up',
    description: 'Brings up pc1-db containers (docker compose up -d).',
    tags: ['pc1', 'stack', 'pc1-db', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-db.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-db.ps1'
    }
  },
  {
    id: 'pc1-db-down',
    label: 'pc1-db down',
    description: 'Stops pc1-db containers (docker compose down).',
    tags: ['pc1', 'stack', 'pc1-db', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-db.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-db.ps1'
    }
  },
  {
    id: 'pc1-db-pull',
    label: 'pc1-db pull images',
    description: 'Runs docker compose pull for pc1-db.',
    tags: ['pc1', 'stack', 'pc1-db', 'pull', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-db.ps1'),
      args: ['-Action', 'pull'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-db.ps1'
    }
  },
  {
    id: 'pc1-db-pull-up',
    label: 'pc1-db pull + up',
    description: 'Runs docker compose pull then up -d for pc1-db.',
    tags: ['pc1', 'stack', 'pc1-db', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-db.ps1'),
      args: ['-Action', 'pull-up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-db.ps1'
    }
  },
  {
    id: 'pc1-web-status',
    label: 'pc1-web status (docker compose ps)',
    description: 'Shows pc1-web container status (docker compose ps).',
    tags: ['pc1', 'stack', 'pc1-web', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-web.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-web.ps1'
    }
  },
  {
    id: 'pc1-web-up',
    label: 'pc1-web up',
    description: 'Brings up pc1-web containers (docker compose up -d).',
    tags: ['pc1', 'stack', 'pc1-web', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-web.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-web.ps1'
    }
  },
  {
    id: 'pc1-web-down',
    label: 'pc1-web down',
    description: 'Stops pc1-web containers (docker compose down).',
    tags: ['pc1', 'stack', 'pc1-web', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-web.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-web.ps1'
    }
  },
  {
    id: 'pc1-web-pull',
    label: 'pc1-web pull images',
    description: 'Runs docker compose pull for pc1-web.',
    tags: ['pc1', 'stack', 'pc1-web', 'pull', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-web.ps1'),
      args: ['-Action', 'pull'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-web.ps1'
    }
  },
  {
    id: 'pc1-web-pull-up',
    label: 'pc1-web pull + up',
    description: 'Runs docker compose pull then up -d for pc1-web.',
    tags: ['pc1', 'stack', 'pc1-web', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-web.ps1'),
      args: ['-Action', 'pull-up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-web.ps1'
    }
  },
  {
    id: 'pc1-gpu-status',
    label: 'pc1-gpu status (docker compose ps)',
    description: 'Shows pc1-gpu container status (docker compose ps).',
    tags: ['pc1', 'stack', 'pc1-gpu', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-gpu.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-gpu.ps1'
    }
  },
  {
    id: 'pc1-gpu-up',
    label: 'pc1-gpu up',
    description: 'Brings up pc1-gpu containers (docker compose up -d).',
    tags: ['pc1', 'stack', 'pc1-gpu', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-gpu.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-gpu.ps1'
    }
  },
  {
    id: 'pc1-gpu-down',
    label: 'pc1-gpu down',
    description: 'Stops pc1-gpu containers (docker compose down).',
    tags: ['pc1', 'stack', 'pc1-gpu', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-gpu.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-gpu.ps1'
    }
  },
  {
    id: 'pc1-gpu-pull',
    label: 'pc1-gpu pull images',
    description: 'Runs docker compose pull for pc1-gpu.',
    tags: ['pc1', 'stack', 'pc1-gpu', 'pull', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-gpu.ps1'),
      args: ['-Action', 'pull'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-gpu.ps1'
    }
  },
  {
    id: 'pc1-gpu-pull-up',
    label: 'pc1-gpu pull + up',
    description: 'Runs docker compose pull then up -d for pc1-gpu.',
    tags: ['pc1', 'stack', 'pc1-gpu', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-gpu.ps1'),
      args: ['-Action', 'pull-up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-gpu.ps1'
    }
  },
  {
    id: 'pc1-devops-status',
    label: 'pc1-devops status (docker compose ps)',
    description: 'Shows pc1-devops container status (docker compose ps).',
    tags: ['pc1', 'stack', 'pc1-devops', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-devops.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-devops.ps1'
    }
  },
  {
    id: 'pc1-devops-up',
    label: 'pc1-devops up',
    description: 'Brings up pc1-devops containers (docker compose up -d).',
    tags: ['pc1', 'stack', 'pc1-devops', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-devops.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-devops.ps1'
    }
  },
  {
    id: 'pc1-devops-down',
    label: 'pc1-devops down',
    description: 'Stops pc1-devops containers (docker compose down).',
    tags: ['pc1', 'stack', 'pc1-devops', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-devops.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-devops.ps1'
    }
  },
  {
    id: 'pc1-devops-pull',
    label: 'pc1-devops pull images',
    description: 'Runs docker compose pull for pc1-devops.',
    tags: ['pc1', 'stack', 'pc1-devops', 'pull', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-devops.ps1'),
      args: ['-Action', 'pull'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-devops.ps1'
    }
  },
  {
    id: 'pc1-devops-pull-up',
    label: 'pc1-devops pull + up',
    description: 'Runs docker compose pull then up -d for pc1-devops.',
    tags: ['pc1', 'stack', 'pc1-devops', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-devops.ps1'),
      args: ['-Action', 'pull-up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-devops.ps1'
    }
  },
  {
    id: 'pc1-deka-status',
    label: 'pc1-deka status (docker compose ps)',
    description: 'Shows pc1-deka container status (docker compose ps).',
    tags: ['pc1', 'stack', 'pc1-deka', 'status', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-deka.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-deka.ps1'
    }
  },
  {
    id: 'pc1-deka-up',
    label: 'pc1-deka up',
    description: 'Brings up pc1-deka containers (docker compose up -d).',
    tags: ['pc1', 'stack', 'pc1-deka', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-deka.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-deka.ps1'
    }
  },
  {
    id: 'pc1-deka-down',
    label: 'pc1-deka down',
    description: 'Stops pc1-deka containers (docker compose down).',
    tags: ['pc1', 'stack', 'pc1-deka', 'down', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-deka.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-deka.ps1'
    }
  },
  {
    id: 'pc1-deka-pull',
    label: 'pc1-deka pull images',
    description: 'Runs docker compose pull for pc1-deka.',
    tags: ['pc1', 'stack', 'pc1-deka', 'pull', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-deka.ps1'),
      args: ['-Action', 'pull'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-deka.ps1'
    }
  },
  {
    id: 'pc1-deka-pull-up',
    label: 'pc1-deka pull + up',
    description: 'Runs docker compose pull then up -d for pc1-deka.',
    tags: ['pc1', 'stack', 'pc1-deka', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-deka.ps1'),
      args: ['-Action', 'pull-up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-deka.ps1'
    }
  },
  {
    id: 'pc1-self-status',
    label: 'pc1-stack (self) status',
    description:
      'Runs docker compose ps for pc1-stack from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-ai-self-status',
    label: 'pc1-ai (self) status',
    description: 'Runs docker compose ps for pc1-ai from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'pc1-ai', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/stack-self.sh',
      cwd: config.repoRoot,
      env: {
        STACK: 'pc1-ai',
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/stack-self.sh'
    }
  },
  {
    id: 'pc1-db-self-status',
    label: 'pc1-db (self) status',
    description: 'Runs docker compose ps for pc1-db from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'pc1-db', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/stack-self.sh',
      cwd: config.repoRoot,
      env: {
        STACK: 'pc1-db',
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/stack-self.sh'
    }
  },
  {
    id: 'pc1-web-self-status',
    label: 'pc1-web (self) status',
    description: 'Runs docker compose ps for pc1-web from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'pc1-web', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/stack-self.sh',
      cwd: config.repoRoot,
      env: {
        STACK: 'pc1-web',
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/stack-self.sh'
    }
  },
  {
    id: 'pc1-gpu-self-status',
    label: 'pc1-gpu (self) status',
    description: 'Runs docker compose ps for pc1-gpu from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'pc1-gpu', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/stack-self.sh',
      cwd: config.repoRoot,
      env: {
        STACK: 'pc1-gpu',
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/stack-self.sh'
    }
  },
  {
    id: 'pc1-devops-self-status',
    label: 'pc1-devops (self) status',
    description: 'Runs docker compose ps for pc1-devops from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'pc1-devops', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/stack-self.sh',
      cwd: config.repoRoot,
      env: {
        STACK: 'pc1-devops',
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/stack-self.sh'
    }
  },
  {
    id: 'pc1-deka-self-status',
    label: 'pc1-deka (self) status',
    description: 'Runs docker compose ps for pc1-deka from inside mcp-devops (requires docker socket mount).',
    tags: ['pc1', 'stack', 'pc1-deka', 'self', 'status', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/stack-self.sh',
      cwd: config.repoRoot,
      env: {
        STACK: 'pc1-deka',
        ACTION: 'status'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/stack-self.sh'
    }
  },
  {
    id: 'pc1-self-up',
    label: 'pc1-stack (self) up (mcp-suite)',
    description:
      'Runs docker compose up -d for pc1-stack from inside mcp-devops (profile mcp-suite).',
    tags: ['pc1', 'stack', 'self', 'up', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'up',
        PROFILE: 'mcp-suite'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-down',
    label: 'pc1-stack (self) down',
    description: 'Runs docker compose down for pc1-stack from inside mcp-devops.',
    tags: ['pc1', 'stack', 'self', 'down', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'down'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-restart-mcp-devops',
    label: 'pc1-stack (self) restart mcp-devops',
    description: 'Restarts the running mcp-devops service via docker compose restart.',
    tags: ['pc1', 'stack', 'self', 'restart', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'restart-service',
        SERVICE: 'mcp-devops'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-restart-mcp0',
    label: 'pc1-stack (self) restart mcp0',
    description: 'Restarts the running mcp0 service via docker compose restart.',
    tags: ['pc1', 'stack', 'self', 'restart', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'restart-service',
        SERVICE: 'mcp0'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-restart-caddy',
    label: 'pc1-stack (self) restart caddy',
    description: 'Restarts the running caddy service via docker compose restart.',
    tags: ['pc1', 'stack', 'self', 'restart', 'caddy', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'restart-service',
        SERVICE: 'caddy'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-restart-webtop2',
    label: 'pc1-stack (self) restart webtop2',
    description: 'Restarts the running webtop2 service via docker compose restart.',
    tags: ['pc1', 'stack', 'self', 'restart', 'webtop', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'restart-service',
        SERVICE: 'webtop2'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-pull',
    label: 'pc1-stack (self) pull images',
    description: 'Runs docker compose pull for pc1-stack (no up/down).',
    tags: ['pc1', 'stack', 'self', 'pull', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'pull'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'pc1-self-pull-up',
    label: 'pc1-stack (self) pull + up (mcp-suite)',
    description: 'Runs docker compose pull then docker compose up -d (profile mcp-suite) for pc1-stack.',
    tags: ['pc1', 'stack', 'self', 'pull', 'up', 'docker'],
    runner: {
      type: 'posix',
      scriptRelative: 'bash ./scripts/pc1-stack-self.sh',
      cwd: config.repoRoot,
      env: {
        ACTION: 'pull-up',
        PROFILE: 'mcp-suite'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/pc1-stack-self.sh'
    }
  },
  {
    id: 'deploy-pc1-stack',
    label: 'Deploy pc1-stack (self pull + up)',
    description:
      'Production-style deploy for pc1-stack: docker compose pull then up -d using profiles mcp-suite + gpu (host-side PowerShell runner to ensure Windows bind mounts resolve correctly).',
    tags: ['deploy', 'pc1', 'stack', 'self', 'pull', 'up', 'docker'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'pc1-stack.ps1'),
      args: [
        '-Action',
        'pull-up',
        '-Profile',
        'mcp-suite gpu',
        '-Services',
        'caddy 1mcp-agent mcp-openai-gateway mcp-glama mcp-github-models openchat-ui qdrant ollama mcp-rag mcp-cuda mcp-tester mcp-webtops webtops-router mcp-agents mcp-playwright'
      ],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/pc1-stack.ps1'
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
    id: 'ai-app-fast',
    label: 'ai_app fast gates (lint/typecheck/build/publish)',
    description:
      'Runs npm ci + lint + typecheck + build and publishes the Next.js static export into sites/a1-idc1/test/ai_app.',
    tags: ['ai-app', 'nextjs', 'test', 'publish', 'verify'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'ai-app-fast.ps1'),
      cwd: config.repoRoot
    },
    outputs: {
      previewUrl: `${config.devHostBaseUrl}/test/ai_app/`,
      docs: 'scripts/ai-app-fast.ps1'
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
    id: 'dever-deploy-git-branch',
    label: 'Dever deploy via git branch',
    description:
      'Checks out the configured git branch inside WSL and runs release-a1-idc1.ps1 with the standard deploy pipeline (validate/deploy/reload/verify).',
    tags: ['dever', 'deploy', 'git'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'dever-deploy-git-branch.ps1'),
      cwd: config.repoRoot,
      env: {
        MCP_DEVOPS_GIT_BRANCH: process.env.MCP_DEVOPS_GIT_BRANCH || 'main'
      }
    },
    outputs: {
      docs: 'scripts/dever-deploy-git-branch.ps1'
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
    id: 'release-verify-a1-idc1',
    label: 'Run /test verification (no deploy)',
    description:
      'Invokes release-a1-idc1.ps1 with SkipDeploy/SkipReload to re-validate Caddy config and /test landing without modifying releases.',
    tags: ['verify', 'publish', 'powershell'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'release-a1-idc1.ps1'),
      args: ['-SkipDeploy', '-SkipReload'],
      cwd: config.repoRoot
    },
    outputs: {
      publicUrl: config.verify.a1Idc1TestUrl,
      docs: 'scripts/release-a1-idc1.ps1'
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
    id: 'verify-systemd-a1',
    label: 'Gather systemd diagnostics on a1-idc1',
    description:
      'Runs scripts/verify-systemd.ps1 to capture systemctl status, journal logs, service definitions, and environment files for selected units on the production host.',
    tags: ['diagnostics', 'systemd', 'ssh'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'verify-systemd.ps1'),
      cwd: config.repoRoot,
      env: {
        A1_DEPLOY_SSH_USER: config.deploy.sshUser,
        A1_DEPLOY_SSH_HOST: config.deploy.sshHost,
        A1_DEPLOY_SSH_PORT: config.deploy.sshPort,
        A1_DEPLOY_SSH_KEY_PATH: config.deploy.sshKeyPath,
        MCP_DEVOPS_WSL_USER: process.env.MCP_DEVOPS_WSL_USER || 'tonezzz'
      }
    },
    outputs: {
      docs: 'scripts/verify-systemd.ps1'
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
    id: 'idc1-docker-ps',
    label: 'idc1 docker ps',
    description: 'SSH into idc1 and run `docker ps -a` to see container status.',
    tags: ['idc1', 'docker', 'diagnostics'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/idc1-docker-ps.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: process.env.IDC1_DEPLOY_SSH_USER || 'chaba',
        SSH_HOST: process.env.IDC1_DEPLOY_SSH_HOST || 'idc1.surf-thailand.com',
        SSH_PORT: process.env.IDC1_DEPLOY_SSH_PORT || '22',
        SSH_KEY_PATH: toPosixIfNeeded(
          process.env.IDC1_DEPLOY_SSH_KEY_PATH ||
            path.join(config.repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519')
        )
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/idc1-docker-ps.sh'
    }
  },
  {
    id: 'idc1-ls-workspace',
    label: 'idc1 code-server workspace listing',
    description: 'Runs `docker exec idc1-code-server ls /workspaces/chaba` to confirm the repo mount exists.',
    tags: ['idc1', 'diagnostics', 'code-server'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/idc1-ls-workspace.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: process.env.IDC1_DEPLOY_SSH_USER || 'chaba',
        SSH_HOST: process.env.IDC1_DEPLOY_SSH_HOST || 'idc1.surf-thailand.com',
        SSH_PORT: process.env.IDC1_DEPLOY_SSH_PORT || '22',
        SSH_KEY_PATH: toPosixIfNeeded(
          process.env.IDC1_DEPLOY_SSH_KEY_PATH ||
            path.join(config.repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519')
        ),
        CODE_SERVER_CONTAINER: process.env.IDC1_CODE_SERVER_CONTAINER || 'idc1-code-server',
        WORKSPACE_PATH: process.env.IDC1_WORKSPACE_PATH || '/workspaces/chaba'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/idc1-ls-workspace.sh'
    }
  },
  {
    id: 'idc1-health-sweep',
    label: 'idc1 MCP health sweep',
    description: 'SSH into idc1 and curl the local mcp0, mcp-agents, and mcp-devops /health endpoints.',
    tags: ['idc1', 'diagnostics', 'health'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/idc1-health-sweep.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: process.env.IDC1_DEPLOY_SSH_USER || 'chaba',
        SSH_HOST: process.env.IDC1_DEPLOY_SSH_HOST || 'idc1.surf-thailand.com',
        SSH_PORT: process.env.IDC1_DEPLOY_SSH_PORT || '22',
        SSH_KEY_PATH: toPosixIfNeeded(
          process.env.IDC1_DEPLOY_SSH_KEY_PATH ||
            path.join(config.repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519')
        ),
        MCP0_PORT: process.env.IDC1_MCP0_PORT || '8355',
        MCP_AGENTS_PORT: process.env.IDC1_MCP_AGENTS_PORT || '8046',
        MCP_DEVOPS_PORT: process.env.IDC1_MCP_DEVOPS_PORT || '8425'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/idc1-health-sweep.sh'
    }
  },
  {
    id: 'idc1-fix-mcp0-vpn',
    label: 'Fix mcp0.idc1.vpn (CoreDNS + Caddy)',
    description:
      'Patches idc1 CoreDNS and Caddy config to make mcp0.idc1.vpn resolve and reverse-proxy to the local mcp0 service, then restarts wg-dns and reloads Caddy.',
    tags: ['idc1', 'vpn', 'dns', 'caddy', 'mcp0'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/idc1-fix-mcp0-vpn.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: process.env.IDC1_DEPLOY_SSH_USER || 'chaba',
        SSH_HOST: process.env.IDC1_DEPLOY_SSH_HOST || 'idc1.surf-thailand.com',
        SSH_PORT: process.env.IDC1_DEPLOY_SSH_PORT || '22',
        SSH_KEY_PATH: toPosixIfNeeded(
          process.env.IDC1_DEPLOY_SSH_KEY_PATH ||
            path.join(config.repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519')
        ),
        IDC1_STACK_DIR: process.env.IDC1_STACK_DIR || '/home/chaba/chaba/stacks/idc1-stack',
        COREFILE_REL: process.env.IDC1_COREFILE_REL || 'config/coredns/Corefile',
        CADDYFILE_REL: process.env.IDC1_CADDYFILE_REL || 'config/caddy/Caddyfile',
        MCP0_PORT: process.env.IDC1_MCP0_PORT || '8355'
      },
      shell: config.deployShell
    },
    outputs: {
      docs: 'scripts/idc1-fix-mcp0-vpn.sh'
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
    id: 'idc1-stack-status',
    label: 'idc1 stack status',
    description: 'Runs scripts/idc1-stack.ps1 -Action status to show docker compose state on idc1.',
    tags: ['idc1', 'docker', 'status'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'idc1-stack.ps1'),
      args: ['-Action', 'status'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/idc1-stack.ps1'
    }
  },
  {
    id: 'idc1-stack-up',
    label: 'idc1 stack up',
    description: 'Calls scripts/idc1-stack.ps1 -Action up to start the MCP suite on idc1.',
    tags: ['idc1', 'docker', 'up'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'idc1-stack.ps1'),
      args: ['-Action', 'up'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/idc1-stack.ps1'
    }
  },
  {
    id: 'idc1-stack-down',
    label: 'idc1 stack down',
    description: 'Stops the idc1 MCP suite via scripts/idc1-stack.ps1 -Action down.',
    tags: ['idc1', 'docker', 'down'],
    runner: {
      type: 'powershell',
      scriptPath: path.join(config.scriptsRoot, 'idc1-stack.ps1'),
      args: ['-Action', 'down'],
      cwd: config.repoRoot
    },
    outputs: {
      docs: 'scripts/idc1-stack.ps1'
    }
  },
  {
    id: 'deploy-idc1-test',
    label: 'Deploy test.idc1 site',
    description: 'Wraps scripts/deploy-idc1-test.sh via Bash/WSL to sync /test assets to the idc1 host.',
    tags: ['idc1', 'deploy', 'test'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/deploy-idc1-test.sh',
      cwd: config.repoRoot,
      env: {
        SSH_USER: process.env.IDC1_DEPLOY_SSH_USER || 'chaba',
        SSH_HOST: process.env.IDC1_DEPLOY_SSH_HOST || 'idc1.surf-thailand.com',
        SSH_PORT: process.env.IDC1_DEPLOY_SSH_PORT || '22',
        SSH_KEY_PATH: toPosixIfNeeded(
          process.env.IDC1_DEPLOY_SSH_KEY_PATH ||
            path.join(config.repoRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519')
        ),
        REMOTE_BASE: process.env.IDC1_DEPLOY_REMOTE_BASE || '/www/idc1.surf-thailand.com',
        LOCAL_BASE: toPosixIfNeeded(path.join(config.repoRoot, 'sites', 'idc1')),
        ENV_DIR: toPosixIfNeeded(process.env.IDC1_DEPLOY_ENV_DIR || path.join(config.repoRoot, '.secrets', 'dev-host')),
        APPS: 'test',
        RELEASES_TO_KEEP: process.env.IDC1_DEPLOY_RELEASES || '5'
      },
      shell: config.deployShell
    },
    outputs: {
      publicUrl: 'https://test.idc1.surf-thailand.com',
      docs: 'scripts/deploy-idc1-test.sh'
    }
  },
  {
    id: 'verify-idc1-test',
    label: 'Verify test.idc1',
    description: 'Curls https://test.idc1.surf-thailand.com with retries via scripts/verify-idc1-test.sh.',
    tags: ['idc1', 'verify', 'test'],
    runner: {
      type: 'posix',
      scriptRelative: './scripts/verify-idc1-test.sh',
      cwd: config.repoRoot,
      env: {
        TARGET_URL: 'https://test.idc1.surf-thailand.com'
      },
      shell: config.deployShell
    },
    outputs: {
      publicUrl: 'https://test.idc1.surf-thailand.com',
      docs: 'scripts/verify-idc1-test.sh'
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
