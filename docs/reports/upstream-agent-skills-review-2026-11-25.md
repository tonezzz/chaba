# Upstream Agent Skills review — DevNest/Chaba fit assessment

**Card:** `devnest-upstream-skills-review` (DEV-0231, follow-up to DEV-0230 info-find pilot)
**Date:** 2026-11-25 · **Mode:** read-only review — shallow clones inspected in `/tmp`, nothing installed, no third-party installers run, no repo imported.
**Method:** cloned each candidate repo (`--depth 1`), read the actual `SKILL.md`, bundled scripts/references, LICENSE, git activity, then mapped against local skills (`.agents/skills/*`, `.devin/skills/*`) and AGENTS/SSOT rules.

## Ranked fit matrix

| Rank | Candidate | Fit | Verdict | License | Activity | Chaba gap it fills |
|---|---|---|---|---|---|---|
| 1 | anthropics/skills `webapp-testing` | High | **ADOPT (adapted)** | Apache-2.0 (per-skill LICENSE.txt) | Active (repo push 2026-11-16) | No UI-verification skill exists locally; we have Playwright KB docs (`docs/kb/e2e-test-automation-patterns*.md`) but no reusable skill |
| 2 | addyosmani/agent-skills `code-review-and-quality` | High | **ADAPT** | MIT | Very active (push 2026-11-23, ~120k★ repo) | Review gate is currently only the `review` devin-mode + DEV-0253 error standard; no structured multi-axis checklist |
| 3 | anthropics/skills `skill-creator` | Medium | **ADAPT (process only)** | Apache-2.0 | Active | DEV-0230 lineage needs a skill eval/iteration method; scripts are `claude -p`-bound so only the methodology ports |
| 4 | vercel-labs/agent-skills `web-design-guidelines` | Medium | **ADAPT (vendor as-is)** | MIT | Active (push 2026-11-20) | UI/a11y review checklist for dashboard (`www/*.js`, ada-cms) work; tiny, pinned snapshot, zero runtime deps |
| 5 | anthropics/skills `mcp-builder` | Low-Medium | **ADAPT (read-only reference)** | Apache-2.0 | Active | Chaba already runs many MCP servers; value is the `reference/*.md` design docs for the *next* server build, not the scripts |
| 6 | bregman-arie/devops-sre-skills | Low | **REJECT (for now)** | Apache-2.0 | Dormant — last push 2026-03-20, ~30★ | All 17 skills marked `maturity: draft`, empty `manifest.yml`, custom frontmatter schema (`tools_allowed: k8s.get`…), targets k8s/aws/gcp/argocd — Chaba is systemd/quadlet/caddy on bare hosts |

