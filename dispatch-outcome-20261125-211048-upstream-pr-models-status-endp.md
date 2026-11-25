# Dispatch outcome — upstream-pr-models-status-endpoint-for-o-280615

## What was done

Ported the OpenChamber `models.status` patch (currently applied to the built
`@openchamber/web` bundle on idc02) to the upstream TypeScript source of
`github.com/openchamber/openchamber` (cloned @ `9909e71`, branch
`feat/models-status-endpoint`, commit `78bbfb5`).

### Generalization vs the dist patch

The dist patch hardcoded `litellm` / `LITELLM_URL` / `LITELLM_KEY`. The
upstream port resolves the probe target per catalog model:

- Provider `package` must be an OpenAI chat-completions package
  (`aisdk:@ai-sdk/openai`, `aisdk:@ai-sdk/openai-compatible`,
  `@opencode/ai/providers/openai`, `.../openai/chat`,
  `.../openai-compatible`, `.../openai-compatible-responses`); model-level
  `package` overrides provider-level. Anthropic/responses-only/Google
  providers report catalog status only — a chat-completions probe would
  false-negative them.
- `baseURL` from model `settings.baseURL` then provider
  `settings.baseURL` (http(s) only).
- Key from `settings.apiKey` with `{env:NAME}` resolution (other
  placeholders like `{file:}` stay unresolved), falling back to the stored
  OpenCode credential via `getProviderAuth` (api-type keys only).
- Provider `headers` are forwarded to the probe.
- Probes run concurrently (`Promise.all`), 10s timeout each, `max_tokens: 1`.
- Catalog read goes through `readLocationCatalog` so plugin-defined
  providers on cold locations are waited for (same as `models.search`).

### Files (upstream repo)

- `packages/web/server/lib/openchamber-control/models-status.ts` (new) —
  `createModelsStatusAction({ getClient })` factory, matching the
  `createUsageReadAction` module pattern.
- `actions.ts` — `models.status` definition (agent-exposed like
  `models.search`).
- `service.ts` — dispatch line merged onto the `models.search` branch
  (zero net line growth; see lessons).
- `self-update/openchamber-routes.ts` — `GET /api/openchamber/models/status`,
  optional `controlService` dep, 503 when unwired, 504/502 on failure.
  Inherits the blanket `/api` auth gate.
- `server-frame/bootstrap-runtime.ts`, `runtime.ts` — wiring
  (`controlService: openChamberControlService`; merged onto an existing
  line for the same ratchet reason).
- `openchamber-control/DOCUMENTATION.md` — behavior contract.
- Tests: service-level (active/unavailable/catalog-status, `{env:}` key,
  provider filter) and route-level (200 + 503).

## Verification

- `bun run check:changed` — **all checks passed** (type-check 5,329 files,
  server lint incl. custom anti-slop rules, knip, ratchet, file-size).
- `bunx vitest run server/lib/openchamber-control/service.test.js
  server/lib/self-update/openchamber-routes.test.js` — **266 passed**.
- Clone + `bun install` + full check ran inside
  `.upstream-work/openchamber/` in this worktree (untracked, not committed).

## Deliverables (committed on dispatch branch `dispatch/20261125-211048-...`)

- `stacks/idc02/openchamber/upstream/models-status-ts.patch` —
  `git format-patch` of the upstream commit.
- `stacks/idc02/openchamber/upstream/ISSUE.md` — draft feature request.
- `stacks/idc02/openchamber/upstream/PR-BODY.md` — draft PR description
  with the required Affected surfaces / Validation tables.

## Blocker — PR not opened

Upstream `CONTRIBUTING.md` auto-closes any PR that doesn't link an accepted
feature-request issue (`needs-accepted-issue`), and this host has no `gh`
CLI, no GitHub token, and no `tonezzz/openchamber` fork. Next step needs
Tony (or a host with GitHub creds): file `ISSUE.md` on
openchamber/openchamber, wait for `accepted`, push the branch to a fork,
open the PR with `PR-BODY.md` + `Fixes #N`. The clone with the commit is at
`.upstream-work/openchamber` (branch `feat/models-status-endpoint`) if the
session worktree is still around; otherwise apply `models-status-ts.patch`
to a fresh clone.

## lessons:

- openchamber repo ratchet: source files >800 lines cannot grow — extract
  new behavior into a sibling module (`createXAction` factory pattern) and
  keep wiring edits line-neutral (merge onto an existing line) in
  service.ts/runtime.ts.
- openchamber lint bans new `//` comments in product code (rationale goes in
  the module's DOCUMENTATION.md) and `unknown` function params
  (anti-slop `no-unknown-parameters`) — use `JsonValue`/domain types.
- `readLocationCatalog` (not raw `client.model/provider.list`) is required
  for catalog reads — it waits for location plugins so plugin-defined
  providers appear.
- Upstream contribution gate: feature PRs need an accepted feature-request
  issue first; check CONTRIBUTING.md before drafting PRs for external repos.
