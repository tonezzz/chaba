## chaba.h3 Web Pages

When adding or editing pages for `chaba.h3.gizmo-thailand.com`, follow `.windsurf/workflows/add-h3-page.md` and `docs/kb/h3-pages.md`. Key reminders:
- Work in `/home/tony/CascadeProjects/chaba-h3` and push to the `chaba.h3` branch.
- Place files under `chaba-h3/public/`; the `web/public/` path from the main branch is not served.
- Link to explicit `/foo/index.html` URLs unless `proxy-server.mjs` has a directory special case.
- Use absolute fetch paths such as `/data.json` inside pages.
