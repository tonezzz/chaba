# Overview App

YAML-driven overview pages for the `chaba.h3` lab.

## Pages

| Path | Purpose |
|------|---------|
| `/apps/overview/` | Landing page with top-level panels |
| `/apps/overview/dirs/` | Worktrees and directory layout |
| `/apps/overview/system/` | Host, ports, LAN devices, Docker networks |

## Files

- `overview.js` — shared renderer, registers layouts, loads `data.yml` per page
- `overview.css` — bright-theme overrides and card styles
- `data.yml` — page title, subtitle, and `sections` array
- `index.html` — shell that loads `nav.js`, `overview.js`, and `shared/yml-edit.js`
- `dirs/` and `system/` — sub-pages using the same renderer

## Layouts

`data.yml` sections use a `layout` key:

- `panels` — 3-column clickable cards with optional icon
- `link-grid` — 2-column link/description cards
- `stats` — 2-column stat/value cards
- `list` — `<ul>` of labeled items (supports `href` and `code`)
- `table` — table with `headers` and `rows`
- `tree` — nested label/children tree
- `dynamic-panels` — fetches a manifest and renders grouped panels from synced docs YAML files

## YAML Sources

Each `index.html` declares editable YAML files via:

```html
<link rel="yaml-source" href="./data.yml">
<link rel="yaml-source" href="/apps/apps.yml">
```

The shared `yml-edit.js` tool discovers these links and lets you copy, download, or server-save the YAML.

## YAML Editor

- Loaded from `/apps/shared/yml-edit.js`
- Floating **Edit YAML** menu in the top-right corner
- Opens a draggable/resizable WinBox window
- Lists all `yaml-source` files in a dropdown
- Save, Copy, Download buttons
- Save posts to `POST /__yml-edit` (server endpoint must be configured)

## Dynamic Docs Panels

The `dynamic-panels` layout shows YAML files synced from the main repo's `docs/overview/` directory.

### Naming convention

Files in `chaba/docs/overview/` should be named:

```
group1.subgroup1.name.yaml
```

The sync script (`npm run sync:docs`) parses the filename and produces `public/data/docs-overview.json` with `group`, `subgroup`, `name`, `title`, and `href` for each file. It also copies the files into `public/docs/overview/`. If a YAML file contains a top-level `title:` line, that title is used in place of the generated one.

### Add the Docs section to `data.yml`

```yaml
  - title: Docs
    icon: 📚
    layout: dynamic-panels
    dataUrl: /data/docs-overview.json
```

## Build

```bash
npm run build:css      # rebuild tailwind.css
npm run sync:docs      # sync docs/overview YAML files from chaba main repo
```

`tailwind.config.cjs` scans `public/apps/overview/**/*.js` and `public/apps/shared/**/*.js` for Tailwind classes.
