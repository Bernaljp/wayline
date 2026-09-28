// The viewer in Chromium (Playwright's cached build, driven by playwright-core): focus, Escape, the
// backdrop, the keys, zoom against transform: scale, scrolling a long document, fonts, requests, the
// console, and where the render time goes. Every request off 127.0.0.1 is logged and aborted.
// Desktop 1280x800, then a phone (390x844, touch, device scale 2). Screenshots go to OUT.
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');
const { BASE, OUT } = require('./common.js');

async function open(browser, options) {
  const context = await browser.newContext(options);
  const local = [];
  const blocked = [];
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1') { local.push(url.pathname.split('/').pop()); return route.continue(); }
    blocked.push(url.href);
    return route.abort();
  });
  const page = await context.newPage();
  const consoleMessages = [];
  page.on('console', (m) => consoleMessages.push(`${m.type()}: ${m.text().slice(0, 120)}`));
  page.on('pageerror', (e) => consoleMessages.push(`pageerror: ${e.message.slice(0, 120)}`));
  await page.goto(new URL('index.html', BASE).href);
  await page.evaluate(() => { try { localStorage.clear(); } catch (error) { /* none */ } });
  return { context, page, local, blocked, consoleMessages };
}
async function view(page, file, how = 'click') {
  await (how === 'tap' ? page.tap(`[data-view="${file}"]`) : page.click(`[data-view="${file}"]`));
  await page.waitForFunction(() => document.querySelectorAll('#viewer-doc .katex').length > 0);
  await page.evaluate(() => document.fonts.ready);
}
const state = (page) => page.evaluate(() => {
  const a = document.activeElement;
  return {
    open: document.getElementById('viewer').open,
    focus: a ? `${a.localName}${a.id ? '#' + a.id : ''}${a.getAttribute('aria-label') ? '[' + a.getAttribute('aria-label') + ']' : ''}${a.dataset && a.dataset.view ? '[view ' + a.dataset.view + ']' : ''}` : null,
    zoom: document.querySelector('#viewer .level').textContent,
    documentScrollTop: Math.round(document.getElementById('viewer-body').scrollTop),
    pageScrollY: Math.round(window.scrollY),
  };
});
const metrics = (page) => page.evaluate(() => {
  const body = document.getElementById('viewer-body');
  const p = document.querySelector('#viewer-doc p:nth-of-type(2)');
  const m = p.querySelector('.katex');
  const r = p.getBoundingClientRect();
  const q = m.getBoundingClientRect();
  return { paragraphOnScreen: [Math.round(r.width), Math.round(r.height)], paragraphLayoutWidth: p.offsetWidth, firstInlineFormula: [Math.round(q.width), Math.round(q.height)], documentScroll: [body.scrollWidth, body.scrollHeight], documentClient: [body.clientWidth, body.clientHeight] };
});
const zoomAndScale = async (page, stepIn) => {
  const at100 = await metrics(page);
  for (let i = 0; i < 3; i++) await stepIn();
  const at150 = await metrics(page);
  const shot150 = await page.evaluate(() => document.querySelector('#viewer .level').textContent);
  await page.evaluate(() => { const d = document.getElementById('viewer-doc'); d.style.setProperty('--zoom', '1'); d.style.transform = 'scale(1.5)'; d.style.transformOrigin = '0 0'; });
  const scale150 = await metrics(page);
  await page.evaluate(() => { const d = document.getElementById('viewer-doc'); d.style.transform = ''; d.style.setProperty('--zoom', '1.5'); });
  return { level: shot150, zoom100: at100, zoom150: at150, transformScale150: scale150 };
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const report = {};
  const browser = await chromium.launch();
  report.browser = browser.version();

  // --- desktop -------------------------------------------------------------------------------
  {
    const { context, page, local, blocked, consoleMessages } = await open(browser, { viewport: { width: 1280, height: 800 } });
    report.features = await page.evaluate(() => ({ closedBy: 'closedBy' in HTMLDialogElement.prototype, zoom: CSS.supports('zoom', '1.5'), has: CSS.supports('selector(:has(a))'), dvh: CSS.supports('height', '100dvh') }));
    await view(page, 'sample.md');
    await page.waitForTimeout(500); // an <img onerror> that survived sanitizing would have fired by now
    report.opened = await state(page);
    report.sample = await page.evaluate(() => ({
      formulas: document.querySelectorAll('#viewer-doc .katex').length,
      displays: document.querySelectorAll('#viewer-doc .katex-display').length,
      katexErrors: document.querySelectorAll('#viewer-doc .katex-error').length,
      annotations: document.querySelectorAll('#viewer-doc .katex annotation').length,
      styleElements: document.querySelectorAll('#viewer-doc style').length,
      scriptRan: window.__pwned === undefined ? 'nothing ran' : window.__pwned,
      fontsLoaded: Array.from(document.fonts).filter((f) => f.status === 'loaded').map((f) => `${f.family} ${f.style} ${f.weight}`).sort(),
    }));
    await page.screenshot({ path: path.join(OUT, 'chromium-desktop-100.png') });
    report.hitAt5x5 = await page.evaluate(() => document.elementFromPoint(5, 5).localName);
    await page.mouse.click(5, 5);
    report.afterBackdropClick = await state(page);

    await page.focus('[data-view="sample.md"]');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelectorAll('#viewer-doc .katex').length > 0);
    report.openedFromKeyboard = await state(page);
    await page.keyboard.press('PageDown');
    await page.waitForTimeout(300);
    report.afterPageDown = await state(page);
    await page.keyboard.press('0');
    await page.evaluate(() => { document.getElementById('viewer-body').scrollTop = 0; });
    report.desktopZoom = await zoomAndScale(page, () => page.keyboard.press('+'));
    await page.screenshot({ path: path.join(OUT, 'chromium-desktop-150.png') });
    await page.keyboard.press('0');
    report.afterZero = await state(page);
    await page.keyboard.press('-');
    report.afterMinus = await state(page);
    await page.keyboard.press('0');
    await page.focus('#viewer-body');
    report.tabStops = [];
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      report.tabStops.push(await page.evaluate(() => {
        const a = document.activeElement;
        const kind = typeof a.className === 'string' && a.className ? '.' + a.className.split(' ')[0] : '';
        return `${a.localName}${a.id ? '#' + a.id : kind}${a.getAttribute('aria-label') ? '[' + a.getAttribute('aria-label') + ']' : ''}${a.scrollWidth > a.clientWidth ? ' (scrolls sideways)' : ''}`;
      }));
    }
    await page.keyboard.press('Escape');
    report.afterEscape = await state(page);

    await view(page, 'long.md');
    report.long = await page.evaluate(() => ({ renderMs: Math.round(window.__lastRenderMs), formulas: document.querySelectorAll('#viewer-doc .katex').length, displays: document.querySelectorAll('#viewer-doc .katex-display').length, katexErrors: document.querySelectorAll('#viewer-doc .katex-error').length }));
    const box = await page.locator('#viewer-body').boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    for (let i = 0; i < 5; i++) { await page.mouse.wheel(0, 600); await page.waitForTimeout(250); }
    await page.waitForTimeout(800);
    report.wheelOverDocument = await state(page);
    await page.evaluate(() => { const b = document.getElementById('viewer-body'); b.scrollTop = b.scrollHeight; });
    await page.mouse.wheel(0, 3000);
    await page.waitForTimeout(500);
    report.wheelPastTheEnd = await state(page);
    await page.mouse.move(5, 5);
    await page.mouse.wheel(0, 3000);
    await page.waitForTimeout(500);
    report.wheelOverBackdrop = await state(page);
    await page.addStyleTag({ content: 'html:has(dialog#viewer[open]) { overflow: visible !important; }' });
    await page.mouse.move(5, 5);
    await page.mouse.wheel(0, 3000);
    await page.waitForTimeout(500);
    report.wheelOverBackdropWithoutTheRule = await state(page);
    await page.keyboard.press('Escape');

    report.renderStages = await page.evaluate(async () => {
      const out = {};
      for (const file of ['sample.md', 'long.md']) {
        const text = await (await fetch(file, { cache: 'no-store' })).text();
        const runs = { markedWithKatex: [], sanitize: [], parseIntoDom: [], markedAlone: [] };
        for (let i = 0; i < 5; i++) {
          let t = performance.now();
          const html = markdownWithMath().parse(text);
          runs.markedWithKatex.push(performance.now() - t);
          t = performance.now();
          const clean = DOMPurify.sanitize(html, MATH_PURIFY);
          runs.sanitize.push(performance.now() - t);
          t = performance.now();
          document.createElement('div').innerHTML = clean;
          runs.parseIntoDom.push(performance.now() - t);
          t = performance.now();
          marked.parse(text);
          runs.markedAlone.push(performance.now() - t);
        }
        const median = (xs) => Math.round(xs.sort((a, b) => a - b)[2] * 10) / 10;
        out[file] = { bytes: text.length, ...Object.fromEntries(Object.entries(runs).map(([k, v]) => [`${k}Ms`, median(v)])) };
      }
      return out;
    });

    await page.emulateMedia({ colorScheme: 'dark' });
    await view(page, 'sample.md');
    await page.screenshot({ path: path.join(OUT, 'chromium-desktop-dark.png') });
    await page.keyboard.press('Escape');
    await view(page, 'refs.md');
    await page.screenshot({ path: path.join(OUT, 'chromium-refs-dark.png') });
    await page.keyboard.press('Escape');

    report.desktopRequests = Array.from(new Set(local));
    report.desktopBlocked = blocked;
    report.desktopConsole = consoleMessages;
    await context.close();
  }

  // --- phone ---------------------------------------------------------------------------------
  {
    const { context, page, local, blocked, consoleMessages } = await open(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await view(page, 'sample.md', 'tap');
    report.phoneViewer = await page.evaluate(() => {
      const r = document.getElementById('viewer').getBoundingClientRect();
      return { rect: [r.x, r.y, r.width, r.height].map(Math.round), window: [innerWidth, innerHeight], buttons: Array.from(document.querySelectorAll('#viewer .viewer-bar button')).map((b) => `${Math.round(b.getBoundingClientRect().width)}x${Math.round(b.getBoundingClientRect().height)}`) };
    });
    await page.screenshot({ path: path.join(OUT, 'chromium-phone-100.png') });
    report.phoneZoom = await zoomAndScale(page, () => page.tap('[data-zoom="in"]'));
    // Every element whose right edge passes the screen's, outside the displays (which scroll inside
    // themselves), reported at the outermost such element.
    report.phoneWiderThanTheScreenAt150 = await page.evaluate(() => {
      const limit = document.getElementById('viewer-body').getBoundingClientRect().right;
      const wide = Array.from(document.querySelectorAll('#viewer-doc *')).filter((el) => !el.closest('.katex-display') && el.getBoundingClientRect().right > limit + 1);
      return wide.filter((el) => !wide.some((other) => other !== el && other.contains(el))).map((el) => `<${el.localName}> in <${el.parentElement.localName}>, right edge ${Math.round(el.getBoundingClientRect().right)} of ${Math.round(limit)}: ${el.textContent.trim().slice(0, 40)}`);
    });
    await page.screenshot({ path: path.join(OUT, 'chromium-phone-150.png') });
    await page.evaluate(() => { const d = document.getElementById('viewer-doc'); d.style.setProperty('--zoom', '1'); d.style.transform = 'scale(1.5)'; d.style.transformOrigin = '0 0'; });
    await page.screenshot({ path: path.join(OUT, 'chromium-phone-transform-150.png') });
    report.phoneBlocked = blocked;
    report.phoneConsole = consoleMessages;
    report.phoneRequests = Array.from(new Set(local)).length;
    await context.close();
  }

  await browser.close();
  console.log(JSON.stringify(report, null, 1));
})().catch((error) => { console.error(error); process.exit(1); });
