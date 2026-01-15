#!/usr/bin/env node

import process from 'node:process';
import { config } from '../src/config.js';
import { invokeDockerTool } from '../src/mcp0Client.js';

const log = (...parts) => console.log('[pc2-compose-control]', ...parts);
const error = (...parts) => console.error('[pc2-compose-control]', ...parts);

const splitList = (value) => {
  if (!value) return [];
  if (Array.isArray(value)) return value.map((entry) => String(entry).trim()).filter(Boolean);
  return String(value)
    .split(/[, ]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
};

const parseArgs = (argv) => {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      result[key] = 'true';
    } else {
      result[key] = next;
      i += 1;
    }
  }
  return result;
};

const run = async () => {
  try {
    const cli = parseArgs(process.argv.slice(2));
    const composePath = cli.compose || process.env.COMPOSE_PATH || config.pcWorker?.composeFile;
    const projectName =
      cli.project || process.env.COMPOSE_PROJECT || config.pc2Host?.workerDirName || 'pc2-worker';
    const command = cli.command || process.env.COMPOSE_COMMAND;

    if (!composePath) {
      throw new Error('compose path is required (set --compose or COMPOSE_PATH)');
    }
    if (!projectName) {
      throw new Error('project name is required (set --project or COMPOSE_PROJECT)');
    }
    if (!command) {
      throw new Error('command is required (set --command or COMPOSE_COMMAND)');
    }

    const flags = splitList(cli.flags || process.env.COMPOSE_FLAGS);
    const services = splitList(cli.services || process.env.COMPOSE_SERVICES);

    const payload = {
      compose_path: composePath,
      project_name: projectName,
      command
    };
    if (flags.length) {
      payload.flags = flags;
    }
    if (services.length) {
      payload.services = services;
    }

    log(`Invoking compose-control (${command}) on ${projectName}`);
    const response = await invokeDockerTool('compose-control', payload);
    const outputs = response?.data?.outputs || [];
    if (!outputs.length) {
      console.log(JSON.stringify(response?.data ?? response, null, 2));
      return;
    }
    outputs.forEach((entry) => {
      if (entry?.text) {
        console.log(entry.text);
      } else {
        console.log(JSON.stringify(entry, null, 2));
      }
    });
  } catch (err) {
    error(err.message || err);
    process.exitCode = 1;
  }
};

run();
