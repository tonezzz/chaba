# One Wiki / two surfaces — MediaWiki private-SSO boundary design

Card: `mediawiki-private-sso-boundary` (SEC-1035) · Date: 2026-11-26 · Author: OpenCode dedicated session
Status: **DESIGN + stage-0 evidence only — no live host, wiki, Cloudflare or Google config was mutated.**

## 1. Verified current state (read-only probes, 2026-11-26)

| Probe | Result |
| --- | --- |
| `GET wiki.h3.gizmo-thailand.com/api.php?action=query&meta=siteinfo&siprop=namespaces\|extensions` | HTTP 200. Extensions loaded: PluggableAuth, OpenID Connect, Lockdown, Cargo, PageForms, CategoryTree, Mermaid, MsUpload, MultimediaViewer, Springboard. Namespaces: `Infrastructure` 3000, `PrivateNews` 3002, `Education` 3004, `Reports` 3006 (+ talk). **No `Home:`, `Ops:` or `Draft:` namespace exists.** |
| Anon read `News/Desks/DevNest/Ada/First-Publication-Test` on wiki.h3 | HTTP 200 with wikitext — public News is anonymous-safe. |
| Anon read `Infrastructure:Hosts` on wiki.h3 | `accessdenied` — Lockdown boundary intact. |
| Spoofed `Cf-Access-Authenticated-User-Email: tonezzzz@gmail.com` on **public** wiki.h3 → `Infrastructure:Hosts` | `accessdenied` — MediaWiki does **not** trust CF identity headers. |
| `wiki-internal.surf-thailand.com` from idc02 (non-allowlisted) | 302 → `chaba-team.cloudflareaccess.com` Access login. Private host is gated. |
| `ada-ha.surf-thailand.com` from idc02 | 302 → the **same** `chaba-team.cloudflareaccess.com` Access login domain. |
| CF Access apps (API read) | `ada-ha` = `775374be-bd6c-443d-8cac-9597e3a40e66`; `wiki-internal` = `189b0d42-1b10-4ef8-a336-c23e0ad0306c`. Both `self_hosted`, `session_duration=720h`, both policies = `allow-tony` + `allow-tony-gmail` (tonezzz@hotmail.com, tonezzzz@gmail.com), no `exclude`/`require`. **Edge policy parity is already achieved.** Difference: wiki-internal has `auto_redirect_to_identity=true`, ada-ha `false`. |
| Direct-origin bypass: `curl -k --resolve wiki-internal.surf-thailand.com:443:103.99.11.249 https://wiki-internal.surf-thailand.com/api.php?...` | **HTTP 200 from MediaWiki, no Access challenge.** Direct-to-origin with the private Host header bypasses Cloudflare Access entirely. Spoofed CF header there still yields `accessdenied` for `Infrastructure:` (Lockdown saves the content), but the surface itself is reachable and enumerable. |
| `wiki-internal.h3.gizmo-thailand.com` SNI → origin IP | HTTP 200, base URL host-aware (`https://wiki-internal.h3.../index.php?...`) — the old 301-to-public blocker is resolved. |
| `wiki.surf-thailand.com` | HTTP 200 anon — a **second public alias**, same wiki. Treat as public surface. |
| Ada HA dashboard `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` | "Private Wiki" tab already points at `https://wiki-internal.surf-thailand.com/index.php?title=Infrastructure:Hosts&v=2`, with an "open in new tab" note (Google blocks iframe sign-in). **No token/password in the URL.** |
| `python3 scripts/wiki-cargo-check.py` | `ok:true`, exit 0, table `Education`, 233 rows. Cargo gate satisfied — do **not** re-apply declare/store. |

## 2. Target design

```
                     Cloudflare (chaba-team.cloudflareaccess.com)
                     one account / one Google IdP / Tony's 2 emails / 720h
                                  |                         |
                       ada-ha.surf-thailand.com    wiki-internal.surf-thailand.com
                       (Access app 775374be)       (Access app 189b0d42)
                                  |                         |
                                  +------ same Wiki ---------+
                                   Plesk origin 103.99.11.249
                                   (one MediaWiki, one DB)
                                  /                          \
                    public surfaces                      private surface
        wiki.h3.gizmo-thailand.com                 wiki-internal.surf-thailand.com
        wiki.surf-thailand.com                     (Access-gated + origin-hardened)
        anon-safe: News/ only                      Lockdown: Infrastructure:/PrivateNews:/
                                                   Education:/Reports: → inhouse/sysop/members
```

**Trust chain (private surface):** CF Access authenticates Tony by Google → forwards to origin → MediaWiki OIDC (PluggableAuth + OpenID Connect, same Google issuer) authenticates the browser session → PluggableAuth `mapped` groupsync maps Tony's verified `email` claim to the local `inhouse` group → Lockdown grants read on the protected namespaces. Edge and wiki are two independent gates; neither trusts an identity header from the other side. The Ada bot is a **local** sysop/inhouse service account used by board-api; it never authenticates through Google and must stay in `locallyManaged` so groupsync cannot strip it.

**Public surfaces:** no `$wgPluggableAuth_EnableAutoLogin` — anonymous read stays possible for `News/`. Lockdown continues to deny `Infrastructure:`, `PrivateNews:`, `Education:`, `Reports:` to anon. CF identity headers are ignored by MediaWiki (verified above).

## 3. MediaWiki config shape (review target — NOT applied)

