// MathJax 4.1.3 in Chromium through mathjax.html (needs `fetch-vendor.sh <repo> --mathjax`): what it
// fetches with its default configuration and with a local font path, with and without speech; how
// long typesetting takes; what \label and \eqref become; and what \href{javascript:...}, \style,
// \class, and \cssId from a document do. Every request off 127.0.0.1 is logged and aborted.
'use strict';
const { chromium } = require('playwright-core');
const { BASE } = require('./common.js');

async function probe(browser, query) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const blocked = [];
  const local = [];
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1') return route.continue();
    blocked.push(url.href.replace('https://cdn.jsdelivr.net/npm/', 'jsdelivr: '));
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  page.on('response', async (response) => {
    const url = new URL(response.url());
    if (url.hostname !== '127.0.0.1') return;
    let bytes = -1;
    try { bytes = (await response.body()).length; } catch (error) { /* a redirect or an aborted body */ }
    if (url.pathname.includes('/vendor-mj/')) local.push({ file: url.pathname.split('/vendor-mj/').pop(), bytes });
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message.slice(0, 100)));
  await page.goto(new URL(`mathjax.html?${query}`, BASE).href);
  let run = 'typeset';
  try { await page.evaluate(() => window.__run()); } catch (error) { run = `failed: ${String(error.message).split('\n')[0].slice(0, 100)}`; }
  await page.waitForTimeout(1500);
  const result = await page.evaluate(() => ({
    typesetMs: window.__typesetMs === undefined ? null : Math.round(window.__typesetMs),
    formulas: document.querySelectorAll('mjx-container').length,
    javascriptLinks: Array.from(document.querySelectorAll('a[href]')).filter((a) => /^\s*javascript:/i.test(a.getAttribute('href'))).length,
    styleWithUrl: Array.from(document.querySelectorAll('[style]')).filter((n) => /url\(/.test(n.getAttribute('style'))).length,
    idViewer: document.querySelectorAll('[id="viewer"]').length,
    classEvil: document.querySelectorAll('.evil').length,
    references: Array.from(document.querySelectorAll('#doc p')).map((p) => p.textContent.replace(/\s+/g, ' ')).filter((t) => /^(Before|After)/.test(t)),
  }));
  if (result.javascriptLinks) {
    await page.evaluate(() => Array.from(document.querySelectorAll('a[href]')).find((a) => /^\s*javascript:/i.test(a.getAttribute('href'))).click());
    await page.waitForTimeout(300);
    result.clickingTheLink = await page.evaluate(() => (window.__pwned ? `ran: ${window.__pwned}` : 'nothing ran'));
  }
  await context.close();
  return { query, run, ...result, blocked, mathjaxFiles: local.length, mathjaxBytes: local.reduce((s, r) => s + Math.max(0, r.bytes), 0), speechFiles: local.filter((r) => r.file.includes('/sre/')).map((r) => r.file.split('/').pop()), pageErrors: errors };
}

(async () => {
  const browser = await chromium.launch();
  for (const query of ['doc=sample.md', 'doc=sample.md&fonts=local', 'doc=sample.md&fonts=local&speech=off', 'doc=long.md&fonts=local&speech=off', 'doc=mjprobe.md&fonts=local&speech=off']) {
    console.log(JSON.stringify(await probe(browser, query)));
  }
  await browser.close();
})().catch((error) => { console.error(error); process.exit(1); });
