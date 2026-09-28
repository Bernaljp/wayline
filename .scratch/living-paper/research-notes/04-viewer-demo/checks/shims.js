// The small additions that close KaTeX's gaps for a paper's LaTeX, each against KaTeX without it.
// A failure is a KaTeX parse error (.katex-error) or the #cc0000 span KaTeX draws for an undefined
// command when throwOnError is false.
'use strict';
const fs = require('fs');
const path = require('path');
const { DEMO, mathWindow } = require('./common.js');

const failures = (html) => (html.match(/katex-error|#cc0000/g) || []).length;
const window = mathWindow();
const plain = (tex, macros = {}) => window.katex.renderToString(tex, { displayMode: true, throwOnError: false, strict: 'ignore', globalGroup: true, macros });

const cases = [
  ['\\label in an equation', String.raw`\begin{equation} a = b \label{eq:ab} \end{equation}`],
  ['\\newcommand of a name KaTeX predefines, then used', String.raw`\newcommand{\R}{\mathcal{R}}\newcommand{\E}{\mathbb{E}} \R(\theta) = \E[\ell]`],
  ['\\DeclareMathOperator', String.raw`\DeclareMathOperator{\Tr}{Tr} \Tr(A)`],
  ['\\DeclareMathOperator* of a predefined name', String.raw`\DeclareMathOperator*{\argmin}{arg\,min} \argmin_x f(x)`],
];
for (const [name, tex] of cases) {
  const shimmed = window.katexRenderer(Object.assign({}, window.MATH_MACROS))(tex, true);
  console.log(`${name.padEnd(52)} KaTeX alone: ${failures(plain(tex))} failure(s); with the shims: ${failures(shimmed)}`);
}

// Equation numbers and references: refs.md, with and without equation-refs.js.
for (const refs of [false, true]) {
  const w = mathWindow({ refs });
  const node = w.renderMarkdown(fs.readFileSync(path.join(DEMO, 'refs.md'), 'utf8'));
  const tags = Array.from(node.querySelectorAll('.katex-display')).map((d) => Array.from(d.querySelectorAll('.katex-tag')).map((t) => t.textContent.replace(/[\s​]/g, '')).join(' '));
  const automatic = node.querySelectorAll('.eqn-num').length;
  const prose = Array.from(node.querySelectorAll('p')).map((p) => p.textContent.replace(/\s+/g, ' ').replace(/[⁡​]/g, ''));
  console.log(`\nrefs.md ${refs ? 'with' : 'without'} equation-refs.js: KaTeX errors ${node.querySelectorAll('.katex-error').length}, explicit tags per display ${JSON.stringify(tags)}, automatic (CSS counter) numbers ${automatic}`);
  for (const line of prose) console.log(`  ${line.slice(0, 120)}`);
}
