# Workspace Rules

Distilled from https://github.com/detailobsessed/awesome-devin

TODO: Revisit this repo later to harvest more rules and prompts (memories/, tips, official links).

## Coding Principles

### Core Principles
- Favor clarity and maintainability over brevity or cleverness.
- Respect language idioms; use descriptive, consistent naming and formatting.
- Keep functions small and single-responsibility; keep components loosely coupled.
- Encapsulate complexity behind clear interfaces; apply DRY.
- Validate inputs; fail fast with clear, actionable error messages.
- Write tests early and run them frequently; separate pure logic from side effects.
- Profile before optimizing; manage resources properly (with, finally, RAII).

### Write for Humans First
- Code should be understandable at a glance, making it more approachable for collaborators and your future self.
- Avoid obfuscation or over-optimization that sacrifices readability.

### Future-Proof Your Design
- Plan for growth and changing requirements, but do not overengineer.
- Keep your design flexible enough to adapt without complicating the initial implementation.

### Code Quality and Readability
- **Clarity First**: Write straightforward code that conveys its intent clearly. Minimize abstraction layers that obscure readability.
- **Descriptive Naming**: Use meaningful, consistent names for variables, functions, classes, and modules that reflect their purpose.
- **Consistent Formatting**: Follow established style guides and use automated tools to maintain uniform formatting across the codebase.
- **Comment Thoughtfully**: Provide comments or docstrings where necessary, but avoid restating what the code already expresses.

### Architecture and Modularity
- **Encapsulate Complexity**: Group related logic into self-contained modules or classes with clear, well-documented interfaces.
- **Loose Coupling**: Design components to function independently, using abstraction layers or interfaces to reduce interdependencies.
- **Apply DRY**: Refactor repetitive or duplicated code into shared utilities or functions to promote reuse and reduce bloat.
- **Design for Extensibility**: Structure your codebase so you can add new features and functionalities without requiring major rewrites.

### Error Handling and Testing
- **Error Awareness**: Implement robust error handling with clear messages and safe fallback paths for smoother recoveries.
- **Write Tests Early**: Create relevant tests at the outset of development to quickly capture edge cases and catch regressions.
- **Iterative Validation**: Run your tests frequently to ensure ongoing stability and to identify potential issues as your code evolves.
- **Proactive Debugging**: Leverage logging, tracing, and profiling to diagnose and resolve errors efficiently.

### Performance and Resource Management
- **Choose Efficient Solutions**: Adopt algorithms and data structures that suit your problem domain, optimizing for efficiency and scalability.
- **Optimize When Necessary**: Maintain clarity in your codebase; address performance bottlenecks only after conducting proper profiling.
- **Manage Resources Properly**: Follow best practices for handling external resources. For example, use `with` statements where applicable.

## Cascade Workflow
- Use the project's configured tooling and scripts for linting, formatting, and checks instead of manual edits.
- Verify facts before stating them; double-check changes before committing or creating PRs.
- Update PRs/issues as work progresses; read comments for context and updates.
- For larger tasks, suggest creating a GitHub issue to track progress.
- If Cascade ignores instructions, ask it to "check your guidelines and revise."
- Reload the window if Cascade behavior degrades after long sessions.

## Commit Messages
Write a short English commit message (one sentence max) and format it as a code block:

```
prefix: short description
```

Allowed prefixes: feat, fix, tweak, style, refactor, perf, test, docs, chore, ci, build, revert, hotfix, init, merge, wip, release

## Hostname Usage Standards

- Always use `.local` hostnames instead of IP addresses: `tony-omen.local` instead of `192.168.1.48`, `tony-dell.local` instead of `192.168.1.42`
- Use hostnames in configuration files, SSOT documents, and application URLs
- Exceptions: Network documentation where IP addresses are explicitly relevant (subnet info, firewall rules, DNS config)
- For Tailscale/remote networks, use the tailnet short name (`tony-omen`) or Magic DNS name instead of `.local`; use the `100.x` IP only when hostnames cannot resolve
- For health check configs, use location-specific files: `ssot.health.home.yml` and `ssot.health.mobile.yml`
- See `docs/overview/hostname-enforcement-strategy.md` for comprehensive enforcement strategy

