# chaba.h3 Static Pages

`chaba.h3.gizmo-thailand.com` is a Node.js proxy server running under Plesk. It is **not** the same as the main `chaba` Caddy / `bserver` stack. These notes capture the deployment pattern we learned while building `/apps/cams` so we do not repeat the 404 / path mistakes.

## Static root

- All deployable static files live in `chaba-h3/public/`.
- `stacks/web/public/` and `stacks/web/bserver-www/` from the `master` / `chaba` branch are **not** served by `chaba.h3`.
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

## Main chaba Caddy integration

Selected `chaba.h3` apps can also be served directly by the main `chaba` Caddy stack (`web` container on `192.168.1.48:8080`) without using the Plesk Node proxy.

- Mount the app directory into the `web` container in `chaba/web/docker-compose.yml`:
  - `/home/tony/CascadeProjects/chaba-h3/public/apps/<app>:/srv/public/tony-omen/apps/<app>`
  - Attach the `chaba-h3_default` network if the page needs to reach `chaba-h3` backend services.
- With `root * /srv/public` and `file_server`, Caddy automatically serves `index.html` for directory URLs.
- Example: `imagen` is available at `http://192.168.1.48:8080/tony-omen/apps/imagen/`.
- Inside these pages, continue using absolute fetch paths such as `/data.json`; they resolve against `/srv/public`.

## Local Development for chaba.h3 Pages

You can preview `chaba-h3/public` apps on the main `chaba` Caddy stack before pushing to the `chaba.h3` branch.

### Subpath preview (8080)

- `stacks/web/docker-compose.yml`: bind mount `chaba-h3/public` to `/srv/public/chaba-h3`
- `stacks/web/Caddyfile`: add `handle_path /chaba-h3/*` block
- Access: `http://192.168.1.48:8080/chaba-h3/apps/<app>/`
- Caveat: pages that use absolute root fetches (e.g. `/cameras.json`, `/api/*`) need those paths mapped or should use app-relative fetches.

### Full parity preview (8081)

- `stacks/web/docker-compose.yml`: expose port `8081`
- `stacks/web/Caddyfile`: add `:8081 { root * /srv/public/chaba-h3 file_server }` site
- Access: `http://192.168.1.48:8081/apps/<app>/`
- This mirrors Plesk root behavior; absolute fetches work as long as the corresponding backend routes are available.

## YAML data files

`chaba.h3` pages are data-driven where possible. Shared content lives in YAML next to the HTML and is parsed with `js-yaml` at runtime.

### `public/apps/apps.yml`

Defines the page title, top nav, and app cards for `public/apps/index.html`. Other app pages (e.g. `/apps/track/`) load `../apps.yml` to render the same nav.

```yaml
title: Apps
nav:
  - label: Apps
    href: /apps/
  - label: Track
    href: /apps/track/
apps:
  - id: track
    title: Track
    description: Simulate moving objects on a live Leaflet map.
    href: /apps/track/
```

- Add `placeholder: true` to grey out a nav item or app card and keep the link disabled.

### `public/apps/track/objects.yml`

Holds static objects (bouys, markers, etc.) for `/apps/track/`.

```yaml
bouis:
  - id: boui-1
    name: BOUI-1
    lat: 13.243858067632821
    lon: 100.92870143484448
    color: '#fbbf24'
```

- The track page fetches `objects.yml`, draws a `L.circleMarker` for each entry, and lists them in the control panel with visibility toggles.

## Track page (`/apps/track/`)

- The map is centered via a `CENTER` constant and uses dark Carto tiles.
- Simulated vehicles are kept in a `vehicleLayer`; the control panel toggles the whole group.
- BOUI markers are added to a `bouiLayer`; each one can be toggled independently.
- The top nav and object list are rendered from YAML after the page loads.
