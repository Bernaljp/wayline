# 141 - Reading the paper with its provenance

**What to build:** The owner reads the paper's main text on the dashboard as a paper, not as files of tags, and sees at a glance where every claim comes from. Each claim sentence is tinted by its source; a click opens what stands behind it; a comment on it goes to the conversation with the sentence attached. Figures work the same way.

The owner asked for this after the toy's run (ticket 122, `docs/verification/m8.md`): the paper's parts hold every sentence's provenance (the toy's `results.md` alone ends 395 sentences with `{res:…}` tags and 7 with `{code:…}`, under headings tagged `{#O1}` and `{#R2}`), but the Paper view lists the parts and the viewer shows their raw Markdown with the tags inline, which takes a learning curve to read. During map #173's prototype the owner reviewed a report whose items were each marked with where they came from and reacted to each one; this makes that the way to read the paper.

**The reading view.** A sub-view of Paper, routed `#/<project>/paper/read` (the browser's back and forward work), reached from the Paper view's parts and from each compilation. It shows the current version's main text in order (title, abstract, introduction, results, discussion, methods: `paper.MAIN_TEXT`), rendered as prose with KaTeX math, the tags hidden, each heading carrying its objective or result id as a quiet label. Each claim sentence is tinted, with an underline style as well as a color so it reads in dark mode, at phone width, and for a colorblind reader; a legend explains the colors. Three lenses, switched by one control, the choice kept per viewer:

- **By source** (the default): the owner's own passage; this project's results (a `res` tag on a run's artifact); code (`code`); the literature (`ref`); inherited documents (`doc`); and a claim with no tag or a reference still to be resolved, outlined rather than tinted.
- **By objective**: the objective each sentence's result serves (from the heading it sits under and its findings), one color per objective, the parked ones grey.
- **By check**: whether the sentence was checked and how it stood: a numbers check or a claim verdict that passed, one that failed, or never checked; read from the journal's `verdict` events and the paper's builds (`builds`), never from a model.

**What a click opens.** A side panel (a bottom sheet at phone width) shows, for the sentence: its text; each tag resolved, naming the run and file and the value the locator holds there (as the numbers check reads it, e.g. `BASE_AUROC = 0.8352720450281426`), with a link that opens the artifact in the viewer; the passage or finding it was written from, the ticket and run behind it; its result and objective as item links (`R2`, `O1`); every check that judged it, with its verdict and a link to the verdict's text; and the part's alternatives (`paper.alternatives_of`), each openable, with `wayline paper choose` offered through the existing card. Two buttons, **Comment** and **This is wrong**, put the owner's note into the dashboard's chat with the sentence's item id attached (the chat already carries the item the owner has open), so the review goes through the conversation as feedback or a mark, never as a write of the view's own.

**Figures.** Each figure in the main text sits in a frame colored by its standing under the active lens (by check: the machine checks and the honesty verdict of its `figure_result`); a click opens its caption, the result it draws, the data and the script behind it, the candidates the figure role ranked, and the checks, with the same two buttons.

**What it reads.** One read-only route, `GET /api/projects/<id>/paper/read`, returns the version as blocks built by code from what is on disk and in the ledger, with no model call and no write, under the dashboard's polling and `etag` rules: headings with their ids; paragraphs as sentences (`provenance.prose_sentences` and `parse_tag`, the resolver of `provenance.resolver_for`), each with its source class, resolved tags and values, passage or finding, ticket, run, result, objectives, checks, and the part's alternatives; figures with their `figure_result` fields. A sentence gets an item id of a new form (its part and its number in the version, for example `results.s12`), added to `dashboard_views.ITEM_ID` and the item-id list of that module, so the chat and item links can name it; a sentence the version no longer holds resolves to None as any stale id does. A project with no composed paper answers with an empty version the page explains in words.

Not part of this ticket:

- editing the text from this view (the section and outline editor stays where it is), and choosing an alternative beyond the existing card;
- the supplement, the front matter, and earlier versions (a later ticket may add them with the same blocks);
- any change to how the paper is composed or compiled, or to what the checks decide.

**Blocked by:** None - can start immediately. It reads the paper parts as ticket 139 left them (merged).

**Status:** ready-for-agent

**GitHub:** [#355](https://github.com/Bernaljp/wayline/issues/355) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (the dashboard: the Paper view, item links, the popup viewer, the chat's item; the paper order and its parts; the provenance linter's tags), 8 (the dashboard), 9 (the provenance linter); ticket 122's live record; the owner's request of 2026-11-15.

- [ ] `GET /api/projects/<id>/paper/read` returns the current version's main text as headings, sentences, and figures, each sentence with its source class, resolved tags and their values, passage or finding, ticket, run, result, objectives, checks, and the part's alternatives; read-only, no model, `etag` as the other views; tested over HTTP against a fixture composed paper, including a sentence with no tag, a `ref` still to be resolved, a failed numbers check, an alternative, and a figure.
- [ ] The reading view at `#/<project>/paper/read`: prose with KaTeX math and hidden tags, the three lenses with a legend, tint plus underline style, legible in light and dark and at phone width; linked from the Paper view's parts and each compilation.
- [ ] A click on a sentence or a figure opens the panel (a bottom sheet at phone width) with everything listed above, its links opening the artifact, the verdict, and the item links in the viewer; **Comment** and **This is wrong** post to the chat with the sentence's or figure's item id.
- [ ] The new item id form is in `dashboard_views.ITEM_ID` and its docstring, and the chat accepts it.
- [ ] The showcase follows: `showcase/build.py`'s `COVERAGE` names the new route, the recorded site serves the reading view of the toy's paper, and `tests/test_showcase_browser.py` waits on it; the CI screenshots show it at desktop and phone width, light and dark.
- [ ] The spec's decision 17 dashboard bullet gains the reading view in the Paper view's list, the user guide's `docs/guide/paper.md` says how to read the paper this way, and `CHANGELOG.md`'s `## Unreleased` describes it.
- [ ] `python -m unittest` passes (the browser modules on CI).
