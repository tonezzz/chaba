# Customer WP site onboarding — LINE-managed

How a customer's WordPress site becomes maintainable through LINE chat.
Approved model 2026-10-27 (card `line-wp-site-manager`, Tony "proceed"
on the open question): **one dedicated LINE group per customer-site,
routed through the existing tony/kk-style lane pattern, with a per-site
`wp-<slug>.env` WP Application Password — Option A identity map.** The
customer never sees credentials; secrets policy applies — nothing goes
into LINE where it persists in history/Yomi index.

Registry: `docs/ssot/apps/ssot.wp-boards.yml` `sites:` — every managed
site must land there. LINE routing:
`docs/ssot/apps/ssot.messaging-lanes.yml` `line.routing`.

## Model

```
customer LINE group ──LINE_GROUP_PERSONA──> ada-<slug> lane (idc03)
                                              │  env: wp-<slug>.env
                                              ▼
                                     WP REST (app password)
                                              │
                                     customer's WP site
```

Isolation is structural: `backend/wp_client` reads
`WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD` from the lane's process env —
a lane can only reach the site its env names, and no `site` parameter
exists for the model to aim elsewhere. Per-site app passwords are
individually revocable in the customer's wp-admin.

## Checklist

### 1. WP side (customer's host/Plesk)

- [ ] WP installed and front page serves 200. On Plesk vhosts without
      nginx rewrites, set permalinks to `/index.php/%postname%/`
      (boards precedent — plain `/wp-json/` may 404; the
      `index.php?rest_route=` form always works).
- [ ] **Mint an Application Password**: wp-admin → Users → the bot
      user's profile → Application Passwords → name it `chaba-<slug>`.
      Create a dedicated low-privilege WP user (Editor) for this —
      never use the admin account, never send the master password to
      anyone. The password is shown once — hand it to the agent on the
      ops host directly (secret-drop or ssh edit), never via LINE/chat.
- [ ] Verify: `python3 scripts/wp-boards/site-preflight.py <site-url>`
      (anonymous checks — front page, REST index, route style, user
      enumeration posture).

### 2. Secrets (idc03)

- [ ] `python3 scripts/wp-boards/site-preflight.py <site-url> \
      --write-env ~/.config/secrets/wp-<slug>.env --user <wp-user>` —
      writes `WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD` mode 0600,
      password never echoed. Then re-run with `--env-file` to confirm
      auth: `users/me` must return 200 as the bot user.
- [ ] Register the file in `ssot.secrets.yml` under
      `wp-boards-app-password` slots (host/file/vars).

### 3. Lane (idc03 — clone ada-kk)

Per `ssot.apps.ada-persona-lanes.yml` + `docs/kb/msg-lane-standard.md`:

- [ ] `persons.<slug>` entry in `ssot.apps.ada-persons.yml` — tool
      profile = member-site set: `wp_read`, `wp_update`, `wp_post`,
      `chat_send`, `cms_read`, core memory/search. No HA tools (no
      ha_upstream), no internal ops tools.
- [ ] Instance entry `ada-<slug>` in persona-lanes `instances:` — pick
      an unused loopback port (see the 800x/891x allocations),
      `env_file: ~/.config/secrets/ada-<slug>.env`, own
      `keys_file`/`bank`/`events`, `upstream_ha: none`, own Gemini key
      or LITELLM virtual key per the per-instance secrets model.
- [ ] Lane env file carries the site creds (copy the three `WP_*`
      vars from `wp-<slug>.env` or add a second `EnvironmentFile=` to
      the unit) plus `ADA_INSTANCE_ID=<slug>` and the identity block.
- [ ] systemd user unit cloned from `ada-kk.service`, enabled.
- [ ] Optional: own CMS collection `ada-cms-pages-<slug>` if the
      customer gets reports (kk pattern); skip for site-only lanes.

### 4. LINE wiring

- [ ] Customer creates a LINE group, invites the chaba bot
      (@339sbrov). Bot greets with the groupId.
- [ ] Add the group to `ssot.messaging-lanes.yml` `line.routing.groups:` (persona =
      the lane's persona name) + relay env on idc03:
      `LINE_ALLOWED_GROUP_IDS`, `LINE_GROUP_PERSONA=<gid>:<persona>`,
      `LINE_NAME_BACKENDS` persona → `ws://127.0.0.1:<port>/ws`.
      Restart `ada-line-relay`.
- [ ] `LINE_USER_CALLERS` entry for the customer's LINE userId →
      `user-<slug>` (no admin fallback — unmapped senders get refused).
- [ ] Timeline: `scripts/ada/line-chat-timeline.py` picks the group
      journal up automatically; the lane's private `/chat/line/<lane>/`
      page appears on its site if configured.

### 5. Verify (consumer surface, not just services)

- [ ] From the customer group: "what's on my site" → `wp_read` list
      replies in-group with `[persona->sender]` tag.
- [ ] "draft a post about X" → `wp_post` draft → "publish it" →
      `wp_update` asks for confirmation → member "yes" → live URL.
      The confirm gate must actually engage (policy:confirmed).
- [ ] Cross-lane check: customer lane cannot see boards-site content
      and vice versa (env isolation, not a filter).
- [ ] `site-preflight.py <site-url> --env-file` green; register the
      site row in `ssot.wp-boards.yml` `sites:` and mark the card.

## Notes

- Revocation = delete the app password in the customer's wp-admin.
  Nothing else needs to change; the lane fails closed (401).
- A customer lane is a prod lane — dev twin optional; the standard
  dev-first CI (persona-lanes `ci:` block) applies when it exists.
- Push replies in customer groups count against the LINE monthly
  quota (429 seen 2026-10-14); replies to inbound are free.
