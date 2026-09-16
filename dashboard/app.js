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

// The columns an id-and-kind table draws: everything but the title is one line of monospace.
const ROW_ID_KIND = ['short', 'short', 'short', 'short', 'text'];
// `dag.svg` draws a project with no tickets as a canvas of no size.
const EMPTY_CANVAS = /viewBox="0 0 0 0"/;

const state = {
  projects: [],
  project: null,
  tags: {},
  since: null, // null means "the tail has not read this project yet": ask by line count, not offset

  openSignature: null, // the open decision tickets last drawn, so a poll that changed nothing leaves their forms alone
  ticket: null, // the ticket id whose page is open, or null when the graph is showing
  log: null, // { kind, id, since } of the log tail that is open, or null

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

function fields(pairs) {
  const list = el('dl', { class: 'fields' });
  for (const [name, value, whole] of pairs) {
    if (value === null || value === undefined || value === '') continue;
    const text = String(value);
    const title = whole === undefined ? (text.length > 60 ? text : null) : String(whole);
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

// Markdown from the ledger is written by workers (models), so it is sanitized before it is shown:
// an unsanitized <script> in a findings file would be a prompt-injection path into the actions the
// dashboard grows in M4. This is the one place any markdown becomes HTML; the ticket pages of
// ticket 12 render through it.
function renderMarkdown(text) {
  const node = el('div', { class: 'markdown' });
  node.innerHTML = DOMPurify.sanitize(marked.parse(text || ''));
  return node;
}

// `columns` names what each column holds: `short` for an id, a count, or a status, which stays on
// one line in the monospace face, and `text` for prose, which wraps inside a readable measure. A
// cell longer than the measure keeps its whole value in its title.
function tableElement(headings, rows, columns) {
  const head = el('tr', {}, headings.map((name, index) => el('th', { class: (columns || [])[index] || null, text: name })));
  const body = rows.map((row) => el('tr', {}, row.map((cell, index) => {
    const text = cell === null || cell === undefined ? '' : String(cell);
    return el('td', { class: (columns || [])[index] || null, text, title: text.length > 60 ? text : null });
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
      text: project.name + (project.active ? ' *' : ''),
      title: project.path + (project.readable ? '' : ' (the path is gone)'),
      'aria-current': String(project.id === state.project),
    });
    if (!project.readable) tab.disabled = true;
    tab.addEventListener('click', () => select(project.id));
    return tab;
  }));
  if (!state.projects.some((project) => project.id === state.project)) {
    const first = state.projects.find((project) => project.active && project.readable) || state.projects.find((project) => project.readable);
    if (first) select(first.id);
    else replace(document.getElementById('overview-body'), [emptyState('no readable project is registered: run wayline init <path>')]);
  }
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
  replace(document.getElementById('overview-body'), [loadingState('reading the ledger')]);
  replace(document.getElementById('graph-body'), [loadingState('drawing the graph')]);
  replace(document.getElementById('outputs-body'), [loadingState('indexing the outputs')]);
  replace(document.getElementById('decisions-open'), [loadingState('reading the open decision tickets')]);
  for (const tab of document.querySelectorAll('button.tab')) {
    tab.setAttribute('aria-current', String(tab.dataset.id === id));
  }
  every('overview', state.pollViews, loadOverview);
  every('graph', state.pollViews, loadGraph);
  every('outputs', state.pollViews, loadOutputs);
  state.openSignature = null;
  // An edit to a control that was never set belongs to the project it was made on.
  dirty.autonomy = false;
  dirty.pacing = false;
  dirty.model_fallback = false;
  every('decisions', state.pollViews, loadDecisions);
  showGraph();
  startTail();
}

// --- the overview -------------------------------------------------------------------------------

async function loadOverview() {
  if (!state.project) return;
  // The render is inside the try with the fetch: a panel that silently keeps saying "loading"
  // tells the owner nothing, so whatever went wrong is shown in its place.
  try {
    const view = await get(`/api/projects/${encodeURIComponent(state.project)}/overview`);
    if (view) renderOverview(view);
  } catch (failure) {
    replace(document.getElementById('overview-body'), [errorState(failure)]);
  }
}

function renderOverview(view) {
  const window_ = view.window || {};
  const goal = view.goal;
  const resources = view.resources || {};
  const cpu = resources.cpu;
  const ram = resources.ram;
  const gpus = resources.gpus;
  const counts = Object.entries(view.counts || {}).filter(([, count]) => count);
  const parts = [
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
      ['hold', view.hold ? view.hold.line : null],
      ['goal', goal ? `${goal.metric} ${goal.value === null ? 'no reading yet' : goal.value} of ${goal.target} (${goal.direction})${goal.reached ? ' reached' : ''}` : 'none set'],
      ['cpu slot', cpu ? `loadavg1 ${cpu.loadavg1} of ${cpu.nproc}, ${cpu.free_cores.length} cores free, ${cpu.free ? 'free' : 'full'}` : null],
      ['ram slot', ram ? `${gib(ram.free_bytes)} free, ${gib(ram.committed_bytes)} committed` : null],
      ['gpu slots', gpus ? (gpus.length ? `${gpus.filter((gpu) => gpu.free).length} free of ${gpus.length}` : 'none detected (CPU-only)') : null],
    ]),
  ];
  parts.push(el('div', { class: 'chips' }, counts.length
    ? counts.map(([status, count]) => el('span', { class: `chip s-${status}`, text: `${status} ${count}` }))
    : [emptyState('no ticket has been written yet')]));
  parts.push(el('hr', { class: 'rule' }));
  // The four counts of a wave, side by side while they fit: none of them is stretched across the
  // page to hold four short columns, and each says in words what a count of zero means.
  const frontierRows = (view.frontier || []).map((entry) => [entry.id, entry.kind, entry.difficulty, entry.role, entry.title]);
  const runningRows = (view.running || []).map((entry) => [entry.id, entry.kind, entry.attempt, entry.role, entry.title]);
  const jobRows = (view.jobs || []).map((job) => [job.id, job.ticket, job.status, job.unit || job.backend]);
  // `blocking` is the scope a decision pauses ("subgraph" or "all"), not a list of ids.
  const decisionRows = (view.decisions || []).map((entry) => [entry.id, entry.title, entry.blocking || '', entry.awaits === 'decider' ? 'the decider' : 'the owner']);
  parts.push(el('div', { class: 'grid' }, [
    el('div', {}, [
      subhead('frontier', frontierRows.length),
      tableOrNone(['id', 'kind', 'd', 'role', 'title'], frontierRows,
        'no ticket is ready to launch: every open ticket is waiting on another', ROW_ID_KIND),
    ]),
    el('div', {}, [
      subhead('running', runningRows.length),
      tableOrNone(['id', 'kind', 'attempt', 'role', 'title'], runningRows, 'no worker is running', ROW_ID_KIND),
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
}

function showTicket() {
  document.getElementById('graph').hidden = true;
  document.getElementById('ticket').hidden = false;
  document.getElementById('logs').hidden = true;
  stopLog();
}

async function loadGraph() {
  if (!state.project) return;
  try {
    const svg = await getText(`/api/projects/${encodeURIComponent(state.project)}/graph.svg`, 'graph');
    if (svg === null) return;
    // A project with no tickets answers with an empty canvas, which draws as nothing at all: the
    // panel says so instead of standing blank.
    if (EMPTY_CANVAS.test(svg)) replace(document.getElementById('graph-body'), [emptyState('no ticket yet: the graph is drawn once the first one is written')]);
    else document.getElementById('graph-body').innerHTML = svg;
  } catch (failure) {
    replace(document.getElementById('graph-body'), [errorState(failure)]);
  }
}

// The SVG's `<a href="#ticket/<id>">` is not meant to navigate: this is a single-page app, so a
// click on it is caught here and turned into `openTicket` instead. The listener is on the
// container, not the links, because `innerHTML` replaces the links themselves on every poll.
document.getElementById('graph-body').addEventListener('click', (event) => {
  const link = event.target.closest('a[href^="#ticket/"]');
  if (!link) return;
  event.preventDefault();
  openTicket(link.getAttribute('href').slice('#ticket/'.length));
});

// --- the ticket page ------------------------------------------------------------------------------

async function openTicket(id) {
  if (!state.project) return;
  state.ticket = id;
  showTicket();
  if (state.ticket !== id || document.getElementById('ticket-body').dataset.ticket !== id) {
    replace(document.getElementById('ticket-body'), [loadingState(`reading ticket ${id}`)]);
  }
  try {
    const view = await get(`/api/projects/${encodeURIComponent(state.project)}/tickets/${encodeURIComponent(id)}`);
    // A second click before this one's fetch returned must not let the first ticket's view land
    // on the page after the page has already moved on to another ticket.
    if (view && state.ticket === id) {
      document.getElementById('ticket-body').dataset.ticket = id;
      renderTicket(view);
    }
  } catch (failure) {
    if (state.ticket === id) replace(document.getElementById('ticket-body'), [errorState(failure)]);
  }
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
    ]),
    ticketActions(f),
    el('hr', { class: 'rule' }),
    subhead('body'),
    renderMarkdown(view.body),
    subhead('context pack', (view.context_pack || []).length),
    listOrNone(view.context_pack, (path) => el('li', { text: path }), 'no file was packed for this ticket'),
    subhead('latest result'),
    view.result ? resultFields(view.result) : emptyState('no attempt has returned a result yet'),
    subhead('findings', (view.findings || []).length),
    listOrNone(view.findings, (finding) => el('li', { text: finding.text }), 'no finding is recorded against this ticket'),
    subhead('session logs', (view.sessions || []).length),
    logList(view.sessions, 'session', (entry) => `attempt ${entry.attempt}${entry.resume ? ` (${entry.resume})` : ''}`,
      'no worker has been launched for this ticket'),
    subhead('job logs', (view.jobs || []).length),
    logList(view.jobs, 'job', (entry) => `${entry.id} (${entry.status})`, 'no job has been queued for this ticket'),
  ];
  replace(document.getElementById('ticket-body'), parts);
}

// `short` cuts a result's value to what the row holds; the whole of it stays in the field's title.
function resultFields(result) {
  return fields(Object.entries(result).map(([key, value]) => [key, short(value), typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)]));
}

function listOrNone(items, render, empty) {
  return (items || []).length ? el('ul', {}, items.map(render)) : emptyState(empty);
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
  state.log = { kind, id, since: null, written: false };
  document.getElementById('logs-tail').textContent = '';
  document.getElementById('logs-note').textContent = `${logName(kind, id)}: reading`;
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
    const note = document.getElementById('logs-note');
    note.textContent = String(failure.message || failure);
    note.className = 'note problems';
    return;
  }
  document.getElementById('logs-note').className = 'note';
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
  document.getElementById('logs-note').textContent = `${logName(current.kind, current.id)}: ${tail.exists ? `${tail.size} bytes` : 'nothing written yet'}`;
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
    parts.push(entries.length
      ? el('ul', { class: 'outputs' }, entries.map((entry) => outputRow(entry)))
      : emptyState(`nothing under ${name} yet`));
  }
  parts.push(el('div', { id: 'outputs-preview' }));
  replace(document.getElementById('outputs-body'), parts);
}

