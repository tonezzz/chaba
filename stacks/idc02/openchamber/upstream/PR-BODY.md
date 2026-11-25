# Draft PR body for openchamber/openchamber

Branch: `feat/models-status-endpoint` (commit 78bbfb5, based on main @ 9909e71)
Patch: `models-status-ts.patch` in this directory.

Before opening: the PR description must link the accepted feature request
(`Fixes #N` or `Part of #N`) — see CONTRIBUTING.md "Before you start".
Without it the PR is auto-closed with `needs-accepted-issue`.

Fill `.github/PULL_REQUEST_TEMPLATE.md` sections:

## What and why

Model pickers and agent tooling can only see the catalog — they cannot tell
that a model's upstream provider is down or out of quota until a session
fails mid-turn. This adds `models.status`, a control action (and the matching
`GET /api/openchamber/models/status` route) that probes each catalog model
whose provider speaks the OpenAI chat-completions API with a minimal
completion (`max_tokens: 1`, 10s timeout) and reports `active`,
`unavailable` (with the provider's error), or `error` (transport failure).
Models on other APIs report their catalog status unchanged, with
`catalogStatus` always echoed so a probe result never hides catalog state.

Ported from a patch we have been running against the built server bundle;
the upstream version generalizes it — the probe target comes from each
provider's configured `package` + `settings.baseURL` instead of hardcoded
LiteLLM env vars, and the key resolves from `settings.apiKey` (`{env:NAME}`
references supported) with a fallback to the stored OpenCode credential.

## Affected surfaces

| Runtime | What you ran and saw |
|---|---|
| Web | `bun run check:changed` clean (type-check 5,329 files, lint, knip, ratchet, file-size); `vitest run server/lib/openchamber-control/service.test.js server/lib/self-update/openchamber-routes.test.js` — 266 tests pass, including new coverage for the action and the route. |
| Desktop (Electron) | Same server code as Web; not run in the desktop shell. |
| VS Code | Does not run the OpenChamber server; not applicable. |
| Hosted mobile | Same server code as Web; not run against a hosted instance. |
| Capacitor mobile | Same server code as Web; not run on device. |
| Relay | No relay code touched. |

## Validation

- `bun run check:changed` — all checks passed.
- `bunx vitest run server/lib/openchamber-control/service.test.js server/lib/self-update/openchamber-routes.test.js` — 266 passed.
- New tests: service-level `models.status` (active/unavailable/catalog-status
  paths, `{env:}` key resolution, provider filter) and route-level
  (200 passthrough with provider filter, 503 without control service).
