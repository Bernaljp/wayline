# 74 - The document viewer: dialog, zoom, KaTeX math, and the sanitizer

**What to build:** Every Markdown file the dashboard opens (documents, reports, sections, the account) opens in one viewer that renders math and zooms on a phone, and a rendered document can no longer restyle the dashboard.

The viewer is a native `<dialog>` opened with `showModal()` outside the panels the dashboard redraws, so a poll never closes or resets it. CSS `zoom` on the document scales it, with the keys `+`, `-`, and `0`, and pinch works at phone width.

Math renders through vendored KaTeX 0.18.9, its woff2 fonts by relative URL so no request leaves the machine, with shims for `\label`, `\eqref`, `\ref`, `\DeclareMathOperator`, `multline`, and redefined macros. One marked extension in `app.js` takes `$...$`, `$$...$$`, `\(...\)`, and `\[...\]` before Markdown reads them, with `emStrongMask` keeping a `*` inside math from pairing. KaTeX renders first with `trust: false`, then `DOMPurify.sanitize(html, {ADD_TAGS: ['semantics', 'annotation'], FORBID_TAGS: ['style']})`. That also closes the v1.0.1 hole by which a rendered document's `<style>` restyled the whole dashboard. A numbered equation written `$$...$$ {#eq:label}` renders with its number.

The dashboard serves the relative image paths a rendered Markdown file names, inside the project and never outside it, so a current report's plots show in the viewer.

Not part of this ticket:

- the routed views and item links that open the viewer over a view (110);
- the views that list documents, reports, and sections (110, 111).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 110.

**Status:** ready-for-agent

**GitHub:** [#221](https://github.com/Bernaljp/wayline/issues/221) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (the dashboard: the document viewer; defects found while charting: relative image paths), 8 (the dashboard); M8 criterion 16 (the viewer, KaTeX, zoom, the sanitizer); user story 170; research note 04 (`research/viewer-math-and-zoom`).

- [ ] Opening a Markdown file shows it in a native `<dialog>` via `showModal()`, outside the redrawn panels; a poll cycle while it is open leaves it open and scrolled where it was.
- [ ] `+`, `-`, and `0` change and reset CSS `zoom` on the document; at phone width the document fits and zooms.
- [ ] KaTeX 0.18.9 and its woff2 fonts are vendored and served by relative URL; the page makes no request outside the machine.
- [ ] The marked extension takes all four delimiters before Markdown; a `*` inside math never pairs; `\label`, `\eqref`, `\ref`, `\DeclareMathOperator`, `multline`, and a redefined macro render; `{#eq:label}` numbers an equation.
- [ ] Rendering runs KaTeX with `trust: false` and then DOMPurify with `semantics` and `annotation` added and `style` forbidden; a document carrying `<style>` and a `<script>` renders with neither taking effect.
- [ ] A relative image path in a rendered file is served from inside the project; a path escaping the project is refused.
- [ ] Tests: the math rendering against recorded constructs from the research note (each shim, each delimiter, the `*` case); the sanitizer's output on a document with `<style>`, `<script>`, and event attributes; image paths over HTTP against a fixture ledger, in and out of the project.
- [ ] The changelog names the viewer and the security fix under `## Unreleased`.
- [ ] `python -m unittest` passes.
