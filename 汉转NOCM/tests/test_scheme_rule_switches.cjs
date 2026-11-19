// Headless regression: relocated switches, history, persistence payload and old tab state.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../web');
let script = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
script = script.replace('save_scheme: async value => ({',
  'save_scheme: async value => (window.__savedScheme = clone(value), {');
script = script.replace(/\}\)\(\);\s*$/, `
  window.__schemeTest = {
    snapshot: () => clone(schemeDraft),
    open: () => openSchemeEditor('current_suno'),
    legacyView: () => { schemeEditorViews.current_suno = { tab: 'options', scroll: {} }; },
  };
})();`);
const server = http.createServer((request, response) => {
  const filename = path.resolve(root, '.' + new URL(request.url, 'http://localhost').pathname);
  if (!filename.startsWith(root + path.sep)) return response.writeHead(403).end();
  try {
    response.setHeader('Content-Type', {
      '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
      '.css': 'text/css; charset=utf-8',
    }[path.extname(filename)] || 'application/octet-stream');
    response.end(filename === path.join(root, 'app.js') ? script : fs.readFileSync(filename));
  } catch (_) { response.writeHead(404).end(); }
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true,
      ...(process.env.EDGE_PATH ? { executablePath: process.env.EDGE_PATH } : {}),
    });
    const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/index.html`);
    await page.locator('#app').waitFor({ state: 'visible' });
    await page.evaluate(() => { window.__schemeTest.legacyView(); });
    await page.evaluate(() => window.__schemeTest.open());
    const tabs = page.locator('#scheme-tabs');
    assert.equal(await tabs.locator('[data-tab="options"]').count(), 0);
    assert.equal(await tabs.locator('[data-tab="rules"]').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('[data-rule-option]').count(), 2);
    const pharyngeal = page.locator('[data-rule-section="pharyngeal_relax"]');
    const syllable = page.locator('[data-rule-section="syllable_relax"]');
    assert.equal(await pharyngeal.locator('.section-heading [data-rule-option="improve_pharyngeal"]').count(), 1);
    assert.equal(await syllable.locator('.section-heading [data-rule-option="improve_syllable"]').count(), 1);
    const original = await page.evaluate(() => window.__schemeTest.snapshot());
    const options = async () => (await page.evaluate(() => window.__schemeTest.snapshot())).options;
    const toggle = section => section.locator('.section-heading .switch').click();

    await toggle(pharyngeal);
    assert.equal((await options()).improve_pharyngeal, false);
    assert.equal((await options()).improve_syllable, false);
    await page.locator('#scheme-undo').click();
    assert.equal((await options()).improve_pharyngeal, true);
    await page.locator('#scheme-redo').click();
    assert.equal((await options()).improve_pharyngeal, false);
    await toggle(syllable);
    assert.equal((await options()).improve_syllable, true);
    await tabs.locator('[data-tab="phonology"]').click();
    assert.equal(await page.locator('[data-option="improve_pharyngeal"]').count(), 0);
    assert.equal(await page.locator('[data-option="voiced_stop_style"]').count(), 0);
    await tabs.locator('[data-tab="rules"]').click();
    assert.equal(await syllable.locator('input').isChecked(), true);
    await page.locator('#save-scheme-button').click();
    await page.waitForFunction(() => window.__savedScheme);
    const saved = await page.evaluate(() => window.__savedScheme);
    assert.equal(saved.options.improve_pharyngeal, false);
    assert.equal(saved.options.improve_syllable, true);
    assert.deepEqual(saved.maps, original.maps);
    assert.deepEqual(saved.rules, original.rules);
    if (process.env.QA_OUTPUT) {
      fs.mkdirSync(process.env.QA_OUTPUT, { recursive: true });
      await page.locator('#theme-button').evaluate(button => button.click());
      await page.locator('#scheme-dialog').screenshot({ path: path.join(process.env.QA_OUTPUT, 'rule-switches-dark.png') });
    }
    for (const width of [1280, 720, 540]) {
      await page.setViewportSize({ width, height: 850 });
      for (const section of [pharyngeal, syllable]) {
        assert.equal(await section.locator('.section-heading').evaluate(node => node.scrollWidth <= node.clientWidth), true);
      }
    }
    assert.deepEqual(errors, []);
    console.log('PASS: removed tab, legacy view, inline switches, independent toggles, undo/redo, save payload, narrow headers');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
