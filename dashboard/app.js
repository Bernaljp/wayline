// The dashboard's front end (Implementation Decisions 8): the views, and since ticket 35 the actions. No framework, no build step.
//
// Transport is polling, which research-notes 08 measured as the cheaper and more robust of the two
// through an ssh tunnel: the journal tail asks for the bytes after an offset every 2 s, every other
// view revalidates with If-None-Match every 5 s and usually gets 304. `?transport=sse` switches the
// tail alone to the server-sent-events endpoint, which is what the owner compares through the
// tunnel before OPEN-20 is closed.
//
// Every fetch is `cache: 'no-store'` with our own If-None-Match, so a 304 reaches this code instead
// of being turned back into a 200 out of the browser's cache.

'use strict';

const PARAMS = new URLSearchParams(location.search);
const TOKEN = PARAMS.get('token') || '';
const TRANSPORT = PARAMS.get('transport') === 'sse' ? 'sse' : 'poll';
const TAIL_LINES = 500;

// What each column of a table holds, in order, for the two tables of tickets: four one-line values
// and then the title, which is the only prose in the row.
const TICKET_COLUMNS = ['short', 'short', 'short', 'short', 'text'];
// `dag.svg` draws a project with no tickets as a canvas of no size.
const EMPTY_CANVAS = /viewBox="0 0 0 0"/;

const state = {
  projects: [],
  project: null,
  tags: {},
  since: null, // null means "the tail has not read this project yet": ask by line count, not offset

  tickets: [], // every ticket's frontmatter, for the board, the graph, and the card a node shows
  ticketsFor: null, // the project `tickets` was read from, so another project's titles are never drawn
  ticketsFailure: null, // { project, message } of the last read of `tickets` that failed, for the board to say
  frontier: [], // the overview's frontier, as ids, for the board's column of it
  frontierFor: null, // the project `frontier` was read from
  frontierFailure: null, // { project, message } of the last read of the overview that failed
  graphSource: null, // the SVG the server last sent, redrawn whenever the titles change or the graph is shown
  openSignature: null, // the open decision tickets last drawn, so a poll that changed nothing leaves their forms alone
  openDecisions: { project: null, list: [] }, // the same list, for the ticket page of one of them
  ticketDecisionSignature: null, // what the ticket page's own answer form was last drawn from
  ticket: null, // the ticket id whose page is open, or null when the graph is showing
  log: null, // { kind, id, since } of the log tail that is open, or null

  view: null, // the view shown: 'projects', or one of VIEW_NAMES (tickets 110, 111, and 112)
  projectsLoaded: false, // whether /api/projects has answered once, so a route naming a project can be applied
  research: null, // { project, view } of the last Research view read, for the dot of the report the owner opens
  waiting: 0, // the selected project's "Waiting on you" count, which the browser tab's title carries
  seeing: null, // { project, item } of a report opened before Research was read, to mark seen once it is

  pollJournal: 2,
  pollViews: 5,
  stream: null,
  timers: {},
};

// --- the transport ------------------------------------------------------------------------------

// `key` is what the ETag is remembered under. It is not the URL: the tail's URL carries a `since`
// that changes on every append, so keying by URL would grow a dead entry per event for the life of
// the page. The server folds the cursor into the tag, so one key per endpoint is safe.
async function get(path, key) {
  const cache = key || path;
  const headers = {};
  if (TOKEN) headers['X-Wayline-Token'] = TOKEN;
  const tag = state.tags[cache];
  if (tag) headers['If-None-Match'] = tag;
  const response = await fetch(path, { cache: 'no-store', headers });
  if (response.status === 304) return null;
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
  const etag = response.headers.get('ETag');
  if (etag) state.tags[cache] = etag;
  return response.json();
}

// Like `get`, but for the graph's SVG body, which is not JSON.
async function getText(path, key) {
  const cache = key || path;
  const headers = {};
  if (TOKEN) headers['X-Wayline-Token'] = TOKEN;
  const tag = state.tags[cache];
  if (tag) headers['If-None-Match'] = tag;
  const response = await fetch(path, { cache: 'no-store', headers });
  if (response.status === 304) return null;
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
  const etag = response.headers.get('ETag');
  if (etag) state.tags[cache] = etag;
  return response.text();
}

function every(name, seconds, run) {
  if (state.timers[name]) clearInterval(state.timers[name]);
  run();
  state.timers[name] = setInterval(run, Math.max(1, seconds) * 1000);
}

// --- rendering helpers --------------------------------------------------------------------------

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined) continue;
    if (name === 'class') node.className = value;
    else if (name === 'text') node.textContent = value;
    else node.setAttribute(name, value);
  }
  for (const child of children || []) node.appendChild(child);
  return node;
}

// A path, an id, or a reading is read character by character rather than as a word, so it is set
// in the monospace face; a long one wraps inside its own column rather than widening the page, and
// carries the whole value in its title when the wrap is not the whole story.
const MONOSPACED = /[/\\]|^[\d.]+$/;

// Longer than this and a value gets its title, so that what the cell shows is never all there is.
const TITLE_AT = 60;

// A value as it reads in full: what a title carries, and what `short` cuts down for a row.
function wholeValue(value) {
  return value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function fields(pairs) {
  const list = el('dl', { class: 'fields' });
  for (const [name, value, whole] of pairs) {
    if (value === null || value === undefined || value === '') continue;
    const text = String(value);
    const title = whole === undefined ? (text.length > TITLE_AT ? text : null) : wholeValue(whole);
    list.appendChild(el('div', { class: 'field' }, [
      el('dt', { text: name }),
      el('dd', { class: MONOSPACED.test(text) ? 'mono' : null, text, title }),
    ]));
  }
  return list;
}

// --- the empty, loading, and error states --------------------------------------------------------
//
// The three things a panel has to say instead of its content, each said inside the panel it belongs
// to (ticket 58). The empty case is the one the owner met at the M1 demo: a table with no rows drew
// its header across the page with nothing under it, which reads as a broken page rather than as a
// count of zero. Every table and list goes through `tableOrNone` or `listOrNone`, so no view can
// draw one without the sentence that stands in for it.

function emptyState(text) {
  return el('p', { class: 'state', text });
}

function loadingState(text) {
  return el('p', { class: 'state loading', text });
}

function errorState(failure) {
  return el('p', { class: 'state error', role: 'alert', text: String((failure && failure.message) || failure) });
}

// A heading inside a panel: what the table or list below it holds, and how many rows it has. A
// section with nothing to count (the body of a ticket, its latest result) is given no badge.
function subhead(name, count) {
  const parts = [el('span', { text: name })];
  if (count !== undefined && count !== null) parts.push(el('span', { class: 'count', text: String(count) }));
  return el('h3', { class: 'sub' }, parts);
}

// --- markdown and its math (ticket 74) ----------------------------------------------------------
//
// One marked extension with a block and an inline tokenizer, which marked tries before its own at
// every position, so the math is taken out of the source before marked reads escapes, emphasis, list
// markers, or HTML inside it (research note 04, `research/viewer-math-and-zoom`). KaTeX renders it to
// a string, and the whole page is sanitized after, so KaTeX's output passes through DOMPurify like
// every other byte of markdown. `$` follows Pandoc's rule, so prices are not math, and displayed math
// holds no blank line (Pandoc's rule too), so a stray `$$` costs one paragraph, not the page.
//
//   inline:  $...$  \(...\)  and  $$...$$  \[...\]  inside a paragraph (the last two displayed)
//   block:   $$...$$  \[...\]  and a bare \begin{equation|align|...}...\end{...} at a line's start,
//            and `$$...$$ {#eq:label}`, a numbered equation as the sections write one

const MATH_INLINE = /^(?:\$\$((?:\\[\s\S]|[^\\$])+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?![\s$])((?:\\[\s\S]|[^\\$])+?)(?<!\s)\$(?!\d))/;
const MATH_INLINE_START = /\$|\\[([]/;
const MATH_ENVIRONMENTS = 'equation|align|alignat|gather|multline|flalign';
const MATH_BLOCK = new RegExp(
  // A display ends at its first closing delimiter, which must end the line: `\[a\] and \[b\]` on one
  // line is a paragraph with two displays in it, never one display running from the first to the last.
  '^ {0,3}(?:\\$\\$((?:\\\\[\\s\\S]|[^\\\\$])+?)\\$\\$(?:[ \\t]*\\{#(eq:[^}\\s]+)\\})?|\\\\\\[((?:(?!\\\\\\])[\\s\\S])+?)\\\\\\]|(\\\\begin\\{(' + MATH_ENVIRONMENTS + ')(\\*?)\\}[\\s\\S]+?\\\\end\\{\\5\\6\\}))[ \\t]*(?:\\n+|$)'
);
const MATH_BLOCK_START = new RegExp('^ {0,3}(?:\\$\\$|\\\\\\[|\\\\begin\\{(?:' + MATH_ENVIRONMENTS + ')\\*?\\})', 'm');
const MATH_BLANK_LINE = /\n[ \t]*\n/;
// The same inline spans, for marked's emStrongMask hook: a `*` or `_` inside math never pairs with
// one outside it (without the mask, `*see $a*b$ here*` emphasizes the wrong words). It is
// MATH_INLINE itself, unanchored and global, so the two can never disagree about where math is.
const MATH_MASK = new RegExp(MATH_INLINE.source.slice(1), 'g');

// Commands a paper's LaTeX has that KaTeX lacks, as KaTeX macros: \label is read and dropped (the
// equation keeps its number; `numberEquations` turns it into one), and \DeclareMathOperator defines
// with \def, which also replaces a name KaTeX already has (\argmin). The starred form is renamed
// before rendering, since a macro cannot see the star.
const MATH_MACROS = {
  '\\label': { tokens: [], numArgs: 1 },
  '\\DeclareMathOperator': '\\def#1{\\operatorname{#2}}',
  '\\DeclareMathOperatorStar': '\\def#1{\\operatorname*{#2}}',
};

// KaTeX never trusts the input (no \href, \url, \includegraphics, or \html* commands), caps sizes and
// macro expansion, and never warns. One `macros` object per document with `globalGroup`, so a
// \newcommand holds for the rest of that document and never leaks into the next. A \newcommand of a
// name KaTeX predefines but LaTeX does not (\R, \N, \Z) is retried as \renewcommand for exactly the
// name KaTeX's error gives; any other error renders as KaTeX's red source with the message on hover,
// and the rest of the page renders.
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
        // Braced or not: `\newcommand{\R}` and `\newcommand\R` are the same definition.
        const bare = name[1].slice(1);
        source = source.replace(new RegExp(`\\\\newcommand(\\{\\\\${bare}\\}|\\\\${bare}(?![A-Za-z]))`, 'g'), '\\renewcommand$1');
      }
    }
    return katex.renderToString(source, Object.assign({}, options, { throwOnError: false }));
  };
}

// Equation numbers and \label, \ref, \eqref, which KaTeX has no cross-references for. This runs in
// marked's processAllTokens hook, after the whole document is tokenized and before anything renders.
// The first pass numbers every numbered equation and row in document order as amsmath does
// (unstarred equation, align, gather, alignat, flalign, multline, and a `$$...$$ {#eq:label}`;
// \notag, \nonumber, and \tag honored) and writes each number as that row's \tag, recording its
// \label; the second puts the numbers where \eqref{key}, \ref{key}, and @eq:key stand, in math or in
// text. Both passes see the whole document, so a reference before its equation works.
const REF_NUMBERED = new RegExp('^\\\\begin\\{(' + MATH_ENVIRONMENTS + ')\\}([\\s\\S]*)\\\\end\\{\\1\\}$');
const REF_ROWS = new Set(['align', 'gather', 'alignat', 'flalign']);
const REF_LABEL = /\\label\{([^}]*)\}/;
const REF_USE = /\\(eqref|ref)\{([^}]*)\}|@(eq:[\w:.-]*\w)/g;

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
    let text = token.text.trim();
    if (token.label && !REF_NUMBERED.test(text)) text = `\\begin{equation}${text}\\label{${token.label}}\\end{equation}`;
    const m = REF_NUMBERED.exec(text);
    if (!m) { token.text = text.replace(REF_LABEL, ''); return; }
    const [, env, body] = m;
    if (REF_ROWS.has(env)) {
      token.text = `\\begin{${env}*}${refRows(body).map((row) => (row.trim() ? numberRow(row) : row)).join('\\\\')}\\end{${env}*}`;
    } else {
      // equation and multline carry one number; KaTeX has no multline, so its rows are gathered.
      const inner = env === 'multline' ? `\\begin{gathered}${body}\\end{gathered}` : body;
      token.text = `\\begin{equation*}${numberRow(inner)}\\end{equation*}`;
    }
  });
  const resolve = (text, math) => text.replace(REF_USE, (all, kind, key, crossref) => {
    const name = crossref || key;
    const number = labels.has(name) ? labels.get(name) : '??';
    const shown = kind === 'ref' ? number : `(${number})`;
    return math ? `\\text{${shown}}` : shown;
  });
  walk(tokens, (token) => {
    if (token.type === 'mathBlock' || token.type === 'mathInline') token.text = resolve(token.text, true);
    else if (token.type === 'text' && !token.tokens) token.text = resolve(token.text, false);
  });
  return tokens;
}

// A new marked instance per file rendered, since the macros a file defines are that file's alone.
function markdownWithMath() {
  const draw = katexRenderer(Object.assign({}, MATH_MACROS));
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
          const text = m[1] ?? m[3] ?? m[4];
          if (MATH_BLANK_LINE.test(text)) return undefined;
          return { type: 'mathBlock', raw: m[0], text: text.trim(), label: m[2] };
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
          const text = m[1] ?? m[2] ?? m[3] ?? m[4];
          return { type: 'mathInline', raw: m[0], text: text.trim(), display };
        },
        renderer(token) { return draw(token.text, token.display); },
      },
    ],
    hooks: {
      emStrongMask: (src) => src.replace(MATH_MASK, (span) => 'a'.repeat(span.length)),
      processAllTokens: (tokens) => numberEquations(tokens, (list, visit) => instance.walkTokens(list, visit)),
    },
  });
  return instance;
}

// DOMPurify's defaults drop MathML's <semantics> and <annotation>, which KaTeX wraps every formula's
// MathML in; kept, the accessible MathML is whole. `annotation-xml`, the integration point where
// mXSS lives, stays forbidden. <style> is refused: a rendered file's stylesheet would restyle the whole
// dashboard (the v1.0.1 hole), and KaTeX never writes one; its `style` attributes stay.
const MATH_PURIFY = { ADD_TAGS: ['semantics', 'annotation'], FORBID_TAGS: ['style'] };

// Markdown from the ledger is written by workers (models), so it is sanitized before it is shown:
// an unsanitized <script> in a findings file would be a prompt-injection path into the actions the
// dashboard grows in M4. This is the one place any markdown becomes HTML; the ticket pages, the
// position memo, and the document viewer all render through it. `fileAt` is the rendered file's path
// in the project (a directory ends in `/`), which its relative images and links are read against.
function renderMarkdown(text, fileAt) {
  const node = el('div', { class: 'markdown' });
  node.innerHTML = DOMPurify.sanitize(markdownWithMath().parse(text || ''), MATH_PURIFY);
  return pointIntoProject(keepOnTheWorkstation(node), fileAt || '');
}

