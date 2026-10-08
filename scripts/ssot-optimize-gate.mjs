#!/usr/bin/env node
/**
 * SSOT optimization baseline gate (card: precommit-warning-baseline).
 *
 * ssot-optimize.mjs rewrites reports/SSOT_OPTIMIZATION_WARNINGS.json on every
 * run. The committed copy of that file is the known-warnings baseline: this
 * gate fails only when a current warning is absent from the baseline — i.e.
 * new debt. Pre-existing debt no longer blocks merge commits or dispatch
 * branch landings.
 *
 * Baseline resolution order:
 *   1. staged blob (`git show :<file>`) — so a commit may update warnings and
 *      baseline together (silencing is an explicit, auditable file change);
 *   2. HEAD blob;
 *   3. absent → advisory pass, so stale branches without the file are not
 *      blocked by debt the baseline simply does not know yet.
 *
 * Warning text embeds counts ("554 lines exceeds review threshold of 350");
 * digits are normalized to '#' for matching, so magnitude drift in an already
 * known warning does not register as new debt.
 *
 * To accept current warnings, refresh the baseline with a FULL optimize run:
 *   node scripts/ssot-optimize.mjs     # not --staged
 *   git add reports/SSOT_OPTIMIZATION_WARNINGS.json
 */
import { execSync } from "child_process";
import { existsSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO = join(__dirname, "..");
const WARNINGS_REL = "reports/SSOT_OPTIMIZATION_WARNINGS.json";
const WARNINGS_PATH = join(REPO, WARNINGS_REL);
const KINDS = ["bloat", "data_isolation", "other"];

const normKey = (w) => `${w.file}\n${String(w.warning).replace(/\d+/g, "#")}`;

function gitShow(spec) {
  try {
    return execSync(`git show "${spec}"`, {
      cwd: REPO,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    return null;
  }
}

function parseWarnings(json, label) {
  let doc;
  try {
    doc = JSON.parse(json);
  } catch (e) {
    console.error(`❌ ssot-optimize-gate: cannot parse ${label}: ${e.message}`);
    console.error(`   Restore a valid baseline or delete ${WARNINGS_REL} to go advisory.`);
    return null;
  }
  const out = [];
  for (const kind of KINDS) for (const w of doc[kind] || []) out.push(w);
  return out;
}

function main() {
  if (!existsSync(WARNINGS_PATH)) {
    console.log("ssot-optimize-gate: no warnings file — nothing to gate");
    return 0;
  }
  const current = parseWarnings(readFileSync(WARNINGS_PATH, "utf8"), WARNINGS_PATH);
  if (current === null) return 1;
  if (current.length === 0) {
    console.log("ssot-optimize-gate: no warnings");
    return 0;
  }

  const staged = gitShow(`:${WARNINGS_REL}`);
  const head = staged === null ? gitShow(`HEAD:${WARNINGS_REL}`) : null;
  const baselineJson = staged !== null ? staged : head;
  const baselineSource = staged !== null ? "index" : head !== null ? "HEAD" : null;

  if (baselineJson === null) {
    console.warn(
      `⚠️  ssot-optimize-gate: no committed baseline (${WARNINGS_REL}); ` +
        `${current.length} warning(s) treated as advisory.\n` +
        `   Seed it with: node scripts/ssot-optimize.mjs && git add ${WARNINGS_REL}`
    );
    return 0;
  }

  const baselineEntries = parseWarnings(baselineJson, `baseline ${WARNINGS_REL} (${baselineSource})`);
  if (baselineEntries === null) return 1;
  const baseline = new Set(baselineEntries.map(normKey));
  const fresh = current.filter((w) => !baseline.has(normKey(w)));

  if (fresh.length === 0) {
    console.log(
      `ssot-optimize-gate: ${current.length} warning(s), all covered by baseline (${baselineSource})`
    );
    return 0;
  }

  console.error(`❌ ${fresh.length} SSOT optimization warning(s) not in baseline (new debt):`);
  for (const w of fresh) console.error(`   - ${w.file}: ${w.warning}`);
  console.error("");
  console.error("Fix the warnings, or accept them by refreshing the baseline:");
  console.error("   node scripts/ssot-optimize.mjs   # full run — do NOT use --staged");
  console.error(`   git add ${WARNINGS_REL}`);
  return 1;
}

process.exit(main());
