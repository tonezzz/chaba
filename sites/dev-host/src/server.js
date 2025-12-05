import fs from 'fs';
import path from 'path';
import express from 'express';
import morgan from 'morgan';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

const workspaceRoot = path.resolve(__dirname, '..', '..');

const siteConfigs = [
  {
    slug: 'a1-idc1',
    label: 'A1 IDC1 preview',
    root: path.join(workspaceRoot, 'a1-idc1')
  },
  {
    slug: 'idc1',
    label: 'IDC1 preview',
    root: path.join(workspaceRoot, 'idc1')
  }
];

const resolveStaticDirs = (siteRoot) => {
  const candidates = [
    path.join(siteRoot, 'public'),
    path.join(siteRoot, 'public-static'),
    path.join(siteRoot, 'test'),
    siteRoot
  ];
  return candidates.filter((dir, index, arr) => fs.existsSync(dir) && arr.indexOf(dir) === index);
};

const buildSiteRouter = (site) => {
  const router = express.Router();
  const staticDirs = resolveStaticDirs(site.root);

  if (!staticDirs.length) {
    router.use((_req, res) => {
      res.status(404).json({ error: 'site_root_missing', site: site.slug });
    });
    return router;
  }

  staticDirs.forEach((dir) => {
    router.use(express.static(dir, { fallthrough: true }));
  });

  router.get('/api/health', (_req, res) => {
    res.json({ site: site.slug, status: 'ok', timestamp: new Date().toISOString() });
  });

  router.use((req, res, next) => {
    const fallback = staticDirs
      .map((dir) => path.join(dir, 'index.html'))
      .find((candidate) => fs.existsSync(candidate));

    if (fallback) {
      return res.sendFile(fallback);
    }

    return next();
  });

  router.use((req, res) => {
    res.status(404).json({ error: 'not_found', site: site.slug, path: req.path });
  });

  return router;
};

app.use(morgan('dev'));

siteConfigs.forEach((site) => {
  app.use(`/${site.slug}`, buildSiteRouter(site));
});

app.get('/api/health', (_req, res) => {
  res.json({
    status: 'ok',
    sites: siteConfigs.map((site) => ({ slug: site.slug, rootExists: fs.existsSync(site.root) })),
    timestamp: new Date().toISOString()
  });
});

app.get('/', (_req, res) => {
  const links = siteConfigs
    .map(
      (site) => `
      <li>
        <a href="/${site.slug}/" target="_blank" rel="noreferrer">${site.label}</a>
        <code>/${site.slug}/*</code>
      </li>`
    )
    .join('');

  res.send(`<!doctype html>
  <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>dev-host gateway</title>
      <style>
        :root { color-scheme: dark; font-family: 'Inter', system-ui, sans-serif; }
        body { margin: 0; padding: 3rem; background: #050812; color: #f5f7ff; }
        main { max-width: 720px; margin: 0 auto; }
        ul { list-style: none; padding: 0; display: grid; gap: 1rem; }
        li { padding: 1rem 1.25rem; background: rgba(255,255,255,0.04); border-radius: 18px; border: 1px solid rgba(255,255,255,0.1); }
        a { color: #8cf0d2; font-weight: 600; text-decoration: none; }
        code { display: block; color: #9ab0d6; margin-top: 0.35rem; font-size: 0.95rem; }
      </style>
    </head>
    <body>
      <main>
        <h1>dev-host gateway</h1>
        <p>Pick a site namespace to preview:</p>
        <ul>${links}</ul>
      </main>
    </body>
  </html>`);
});

app.listen(PORT, () => {
  console.log(`[dev-host] listening on port ${PORT}`);
});
