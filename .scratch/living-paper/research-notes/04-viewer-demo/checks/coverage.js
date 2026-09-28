// The LaTeX a paper uses, one construct at a time, through KaTeX 0.18.9 (alone, and with the shims of
// markdown-math.js), MathJax 4.1.3, and MathJax 3.2.2 (tags: 'ams'; default TeX packages plus
// autoload). A pass is no KaTeX parse error or red undefined command; for MathJax, no <merror> and no
// red <mtext> (its noundefined extension). The two MathJax versions clash in one process, so each
// runs in its own: node coverage.js katex | mathjax4 | mathjax3, or with no argument all three.
'use strict';
const { execFileSync } = require('child_process');
const { mathWindow } = require('./common.js');

const CASES = [
  ['align with & and \\\\', String.raw`\begin{align} a &= b + c \\ d &= e \end{align}`],
  ['align*', String.raw`\begin{align*} a &= b \\ c &= d \end{align*}`],
  ['aligned', String.raw`\begin{aligned} a &= b \\ c &= d \end{aligned}`],
  ['equation', String.raw`\begin{equation} E = mc^2 \end{equation}`],
  ['gather', String.raw`\begin{gather} a = b \\ c = d \end{gather}`],
  ['multline', String.raw`\begin{multline} a + b + c \\ + d + e \end{multline}`],
  ['split in equation', String.raw`\begin{equation}\begin{split} a &= b \\ &= c \end{split}\end{equation}`],
  ['cases', String.raw`f(x) = \begin{cases} 0 & x < 0 \\ 1 & x \ge 0 \end{cases}`],
  ['\\tag', String.raw`x = y \tag{3.1}`],
  ['\\tag in an align row', String.raw`\begin{align} a &= b \tag{A} \\ c &= d \end{align}`],
  ['\\notag, \\nonumber', String.raw`\begin{align} a &= b \notag \\ c &= d \nonumber \end{align}`],
  ['\\label', String.raw`\begin{equation} a = b \label{eq:ab} \end{equation}`],
  ['\\eqref', String.raw`\text{see } \eqref{eq:ab}`],
  ['\\ref', String.raw`\text{see } \ref{eq:ab}`],
  ['\\mathbf', String.raw`\mathbf{W} \mathbf{x}`],
  ['\\boldsymbol', String.raw`\boldsymbol{\mu}, \boldsymbol{\Sigma}`],
  ['\\bm', String.raw`\bm{\theta}`],
  ['\\mathbb \\mathcal \\mathrm \\mathsf', String.raw`\mathbb{E} \mathcal{L} \mathrm{d}x \mathsf{T}`],
  ['\\operatorname, \\operatorname*', String.raw`\operatorname{tr}(A) \operatorname*{arg\,min}_\theta L`],
  ['\\DeclareMathOperator', String.raw`\DeclareMathOperator{\Tr}{Tr} \Tr(A)`],
  ['\\newcommand with an argument', String.raw`\newcommand{\norm}[1]{\left\lVert #1 \right\rVert} \norm{x}`],
  ['\\newcommand{\\R}', String.raw`\newcommand{\R}{\mathbb{R}} x \in \R`],
  ['\\renewcommand{\\R}', String.raw`\renewcommand{\R}{\mathbb{R}} x \in \R`],
  ['\\providecommand', String.raw`\providecommand{\E}{\mathbb{E}} \E[x]`],
  ['\\def', String.raw`\def\half{\frac12} \half`],
  ['\\left \\middle \\right', String.raw`\left( \frac{a}{b} \middle| c \right)`],
  ['\\big \\Big', String.raw`\big( x \Big)`],
  ['\\text with $ inside', String.raw`\text{if $x>0$}`],
  ['\\xrightarrow \\overset \\underbrace', String.raw`A \xrightarrow{f} B, \overset{?}{=}, \underbrace{a+b}_{n}`],
  ['\\substack', String.raw`\sum_{\substack{i<j \\ i \ne k}} a_{ij}`],
  ['\\lVert \\rVert \\lvert \\rvert', String.raw`\lVert x \rVert_2 \lvert y \rvert`],
  ['\\top \\intercal \\odot \\otimes', String.raw`A^\top B^\intercal \odot \otimes`],
  ['\\coloneqq (mathtools)', String.raw`x \coloneqq y`],
  ['\\mathbbm (bbm)', String.raw`\mathbbm{1}`],
  ['\\mathds (dsfont)', String.raw`\mathds{1}`],
  ['\\SI (siunitx)', String.raw`\SI{3}{\meter}`],
  ['\\qty (physics)', String.raw`\qty(\frac{a}{b})`],
  ['\\ce (mhchem)', String.raw`\ce{H2O}`],
  ['\\color \\textcolor', String.raw`\color{red} x \textcolor{blue}{y}`],
  ['accents', String.raw`\hat{x} \tilde{y} \bar{z} \vec{v} \dot{q}`],
  ['\\mathop \\limits', String.raw`\mathop{\mathrm{softmax}}\limits_i z_i`],
  ['array with | and \\hline', String.raw`\begin{array}{c|c} a & b \\ \hline c & d \end{array}`],
  ['pmatrix, bmatrix', String.raw`\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix} \begin{bmatrix} a \end{bmatrix}`],
  ['smallmatrix', String.raw`\left(\begin{smallmatrix} a & b \\ c & d \end{smallmatrix}\right)`],
  ['subequations', String.raw`\begin{subequations} a = b \end{subequations}`],
  ['\\cite', String.raw`x \cite{smith2020}`],
];