// What a sanitized page may still fetch by itself, beside an image's `src` and a link's `href`, which
// `pointIntoProject` points at the project: DOMPurify keeps these, and each one is a request a
// model-written file could aim off the workstation, with what it read in the URL.
const FETCHING_ATTRIBUTES = ['srcset', 'poster', 'background', 'lowsrc', 'dynsrc', 'xlink:href', 'ping'];
const FETCHING_STYLE = /url\s*\(|image-set\s*\(|@\s*import/i;

function keepOnTheWorkstation(node) {
  for (const element of node.querySelectorAll('*')) {
    for (const name of FETCHING_ATTRIBUTES) element.removeAttribute(name);
    // KaTeX writes `style` attributes, never one that fetches.
    if (FETCHING_STYLE.test(element.getAttribute('style') || '')) element.removeAttribute('style');
    const tag = element.localName;
    if (tag !== 'img') element.removeAttribute('src'); // video, audio, source, input, and the rest
    if (tag !== 'a') element.removeAttribute('href'); // SVG's <image> and <use> among them
  }
  return node;
}

// `columns` names what each column holds: `short` for an id, a count, or a status, which stays on
// one line in the monospace face, and `text` for prose, which wraps inside a readable measure. A
// cell longer than the measure keeps its whole value in its title.
function tableElement(headings, rows, columns) {
  const head = el('tr', {}, headings.map((name, index) => el('th', { class: (columns || [])[index] || null, text: name })));
  const body = rows.map((row) => el('tr', {}, row.map((cell, index) => {
    const text = cell === null || cell === undefined ? '' : String(cell);
    const kind = (columns || [])[index] || null;
    if (kind === 'clamp') {
      // A cell that can run to pages (a decider's rationale) shows its first lines; a click shows the rest.
      const inner = el('div', { class: 'clamp', text, title: text.length > TITLE_AT ? 'click to read it whole' : null });
      inner.addEventListener('click', () => inner.classList.toggle('open'));
      return el('td', { class: 'text' }, [inner]);
    }
    return el('td', { class: kind, text, title: text.length > TITLE_AT ? text : null });
  })));
  return el('table', {}, [el('thead', {}, [head]), el('tbody', {}, body)]);
}

// The only way a table is drawn: rows, or the words that say there are none. The wrapper scrolls a
// wide table inside its panel rather than widening the page.
function tableOrNone(headings, rows, empty, columns) {
  if (!rows.length) return emptyState(empty);
  return el('div', { class: 'table-wrap' }, [tableElement(headings, rows, columns)]);
}

function replace(node, children) {
  node.replaceChildren(...children);
}

// --- the tabs -----------------------------------------------------------------------------------

async function loadProjects() {
  const view = await get('/api/projects');
  if (!view) return;
  state.projects = view.projects;
  if (view.settings) {
    state.pollJournal = view.settings.poll_journal_s || state.pollJournal;
    state.pollViews = view.settings.poll_views_s || state.pollViews;
  }
  const tabs = document.getElementById('tabs');
  replace(tabs, state.projects.map((project) => {
    const tab = el('button', {
      class: 'tab',
      type: 'button',
      'data-id': project.id,
      title: project.path + (project.readable ? '' : ' (the path is gone)')
        + (project.readable && project.read_only ? ' (made with ' + (project.harness_tag || 'an older tag') + ', read-only: wayline upgrade --to that tag, or a new project)' : ''),
      'aria-current': String(project.id === state.project),
    }, [
      // A project of another research_version is read-only (decision 17): marked with its tag, its files still open.
      el('span', { text: project.name + (project.active ? ' *' : '') + (project.readable && project.read_only ? ' (' + (project.harness_tag || 'an older tag') + ', read-only)' : '') }),
      // What waits on the owner in that project, on its tab (ticket 110).
      ...(project.waiting ? [el('span', { class: 'count', text: String(project.waiting), title: `${project.waiting} waiting on you` })] : []),
    ]);
    if (!project.readable) tab.disabled = true;
    tab.addEventListener('click', () => go(routeTo(project.id, state.view && state.view !== 'projects' ? state.view : 'research')));
    return tab;
  }));
  state.projectsLoaded = true;
  markViews(); // a project's first document offers its Inherited view
  if (state.view === 'projects') renderProjectsPage();
  if (state.project && !state.projects.some((project) => project.id === state.project && project.readable)) {
    // The project open here was unregistered or its path is gone: its polls would only fail, so the page moves to the
    // default route, the active project's Research or the projects page.
    state.project = null;
    history.replaceState(null, '', location.pathname + location.search);
    routing.done = false;
  }
  if (!routing.done) route();
}

function select(id) {
  if (state.project === id) return;
  state.project = id;
  state.since = null;
  state.tags = {};
  // The panels of the project being left are not the panels of the one being opened: each says it
  // is reading until its own first answer lands.
  document.getElementById('journal-tail').replaceChildren();
  delete document.getElementById('ticket-body').dataset.ticket;
  state.tickets = [];
  state.ticketsFor = null;
  state.ticketsFailure = null;
  state.frontier = [];
  state.frontierFor = null;
  state.frontierFailure = null;
  state.graphSource = null;
  hideNodeCard();
  renderBoard();
  replace(document.getElementById('overview-body'), [loadingState('reading the ledger')]);
  replace(document.getElementById('graph-body'), [loadingState('drawing the graph')]);
  replace(document.getElementById('outputs-body'), [loadingState('indexing the outputs')]);
  replace(document.getElementById('decisions-open'), [loadingState('reading the open decision tickets')]);
  replace(document.getElementById('changes-body'), [loadingState('reading the feedback')]);
  for (const [id, text] of Object.entries(READING)) replace(document.getElementById(id), [loadingState(text)]);
  replace(document.getElementById('strip-items'), []);
  state.research = null;
  state.waiting = 0;
  // A project of another research_version is read-only (decision 17): its files open, and no action is offered.
  const entry = state.projects.find((project) => project.id === id);
  document.body.dataset.readOnly = String(Boolean(entry && entry.read_only));
  showTitle();
  controlsState('reading the controls');
  for (const tab of document.querySelectorAll('button.tab')) {
    tab.setAttribute('aria-current', String(tab.dataset.id === id));
  }
  every('overview', state.pollViews, loadOverview);
  every('graph', state.pollViews, loadGraph);
  every('tickets', state.pollViews, loadTickets);
  every('outputs', state.pollViews, loadOutputs);
  state.openSignature = null;
  // An edit to a control that was never set belongs to the project it was made on.
  dirty.autonomy = false;
  dirty.pacing = false;
  dirty.model_fallback = false;
  dirty.ladder_changes = false;
  every('decisions', state.pollViews, loadDecisions);
  every('changes', state.pollViews, loadChanges);
  every('waiting', state.pollViews, loadWaiting);
  every('run', state.pollViews, loadRun);
  for (const [name, load] of Object.entries(VIEW_LOADERS)) every(name, state.pollViews, load);
  markViews();
  showGraph();
  startTail();
}

// --- the overview -------------------------------------------------------------------------------

async function loadOverview() {
  const project = state.project;
  if (!project) return;
  // The render is inside the try with the fetch: a panel that silently keeps saying "loading"
  // tells the owner nothing, so whatever went wrong is shown in its place.
  try {
    const view = await get(`/api/projects/${encodeURIComponent(project)}/overview`);
    // A tab switched while this poll was out: the view is another project's.
    if (!view || project !== state.project) return;
    state.frontierFailure = null;
    renderOverview(view, project);
  } catch (failure) {
    if (project !== state.project) return;
    replace(document.getElementById('overview-body'), [errorState(failure)]);
    // The board's frontier column is this read, so the board says it failed too.
    state.frontierFailure = { project, message: String(failure.message || failure) };
    renderBoard();
  }
}

function renderOverview(view, project) {
  const window_ = view.window || {};
  const objectives = view.objectives || [];
  const resources = view.resources || {};
  const cpu = resources.cpu;
  const ram = resources.ram;
  const gpus = resources.gpus;
  const counts = Object.entries(view.counts || {}).filter(([, count]) => count);
  const parts = [];
  // The position memo leads the overview while it is the owner's to read (ticket 29): its verdicts in
  // a line, then the memo itself, sanitized like every other markdown the ledger holds.
  if (view.position && view.position.first) {
    const memo = view.position;
    // One verdict per objective (decision 17), in place of the goal's: `O1 uncertain (revised target 0.83), O2 reachable`.
    parts.push(
      subhead('position memo'),
      el('p', { class: 'memo-line', text: `feasibility ${memo.feasibility}, objectives ${memo.verdicts}; ${memo.cited} prior work cited, ${memo.dropped} dropped. Read ${memo.path} before the grill.` }),
      el('details', { class: 'memo', open: '' }, [el('summary', { text: 'the memo' }), renderMarkdown(view.position.text, 'research/POSITION.md')]),
      el('hr', { class: 'rule' }),
    );
  }
  parts.push(
    fields([
      ['project', view.path || view.project],
      ['harness', view.harness_tag],
      ['phase', view.phase || 'not started'],
      ['autonomy', view.autonomy],
      ['radius', view.radius],
      ['window', window_.paused ? `paused (${window_.window || 'unknown'}) until ${window_.resets_at || 'unknown'}` : (window_.action || 'normal')],
      ['five hour', window_.five_hour],
      ['seven day', window_.seven_day],
      ['fable', window_.fable],
      // What `cheap_at` costs each launch (decision 16), beside the hold line of decision 15.
      ['stepping down', window_.stepping_down],
      ['hold', view.hold ? view.hold.line : null],
      // The objectives' statuses, each goal with its best kept value (decision 17); GOAL.json is read by nobody (ticket 87).
      ['objectives', objectives.length
        ? objectives.map((objective) => `${objective.id} ${objective.status}${objective.metric === null ? '' : ` (goal ${objective.metric}${objective.best === null || objective.best === undefined ? '' : ` best ${objective.best}`}${objective.reached ? ' reached' : ''})`}`).join(', ')
        : 'none recorded'],
      // The stopping rule and the budgets (ticket 87).
      ['stopping', view.stopping ? `${view.stopping.line}${view.stopping.spent.length ? `; spent: ${view.stopping.spent.join(', ')}` : ''}` : null],
      ['cpu slot', cpu ? `loadavg1 ${cpu.loadavg1} of ${cpu.nproc}, ${cpu.free_cores.length} cores free, ${cpu.free ? 'free' : 'full'}` : null],
      ['ram slot', ram ? `${gib(ram.free_bytes)} free, ${gib(ram.committed_bytes)} committed` : null],
      ['gpu slots', gpus ? (gpus.length ? `${gpus.filter((gpu) => gpu.free).length} free of ${gpus.length}` : 'none detected (CPU-only)') : null],
    ]),
    el('hr', { class: 'rule' }),
  );
  parts.push(el('div', { class: 'chips' }, counts.length
    ? counts.map(([status, count]) => el('span', { class: `chip s-${status}`, text: `${status} ${count}` }))
    : [emptyState('no ticket has been written yet')]));
  parts.push(el('hr', { class: 'rule' }));
  // The four counts of a wave, side by side while they fit: none of them is stretched across the
  // page to hold four short columns, and each says in words what a count of zero means.
  const frontierRows = (view.frontier || []).map((entry) => [entry.id, entry.kind, entry.difficulty, entry.role, entry.title]);
  // The board's frontier column is this list, the conductor's own, rather than a second guess at it.
  const frontier = (view.frontier || []).map((entry) => String(entry.id));
  if (state.frontierFor !== project || frontier.join(',') !== state.frontier.join(',')) {
    state.frontier = frontier;
    state.frontierFor = project;
    renderBoard();
  }
  const runningRows = (view.running || []).map((entry) => [entry.id, entry.kind, entry.attempt, entry.role, entry.title]);
  const jobRows = (view.jobs || []).map((job) => [job.id, job.ticket, job.status, job.unit || job.backend]);
  // `blocking` is the scope a decision pauses ("subgraph" or "all"), not a list of ids.
  const decisionRows = (view.decisions || []).map((entry) => [entry.id, entry.title, entry.blocking || '', entry.awaits === 'decider' ? 'the decider' : 'the owner']);
  parts.push(el('div', { class: 'grid panes' }, [
    el('div', {}, [
      subhead('frontier', frontierRows.length),
      tableOrNone(['id', 'kind', 'd', 'role', 'title'], frontierRows,
        'no ticket is ready to launch: every open ticket is waiting on another', TICKET_COLUMNS),
    ]),
    el('div', {}, [
      subhead('running', runningRows.length),
      tableOrNone(['id', 'kind', 'attempt', 'role', 'title'], runningRows, 'no worker is running', TICKET_COLUMNS),
    ]),
    el('div', {}, [
      subhead('jobs', jobRows.length),
      tableOrNone(['id', 'ticket', 'status', 'unit'], jobRows, 'no job has been queued', ['short', 'short', 'short', 'text']),
    ]),
    el('div', {}, [
      subhead('open decisions', decisionRows.length),
      tableOrNone(['id', 'title', 'blocking', 'asks'], decisionRows,
        'no decision is waiting for an answer', ['short', 'text', 'short', 'short']),
    ]),
  ]));
  if ((view.problems || []).length) {
    parts.push(subhead('problems', view.problems.length));
    parts.push(el('ul', { class: 'problems' }, view.problems.map((problem) => el('li', { text: problem }))));
  }
  replace(document.getElementById('overview-body'), parts);
}

// --- the graph ------------------------------------------------------------------------------------

// The graph section, the ticket page, and the log tail share one area of the page and show one at
// a time: a click on a graph node opens the ticket it names, and a click on one of its logs opens
// the tail. Each "back" reveals the view underneath it.
function showGraph() {
  document.getElementById('graph').hidden = false;
  document.getElementById('ticket').hidden = true;
  document.getElementById('logs').hidden = true;
  stopLog();
  state.ticket = null;
  buildIndex();
  // The graph may have changed while the ticket page covered it, and a hidden drawing cannot be
  // measured, so it is drawn now that it can be seen.
  drawGraph();
}

function showTicket() {
  document.getElementById('graph').hidden = true;
  document.getElementById('ticket').hidden = false;
  document.getElementById('logs').hidden = true;
  stopLog();
  buildIndex();
}

async function loadGraph() {
  if (!state.project) return;
  try {
    const svg = await getText(`/api/projects/${encodeURIComponent(state.project)}/graph.svg`, 'graph');
    if (svg === null) return;
    // A project with no tickets answers with an empty canvas, which draws as nothing at all: the
    // panel says so instead of standing blank.
    if (EMPTY_CANVAS.test(svg)) {
      state.graphSource = null;
      replace(document.getElementById('graph-body'), [emptyState('no ticket yet: the graph is drawn once the first one is written')]);
      return;
    }
    state.graphSource = svg;
    drawGraph();
  } catch (failure) {
    replace(document.getElementById('graph-body'), [errorState(failure)]);
  }
}

// --- the graph's hover card ------------------------------------------------------------------------
//
// A node carries its ticket id and nothing else, which is all the layout has room for. The rest of
// what the owner wants to know before clicking (the title, where the ticket stands, who runs it,
// what it waits on) is read from the tickets endpoint and shown beside the node. Hover is not the
// only way to it: the node is a link, so the keyboard reaches it and a click opens the whole page.

async function loadTickets() {
  const project = state.project;
  if (!project) return;
  try {
    const view = await get(`/api/projects/${encodeURIComponent(project)}/tickets`, 'tickets');
    if (!view || project !== state.project) return;
    // A list for a project that had none drawn yet (an empty one included), or one whose tickets
    // moved, is drawn at once rather than at the graph's next poll: the board and the graph are one
    // picture of it and must agree.
    const changed = state.ticketsFor !== project || ticketsSignature(view) !== ticketsSignature(state.tickets);
    state.tickets = view;
    state.ticketsFor = project;
    state.ticketsFailure = null;
    if (changed) {
      drawGraph();
      renderBoard();
    }
  } catch (failure) {
    if (project !== state.project) return;
    // The board is this read, so the board says it failed; the graph is drawn either way.
    state.ticketsFailure = { project, message: String(failure.message || failure) };
    renderBoard();
  }
}

// What the board and the graph draw from a ticket: where it stands, what it is called, and what it waits on.
function ticketsSignature(tickets) {
  return (tickets || []).map((entry) => `${entry.id}:${entry.status}:${entry.title}:${(entry.blocked_by || []).join(',')}`).join('|');
}

// The tickets belong to this project, or there are none to draw yet.
function ticketsHere() {
  return state.ticketsFor === state.project ? (state.tickets || []) : [];
}

function ticketById(id) {
  return ticketsHere().find((entry) => String(entry.id) === String(id));
}

// The id a graph node's link names, from its `#ticket/<id>`.
function ticketIdOf(link) {
  return link.getAttribute('href').slice('#ticket/'.length);
}

// A space token of the stylesheet, in pixels, for the few distances the script has to work out itself.
function space(step) {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(`--space-${step}`)) || 0;
}

function nodeCard(id) {
  const ticket = ticketById(id);
  const card = document.getElementById('node-card');
  if (!ticket) {
    replace(card, [el('p', { class: 'node-title', text: `ticket ${id}` })]);
    return card;
  }
  const blocked = (ticket.blocked_by || []).length ? `waits on ${ticket.blocked_by.join(', ')}` : 'waits on nothing';
  replace(card, [
    el('p', { class: 'node-title', text: `#${ticket.id} ${ticket.title || ''}` }),
    el('p', { class: 'node-line' }, [
      el('span', { class: `chip s-${ticket.status}`, text: ticket.status || 'unknown' }),
      el('span', { class: 'node-dim', text: [ticket.kind, ticket.role, ticket.difficulty ? `d${ticket.difficulty}` : null].filter(Boolean).join('  ') }),
    ]),
    el('p', { class: 'node-dim', text: blocked }),
  ]);
  return card;
}

// The node the card is open for, so that a scroll moves the card with it rather than dropping it:
// scrolling to read a long graph is not the same as leaving the node.
let cardFor = null;

function placeNodeCard(link) {
  const card = document.getElementById('node-card');
  // Beside the node, and inside the window: a card that runs off the right edge is worse than one
  // that sits to the left of what it describes.
  const gap = space(3);
  const at = link.getBoundingClientRect();
  const left = Math.min(at.right + gap, window.innerWidth - card.offsetWidth - gap);
  card.style.left = `${Math.max(gap, left)}px`;
  card.style.top = `${Math.max(gap, at.top + window.scrollY - space(1))}px`;
}

function showNodeCard(link) {
  const card = nodeCard(ticketIdOf(link));
  card.hidden = false;
  cardFor = link;
  placeNodeCard(link);
}

function hideNodeCard() {
  document.getElementById('node-card').hidden = true;
  cardFor = null;
}

function followNodeCard() {
  if (!cardFor) return;
  // The graph is redrawn on its own poll, which replaces the node the card was opened from.
  if (!cardFor.isConnected) hideNodeCard();
  else placeNodeCard(cardFor);
}

// `dag.svg` sizes its canvas by the grid it lays out on, which leaves the gap below the last row
// inside the picture. The drawing is measured here and the canvas trimmed to it, so the panel is
// the height of the graph rather than the height of the grid.
function trimCanvas(svg) {
  let drawn = null;
  try {
    drawn = svg.getBBox();
  } catch (failure) {
    // A drawing that is not laid out has no box in some browsers; it keeps the canvas it came with.
    return;
  }
  if (!drawn || !drawn.width || !drawn.height) return;
  const pad = space(2);
  svg.setAttribute('viewBox', `${drawn.x - pad} ${drawn.y - pad} ${drawn.width + pad * 2} ${drawn.height + pad * 2}`);
}

// --- the graph, drawn again ------------------------------------------------------------------------
//
// The server decides the graph: which ticket sits in which layer, in what order across it, and which
// node is on the frontier. That is the part worth having in one tested place, and it stays there.
// What it cannot know is how much room a browser has, so its nodes are a box of 120 by 36. Here the
// same layout is drawn again as the owner asked for it: a circle per ticket with its number inside,
// colored by where it stands, the rest on hover. Reading titles is the board's job; the graph is
// for seeing the shape of what waits on what.
//
// Nothing is re-laid-out: each node keeps its column and its row, each edge keeps its ends, and the
// fill the server chose is carried over untouched, so the stylesheet's rules (and the test that
// holds them to `dag.STATUS_COLOR`) still decide every color.

const SVG_NS = 'http://www.w3.org/2000/svg';
const NODE = { w: 44, h: 44, gx: 40, gy: 46, r: 19 };

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value !== null && value !== undefined) node.setAttribute(name, String(value));
  }
  return node;
}

// The grid the server drew on, read back from the drawing itself rather than assumed: the node box
// is a rect's own size, and the pitch is the smallest step between two columns or two rows.
function gridOf(rects) {
  const pitch = (values) => {
    const sorted = [...new Set(values)].sort((a, b) => a - b);
    const steps = sorted.slice(1).map((value, index) => value - sorted[index]).filter((step) => step > 0);
    return steps.length ? Math.min(...steps) : 0;
  };
  const first = rects[0];
  return {
    w: Number(first.getAttribute('width')),
    h: Number(first.getAttribute('height')),
    px: pitch(rects.map((rect) => Number(rect.getAttribute('x')))),
    py: pitch(rects.map((rect) => Number(rect.getAttribute('y')))),
  };
}

