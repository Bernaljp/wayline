// Equation numbers and \label, \ref, \eqref for KaTeX, which has no cross-references: a prototype of
// the optional part of ticket 180's answer. It runs in marked's processAllTokens hook, after the whole
// document is tokenized and before anything renders. The first pass numbers every numbered equation
// and row in document order as amsmath does (unstarred equation, align, gather, alignat, flalign,
// multline; \notag, \nonumber, and \tag honored) and writes each number as that row's \tag, turning
// \label into a record of it; the second pass puts the numbers where \eqref{key} and \ref{key} stand,
// in math or in text. Both passes see the whole document, so a reference before its equation works.

'use strict';

const REF_NUMBERED = /^\\begin\{(equation|align|gather|alignat|flalign|multline)\}([\s\S]*)\\end\{\1\}$/;
const REF_ROWS = new Set(['align', 'gather', 'alignat', 'flalign']);
const REF_LABEL = /\\label\{([^}]*)\}/;
const REF_USE = /\\(eqref|ref)\{([^}]*)\}/g;

// The rows of an environment's body: split at each \\ outside braces and nested environments.
function refRows(body) {
  const rows = [];
  let depth = 0;
  let nested = 0;
  let start = 0;
  for (let i = 0; i < body.length; i++) {
    if (body[i] === '\\') {
      if (body.startsWith('\\begin{', i)) nested += 1;
      else if (body.startsWith('\\end{', i)) nested -= 1;
      else if (body[i + 1] === '\\' && depth === 0 && nested === 0) { rows.push(body.slice(start, i)); start = i + 2; }
      i += 1;
    } else if (body[i] === '{') depth += 1;
    else if (body[i] === '}') depth -= 1;
  }
  rows.push(body.slice(start));
  return rows;
}

function numberEquations(tokens, walk) {
  const labels = new Map();
  let counter = 0;
  const numberRow = (row) => {
    const label = REF_LABEL.exec(row);
    const bare = row.replace(REF_LABEL, '');
    if (/\\(notag|nonumber)(?![A-Za-z])/.test(bare)) return bare;
    const tag = /\\tag\*?\{([^}]*)\}/.exec(bare);
    const number = tag ? tag[1] : String(++counter);
    if (label) labels.set(label[1], number);
    return tag ? bare : `${bare} \\tag{${number}}`;
  };
  walk(tokens, (token) => {
    if (!(token.type === 'mathBlock' || (token.type === 'mathInline' && token.display))) return;
    const m = REF_NUMBERED.exec(token.text.trim());
    if (!m) { token.text = token.text.replace(REF_LABEL, ''); return; }
    const [, env, body] = m;
    if (REF_ROWS.has(env)) {
      token.text = `\\begin{${env}*}${refRows(body).map((row) => (row.trim() ? numberRow(row) : row)).join('\\\\')}\\end{${env}*}`;
    } else {
      // equation and multline carry one number; KaTeX has no multline, so its rows are gathered.
      const inner = env === 'multline' ? `\\begin{gathered}${body}\\end{gathered}` : body;
      token.text = `\\begin{equation*}${numberRow(inner)}\\end{equation*}`;
    }
  });
  const resolve = (text, math) => text.replace(REF_USE, (all, kind, key) => {
    const number = labels.has(key) ? labels.get(key) : '??';
    const shown = kind === 'eqref' ? `(${number})` : number;
    return math ? `\\text{${shown}}` : shown;
  });
  walk(tokens, (token) => {
    if (token.type === 'mathBlock' || token.type === 'mathInline') token.text = resolve(token.text, true);
    else if (token.type === 'text' && !token.tokens) token.text = resolve(token.text, false);
  });
  return tokens;
}
