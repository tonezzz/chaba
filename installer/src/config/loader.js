import { promises as fs } from 'fs';
import path from 'path';
import yaml from 'js-yaml';
import dotenv from 'dotenv';

dotenv.config();

const requiredTopLevelKeys = ['targets', 'services'];

export async function loadConfig(configPath) {
  const resolvedPath = path.isAbsolute(configPath)
    ? configPath
    : path.resolve(process.cwd(), configPath);

  let fileContents;
  try {
    fileContents = await fs.readFile(resolvedPath, 'utf8');
  } catch (error) {
    throw new Error(`Unable to read config file at ${resolvedPath}: ${error.message}`);
  }

  let parsed;
  try {
    parsed = yaml.load(fileContents) || {};
  } catch (error) {
    throw new Error(`YAML parsing error in ${resolvedPath}: ${error.message}`);
  }

  validateConfig(parsed, resolvedPath);
  return normalizeConfig(parsed, resolvedPath);
}

function validateConfig(config, sourcePath) {
  for (const key of requiredTopLevelKeys) {
    if (!config[key]) {
      throw new Error(`Config ${sourcePath} is missing required key: ${key}`);
    }
    if (!Array.isArray(config.targets) && key === 'targets') {
      throw new Error(`Config ${sourcePath} expected "targets" to be an array.`);
    }
    if (typeof config.services !== 'object') {
      throw new Error(`Config ${sourcePath} expected "services" to be an object.`);
    }
  }
}

function normalizeConfig(config, sourcePath) {
  const normalizedTargets = config.targets.map((target, index) => {
    if (!target.host || !target.username) {
      throw new Error(
        `Target entry #${index + 1} in ${sourcePath} requires "host" and "username".`
      );
    }
    return {
      port: 22,
      ...target,
      name: target.name || `target-${index + 1}`
    };
  });

  return {
    ...config,
    metadata: {
      sourcePath,
      generatedAt: new Date().toISOString()
    },
    targets: normalizedTargets
  };
}
