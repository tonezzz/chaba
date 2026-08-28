#!/usr/bin/env node
/**
 * Task Completion Runner
 *
 * Runs the task-completion checklist from
 * docs/ssot/infrastructure/ssot.task-completion.yml, performs mandatory
 * validation/optimization, prints the git status, and optionally appends a
 * session entry to docs/ssot/ssot.focus.sessions.yml.
 */
import { execSync } from 'child_process';
import { existsSync, readFileSync, writeFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'js-yaml';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const TASK_SSOT = join(ROOT, 'docs/ssot/infrastructure/ssot.task-completion.yml');
const SESSIONS = join(ROOT, 'docs/ssot/ssot.focus.sessions.yml');

function run(cmd, options = {}) {
  try {
    return execSync(cmd, { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...options });
  } catch (err) {
    return err.stderr ? `${err.stdout || ''}\n${err.stderr}` : err.message;
  }
}

function parseArgs(argv) {
  const out = { focus: null, source: 'user request', done: [], next: null, followUp: [], dry: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--focus' || a === '-f') out.focus = argv[++i];
    else if (a === '--source' || a === '-s') out.source = argv[++i];
    else if (a === '--done' || a === '-d') out.done.push(argv[++i]);
    else if (a === '--next' || a === '-n') out.next = argv[++i];
    else if (a === '--follow-up' || a === '-u') out.followUp.push(argv[++i]);
    else if (a === '--dry' || a === '--dry-run') out.dry = true;
    else if (a === '--help' || a === '-h') out.help = true;
  }
  return out;
}

function showHelp() {
  console.log(`Usage: node scripts/task-complete.mjs [options]

Options:
  -f, --focus <label>     Focus label for the session entry
  -s, --source <text>     Session source (default: user request)
  -d, --done <text>       Completed item; repeatable
  -n, --next <text>       Next action line
  -u, --follow-up <text>  Follow-up item; repeatable
      --dry               Print the session entry without writing it
  -h, --help              Show this help

Without session options, the runner validates SSOT, prints the checklist,
shows git status, and exits.
`);
}

function appendSession(opts) {
  const doc = yaml.load(readFileSync(SESSIONS, 'utf8'));
  const sessions = doc.sessions || [];
  const today = new Date().toISOString().split('T')[0];
  const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15);
  const newSession = {
    date: today,
    session: `chaba-${ts}`,
    focus: opts.focus,
    source: opts.source,
    plan: ['Complete the active focus'],
    done: opts.done.length ? opts.done : ['Completed the focus'],
    follow_up: opts.followUp.length ? opts.followUp : [],
    next_action: opts.next || 'Continue with the next focus or review backlog',
  };
  sessions.push(newSession);
  doc.sessions = sessions.slice(-10);
  if (opts.dry) {
    console.log('\n--- Dry-run session entry ---');
    console.log(yaml.dump(newSession, { sortKeys: false }));
  } else {
    writeFileSync(SESSIONS, yaml.dump(doc, { sortKeys: false, noRefs: true, lineWidth: 120 }));
    console.log('\nAppended session entry to docs/ssot/ssot.focus.sessions.yml');
  }
}

function main() {
  const argv = process.argv.slice(2);
  const opts = parseArgs(argv);
  if (opts.help) return showHelp();

  if (!existsSync(TASK_SSOT)) {
    console.error('Missing task completion SSOT:', TASK_SSOT);
    process.exit(1);
  }
  const taskDoc = yaml.load(readFileSync(TASK_SSOT, 'utf8'));

  console.log(`=== ${taskDoc.title} ===`);
  console.log(taskDoc.subtitle);
  console.log('');

  for (const phase of (taskDoc.phases || [])) {
    console.log(`\n## ${phase.order}. ${phase.name} ${phase.must ? '(required)' : '(optional)'}`);
    for (const step of (phase.steps || [])) {
      console.log(`  [ ] ${step.label}`);
      if (step.action) console.log(`      ${step.action.trim()}`);
    }
  }

  console.log('\n--- Running mandatory SSOT checks ---');
  console.log(run('npm run check:all'));

  console.log('\n--- Git status ---');
  const status = run('git status --short').trim();
  console.log(status || 'No uncommitted changes.');

  if (opts.focus) {
    console.log('\n--- Session log ---');
    appendSession(opts);
  }

  console.log('\nDone. Review the checklist and commit when ready.');
}

main();
