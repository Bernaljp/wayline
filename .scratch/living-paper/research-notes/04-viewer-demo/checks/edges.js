// The math tokenizers of markdown-math.js on the cases where Markdown and math collide, with math
// drawn as [[...]] so the Markdown around it shows. The first case is run again without the
// emStrongMask hook, to show what the hook is for.
'use strict';
const { mathWindow } = require('./common.js');

const CASES = [
  ['emphasis around math with a star', '*see $a*b$ here*'],
  ['strong around math with a subscript star', '**bold $x_1^*$ text**'],
  ['underscore emphasis around math', '_the value $x_i$ and $y_j$_'],
  ['math inside a link', '[the loss $\\mathcal{L}$](https://example.com)'],
  ['inline math across a line break', 'a formula $a +\nb$ across lines'],
  ['escaped dollars stay text', 'costs \\$5 and \\$10'],
  ['a price pair stays text', 'from $20,000 to $30,000'],
  ['dollars with spaces stay text', 'a $ b $ c'],
  ['an unclosed $$ costs one paragraph', '$$\nx = 1\n\nA paragraph.\n\nAnother.\n\n$$y$$'],
  ['a display holding a blank line is not math', '$$\na\n\nb\n$$'],
  ['a bare align at a line start, a row starting with +', '\\begin{align}\na &= b \\\\\n+ c &= d\n\\end{align}'],
  ['\\[ \\] inside a paragraph', 'text \\[x^2\\] text'],
  ['a pipe inside math in a table cell', '| a | b |\n|---|---|\n| $|x|$ | $\\lvert x \\rvert$ |'],
  ['math in a heading', '## The bound $\\epsilon_n$'],
  ['a code span with dollars', '`$x$` and $y$'],
  ['math in list items', '- first $a_1$\n- second $a_2$'],
];
const marker = (tex, display) => (display ? `<div>[[${tex}]]</div>` : `[[${tex}]]`);
const withMask = mathWindow();
const withoutMask = mathWindow({ edit: (source) => source.replace(/\s*emStrongMask:[^\n]*\n/, '\n') });
const show = (window, src) => window.markdownWithMath(marker).parse(src).trim().replace(/\n/g, '\\n');
for (const [name, src] of CASES) console.log(`${name}\n  ${show(withMask, src)}`);
console.log(`without the emStrongMask hook, the first case\n  ${show(withoutMask, CASES[0][1])}`);
