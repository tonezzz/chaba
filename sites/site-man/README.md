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
