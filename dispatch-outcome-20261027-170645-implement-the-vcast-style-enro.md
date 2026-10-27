# Dispatch outcome — OPS-0951 jack-opencode-enrollment-gateway

## Result: DEPLOYED + VERIFIED on idc02 (tailnet edge live; public path gated)

The VCAST-style enrollment flow is live for the isolated Jack OpenCode
Podman IDE. Since the sibling IDE card (`jack-opencode-podman-ide`, still
backlog) had no runtime yet, this dispatch also stood up a minimal isolated
opencode pod so the gate has a real upstream — the parent card can iterate
on hardening.

## Architecture

```
browser ──https──> idc02.taila0626a.ts.net:8448
        (tailscale serve: TLS + tailnet auth, injects Tailscale-User-Login)
        v
127.0.0.1:8377  jack-enroll (rootless podman, loopback-only)
   /enroll /redeem/* /logout /admin/* /health — local
   everything else — session-gated proxy ──> http://jack-opencode:4096
        v                                     (private podnet jack-ide,
jack-opencode — `opencode serve` 1.19.4, no published ports,   no host route)
basic-auth upstream (injected by gw), /workspace + disposable HOME only
```

## What landed

- `stacks/idc02/jack-ide/` — full stack: `enroll-gw/server.mjs` + `enroll.html`
  + Containerfile, `opencode/Containerfile` + `opencode.json` (litellm
  provider, `mcp:{}`, external_directory deny), `jack-ide.network`,
  `jack-enroll.container`, `jack-opencode.container`, `jack-enroll.sh` admin
  CLI, `stack.yml` manifest, `README.md` runbook, `tests/`.
- `docs/ssot/jobs/devnest/2026-10-27-jack-enrollment-gateway.yml` — job doc.
- Host: quadlets installed (`UserNS=keep-id`), secrets in
  `~/.config/secrets/jack-{ide,enroll}.env` (600), LiteLLM key in container
  `auth.json`, scratch git repo seeded in workspace,
  `sudo tailscale serve --bg --https=8448 http://127.0.0.1:8377`,
  `~/.local/bin/jack-enroll`.
- Committed on dispatch branch `dispatch/20261027-170645-…` (no push).

## Card criteria — all verified live

| Requirement | Evidence |
|---|---|
| HTTPS /enroll behind authenticated edge | SPA enroll page 200 via `https://idc02.taila0626a.ts.net:8448/enroll`; gw requires `Tailscale-User-Login` (403 without it) |
| single-use code, hashed+consumed | `JCK-…` minted via `/admin/codes`; sha256-only in state.json; replay → `{"error":"code_used"}` |
| scoped Secure/HttpOnly/SameSite cookie | `jack_ide_sess=…; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200; Secure` → 303 to IDE |
| re-registration revokes prior session | new mint (exclusive default) → old cookie 401 |
| no creds to browser | **found+fixed:** `/config` echoed resolved `apiKey` — key moved to `auth.json`; config/cookie/page all clean |
| session proxy + WS | SPA 200, `/global/health`, SSE `server.connected` live through edge; WS upgrade tunnel unit-tested |
| revoke/health/TTL/audit/reset | `jack-enroll status/revoke/reset/audit/health`; code TTL 900s, session 12h; audit.jsonl records all events |
| tailnet first, CF Access after smoke | tailnet live; `jack.surf-thailand.com` documented in README, NOT deployed |
| one-time use / expiry / replay / unauth / boundary / UI | all of the above + `/etc/passwd` denied vs `/workspace` served; direct `:4096` unreachable from host; 401 no-cookie + forged-cookie |
| reuse VCAST pattern, no HA tokens/storage | same mint→redeem→session shape as ada `redeem_url`, standalone JSON state |

- 17/17 `node --test stacks/idc02/jack-ide/tests/` green.
- Real model call through LiteLLM inside the pod: `opencode run` → `PONG`.

## Ops quick ref

```
jack-enroll mint            # prints code + redeem URL (re-registers Jack)
jack-enroll status|audit|revoke|reset|health
```

## Follow-ups (carded on jack-opencode-podman-ide)

- Dedicated jack-scoped spend-capped LiteLLM virtual key (needs proxy
  admin on idc03; shared key is a placeholder).
- Public CF Access route after Tony sign-off.
- IDE hardening/evidence items from the parent spec.
