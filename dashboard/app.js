// The read-only dashboard's front end (Implementation Decisions 8). No framework, no build step.
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

const state = {
  projects: [],
  project: null,
  tags: {},
  since: null, // null means "the tail has not read this project yet": ask by line count, not offset

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

function fields(pairs) {
  const list = el('dl', { class: 'fields' });
  for (const [name, value] of pairs) {
    if (value === null || value === undefined || value === '') continue;
    list.appendChild(el('dt', { text: name }));
    list.appendChild(el('dd', { text: String(value) }));
  }
  return list;
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

function table(headings, rows) {
  const head = el('tr', {}, headings.map((name) => el('th', { text: name })));
  const body = rows.map((row) => el('tr', {}, row.map((cell) => el('td', { text: cell === null || cell === undefined ? '' : String(cell) }))));
  return el('table', {}, [el('thead', {}, [head]), el('tbody', {}, body)]);
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
    else replace(document.getElementById('overview-body'), [el('p', { text: 'no readable project is registered; run wayline init <path>' })]);
  }
}

function select(id) {
  if (state.project === id) return;
  state.project = id;
  state.since = null;
  state.tags = {};
  document.getElementById('journal-tail').replaceChildren();
  for (const tab of document.querySelectorAll('button.tab')) {
    tab.setAttribute('aria-current', String(tab.dataset.id === id));
  }
  every('overview', state.pollViews, loadOverview);
  every('graph', state.pollViews, loadGraph);
  every('outputs', state.pollViews, loadOutputs);
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
    replace(document.getElementById('overview-body'), [el('p', { class: 'problems', text: String(failure.message || failure) })]);
  }
}

function renderOverview(view) {
  const window_ = view.window || {};
  const goal = view.goal;
  const resources = view.resources || {};
  const cpu = resources.cpu;
  const ram = resources.ram;
  const gpus = resources.gpus;
  const counts = Object.entries(view.counts || {}).filter(([, count]) => count).map(([status, count]) => `${status} ${count}`).join('   ');
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
      ['tickets', counts || 'none'],
    ]),
  ];
  parts.push(el('h3', { text: `frontier (${(view.frontier || []).length})` }));
  parts.push(table(['id', 'kind', 'd', 'role', 'title'], (view.frontier || []).map((entry) => [entry.id, entry.kind, entry.difficulty, entry.role, entry.title])));
  parts.push(el('h3', { text: `running (${(view.running || []).length})` }));
  parts.push(table(['id', 'kind', 'attempt', 'role', 'title'], (view.running || []).map((entry) => [entry.id, entry.kind, entry.attempt, entry.role, entry.title])));
  parts.push(el('h3', { text: `jobs (${(view.jobs || []).length})` }));
  parts.push(table(['id', 'ticket', 'status', 'unit'], (view.jobs || []).map((job) => [job.id, job.ticket, job.status, job.unit || job.backend])));
  // `blocking` is the scope a decision pauses ("subgraph" or "all"), not a list of ids.
  parts.push(el('h3', { text: `open decisions (${(view.decisions || []).length})` }));
  parts.push(table(['id', 'title', 'blocking', 'asks'], (view.decisions || []).map((entry) => [entry.id, entry.title, entry.blocking || '', entry.human_only ? 'the human' : 'the decider'])));
  if ((view.problems || []).length) {
    parts.push(el('h3', { text: `problems (${view.problems.length})` }));
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
    if (svg !== null) document.getElementById('graph-body').innerHTML = svg;
  } catch (failure) {
    replace(document.getElementById('graph-body'), [el('p', { class: 'problems', text: String(failure.message || failure) })]);
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
  try {
    const view = await get(`/api/projects/${encodeURIComponent(state.project)}/tickets/${encodeURIComponent(id)}`);
    // A second click before this one's fetch returned must not let the first ticket's view land
    // on the page after the page has already moved on to another ticket.
    if (view && state.ticket === id) renderTicket(view);
  } catch (failure) {
    if (state.ticket === id) replace(document.getElementById('ticket-body'), [el('p', { class: 'problems', text: String(failure.message || failure) })]);
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
    el('h3', { text: 'body' }),
    renderMarkdown(view.body),
    el('h3', { text: `context pack (${(view.context_pack || []).length})` }),
    listOrNone(view.context_pack, (path) => el('li', { text: path })),
    el('h3', { text: 'latest result' }),
    view.result ? resultFields(view.result) : el('p', { class: 'note', text: 'no attempt has returned a result yet' }),
    el('h3', { text: `findings (${(view.findings || []).length})` }),
    listOrNone(view.findings, (finding) => el('li', { text: finding.text })),
    el('h3', { text: 'session logs' }),
    logList(view.sessions, 'session', (entry) => `attempt ${entry.attempt}${entry.resume ? ` (${entry.resume})` : ''}`),
    el('h3', { text: 'job logs' }),
    logList(view.jobs, 'job', (entry) => `${entry.id} (${entry.status})`),
  ];
  replace(document.getElementById('ticket-body'), parts);
}

