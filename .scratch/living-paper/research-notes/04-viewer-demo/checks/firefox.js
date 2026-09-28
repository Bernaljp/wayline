// The same viewer checks in Firefox (a stock build, here the snap's own binary), driven over WebDriver
// BiDi by puppeteer-core: focus on open, Escape, the backdrop, zoom reflow in a wide and a narrow
// window, KaTeX's fonts, requests off 127.0.0.1, and the console.
// FIREFOX: the binary (default: the snap's). FIREFOX_PROFILE: a profile directory the binary may
// write (a snap cannot write the host's /tmp).
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const puppeteer = require('puppeteer-core');
const { BASE, OUT } = require('./common.js');

const FIREFOX = process.env.FIREFOX || '/snap/firefox/current/usr/lib/firefox/firefox';
const PROFILE = process.env.FIREFOX_PROFILE || path.join(os.homedir(), 'snap/firefox/common/viewer-checks-profile');

(async () => {
  fs.mkdirSync(PROFILE, { recursive: true });
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ browser: 'firefox', executablePath: FIREFOX, userDataDir: PROFILE, headless: true, args: ['--no-remote'] });
  const out = { version: await browser.version() };
  const page = await browser.newPage();
  const offsite = [];
  let fontFiles = 0;
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.hostname !== '127.0.0.1') offsite.push(url.href);
    else if (url.pathname.endsWith('.woff2')) fontFiles += 1;
  });
  const consoleMessages = [];
  page.on('console', (message) => consoleMessages.push(`${message.type()}: ${message.text().slice(0, 120)}`));

  for (const [label, width, height] of [['wide', 1280, 800], ['narrow', 390, 844]]) {
    await page.setViewport({ width, height });
    await page.goto(new URL('index.html', BASE).href, { waitUntil: 'load' });
    await page.evaluate(() => { try { localStorage.clear(); } catch (error) { /* none */ } });
    await page.click('[data-view="sample.md"]');
    await page.waitForFunction(() => document.querySelectorAll('#viewer-doc .katex').length > 0);
    await page.evaluate(() => document.fonts.ready);
    const probe = () => page.evaluate(() => {
      const body = document.getElementById('viewer-body');
      const p = document.querySelector('#viewer-doc p:nth-of-type(2)');
      const r = p.getBoundingClientRect();
      return {
        open: document.getElementById('viewer').open,
        focus: `${document.activeElement.localName}${document.activeElement.id ? '#' + document.activeElement.id : ''}`,
        zoom: document.querySelector('#viewer .level').textContent,
        paragraphOnScreen: [Math.round(r.width), Math.round(r.height)],
        paragraphLayoutWidth: p.offsetWidth,
        documentScrollWidth: body.scrollWidth,
        documentClientWidth: body.clientWidth,
        formulas: document.querySelectorAll('#viewer-doc .katex').length,
        fontsLoaded: Array.from(document.fonts).filter((f) => f.status === 'loaded').length,
        features: { zoom: CSS.supports('zoom', '1.5'), closedBy: 'closedBy' in HTMLDialogElement.prototype, has: CSS.supports('selector(:has(a))') },
      };
    });
    const at100 = await probe();
    for (let i = 0; i < 3; i++) await page.keyboard.press('+');
    const at150 = await probe();
    await page.screenshot({ path: path.join(OUT, `firefox-${label}-150.png`) });
    await page.keyboard.press('0');
    await page.keyboard.press('Escape');
    const afterEscape = await page.evaluate(() => ({ open: document.getElementById('viewer').open, focus: document.activeElement && (document.activeElement.dataset.view ? `view ${document.activeElement.dataset.view}` : document.activeElement.localName) }));
    let backdrop = 'not tried: the viewer fills a narrow window';
    if (width > 720) {
      await page.click('[data-view="sample.md"]');
      await page.waitForFunction(() => document.querySelectorAll('#viewer-doc .katex').length > 0);
      await page.mouse.click(5, 5);
      backdrop = await page.evaluate(() => (document.getElementById('viewer').open ? 'still open' : 'closed'));
    }
    out[label] = { at100, at150, afterEscape, backdropClick: backdrop };
  }
  out.offsite = offsite;
  out.fontRequests = fontFiles;
  out.console = consoleMessages;
  await browser.close();
  console.log(JSON.stringify(out, null, 1));
})().catch((error) => { console.error(String(error.stack || error).slice(0, 1500)); process.exit(1); });