function outputRow(entry) {
  const row = el('li', {}, [
    el('a', { href: downloadUrl(entry.path), text: entry.path, title: entry.path }),
    el('span', { class: 'note', text: humanSize(entry.size) }),
  ]);
  if (PREVIEWABLE_MARKDOWN.test(entry.path) || PREVIEWABLE_IMAGE.test(entry.path)) {
    const view = el('button', { type: 'button', class: 'action', text: 'view' });
    view.addEventListener('click', () => previewOutput(entry));
    row.appendChild(document.createTextNode(' '));
    row.appendChild(view);
  }
  return row;
}

async function previewOutput(entry) {
  const preview = document.getElementById('outputs-preview');
  if (!preview) return;
  if (PREVIEWABLE_IMAGE.test(entry.path)) {
    replace(preview, [el('img', { src: downloadUrl(entry.path), alt: entry.path })]);
    return;
  }
  replace(preview, [loadingState(`reading ${entry.path}`)]);
  try {
    const headers = TOKEN ? { 'X-Wayline-Token': TOKEN } : {};
    const response = await fetch(downloadUrl(entry.path), { cache: 'no-store', headers });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    replace(preview, [renderMarkdown(await response.text())]);
  } catch (failure) {
    replace(preview, [errorState(failure)]);
  }
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
    const note = document.getElementById('journal-note');
    note.textContent = String(failure.message || failure);
    note.className = 'note problems';
    return;
  }
  document.getElementById('journal-note').className = 'note';
  if (!tail) return;
  if (tail.truncated) document.getElementById('journal-tail').replaceChildren();
  state.since = tail.next;
  appendEvents(tail.events);
  document.getElementById('journal-note').textContent = `${tail.size} bytes, reading from ${tail.next}`;
}

