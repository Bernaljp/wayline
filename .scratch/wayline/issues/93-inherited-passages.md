# 93 - Inherited passages

**What to build:** A project started midway brings an earlier manuscript, a separate Methods, or a supplement, sorted `inherited` by "84 - Documents in: converting and keeping a project's documents". Code deconstructs each such document verbatim into **inherited passages** in the five sections, so the owner can tell what holds from what is overstated. Only text under headings that map to Introduction, Results, Discussion, or Methods is deconstructed. The heading table is fixed:

- Introduction or Background go to Introduction;
- Discussion, Conclusions, or Outlook go to Discussion;
- Methods, Materials and methods, Theory, Model, or Algorithm go to Methods;
- "Results and discussion" goes to Results.

A subheading follows its parent. Any other heading is placed by the setup session, or, with no session, under Results as written and listed. The title, the abstract, captions, back matter, availability statements, and the reference list are kept and read, never deconstructed, so none of them reaches the paper.

Every paragraph is split at its claims. The classifier's claim sentences become one inherited passage each, and the sentences between them stay together. Each carries a `{doc:<document>#<locator>}` tag naming the document, the paragraph, and the sentence, which is provenance and never a citation. Inherited citations become identifier `ref` tags from the start, with no locator. The rendered section rejoins a paragraph's passages, each claim marked unchecked. An inherited claim stands **unchecked** until a ticket's passage or finding replaces it with whether this project's evidence supports, narrows, or contradicts it, or until it is found **unverifiable**.

A separate Methods or supplement document is placed by content. The setup session that reads the inherited passages proposes, for each passage that reports or interprets an outcome, its place in Results or Discussion, and code moves it and lists the move for the owner. Such a document's own front matter is kept, not deconstructed. Without pandoc a `.docx` is kept, but nothing is deconstructed from it. A newer version of an inherited document, handed over later, is taken in like a section edit: new text becomes new inherited passages, changed text replaces, and removed text withdraws.

Not part of this ticket:

- repeat groups, merges, and contradictions across occurrences, which are "95 - Repeated claims";
- concerns targeting inherited claims, which are "96 - Critiques and concerns";
- verifying inherited results, which is "97 - Verifying inherited results";
- the outline's "Inherited, checked by no objective" list, which is "104 - The outline".

**Blocked by:** 84 - Documents in: converting and keeping a project's documents; 86 - Passages and the five sections. It blocks 95, 96, 97, and 104.

**Status:** ready-for-agent

**GitHub:** [#240](https://github.com/Bernaljp/wayline/issues/240) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Inherited passages and repeated claims; Documents, critiques, and concerns; Sections and passages, the `doc` tag); the schemas list (`passage`, the inherited `by`); M8 criteria 9 and 10; user stories 101 and 137.

- [ ] An inherited document's body under mapped headings becomes inherited passages in `research/passages.jsonl` through the ledger, with `by` naming the document. The heading table above is code, a subheading follows its parent, and an unmapped heading with no session lands under Results as written and is listed.
- [ ] Each claim sentence the classifier marks is one passage, the sentences between claims stay together, and each passage carries a `doc` tag naming document, paragraph, and sentence. Inherited citations are identifier `ref` tags with no locator.
- [ ] The title, abstract, captions, back matter, availability statements, and reference list are kept in the document's record and never become passages.
- [ ] The rendered section rejoins a paragraph's passages verbatim, with each inherited claim marked unchecked. A ticket passage or finding that names the inherited passage in `replaces` with supports, narrows, or contradicts takes its place. An unverifiable standing is kept apart from unchecked.
- [ ] A separate Methods or supplement: the setup session's proposal places each outcome passage in Results or Discussion, code moves it and lists the move, and the document's own front matter stays undeconstructed.
- [ ] With no pandoc recorded in `tools.json`, a `.docx` is kept and nothing is deconstructed from it, and the reason is listed.
- [ ] A newer version of an inherited document is taken in like a section edit: new text becomes passages, changed text replacements, removed text withdrawals.
- [ ] Tests over the synthetic start-midway project of ticket 78, on the ledger seam over a temporary project, with the classifier scripted through the fake launcher and the conversion through the tool runner's recordings: the heading table, claim splitting, tags, kept parts, rendering, placement, the no-pandoc case, and a newer version. Nothing of PINF enters the repository.
- [ ] The CHANGELOG's `## Unreleased` entry describes inherited passages.
- [ ] `python -m unittest` passes.