function redrawGraph(source) {
  const rects = [...source.querySelectorAll('a rect')];
  if (!rects.length) return null;
  const grid = gridOf(rects);
  if (!grid.w || !grid.h) return null;

  // Where each node lands in the new grid, by the column and row the old one was in.
  const landing = (x, y) => ({
    x: (grid.px ? Math.round(x / grid.px) : 0) * (NODE.w + NODE.gx),
    y: (grid.py ? Math.round(y / grid.py) : 0) * (NODE.h + NODE.gy),
  });

  const drawn = svgEl('svg', { xmlns: SVG_NS });
  drawn.appendChild((() => {
    const defs = svgEl('defs');
    // Two heads: the everyday one, and the one an edge takes while its ticket is pointed at.
    for (const [id, cls] of [['arrow', 'head'], ['arrow-hot', 'head hot']]) {
      const marker = svgEl('marker', { id, viewBox: '0 0 10 10', refX: 9, refY: 5,
                                       markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' });
      marker.appendChild(svgEl('path', { d: 'M0,1L9,5L0,9z', class: cls }));
      defs.appendChild(marker);
    }
    return defs;
  })());

  // Which ticket sits at each place, so an edge can say which two it joins.
  const at = new Map();
  for (const link of source.querySelectorAll('a')) {
    const rect = link.querySelector('rect');
    if (!rect) continue;
    const spot = landing(Number(rect.getAttribute('x')), Number(rect.getAttribute('y')));
    at.set(`${spot.x},${spot.y}`, ticketIdOf(link));
  }

  // The edges first, so a node is never drawn under one of its own lines. An edge runs from the
  // bottom of the ticket that blocks to the top of the one that waits.
  for (const line of source.querySelectorAll('line')) {
    const from = landing(Number(line.getAttribute('x1')) - grid.w / 2, Number(line.getAttribute('y1')) - grid.h);
    const to = landing(Number(line.getAttribute('x2')) - grid.w / 2, Number(line.getAttribute('y2')));
    const x1 = from.x + NODE.w / 2;
    const y1 = from.y + NODE.h / 2 + NODE.r;
    const x2 = to.x + NODE.w / 2;
    const y2 = to.y + NODE.h / 2 - NODE.r - 2;
    const bend = Math.max(14, (y2 - y1) / 2);
    drawn.appendChild(svgEl('path', {
      class: 'edge',
      'data-from': at.get(`${from.x},${from.y}`),
      'data-to': at.get(`${to.x},${to.y}`),
      d: `M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}`,
      'marker-end': 'url(#arrow)',
    }));
  }

  for (const link of source.querySelectorAll('a')) {
    const rect = link.querySelector('rect');
    if (!rect) continue;
    const id = ticketIdOf(link);
    const ticket = ticketById(id) || {};
    const spot = landing(Number(rect.getAttribute('x')), Number(rect.getAttribute('y')));
    const cx = spot.x + NODE.w / 2;
    const cy = spot.y + NODE.h / 2;
    const node = svgEl('a', { href: link.getAttribute('href'), class: 'node', 'data-id': id,
                              'aria-label': `ticket ${id}${ticket.title ? `: ${ticket.title}` : ''}${ticket.status ? `, ${ticket.status}` : ''}` });
    node.appendChild(svgEl('circle', {
      cx, cy, r: NODE.r,
      // The server's own choice of fill, carried over: the stylesheet maps it to the palette.
      fill: rect.getAttribute('fill'),
      // The ring repeats where the ticket stands, so the fill is not carrying it alone.
      class: `ring s-${ticket.status || 'unknown'}`,
    }));
    const number = svgEl('text', { class: 'node-id', x: cx, y: cy + 4, 'text-anchor': 'middle' });
    number.textContent = id;
    node.appendChild(number);
    drawn.appendChild(node);
  }
  return drawn;
}

// --- what a ticket waits on, and what waits on it --------------------------------------------------
//
// The dependencies of one ticket at a time, rather than of all of them at once: the board's columns
// are where tickets stand, not the order they depend in, so every edge drawn across them would cross
// the others. Pointing at a ticket, on the board or on the graph, marks the tickets it waits on and
// the ones waiting on it, and dims the rest.

function relationsOf(id) {
  const self = ticketById(id);
  const waitsOn = new Set(((self && self.blocked_by) || []).map(String));
  const waitedOnBy = new Set(ticketsHere().filter((entry) => (entry.blocked_by || []).map(String).includes(String(id))).map((entry) => String(entry.id)));
  return { waitsOn, waitedOnBy };
}

function markRelations(container, id) {
  const { waitsOn, waitedOnBy } = relationsOf(id);
  container.classList.add('relating');
  for (const item of container.querySelectorAll('[data-id]')) {
    const other = String(item.dataset.id);
    item.classList.toggle('is-self', other === String(id));
    item.classList.toggle('is-blocker', waitsOn.has(other));
    item.classList.toggle('is-waiting', waitedOnBy.has(other));
    const note = item.querySelector('.card-rel');
    if (note) {
      if (waitsOn.has(other)) note.textContent = `#${id} waits on this`;
      else if (waitedOnBy.has(other)) note.textContent = `waits on #${id}`;
      else note.textContent = '';
    }
  }
  for (const edge of container.querySelectorAll('.edge')) {
    edge.classList.toggle('is-related', edge.dataset.from === String(id) || edge.dataset.to === String(id));
  }
}

function clearRelations(container) {
  container.classList.remove('relating');
  for (const item of container.querySelectorAll('.is-self, .is-blocker, .is-waiting, .is-related')) {
    item.classList.remove('is-self', 'is-blocker', 'is-waiting', 'is-related');
  }
  for (const note of container.querySelectorAll('.card-rel')) note.textContent = '';
}

// Pointer and keyboard alike: a move between two parts of the same item is not leaving it.
function wireRelations(container, selector, entered, left) {
  for (const type of ['mouseover', 'focusin']) {
    container.addEventListener(type, (event) => {
      const item = event.target.closest(selector);
      if (!item) return;
      markRelations(container, item.dataset.id);
      if (entered) entered(item);
    });
  }
  for (const type of ['mouseout', 'focusout']) {
    container.addEventListener(type, (event) => {
      const item = event.target.closest(selector);
      if (!item) return;
      const to = event.relatedTarget;
      if (to && item.contains(to)) return;
      clearRelations(container);
      if (left) left(item);
    });
  }
}

// --- the board ---------------------------------------------------------------------------------------
//
// Every ticket as a card, in a column for where it stands. Two of the columns are the server's
// answers rather than rules worked out again here: the frontier is the overview's (what puts an open
// ticket on it is the conductor's rule, and it lives in one place), and a decision ticket waiting on
// the owner is the decisions view's. The rest is the ticket's own status.

const COLUMNS = [
  ['needs you', (ticket, known) => known.forOwner.has(String(ticket.id)) || ['needs_human', 'failed', 'blocked'].includes(ticket.status)],
  ['frontier', (ticket, known) => known.frontier.has(String(ticket.id))],
  ['waiting', (ticket) => ticket.status === 'open'],
  ['running', (ticket) => ticket.status === 'running'],
  ['done', (ticket) => ['done', 'accepted'].includes(ticket.status)],
  ['parked', (ticket) => ticket.status === 'parked'],
];
// The order the columns are read in, left to right, which is not the order they are tested in.
const COLUMN_ORDER = ['waiting', 'frontier', 'running', 'needs you', 'done', 'parked'];

function columnOf(ticket, known) {
  const found = COLUMNS.find(([, belongs]) => belongs(ticket, known));
  // A status the board has no column for is still a ticket the owner should see: it waits.
  return found ? found[0] : 'waiting';
}

function renderBoard() {
  const body = document.getElementById('board-body');
  if (!body) return;
  const project = state.project;
  const failed = [state.ticketsFailure, state.frontierFailure].find((failure) => failure && failure.project === project);
  if (state.ticketsFor !== project || state.frontierFor !== project) {
    // What is not read yet is said as such; what failed to be read is said as that.
    replace(body, [failed ? errorState(failed.message) : loadingState('reading the tickets and the frontier')]);
    return;
  }
  const tickets = ticketsHere();
  if (!tickets.length) {
    replace(body, [emptyState('no ticket yet: the board fills once the first one is written')]);
    return;
  }
  const { project: decisionsFor, list } = state.openDecisions;
  const known = {
    frontier: new Set(state.frontier),
    forOwner: new Set(decisionsFor === project ? list.filter((entry) => entry.awaits === 'owner').map((entry) => String(entry.id)) : []),
  };
  const placed = new Map(COLUMN_ORDER.map((name) => [name, []]));
  for (const ticket of tickets) placed.get(columnOf(ticket, known)).push(ticket);
  const columns = COLUMN_ORDER.map((name) => {
    const cards = placed.get(name).map((ticket) => {
      const card = el('button', { type: 'button', class: `card s-${ticket.status || 'unknown'}`, 'data-id': String(ticket.id),
                                  'aria-label': `ticket ${ticket.id}: ${ticket.title || ''}, ${ticket.status || ''}` }, [
        el('span', { class: 'card-top' }, [
          el('span', { class: 'card-id', text: `#${ticket.id}` }),
          el('span', { class: 'card-meta', text: [ticket.kind, ticket.difficulty ? `d${ticket.difficulty}` : null].filter(Boolean).join(' ') }),
        ]),
        el('span', { class: 'card-title', text: ticket.title || '', title: ticket.title || null }),
        el('span', { class: 'card-foot', text: [ticket.role, ticket.status].filter(Boolean).join(' \u00b7 ') }),
        // Which way a dependency runs, while a related ticket is pointed at. Not a live region: one
        // pointer move would have a screen reader read out every card it touches.
        el('span', { class: 'card-rel' }),
      ]);
      card.addEventListener('click', () => openTicket(String(ticket.id)));
      return card;
    });
    return el('div', { class: 'column', 'data-column': name }, [
      el('h3', { class: 'sub' }, [el('span', { text: name }), el('span', { class: 'count', text: String(cards.length) })]),
      cards.length ? el('div', { class: 'cards' }, cards) : el('p', { class: 'state', text: 'none' }),
    ]);
  });
  replace(body, [el('div', { class: 'columns' }, columns)]);
}

// --- board or graph --------------------------------------------------------------------------------

const VIEWS = ['board', 'graph'];

function setTicketView(choice) {
  const view = VIEWS.includes(choice) ? choice : 'board';
  document.getElementById('board-body').hidden = view !== 'board';
  document.getElementById('graph-body').hidden = view !== 'graph';
  markChoice(document.getElementById('ticket-view'), view);
  remember(STORE.view, view);
  if (view === 'graph') drawGraph();
  else renderBoard();
}

function wireTicketView() {
  segmented(document.getElementById('ticket-view'), VIEWS.map((name) => ({ name, label: name })), setTicketView);
  wireRelations(document.getElementById('board-body'), '.card[data-id]');
  setTicketView(remembered(STORE.view) || 'board');
}

// A set of buttons of which one is chosen, the way the header's theme and the tickets' view are.
function segmented(group, choices, pick) {
  replace(group, choices.map(({ name, label, title }) => {
    const button = el('button', { type: 'button', class: 'action', text: label, 'data-choice': name, title: title || null });
    button.addEventListener('click', () => pick(name));
    return button;
  }));
}

function markChoice(group, chosen) {
  for (const button of group.querySelectorAll('button[data-choice]')) {
    button.setAttribute('aria-current', String(button.dataset.choice === chosen));
  }
}

// The graph can be seen: its view is chosen, the ticket page is not over it, and it is not folded.
function graphShown() {
  return document.getElementById('graph-body').getClientRects().length > 0;
}

// The server's SVG, drawn again at a readable size when it can be read back. Its own drawing stands
// if it cannot, so the graph is never lost to a shape this did not expect. A drawing is measured to
// trim its canvas and a hidden one measures as nothing, so a graph that cannot be seen is left until
// it can: choosing the graph view, coming back from a ticket, and unfolding the section all draw it.
function drawGraph() {
  if (!state.graphSource || !graphShown()) return;
  const body = document.getElementById('graph-body');
  body.innerHTML = state.graphSource;
  hideNodeCard();
  const source = body.querySelector('svg');
  if (!source) return;
  let shown = source;
  try {
    const redrawn = redrawGraph(source);
    if (redrawn) {
      replace(body, [redrawn]);
      shown = redrawn;
    }
  } catch (failure) {
    body.innerHTML = state.graphSource;
    shown = body.querySelector('svg');
  }
  if (shown) trimCanvas(shown);
}

function wireGraph() {
  const body = document.getElementById('graph-body');
  // A node is a circle and a number inside one link; `wireRelations` treats a move between the two
  // as staying on the node, so the card goes only when the pointer leaves the link.
  wireRelations(body, 'a.node[data-id]', showNodeCard, hideNodeCard);
  window.addEventListener('scroll', followNodeCard, { passive: true });
  window.addEventListener('resize', followNodeCard);
}

// The SVG's `<a href="#ticket/<id>">` is not meant to navigate: this is a single-page app, so a
// click on it is caught here and turned into `openTicket` instead. The listener is on the
// container, not the links, because `innerHTML` replaces the links themselves on every poll.
document.getElementById('graph-body').addEventListener('click', (event) => {
  const link = event.target.closest('a[href^="#ticket/"]');
  if (!link) return;
  event.preventDefault();
  openTicket(ticketIdOf(link));
});

// --- the ticket page ------------------------------------------------------------------------------

async function openTicket(id) {
  if (!state.project) return;
  state.ticket = id;
  showTicket();
  const body = document.getElementById('ticket-body');
  // The ticket already on the page is left where it is while it is read again; another one's page
  // says it is being read rather than showing the ticket the owner just clicked away from.
  if (body.dataset.ticket !== id) replace(body, [loadingState(`reading ticket ${id}`)]);
  try {
    const view = await get(`/api/projects/${encodeURIComponent(state.project)}/tickets/${encodeURIComponent(id)}`);
    // A second click before this one's fetch returned must not let the first ticket's view land
    // on the page after the page has already moved on to another ticket.
    if (view && state.ticket === id) {
      body.dataset.ticket = id;
      renderTicket(view);
    }
  } catch (failure) {
    if (state.ticket === id) replace(body, [errorState(failure)]);
  }
}

function needsHumanLine(entry) {
  const question = entry.question || 'no question was journaled';
  return entry.note ? `${entry.note}: ${question}` : question;
}

function renderTicket(view) {
  const f = view.fields || {};
  const parts = [
    fields([
      ['id', f.id],
      ['title', f.title],
      ['kind', f.kind],
      ['status', f.status],
      ['difficulty', f.difficulty],
      ['role', f.role],
      ['blocked by', (f.blocked_by || []).length ? f.blocked_by.join(', ') : 'nothing'],
      // Why it waits for a person, with the note its `reason` reads as: "at the ladder's top rung"
      // for a ticket the escalation chain left with nowhere to climb (decision 16).
      ...(view.needs_human ? [['needs a person', needsHumanLine(view.needs_human)]] : []),
    ]),
    ticketActions(f),
    el('div', { id: 'ticket-decision' }),
    el('hr', { class: 'rule' }),
    subhead('body'),
    renderMarkdown(view.body, 'research/tickets/'),
    subhead('context pack', (view.context_pack || []).length),
    listOrNone(view.context_pack, (path) => el('li', { text: path }), 'no file was packed for this ticket'),
    subhead('latest result'),
    view.result ? resultFields(view.result) : emptyState('no attempt has returned a result yet'),
    subhead('findings', (view.findings || []).length),
    listOrNone(view.findings, (finding) => el('li', { text: finding.text }), 'no finding is recorded against this ticket'),
    subhead('session logs', (view.sessions || []).length),
    logList(view.sessions, 'session',
      (entry) => `attempt ${entry.attempt}${entry.resume ? ` (${entry.resume})` : ''}${entry.label ? ` · ${entry.label}` : ''}`,
      'no worker has been launched for this ticket'),
    subhead('job logs', (view.jobs || []).length),
    logList(view.jobs, 'job', (entry) => `${entry.id} (${entry.status})`, 'no job has been queued for this ticket'),
  ];
  replace(document.getElementById('ticket-body'), parts);
  state.ticketDecisionSignature = null;
  renderTicketDecision();
}

// A decision ticket opened from the board or the graph can be answered where it is, with the same
// card and the same form the decisions panel draws: one way to answer, shown in two places, sharing
// the draft the owner has typed. The form is drawn again only when the decision itself changed, so
// a poll never takes it out from under the cursor.
function renderTicketDecision() {
  const slot = document.getElementById('ticket-decision');
  if (!slot || state.ticket === null || document.getElementById('ticket').hidden) return;
  const { project, list } = state.openDecisions;
  const decision = project === state.project ? list.find((entry) => String(entry.id) === String(state.ticket)) : null;
  const signature = JSON.stringify([project, state.ticket, decision || null]);
  if (signature === state.ticketDecisionSignature) return;
  state.ticketDecisionSignature = signature;
  replace(slot, decision ? [el('hr', { class: 'rule' }), subhead('decision'), decisionCard(decision, project)] : []);
}

// `short` cuts a result's value to what the row holds; the whole of it stays in the field's title.
function resultFields(result) {
  return fields(Object.entries(result).map(([key, value]) => [key, short(value), value]));
}

function listOrNone(items, render, empty, className) {
  return (items || []).length ? el('ul', { class: className || null }, items.map(render)) : emptyState(empty);
}

function logList(entries, kind, label, empty) {
  return listOrNone(entries, (entry) => {
    const button = el('button', { type: 'button', class: 'action', text: label(entry) });
    button.addEventListener('click', () => openLog(kind, entry.id));
    return el('li', {}, [button]);
  }, empty);
}

// --- the log tail -----------------------------------------------------------------------------------

// The tick's log is the only one whose kind and id are the same word, and "tick tick" reads as a
// stutter rather than as a name.
function logName(kind, id) {
  return kind === id ? kind : `${kind} ${id}`;
}

function stopLog() {
  if (state.timers.logs) {
    clearInterval(state.timers.logs);
    delete state.timers.logs;
  }
  state.log = null;
}

function openLog(kind, id) {
  if (!state.project) return;
  document.getElementById('graph').hidden = true;
  document.getElementById('ticket').hidden = true;
  document.getElementById('logs').hidden = false;
  buildIndex();
  state.log = { kind, id, since: null, written: false };
  document.getElementById('logs-tail').textContent = '';
  noteText('logs-note', `${logName(kind, id)}: reading`);
  every('logs', state.pollJournal, pollLog);
}

async function pollLog() {
  const current = state.log;
  if (!current) return;
  const since = current.since === null ? 0 : current.since;
  // Not `encodeURIComponent`: a session id like `3/1/resume-1` must reach the route with its
  // slashes literal, since the server matches the path itself rather than a decoded one.
  const path = `/api/projects/${encodeURIComponent(state.project)}/logs/${current.kind}/${current.id}?since=${since}`;
  let tail;
  try {
    tail = await get(path, `log:${current.kind}:${current.id}`);
  } catch (failure) {
    noteText('logs-note', String(failure.message || failure), true);
    return;
  }
  if (!tail || current !== state.log) return;
  const pre = document.getElementById('logs-tail');
  if (tail.truncated) {
    pre.textContent = '';
    current.written = false;
  }
  current.since = tail.next;
  if (tail.text) {
    // The words of the empty case are the pre's own text until the first byte arrives, so they are
    // cleared rather than left above the log.
    if (!current.written) pre.textContent = '';
    current.written = true;
    pre.textContent += tail.text;
  } else if (!current.written) {
    pre.textContent = tail.exists ? 'this log exists but nothing has been written to it yet' : 'nothing has been written to this log yet';
  }
  noteText('logs-note', `${logName(current.kind, current.id)}: ${tail.exists ? `${tail.size} bytes` : 'nothing written yet'}`);
}

document.getElementById('ticket-back').addEventListener('click', showGraph);
document.getElementById('logs-back').addEventListener('click', () => (state.ticket ? openTicket(state.ticket) : showGraph()));
document.getElementById('tick-log-button').addEventListener('click', () => openLog('tick', 'tick'));

// --- the outputs index (ticket 42) ---------------------------------------------------------------

const CATEGORIES = ['results', 'findings', 'figures', 'dossiers', 'report', 'paper', 'docs'];
const PREVIEWABLE_MARKDOWN = /\.(?:md|markdown)$/i;
const PREVIEWABLE_IMAGE = /\.(?:png|jpe?g|gif|svg|webp)$/i;

function humanSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let value = n;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(1)} ${units[unit]}`;
}

// A download's URL carries the token the same way the page's own polls do: `fetch` and `<img>`
// attach neither a header nor a cookie of their own to a link the owner clicks or a preview opens.
function downloadUrl(path) {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  const query = TOKEN ? `?${new URLSearchParams({ token: TOKEN })}` : '';
  return `/api/projects/${encodeURIComponent(state.project)}/download/${encoded}${query}`;
}

async function loadOutputs() {
  if (!state.project) return;
  try {
    const view = await get(`/api/projects/${encodeURIComponent(state.project)}/outputs`);
    if (view) renderOutputs(view);
  } catch (failure) {
    replace(document.getElementById('outputs-body'), [errorState(failure)]);
  }
}

function renderOutputs(view) {
  const parts = [];
  for (const name of CATEGORIES) {
    const entries = view[name] || [];
    parts.push(subhead(name, entries.length));
    parts.push(listOrNone(entries, (entry) => outputRow(entry), `nothing under ${name} yet`, 'outputs'));
    if (name === 'docs' && (view.site || []).length) parts.push(siteRow(view.site[0]));
  }
  replace(document.getElementById('outputs-body'), parts);
}

// The built documentation site (ticket 51) opens as a site in its own tab, served in a sandbox by
// `site/`. Its link never carries the token: the site's pages are model-written and a script in one
// can read its own URL. The navigation carries the cookie instead; the loopback bind the tunnel uses
// asks no token at all, and on a wide bind a sandboxed page's own requests carry no cookie, so there
// the site renders without its stylesheet.
function siteRow(site) {
  const checks = site.passed === true ? 'every check passed' : site.passed === false ? 'a check failed' : 'no checks recorded';
  return el('p', { class: 'note' }, [
    el('a', { href: `/api/projects/${encodeURIComponent(state.project)}/${site.url}`, target: '_blank', rel: 'noopener', text: 'open the documentation site' }),
    document.createTextNode(` built ${site.built || 'at an unrecorded time'}; ${checks}`),
  ]);
}

function outputRow(entry) {
  const row = el('li', {}, [
    el('a', { href: downloadUrl(entry.path), text: entry.path, title: entry.path }),
    el('span', { class: 'note', text: humanSize(entry.size) }),
  ]);
  if (PREVIEWABLE_MARKDOWN.test(entry.path) || PREVIEWABLE_IMAGE.test(entry.path)) {
    const view = el('button', { type: 'button', class: 'action', text: 'view' });
    view.addEventListener('click', () => openViewer(entry.path));
    row.appendChild(document.createTextNode(' '));
    row.appendChild(view);
  }
  return row;
}

// --- the document viewer (ticket 74) --------------------------------------------------------------
//
// Every Markdown file the dashboard opens, and every image, opens in one native <dialog> placed in
// index.html outside the panels the polls redraw, so a poll never closes it, resets its scroll, or
// replaces what it shows. showModal() makes the page behind inert; Escape closes it and gives focus
// back to whatever opened it, and so does a click on the backdrop. The document zooms with CSS
// `zoom`, which rewraps the text where `transform: scale` would run it past a phone's edge (research
// note 04, section 7); the keys + (or =), -, and 0 step and reset it, and Ctrl, Cmd, and Alt are left
// to the browser, whose own zoom still works on the whole page.

const ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const ZOOM_RESET = ZOOM_STEPS.indexOf(1);
const viewer = {
  zoom: ZOOM_RESET,
  reads: 0, // counts every open and close, so a slow read that a newer one replaced is dropped
  item: null, // { project, id, landed } of the item link the viewer is open on (ticket 110), or null
};

function setZoom(index) {
  viewer.zoom = Math.max(0, Math.min(ZOOM_STEPS.length - 1, index));
  const value = ZOOM_STEPS[viewer.zoom];
  document.getElementById('viewer-doc').style.setProperty('--zoom', String(value));
  document.querySelector('#viewer [data-zoom="reset"]').textContent = `${Math.round(value * 100)}%`;
  remember(STORE.zoom, String(value));
}

// A reference a rendered file makes (an image's `src`, a link's `href`) as a path inside the
// project, relative to that file's own directory, or null for one that leaves the project. `/x` is the
// project's own root. Nothing is normalized away: a `..` above the root refuses the reference
// rather than landing on some other file of the project.
function projectPathOf(fileAt, reference) {
  let path;
  try {
    path = decodeURIComponent(reference.split(/[?#]/)[0]);
  } catch (failure) {
    return null;
  }
  const parts = path.startsWith('/') ? [] : fileAt.split('/').slice(0, -1);
  for (const part of path.split('/')) {
    if (part === '' || part === '.') continue;
    if (part !== '..') parts.push(part);
    else if (parts.length) parts.pop();
    else return null;
  }
  return parts.length ? parts.join('/') : null;
}

const URL_SCHEME = /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i;

// A rendered file's images and links, pointed at the project: a relative image is served from
// the project through the download route, so a report's plots show; an image from anywhere else is
// never fetched, since the page makes no request off the workstation and a model-written URL could
// carry what it read; a relative link to another Markdown file opens it here.
function pointIntoProject(node, fileAt) {
  for (const image of node.querySelectorAll('img[src]')) {
    const source = image.getAttribute('src');
    if (source.startsWith('data:')) continue;
    const path = URL_SCHEME.test(source) ? null : projectPathOf(fileAt, source);
    if (path) {
      image.setAttribute('src', downloadUrl(path));
    } else {
      image.removeAttribute('src');
      image.setAttribute('data-refused', source);
      image.title = `not shown: ${source} is outside the project`;
    }
  }
  for (const link of node.querySelectorAll('a[href]')) {
    const target = link.getAttribute('href');
    if (target.startsWith('#')) continue;
    if (URL_SCHEME.test(target)) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      continue;
    }
    const path = projectPathOf(fileAt, target);
    if (!path) {
      link.removeAttribute('href');
      link.title = `${target} is outside the project`;
      continue;
    }
    link.setAttribute('href', downloadUrl(path));
    if (PREVIEWABLE_MARKDOWN.test(path)) {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        openViewer(path);
      });
    }
  }
  return node;
}

// Open `path`, relative to the project, in the viewer: the one way any view shows a document,
// report, section, or image. `options` comes from an item link (tickets 110 and 111): the `title` the
// bar shows, the heading to `focus` (an objective in OBJECTIVES.md), a plot's `caption`, a table's
// `rows`, and for an item no file holds (a pair of claims, `path` null) its `sides` and `fields`.
async function openViewer(path, options) {
  const opts = options || {};
  const dialog = document.getElementById('viewer');
  const body = document.getElementById('viewer-body');
  const shown = document.getElementById('viewer-doc');
  const read = ++viewer.reads;
  const download = document.getElementById('viewer-download');
  document.getElementById('viewer-title').textContent = opts.title || path;
  if (!path) {
    download.removeAttribute('href');
    replace(shown, [sidesOf(opts.sides), fields(opts.fields || [])]);
    if (!dialog.open) dialog.showModal();
    body.scrollTop = 0;
    return;
  }
  download.href = downloadUrl(path);
  replace(shown, [loadingState(`reading ${path}`)]);
  if (!dialog.open) dialog.showModal();
  if (opts.rows) {
    const [head, ...rows] = opts.rows;
    const table = opts.unreadable ? emptyState(`${path} could not be read`) : tableOrNone(head || [], rows, 'the table has no rows');
    replace(shown, [table, ...captionOf(opts.caption)]);
    return;
  }
  if (PREVIEWABLE_IMAGE.test(path)) {
    replace(shown, [el('img', { src: downloadUrl(path), alt: opts.title || path }), ...captionOf(opts.caption)]);
    return;
  }
  try {
    const headers = TOKEN ? { 'X-Wayline-Token': TOKEN } : {};
    const response = await fetch(downloadUrl(path), { cache: 'no-store', headers });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    const text = await response.text();
    if (read !== viewer.reads) return;
    replace(shown, [renderMarkdown(withoutFrontmatter(text), path)]);
    body.scrollTop = 0;
    if (opts.focus) focusHeading(shown, opts.focus);
  } catch (failure) {
    if (read === viewer.reads) replace(shown, [errorState(failure)]);
  }
}

// A ticket file opens on its body: the YAML frontmatter above it is the ticket page's fields, not prose.
function withoutFrontmatter(text) {
  const found = /^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/.exec(text);
  return found ? text.slice(found[0].length) : text;
}

// Two claims side by side, each with where it stands: a contradiction or a merge (ticket 111). The
// columns stack on a phone.
function sidesOf(sides) {
  return el('div', { class: 'sides' }, (sides || []).map((side) => {
    const where = [side.section, side.heading ? `under "${side.heading}"` : null].filter(Boolean).join(', ');
    return el('div', { class: 'side' }, [
      el('p', { class: 'side-head' }, [el('strong', { text: side.id }), document.createTextNode(where ? ` in ${where}` : '')]),
      el('blockquote', { text: side.text || 'its passage could not be read' }),
    ]);
  }));
}

// A plot's or a table's three explanations, under it.
function captionOf(caption) {
  if (!caption) return [];
  return [fields([['purpose', caption.purpose], ['data', caption.data], ['what it shows', caption.shows]])];
}

// The heading an item link names inside its file, scrolled to the top: an id (`O3` in OBJECTIVES.md, `R4` in
// REPORT.md) leading its heading, or a passage's heading as written. A heading that is the name exactly wins over one
// it only leads, and one under the file's title over the title, so a passage under "Results" lands at its `## Results`.
function focusHeading(node, id) {
  const headings = [...node.querySelectorAll('h2, h3, h4'), ...node.querySelectorAll('h1')];
  const exact = headings.find((candidate) => candidate.textContent.trim() === id);
  const heading = exact || headings.find((candidate) => {
    const text = candidate.textContent.trim();
    return text.startsWith(`${id} `) || text.startsWith(`${id}.`) || text.startsWith(`${id}:`);
  });
  if (heading && heading.scrollIntoView) heading.scrollIntoView({ block: 'start' });
}

// What the viewer says for an item link that names nothing: one line, not an error page.
function viewerNotFound(id, line) {
  const dialog = document.getElementById('viewer');
  viewer.reads += 1;
  document.getElementById('viewer-title').textContent = id;
  document.getElementById('viewer-download').removeAttribute('href');
  replace(document.getElementById('viewer-doc'), [emptyState(line || `${id}: not found in this project`)]);
  if (!dialog.open) dialog.showModal();
}

function wireViewer() {
  const dialog = document.getElementById('viewer');
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  dialog.querySelector('[data-zoom="in"]').addEventListener('click', () => setZoom(viewer.zoom + 1));
  dialog.querySelector('[data-zoom="out"]').addEventListener('click', () => setZoom(viewer.zoom - 1));
  dialog.querySelector('[data-zoom="reset"]').addEventListener('click', () => setZoom(ZOOM_RESET));
  dialog.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest('input, textarea, select')) return;
    if (event.key === '+' || event.key === '=') setZoom(viewer.zoom + 1);
    else if (event.key === '-' || event.key === '_') setZoom(viewer.zoom - 1);
    else if (event.key === '0') setZoom(ZOOM_RESET);
    else return;
    event.preventDefault();
  });
  // A click on the backdrop lands on the dialog itself, since the bar and the body fill it.
  // (`closedby="any"` does this natively in Chrome 134 and Firefox 141, not yet in Safari.)
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => {
    viewer.reads += 1;
    replace(document.getElementById('viewer-doc'), []);
    leaveItem();
  });
  const saved = ZOOM_STEPS.indexOf(Number(remembered(STORE.zoom)));
  setZoom(saved >= 0 ? saved : ZOOM_RESET);
}

