#!/usr/bin/env node
/*
 * Generate a hand-off contract from the Hand-off Queue section in ssot.focus.current.yml.
 * Adds contract_path, completion_criteria, deliverables, and feedback_required fields.
 */
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';
import yaml from 'yaml';

const FOCUS = '/home/tony/CascadeProjects/chaba/docs/ssot/ssot.focus.current.yml';
const REPORT = '/home/tony/CascadeProjects/chaba/reports/HANDOFF_CONTRACT.md';

function loadFocus() {
  return yaml.parse(readFileSync(FOCUS, 'utf8'));
}

function findHandoffQueue(doc) {
  for (const section of doc.sections || []) {
    if (section.title === 'Hand-off Queue') return section;
  }
  return null;
}

function generateContract(items) {
  let md = '# Hand-off Queue Contract\n\n';
  md += `Generated: ${new Date().toISOString().split('T')[0]}\n\n`;

  if (!items || items.length === 0) {
    md += 'No hand-off items.\n';
    return md;
  }

  for (const item of items) {
    const label = item.label || 'Unnamed hand-off';
    const branch = item.branch || 'unknown';
    const subagent = item.subagent || 'unknown';
    const status = item.status || 'unknown';
    const delegated = item.delegated || 'unknown';
    const completed = item.completed || null;
    const plan = item.plan || '';
    const summary = item.summary || '';
    const contractPath = item.contract_path || join('/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure', `ssot.handoff.${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}.yml`);
    const completionCriteria = item.completion_criteria || [
      'Sub-agent completed all assigned subtasks',
      'Changes are validated or reported',
      'SSOT and KB remain consistent'
    ];
    const deliverables = item.deliverables || [
      plan ? `Plan: ${plan}` : 'Plan document',
      'Summary of work completed'
    ];
    const feedbackRequired = item.feedback_required !== false;

    md += `## ${label}\n\n`;
    md += `- **Branch:** ${branch}\n`;
    md += `- **Sub-agent:** ${subagent}\n`;
    md += `- **Status:** ${status}\n`;
    md += `- **Delegated:** ${delegated}\n`;
    if (completed) md += `- **Completed:** ${completed}\n`;
    md += `- **Contract path:** ${contractPath}\n`;
    md += `- **Feedback required:** ${feedbackRequired ? 'Yes' : 'No'}\n\n`;
    md += '### Summary\n\n';
    md += `${summary || 'No summary provided.'}\n\n`;
    md += '### Completion criteria\n\n';
    for (const c of completionCriteria) md += `- [x] ${c}\n`;
    md += '\n### Deliverables\n\n';
    for (const d of deliverables) md += `- ${d}\n`;
    md += '\n';
  }

  return md;
}

function main() {
  const doc = loadFocus();
  const queue = findHandoffQueue(doc);
  const items = queue ? queue.items || [] : [];
  const contract = generateContract(items);
  writeFileSync(REPORT, contract, 'utf8');
  console.log(`Wrote ${REPORT}`);
  console.log(`Hand-off items: ${items.length}`);
}

main();
