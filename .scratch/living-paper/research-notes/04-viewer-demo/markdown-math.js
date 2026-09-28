// Math in markdown: the demo's stand-in for what renderMarkdown in dashboard/app.js would become
// (ticket 180). Plain script, no module syntax and no build step, like app.js; it needs the globals
// `marked`, `DOMPurify`, and `katex` from the vendored files loaded before it, and uses
// `numberEquations` from equation-refs.js when that file is loaded too.

'use strict';

// One marked extension with a block and an inline tokenizer. The tokenizers take the math out of
// the source before marked reads escapes, emphasis, list markers, or HTML inside it; KaTeX renders it
// to a string; the page is sanitized after, so KaTeX's output passes through DOMPurify like every
// other byte of markdown. `$` follows Pandoc's rule so that prices are not math, and displayed math
// holds no blank line (Pandoc's rule too), so a stray `$$` costs one paragraph, not the page.
//
//   inline:  $...$  \(...\)  and  $$...$$  \[...\]  inside a paragraph (the last two displayed)
//   block:   $$...$$  \[...\]  and a bare \begin{equation|align|...}...\end{...} at a line's start

const MATH_INLINE = /^(?:\$\$((?:\\[\s\S]|[^\\$])+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?![\s$])((?:\\[\s\S]|[^\\$])+?)(?<!\s)\$(?!\d))/;
const MATH_INLINE_START = /\$|\\[([]/;
const MATH_ENVIRONMENTS = 'equation|align|alignat|gather|multline|flalign';
const MATH_BLOCK = new RegExp(
  '^ {0,3}(?:\\$\\$((?:\\\\[\\s\\S]|[^\\\\$])+?)\\$\\$|\\\\\\[([\\s\\S]+?)\\\\\\]|(\\\\begin\\{(' + MATH_ENVIRONMENTS + ')\\*?\\}[\\s\\S]+?\\\\end\\{\\4\\*?\\}))[ \\t]*(?:\\n+|$)'
);
const MATH_BLOCK_START = new RegExp('^ {0,3}(?:\\$\\$|\\\\\\[|\\\\begin\\{(?:' + MATH_ENVIRONMENTS + ')\\*?\\})', 'm');
const MATH_BLANK_LINE = /\n[ \t]*\n/;
// The same inline spans, for marked's emStrongMask hook: a `*` or `_` inside math never pairs with
// one outside it (without the mask, `*see $a*b$ here*` emphasizes the wrong words).
const MATH_MASK = /\$\$(?:\\[\s\S]|[^\\$])+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$(?![\s$])(?:\\[\s\S]|[^\\$])+?(?<!\s)\$(?!\d)/g;

// Commands a paper's LaTeX has that KaTeX lacks, as KaTeX macros: \label is read and dropped (the
// equation keeps its number; equation-refs.js turns it into one), and \DeclareMathOperator defines
// with \def, which also replaces a name KaTeX already has (\argmin). The starred form is renamed
// before rendering, since a macro cannot see the star.
const MATH_MACROS = {
  '\\label': { tokens: [], numArgs: 1 },
  '\\DeclareMathOperator': '\\def#1{\\operatorname{#2}}',
  '\\DeclareMathOperatorStar': '\\def#1{\\operatorname*{#2}}',
};

// KaTeX never trusts the input (no \href, \url, \includegraphics, or \html* commands), caps sizes
// and macro expansion, and never warns (the console stays silent). One `macros` object per document
// with `globalGroup`, so a \newcommand holds for the rest of that document and never leaks into the
// next. A \newcommand of a name KaTeX predefines (\R, \N, \Z) is retried as \renewcommand for exactly
// the name KaTeX's error gives, as LaTeX itself defines none of them; any other error renders as
// KaTeX's red source with the message on hover, and the rest of the page renders.
function katexRenderer(macros) {
  return (tex, display) => {
    const options = { displayMode: display, throwOnError: true, trust: false, strict: 'ignore', maxSize: 20, maxExpand: 1000, output: 'htmlAndMathml', globalGroup: true, macros };
    let source = tex.replace(/\\DeclareMathOperator\*/g, '\\DeclareMathOperatorStar');
    for (let attempt = 0; attempt < 8; attempt++) {
      try {
        return katex.renderToString(source, options);
      } catch (error) {
        const name = /\\newcommand\{(\\[A-Za-z]+)\} attempting to redefine/.exec(String(error && error.message));
        if (!name) break;
        source = source.split(`\\newcommand{${name[1]}}`).join(`\\renewcommand{${name[1]}}`);
      }
    }
    return katex.renderToString(source, Object.assign({}, options, { throwOnError: false }));
  };
}

function markdownWithMath(render) {
  const draw = render || katexRenderer(Object.assign({}, MATH_MACROS));
  const instance = new marked.Marked();
  instance.use({
    extensions: [
      {
        name: 'mathBlock',
        level: 'block',
        start(src) { const m = src.match(MATH_BLOCK_START); return m ? m.index : undefined; },
        tokenizer(src) {
          const m = MATH_BLOCK.exec(src);
          if (!m) return undefined;
          const text = m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3];
          if (MATH_BLANK_LINE.test(text)) return undefined;
          return { type: 'mathBlock', raw: m[0], text: text.trim() };
        },
        renderer(token) { return draw(token.text, true) + '\n'; },
      },
      {
        name: 'mathInline',
        level: 'inline',
        start(src) { const m = src.match(MATH_INLINE_START); return m ? m.index : undefined; },
        tokenizer(src) {
          const m = MATH_INLINE.exec(src);
          if (!m) return undefined;
          const display = m[1] !== undefined || m[2] !== undefined;
          const text = m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : m[4];
          return { type: 'mathInline', raw: m[0], text: text.trim(), display };
        },
        renderer(token) { return draw(token.text, token.display); },
      },
    ],
    hooks: {
      emStrongMask: (src) => src.replace(MATH_MASK, (span) => 'a'.repeat(span.length)),
      // Equation numbers and references, when equation-refs.js is loaded.
      processAllTokens: (tokens) => (typeof numberEquations === 'function' ? numberEquations(tokens, (list, visit) => instance.walkTokens(list, visit)) : tokens),
    },
  });
  return instance;
}

// DOMPurify's defaults drop MathML's <semantics> and <annotation>, which KaTeX wraps every formula's
// MathML in; kept, the accessible MathML is whole. <style> is refused: a document's stylesheet would
// restyle the whole dashboard, and KaTeX never writes one.
const MATH_PURIFY = { ADD_TAGS: ['semantics', 'annotation'], FORBID_TAGS: ['style'] };

function renderMarkdown(text) {
  const node = document.createElement('div');
  node.className = 'markdown';
  node.innerHTML = DOMPurify.sanitize(markdownWithMath().parse(text || ''), MATH_PURIFY);
  return node;
}