function resultFields(result) {
  return fields(Object.entries(result).map(([key, value]) => [key, short(value)]));
}

function listOrNone(items, render) {
  return (items || []).length ? el('ul', {}, items.map(render)) : el('p', { class: 'note', text: 'none' });
}

function logList(entries, kind, label) {
  return listOrNone(entries, (entry) => {
    const button = el('button', { type: 'button', class: 'tab', text: label(entry) });
    button.addEventListener('click', () => openLog(kind, entry.id));
    return el('li', {}, [button]);
  });
}

// --- the log tail -----------------------------------------------------------------------------------

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
  state.log = { kind, id, since: null };
  document.getElementById('logs-tail').textContent = '';
  document.getElementById('logs-note').textContent = `${kind} ${id}`;
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
    document.getElementById('logs-note').textContent = String(failure.message || failure);
    return;
  }
  if (!tail || current !== state.log) return;
  if (tail.truncated) document.getElementById('logs-tail').textContent = '';
  current.since = tail.next;
  if (tail.text) document.getElementById('logs-tail').textContent += tail.text;
  document.getElementById('logs-note').textContent = `${current.kind} ${current.id} — ${tail.exists ? `${tail.size} bytes` : 'nothing written yet'}`;
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
    replace(document.getElementById('outputs-body'), [el('p', { class: 'problems', text: String(failure.message || failure) })]);
  }
}

function renderOutputs(view) {
  const parts = [];
  for (const name of CATEGORIES) {
    const entries = view[name] || [];
    parts.push(el('h3', { text: `${name} (${entries.length})` }));
    parts.push(entries.length
      ? el('ul', { class: 'outputs' }, entries.map((entry) => outputRow(entry)))
      : el('p', { class: 'note', text: 'none' }));
  }
  parts.push(el('div', { id: 'outputs-preview' }));
  replace(document.getElementById('outputs-body'), parts);
}

function outputRow(entry) {
  const row = el('li', {}, [
    el('a', { href: downloadUrl(entry.path), text: entry.path }),
    el('span', { class: 'note', text: ` ${humanSize(entry.size)}` }),
  ]);
  if (PREVIEWABLE_MARKDOWN.test(entry.path) || PREVIEWABLE_IMAGE.test(entry.path)) {
    const view = el('button', { type: 'button', class: 'tab', text: 'view' });
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
  replace(preview, [el('p', { class: 'note', text: 'loading...' })]);
  try {
    const headers = TOKEN ? { 'X-Wayline-Token': TOKEN } : {};
    const response = await fetch(downloadUrl(entry.path), { cache: 'no-store', headers });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    replace(preview, [renderMarkdown(await response.text())]);
  } catch (failure) {
    replace(preview, [el('p', { class: 'problems', text: String(failure.message || failure) })]);
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
    document.getElementById('journal-note').textContent = String(failure.message || failure);
    return;
  }
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
    document.getElementById('journal-note').textContent = 'stream dropped; the browser reconnects in 2 s with Last-Event-ID';
  });
  state.stream = stream;
}

function appendEvents(events) {
  const tail = document.getElementById('journal-tail');
  const atBottom = tail.scrollTop + tail.clientHeight >= tail.scrollHeight - 8;
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
      el('span', { class: 'payload', text: detail }),
    ]));
  }
  while (tail.childElementCount > TAIL_LINES) tail.removeChild(tail.firstElementChild);
  if (atBottom) tail.scrollTop = tail.scrollHeight;
}

function gib(bytes) {
  return `${(Number(bytes || 0) / 1024 ** 3).toFixed(1)} GiB`;
}

function short(value) {
  if (Array.isArray(value)) return value.slice(0, 3).join(',') + (value.length > 3 ? '...' : '');
  if (value !== null && typeof value === 'object') return `{${Object.keys(value).length} keys}`;
  const text = String(value);
  return text.length <= 40 ? text : `${text.slice(0, 37)}...`;
}

// --- start ---------------------------------------------------------------------------------------

every('projects', 5, loadProjects);
