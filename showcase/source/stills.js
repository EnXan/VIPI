const { chromium } = require('playwright');
(async () => {
  const times = process.argv.slice(2).map(Number);
  const b = await chromium.launch({ args: ['--allow-file-access-from-files'] });
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto('file://' + __dirname + '/index.html');
  await p.evaluate(() => window.READY);
  require('fs').mkdirSync('stills', { recursive: true });
  for (const t of times) {
    await p.evaluate(t => render(t), t);
    await p.locator('canvas').screenshot({ path: `stills/t${String(t).padStart(5, '0')}.png` });
  }
  console.log('errors:', errs);
  await b.close();
})();