// --- the journal tail ---------------------------------------------------------------------------

function startTail() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  if (state.timers.journal) {
    clearInterval(state.timers.journal);
    delete state.timers.journal;
  }
  journalPlaceholder('reading the journal', true);
  const note = document.getElementById('transport');
  if (TRANSPORT === 'sse') {
    note.textContent = 'transport: server-sent events (?transport=sse). Drop the parameter for the polling default.';
    startStream();
  } else {
    note.textContent = `transport: polling, ${state.pollJournal} s for the tail and ${state.pollViews} s for the views. Add ?transport=sse to compare.`;
    every('journal', state.pollJournal, pollJournal);
  }
}

async function pollJournal() {
  if (!state.project) return;
  const base = `/api/projects/${encodeURIComponent(state.project)}/journal`;
  // The first read of a project asks for the last screenful by line count, not for the whole
  // journal, which on a mature project is the largest file in the ledger. After that it is offsets.
  const path = state.since === null ? `${base}?tail=${TAIL_LINES}` : `${base}?since=${state.since}`;
  let tail;
  try {
    tail = await get(path, base);
  } catch (failure) {
    noteText('journal-note', String(failure.message || failure), true);
    return;
  }
  if (!tail) return;
  if (tail.truncated) document.getElementById('journal-tail').replaceChildren();
  state.since = tail.next;
  appendEvents(tail.events);
  // The read came back, so an empty tail is a journal with nothing in it rather than one unread.
  journalPlaceholder('no event has been journaled for this project yet');
  noteText('journal-note', `${tail.size} bytes, reading from ${tail.next}`);
}

function startStream() {
  const query = new URLSearchParams({ transport: 'sse', since: String(state.since ?? 0) });
  if (TOKEN) query.set('token', TOKEN);
  const stream = new EventSource(`/api/projects/${encodeURIComponent(state.project)}/journal?${query}`);
  // A stream has no end of backlog to wait for, so the tail says what is true of it: it is open,
  // and nothing has come along it yet.
  stream.addEventListener('open', () => journalPlaceholder('the stream is open; no event has arrived on it yet'));
  stream.addEventListener('message', (message) => {
    state.since = Number(message.lastEventId) || state.since;
    try {
      appendEvents([JSON.parse(message.data)]);
    } catch (failure) {
      // A torn line the ledger closes on its next append; the next id carries the whole line.
    }
    noteText('journal-note', `streaming, at offset ${state.since}`);
  });
  stream.addEventListener('error', () => {
    noteText('journal-note', 'stream dropped; the browser reconnects in 2 s with Last-Event-ID', true);
  });
  state.stream = stream;
}

// What the tail says while it holds no event: that it is reading, or, once a read has come back
// with nothing, that there is nothing. Both transports say it, and the line goes as soon as the
// first event lands.
function journalPlaceholder(text, loading) {
  const tail = document.getElementById('journal-tail');
  if (tail.querySelector('li:not(.state)')) return;
  replace(tail, [el('li', { class: loading ? 'state loading' : 'state', text })]);
}

function appendEvents(events) {
  const tail = document.getElementById('journal-tail');
  const atBottom = tail.scrollTop + tail.clientHeight >= tail.scrollHeight - 8;
  const placeholder = tail.querySelector('li.state');
  if ((events || []).length && placeholder) placeholder.remove();
  for (const event of events || []) {
    const payload = event.payload || {};
    const detail = Object.entries(payload)
      .filter(([name, value]) => name !== 'ticket' && value !== null && value !== '' && !(Array.isArray(value) && !value.length))
      .slice(0, 4)
      .map(([name, value]) => `${name}=${short(value)}`)
      .join(' ');
    tail.appendChild(el('li', {}, [
      el('span', { class: 'ts', text: (event.ts || '').replace('T', ' ').replace('Z', '') }),
      el('span', { class: `event s-${event.event}`, text: event.event }),
      el('span', { class: 'ticket', text: event.ticket === null || event.ticket === undefined ? '' : `#${event.ticket}` }),
      // The payload is cut to what fits the row; the whole of it is in the line's title.
      el('span', { class: 'payload', text: detail, title: Object.keys(payload).length ? wholeValue(payload) : null }),
    ]));
  }
  while (tail.childElementCount > TAIL_LINES) tail.removeChild(tail.firstElementChild);
  if (atBottom) tail.scrollTop = tail.scrollHeight;
}

function gib(bytes) {
  return `${(Number(bytes || 0) / 1024 ** 3).toFixed(1)} GiB`;
}

