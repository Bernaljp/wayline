"""PROTOTYPE, throwaway: renders both reports and the cost record into one HTML page for the owner.

`python3 build_page.py` writes page.html: three tabs (general report, current report, cost and
questions), every plot inlined as a data URI, provenance tags shown as small chips, and under
each plot a keep / maybe / drop mark with a note, saved to the artifact's db (`reactions/<id>`,
`answers/q1..q5`) so the owner's reaction can be read back.
"""

import base64
import html
import re
from pathlib import Path

import markdown

HERE = Path(__file__).parent
PLOT_HEAD = re.compile(r"^### ([PC]\d\d) · (.*)$")


def prepare(md):
    """Split the per-plot lines into paragraphs and wrap each plot in a section."""
    md = re.sub(r"\n(\*\*(?:Purpose|Data|What it shows)\.\*\*)", r"\n\n\1", md)
    md = re.sub(r"\n(\*Index:\*)", r"\n\n\1", md)
    out, open_id = [], None
    for line in md.split("\n"):
        m = PLOT_HEAD.match(line)
        boundary = m or line.startswith("## ") or line.strip() == "---"
        if boundary and open_id:
            out += ["", f'<div class="react" data-plot="{open_id}"></div>', "", "</section>", ""]
            open_id = None
        if m:
            open_id = m.group(1)
            out += ["", f'<section class="plot" id="{open_id}" markdown="1">', ""]
        out.append(line)
    if open_id:
        out += ["", f'<div class="react" data-plot="{open_id}"></div>', "", "</section>", ""]
    return "\n".join(out)


def tag_chip(m):
    kind, body = m.group(1), m.group(2)
    short = body
    rm = re.match(r"^(t\d+-a\d+)/(?:.*/)?([^/#]+)#(.+)$", body)
    if rm:
        short = f"{rm.group(1)} · {rm.group(2)}#{rm.group(3)}"
    return f'<span class="tag" title="{html.escape(kind + ":" + body)}">{html.escape(short)}</span>'


def render(md_text):
    body = markdown.markdown(prepare(md_text), extensions=["tables", "md_in_html"])
    body = re.sub(r"\{(res|ref):([^{}]+)\}", tag_chip, body)
    body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    body = re.sub(r"<p><strong>(Purpose|Data|What it shows)\.</strong>",
                  lambda m: f'<p class="k k-{m.group(1).split()[0].lower()}"><strong>{m.group(1)}.</strong>', body)
    body = re.sub(r"<p><em>Index:</em>", '<p class="idx"><em>Index:</em>', body)

    def inline(m):
        path = HERE / m.group(1)
        data = base64.b64encode(path.read_bytes()).decode()
        return f'<img loading="lazy" alt="{html.escape(m.group(1).split("/")[-1])}" src="data:image/png;base64,{data}"'

    body = re.sub(r'<img alt="" src="([^"]+\.png)"', inline, body)
    return body


general = render((HERE / "general-report.md").read_text())
current = render((HERE / "current-report.md").read_text())
cost = render((HERE / "cost.md").read_text())
n_plots = len(re.findall(r'class="plot"', general + current))

QUESTIONS = [
    ("q1", "Which plots were useful?", "Your marks under each plot answer this. Add anything the marks miss: a kind of plot you want that is not here, or one you never want to see again."),
    ("q2", "How much explanation is right?", "Each plot carries Purpose, Data, and What it shows. Too much, too little, or the wrong kind?"),
    ("q3", "What should a current report cover?", "The current report covers one line of work at full depth. Is that the right unit, and the right depth?"),
    ("q4", "How should the general report be organized?", "By objective, then by result, with a summary table first and the run's own account left out."),
    ("q5", "Is the cost acceptable?", "One fresh Sonnet session per result: about 80,000 tokens and three minutes for 16 plots. See the figures above."),
]
qhtml = "\n".join(
    f'<div class="q"><label for="{qid}"><span class="qn">{i + 1}</span> {html.escape(q)}</label>'
    f'<p class="qh">{html.escape(h)}</p><textarea id="{qid}" data-q="{qid}" rows="3" placeholder="Your answer, in your own words"></textarea>'
    f'<span class="saved" data-saved="{qid}"></span></div>'
    for i, (qid, q, h) in enumerate(QUESTIONS))

