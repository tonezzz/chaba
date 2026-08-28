---
category: operations
---

# Phase 4 — Update SSOT and Health Check Files

### `docs/ssot/ssot.mysystem.mobile.yml`

- Mark the `VPN/Tunnel` item under `Dynamic IP Solutions` as `status: done`.
- Add a `Tailscale` profile next to `Home Profile` and `Mobile Profile`:
  - `text`: Stable tailnet access using `tony-omen` name.
  - `config`: `ssot.mysystem.mobile.yml`.
  - `health_config`: `ssot.health.mobile.yml`.
  - `switch_method`: Connect via Tailscale app, then use `tony-omen`.
- Update the `tony-omen` workstation `current_access`:
  - `text`: `Accessible via Tailscale as tony-omen`.
- Update the `Services` and `Access & URLs (Mobile)` sections from `http://[current-ip]:...` to `http://tony-omen:...`.

### `stacks/web/public/ssot.health.mobile.yml`

- Replace `http://tony-omen.local:...` with `http://tony-omen:...` for all `url` fields (or the chosen full Magic DNS name).
- Update the `hostname_resolution` recovery note:
  - Replace the note about `tony-omen.local` resolving to `172.20.10.7`.
  - Add: "On mobile, connect to Tailscale first; use `tony-omen` instead of `tony-omen.local`."
- Keep the `vpn_required` recovery action but update the text to reference Tailscale specifically.

### `docs/ssot/infrastructure/ssot.health.yml`

If this is the source copy, mirror the same changes made to `stacks/web/public/ssot.health.mobile.yml`.

## Phase 5 — Update Hostname Standards

### `.windsurfrules`

Add a Tailscale clause to the existing hostname usage standards:

```markdown
- Use `.local` hostnames on the home LAN.
- Use Tailscale hostnames (`tony-omen`) or Magic DNS (`tony-omen.tailXXXX.ts.net`) for remote/mobile access.
- Use `100.x.x.x` Tailscale IPs only where hostnames cannot be resolved.
```

## Phase 6 — Validate and Smoke Test

1. From the mobile/remote device on the tailnet:

```bash
tailscale status
tailscale ping tony-omen
```

2. Test a few key endpoints:

```bash
curl http://tony-omen:8080/api/health
curl http://tony-omen:8001/health
curl http://tony-omen:8080/apps/health-check/
```

3. Run the health check mobile configuration:

```bash
# from the health-check project directory or via the configured health-check runner
./health-check stacks/web/public/ssot.health.mobile.yml
```

4. Run the project validation tools:

```bash
skill ssot-validate
```

## Phase 7 — Optional Enhancements

- **Subnet routes**: advertise the `192.168.1.0/24` home subnet from `tony-omen` so remote devices can reach non-Tailscale LAN devices.
- **Exit node**: make `tony-omen` an exit node for secure mobile internet routing.
- **Headscale**: if the cloud coordination server is not acceptable, migrate to a self-hosted Headscale instance later.