function short(value) {
  // A list's items read the way a value does, so an object inside it, however deep, never prints [object Object].
  if (Array.isArray(value)) return value.slice(0, 3).map((item) => (item !== null && typeof item === 'object' ? short(item) : item)).join(',') + (value.length > 3 ? '...' : '');
  if (value !== null && typeof value === 'object') return `{${Object.keys(value).length} keys}`;
  const text = String(value);
  return text.length <= 40 ? text : `${text.slice(0, 37)}...`;
}

// --- the actions (ticket 35) --------------------------------------------------------------------
//
// Every action is a POST with the token in the X-Wayline-Token header, which the server asks for on
// every bind and takes from nowhere else. The page holds the token only when its own URL carries it,
// as the URL `wayline serve` prints does; without it the controls stay off and the page says why.

function projectPath(suffix) {
  return `/api/projects/${encodeURIComponent(state.project)}${suffix}`;
}

// `project` is the project the action is for: the one whose view drew the form, else the selected one.
async function act(name, body, headers, project) {
  const target = project || state.project;
  if (!TOKEN) throw new Error('actions need the token: open the URL wayline serve printed, which carries it');
  if (!target) throw new Error('no project is selected');
  const sent = { 'X-Wayline-Token': TOKEN, ...(headers || {}) };
  let payload = body;
  if (!(body instanceof Blob)) {
    sent['Content-Type'] = 'application/json';
    payload = JSON.stringify(body || {});
  }
  const response = await fetch(`/api/projects/${encodeURIComponent(target)}/actions/${name}`, { method: 'POST', cache: 'no-store', headers: sent, body: payload });
  let reply;
  try {
    reply = await response.json();
  } catch (failure) {
    reply = { ok: false, error: `${response.status} ${response.statusText}` };
  }
  if (!response.ok || !reply.ok) throw new Error(reply.error || `${response.status} ${response.statusText}`);
  return reply;
}

// One line, said in its own note: the action note, the journal's, and the log tail's all read the
// same way, and a note that carried a failure last time is plain again when the next read lands.
function noteText(id, text, failed) {
  const note = document.getElementById(id);
  note.textContent = text;
  note.className = failed ? 'note problems' : 'note';
}

function say(text, failed) {
  noteText('action-note', text, failed);
}

// Take one action, say what came of it, and poll the views again at once instead of at their next tick, whether it
// was taken or refused: a refused change shows the value that stands.
async function perform(name, body, said, project) {
  try {
    const reply = await act(name, body, null, project);
    say(said ? said(reply) : `${name}: done`);
    return reply;
  } catch (failure) {
    say(`${name}: ${failure.message || failure}`, true);
    return null;
  } finally {
    refreshViews();
  }
}

function refreshViews() {
  state.tags = {};
  loadProjects();
  loadOverview();
  loadDecisions();
  loadChanges();
  loadGraph();
  loadWaiting();
  loadRun();
  for (const load of Object.values(VIEW_LOADERS)) load();
}

// --- the controls (ticket 35) ------------------------------------------------------------------

// A control the owner changed and has not set yet keeps what they chose while the views poll.
const dirty = { autonomy: false, pacing: false, model_fallback: false, ladder_changes: false };

// The line at the top of the controls panel: what it is doing, or what went wrong, before the
// first reading of the decisions view fills the controls themselves.
function controlsState(text, failed) {
  const line = document.getElementById('controls-state');
  if (!line) return;
  line.hidden = false;
  line.textContent = text;
  line.className = failed ? 'state error' : 'state loading';
}

function renderControls(controls) {
  const state_ = document.getElementById('controls-state');
  if (state_) state_.hidden = true;
  const select = document.getElementById('autonomy-select');
  if (!dirty.autonomy) {
    replace(select, (controls.autonomy_levels || []).map((level) => {
      const option = el('option', { value: level, text: level });
      option.selected = level === controls.autonomy;
      return option;
    }));
  }
  if (!dirty.pacing) {
    document.getElementById('stop-at').value = controls.stop_at ?? '';
    document.getElementById('cheap-at').value = controls.cheap_at ?? '';
  }
  if (!dirty.model_fallback) {
    replace(document.getElementById('model-fallback-select'), (controls.model_fallback_levels || []).map((consent) => {
      const option = el('option', { value: consent, text: consent });
      option.selected = consent === controls.model_fallback;
      return option;
    }));
  }
  document.getElementById('model-fallback-current').textContent = controls.model_fallback
    ? `now ${controls.model_fallback_stated ? controls.model_fallback : 'ask (unset)'}: what Fable work does while Fable's weekly window is spent` : '';
  if (!dirty.ladder_changes) {
    replace(document.getElementById('ladder-changes-select'), (controls.ladder_changes_levels || []).map((consent) => {
      const option = el('option', { value: consent, text: consent });
      option.selected = consent === controls.ladder_changes;
      return option;
    }));
  }
  document.getElementById('ladder-changes-current').textContent = controls.ladder_changes
    ? `now ${controls.ladder_changes_stated ? controls.ladder_changes : 'ask (unset)'}: whether an autonomous run may change the rung ladder on its own` : '';
  document.getElementById('autonomy-current').textContent = controls.autonomy
    ? `now ${controls.autonomy}; raised at any time, lowered only while no conductor runs` : '';
  document.getElementById('active-state').textContent = controls.active ? 'this is the active project' : 'another project is active';
  document.getElementById('pause-state').textContent = controls.paused_by_owner
    ? 'paused by the owner: nothing that needs a model launches' : 'not paused by the owner';
  for (const id of ['autonomy-set', 'pacing-set', 'model-fallback-set', 'ladder-changes-set', 'pause-button', 'resume-button']) document.getElementById(id).disabled = !TOKEN;
  document.getElementById('switch-button').disabled = !TOKEN || Boolean(controls.active);
}

function wireControls() {
  document.getElementById('autonomy-select').addEventListener('change', () => { dirty.autonomy = true; });
  for (const id of ['stop-at', 'cheap-at']) document.getElementById(id).addEventListener('input', () => { dirty.pacing = true; });
  document.getElementById('autonomy-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const level = document.getElementById('autonomy-select').value;
    dirty.autonomy = false;
    await perform('autonomy', { autonomy: level },
      (done) => (done.changed ? `autonomy set from ${done.from} to ${done.to}` : `autonomy is already ${done.to}`));
  });
  document.getElementById('pacing-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = { stop_at: Number(document.getElementById('stop-at').value), cheap_at: Number(document.getElementById('cheap-at').value) };
    dirty.pacing = false;
    await perform('pacing', body,
      (done) => (done.changed ? `pacing set: stop at ${done.to.stop_at}, cheap only at ${done.to.cheap_at}` : 'the pacing thresholds are already these'));
  });
  document.getElementById('model-fallback-select').addEventListener('change', () => { dirty.model_fallback = true; });
  document.getElementById('ladder-changes-select').addEventListener('change', () => { dirty.ladder_changes = true; });
  document.getElementById('ladder-changes-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const consent = document.getElementById('ladder-changes-select').value;
    dirty.ladder_changes = false;
    await perform('ladder_changes', { ladder_changes: consent },
      (done) => (done.changed ? `ladder consent set from ${done.from || 'ask (unset)'} to ${done.to}` : `the ladder consent is already ${done.to}`));
  });
  document.getElementById('model-fallback-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const consent = document.getElementById('model-fallback-select').value;
    dirty.model_fallback = false;
    await perform('model_fallback', { model_fallback: consent },
      (done) => (done.changed ? `fallback consent set from ${done.from || 'ask (unset)'} to ${done.to}` : `the fallback consent is already ${done.to}`));
  });
  document.getElementById('pause-button').addEventListener('click',
    () => perform('pause', {}, () => 'pause journaled: nothing that needs a model launches until resume'));
  document.getElementById('resume-button').addEventListener('click',
    () => perform('resume', {}, () => 'resume journaled: the conductor launches again at its next wave'));
  document.getElementById('switch-button').addEventListener('click', () => perform('switch', {}, (done) => (done.draining
    ? `the conductor on ${done.from} is draining; this project becomes the active one once it has ended`
    : `${done.to} is the active project`)));
}

function ticketActions(f) {
  const buttons = [
    ['cancel', `Cancel ticket ${f.id}? Its worker is ended and the ticket is parked.`],
    ['rerun', `Rerun ticket ${f.id}? Its worker is ended and the ticket opens for a new attempt.`],
  ].map(([name, question]) => {
    const button = el('button', { type: 'button', class: 'action', text: name });
    button.disabled = !TOKEN;
    button.addEventListener('click', () => {
      if (window.confirm(question)) perform(name, { ticket: f.id }, () => `${name} of ticket ${f.id} journaled; the conductor applies it at its next wave`);
    });
    return button;
  });
  return el('p', { class: 'inline acts' }, buttons);
}

// --- the feedback form and the evolve loop's view (ticket 45) -----------------------------------

// What the evolve loop made of each item, in the owner's terms.
function feedbackState(item) {
  if (item.journaled === false) return 'dropped in research/feedback/; journaled when the evolve loop next looks';
  if (!item.read) return 'waits for the evolver';
  if ((item.records || []).length) return `became ${item.records.join(', ')}`;
  return item.dismissed ? `dismissed: ${item.dismissed}` : 'read; no change came of it';
}

function changeState(record) {
  const ticket = record.ticket === null || record.ticket === undefined ? '' : ` (ticket #${record.ticket}${record.ticket_status ? `, ${record.ticket_status}` : ''})`;
  const said = {
    open: `its harness ticket is filed${ticket}`,
    proposed: `proposed, not applied: wayline evolve --apply ${record.id}`,
    awaiting_owner: `${record.branch} passed the tests and the fixture suite; merge it, then run wayline evolve`,
    applied: record.tag ? `applied, tagged ${record.tag}` : `applied${ticket}`,
    declined: 'declined',
  };
  return said[record.status] || record.status;
}

async function loadChanges() {
  const project = state.project;
  if (!project) return;
  try {
    const view = await get(projectPath('/changes'));
    if (view && project === state.project) renderChanges(view);
  } catch (failure) {
    if (project === state.project) replace(document.getElementById('changes-body'), [errorState(failure)]);
  }
}

function renderChanges(view) {
  const items = view.feedback || [];
  const records = view.changes || [];
  const parts = [subhead('feedback', items.length)];
  parts.push(tableOrNone(['item', 'from', 'what came of it', 'when'], items.map((item) => [
    item.id, item.source, feedbackState(item), (item.ts || '').replace('T', ' ').replace('Z', ''),
  ]), 'no feedback has been filed on this project yet', ['short', 'short', 'clamp', 'short']));
  parts.push(subhead('change records', records.length));
  parts.push(tableOrNone(['record', 'change', 'mechanism', 'where', 'risk', 'fixture', 'state'], records.map((record) => [
    record.id, record.desired || '', `${record.mechanism}, ${record.scope_kind}`, record.target || '', record.risk, record.fixture, changeState(record),
  ]), 'no change record yet: the evolver writes them from the feedback above', ['short', 'clamp', 'short', 'short', 'short', 'short', 'clamp']));
  replace(document.getElementById('changes-body'), parts);
}

function wireFeedback() {
  const form = document.getElementById('feedback-form');
  const text = document.getElementById('feedback-text');
  const send = document.getElementById('feedback-send');
  send.disabled = !TOKEN;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const words = text.value.trim();
    if (!words) {
      say('feedback: say what should have gone better', true);
      return;
    }
    send.disabled = true;
    const reply = await perform('feedback', { text: words },
      (done) => `feedback ${done.id} filed: a running conductor hands it to the evolver at its next wave, and wayline evolve does so by hand`);
    if (reply) text.value = '';
    send.disabled = !TOKEN;
  });
}

// --- the decisions view (ticket 35) ------------------------------------------------------------

// What the owner has typed into an answer form, per project and ticket, so that a redraw of the open
// decisions never loses a half-written answer.
const drafts = {};

async function loadDecisions() {
  const project = state.project;
  if (!project) return;
  try {
    const view = await get(projectPath('/decisions'));
    // A tab switched while this poll was out: the view is another project's, and its forms must not be drawn under this one.
    if (view && project === state.project) renderDecisions(view, project);
  } catch (failure) {
    if (project !== state.project) return;
    state.openSignature = null;
    replace(document.getElementById('decisions-open'), [errorState(failure)]);
    // The controls are drawn from this same view, so the panel that lost its reading says so.
    controlsState(String(failure.message || failure), true);
  }
}

function renderDecisions(view, project) {
  renderControls(view.controls || {});
  const open = view.open || [];
  const before = JSON.stringify(state.openDecisions);
  state.openDecisions = { project, list: open };
  renderTicketDecision();
  // A decision waiting on the owner sits in the board's "needs you".
  if (JSON.stringify(state.openDecisions) !== before) renderBoard();
  // Redrawn only when it changed: a redraw replaces the form under the owner's cursor.
  const signature = JSON.stringify([project, open]);
  if (signature !== state.openSignature) {
    state.openSignature = signature;
    const cards = [subhead('open decision tickets', open.length)];
    if (!open.length) cards.push(emptyState('nothing is waiting for an answer'));
    for (const decision of open) cards.push(decisionCard(decision, project));
    replace(document.getElementById('decisions-open'), cards);
  }
  const log = view.log || [];
  const parts = [subhead('decision log', log.length), el('p', { class: 'note', text: "the decider's decisions first" })];
  parts.push(tableOrNone(['decided by', 'ticket', 'question', 'answer', 'rationale', 'when'], log.map((entry) => [
    entry.decided_by + (entry.superseded ? ' (superseded)' : ''),
    entry.ticket === null ? (entry.id || '') : `#${entry.ticket}`,
    entry.question || '',
    entry.answer,
    entry.rationale || '',
    (entry.ts || '').replace('T', ' ').replace('Z', ''),
  ]), 'nothing has been decided on this project yet', ['short', 'short', 'clamp', 'clamp', 'clamp', 'short']));
  if ((view.problems || []).length) {
    parts.push(subhead('problems', view.problems.length));
    parts.push(el('ul', { class: 'problems' }, view.problems.map((problem) => el('li', { text: problem }))));
  }
  replace(document.getElementById('decisions-log'), parts);
}

function decisionCard(decision, project) {
  const key = `${project}:${decision.id}`;
  const draft = drafts[key] || (drafts[key] = { choice: '', text: '', rationale: '' });
  let pauses = 'no ticket waits on it yet';
  if (decision.blocking === 'all') pauses = 'every other ticket waits for the answer';
  else if ((decision.pauses || []).length) pauses = `ticket(s) ${decision.pauses.join(', ')} wait for the answer`;
  const card = el('article', { class: 'decision', 'data-id': String(decision.id) }, [
    el('h4', { text: `#${decision.id} ${decision.title || ''}` }),
    el('p', { class: 'question', text: decision.question || '' }),
    fields([
      ['pauses', pauses],
      ['answered by', decision.awaits === 'owner'
        ? (decision.human_only ? 'the owner only: it is human-only' : 'the owner')
        : 'the decider, unless the owner answers first'],
      ['recommended', decision.recommended],
      ['falls back', decision.falls_back_at ? `at ${decision.falls_back_at} unless answered` : null],
      ['status', decision.status],
      ['asked by', decision.proposed_by],
      ['origin', decision.origin],
    ]),
    ...kindFields(decision, project),
  ]);
  if ((decision.evidence || []).length) {
    card.appendChild(el('h5', { text: 'evidence' }));
    card.appendChild(el('ul', {}, decision.evidence.map((item) => el('li', { text: item }))));
  }
  if (decision.answered) {
    card.appendChild(el('p', { class: 'note', text: `answered by the ${decision.answered.decided_by}: ${decision.answered.answer}. The conductor closes it at its next wave, and the tick relaunches one when none runs.` }));
    return card;
  }
  if (decision.written) {
    card.appendChild(el('p', { class: 'note', text: `an answer is written in the ticket file: ${decision.written}. The next wave or tick journals it as the owner's.` }));
    return card;
  }
  const form = el('form', { class: 'answer-form acts' });
  for (const option of decision.options || []) {
    const input = el('input', { type: 'radio', name: `choice-${decision.id}`, value: option, 'data-draft': key, 'data-field': 'choice' });
    input.checked = draft.choice === option;
    input.addEventListener('change', () => {
      draft.choice = option;
      showDraft(key, 'choice', input);
    });
    form.appendChild(el('label', { class: 'option' }, [input, document.createTextNode(` ${option}${option === decision.recommended ? ' (recommended)' : ''}`)]));
  }
  const text = el('textarea', {
    rows: '2', placeholder: (decision.options || []).length ? 'or an answer in your own words' : 'the answer', 'aria-label': `the answer to ticket ${decision.id}`,
    'data-draft': key, 'data-field': 'text',
  });
  text.value = draft.text;
  text.addEventListener('input', () => {
    draft.text = text.value;
    showDraft(key, 'text', text);
  });
  const rationale = el('textarea', { rows: '2', placeholder: 'why (optional; journaled with the answer)', 'aria-label': `why, for ticket ${decision.id}`,
                                     'data-draft': key, 'data-field': 'rationale' });
  rationale.value = draft.rationale;
  rationale.addEventListener('input', () => {
    draft.rationale = rationale.value;
    showDraft(key, 'rationale', rationale);
  });
  const submit = el('button', { type: 'submit', class: 'action primary', text: `answer ticket ${decision.id}` });
  submit.disabled = !TOKEN;
  form.append(text, rationale, submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const answer = draft.text.trim() || draft.choice;
    if (!answer) {
      say(`ticket ${decision.id}: choose an option or write an answer`, true);
      return;
    }
    const body = { ticket: decision.id, answer };
    if (draft.rationale.trim()) body.rationale = draft.rationale.trim();
    submit.disabled = true;
    const reply = await perform('answer', body,
      () => `ticket ${decision.id} answered: ${answer}. It is journaled as your decision, and the conductor closes the ticket at its next wave.`,
      project);
    if (reply) delete drafts[key];
    else submit.disabled = !TOKEN;
  });
  card.appendChild(form);
  return card;
}

// A decision can be on the page twice (the decisions panel, and its own ticket page), and both forms
// send the one draft, so what is typed in one is shown in the other as it is typed.
function showDraft(key, field, typedIn) {
  for (const other of document.querySelectorAll('[data-draft][data-field]')) {
    if (other === typedIn || other.dataset.draft !== key || other.dataset.field !== field) continue;
    if (other.type === 'radio') other.checked = other.value === drafts[key].choice;
    else other.value = drafts[key][field];
  }
}

