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
      // A project of another research_version is read-only (decision 17): marked with its tag, its files still open.
      text: project.name + (project.active ? ' *' : '') + (project.readable && project.read_only ? ' (' + (project.harness_tag || 'an older tag') + ', read-only)' : ''),
      title: project.path + (project.readable ? '' : ' (the path is gone)')
        + (project.readable && project.read_only ? ' (made with ' + (project.harness_tag || 'an older tag') + ', read-only: wayline upgrade --to that tag, or a new project)' : ''),
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
  const goal = view.goal;
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
    const revised = memo.revised_target === null ? '' : `, revised target ${memo.revised_target}`;
    parts.push(
      subhead('position memo'),
      el('p', { class: 'memo-line', text: `feasibility ${memo.feasibility}, goal ${memo.goal}${revised}; ${memo.cited} prior work cited, ${memo.dropped} dropped. Read ${memo.path} before the grill.` }),
      el('details', { class: 'memo', open: '' }, [el('summary', { text: 'the memo' }), renderMarkdown(view.position.text)]),
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
      ['goal', goal ? `${goal.metric} ${goal.value === null ? 'no reading yet' : goal.value} of ${goal.target} (${goal.direction})${goal.reached ? ' reached' : ''}` : 'none set'],
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
    renderMarkdown(view.body),
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
  parts.push(el('div', { id: 'outputs-preview' }));
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
  return el('p', { class: 'inline' }, buttons);
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

// --- the theme, and the sections that fold ------------------------------------------------------
//
// Both are the owner's own choice about their own screen, so both are remembered in this browser
// and nowhere else: they are no part of the ledger, and the dashboard stays a view of it. A browser
// that refuses storage (a private window, blocked site data) still works; it just forgets.

const THEMES = [['auto', 'auto'], ['light', 'day'], ['dark', 'night']];
const STORE = { theme: 'wayline.theme', folded: 'wayline.folded', view: 'wayline.view' };

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
  for (const section of document.querySelectorAll('main > section')) {
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
  return [...document.querySelectorAll('main > section')].filter((section) => !section.hidden);
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
wireFolds();
wireIndex();
wireTicketView();
wireGraph();
wireControls();
wireIntake();
wireFeedback();
intakeEmpty();
if (!TOKEN) say('Actions need the dashboard token: open the URL wayline serve printed, which carries it. The views work without it.');
every('projects', 5, loadProjects);
