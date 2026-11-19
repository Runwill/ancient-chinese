// Run with PLAYWRIGHT_MODULE pointing to Playwright if it is not installed locally.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const webRoot = path.resolve(__dirname, '../web');
let source = fs.readFileSync(path.join(webRoot, 'app.js'), 'utf8');
if (process.env.DRAG_TEST_BASELINE) {
  source = require('node:child_process').execFileSync('git',
    ['show', 'HEAD:汉转NOCM/web/app.js'], { cwd: webRoot, encoding: 'utf8' });
}
// Test-only observability; no hooks are added to the shipped application.
source = source.replace(/\}\)\(\);\s*$/, `
  window.__dragTest = {
    snapshot: () => clone(editor),
    idle: () => actionQueue,
    calls: [],
    delay: 0,
    instrument() {
      const original = api;
      const test = this;
      api = new Proxy(original, { get(target, name) {
        if (!['set_caret', 'set_selection'].includes(name)) return target[name];
        return async (...args) => {
          test.calls.push([name, ...args]);
          const result = await target[name](...args);
          if (name === 'set_caret' && test.delay) {
            await new Promise(resolve => setTimeout(resolve, test.delay));
          }
          return result;
        };
      }});
    },
  };
})();`);

const server = http.createServer((request, response) => {
  const filename = path.resolve(webRoot, '.' + new URL(request.url, 'http://localhost').pathname);
  if (!filename.startsWith(webRoot + path.sep)) {
    response.writeHead(403).end();
    return;
  }
  try {
    const extension = path.extname(filename);
    response.setHeader('Content-Type', {
      '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
      '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml',
    }[extension] || 'application/octet-stream');
    response.end(filename === path.join(webRoot, 'app.js') ? source : fs.readFileSync(filename));
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
    await page.evaluate(() => window.__dragTest.instrument());

    async function point(line, column, right = false) {
      const box = await page.locator(`.cell[data-line="${line}"][data-column="${column}"]`).boundingBox();
      assert.ok(box, `Visible cell ${line}:${column}`);
      return { x: box.x + box.width * (right ? 0.8 : 0.2), y: box.y + box.height / 2 };
    }
    async function expectSelection(expected, label) {
      await page.evaluate(() => window.__dragTest.idle());
      assert.deepEqual(await page.evaluate(() => window.__dragTest.snapshot().selection), expected, label);
      const finalCall = await page.evaluate(() => window.__dragTest.calls.filter(call => call[0] === 'set_selection').at(-1));
      assert.deepEqual(finalCall.slice(1, 5), expected.flat(), `${label}: backend endpoint`);
    }
    async function drag(start, end, expected, label) {
      await page.mouse.move(start.x, start.y);
      await page.mouse.down();
      await page.mouse.move(end.x, end.y, { steps: 8 });
      await page.waitForTimeout(40);
      assert.deepEqual(await page.evaluate(() => window.__dragTest.snapshot().selection), expected, `${label}: preview`);
      await page.mouse.up();
      await expectSelection(expected, label);
    }

    await drag(await point(1, 0), await point(1, 2, true), [[1, 0], [1, 3]], 'forward three characters');
    await drag(await point(1, 2, true), await point(1, 0), [[1, 3], [1, 0]], 'reverse three characters');
    await drag(await point(1, 1), await point(2, 1, true), [[1, 1], [2, 2]], 'cross-line selection');

    // Multiple moves and release before a frame, with a distinct release endpoint.
    const start = await point(1, 0);
    const middle = await point(1, 1, true);
    const end = await point(1, 2, true);
    await page.evaluate(({ start, middle, end }) => {
      const fire = (type, position, buttons) => document.elementFromPoint(position.x, position.y)
        .dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: position.x, clientY: position.y, button: 0, buttons }));
      fire('mousedown', start, 1);
      fire('mousemove', middle, 1);
      fire('mousemove', middle, 1);
      fire('mouseup', end, 0);
    }, { start, middle, end });
    await expectSelection([[1, 0], [1, 3]], 'release before animation frame');

    // The initial click response arrives after a newer preview is already visible.
    await page.evaluate(() => { window.__dragTest.delay = 150; });
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(end.x, end.y, { steps: 4 });
    await page.waitForTimeout(220);
    assert.deepEqual(await page.evaluate(() => window.__dragTest.snapshot().selection), [[1, 0], [1, 3]], 'late caret response must not overwrite preview');
    await page.mouse.up();
    await expectSelection([[1, 0], [1, 3]], 'delayed caret commit');
    await page.evaluate(() => { window.__dragTest.delay = 0; });

    // Shift-drag preserves the original anchor rather than the new mouse-down point.
    await page.keyboard.down('Shift');
    await drag(await point(1, 1), await point(1, 2), [[1, 0], [1, 2]], 'Shift-drag original anchor');
    await page.keyboard.up('Shift');

    // Leaving the editor retains the last valid endpoint, not column zero.
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(end.x, end.y, { steps: 4 });
    await page.mouse.move(5, 5);
    await page.mouse.up();
    await expectSelection([[1, 0], [1, 3]], 'release outside editor');
    await page.waitForTimeout(80);
    await expectSelection([[1, 0], [1, 3]], 'selection remains stable');
    assert.deepEqual(errors, []);
    console.log('PASS: forward, reverse, cross-line, same-frame release, delayed response, Shift-drag, outside release, stability');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
