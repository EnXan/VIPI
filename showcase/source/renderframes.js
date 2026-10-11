const { chromium } = require('playwright');
const fs = require('fs');
const FPS = 30, DUR = 60, N = FPS * DUR;
const workers = +process.argv[2] || 4;
const only = process.argv[3] ? process.argv[3].split('-').map(Number) : [0, N];
(async () => {
  fs.mkdirSync('frames', { recursive: true });
  const b = await chromium.launch({ args: ['--allow-file-access-from-files'] });
  const t0 = Date.now();
  await Promise.all([...Array(workers).keys()].map(async w => {
    const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
    p.on('pageerror', e => console.log('ERR', e.message));
    await p.goto('file://' + __dirname + '/index.html');
    await p.evaluate(() => window.READY);
    for (let f = only[0] + w; f < only[1]; f += workers) {
      const data = await p.evaluate(t => { render(t); return document.getElementById('c').toDataURL('image/png'); }, f / FPS);
      fs.writeFileSync(`frames/f${String(f).padStart(5, '0')}.png`, Buffer.from(data.split(',')[1], 'base64'));
      if (f % 150 === 0) console.log('frame', f, ((Date.now() - t0) / 1000).toFixed(1) + 's');
    }
  }));
  console.log('done', ((Date.now() - t0) / 1000).toFixed(1) + 's');
  await b.close();
})();
