---
name: info-find
description: Unified information-finding for any project — routes a query across local SSOT/code, MDDB semantic docs, policy-allowlisted MCP, service-health sources, and web; returns ranked results with citations. Read-only, fails safe per source, cache/audit isolated per project+session.
allowed-tools:
  - exec
  - grep
  - read
  - web_search
  - webfetch
  - mcp_call_tool
  - mcp_list_tools
triggers:
  - user
  - model
---

Portable unified info-find (DevNest phase-1 conversational skill; card
`devnest-info-find-skill`). Works in any checkout that carries
`scripts/devnest/info_find.py` — the shared planner + source adapters do
the fan-out; the agent only runs the script and services the deferred
rungs.

1. Run the shared planner/adapters from the repo root:

   ```bash
   python3 scripts/devnest/info_find.py run --query "<query>" --format md
   ```

   Flags: `--quick` skips MDDB/web (local only); `--web` forces the web
   rung; `--collection <name>` overrides MDDB collections;
   `--session <id>` pins the audit session; `--probe-health` also GETs
   the URLs declared in matching `ssot*health*.yml` files.
   `--format json` gives the full machine-readable result.

2. Read the output contract:
   - `results[]` — ranked, deduped; every entry has `source`, `ref`
     (file:line, `mddb://<collection>/<key>`, or URL), `excerpt`,
     `score`, `rank`. Rank order: MDDB semantic docs → web → SSOT →
     health → code.
   - `sources{}` — per-source `status`: `ok` | `degraded` |
     `unavailable` | `deferred`. An `unavailable` source is reported,
     never fatal — answer from the sources that did return, and say
     which were skipped.
   - `deferred` — rungs the script cannot perform (web search, MCP
     calls). Service them yourself per step 3.

3. Service deferred rungs (only when listed in `deferred`):
   - `web` — run `web_search` with the step's `query` (for `explore`
     intents the first query is `<query> github` — the GitHub precedent
     rung — then the bare query). Optionally write the hits as JSON to a
     file and re-run with `--web-json <file>` to merge them into the
     ranked output.
   - `mcp` — the step lists the policy domains parsed from
     `docs/ssot/infrastructure/ssot.mcp-tools.yml`. Pick the relevant
     `primary` server, `mcp_list_tools` it, then `mcp_call_tool`.
     Never call a server outside the policy allowlist; on failure,
     notify instead of silently falling back.

4. Cite in the answer: every factual claim needs a `ref` from the
   results — a repo path (with line), an `mddb://` key, or a URL. If
   nothing answers the question, say "not found" and list which sources
   were consulted (visible in `sources{}`).

5. Close the audit: after answering, append a one-line outcome:

   ```bash
   python3 scripts/devnest/info_find.py record \
     --session <id> --result '{"q":"…","answered":true,"top":"<ref>"}'
   ```

Safety / isolation contract:

- Read-only: the adapters only read the checkout, GET health URLs, and
  POST read-only `/v1/vector-search`. They never write outside the
  cache dir, never call mutating endpoints, never read
  `~/.config/secrets`.
- Cache + audit live under `~/.cache/devin/info-find/<project>/
  sessions/<session>/` — project comes from the git remote basename,
  session from `--session` / `DEVIN_SESSION_ID` / `$TASK_DIR` / pid.
  Other sessions and projects cannot see these files. Override with
  `INFO_FIND_CACHE_BASE` (e.g. inside a task dir).
- Unattended/read-only lanes (e.g. the opencode `info-find` profile):
  run step 1 and stop — deferred rungs are reported as `deferred` in the
  artifact, not silently executed.
