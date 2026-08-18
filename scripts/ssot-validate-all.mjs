#!/usr/bin/env node

/**
 * SSOT Validation Script - optimized
 * 
 * Validates all SSOT YAML files for syntax and structure using a single
 * batched Python invocation with parallel file processing.
 */

import { readFileSync, readdirSync, existsSync, writeFileSync, statSync, unlinkSync } from 'fs';
import { join, relative } from 'path';
import { execSync } from 'child_process';

const SSOT_DIR = '/home/tony/CascadeProjects/chaba/docs/ssot';
const TEMP_PY = '/tmp/ssot-validate-batch.py';

function findYAMLFiles(dir, files = []) {
  const items = readdirSync(dir);
  for (const item of items) {
    const fullPath = join(dir, item);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      findYAMLFiles(fullPath, files);
    } else if (item.endsWith('.yml') && !item.toLowerCase().includes('template')) {
      files.push(fullPath);
    }
  }
  return files;
}

function buildPythonScript(filePaths) {
  const pathsStr = filePaths.map(p => p.replace(/\\/g, '\\\\').replace(/'/g, "\\'")).map(p => `'${p}'`).join(',\n    ');
  return `
import concurrent.futures
import json
import re
import sys
import yaml

FILE_PATHS = [
    ${pathsStr}
]

OPTIMIZATION_DOC = yaml.safe_load(open('/home/tony/CascadeProjects/chaba/docs/ssot/ssot.file-optimization.yml'))
BLOAT_EXEMPTIONS = OPTIMIZATION_DOC.get('config', {}).get('bloat_exemptions', {})
HARD_EXEMPT = set(BLOAT_EXEMPTIONS.get('hard_threshold', []))
REVIEW_EXEMPT = set(BLOAT_EXEMPTIONS.get('review_threshold', []))

CONFIG_TYPE_MARKERS = ('ssot.health', 'ssot.gpu', 'ssot.mcp', 'ssot.automation', 'ssot.containerization')

REVIEW_LINES = 350
REVIEW_SECTIONS = 10
REVIEW_ITEMS = 45
HARD_LINES = 750
HARD_SECTIONS = 12
HARD_ITEMS = 60

IP4_RE = re.compile(r'''(?<!\\d)(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)(?!\\d)''')
SECRETS_RE = re.compile(r'''(password|secret|token|api_key|private_key|access_key)["']?\\s*[:=]\\s*["']?([^\\s\\n"']+)''', re.IGNORECASE)
RUNTIME_RE = re.compile(r'''(last_seen|last_login|generated_at|timestamp|updated_at):\\s+["']?\\d{4}-\\d{2}-\\d{2}''', re.IGNORECASE)


def _is_config_type(path):
    return any(marker in path for marker in CONFIG_TYPE_MARKERS)


def _count_lines(content):
    return content.count('\\n') + 1 if content else 0


def _data_isolation_scan(rel, content, warnings):
    # Skip per-host SSOTs and health/perf baseline files that legitimately contain runtime values
    if any(skip in rel for skip in ('ssot.mysystem.', 'ssot.health.', 'performance-baselines')):
        return
    for match in IP4_RE.finditer(content):
        # Skip loopback, Tailscale, wildcard bind, and documented home subnets
        ip = match.group(0)
        if ip.startswith(('127.', '100.', '0.0.0.0', '192.168.', '8.8.8.8', '8.8.4.4')):
            continue
        warnings.append(f'Data isolation: hardcoded IPv4 address {ip}')
        break
    for match in SECRETS_RE.finditer(content):
        value = match.group(2)
        # Skip references to environment variables, secret file paths, and placeholders
        if re.match(r'^[A-Z_]+$', value):
            continue
        if re.match(r'^[~/.]', value):
            continue
        if 'environment variable' in value.lower() or 'do not commit' in value.lower():
            continue
        warnings.append(f'Data isolation: possible secret value embedded in YAML: {value[:40]}')
        break
    for match in RUNTIME_RE.finditer(content):
        warnings.append('Data isolation: runtime timestamp field may not belong in canonical SSOT')
        break


def validate_one(file_path):
    rel = file_path.replace('${SSOT_DIR}/', '')
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {'path': rel, 'valid': False, 'errors': [f'YAML syntax error: {str(e)}'], 'warnings': []}

        if data is None:
            return {'path': rel, 'valid': False, 'errors': ['Empty file'], 'warnings': []}

        errors = []
        warnings = []
        metrics = {
            'lines': _count_lines(content),
            'sections': 0,
            'items': 0,
        }

        is_config_type = _is_config_type(file_path)
        if not is_config_type and 'title' not in data:
            errors.append('Missing required field: title')

        if 'sections' in data and isinstance(data['sections'], list):
            section_titles = set()
            metrics['sections'] = len(data['sections'])
            for idx, section in enumerate(data['sections']):
                if 'title' not in section:
                    errors.append(f'Section {idx}: Missing required field: title')
                if 'icon' not in section:
                    warnings.append(f'Section {idx}: Missing recommended field: icon')
                if 'layout' not in section:
                    warnings.append(f'Section {idx}: Missing recommended field: layout')
                if 'title' in section and section['title'] in section_titles:
                    errors.append(f'Duplicate section title: {section["title"]}')
                section_titles.add(section.get('title', ''))

                if 'items' in section and isinstance(section['items'], list):
                    item_labels = set()
                    metrics['items'] += len(section['items'])
                    for item_idx, item in enumerate(section['items']):
                        if not isinstance(item, dict):
                            continue
                        if 'label' not in item:
                            errors.append(f'Section {idx}, item {item_idx}: Missing required field: label')
                        if 'label' in item and item['label'] in item_labels:
                            errors.append(f'Section {idx}: Duplicate item label: {item["label"]}')
                        item_labels.add(item.get('label', ''))

        # Bloat thresholds (respect grandfathered exemptions)
        if rel not in HARD_EXEMPT:
            if metrics['lines'] > HARD_LINES:
                warnings.append(f'Bloat: {metrics["lines"]} lines exceeds hard threshold of {HARD_LINES}')
            if metrics['sections'] > HARD_SECTIONS:
                warnings.append(f'Bloat: {metrics["sections"]} sections exceeds hard threshold of {HARD_SECTIONS}')
            if metrics['items'] > HARD_ITEMS:
                warnings.append(f'Bloat: {metrics["items"]} items exceeds hard threshold of {HARD_ITEMS}')
        if rel not in REVIEW_EXEMPT and rel not in HARD_EXEMPT:
            if metrics['lines'] > REVIEW_LINES:
                warnings.append(f'Bloat: {metrics["lines"]} lines exceeds review threshold of {REVIEW_LINES}')
            if metrics['sections'] > REVIEW_SECTIONS:
                warnings.append(f'Bloat: {metrics["sections"]} sections exceeds review threshold of {REVIEW_SECTIONS}')
            if metrics['items'] > REVIEW_ITEMS:
                warnings.append(f'Bloat: {metrics["items"]} items exceeds review threshold of {REVIEW_ITEMS}')

        _data_isolation_scan(rel, content, warnings)

        if 'ideas' in data and isinstance(data['ideas'], list):
            for idx, idea in enumerate(data['ideas']):
                if isinstance(idea, str):
                    continue
                if isinstance(idea, dict) and 'text' not in idea:
                    warnings.append(f'Idea {idx}: Missing recommended field: text')

        return {'path': rel, 'valid': len(errors) == 0, 'errors': errors, 'warnings': warnings, 'metrics': metrics}

    except Exception as e:
        return {'path': rel, 'valid': False, 'errors': [f'Validation error: {str(e)}'], 'warnings': [], 'metrics': {'lines': 0, 'sections': 0, 'items': 0}}


def main():
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(validate_one, p): p for p in FILE_PATHS}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda r: r['path'])
    print(json.dumps(results))


if __name__ == '__main__':
    main()
`;
}

function main() {
  if (!existsSync(SSOT_DIR)) {
    console.log('SSOT directory not found');
    return;
  }

  const files = findYAMLFiles(SSOT_DIR);
  console.log('=== SSOT Validation Report ===\n');
  console.log(`Found ${files.length} SSOT YAML files\n`);

  const pythonScript = buildPythonScript(files);
  writeFileSync(TEMP_PY, pythonScript, 'utf8');

  const start = Date.now();
  let results = [];
  try {
    const output = execSync(`python3 ${TEMP_PY}`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    results = JSON.parse(output);
  } catch (error) {
    console.error('Python execution error:', error.message);
    process.exit(1);
  } finally {
    // Debug: keep temp file
    console.log(TEMP_PY);
  }
  const elapsed = Date.now() - start;

  let totalErrors = 0;
  let totalWarnings = 0;
  let validFiles = 0;

  for (const result of results) {
    console.log(`Validating: ${result.path}`);
    if (result.errors.length > 0) {
      console.log(`  ❌ Errors:`);
      result.errors.forEach(error => console.log(`    - ${error}`));
      totalErrors += result.errors.length;
    }
    if (result.warnings.length > 0) {
      console.log(`  ⚠️  Warnings:`);
      result.warnings.forEach(warning => console.log(`    - ${warning}`));
      totalWarnings += result.warnings.length;
    }
    if (result.valid) {
      console.log(`  ✅ Valid`);
      validFiles++;
    }
    console.log();
  }

  console.log('=== Summary ===');
  console.log(`Total files checked: ${files.length}`);
  console.log(`Valid files: ${validFiles}`);
  console.log(`Total errors: ${totalErrors}`);
  console.log(`Total warnings: ${totalWarnings}`);
  console.log(`Validation time: ${elapsed}ms`);

  if (totalErrors === 0) {
    console.log(`\n✅ All SSOT files are valid`);
  } else {
    console.log(`\n❌ ${files.length - validFiles} SSOT files have validation issues`);
  }
}

main();
