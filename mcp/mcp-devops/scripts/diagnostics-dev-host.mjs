#!/usr/bin/env node

import { config } from '../src/config.js';
import { invokeDockerTool } from '../src/mcp0Client.js';

const log = (...parts) => {
  console.log('[diagnostics-dev-host]', ...parts);
};

const stringifyOutputs = (data) => {
  if (!data) {
    return '∅ (no data returned)';
  }
  const outputs = Array.isArray(data.outputs) ? data.outputs : [];
  if (!outputs.length) {
    return JSON.stringify(data, null, 2);
  }
  return outputs
    .map((entry) => {
      if (entry?.text) {
        return entry.text;
      }
      return JSON.stringify(entry, null, 2);
    })
    .join('\n---\n');
};

const collectContainerNames = () => {
  const raw = config.mcp0.dockerLogContainers || '';
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
};

const run = async () => {
  try {
    log('Listing all containers via mcp-docker…');
    const listResult = await invokeDockerTool('list-containers');
    log('Containers:');
    console.log(stringifyOutputs(listResult?.data));

    const targets = collectContainerNames();
    if (!targets.length) {
      log('No containers configured in config.mcp0.dockerLogContainers; skipping log fetch.');
      return;
    }

    for (const name of targets) {
      try {
        log(`Fetching logs for container '${name}'…`);
        const logsResult = await invokeDockerTool('get-logs', { container_name: name });
        console.log(stringifyOutputs(logsResult?.data));
      } catch (err) {
        console.error(`[diagnostics-dev-host] Failed to fetch logs for ${name}:`, err.message || err);
      }
    }
  } catch (error) {
    console.error('[diagnostics-dev-host] Fatal error:', error.message || error);
    process.exitCode = 1;
  }
};

run();