function startStream() {
  const query = new URLSearchParams({ transport: 'sse', since: String(state.since ?? 0) });
  if (TOKEN) query.set('token', TOKEN);
  const stream = new EventSource(`/api/projects/${encodeURIComponent(state.project)}/journal?${query}`);
  stream.addEventListener('message', (message) => {
    state.since = Number(message.lastEventId) || state.since;
    try {
      appendEvents([JSON.parse(message.data)]);
    } catch (failure) {
      // A torn line the ledger closes on its next append; the next id carries the whole line.
    }
    document.getElementById('journal-note').textContent = `streaming, at offset ${state.since}`;
  });
  stream.addEventListener('error', () => {
    const note = document.getElementById('journal-note');
    note.textContent = 'stream dropped; the browser reconnects in 2 s with Last-Event-ID';
    note.className = 'note problems';
  });
  state.stream = stream;
}

function appendEvents(events) {
  const tail = document.getElementById('journal-tail');
  const atBottom = tail.scrollTop + tail.clientHeight >= tail.scrollHeight - 8;
  // A journal with nothing in it yet says so, and the line goes as soon as the first event lands.
  const blank = tail.querySelector('li.state');
  if ((events || []).length && blank) blank.remove();
  if (!(events || []).length && !tail.childElementCount) {
    tail.appendChild(el('li', { class: 'state', text: 'no event has been journaled for this project yet' }));
  }
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
      el('span', { class: 'payload', text: detail, title: Object.keys(payload).length ? JSON.stringify(payload) : null }),
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

function say(text, failed) {
  const note = document.getElementById('action-note');
  note.textContent = text;
  note.className = failed ? 'note problems' : 'note';
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
  loadGraph();
}

// --- the controls (ticket 35) ------------------------------------------------------------------

// A control the owner changed and has not set yet keeps what they chose while the views poll.
const dirty = { autonomy: false, pacing: false, model_fallback: false };

function renderControls(controls) {
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
  document.getElementById('autonomy-current').textContent = controls.autonomy
    ? `now ${controls.autonomy}; raised at any time, lowered only while no conductor runs` : '';
  document.getElementById('active-state').textContent = controls.active ? 'this is the active project' : 'another project is active';
  document.getElementById('pause-state').textContent = controls.paused_by_owner
    ? 'paused by the owner: nothing that needs a model launches' : 'not paused by the owner';
  for (const id of ['autonomy-set', 'pacing-set', 'model-fallback-set', 'pause-button', 'resume-button']) document.getElementById(id).disabled = !TOKEN;
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
  return el('p', { class: 'inline' }, buttons);
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
  }
}

