// Renders every Mermaid diagram in the built Atlas in headless Chromium and reports failures.
// Usage: node atlas/validation/render_check.js [path/to/atlas.html]
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const file = path.resolve(process.argv[2] || path.join(__dirname, '..', '..', 'uber-system-design-atlas.html'));
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('pageerror', e => consoleErrors.push(String(e)));
  await page.goto('file://' + file);
  const errs = await page.evaluate(() => window.__renderAll());
  const counts = await page.evaluate(() => ({
    total: document.querySelectorAll('pre.mermaid').length,
    ok: [...document.querySelectorAll('pre.mermaid')].filter(p => p.querySelector('svg')).length,
    articles: document.querySelectorAll('article').length,
    brokenLinks: [...document.querySelectorAll('a[href^="#/"]')].map(a => a.getAttribute('href').slice(1)).filter(h => !document.querySelector('article[data-route="' + h + '"]')),
  }));
  console.log(JSON.stringify({ ...counts, brokenLinks: [...new Set(counts.brokenLinks)], renderErrors: errs.length, pageErrors: consoleErrors }, null, 1));
  errs.slice(0, 40).forEach(e => console.log('ERR', e.route, e.err.slice(0, 300)));
  await browser.close();
  process.exit(errs.length || counts.brokenLinks.length ? 1 : 0);
})();
