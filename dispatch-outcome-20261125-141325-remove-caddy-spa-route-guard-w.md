# Dispatch outcome — ocb-spa-route-guard-upstream-fix (2026-11-25)

## Verdict: card is moot — nothing to remove; verified, no live changes made

The `@ocbUnknownRoute` SPA route guard no longer exists on idc02 caddy-edge.
It was removed on **2026-11-24** as part of the opencode public-edge
retirement — the entire site blocks for `ada-code.surf-thailand.com`,
`opencode-ada.surf-thailand.com`, and `opencode-jack` were deleted from
`~/.config/caddy/Caddyfile` along with the `ada-code-enroll` (:8378) /
`jack-enroll` (:8377) CF-Access JWT gateway quadlets. The guard text
survives only in backups (`Caddyfile.bak-retired-opencode-20261124` still
contains it verbatim; `Caddyfile.bak-ocb-route-guard-20261121` is the
pre-guard baseline).

## Upstream state (checked 2026-11-25)

- `anomalyco/opencode#61001` — still **open**.
- PR `#61017` — still **open**, and per opencodejr bot review incomplete
  (fixes the throw but leaves a blank page; needs a catch-all route;
  `requireServerKey` still throws — see #60752).
- `dev` branch and latest releases **v2.4.0 / v2.4.1** still contain
  `throw new Error("Unrecognised route!")` in
  `packages/app/src/shell/state/layout.tsx` — the bug is unfixed in every
  shipped release.

This is moot for the public edge because nothing public serves the
opencode SPA anymore: live opencode on idc02 is now a **host binary
v2.4.1** (`/usr/local/bin/opencode`, `@opencode/cli` npm global) served
by `opencode-serve.service`, listening on tailnet `100.123.163.11:4096`
only — no Caddy vhost in front. The `localhost/ada-opencode` container +
`ada-code`/`ada-enroll` quadlets were retired (backup
`~/backups/retired-opencode-20261124` on idc02; see card
`ada-opencode-v2-upgrade` comms 2026-11-24).

## Consumer drift found (carded, not fixed)

- ada-ha chaba-admin dashboard "Ada Code" view still iframes the dead
  hostname `https://ada-code.surf-thailand.com/` → new card
  `ada-ha-chaba-admin-ada-code-view-iframes-d1c492` (HOM-1394, backlog)
  with fix options.
- `ssot.audit.hosts.yml` still lists retired `ada-code-enroll.service` —
  already covered by in-flight card `idc02-audit-census-reconcile`.
- consumer-canary only watches `tony-dell.taila0626a.ts.net`; noted in
  the new card that retired *public* hostnames aren't covered.

## Files changed (worktree only)

- `docs/ssot/jobs/infrastructure/2026-11-25-ocb-spa-route-guard-moot.yml`
  — verification trail: findings, verify commands, and re-check procedure
  if the opencode web UI is ever re-exposed publicly.
- `dispatch-outcome-20261125-141325-remove-caddy-spa-route-guard-w.md` —
  this file.

No commits to master, no push, no live mutation. Board comms posted on
the card.

## How to verify

- `ssh idc02 'grep -n ocbUnknownRoute ~/.config/caddy/Caddyfile'` → no match.
- `ssh idc02 'systemctl --user status opencode-serve.service; opencode --version'`
  → active, v2.4.1.
- `curl -s https://api.github.com/repos/anomalyco/opencode/issues/61001 | jq .state` → open.
- Card comms on `ocb-spa-route-guard-upstream-fix` have the same findings.

## Recommendation for the card

Close as **obsolete/superseded** — the guard's host blocks were retired
before the upstream fix shipped, and upstream still hasn't shipped it.
If the opencode web UI is ever re-exposed publicly, re-apply the guard
block (verbatim copy in the idc02 Caddyfile backup) or wait for an actual
upstream fix.

lessons:
- Upstream-watch cards go stale silently: this one's entire premise (public
  opencode SPA behind CF Access) was retired by a different card the day
  before dispatch — always re-verify the guarded surface still exists
  before planning removal work.
- "Removed when X ships" guards can be mooted by surface retirement, not
  just by the trigger condition — check both.
- Live Caddyfiles on idc02 are not in the repo; grep ~/.config/caddy/
  over ssh, and remember backups keep retired blocks (good for restore,
  noisy for "does the guard exist" greps — exclude *.bak).
- The opencode SPA bug (#61001) is still unfixed upstream through v2.4.1;
  if opencode-serve :4096 ever gets a public vhost, the guard (or an
  upstream fix) must go back in first.
