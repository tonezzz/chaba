# Draft feature request for openchamber/openchamber

File at: https://github.com/openchamber/openchamber/issues/new?template=feature_request.yml
A PR without an accepted feature request is auto-closed (`needs-accepted-issue`),
so this issue must exist and be marked `accepted` before the PR is opened.

## Title

Model status endpoint: report which catalog models actually answer

## Body (plain words, per CONTRIBUTING.md)

I run a LiteLLM gateway in front of several upstream providers, and the model
picker happily offers models whose upstream is down or out of quota — the
failure only shows up when a session tries to use them.

I would like a way to ask the server which catalog models are actually
servable right now: something like `GET /api/openchamber/models/status`
returning, per model, whether a minimal completion succeeds, plus the
provider's error when it does not. A `models.status` control action alongside
`models.search` would cover both the HTTP surface and agent tooling.

The check should be generic: probe providers whose package speaks the
OpenAI chat-completions API and that have a configured `baseURL`, resolving
the key the same way the rest of the app does (config `apiKey` with
`{env:NAME}` references, then the stored credential). Models on other APIs
(Anthropic, responses-only, Google) should report their catalog status rather
than a false "unavailable".
