---
description: Add a static page to chaba.h3.gizmo-thailand.com
---

# Add a page to chaba.h3

1. Work in the `chaba.h3` branch worktree: `/home/tony/CascadeProjects/chaba-h3`.
2. Add the HTML and any YAML/JSON data files under `public/<path>/index.html` or `public/<path>.html`.
3. If the page belongs under `/apps/`, register it in `public/apps/apps.yml` so the shared nav and app grid pick it up.
4. For directory URLs (`/foo/`), either:
   - link users to `/foo/index.html` explicitly, or
   - add a special case in `proxy-server.mjs` and restart the Node app.
5. Inside the page, use **absolute** fetch paths such as `/data.json`.
6. If the page adds or changes Tailwind classes, run `npm run build:css` in `/home/tony/CascadeProjects/chaba-h3` and include `public/assets/tailwind.css` in the commit.
7. Test the exact URL users will type, including `.../index.html` if needed.
8. Stage, commit, and push from `chaba-h3`:
   ```bash
   git add public/<path> public/assets/tailwind.css proxy-server.mjs  # only mjs if routing changed
   git commit -m "h3: add /foo page"
   git push origin chaba.h3
   ```
9. On the host: pull the `chaba.h3` branch. Restart the app only if `proxy-server.mjs` changed.

See also `docs/kb-h3-pages.md`.