// --- the intake drop zone (ticket 35) ----------------------------------------------------------

async function upload(files) {
  const list = document.getElementById('intake-list');
  const placeholder = list.querySelector('li.state');
  if (placeholder) placeholder.remove();
  for (const file of Array.from(files || [])) {
    const row = el('li', { text: `${file.name}: sending ${humanSize(file.size)}...` });
    list.prepend(row);
    try {
      // Code's cautious guess sorted it (ticket 84), and the reply says how in one line.
      const reply = await act('intake', file, { 'X-Wayline-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' });
      row.textContent = `${file.name} (${humanSize(file.size)}): ${reply.said}`;
    } catch (failure) {
      row.textContent = `${file.name}: ${failure.message || failure}`;
      row.className = 'problems';
    }
  }
  refreshViews();
}

// The list under the drop zone holds what this page has sent, which is nothing until a file is
// dropped on it: it says that rather than sitting as an empty box.
function intakeEmpty() {
  const list = document.getElementById('intake-list');
  if (!list.querySelector('li:not(.state)')) replace(list, [el('li', { class: 'state', text: 'nothing has been sent from this page yet' })]);
}

function wireIntake() {
  const zone = document.getElementById('intake-drop');
  for (const type of ['dragenter', 'dragover']) {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.add('over');
    });
  }
  for (const type of ['dragleave', 'drop']) zone.addEventListener(type, () => zone.classList.remove('over'));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    upload(event.dataTransfer.files);
  });
  const input = document.getElementById('intake-file');
  input.addEventListener('change', () => {
    upload(input.files).then(() => { input.value = ''; });
  });
}

// --- the routes (ticket 110) ------------------------------------------------------------------------
//
// The dashboard is views behind the project tabs, routed by the hash so the browser's back and forward
// move between them and a reload keeps the one shown: `#/` is the projects page, `#/<project>/research`
// and `#/<project>/run` a project's views, and `#/<project>/<id>` opens one item in the viewer over its
// view, so a notice on the phone lands on the item in one tap. Paper and Inherited (111) are views too,
// Inherited only for a project with documents; Marks (112) joins them. A hash that is not a route
// (`#ticket/3`, a graph node's) is left alone.

const VIEW_NAMES = ['research', 'paper', 'inherited', 'run', 'marks'];
const routing = { done: false };

// The views that read only while they are shown, each by its loader: every poll asks, and a hidden view
// returns at once. Run's panels are read whatever is shown, since its overview feeds the tabs.
const VIEW_LOADERS = { research: loadResearch, paper: loadPaper, inherited: loadInherited, marks: loadMarks };

// Each routed view's panels, with what each says until its project's first answer lands.
const READING = {
  'general-body': 'reading the research',
  'objectives-body': 'reading the objectives',
  'beyond-body': 'reading the results',
  'account-body': 'reading the account',
  'software-body': 'reading tools.json',
  'paper-sections-body': 'reading the sections',
  'paper-references-body': 'reading the references',
  'paper-repository-body': 'reading the code repository',
  'paper-methods-body': 'reading Methods',
  'inherited-documents-body': 'reading the documents',
  'inherited-concerns-body': 'reading the concerns',
  'inherited-claims-body': 'reading the inherited claims',
  'inherited-pairs-body': 'reading the repeated claims',
  'inherited-material-body': 'reading the missing material',
  'marks-body': 'reading the batches',
  'marks-settled-body': 'reading the settled batches',
};

// Whether a project offers Inherited: only one with documents does (decision 17). A count not known (its record
// could not be read) still offers it, and the view says why.
function offersInherited(id) {
  const entry = state.projects.find((project) => project.id === id);
  return Boolean(entry && entry.readable && !entry.read_only && entry.documents !== 0);
}

function routeTo(project, viewOrItem) {
  return `#/${encodeURIComponent(project)}/${encodeURIComponent(viewOrItem)}`;
}

function parseRoute(hash) {
  const raw = (hash || '').replace(/^#/, '');
  if (!raw.startsWith('/')) return null;
  let parts;
  try {
    parts = raw.slice(1).split('/').filter(Boolean).map(decodeURIComponent);
  } catch (failure) {
    return null;
  }
  if (!parts.length) return { page: 'projects' };
  const [project, rest] = parts;
  if (rest === undefined) return { project, view: 'research' };
  if (VIEW_NAMES.includes(rest)) return { project, view: rest };
  if (BATCH_ID.test(rest)) return { project, view: 'marks', batch: rest }; // a batch opens Marks at it, not the viewer
  return { project, item: rest };
}

// Move to a route: a new entry in the history, which `hashchange` then applies.
function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function route() {
  let target = parseRoute(location.hash);
  if (target === null) {
    // Not a route of ours (`#ticket/3`, a fragment a rendered file linked to): left alone once a view is shown, and
    // replaced by the default route on a page that has shown none yet, so a stray hash never leaves the page blank.
    if (location.hash && location.hash !== '#' && routing.done) return;
    if (!state.projectsLoaded) return; // the default needs the projects: applied once they are read
    // No route yet: the active project's Research, else the projects page. Replaced, not pushed, so back leaves the page.
    const first = state.projects.find((project) => project.active && project.readable) || state.projects.find((project) => project.readable);
    target = first ? { project: first.id, view: 'research' } : { page: 'projects' };
    history.replaceState(null, '', first ? routeTo(first.id, 'research') : '#/');
  }
  if (target.page === 'projects') {
    routing.done = true;
    closeItem();
    showView('projects');
    return;
  }
  if (!state.projectsLoaded) return;
  const known = state.projects.find((project) => project.id === target.project);
  const landed = !routing.done;
  routing.done = true;
  if (!known || !known.readable) {
    closeItem();
    showView('projects');
    say(`no readable project has the id ${target.project}: the projects page lists them`, true);
    return;
  }
  select(target.project);
  if (target.view === 'inherited' && !offersInherited(target.project)) {
    closeItem();
    history.replaceState(null, '', routeTo(target.project, 'research'));
    showView('research');
    say('this project has no documents, so it has no Inherited view: hand one over in a conversation or the intake', true);
    return;
  }
  if (target.view) {
    closeItem();
    if (target.batch) marks.focus = target.batch;
    showView(target.view);
    return;
  }
  openItem(target.project, target.item, landed);
}

function showView(name) {
  state.view = name;
  for (const view of document.querySelectorAll('main .view')) view.hidden = view.dataset.view !== name;
  document.getElementById('strip').hidden = name === 'projects' || !state.project || readOnlyNow();
  document.body.dataset.view = name;
  markViews();
  buildIndex();
  if (name === 'projects') renderProjectsPage();
  if (VIEW_LOADERS[name]) VIEW_LOADERS[name]();
  // A drawing that could not be measured while Run was hidden is drawn now that it can be.
  if (name === 'run') drawGraph();
}

// The views' links name the selected project's routes; Inherited's shows only for a project with documents.
function markViews() {
  for (const link of document.querySelectorAll('#views a[data-route]')) {
    const name = link.dataset.route;
    if (name !== 'projects') {
      if (state.project) link.setAttribute('href', routeTo(state.project, name));
      else link.removeAttribute('href');
    }
    if (name === 'inherited') link.hidden = !state.project || !offersInherited(state.project);
    link.setAttribute('aria-current', String(name === state.view));
  }
}

// --- items in the viewer ----------------------------------------------------------------------------
//
// An item link asks the server what it opens (`items/<id>`): a file the viewer reads, with the heading to
// scroll to, a plot's image and its explanation, or a table's rows. Closing the viewer goes back to the
// view under it: a step back when the item was opened from the page, the view's own route when the
// owner landed on the item from a notice.

async function openItem(project, id, landed) {
  const opening = { project, id, landed };
  viewer.item = opening;
  if (!state.view || state.view === 'projects') showView('research');
  const headers = TOKEN ? { 'X-Wayline-Token': TOKEN } : {};
  let item;
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(project)}/items/${encodeURIComponent(id)}`, { cache: 'no-store', headers });
    if (response.status === 404) {
      let line;
      try {
        line = (await response.json()).line;
      } catch (failure) {
        line = null; // a project the server no longer knows answers in plain text
      }
      if (viewer.item === opening) viewerNotFound(id, line);
      return;
    }
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    item = await response.json();
  } catch (failure) {
    if (viewer.item === opening) viewerNotFound(id, `${id}: ${failure.message || failure}`);
    return;
  }
  if (viewer.item !== opening) return;
  showView(item.view);
  // `R4 Does the loss fall?`, but `The account` alone: a word id says nothing its title does not.
  const title = !item.title ? item.id : /^[A-Z0-9]/.test(item.id) ? `${item.id} ${item.title}` : item.title;
  openViewer(item.path, {
    title, focus: item.focus, caption: item.caption, rows: item.rows, unreadable: item.unreadable, sides: item.sides, fields: item.fields,
  });
  seeReport(project, item);
}

function closeItem() {
  const dialog = document.getElementById('viewer');
  if (viewer.item && dialog.open) dialog.close();
  viewer.item = null;
}

// The viewer closed: an item route goes back to its view.
function leaveItem() {
  const item = viewer.item;
  viewer.item = null;
  if (!item) return;
  const now = parseRoute(location.hash);
  if (!now || now.item !== item.id || now.project !== item.project) return;
  if (item.landed) history.replaceState(null, '', routeTo(item.project, state.view && state.view !== 'projects' ? state.view : 'research'));
  else history.back();
}

// --- new since you looked ---------------------------------------------------------------------------
//
// A current report renewed since the owner last opened it carries a dot. What the owner last opened is
// kept in this browser, each report's hash as it was then, and nowhere else: the dashboard never writes
// the ledger, and a renewed report notifies nowhere.

function seenReports() {
  try {
    return JSON.parse(remembered(STORE.seen) || '{}') || {};
  } catch (failure) {
    return {};
  }
}

function isNew(project, name, sha) {
  return Boolean(sha) && seenReports()[`${project}:${name}`] !== sha;
}

// The report an opened item is, and its hash, from the Research view last read; the dot goes once it is seen.
function seeReport(project, item) {
  const held = state.research && state.research.project === project ? state.research.view : null;
  if (!held) {
    // Landed from a notice: the item came back before Research did, so it is seen once Research is read.
    state.seeing = { project, item };
    return;
  }
  let name = null;
  let sha = null;
  if (item.id === 'report') {
    name = 'report';
    sha = held.report.sha256;
  } else {
    for (const result of held.results || []) {
      const current = result.current;
      if (current && (item.id === result.id || item.id === current.name)) {
        name = current.name;
        sha = current.sha256;
      }
    }
  }
  if (!name || !sha) return;
  const seen = seenReports();
  seen[`${project}:${name}`] = sha;
  remember(STORE.seen, JSON.stringify(seen));
  renderResearch(held, project);
}

// --- thin lists ---------------------------------------------------------------------------------------
//
// Every view lists items as thin rows: the id, the title, the status, the link that opens it, and insert
// into chat. A row never carries a rendered file: those open in the viewer only.

function itemLink(project, id, text) {
  return el('a', { class: 'row-id', href: routeTo(project, id), text: text || id, title: `open ${id} in the viewer` });
}

// A row: `id`, the item it links to, shown as `label` when one is given (a section by its name, not its
// route word); `title`, `status`, `dot`, and `more` lines; `link: false` for a row that opens nothing,
// `insert: false` for one that names nothing a conversation could take.
function itemRow(project, row) {
  const label = row.label || row.id;
  const line = [
    row.link === false ? el('span', { class: 'row-id', text: label, title: label }) : itemLink(project, row.id, label),
    el('span', { class: 'row-title', text: row.title || '' }),
  ];
  if (row.status) line.push(statusChip(row.status));
  if (row.dot) line.push(newDot());
  const acts = [];
  if (row.link !== false) acts.push(el('a', { class: 'action', href: routeTo(project, row.id), text: 'view' }));
  if (row.insert !== false) acts.push(insertButton(project, row.id));
  if (acts.length) line.push(el('span', { class: 'row-acts' }, acts));
  return el('li', { class: 'row', 'data-item': row.id }, [el('div', { class: 'row-line' }, line), ...(row.more || [])]);
}

// A status as a chip, its class the status's words joined (`to the scout` is `s-to-the-scout`).
function statusChip(status) {
  return el('span', { class: `chip s-${String(status).replace(/[^a-z0-9_]+/gi, '-')}`, text: status });
}

function newDot() {
  return el('span', { class: 'dot', role: 'img', title: 'new since you looked', 'aria-label': 'new since you looked' });
}

function more(text, children) {
  return el('p', { class: 'row-more', text: children ? null : text }, children || []);
}

// The chat panel arrives with ticket 114; until then insert copies the item's reference, to paste into a conversation.
function insertButton(project, id) {
  const button = el('button', { type: 'button', class: 'action', text: 'insert', title: `insert ${id} into the chat` });
  button.addEventListener('click', async () => {
    const reference = `${id} (${location.pathname}${routeTo(project, id)})`;
    try {
      await navigator.clipboard.writeText(reference);
      say(`${id}: its reference is copied, to paste into a conversation`);
    } catch (failure) {
      say(`${id}: copy its reference by hand: ${reference}`);
    }
  });
  return button;
}

function rowsOrNone(items, render, empty) {
  return items.length ? el('ul', { class: 'rows' }, items.map(render)) : emptyState(empty);
}

// --- "Waiting on you" -----------------------------------------------------------------------------------

// A project of another research_version gets no strip: its account is not this release's to read.
function readOnlyNow() {
  return document.body.dataset.readOnly === 'true';
}

async function loadWaiting() {
  const project = state.project;
  if (!project || readOnlyNow()) return;
  try {
    const view = await get(projectPath('/waiting'), 'waiting');
    if (view && project === state.project) renderStrip(view, project);
  } catch (failure) {
    if (project === state.project) replace(document.getElementById('strip-items'), [el('li', {}, [errorState(failure)])]);
  }
}

function renderStrip(view, project) {
  const strip = document.getElementById('strip');
  document.getElementById('strip-count').textContent = String(view.count);
  strip.classList.toggle('empty', !view.count);
  replace(document.getElementById('strip-items'), view.items.length
    ? view.items.map((item) => el('li', { class: 'row' }, [el('div', { class: 'row-line' }, [
      ...(item.item ? [itemLink(project, item.item, `#${item.item}`)] : []),
      el('span', { class: 'row-title', text: item.text }),
    ])]))
    : [el('li', {}, [emptyState('nothing waits on you')])]);
  state.waiting = view.count;
  showTitle();
}

// The selected project's waiting count in the browser tab's title, so it shows from another tab.
function showTitle() {
  const entry = state.projects.find((project) => project.id === state.project);
  const name = entry ? entry.name : null;
  document.title = `${state.waiting ? `(${state.waiting}) ` : ''}${name ? `${name} - ` : ''}wayline`;
}

// --- the projects page -----------------------------------------------------------------------------------

function runStateLine(run) {
  if (!run) return null;
  const conductor = run.conductor ? 'a conductor holds it' : 'no conductor runs';
  if (run.state === 'running') return `running since ${run.since}; ${conductor}`;
  if (run.state === 'ended') return `ended ${run.since}${run.reason ? ` (${run.reason})` : ''}; ${conductor}`;
  return `not started; ${conductor}`;
}

function renderProjectsPage() {
  const body = document.getElementById('projects-body');
  if (!state.projectsLoaded) return;
  if (!state.projects.length) {
    replace(body, [emptyState('no project is registered: run wayline init <path>')]);
    return;
  }
  replace(body, [el('ul', { class: 'rows' }, state.projects.map((project) => {
    const chips = [];
    if (project.active) chips.push(el('span', { class: 'chip', text: 'active' }));
    if (project.read_only) chips.push(el('span', { class: 'chip s-parked', text: `${project.harness_tag || 'an older tag'}, read-only` }));
    if (project.waiting) chips.push(el('span', { class: 'chip s-running', text: `${project.waiting} waiting on you` }));
    const title = project.readable
      ? el('a', { class: 'row-id', href: routeTo(project.id, project.read_only ? 'run' : 'research'), text: project.name })
      : el('span', { class: 'row-id', text: project.name });
    const lines = [el('div', { class: 'row-line' }, [title, el('span', { class: 'row-title mono', text: project.path }), ...chips])];
    if (!project.readable) lines.push(more('the path is gone'));
    else if (project.read_only) {
      lines.push(more(null, [
        document.createTextNode(`Made with ${project.harness_tag || 'an older tag'} (research_version ${project.research_version}): read-only here. `),
        el('a', { href: routeTo(project.id, 'run'), text: 'its files' }),
        document.createTextNode(' open in the viewer; wayline upgrade --to that tag, or a new project, to work on it.'),
      ]));
    } else {
      if (project.standing) lines.push(more(project.standing));
      const run = runStateLine(project.run_state);
      if (run) lines.push(more(run));
    }
    return el('li', { class: 'row project-row' }, lines);
  }))]);
}

// --- Research -----------------------------------------------------------------------------------------------

async function loadResearch() {
  const project = state.project;
  if (!project || state.view !== 'research') return;
  try {
    const view = await get(projectPath('/research'), 'research');
    if (!view || project !== state.project) return;
    state.research = { project, view };
    renderResearch(view, project);
    const seeing = state.seeing;
    state.seeing = null;
    if (seeing && seeing.project === project) seeReport(project, seeing.item);
  } catch (failure) {
    if (project === state.project) replace(document.getElementById('general-body'), [errorState(failure)]);
  }
}

function measureLine(objective) {
  if (!objective.measure) return 'no measure: an objective, not a goal';
  const kept = (objective.kept || []).length ? `kept ${objective.kept.join(', ')}` : 'nothing kept yet';
  const best = objective.best === null || objective.best === undefined ? '' : `; best ${objective.best}${objective.reached ? ', reached' : ''}`;
  return `${objective.measure}; ${kept}${best}`;
}

function lineageLine(objective) {
  const lineage = objective.lineage || {};
  const parts = [];
  if ((lineage.reframed_from || []).length) parts.push(`reframed from ${lineage.reframed_from.join(', ')}`);
  if (lineage.reframed_as) parts.push(`reframed as ${lineage.reframed_as}`);
  for (const earlier of lineage.superseded || []) parts.push(`once ${earlier.status}: ${earlier.answer || 'no answer'}`);
  return parts.join('; ');
}

