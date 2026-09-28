// What every check shares: where the demo and the repository are, where the served copy of the demo
// answers, where screenshots go, and a jsdom window that runs the vendored scripts and the demo's
// math code the way a page's classic <script> tags would.
//
// Run the checks with the packages of package.json installed outside the repository:
//   NODE_PATH=<dir>/node_modules node checks/<name>.js
// The browser checks also need the demo served (see the note): DEMO_URL, default http://127.0.0.1:8791/.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const DEMO = path.resolve(__dirname, '..');
const REPO = path.resolve(DEMO, '..', '..', '..', '..');
const BASE = process.env.DEMO_URL || 'http://127.0.0.1:8791/';
const OUT = process.env.OUT || path.join(os.tmpdir(), 'viewer-checks');

// A window with marked 18.0.12 and DOMPurify 3.4.15 (the dashboard's own vendored files), KaTeX
// 0.18.9, and the demo's scripts. The demo's scripts are evaluated together, as classic scripts share
// one global scope; a strict-mode eval would otherwise keep their functions to itself.
function mathWindow({ refs = false, edit = (source) => source } = {}) {
  const { JSDOM } = require('jsdom');
  const { window } = new JSDOM('<!DOCTYPE html><html><body></body></html>', { runScripts: 'outside-only' });
  for (const file of [path.join(REPO, 'dashboard/vendor/marked.umd.js'), path.join(REPO, 'dashboard/vendor/purify.min.js'), require.resolve('katex/dist/katex.min.js')]) {
    window.eval(fs.readFileSync(file, 'utf8'));
  }
  const parts = [];
  if (refs) parts.push(fs.readFileSync(path.join(DEMO, 'equation-refs.js'), 'utf8').replace("'use strict';", ''));
  parts.push(edit(fs.readFileSync(path.join(DEMO, 'markdown-math.js'), 'utf8').replace("'use strict';", '')));
  parts.push('Object.assign(window, { renderMarkdown, markdownWithMath, katexRenderer, MATH_PURIFY, MATH_MACROS });');
  window.eval(parts.join('\n'));
  return window;
}

module.exports = { DEMO, REPO, BASE, OUT, mathWindow };
