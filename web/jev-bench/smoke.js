const puppeteer = require('/home/tony/gods-eye-view/node_modules/puppeteer-core');
const model = process.argv[2] || 'minilm';
const wait = +(process.argv[3] || 600000);
(async () => {
  const b = await puppeteer.launch({
    executablePath: '/usr/bin/google-chrome',
    args: ['--no-sandbox', '--disable-gpu', '--user-data-dir=/tmp/jev-smoke/prof'],
    headless: 'new',
  });
  const p = await b.newPage();
  p.on('console', m => console.log('[pg]', m.text().slice(0, 300)));
  p.on('pageerror', e => console.log('[err]', String(e).slice(0, 300)));
  await p.goto(`http://127.0.0.1:8080/apps/jev-bench/?autorun=${model}`,
    { waitUntil: 'domcontentloaded', timeout: 60000 });
  const t0 = Date.now();
  while (Date.now() - t0 < wait) {
    const done = await p.evaluate(() => !document.getElementById('dl').disabled);
    if (done) break;
    await new Promise(r => setTimeout(r, 5000));
  }
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('=== LOG ===\n' + log);
  await b.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