function renderDecisions(view, project) {
  renderControls(view.controls || {});
  const open = view.open || [];
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
  const parts = [subhead("decision log, the decider's first", log.length)];
  parts.push(tableOrNone(['decided by', 'ticket', 'question', 'answer', 'rationale', 'when'], log.map((entry) => [
    entry.decided_by + (entry.superseded ? ' (superseded)' : ''),
    entry.ticket === null ? (entry.id || '') : `#${entry.ticket}`,
    entry.question || '',
    entry.answer,
    entry.rationale || '',
    (entry.ts || '').replace('T', ' ').replace('Z', ''),
  ]), 'nothing has been decided on this project yet', ['short', 'short', 'text', 'text', 'text', 'short']));
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
  const form = el('form', { class: 'answer-form' });
  for (const option of decision.options || []) {
    const input = el('input', { type: 'radio', name: `choice-${decision.id}`, value: option });
    input.checked = draft.choice === option;
    input.addEventListener('change', () => { draft.choice = option; });
    form.appendChild(el('label', { class: 'option' }, [input, document.createTextNode(` ${option}${option === decision.recommended ? ' (recommended)' : ''}`)]));
  }
  const text = el('textarea', {
    rows: '2', placeholder: (decision.options || []).length ? 'or an answer in your own words' : 'the answer', 'aria-label': `the answer to ticket ${decision.id}`,
  });
  text.value = draft.text;
  text.addEventListener('input', () => { draft.text = text.value; });
  const rationale = el('textarea', { rows: '2', placeholder: 'why (optional; journaled with the answer)', 'aria-label': `why, for ticket ${decision.id}` });
  rationale.value = draft.rationale;
  rationale.addEventListener('input', () => { draft.rationale = rationale.value; });
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

// --- the intake drop zone (ticket 35) ----------------------------------------------------------

async function upload(files) {
  const list = document.getElementById('intake-list');
  for (const file of Array.from(files || [])) {
    const row = el('li', { text: `${file.name}: sending ${humanSize(file.size)}...` });
    list.prepend(row);
    try {
      const reply = await act('intake', file, { 'X-Wayline-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' });
      let where = 'INTAKE.md already lists it';
      if (reply.taken === null) where = 'there is no INTAKE.md yet, so the next wayline intake takes it';
      else if (reply.taken.length) where = `added to INTAKE.md under ${reply.taken.join(', ')}`;
      row.textContent = `${file.name}: kept as ${reply.path} (${humanSize(reply.size)}); ${where}`;
    } catch (failure) {
      row.textContent = `${file.name}: ${failure.message || failure}`;
      row.className = 'problems';
    }
  }
  refreshViews();
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

// --- start ---------------------------------------------------------------------------------------

wireControls();
wireIntake();
if (!TOKEN) say('Actions need the dashboard token: open the URL wayline serve printed, which carries it. The views work without it.');
every('projects', 5, loadProjects);