PAGE = r"""<title>Toy Research Reports</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Serif:wght@500;600&display=swap">
<style>
/* Layout: a lab-notebook reading column under a slim sticky tab bar; each plot is a numbered specimen with a reaction tray beneath it. */
:root {
  --paper: #f3f6f4; --ink: #17211d; --muted: #5a6a63; --rule: #d3dcd7; --plate: #ffffff; --plate-ink: #17211d;
  --accent: #00785a; --accent-soft: #dcefe7; --keep: #00785a; --maybe: #9a6400; --drop: #b03f2c;
  --chip: #e6ece9;
  --f-display: "IBM Plex Serif", Georgia, "Times New Roman", serif;
  --f-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper: #111714; --ink: #e2eae6; --muted: #93a39c; --rule: #2b3631; --plate: #ffffff; --plate-ink: #17211d;
  --accent: #46c79d; --accent-soft: #1a2e26; --keep: #46c79d; --maybe: #e0a83a; --drop: #f07a62; --chip: #1f2a25;
  color-scheme: dark } }
:root[data-theme="dark"] {
  --paper: #111714; --ink: #e2eae6; --muted: #93a39c; --rule: #2b3631; --plate: #ffffff; --plate-ink: #17211d;
  --accent: #46c79d; --accent-soft: #1a2e26; --keep: #46c79d; --maybe: #e0a83a; --drop: #f07a62; --chip: #1f2a25;
  color-scheme: dark }
body { background: var(--paper); color: var(--ink); font: 15px/1.6 var(--f-body); }
.wrap { max-width: 50rem; margin: 0 auto; padding-inline: 16px; padding-block: 0 4rem; }
header.top { padding-block: 2rem 1rem; display: grid; gap: .6rem; }
.eyebrow { font: 500 .72rem/1 var(--f-mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1, h2, h3 { font-family: var(--f-display); text-wrap: balance; line-height: 1.25; }
header.top h1 { font-size: 2rem; margin: 0; }
.lede { margin: 0; color: var(--muted); max-width: 40rem; }
.tally { font: .8rem/1.4 var(--f-mono); font-variant-numeric: tabular-nums; color: var(--muted); display: flex; flex-wrap: wrap; gap: .4rem 1rem; }
.tally b { color: var(--ink); font-weight: 500; }
.tally .k1 { color: var(--keep); } .tally .k2 { color: var(--maybe); } .tally .k3 { color: var(--drop); }
nav.tabs { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--paper); border-bottom: 1px solid var(--rule); }
nav.tabs .in { max-width: 50rem; margin: 0 auto; padding-inline: 16px; display: flex; gap: .25rem; overflow-x: auto; }
nav.tabs button { font: 600 .85rem/1 var(--f-body); color: var(--muted); background: none; border: 0; border-bottom: 2px solid transparent; padding: .9rem .7rem .75rem; cursor: pointer; white-space: nowrap; }
nav.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--accent); }
nav.tabs button:focus-visible, .react button:focus-visible, textarea:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.notice { font-size: .85rem; color: var(--muted); border-left: 3px solid var(--rule); padding: .2rem 0 .2rem .8rem; margin: 1.2rem 0 0; }
article h1 { font-size: 1.6rem; margin: 2rem 0 .5rem; }
article h2 { font-size: 1.3rem; margin: 2.8rem 0 .6rem; padding-top: .4rem; border-top: 2px solid var(--ink); }
article h3 { font-size: 1.02rem; margin: 0 0 .6rem; }
article p, article li { max-width: 65ch; }
article hr { display: none; }
article ul { padding-left: 1.2rem; display: grid; gap: .35rem; }
.tw { overflow-x: auto; margin: 1rem 0; }
table { border-collapse: collapse; font-size: .8rem; font-variant-numeric: tabular-nums; min-width: 32rem; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: .75rem; }
.tag { display: inline-block; font: .68rem/1.5 var(--f-mono); background: var(--chip); color: var(--muted); border-radius: 3px; padding: 0 .35rem; margin: 0 .1rem; vertical-align: .08em; word-break: break-all; }
section.plot { margin: 1.6rem 0; padding-top: 1.2rem; border-top: 1px solid var(--rule); display: grid; gap: .5rem; min-width: 0; }
section.plot h3 { margin: 0; }
section.plot p { margin: 0; }
section.plot img { display: block; background: var(--plate); padding: .5rem; border-radius: 4px; max-width: 100%; height: auto; cursor: zoom-in; border: 1px solid var(--rule); }
p.k strong { font-family: var(--f-mono); font-weight: 500; font-size: .74rem; letter-spacing: .04em; text-transform: uppercase; color: var(--accent); margin-right: .3rem; }
p.idx { font-size: .8rem; color: var(--muted); }
.react { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: .3rem; padding: .55rem .6rem; background: var(--accent-soft); border-radius: 6px; }
.react .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 5px; overflow: hidden; background: var(--paper); }
.react button { font: 600 .78rem/1 var(--f-body); padding: .5rem .75rem; border: 0; background: none; color: var(--muted); cursor: pointer; }
.react button + button { border-left: 1px solid var(--rule); }
.react button[aria-pressed="true"][data-mark="keep"] { background: var(--keep); color: var(--paper); }
.react button[aria-pressed="true"][data-mark="maybe"] { background: var(--maybe); color: var(--paper); }
.react button[aria-pressed="true"][data-mark="drop"] { background: var(--drop); color: var(--paper); }
.react input { flex: 1 1 12rem; min-width: 0; font: .85rem var(--f-body); padding: .45rem .55rem; border: 1px solid var(--rule); border-radius: 5px; background: var(--paper); color: var(--ink); }
.react .pid { font: 500 .75rem var(--f-mono); color: var(--muted); }
.saved { font: .72rem var(--f-mono); color: var(--muted); }
.q { display: grid; gap: .35rem; margin: 1.4rem 0; }
.q label { font: 600 1rem var(--f-display); }
.qn { font: 500 .75rem var(--f-mono); color: var(--paper); background: var(--accent); border-radius: 3px; padding: .05rem .4rem; margin-right: .3rem; vertical-align: .1em; }
.qh { margin: 0; color: var(--muted); font-size: .88rem; }
textarea { font: .92rem/1.5 var(--f-body); padding: .6rem; border: 1px solid var(--rule); border-radius: 6px; background: var(--plate); color: var(--plate-ink); resize: vertical; }
dialog#zoom { border: 0; padding: 0; background: var(--plate); max-width: 96vw; max-height: 94vh; overflow: auto; border-radius: 6px; }
dialog#zoom::backdrop { background: rgba(10, 15, 13, .7); }
dialog#zoom img { display: block; width: min(1400px, 94vw); height: auto; cursor: zoom-out; }
@media (prefers-reduced-motion: no-preference) { .react button { transition: background .12s, color .12s; } }
</style>

<header class="top wrap">
  <span class="eyebrow">Prototype · map ticket “A research report to react to”</span>
  <h1>Toy Research Reports</h1>
  <p class="lede">Two research reports built from the toy project’s results: a general report on everything found so far, and a current report on one line of work. Mark each plot keep, maybe, or drop, and answer the five questions at the end.</p>
  <div class="tally" id="tally"><span><b id="t-marked">0</b> of __N__ plots marked</span><span class="k1">keep <b id="t-keep">0</b></span><span class="k2">maybe <b id="t-maybe">0</b></span><span class="k3">drop <b id="t-drop">0</b></span><span id="t-state"></span></div>
</header>
<nav class="tabs" aria-label="Reports"><div class="in" role="tablist">
  <button role="tab" id="tab-general" aria-controls="general" aria-selected="true">General report · P01 to P27</button>
  <button role="tab" id="tab-current" aria-controls="current" aria-selected="false">Current report · C01 to C16</button>
  <button role="tab" id="tab-react" aria-controls="react" aria-selected="false">Cost and questions</button>
</div></nav>
<main class="wrap">
<p class="notice" id="dbnote" hidden>Marks and answers are saved only in a signed-in view on claude.ai. Here they stay on this screen.</p>
<article id="general" role="tabpanel" aria-labelledby="tab-general">__GENERAL__</article>
<article id="current" role="tabpanel" aria-labelledby="tab-current" hidden>__CURRENT__</article>
<article id="react" role="tabpanel" aria-labelledby="tab-react" hidden>
<h1>Your reaction</h1>
<p>Each answer is saved as you type. Write it the way you would say it; nothing here needs a particular form.</p>
__QUESTIONS__
__COST__
</article>
</main>
<dialog id="zoom"><img alt="enlarged plot"></dialog>
<script>
(() => {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function show(id) {
    tabs.forEach(t => { const on = t.getAttribute('aria-controls') === id; t.setAttribute('aria-selected', on); document.getElementById(t.getAttribute('aria-controls')).hidden = !on; });
  }
  tabs.forEach(t => t.addEventListener('click', () => { show(t.getAttribute('aria-controls')); try { localStorage.setItem('tab', t.getAttribute('aria-controls')); } catch (e) {} window.scrollTo({ top: 0 }); }));
  const h = location.hash.slice(1);
  let start = ['general', 'current', 'react'].includes(h) ? h : null;
  if (!start && /^[PC]\d\d$/.test(h)) start = h[0] === 'P' ? 'general' : 'current';
  if (!start) { try { start = localStorage.getItem('tab'); } catch (e) {} }
  if (start && document.getElementById(start)) show(start);
  if (/^[PC]\d\d$/.test(h)) document.getElementById(h)?.scrollIntoView();

  const zoom = document.getElementById('zoom');
  document.querySelectorAll('section.plot img').forEach(img => img.addEventListener('click', () => { zoom.querySelector('img').src = img.src; zoom.showModal(); }));
  zoom.addEventListener('click', () => zoom.close());

  const marks = {};
  let db = null;
  function tally() {
    const v = Object.values(marks);
    document.getElementById('t-marked').textContent = v.filter(x => x.mark).length;
    for (const k of ['keep', 'maybe', 'drop']) document.getElementById('t-' + k).textContent = v.filter(x => x.mark === k).length;
  }
  function paint(id) {
    const tray = document.querySelector(`.react[data-plot="${id}"]`);
    if (!tray) return;
    tray.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', marks[id]?.mark === b.dataset.mark));
    const inp = tray.querySelector('input');
    if (document.activeElement !== inp) inp.value = marks[id]?.note || '';
  }
  const timers = {};
  async function save(id) {
    if (!db) return;
    const st = document.querySelector(`.react[data-plot="${id}"] .saved`);
    try { await db.doc('reactions/' + id).set({ mark: marks[id].mark || null, note: marks[id].note || '', updated: new Date().toISOString() }); st.textContent = 'saved'; }
    catch (e) { st.textContent = e && e.code === 'invalid_argument' ? 'not saved: this view cannot write' : 'not saved, try again'; }
  }
  document.querySelectorAll('.react').forEach(tray => {
    const id = tray.dataset.plot;
    tray.innerHTML = `<span class="pid">${id}</span><span class="seg" role="group" aria-label="Mark ${id}">` +
      ['keep', 'maybe', 'drop'].map(m => `<button type="button" data-mark="${m}" aria-pressed="false">${m[0].toUpperCase() + m.slice(1)}</button>`).join('') +
      `</span><input id="note-${id}" type="text" placeholder="Note on ${id} (optional)" aria-label="Note on ${id}"><span class="saved"></span>`;
    tray.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      marks[id] = marks[id] || {};
      marks[id].mark = marks[id].mark === b.dataset.mark ? null : b.dataset.mark;
      paint(id); tally(); save(id);
    }));
    const inp = tray.querySelector('input');
    inp.addEventListener('input', () => { marks[id] = marks[id] || {}; marks[id].note = inp.value; clearTimeout(timers[id]); timers[id] = setTimeout(() => save(id), 900); });
  });
  const qtimers = {};
  document.querySelectorAll('textarea[data-q]').forEach(ta => {
    ta.addEventListener('input', () => {
      clearTimeout(qtimers[ta.id]);
      qtimers[ta.id] = setTimeout(async () => {
        if (!db) return;
        const st = document.querySelector(`[data-saved="${ta.id}"]`);
        try { await db.doc('answers/' + ta.id).set({ text: ta.value, updated: new Date().toISOString() }); st.textContent = 'saved'; }
        catch (e) { st.textContent = 'not saved, try again'; }
      }, 1000);
    });
  });

  (async () => {
    db = window.claude && window.claude.use ? await window.claude.use('db') : null;
    if (!db) { document.getElementById('dbnote').hidden = false; return; }
    db.collection('reactions').onSnapshot(snap => {
      snap.docs.forEach(d => { if (d.exists) { marks[d.id] = { ...d.data() }; paint(d.id); } });
      tally();
    }, () => { document.getElementById('t-state').textContent = 'marks not loading'; });
    db.collection('answers').onSnapshot(snap => {
      snap.docs.forEach(d => { const ta = document.getElementById(d.id); if (ta && d.exists && document.activeElement !== ta) ta.value = d.data().text || ''; });
    }, () => {});
  })();
})();
</script>
"""

page = (PAGE.replace("__N__", str(n_plots)).replace("__GENERAL__", general).replace("__CURRENT__", current)
        .replace("__QUESTIONS__", qhtml).replace("__COST__", cost))
(HERE / "page.html").write_text(page)
print("page.html", round(len(page) / 1e6, 2), "MB,", n_plots, "plots")
