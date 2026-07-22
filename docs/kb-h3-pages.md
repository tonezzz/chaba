# chaba.h3 Static Pages

`chaba.h3.gizmo-thailand.com` is a Node.js proxy server running under Plesk. It is **not** the same as the main `chaba` Caddy / `bserver` stack. These notes capture the deployment pattern we learned while building `/apps/cams` so we do not repeat the 404 / path mistakes.

## Static root

- All deployable static files live in `chaba-h3/public/`.
- `web/public/` and `web/bserver-www/` from the `master` / `chaba` branch are **not** served by `chaba.h3`.
- Use the `chaba-h3` worktree at `/home/tony/CascadeProjects/chaba-h3` for edits.

## URL routing

- `proxy-server.mjs` maps the request `pathname` directly to `public/<pathname>`.
- It does **not** automatically serve `index.html` for directories.
- Only these paths are special-cased to map to `.../index.html`: `/`, `/hosts`, `/tony-omen`, and `/apps/cams`.
- For any new directory page, choose one of:
  1. Link to the explicit `index.html` URL, e.g. `/apps/cams/index.html`.
  2. Add a special case to `proxy-server.mjs` and restart the Node app.

## Inside the HTML

- Use absolute fetch paths such as `/cameras.json`. Relative paths (`../../cameras.json`) break when the user lands on an explicit `.../index.html` URL.
- Keep CDN URLs for assets (Tailwind, Leaflet, Hls.js, etc.) as absolute `https://` URLs.
- Do not assume `/frigate/*` is proxied. `proxy-server.mjs` does not proxy to Frigate unless a route is added.

## Publishing

1. `cd /home/tony/CascadeProjects/chaba-h3`
2. Stage files in `public/` (and `proxy-server.mjs` only if routing changed).
3. Commit and `git push origin chaba.h3`.
4. On the host, `git pull` the `chaba.h3` worktree.
5. Restart the Node app **only** if `proxy-server.mjs` changed. Plain HTML/JSON changes do not need a restart.

## Quick reference URL

- Page: `https://chaba.h3.gizmo-thailand.com/apps/cams/index.html`
- Data: `https://chaba.h3.gizmo-thailand.com/cameras.json`
