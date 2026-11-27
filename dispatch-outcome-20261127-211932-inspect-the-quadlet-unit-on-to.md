# dispatch-outcome — gemini-ollama-proxy-conmon-logtag-failure

## What was found

The card's named cause (--log-tag / k8s-file conmon rejection) was already
half-fixed before this session, and a second blocker was hiding behind it:

1. **log-tag**: tony-dell's `~/.config/containers/containers.conf` had
   `log_tag = "{{.Name}}/{{.ID}}"` with `log_driver = "k8s-file"` — pushed
   fleet-wide 2026-11-26 ~11:24-12:35. The 2026-11-26 fix job
   (`2026-11-26-podman-conmon-log-tag-fix.yml`) removed it on
   con01/idc02/idc03 but exempted dell/omen assuming conmon 2.1.13 accepts
   --log-tag. **That assumption was wrong** — dell's conmon 2.1.13 +
   k8s-file rejects --log-tag identically (journal proof 11:48-11:56).
   Someone had already commented the line out on dell at 2026-11-26 19:35
   ("broke web.service"); web.service is the healthy canary.
2. **missing env file**: the quadlet installed by
   `gemini-proxy-quadlet-envfile-drop` declares
   `EnvironmentFile=~/.config/secrets/mddb-gemini.env` — the file never
   existed on dell (only idc03 had it). `podman --env-file` on a missing
   path is a hard error, so the unit could not start regardless.
3. The unit was also stuck in systemd failed state (start-rate-limited
   since 11:56:44 Nov 26) — needed `reset-failed`.

## What changed

- **tony-dell**: provisioned `~/.config/secrets/mddb-gemini.env` (mode 600)
  by piping idc03's canonical file over SSH — contents never displayed;
  key-name diff identical (19 keys). This completes what
  gemini-proxy-quadlet-envfile-drop intended but only applied on idc03.
- **tony-dell**: `systemctl --user reset-failed` + `start
  gemini-ollama-proxy.service` → active (running) at 21:36:23 +07.
- **Repo (this branch)**: `docs/ssot/infrastructure/ssot.audit.hosts.yml` —
  removed dell's `known_failed` tolerance entry and added an
  `expected_services` declaration (active, non-critical) so the daily
  audit now guards the unit.
- Job trail: `docs/ssot/jobs/infrastructure/2026-11-27-gemini-ollama-proxy-dell-conmon-logtag.yml`.

## Result / verification

- conmon cmdline shows `-l k8s-file:...` with **no --log-tag**; journal
  clean since start.
- `GET http://127.0.0.1:11435/health` → 200, `status:ok`,
  `provider_mode:gemini-primary`, `embed_gateway:embedding`,
  `free_keys:6`, all spend caps delivered — proves env-file delivery.
- `POST /api/embed` → 200, real 768-dim vector via `gemini-embedding-2`
  in 653ms — end-to-end embed works, not just the listener.
- `podman ps`: `systemd-gemini-ollama-proxy Up`; 60s HealthCmd keeps watch.

## How to verify

```
ssh tony-dell-m2m 'systemctl --user is-active gemini-ollama-proxy.service; \
  curl -sf http://127.0.0.1:11435/health | head -c 200'
```

Rollback: `systemctl --user stop gemini-ollama-proxy.service` + remove the
env file on dell (unit was already failed — nothing depended on it).

lessons:
- conmon 2.1.13 k8s-file rejects --log-tag just like 2.1.10 — the prior fix job's "dell/omen are safe" exemption was assumed, never tested; verify the exact host's conmon before exempting it from a fleet config fix.
- A quadlet fix can be DOA on a second missing file: envfile-drop patched the quadlet on two hosts but only idc03 had ~/.config/secrets/mddb-gemini.env — check every file a generated unit references exists on THAT host.
- podman --env-file on a missing path is a hard create-time error (before conmon runs) — it extends/masks the visible failure signature.
- systemd start-rate-limit leaves units in failed state forever — a fixed root cause still needs reset-failed + start.
- The proxy's /health self-reports env delivery (free_keys, caps) — consumer proof without exposing secret values.