// A list of item links, `R1-1, R1-2`, after a word that says what they are.
function linkList(project, word, ids) {
  const parts = [document.createTextNode(`${word} `)];
  ids.forEach((id, index) => {
    if (index) parts.push(document.createTextNode(', '));
    parts.push(itemLink(project, id));
  });
  return parts;
}

function resultRow(project, result) {
  const current = result.current;
  const lines = [];
  if (result.headline) lines.push(more(`headline: ${result.headline}`));
  const reports = current ? linkList(project, 'current report', [current.name]) : [document.createTextNode('no report before its first drawing')];
  if (current && isNew(project, current.name, current.sha256)) reports.push(newDot());
  if ((result.earlier || []).length) reports.push(document.createTextNode('; '), ...linkList(project, 'earlier', result.earlier.map((report) => report.name)));
  lines.push(more(null, reports));
  if ((result.plots || []).length) lines.push(more(null, linkList(project, 'plots', result.plots.map((plot) => plot.id))));
  if ((result.left_out || []).length) {
    lines.push(more(`left out: ${result.left_out.map((item) => `${item.what} (${item.reason})`).join('; ')}`));
  }
  return itemRow(project, { id: result.id, title: result.heading, status: result.standing, more: lines });
}

function renderResearch(view, project) {
  const byId = new Map((view.results || []).map((result) => [result.id, result]));
  const report = view.report || {};
  const general = [report.exists
    ? rowsOrNone([report], () => itemRow(project, {
      id: 'report', title: 'The general report', dot: isNew(project, 'report', report.sha256),
      more: [more(report.renewed ? `rendered ${report.renewed}` : 'rendered by code')],
    }), '')
    : emptyState('no general report yet: code renders it once the first finding is filed')];
  general.push(fields([['plotting', view.plotting ? `${view.plotting.label} (${view.plotting.library})` : null]]));
  if ((view.problems || []).length) general.push(el('ul', { class: 'problems' }, view.problems.map((problem) => el('li', { text: problem }))));
  replace(document.getElementById('general-body'), general);

  replace(document.getElementById('objectives-body'), [rowsOrNone(view.objectives || [], (objective) => {
    const lines = [more(measureLine(objective))];
    const lineage = lineageLine(objective);
    if (lineage) lines.push(more(lineage));
    const results = (objective.results || []).map((id) => byId.get(id)).filter(Boolean);
    lines.push(results.length ? el('ul', { class: 'rows nested' }, results.map((result) => resultRow(project, result)))
      : more('no result answers it yet'));
    return itemRow(project, { id: objective.id, title: objective.text, status: objective.status, more: lines });
  }, 'no objective is recorded yet: say what the research should answer in a conversation')]);

  const beyond = (view.beyond || []).map((id) => byId.get(id)).filter(Boolean);
  replace(document.getElementById('beyond-body'), [
    subhead('results', beyond.length),
    rowsOrNone(beyond, (result) => resultRow(project, result), 'every result answers an objective'),
    subhead('set-aside claims', (view.set_aside || []).length),
    rowsOrNone(view.set_aside || [], (claim) => itemRow(project, {
      id: claim.id, title: claim.text, link: false, more: [more(`its objectives ${claim.objectives.join(', ')} are closed`)],
    }), 'no claim is set aside'),
    subhead('parked for a closed objective', (view.parked || []).length),
    rowsOrNone(view.parked || [], (ticket) => itemRow(project, {
      id: String(ticket.id), title: ticket.title, status: 'parked', more: [more(ticket.reason)],
    }), 'no ticket is parked for a closed objective'),
  ]);
}

// --- Paper (ticket 111) --------------------------------------------------------------------------------------
//
// The five sections and the outline, each read only in the viewer; References with its Not yet resolved
// rows; the code repository; Methods' parameter table and the methods with no code; and the place the
// paper order's card takes (ticket 121). The edit buttons on the sections, the outline, and a parameter's
// reason come with ticket 113.

async function loadPaper() {
  const project = state.project;
  if (!project || state.view !== 'paper') return;
  try {
    const view = await get(projectPath('/paper'), 'paper');
    if (view && project === state.project) renderPaper(view, project);
  } catch (failure) {
    if (project === state.project) replace(document.getElementById('paper-sections-body'), [errorState(failure)]);
  }
}

// What a view could not read, said under its first panel while the rest of it still shows.
function problemsList(problems) {
  return (problems || []).length ? [el('ul', { class: 'problems' }, problems.map((problem) => el('li', { text: problem })))] : [];
}

// A file code renders, as a row that opens it: a section or the outline.
function renderedRow(project, file, lines) {
  return itemRow(project, {
    id: file.id, label: file.title, link: file.exists,
    more: [more(file.exists ? `rendered ${file.rendered || 'by code'}` : 'not rendered yet'), ...(lines || [])],
  });
}

function passagesLine(section) {
  if (section.passages === null || section.passages === undefined) return more('code writes it from the works the other sections cite');
  if (!section.passages) return more('empty for now');
  return more(`${section.passages} passage${section.passages === 1 ? '' : 's'} standing`);
}

function renderPaper(view, project) {
  const files = (view.sections || []).map((section) => renderedRow(project, section, [passagesLine(section)]));
  if (view.outline) files.push(renderedRow(project, view.outline, [more('the proposed shape of the paper, built by code')]));
  replace(document.getElementById('paper-sections-body'), [
    files.length ? el('ul', { class: 'rows' }, files) : emptyState('no section is rendered yet'),
    ...problemsList(view.problems),
  ]);
  renderReferences(view.references || {}, project);
  renderRepository(view.code_repository || {});
  renderMethods(view.methods || {}, project);
}

function authorsOf(entry) {
  const names = (entry.authors || []).join(', ');
  return names ? `${names}${entry.more_authors ? ' et al.' : ''}` : '';
}

// References' entries are works, not items: a row of one opens nothing and inserts nothing.
function renderReferences(references, project) {
  const entries = references.entries || [];
  const unresolved = references.unresolved || [];
  replace(document.getElementById('paper-references-body'), [
    el('p', { class: 'note' }, [itemLink(project, 'references', 'open References'), document.createTextNode(' as code wrote it')]),
    subhead('entries', entries.length),
    rowsOrNone(entries, (entry) => itemRow(project, {
      id: `[${entry.number}]`, link: false, insert: false,
      title: [authorsOf(entry), entry.year ? `(${entry.year})` : '', entry.title].filter(Boolean).join(' '),
      more: [more([entry.venue, entry.identifier, entry.slug].filter(Boolean).join(' · '))],
    }), 'nothing is cited yet: a work enters References only when a section cites it'),
    subhead('not yet resolved', unresolved.length),
    rowsOrNone(unresolved, (row) => itemRow(project, {
      id: row.slug || row.named, link: false, insert: false, title: row.slug ? row.title || row.named : '', status: row.state,
      more: [more(row.detail)],
    }), 'nothing: every cited work resolved'),
  ]);
}