## Documentation Search Standards

For all SSOT, documentation, and conceptual/background queries, MDDB must be the first search tool used.

1. **Search-first gate**
   - Before any `grep`, `glob`, or `read` of `docs/` or SSOT files, call `mcp_call_tool mddb semantic_search` on the topic.
   - For SSOT-specific exact pattern matching, call MDDB first, then use the `ssot-search` skill with the "SSOT YAML only" option.
   - For broad documentation, call MDDB first; fall back to the MCP docs server (`@devista/docs-mcp`) only if MDDB is unavailable or fails, with user confirmation per the Service Failure and Fallback Procedures.

2. **When direct `read`/`grep` is allowed**
   - The exact file path is already known from the active focus, a previous MDDB result, or the user explicitly provided it.
   - You are creating a new file from scratch and only need a known template or existing example.
   - You are running a project script or command, not searching documentation.

3. **Tool selection**
   - `mcp_call_tool mddb get_stats` for collection overview.
   - `mcp_call_tool mddb search_documents` for metadata-only filtering.
   - `mcp_call_tool mddb semantic_search` for all other queries.
   - `mcp_search_ssot` for precise SSOT key lookups after MDDB has been queried.

See `docs/kb/documentation-search.md` for the comprehensive search guide.

## Service Failure and Fallback Procedures (MANDATORY)

**CRITICAL: User Notification Before Fallback Actions**

Before taking any fallback or workaround actions due to service failures, API key issues, or service unavailability, you MUST:

1. **Notify the user immediately** with:
   - What service/API is failing
   - Specific error message or symptoms
   - Proposed fallback/workaround action
   - Impact of the fallback action
   - Request for confirmation before proceeding

2. **Never silently apply workarounds** for:
   - API key expiration or authentication failures (Gemini, OpenAI, etc.)
   - Service downtime or unavailability (Llama Router, Weaviate, etc.)
   - Configuration changes that affect core functionality
   - Service disabling or enabling (systemd services, Docker containers)

3. **Examples requiring user notification:**
   - `Disabling Gemini API due to 401 errors` -> Ask first
   - `Switching to fallback service` -> Ask first
   - `Removing service configuration` -> Ask first
   - `Stopping systemd service` -> Ask first
   - `Gemini API returning 401 errors. Proposed action: switch to Llama Router. Impact: uses local model instead of Google API. Confirm?`

### Escalation Procedure

1. **Detect Issue:** Identify service failure or API key problem
2. **Assess Impact:** Determine what functionality is affected
3. **Propose Solution:** Suggest specific fallback or fix
4. **Notify User:** Present findings and proposed action clearly
5. **Await Confirmation:** Do not proceed without user approval
6. **Implement Solution:** Execute approved action
7. **Verify Resolution:** Confirm the fix works
8. **Document:** Update relevant documentation/KB

## Auto KB Processing (MANDATORY)

At the end of every assistant response that answers or completes a user request, you MUST:

1. **Append KB review section** with KB-worthy facts from the conversation:
   - Decisions, discoveries, infrastructure changes, conventions, and workarounds
   - Check existing KB entries for overlap before suggesting new entries
   - Update existing entries instead of creating duplicates
   - Archive outdated entries rather than deleting
   - Maintain single source of truth for each topic

2. **Automatically invoke auto-kb skill** to process the KB review section:
   - Auto-kb will check redundancy with existing entries
   - Auto-kb will update existing entries or create new ones as needed
   - Auto-kb follows consistent KB entry structure and quality criteria

3. **Exception**: Only ask for user confirmation when creating entirely new KB entries for major new topics (not updates to existing entries)

**KB-Worthy Triggers**:
- Fixing significant bugs or issues (especially data corruption, security vulnerabilities)
- Discovering new patterns, workarounds, or best practices
- Implementing new systems, integrations, or technologies
- Finding configuration optimizations or performance improvements
- Identifying language-specific challenges (Thai/English mixed content, encoding issues)
- Documenting root cause analyses of complex problems
- Creating reusable patterns or conventions

