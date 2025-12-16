const express = require('express');
const cors = require('cors');
const { execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const APP_NAME = 'mcp-webtop';
const APP_VERSION = '0.1.0';

const PORT = Number(process.env.PORT || 8055);
const HOST = process.env.HOST || '0.0.0.0';

const WEBTOP_CONFIG_DIR = process.env.WEBTOP_CONFIG_DIR || '/webtop-config';
const EXPORT_DIR = process.env.EXPORT_DIR || '/data/exports';

const ensureDir = async (dir) => {
  await fs.promises.mkdir(dir, { recursive: true });
};

const execFileAsync = (file, args, options = {}) =>
  new Promise((resolve, reject) => {
    execFile(file, args, { ...options, maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) {
        err.stdout = stdout;
        err.stderr = stderr;
        return reject(err);
      }
      return resolve({ stdout, stderr });
    });
  });

const sanitizeExportName = (value) => {
  const raw = String(value || '').trim();
  const cleaned = raw.replace(/[^a-zA-Z0-9._-]/g, '_').replace(/_+/g, '_');
  return cleaned || null;
};

const listExports = async () => {
  await ensureDir(EXPORT_DIR);
  const entries = await fs.promises.readdir(EXPORT_DIR, { withFileTypes: true });
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith('.tar.gz'))
    .map((entry) => entry.name)
    .sort();
  return { export_dir: EXPORT_DIR, files };
};

const exportConfig = async (args = {}) => {
  await ensureDir(EXPORT_DIR);

  const stamp = new Date().toISOString().replace(/[:.]/g, '').replace('Z', 'Z');
  const prefix = sanitizeExportName(args.name) || 'webtop-config';
  const outFile = path.join(EXPORT_DIR, `${prefix}-${stamp}.tar.gz`);

  await execFileAsync('tar', ['-C', WEBTOP_CONFIG_DIR, '-czf', outFile, '.']);

  const stat = await fs.promises.stat(outFile);
  return {
    status: 'ok',
    source_dir: WEBTOP_CONFIG_DIR,
    export_file: outFile,
    bytes: stat.size
  };
};

const importConfig = async (args = {}) => {
  const rel = typeof args.export_file === 'string' ? args.export_file.trim() : '';
  if (!rel) {
    throw new Error('export_file is required');
  }

  const filePath = path.isAbsolute(rel) ? rel : path.join(EXPORT_DIR, rel);

  await fs.promises.access(filePath, fs.constants.R_OK);
  await ensureDir(WEBTOP_CONFIG_DIR);

  const tmpDir = await fs.promises.mkdtemp(path.join('/tmp', 'webtop-import-'));
  try {
    await execFileAsync('tar', ['-C', tmpDir, '-xzf', filePath]);

    const contents = await fs.promises.readdir(tmpDir);
    if (!contents.length) {
      throw new Error('Import archive produced no files');
    }

    const existingEntries = await fs.promises.readdir(WEBTOP_CONFIG_DIR);
    await Promise.all(
      existingEntries.map((entry) =>
        fs.promises.rm(path.join(WEBTOP_CONFIG_DIR, entry), { recursive: true, force: true })
      )
    );

    await fs.promises.cp(tmpDir, WEBTOP_CONFIG_DIR, { recursive: true, force: true });

    return {
      status: 'ok',
      import_file: filePath,
      target_dir: WEBTOP_CONFIG_DIR
    };
  } finally {
    await fs.promises.rm(tmpDir, { recursive: true, force: true });
  }
};

const TOOL_SCHEMAS = {
  list_exports: {
    name: 'list_exports',
    description: 'List available webtop config export archives (.tar.gz).',
    input_schema: { type: 'object', properties: {} }
  },
  export_config: {
    name: 'export_config',
    description: 'Create a tar.gz export of the mounted webtop /config directory.',
    input_schema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Optional export name prefix.' }
      }
    }
  },
  import_config: {
    name: 'import_config',
    description: 'Import a previously exported tar.gz into the mounted webtop /config directory.',
    input_schema: {
      type: 'object',
      required: ['export_file'],
      properties: {
        export_file: {
          type: 'string',
          description: 'Filename in EXPORT_DIR or absolute path to the tar.gz.'
        }
      }
    }
  }
};

const TOOL_HANDLERS = {
  list_exports: listExports,
  export_config: exportConfig,
  import_config: importConfig
};

const app = express();
app.use(cors());
app.use(express.json({ limit: process.env.JSON_BODY_LIMIT || '1mb' }));

app.get('/health', async (_req, res) => {
  try {
    const exports = await listExports();
    res.json({
      status: 'ok',
      service: APP_NAME,
      version: APP_VERSION,
      webtop_config_dir: WEBTOP_CONFIG_DIR,
      export_dir: EXPORT_DIR,
      exports_count: exports.files.length,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    res.status(500).json({ status: 'error', detail: error.message });
  }
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: APP_NAME,
    version: APP_VERSION,
    description: 'MCP provider for managing a webtop config volume (export/import/list)',
    capabilities: {
      tools: Object.values(TOOL_SCHEMAS)
    },
    metadata: {
      webtop_config_dir: WEBTOP_CONFIG_DIR,
      export_dir: EXPORT_DIR
    }
  });
});

app.post('/invoke', async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool || typeof tool !== 'string') {
    return res.status(400).json({ error: 'tool is required' });
  }
  const handler = TOOL_HANDLERS[tool];
  if (!handler) {
    return res.status(404).json({ error: `Unknown tool '${tool}'` });
  }
  try {
    const result = await handler(args);
    return res.json(result);
  } catch (error) {
    console.error('[mcp-webtop] invoke error', error);
    return res.status(502).json({ error: error.message || 'invoke_failed' });
  }
});

app.listen(PORT, HOST, () => {
  console.log(`[${APP_NAME}] listening on ${HOST}:${PORT}`);
});