// A remote's link, only when it is a web address: anything else is shown as words, never followed.
function remoteLink(repository) {
  const name = repository.repository || repository.url || '';
  if (!/^https:\/\//i.test(repository.url || '')) return document.createTextNode(name);
  return el('a', { href: repository.url, target: '_blank', rel: 'noopener noreferrer', text: name });
}

function renderRepository(repository) {
  const body = document.getElementById('paper-repository-body');
  if (!repository.settled) {
    replace(body, [emptyState('no code repository yet: one setup question settles its shape, its remote, its visibility, and its license')]);
    return;
  }
  const pushed = repository.last_push;
  replace(body, [
    el('p', {}, [remoteLink(repository)]),
    fields([
      ['visibility', repository.visibility === 'public' ? 'public' : 'private, until you make it public'],
      ['shape', repository.shape],
      ['license', repository.license],
      ['last push', pushed ? `${String(pushed.commit || '').slice(0, 12)} at ${pushed.ts}` : 'nothing pushed yet', pushed ? pushed.commit : undefined],
    ]),
  ]);
}

function renderMethods(methods, project) {
  const parameters = methods.parameters || [];
  const missing = methods.no_code || [];
  replace(document.getElementById('paper-methods-body'), [
    subhead('parameters', parameters.length),
    tableOrNone(['method', 'parameter', 'value', 'default', 'reason', 'whose reason', 'code'],
      parameters.map((row) => [row.method, row.name, row.value, row.default, row.reason, row.by === 'owner' ? 'yours' : `ticket ${row.ticket}`, row.code]),
      'no parameter is recorded yet: the results that ran list theirs', ['short', 'short', 'short', 'short', 'text', 'short', 'text']),
    subhead('methods with no code behind them', missing.length),
    rowsOrNone(missing, (entry) => itemRow(project, {
      id: entry.passage, title: `${entry.heading ? `${entry.heading}: ` : ''}${entry.named}`, more: [more(entry.why)],
    }), 'every method Methods names has code behind it'),
  ]);
}

// --- Inherited (ticket 111) ----------------------------------------------------------------------------------
//
// Only for a project with documents: what a start midway brought (the documents, the concerns their
// critiques raised) and what became of it (each inherited claim's standing, the contradictions and the
// merges the setup's check found, the material verification still lacks, with the owner's replies).

async function loadInherited() {
  const project = state.project;
  if (!project || state.view !== 'inherited') return;
  try {
    const view = await get(projectPath('/inherited'), 'inherited');
    if (view && project === state.project) renderInherited(view, project);
  } catch (failure) {
    if (project === state.project) replace(document.getElementById('inherited-documents-body'), [errorState(failure)]);
  }
}

// A document's headings, folded under their count: a manuscript has dozens.
function headingsOf(held) {
  const headings = held.headings || [];
  if (!headings.length) return more('no headings');
  return el('details', { class: 'row-more' }, [
    el('summary', { text: `${headings.length} heading${headings.length === 1 ? '' : 's'}` }),
    el('ul', { class: 'headings' }, headings.map((heading) => el('li', { class: `level-${Math.min(heading.level || 1, 4)}` }, [
      el('span', { class: 'mono', text: heading.locator }), document.createTextNode(` ${heading.text}`),
    ]))),
  ]);
}

function concernStanding(concern) {
  if (concern.status === 'answered') return `answered: ${concern.answer || ''}`;
  if (concern.status === 'declined') return `declined: ${concern.reason || ''}`;
  if (concern.place === 'objectives') return `open, tied to ${(concern.objectives || []).join(', ')}`;
  if (concern.place === 'order') return 'open, kept for the paper order';
  return 'open, waiting to be sorted';
}

function verdictLine(claim) {
  if (claim.standing === 'verified') {
    const how = [claim.route, claim.ticket ? `ticket ${claim.ticket}` : null, claim.by ? `by ${claim.by}` : null].filter(Boolean).join(', ');
    return `${claim.verdict || 'replaced'}${how ? ` (${how})` : ''}`;
  }
  if (claim.standing === 'unverifiable') return `unverifiable: ${claim.reason || 'no reason given'}`;
  return claim.section === 'results' ? 'unchecked: its verification has no verdict yet' : 'unchecked';
}

// A pair of claims, each named with its words: a contradiction or a merge.
function pairRow(project, pair, title, status, lines) {
  const texts = (pair.texts || []).map((text, index) => more(`${index ? pair.b : pair.a}: ${text}`));
  return itemRow(project, { id: pair.id, title, status, more: [...texts, ...(lines || [])] });
}

function renderInherited(view, project) {
  replace(document.getElementById('inherited-documents-body'), [
    rowsOrNone(view.documents || [], (held) => itemRow(project, {
      id: held.id, title: held.title, status: held.kind,
      more: [more(`version ${held.version}${held.converted ? '' : ', kept as given: not converted'}`), headingsOf(held)],
    }), 'no document is recorded'),
    ...problemsList(view.problems),
  ]);
  replace(document.getElementById('inherited-concerns-body'), [rowsOrNone(view.concerns || [], (concern) => itemRow(project, {
    id: concern.id, title: concern.text, status: concern.status,
    more: [
      ...(concern.sources || []).map((source) => more(`${source.locator}: "${source.text}"`)),
      more([concernStanding(concern), (concern.targets || []).length ? `targets ${concern.targets.join(', ')}` : null].filter(Boolean).join('; ')),
    ],
  }), 'no concern is recorded: a critique’s points and the open comment threads become concerns')]);
  const claims = view.claims || [];
  const unverifiable = view.unverifiable || [];
  replace(document.getElementById('inherited-claims-body'), [
    subhead('claims', claims.length),
    rowsOrNone(claims, (claim) => itemRow(project, {
      id: claim.id, title: claim.text, status: claim.standing,
      more: [more(`${claim.section}, under "${claim.heading}"`), more(verdictLine(claim))],
    }), 'no inherited claim stands'),
    subhead('unverifiable', unverifiable.length),
    rowsOrNone(unverifiable, (claim) => itemRow(project, {
      id: claim.id, title: claim.text, status: 'unverifiable', more: [more(claim.reason || 'no reason given')],
    }), 'no claim was found unverifiable'),
  ]);
  const contradictions = view.contradictions || [];
  const merges = view.merges || [];
  replace(document.getElementById('inherited-pairs-body'), [
    subhead('contradicting pairs', contradictions.length),
    rowsOrNone(contradictions, (pair) => pairRow(project, pair, pair.why || 'they contradict each other', 'contradiction',
      (pair.results || []).length ? [more(`for the verification of ${pair.results.join(', ')}`)] : []),
    'no contradicting pair is listed'),
    subhead('merges at setup', merges.length),
    rowsOrNone(merges, (pair) => pairRow(project, pair, `kept: ${pair.text || ''}`, pair.mark || pair.outcome,
      pair.passage ? [more(null, linkList(project, 'merged into', [pair.passage]))] : []),
    'the setup merged no claims'),
  ]);
  replace(document.getElementById('inherited-material-body'), [rowsOrNone(view.material || [], (item) => itemRow(project, {
    id: item.id, title: item.item, status: item.reply || 'waiting',
    more: [more(`${item.heading}, ${item.kind}${item.licensed ? ', licensed' : ''}; ${item.reply ? `${item.reply}, said by the ${item.by}` : 'no reply yet'}`)],
  }), 'no material is missing')]);
}

// --- Marks (ticket 112) -----------------------------------------------------------------------------------------
//
// Every open batch put before the owner, each item whole with its marks and a note box. A mark saves when
// clicked, through the `mark` action, which calls the `wayline mark` verb's function; a note saves when the
// owner leaves its box, or with the mark clicked while it is still in it. The first answer, here or in the
// conversation, settles an item; a mark given here changes with another click until its batch's producer acts
// on it. "Take all defaults" answers a batch in one click. At phone width one item fills the screen, with
// previous and next. The settled batches follow, folded, newest first.

// A batch's item link, `#/<project>/B3`: it opens Marks at that batch rather than the viewer.
const BATCH_ID = /^B[1-9][0-9]*$/;

// What each kind of batch is called on its card.
const BATCH_KINDS = {
  plots: 'plots',
  objective_changes: 'objective changes',
  software_ask: 'the software ask',
  account_review: 'account review',
  merges: 'merges',
  contradictions: 'contradictions',
  concern_placements: 'concern placements',
  outline_proposals: 'outline proposals',
};

// The kinds whose refs are item ids the viewer opens: a plot or a table, a pair of passages, a concern. An account
// review's `D1` is a decision, not a document, so a ref of any other kind is shown as words.
const LINKED_REFS = new Set(['plots', 'merges', 'contradictions', 'concern_placements']);

const marks = {
  project: null, // the project `view` was read from
  view: null, // the view last read, drawn again when the owner moves between items or a link names a batch
  current: null, // `B1.2`, the item the phone's one screen shows
  order: [], // the open items as last drawn, so an item a click took out of them (its batch closed) hands on to the next
  focus: null, // the batch a link `#/<project>/B3` named, shown once the view is drawn
  notes: {}, // `B1.2` -> a note typed and not saved yet, which a redraw keeps
  saving: {}, // `B1.2` -> the note's save under way, which a mark clicked meanwhile waits for
};

async function loadMarks() {
  const project = state.project;
  if (!project || state.view !== 'marks') return;
  try {
    const view = await get(projectPath('/marks'), 'marks');
    if (project !== state.project) return;
    if (view) {
      if (marks.project !== project) Object.assign(marks, { current: null, order: [], notes: {}, saving: {} });
      Object.assign(marks, { project, view });
    }
    if (view || marks.focus) renderMarks();
  } catch (failure) {
    if (project === state.project) replace(document.getElementById('marks-body'), [errorState(failure)]);
  }
}

function itemKey(batch, item) {
  return `${batch.id}.${item.id}`;
}

function isOpen(item) {
  return item.mark === null || item.mark === undefined;
}

// Where an item stands: open with its default, or its mark with who gave it and where.
function standingLine(item) {
  if (isOpen(item)) return item.default ? `open; its default is ${item.default}` : 'open; it has no default';
  const who = item.by === 'decider' ? 'the decider' : 'you';
  const where = item.via ? ` in the ${item.via}` : '';
  const after = item.changeable ? '; another click changes it until its work acts on it'
    : item.acted ? `; acted on at ${item.acted}` : '';
  return `${item.mark}, by ${who}${where}${item.at ? ` at ${item.at}` : ''}${after}`;
}

// The item whole: a plot's SVG as its drawing wrote it, with its three explanations; a table's explanations and its
// rows in the viewer; a merge's or a contradiction's two texts side by side; a proposal's fields; else its text.
function itemWhole(project, item) {
  const plot = item.plot;
  if (plot) {
    const shown = plot.kind === 'plot' && plot.svg
      ? [el('figure', { class: 'mark-plot' }, [el('img', { src: downloadUrl(plot.svg), alt: `${item.ref}: ${plot.chart_type || 'a plot'}` })])]
      : plot.kind === 'table' ? [el('p', { class: 'note' }, [itemLink(project, item.ref, `the table ${item.ref}`), document.createTextNode(' opens with its rows')])]
        : [el('p', { class: 'mark-text', text: item.text })];
    return [...shown, ...captionOf(plot.caption)];
  }
  if (item.sides) return [sidesOf(item.sides), el('p', { class: 'mark-text', text: item.text })];
  if (item.fields) return [fields(item.fields)];
  return [el('p', { class: 'mark-text', text: item.text })];
}

function markButtons(project, batch, item) {
  const open = isOpen(item);
  return el('div', { class: 'mark-choices acts', role: 'group', 'aria-label': `marks for item ${item.id} of ${batch.id}` }, item.marks.map((name) => {
    const button = el('button', {
      type: 'button', class: `action mark${open && name === item.default ? ' default' : ''}`, text: name,
      'aria-pressed': String(name === item.mark), title: name === item.default ? `${name}, its default` : null,
    });
    button.disabled = !(open || item.changeable);
    // This item's note box keeps the focus, so a note typed and not left yet goes with this mark rather than on its own
    // first; another item's box is left, which saves its note.
    button.addEventListener('mousedown', (event) => {
      const typing = noteInFocus();
      if (typing && typing.key === itemKey(batch, item)) event.preventDefault();
    });
    button.addEventListener('click', () => giveMark(project, batch, item, name));
    return button;
  }));
}

function noteBox(project, batch, item) {
  const key = itemKey(batch, item);
  const box = el('textarea', {
    class: 'mark-note', rows: '2', 'data-key': key, placeholder: 'a note, kept with the item', 'aria-label': `note on item ${item.id} of ${batch.id}`,
  });
  box.value = key in marks.notes ? marks.notes[key] : (item.note || '');
  box.disabled = readOnlyNow() || !(isOpen(item) || item.changeable);
  box.addEventListener('input', () => { marks.notes[key] = box.value; });
  // Saved when the owner leaves the box, whatever drew it: a box a redraw gave back the focus to fires no `change`, so
  // leaving is the moment, and `unsavedNote` sends nothing the item holds already. A box a redraw takes away is not left
  // by the owner: its note is not saved half typed.
  box.addEventListener('blur', () => { if (box.isConnected) saveNote(project, batch, item); });
  return el('label', { class: 'mark-note-label' }, [el('span', { text: 'note' }), box]);
}

// The note typed for an item and not saved yet, or null.
function unsavedNote(item, key) {
  const typed = marks.notes[key];
  return typed !== undefined && typed.trim() && typed !== (item.note || '') ? typed : null;
}

async function giveMark(project, batch, item, name) {
  const key = itemKey(batch, item);
  if (marks.saving[key]) await marks.saving[key];
  const note = unsavedNote(item, key);
  const body = { batch: batch.id, item: item.id, mark: name };
  if (note !== null) body.note = note;
  const reply = await perform('mark', body, () => `${batch.id}, item ${item.id}: ${name}${note !== null ? ' and its note' : ''} saved`, project);
  if (reply && marks.notes[key] === note) delete marks.notes[key];
}

async function saveNote(project, batch, item) {
  const key = itemKey(batch, item);
  const note = unsavedNote(item, key);
  if (note === null) return;
  const saving = perform('mark', { batch: batch.id, item: item.id, note }, () => `${batch.id}, item ${item.id}: note saved`, project);
  marks.saving[key] = saving;
  const reply = await saving;
  if (marks.saving[key] === saving) delete marks.saving[key];
  if (reply && marks.notes[key] === note) delete marks.notes[key];
}

function takeDefaults(project, batch) {
  const button = el('button', {
    type: 'button', class: 'action acts', text: `take all defaults (${batch.defaults})`,
    title: `settle each unsettled item of ${batch.id} that has a default with it`,
  });
  button.addEventListener('click', () => perform('mark', { batch: batch.id, defaults: true },
    (reply) => `${batch.id}: ${reply.settled.length} item${reply.settled.length === 1 ? '' : 's'} settled by ${reply.settled.length === 1 ? 'its default' : 'their defaults'}`, project));
  return button;
}

function markItem(project, batch, item) {
  const key = itemKey(batch, item);
  const ref = LINKED_REFS.has(batch.kind) ? itemLink(project, item.ref) : el('span', { class: 'mono', text: item.ref });
  const head = [el('span', { class: 'row-id', text: `${item.id}.` }), ref];
  if (!isOpen(item)) head.push(statusChip(item.mark));
  return el('li', { class: `mark-item${isOpen(item) ? '' : ' settled'}${key === marks.current ? ' current' : ''}`, 'data-item': key }, [
    el('div', { class: 'row-line' }, head),
    ...itemWhole(project, item),
    more(standingLine(item)),
    markButtons(project, batch, item),
    noteBox(project, batch, item),
  ]);
}

function batchCard(project, batch) {
  const acts = [];
  if (batch.decision) acts.push(el('a', { class: 'action', href: routeTo(project, String(batch.decision)), text: `decision ${batch.decision}` }));
  acts.push(insertButton(project, batch.id));
  if (batch.status === 'open' && batch.defaults) acts.push(takeDefaults(project, batch));
  const count = batch.items.length;
  const current = batch.items.some((item) => itemKey(batch, item) === marks.current);
  return el('article', { class: `batch${current ? ' has-current' : ''}`, 'data-batch': batch.id }, [
    el('div', { class: 'row-line batch-head' }, [
      el('span', { class: 'row-id', text: batch.id }),
      el('span', { class: 'row-title', text: batch.title }),
      statusChip(BATCH_KINDS[batch.kind] || batch.kind),
      el('span', { class: 'row-acts' }, acts),
    ]),
    more(batch.status === 'open' ? `${batch.open} of ${count} unsettled` : `settled, ${count} item${count === 1 ? '' : 's'}`),
    el('ol', { class: 'mark-items' }, batch.items.map((item) => markItem(project, batch, item))),
  ]);
}

// Previous and next, which only the phone shows: one item per screen.
function pager(order) {
  const index = order.indexOf(marks.current);
  const step = (by, text) => {
    const button = el('button', { type: 'button', class: 'action', text });
    button.disabled = index + by < 0 || index + by >= order.length;
    button.addEventListener('click', () => {
      marks.current = order[index + by];
      renderMarks();
      const shown = document.querySelector('#marks-body .mark-item.current');
      if (shown && shown.scrollIntoView) shown.scrollIntoView({ block: 'start' });
    });
    return button;
  };
  return el('nav', { class: 'pager', 'aria-label': 'items, one at a time' }, [
    step(-1, 'previous'), el('span', { class: 'pager-at', text: `${index + 1} of ${order.length}` }), step(1, 'next'),
  ]);
}

// The note box the owner is typing in, to give the focus back to once the view is drawn again.
function noteInFocus() {
  const active = document.activeElement;
  if (!active || !active.classList || !active.classList.contains('mark-note')) return null;
  return { key: active.dataset.key, start: active.selectionStart, end: active.selectionEnd };
}

function restoreNote(typing) {
  if (!typing) return;
  const box = [...document.querySelectorAll('#view-marks textarea.mark-note')].find((node) => node.dataset.key === typing.key);
  if (!box || box.disabled) return;
  box.focus();
  if (box.setSelectionRange) box.setSelectionRange(typing.start, typing.end);
}

function renderMarks() {
  const project = state.project;
  if (marks.project !== project || !marks.view) return;
  const view = marks.view;
  const open = view.batches || [];
  const settled = view.settled || [];
  const order = open.flatMap((batch) => batch.items.map((item) => itemKey(batch, item)));
  const named = marks.focus ? open.find((batch) => batch.id === marks.focus) : null;
  if (named) marks.current = itemKey(named, named.items.find(isOpen) || named.items[0]);
  if (!order.includes(marks.current)) {
    // Gone from the open items, its batch closed: the next one that was after it, else the first one still open.
    const after = marks.order.slice(marks.order.indexOf(marks.current) + 1).find((key) => order.includes(key));
    const firstOpen = open.flatMap((batch) => batch.items.filter(isOpen).map((item) => itemKey(batch, item)))[0];
    marks.current = (marks.current && after) || firstOpen || order[order.length - 1] || null;
  }
  marks.order = order;
  const typing = noteInFocus();
  replace(document.getElementById('marks-body'), [
    open.length ? el('div', { class: 'batches' }, open.map((batch) => batchCard(project, batch)))
      : emptyState('nothing waits for a mark: every batch put before you is settled'),
    ...(order.length > 1 ? [pager(order)] : []),
    ...problemsList(view.problems),
  ]);
  replace(document.getElementById('marks-settled-body'), [settled.length
    ? el('div', { class: 'batches' }, settled.map((batch) => el('details', { class: 'batch-fold', 'data-batch': batch.id, open: batch.id === marks.focus ? '' : null }, [
      el('summary', { text: `${batch.id} ${batch.title}` }), batchCard(project, batch),
    ])))
    : emptyState('no batch is settled yet')]);
  restoreNote(typing);
  if (marks.focus) {
    const shown = document.querySelector(`#view-marks [data-batch="${marks.focus}"]`);
    if (shown && shown.scrollIntoView) shown.scrollIntoView({ block: 'start' });
    marks.focus = null;
  }
}

// --- Run's additions: the account and Software ------------------------------------------------------------

async function loadRun() {
  const project = state.project;
  if (!project) return;
  try {
    const view = await get(projectPath('/run'), 'run');
    if (!view || project !== state.project) return;
    renderAccount(view.account, project);
    renderSoftware(view.software);
  } catch (failure) {
    if (project !== state.project) return;
    replace(document.getElementById('account-body'), [errorState(failure)]);
    replace(document.getElementById('software-body'), [errorState(failure)]);
  }
}

function renderAccount(account, project) {
  if (!account.exists) {
    replace(document.getElementById('account-body'), [emptyState('no account yet: code renders it with the general report')]);
    return;
  }
  replace(document.getElementById('account-body'), [rowsOrNone([account], () => itemRow(project, {
    id: 'account', title: 'What wayline did: the account',
    more: [more(`${account.decided ?? '?'} decided for you, ${account.waiting ?? '?'} waiting on you`)],
  }), '')]);
}

function renderSoftware(software) {
  const tools = software.tools || [];
  const matlab = software.matlab;
  const environment = software.environment || {};
  const move = environment.move;
  const parts = [
    subhead('tools.json', tools.length),
    tableOrNone(['tool', 'version', 'installer', 'executable'], tools.map((tool) => [tool.name, tool.version, tool.installer, tool.executable]),
      'tools.json records no tool yet: wayline tools install', ['short', 'short', 'short', 'text']),
    subhead('MATLAB'),
  ];
  if (!matlab) parts.push(emptyState('no MATLAB is recorded, and no check of one has run'));
  else {
    const check = matlab.check;
    parts.push(fields([
      ['recorded', matlab.version ? `${matlab.version} (${matlab.release || 'release unknown'}) at ${matlab.executable}` : 'not recorded'],
      ['toolboxes', (matlab.toolboxes || []).length ? matlab.toolboxes.join(', ') : null],
      ['the check', check ? `${check.outcome}${check.reason ? `: ${check.reason}` : ''} (${check.ts})` : 'no matlab -batch "ver" check has run'],
    ]));
  }
  parts.push(subhead('environment'), fields([
    ['setting', environment.setting],
    ['place', environment.place || 'the shared tools'],
    ['move', move ? `to ${move.to} from ${move.from}, since ${move.started} (pid ${move.pid})` : 'none under way'],
  ]));
  replace(document.getElementById('software-body'), parts);
}

// --- the new decision kinds' cards ----------------------------------------------------------------------------

const KIND_NAMES = {
  objective_changes: 'objective changes',
  software: 'software',
  empty_frontier: 'empty frontier',
  concern: 'a concern to sort',
  verification_gap: 'a verification gap',
};

function kindFields(decision, project) {
  const about = decision.about || {};
  if (!decision.kind || decision.kind === 'decision') return [];
  const pairs = [['kind', KIND_NAMES[decision.kind] || decision.kind]];
  if (decision.kind === 'objective_changes') pairs.push(['round', about.round]);
  if (decision.kind === 'software') {
    pairs.push(['tool', about.tool], ['licensed', about.licensed ? 'yes: the owner installs it and says where' : 'no'],
      ['asks about', about.gap ? 'a gap in the installed tool' : 'installing it'],
      ['recorded', about.recorded ? `version ${about.version || 'unknown'}` : 'not yet']);
  }
  if (decision.kind === 'empty_frontier') pairs.push(['objective', `${about.objective}${about.text ? ` ${about.text}` : ''}`], ['asked', about.asked]);
  if (decision.kind === 'concern') pairs.push(['concern', about.concern], ['status', about.status], ['raised in', (about.sources || []).join(' | ') || null]);
  if (decision.kind === 'verification_gap') {
    pairs.push(['item', about.item], ['missing', about.missing ? `${about.missing}: ${about.what || ''}` : null], ['result', about.heading], ['asked', about.asked]);
  }
  const parts = [fields(pairs)];
  if (decision.kind === 'empty_frontier' && about.objective) parts.push(el('p', { class: 'note' }, [itemLink(project, about.objective, `open ${about.objective}`)]));
  return parts;
}

// --- the theme, and the sections that fold ------------------------------------------------------
//
// Both are the owner's own choice about their own screen, so both are remembered in this browser
// and nowhere else: they are no part of the ledger, and the dashboard stays a view of it. A browser
// that refuses storage (a private window, blocked site data) still works; it just forgets.

const THEMES = [['auto', 'auto'], ['light', 'day'], ['dark', 'night']];
const STORE = { theme: 'wayline.theme', folded: 'wayline.folded', view: 'wayline.view', zoom: 'wayline.viewer.zoom', seen: 'wayline.seen' };

function remember(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (failure) {
    // A browser that will not store it is not a browser that cannot show it.
  }
}

function remembered(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (failure) {
    return null;
  }
}

function setTheme(choice) {
  const theme = THEMES.some(([name]) => name === choice) ? choice : 'auto';
  if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  remember(STORE.theme, theme);
  markChoice(document.getElementById('theme'), theme);
}

function wireTheme() {
  segmented(document.getElementById('theme'), THEMES.map(([name, label]) => ({
    name, label, title: name === 'auto' ? 'follow the system' : `always ${label}`,
  })), setTheme);
  setTheme(remembered(STORE.theme) || 'auto');
}

function foldedNow() {
  return new Set((remembered(STORE.folded) || '').split(',').filter(Boolean));
}

function fold(section, folded) {
  const node = document.getElementById(section);
  if (!node) return;
  node.classList.toggle('folded', folded);
  const button = node.querySelector('button.fold');
  if (button) button.setAttribute('aria-expanded', String(!folded));
  // A graph unfolded can be measured again.
  if (!folded && section === 'graph') drawGraph();
}

// Fold or open a section and remember which it is.
function setFolded(section, folded) {
  fold(section, folded);
  const now = foldedNow();
  if (folded) now.add(section);
  else now.delete(section);
  remember(STORE.folded, [...now].join(','));
}

// Every section's heading gets the button that folds it, made here from the page's own sections, as
// the index is, so a section added to the page folds without a second edit.
function wireFolds() {
  const folded = foldedNow();
  for (const section of document.querySelectorAll('main .view > section')) {
    const head = section.querySelector('.view-head');
    const heading = section.querySelector('h2');
    if (!head) continue;
    const button = el('button', { type: 'button', class: 'fold', 'aria-controls': section.id,
                                  'aria-label': `fold ${heading ? heading.textContent.toLowerCase() : section.id}` });
    button.addEventListener('click', () => setFolded(section.id, !section.classList.contains('folded')));
    head.prepend(button);
    fold(section.id, folded.has(section.id));
  }
}

// --- the index -----------------------------------------------------------------------------------
//
// Every section the page is showing, in order, as a list down the left. The list is read off the
// page rather than written out, so a section added to it, or the ticket page and the log tail
// taking the graph's place, shows up here without a second edit. A jump to a folded section opens it:
// asking to go somewhere is asking to see it.

function sectionsShown() {
  return [...document.querySelectorAll('main .view:not([hidden]) > section')].filter((section) => !section.hidden);
}

function buildIndex() {
  const list = document.getElementById('index-list');
  if (!list) return;
  replace(list, sectionsShown().map((section) => {
    const heading = section.querySelector('h2');
    const link = el('a', { href: `#${section.id}`, 'data-section': section.id, text: heading ? heading.textContent : section.id });
    link.addEventListener('click', (event) => {
      event.preventDefault();
      jumpTo(section.id);
    });
    return el('li', {}, [link]);
  }));
  markCurrent();
}

function jumpTo(id) {
  const section = document.getElementById(id);
  if (!section || section.hidden) return;
  if (section.classList.contains('folded')) setFolded(id, false);
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  section.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
  // Where the keyboard is follows where the eye was sent.
  const heading = section.querySelector('h2');
  if (heading) {
    heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: true });
  }
}

// The section being read is the last one whose top has passed under the header.
function markCurrent() {
  const line = headerHeight() + space(5);
  let current = null;
  for (const section of sectionsShown()) {
    if (section.getBoundingClientRect().top <= line) current = section.id;
  }
  if (!current && sectionsShown().length) current = sectionsShown()[0].id;
  for (const link of document.querySelectorAll('#index-list a')) {
    link.setAttribute('aria-current', String(link.dataset.section === current));
  }
}

// The header is sticky and its height depends on how its tabs wrap, so it is measured rather than
// assumed, for the index to sit under it and for a jump to land below it.
function headerHeight() {
  const header = document.querySelector('header');
  return header ? header.getBoundingClientRect().height : 0;
}

function measureHeader() {
  document.documentElement.style.setProperty('--header-h', `${Math.ceil(headerHeight())}px`);
}

function wireIndex() {
  buildIndex();
  measureHeader();
  let pending = false;
  window.addEventListener('scroll', () => {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(() => {
      pending = false;
      markCurrent();
    });
  }, { passive: true });
  // The header's own size is what matters, so it is watched where the browser can; a window resize is
  // the nearest thing where it cannot.
  if (window.ResizeObserver) new ResizeObserver(measureHeader).observe(document.querySelector('header'));
  else window.addEventListener('resize', measureHeader);
}

// --- start ---------------------------------------------------------------------------------------

wireTheme();
wireViewer();
wireFolds();
wireIndex();
wireTicketView();
wireGraph();
wireControls();
wireIntake();
wireFeedback();
intakeEmpty();
if (!TOKEN) say('Actions need the dashboard token: open the URL wayline serve printed, which carries it. The views work without it.');
window.addEventListener('hashchange', route);
route();
every('projects', 5, loadProjects);
