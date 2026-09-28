// The popup viewer and its zoom: the demo's stand-in for what dashboard/app.js would gain beside
// renderMarkdown (markdown-math.js). Plain script, no build step, like app.js.

'use strict';

const viewer = document.getElementById('viewer');
const viewerBody = document.getElementById('viewer-body');
const viewerDoc = document.getElementById('viewer-doc');
const zoomLevel = viewer.querySelector('.level');
const ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const ZOOM_KEY = 'wayline.viewer.zoom';
let zoomIndex = ZOOM_STEPS.indexOf(1);
let opening = 0; // which open the last fetch belongs to, so a slow read never replaces a newer one

function setZoom(index) {
  zoomIndex = Math.max(0, Math.min(ZOOM_STEPS.length - 1, index));
  const value = ZOOM_STEPS[zoomIndex];
  viewerDoc.style.setProperty('--zoom', String(value));
  zoomLevel.textContent = `${Math.round(value * 100)}%`;
  try { localStorage.setItem(ZOOM_KEY, String(value)); } catch (error) { /* a private window keeps no zoom */ }
}

try {
  const saved = ZOOM_STEPS.indexOf(Number(localStorage.getItem(ZOOM_KEY)));
  if (saved >= 0) zoomIndex = saved;
} catch (error) { /* no storage: start at 100% */ }
setZoom(zoomIndex);

async function openViewer(path) {
  const mine = ++opening;
  document.getElementById('viewer-title').textContent = path;
  document.getElementById('viewer-download').href = path;
  viewerDoc.replaceChildren(Object.assign(document.createElement('p'), { className: 'note', textContent: `reading ${path}` }));
  if (!viewer.open) viewer.showModal();
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    const text = await response.text();
    if (mine !== opening) return;
    const started = performance.now();
    const rendered = renderMarkdown(text);
    window.__lastRenderMs = performance.now() - started;
    viewerDoc.replaceChildren(...rendered.childNodes);
    viewerBody.scrollTop = 0;
  } catch (failure) {
    if (mine !== opening) return;
    viewerDoc.replaceChildren(Object.assign(document.createElement('p'), { className: 'note', textContent: String(failure.message || failure) }));
  }
}

for (const button of document.querySelectorAll('[data-view]')) {
  button.addEventListener('click', () => openViewer(button.dataset.view));
}
viewer.querySelector('[data-close]').addEventListener('click', () => viewer.close());
viewer.querySelector('[data-zoom="in"]').addEventListener('click', () => setZoom(zoomIndex + 1));
viewer.querySelector('[data-zoom="out"]').addEventListener('click', () => setZoom(zoomIndex - 1));
viewer.querySelector('[data-zoom="reset"]').addEventListener('click', () => setZoom(ZOOM_STEPS.indexOf(1)));

// The keys: + (or =) and - step the zoom, 0 resets it; Escape closes the dialog on its own. Ctrl and
// Cmd are left to the browser, whose own zoom still works on the whole page.
viewer.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest('input, textarea, select')) return;
  if (event.key === '+' || event.key === '=') setZoom(zoomIndex + 1);
  else if (event.key === '-' || event.key === '_') setZoom(zoomIndex - 1);
  else if (event.key === '0') setZoom(ZOOM_STEPS.indexOf(1));
  else return;
  event.preventDefault();
});

// A click on the backdrop lands on the dialog itself, since the bar and the body fill it. (The
// closedby="any" attribute does this natively in Chrome 134 and Firefox 141, not yet in Safari.)
viewer.addEventListener('click', (event) => {
  if (event.target === viewer) viewer.close();
});
viewer.addEventListener('close', () => { opening += 1; viewerDoc.replaceChildren(); });

// For the demo's checks: ?open=<file>&zoom=<percent> opens the viewer on load (a browser run headless
// without a driver, such as `firefox --headless --screenshot`, cannot click), and the button behind
// the viewer counts its clicks.
{
  const params = new URLSearchParams(location.search);
  const step = ZOOM_STEPS.indexOf(Number(params.get('zoom')) / 100);
  if (step >= 0) setZoom(step);
  if (params.get('open')) openViewer(params.get('open'));
}
document.getElementById('behind').addEventListener('click', () => {
  const count = document.getElementById('behind-count');
  count.textContent = String(Number(count.textContent) + 1);
});
