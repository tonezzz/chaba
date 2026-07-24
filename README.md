# Chaba.h3

Static website files for Plesk shared hosting. Only the `public/` directory is served.

## Local preview

```bash
python3 -m http.server 8123 -d public
```

Open `http://localhost:8123`.

## Build CSS

```bash
npm install
npm run build:css
```

## Plesk settings

- Document root: `/www/chaba.h3.gizmo-thailand.com/chaba/public`
