# node-1 Sample Site

Minimal Express application ready to deploy on node-1.h3.surf-thailand.com via Plesk.

## Structure

```
site-sample/
├── app.js               # Entry file referenced by hosting panel
├── package.json
├── public/              # Static assets served as document root
│   ├── index.html
│   ├── 404.html
│   └── styles.css
└── src/
    └── server.js        # Express app with /api/* endpoints
```

## Local development

```bash
npm install
npm run dev
```
Visit http://localhost:3000 to view the site and hit `/api/health`.

## Production start

```
npm install --production
npm run start
```

Set `app.js` as the startup file in Plesk so it boots the Express server. Adjust `PORT` via environment variables if needed.

## Tony sandbox deploy API

When `TONY_DEPLOY_SECRET` is configured (defaults to `NODE1_WEBHOOK_SECRET`), you can push static bundles directly into `sites/tony/sites/<name>/` without SSH:

```
POST /api/tony/deploy
Headers:
  Content-Type: application/json
  x-tony-secret: <TONY_DEPLOY_SECRET>

Body:
{
  "site": "chat1",
  "clear": true,
  "files": [
    {
      "path": "index.html",
      "contents": "<!doctype html>...",
      "encoding": "utf8"
    },
    {
      "path": "assets/main.js",
      "contents": "...base64 data...",
      "encoding": "base64"
    }
  ]
}
```

The server writes each file relative to `sites/tony/sites/<site>/`, optionally clears the folder, then restarts the Node domain via Plesk so the updated sandbox is immediately live at `https://node-1.h3.surf-thailand.com/tony/sites/<site>/`.