Also shortlisted by the card but assessed within the above: addyosmani `test-driven-development` (400-line SKILL.md, same MIT repo — solid but overlaps heavily with rank-2 pick; adopt one gate skill first, TDD can follow if wanted) and vercel-labs `skills` CLI repo itself (that's the installer tool — explicitly out of scope per card).

## Per-candidate detail

### 1. anthropics/skills → `webapp-testing` — ADOPT (adapted)

- **Files:** `SKILL.md` (95 lines) + `scripts/with_server.py` (stdlib only: subprocess/socket/argparse) + 3 example scripts. Runtime needs Python Playwright (`pip install playwright` + browser download) — a real dependency to declare.
- **Tool/network assumptions:** localhost-only by design (decision tree starts "is it static HTML?" → "is the server already running?"). No telemetry, no network beyond the target app. `with_server.py` manages server lifecycle — must be reviewed before unattended use since it spawns arbitrary `--server` commands.
- **Overlap:** complements, doesn't duplicate — `docs/kb/e2e-test-automation-patterns*.md` is Chaba-Raceman-specific prose; `static-site-tester` agent exists in `.devin/agents` (referenced by the KB doc). No general "open a page and verify" skill in `.devin/skills` or `.agents/skills`.
- **Adapt needed:** rewrite SKILL.md trigger description for Devin skill format; pin "headless chromium only" and "localhost/Tailscale-internal URLs only" guardrails (consistent with host-hygiene rules); decide where playwright is installed (per-host venv vs repo-pinned).
- **Small test before integration:** vendor the skill folder into a scratch dir, run `python scripts/with_server.py --help`, then one `examples/static_html_automation.py`-style script against a single local page (e.g. a dashboard JSON endpoint rendered page). Pass = screenshot + console-log capture works with zero repo changes.

### 2. addyosmani/agent-skills → `code-review-and-quality` — ADAPT

- **Files:** `SKILL.md` (402 lines) + `references/shared/{security,performance}-checklist.md`. Pure markdown, zero scripts, zero network, zero deps. Same anatomy across the repo's 24 skills (Overview / When to Use / Process / Rationalizations / Red Flags / Verification).
- **Overlap:** partial. DEV-0253 (`docs/kb/devin-error-handling-standard.md`) covers failure-handling lanes, not diff review. `review` mode in `ssot.devin-modes.yml` is behavioral, not a checklist. Kanban field-ownership and single-writer rules are NOT in the upstream skill — must be added or it will give generic advice that conflicts (e.g. it won't know `column:` is human-owned).
- **Adapt needed:** extract the five-axis review (correctness, readability, architecture, security, performance) + approval standard into a `.devin/skills/code-review/` skill; append a "Chaba gates" section (field ownership, card-union merge driver, pre-commit single-writer blocks, no push without label). Do NOT import the repo's AGENTS.md/CLAUDE.md persona machinery — that's repo-scoped config, not a skill.
- **Small test:** run the adapted checklist manually against one recent merged dispatch diff (e.g. `git show` of a small card merge); check it produces findings in the `file:line` style and doesn't contradict AGENTS rules. Pass = one dry-run review posted as a card comment.

### 3. anthropics/skills → `skill-creator` — ADAPT (methodology only)

- **Files:** `SKILL.md` (485 lines) + `scripts/` (run_eval.py, run_loop.py, improve_description.py, package_skill.py, quick_validate.py, aggregate_benchmark.py) + `eval-viewer/` + `agents/`.
- **Tool/network assumptions — the blocker for direct use:** `run_eval.py` writes `.claude/commands/` files and shells out to `claude -p` (strips `CLAUDECODE` env to allow nesting). It assumes a Claude-Code-shaped project root. On Devin lanes this would need a rewrite of the eval harness — possible but non-trivial.
- **What's worth keeping:** the *loop* — capture intent → draft → test prompts → qualitative + quantitative evals → iterate → description-improver for trigger accuracy. This is exactly the method DEV-0230's info-find pilot needs for its next iteration, and it's agent-agnostic prose.
- **Adapt needed:** port the methodology into `docs/kb/skill-authoring-evals.md` (or a `.devin/skills/skill-author/` skill) describing the same loop with Devin-native eval mechanics (dispatch a fixed prompt set, score outputs). Skip all scripts.
- **Small test:** apply the ported loop once to the existing `info-find` skill — write 5 fixed prompts, run them, score source-selection accuracy. Pass = a repeatable eval checklist exists and produced scores.

### 4. vercel-labs/agent-skills → `web-design-guidelines` — ADAPT (vendor)

- **Files:** `SKILL.md` (51 lines) + `references/command.md` (191 lines, a pinned snapshot of vercel-labs/web-interface-guidelines at SHA `434b7f9`, SHA-256 recorded in SKILL.md). No scripts, no network at runtime ("Do not fetch rules from the network" is explicit).
- **Overlap:** none locally — closest is general code-review; this is UI/a11y-specific (focus states, contrast, semantics, form labels…). Useful for ada-cms/dashboard work which has no dedicated UI-review path.
- **Adapt needed:** minimal — copy the two files into `.devin/skills/web-design-guidelines/`; the skill already documents its own update procedure (fetch new upstream SHA, update hash, re-zip optional).
- **Small test:** run it against one `www/*.js` dashboard file or one ada-cms page source; verify output is terse `file:line` findings and the rule snapshot loads without network.

### 5. anthropics/skills → `mcp-builder` — ADAPT (reference shelf)

- **Files:** `SKILL.md` (252 lines) + `reference/{mcp_best_practices,node_mcp_server,node_mcp_server_v2,python_mcp_server,evaluation}.md` + `scripts/` (connections.py, evaluation.py, requirements.txt = `anthropic>=0.39.0`, `mcp>=1.1.0`).
- **Tool/network assumptions:** scripts need pip installs and are an *evaluation harness* for MCP servers, not something to run casually. The markdown references are the durable value: tool-naming/discoverability, context management, actionable errors, transport choice (streamable HTTP stateless vs stdio).
- **Overlap:** Chaba has ~15 MCP servers already and `docs/kb/mcp-tools*.md` runbooks. Marginal new capability; useful when the *next* MCP server is designed.
- **Adapt needed:** don't install as a skill. Copy `reference/*.md` into `docs/kb/mcp/` (or link the upstream paths in an index) so agents find them via info-find/ssot-search when an MCP task arrives.
- **Small test:** on the next MCP-server card, check whether the agent cites `mcp_best_practices.md` content unprompted. Pass = reference is discoverable through existing search paths.

### 6. bregman-arie/devops-sre-skills — REJECT (for now)

- **Evidence:** Apache-2.0, ~30★, last commit 2026-03-20 (8 months dormant). All 17 SKILL.md files self-declare `maturity: draft`. `skills/manifest.yml` is a stub (`skills: []`). Frontmatter uses a custom schema (`id`, `tools_allowed: [k8s.get…]`, `safety.default_mode`) that does not match the SKILL.md `name`/`description` convention Devin/Claude skills use. Content targets kubernetes/aws/gcp/argocd/terraform — Chaba runs systemd units, quadlets, caddy, and host scripts; none of the 17 skills apply directly.
- **The one good idea:** the read-only triage-runbook pattern (When to use / Preconditions / Procedure / Decision points / Verification / Rollback / Escalation) is a nice template — worth stealing the *shape* for a future `chaba-sre-triage` skill covering our actual stack (systemd, mddb, board-api, caddy). That's an adapt-the-pattern job, not an import.
- **Small test (if ever revisited):** none — reject stands until the repo matures or a k8s workload appears.

## Overlap map (local skills/rules vs candidates)

| Local asset | Covers | Candidate overlap |
|---|---|---|
| `.devin/skills/info-find` | unified info-finding (MDDB/SSOT/MCP/web) | none — complementary to all |
| `.devin/skills/card-ops-sweep`, `session-capture`, `finish-and-close`, `save-to-focus`, `subtask-triage` | kanban/session hygiene | none |
| `.agents/skills/{health-check,ssot-search,ssot-validate,auto-kb,code-decision,status,overnight-assessment,git-status}` | health, SSOT, KB, decisions | none |
| `.devin/skills/{noul-gate,mcp-health-preflight,ada-transcript-audit,devin-session-audit,scalecheck}` | host/ops-specific | none |
| `docs/kb/devin-error-handling-standard.md` (DEV-0253) | failure lanes, retries, verified gate | partial → code-review-and-quality (add Chaba gates) |
| `ssot.devin-modes.yml` `review` mode | behavioral review mode | partial → code-review-and-quality |
| `docs/kb/e2e-test-automation-patterns*.md` + `.devin/agents/static-site-tester` | Chaba-Raceman Playwright prose/agent | partial → webapp-testing (generalize) |
| AGENTS.md rules (field ownership, single-writer, sweep duty, lesson-capture) | governance | must be *added to* any adopted review skill |

**Net:** no candidate duplicates a local skill. The two real gaps are (a) structured pre-merge review and (b) ad-hoc UI verification — both have high-fit upstream material.

## License & security notes

- **anthropics/skills:** no repo-level LICENSE; each skill carries its own `LICENSE.txt` = Apache-2.0. Attribution required on redistribution; fine for vendoring into `.devin/skills/` with the license file kept alongside.
- **addyosmani/agent-skills:** MIT (repo LICENSE). Markdown-only skills carry no secrets; the repo also ships personas/hooks/commands we are NOT importing.
- **vercel-labs/agent-skills:** MIT. `web-design-guidelines` bundles a rule snapshot pinned by SHA-256 — verify the hash matches `d246b026…` when vendoring (it did at clone time: file is the pinned upstream `command.md`).
- **bregman-arie/devops-sre-skills:** Apache-2.0. Rejected on maturity/fit, not license.
- **Scripts audited:** `with_server.py` is stdlib-only but spawns user-supplied server commands — treat as code, review before unattended dispatch use. `skill-creator/scripts/*` invoke `claude -p` and write `.claude/commands/` — Claude-Code-bound, do not run on Devin lanes. `mcp-builder/scripts/*` require `pip install anthropic mcp` — reference-only.
- **No network assumptions at runtime** for the markdown-only skills; `webapp-testing` is localhost-scoped by design.

## Recommended order of work

1. Vendor + adapt `webapp-testing` → `.devin/skills/webapp-testing/` (highest gap, self-contained).
2. Write `.devin/skills/code-review/` from addyosmani's five-axis checklist + Chaba gates section.
3. Port skill-creator's eval loop into a `docs/kb/` page; apply it to `info-find`.
4. Vendor `web-design-guidelines` as-is (cheap).
5. File `mcp-builder` references into `docs/kb/mcp/` index when next MCP work is carded.
6. Reject `devops-sre-skills`; optionally card a "chaba-sre-triage skill using the draft-runbook shape" idea later.

Follow-up installs themselves are **not** done in this dispatch — each adoption wants its small test above first, per the card spec.