function katexColumns() {
  const window = mathWindow();
  const out = {};
  for (const [name, tex] of CASES) {
    const bad = (html) => /katex-error|#cc0000/.test(html);
    const alone = window.katex.renderToString(tex, { displayMode: true, throwOnError: false, strict: 'ignore', globalGroup: true, macros: {} });
    const shimmed = window.katexRenderer(Object.assign({}, window.MATH_MACROS))(tex, true);
    out[name] = { katex: bad(alone) ? 'no' : 'ok', shims: bad(shimmed) ? 'no' : 'ok' };
  }
  return out;
}

async function mathjaxColumn(which) {
  const MathJax = await require(which === 3 ? 'mathjax3' : 'mathjax').init({ loader: { load: ['input/tex'] }, tex: { tags: 'ams' }, startup: { typeset: false } });
  const out = {};
  for (const [name, tex] of CASES) {
    try {
      const mml = await MathJax.tex2mmlPromise(tex, { display: true });
      const error = /<merror[^>]*>[\s\S]*?<mtext[^>]*>([^<]*)</.exec(mml);
      const undefinedMacro = /<mtext[^>]*mathcolor="red"[^>]*>([^<]*)</.exec(mml);
      out[name] = error ? `no (${error[1].slice(0, 40)})` : undefinedMacro ? `no (undefined ${undefinedMacro[1]})` : 'ok';
    } catch (failure) {
      out[name] = `no (${String(failure.message).slice(0, 40)})`;
    }
  }
  return out;
}

(async () => {
  const which = process.argv[2];
  if (which === 'katex') { console.log(JSON.stringify(katexColumns())); return; }
  if (which === 'mathjax4' || which === 'mathjax3') { console.log(JSON.stringify(await mathjaxColumn(which === 'mathjax3' ? 3 : 4))); process.exit(0); }
  const run = (arg) => JSON.parse(execFileSync(process.execPath, [__filename, arg], { encoding: 'utf8', env: process.env }).trim().split('\n').pop());
  const k = run('katex');
  const m4 = run('mathjax4');
  const m3 = run('mathjax3');
  console.log(`| construct | KaTeX 0.18.9 | KaTeX with shims | MathJax 4.1.3 | MathJax 3.2.2 |\n|---|---|---|---|---|`);
  for (const [name] of CASES) console.log(`| ${name.replace(/\|/g, '\\|')} | ${k[name].katex} | ${k[name].shims} | ${m4[name]} | ${m3[name]} |`);
  const tally = (col, key) => CASES.filter(([name]) => (key ? col[name][key] : col[name]) === 'ok').length;
  console.log(`\npassed of ${CASES.length}: KaTeX ${tally(k, 'katex')}, KaTeX with shims ${tally(k, 'shims')}, MathJax 4 ${tally(m4)}, MathJax 3 ${tally(m3)}`);
})();