**Do NOT save**:
- Temporary commands or one-off output
- Obvious trivia or well-known information
- Transient debugging steps without lasting value
- Personal preferences without technical justification

## Immediate KB Creation (During Work)

For significant discoveries during work (not end-of-session):
1. Immediately suggest KB entry creation when encountering KB-worthy triggers
2. Ask user for confirmation before creating major new entries
3. Use auto-kb skill for processing to ensure consistency
4. Provide suggested KB entry title and brief description
5. Explain why it's KB-worthy (operational value, reusability, prevention)

## mcp-debug tool selection

When executing a host command via the `mcp-debug` MCP server:

1. Prefer `mcp_raw` for all commands by default.
2. Use `mcp_debug` only for commands marked `recommended: true` in `docs/ssot/infrastructure/ssot.mcp-debug.yml` (currently only `systemctl list-units`).
3. Vet any new command with `mcp_stats(host, command)` on both `tony_omen` and `tony_dell` before adding it to the `mcp_debug` whitelist. A command is efficient only when `savings_pct_chars` is positive on both hosts.
4. Keep `ssot.mcp-debug.yml` baselines and recommendation lists up to date by running the `mcp-debug-refresh-baselines` workflow after host or command changes.
5. Prefer the `mcp-debug` MCP tools (`mcp_report`, `mcp_stats`, `mcp_savings`, `mcp_preset_run`, etc.) over importing `mcp_debug` modules directly. Use the library only for server development or when the MCP server is unavailable.

## MCP Tools Policy

Before using any MCP server, use `ssot-search` or `grep` to read only the relevant `policy.<domain>` section in `docs/ssot/infrastructure/ssot.mcp-tools.yml`. Avoid full-file reads. Do not silently fall back without user confirmation.

## Request-to-Focus Workflow

At the start of every session, read `docs/ssot/ssot.focus.current.yml` to identify the active shared focus and active branch focus. For each user request:

1. Match it against active focus labels, subtasks, quick wins, and backlog items.
2. If it matches an active task, append a `request_log` entry and do the work inside that focus.
3. If it is a small standalone action, add it to `quick_wins` and complete it immediately.
4. If it is new strategic work, add it to the backlog in `docs/ssot/ssot.focus.yml` and ask the user to activate it.
5. If it comes from another session, save it as an inbox file in `docs/ssot/focus-inbox/` using the `save-to-focus` skill.
6. Never start a new activated task while another activated task is still unfinished.
7. For exact lookups in the full focus file, prefer `ssot-search` over reading the entire `ssot.focus.yml`.
8. At session end, update subtask statuses, append completed quick wins to focus history, and commit only the intended files.

## Subtask Inbox Triage

- At the start of every session, immediately after reading `docs/ssot/ssot.focus.current.yml`, invoke the `subtask-triage` skill on the active focus subtasks.
- The skill may only create new `docs/ssot/focus-inbox/*.yml` drafts and must leave `ssot.focus.current.yml` and `ssot.focus.yml` untouched.
- Treat any subtask that does not meet the quick_win_criteria as remaining in the active focus.

## Job Lifecycle (SSOT)

For context improvement/optimization jobs and any other critical/important work, create and maintain a job-lifecycle SSOT artifact before starting processing.

A critical job is any non-quick-win task that touches infrastructure, security, data, deploys, or cross-cutting systems, or any work the user explicitly marks as important.

1. **Create the artifact from the template.** Copy `docs/ssot/templates/job.yml` to `docs/ssot/jobs/<type>/<YYYY-MM-DD>-<short-name>.yml` and fill at least `planning` before processing begins.
2. **Keep it live as you work.** Update `processing` with steps, decisions, and changes. Append `followup` with verification, rollback, and handoff notes.
3. **Close with `report`.** The `report` section must be non-empty before the job is marked complete and before `auto-kb` is invoked.
4. **Pilot on `ssot-optimization-snapshot`.** The `ssot-optimization-snapshot` night job must emit the four lifecycle sections (`planning`, `processing`, `followup`, `report`) in its output once `scripts/ssot-optimize.mjs` is implemented.
