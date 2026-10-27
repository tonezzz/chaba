# jack-ide — isolated OpenCode IDE + one-time enrollment gateway (idc02)

VCAST-style enrollment for Jack's disposable OpenCode web IDE. The browser
never sees LiteLLM/MCP/host/SSH/Ada/Devin credentials — only an opaque
HttpOnly session ticket.

```
browser ──https──> idc02.taila0626a.ts.net:8448   (tailscale serve: TLS + tailnet auth,
        |                                         injects Tailscale-User-Login)
        v
127.0.0.1:8377  jack-enroll (podman, loopback-only)
        |  /enroll /redeem/* /logout /admin/* /health  — handled locally
        |  everything else — session-gated proxy ──────> http://jack-opencode:4096
        v                                              (private podnet jack-ide,
jack-opencode container — `opencode serve`, no published ports,     no host route)
basic-auth'd upstream, workspace + disposable HOME only
```

## Enroll Jack (operator flow)

```
jack-enroll mint            # one-time code + redeem URL; REVOKES the prior
                            # Jack session (re-registration is the default)
jack-enroll mint --shared   # extra code without revoking existing sessions
```

Hand Jack either the code (`JCK-XXXX-…`) for
`https://idc02.taila0626a.ts.net:8448/enroll`, or the printed redeem URL
(one click, QR-able). Codes are sha256-stored, single-use, default TTL 15 min.

## Ops

```
jack-enroll status      # sessions + pending codes (metadata only)
jack-enroll revoke [id] # kill one / all sessions
jack-enroll reset       # burn all sessions + codes (auth reset)
jack-enroll audit [N]   # audit.jsonl tail
jack-enroll health      # gateway + upstream
```

Workspace reset (files, not auth):
`systemctl --user stop jack-opencode && rm -rf ~/.local/share/jack-ide/workspace/* && systemctl --user start jack-opencode`

## Edge

- **Tailnet (live):** `sudo tailscale serve --https=8448 http://127.0.0.1:8377`
  (persistent). Gateway additionally requires `Tailscale-User-Login` on
  browser routes (`REQUIRE_EDGE_HEADER=1`) so only the served edge works.
- **Public (gated, NOT deployed):** after isolation smoke + Tony sign-off —
  add `jack.surf-thailand.com` to `~/.config/caddy/Caddyfile`
  (`reverse_proxy http://127.0.0.1:8377`) and a CF Access policy for Jack's
  email at `chaba-team.cloudflareaccess.com`, same pattern as
  `michael-dev.surf-thailand.com`. Do not bypass tailnet-only first.

## Security properties

- Codes + session tokens: sha256 server-side only (state.json leak ≠ usable creds).
- Session cookie: `Secure; HttpOnly; SameSite=Lax; Path=/`; TTL 12 h, fixed expiry.
- Upstream basic auth + admin token injected server-side; `Cookie`,
  `x-admin-token`, and `Tailscale-*` headers are stripped before proxying.
- opencode container: rootless, no published ports, no host mounts beyond
  its workspace + disposable home, `mcp: {}`, 2G RAM / 200% CPU caps.
- Every mint/enroll/replay/expiry/revoke/reset/denied-proxy/upgrade event is
  audited to `state/audit.jsonl`.

## Deploy (first time on idc02)

```
cp stacks/idc02/jack-ide/*.container stacks/idc02/jack-ide/jack-ide.network \
   ~/.config/containers/systemd/
podman build -t localhost/jack-enroll   stacks/idc02/jack-ide/enroll-gw
podman build -t localhost/jack-opencode stacks/idc02/jack-ide/opencode
install -m600 /dev/null ~/.config/secrets/jack-ide.env      # fill from .example
install -m600 /dev/null ~/.config/secrets/jack-enroll.env   # fill from .example
install -Dm644 stacks/idc02/jack-ide/opencode/opencode.json ~/.config/jack-ide/opencode.json
mkdir -p ~/.local/share/jack-ide/{state,workspace,opencode-home/.local/share/opencode}
# LiteLLM key goes into the container's auth store — NOT opencode.json, whose
# resolved apiKey is echoed back by /config and would leak to the browser:
python3 - <<'PY'
import json, re, os
key = re.search(r'(?m)^LITELLM_KEY=(.*)', open(os.path.expanduser("~/.config/secrets/jack-ide.env")).read()).group(1)
json.dump({"litellm": {"type": "api", "key": key}},
          open(os.path.expanduser("~/.local/share/jack-ide/opencode-home/.local/share/opencode/auth.json"), "w"))
PY
chmod 600 ~/.local/share/jack-ide/opencode-home/.local/share/opencode/auth.json
# seed a scratch git repo in workspace (see deploy log / job doc)
install -m755 stacks/idc02/jack-ide/jack-enroll.sh ~/.local/bin/jack-enroll
systemctl --user daemon-reload
systemctl --user start jack-ide-network jack-opencode jack-enroll
sudo tailscale serve --https=8448 http://127.0.0.1:8377
```

Tests: `node --test stacks/idc02/jack-ide/tests/`
