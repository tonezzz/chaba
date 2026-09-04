#!/usr/bin/env node
/*
 * Generate the focus decision tree JSON for the H3/local web view.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba-tony-dell';
const SSOT_FILE = join(PROJECT_ROOT, 'docs', 'ssot', 'infrastructure', 'ssot.mcp-focus.yml');
const OUT_DIR = join(PROJECT_ROOT, 'stacks', 'web', 'public', 'apps', 'focus', 'data');
const OUT_FILE = join(OUT_DIR, 'decision-tree.json');

const ssot = yaml.load(readFileSync(SSOT_FILE, 'utf8'));
mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(OUT_FILE, JSON.stringify(ssot.decision_tree || [], null, 2));
console.log(`Wrote ${OUT_FILE}`);