```php
// LocalSettings.php — Plesk host path; edit only via the admin path, with backup.
// 1) Keep host-aware $wgServer (already live); never canonical-redirect
//    wiki-internal.* to wiki.h3.*. Do NOT enable auto-login on public hosts.
// 2) Group auto-provision/map for the OIDC login:
$wgPluggableAuth_Config[] = [
    'plugin' => 'OpenIDConnect',
    'data' => [ /* providerURL/clientID/clientsecret loaded from the 0600 secret file */ ],
    'buttonLabelMessage' => '...',           // fixes the broken "0" label
    'groupsyncs' => [[
        'type' => 'mapped',
        'map' => [
            'inhouse' => [ 'email' => [
                'tonezzz@hotmail.com', 'tonezzzz@gmail.com',
            ] ],
        ],
        'addOnlyGroups' => [ 'sysop', 'bureaucrat' ], // Ada bot + local admins stay
    ]],
];
```

Rationale: Google does not emit group claims; PluggableAuth 7.x `mapped` groupsync can map any ID-token attribute, and OpenIDConnect's `getAttributes()` merges the ID-token payload, so `email` is available. `addOnlyGroups` keeps locally-assigned sysop/bureaucrat (Ada bot) from being removed. Secret values stay in the existing 0600 Plesk secret file; never in LocalSettings.php plaintext, chat, or iframe URLs.

**Lockdown:** retain the existing read arrays for `Infrastructure:` (3000), `PrivateNews:` (3002), `Education:` (3004), `Reports:` (3006) — `inhouse`/`sysop` full read, `members` read only on Education/Reports. Do **not** grant read to `*` and do not let the public hostname inherit private grants. `Home:`, `Ops:`, `Draft:` are not registered; see Blocker B2.

## 4. Smallest safe staged implementation

- **Stage 0 — DONE (this session):** read-only verification above; design recorded on card through board-api `/comment`; no live writes. Cargo gate confirmed exit 0.
- **Stage 1 — origin hardening (admin/Plesk, blocking):** on the Plesk vhost for the private hostname, allow only Cloudflare origin IPs and reject `Cf-Access-*` headers from any other client. Use Plesk HTTPS :8443 Terminal (SSH 22/2222 blocked; FTP 21 fallback), back up the vhost config first. This closes the confirmed direct-origin bypass. Verify with the same `--resolve` probe: expect 403/connection refusal instead of HTTP 200.
- **Stage 2 — IdP callback (human, Google Cloud Console):** register the percent-encoded Thai callback on the approved Google OAuth client — `https://wiki-internal.surf-thailand.com/index.php?title=%E0%B8%9E%E0%B8%B4%E0%B9%80%E0%B8%A8%E0%B8%A9:PluggableAuthLogin` (and the English `Special:` form). Google console rejects raw Thai characters; store the encoded value. See Blocker B3 for client choice.
- **Stage 3 — LocalSettings group map (admin/Plesk):** apply the snippet in §3, fix the login-button label, keep `$wgPluggableAuth_EnableAutoLogin=false` on public hosts. Back up LocalSettings.php, then verify `Special:Version`, the wiki health endpoint, and login from a normal browser tab.
- **Stage 4 — access verification (no secrets in URLs):** anon deny on private host; Tony login → `inhouse` read on `Infrastructure:Hosts`; Ada/sysop read; anon News allow on both public hosts; spoofed header deny; direct-origin deny. HA dashboard already points at the private hostname with a new-tab note — keep it; do not embed tokens.
- **Stage 5 — record evidence:** job SSOT under `docs/ssot/jobs/infrastructure/` + card comment via board-api; mirror the lesson to KB/MDDB. Wiki documentation, if any, goes through `/publish` with `sinks=["wiki-education"]`, `visibility=private`, fresh `event_id`, and `source:"wiki"` readback — never a direct MediaWiki edit.

## 5. Rollback

Remove the private hostname from the HA tab and the CF Access app/domain, revert LocalSettings.php from the timestamped backup (disable the groupsync block first), leave public News and Lockdown untouched. Origin-hardening rules are a separate reversible vhost change. No rollback is needed for anything done in Stage 0.

## 6. Blockers / decisions (reported, not forced)

- **B1 — Confirmed direct-origin bypass.** `wiki-internal.surf-thailand.com` answers MediaWiki HTTP 200 when addressed straight to 103.99.11.249. Fixing it requires Plesk :8443/Terminal admin; SSH is blocked. Not attempted here.
- **B2 — `Home:`, `Ops:`, `Draft:` do not exist.** The card asks to "retain Lockdown namespace read rules" for them, but siteinfo registers only Infrastructure/PrivateNews/Education/Reports. Needs Tony to confirm whether those are aliases for the existing namespaces or new namespaces to be created via the Plesk/LocalSettings path. Not created here.
- **B3 — OIDC client conflict.** Card request `oidc-client-registration` was answered `register-new-google-client`, but later evidence shows client `517766007004-7vp0c2qjdeee515qp5d580g0nh02p2qh.apps.googleusercontent.com` already serving wiki.h3/wiki.surf with Thai-alias callbacks registered. Recommendation: add the wiki-internal callback to that approved client (one IdP, one client) unless Tony insists on a dedicated client. Google Console is human-only; not touched.
- **B4 — "Ada to inhouse" ambiguity.** CF Access allowlist contains only Tony's two emails; the wiki `Ada` account is a local bot, not a Google identity. Recommendation: keep Ada local sysop/inhouse via `addOnlyGroups`; if a Google-backed Ada identity is meant, its email must be supplied and added to both Access policies.
- **B5 — End-to-end OIDC login unverified.** Prior root cause was a missing `openid_connect` table (`update.php` not run after install); a later card says login was fixed by registering redirect URIs. Cannot confirm without a human browser session and the secret file. Admin should run the MW 1.46 update check and a real login before exposing the tab.
- **B6 — No live mutations by design.** No host, Cloudflare, Google, MediaWiki or HA-dashboard write was performed; the Cargo declare/store gate is exit 0 and must not be re-applied.
