---
category: operations
---

# Phase 1 — Install and Verify Tailscale

### On `tony-omen` (Ubuntu)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo systemctl enable --now tailscaled
```

Check status:

```bash
tailscale status
tailscale ip -4
```

### On mobile/remote devices

Install the Tailscale app, sign in with the same account, and accept the device in the admin console.

### Validate peer-to-peer connectivity

From a remote device:

```bash
tailscale ping tony-omen
```

## Phase 2 — Choose Hostname and IP Strategy

Decide on one of the following:

1. **Magic DNS** (easiest): use `tony-omen` (short name inside tailnet) or `tony-omen.tailXXXX.ts.net`.
2. **Tailscale IP** (stable, human-unfriendly): use the `100.x.x.x` address assigned to `tony-omen`.
3. **Custom machine name**: rename the device in the Tailscale admin console to `tony-omen` if it is not already.

Recommendation: use the short Magic DNS name `tony-omen` inside the tailnet for services that are protected by the tailnet, and keep `tony-omen.local` for the home LAN profile.

## Phase 3 — Prepare `tony-omen` Services

1. Verify Caddy and any non-Docker services listen on all interfaces or the Tailscale interface:
   - `stacks/web/Caddyfile` / Docker Caddy container: should bind to `0.0.0.0` or at least `100.x.x.x` and `127.0.0.1`.
   - If `llama-router` (port `8001`), `postgres` (port `5432`), or other ports are bound to `127.0.0.1`, rebind them to `0.0.0.0` or the specific Tailscale IP.
2. Confirm no new ports need opening in the firewall; Tailscale uses outbound UDP and can punch through NAT.
3. Test service reachability over the Tailscale IP:

```bash
# from a remote device
curl http://$(tailscale ip -4 tony-omen):8080/api/health
curl http://tony-omen:8080/api/health
```

