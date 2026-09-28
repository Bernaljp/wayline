// Bytes and file counts of what each renderer would put under dashboard/vendor/, raw (what the
// dashboard's server sends; it does not compress) and gzipped at level 9 for comparison only.
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const dir = (pkg) => path.dirname(require.resolve(`${pkg}/package.json`));
function files(target, keep = () => true) {
  const out = [];
  const walk = (p) => (fs.statSync(p).isDirectory() ? fs.readdirSync(p).forEach((n) => walk(path.join(p, n))) : keep(p) && out.push(p));
  walk(target);
  return out;
}
function row(label, list) {
  let raw = 0;
  let gz = 0;
  for (const file of list) {
    const data = fs.readFileSync(file);
    raw += data.length;
    gz += zlib.gzipSync(data, { level: 9 }).length;
  }
  console.log(`| ${label} | ${list.length} | ${raw.toLocaleString('en-US')} | ${gz.toLocaleString('en-US')} |`);
}

const katex = path.join(dir('katex'), 'dist');
const woff2 = files(path.join(katex, 'fonts'), (f) => f.endsWith('.woff2'));
const mj4 = dir('mathjax');
const ncm = dir('@mathjax/mathjax-newcm-font');
const mj3 = path.join(dir('mathjax3'), 'es5');
console.log('| set | files | bytes | gzip -9 bytes |\n|---|---|---|---|');
row('KaTeX 0.18.9: katex.min.js', [path.join(katex, 'katex.min.js')]);
row('KaTeX 0.18.9: katex.min.css', [path.join(katex, 'katex.min.css')]);
row('KaTeX 0.18.9: fonts/*.woff2', woff2);
row('**KaTeX 0.18.9: the set (js, css, woff2)**', [path.join(katex, 'katex.min.js'), path.join(katex, 'katex.min.css'), ...woff2]);
row('KaTeX 0.18.9: fonts/*.woff and *.ttf, not needed', files(path.join(katex, 'fonts'), (f) => !f.endsWith('.woff2')));
row('KaTeX 0.18.9: contrib/mhchem.min.js, optional', [path.join(katex, 'contrib/mhchem.min.js')]);
row('MathJax 4.1.3: tex-chtml.js', [path.join(mj4, 'tex-chtml.js')]);
row('MathJax 4.1.3: input/tex/extensions/', files(path.join(mj4, 'input/tex/extensions')));
row('MathJax 4.1.3: newcm font chtml/woff2/', files(path.join(ncm, 'chtml/woff2')));
row('MathJax 4.1.3: newcm font chtml/dynamic/', files(path.join(ncm, 'chtml/dynamic')));
row('MathJax 4.1.3: ui/safe.js', [path.join(mj4, 'ui/safe.js')]);
row('**MathJax 4.1.3: offline set without speech**', [path.join(mj4, 'tex-chtml.js'), ...files(path.join(mj4, 'input/tex/extensions')), ...files(path.join(ncm, 'chtml/woff2')), ...files(path.join(ncm, 'chtml/dynamic')), path.join(mj4, 'ui/safe.js')]);
row('MathJax 4.1.3: sre/ (speech worker and locale maps)', files(path.join(mj4, 'sre')));
row('MathJax 3.2.2: es5/tex-chtml-full.js', [path.join(mj3, 'tex-chtml-full.js')]);
row('MathJax 3.2.2: es5/output/chtml/fonts/woff-v2/', files(path.join(mj3, 'output/chtml/fonts/woff-v2')));
row('**MathJax 3.2.2: the set (tex-chtml-full.js, woff-v2)**', [path.join(mj3, 'tex-chtml-full.js'), ...files(path.join(mj3, 'output/chtml/fonts/woff-v2'))]);
const { REPO } = require('./common.js');
row('marked 18.0.12 and DOMPurify 3.4.15, vendored today', [path.join(REPO, 'dashboard/vendor/marked.umd.js'), path.join(REPO, 'dashboard/vendor/purify.min.js')]);
