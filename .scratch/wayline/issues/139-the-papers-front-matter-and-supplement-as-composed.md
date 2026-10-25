# 139 - The paper's front matter and supplement as composed

**What to build:** The parts code writes into the paper (the availability statements and the supplement's numbering) read as prose and number every item once.

On the toy's live paper order (ticket 122, `docs/verification/m8.md`), the independent read of build 1 failed, and three of its points were the harness's composition, not the writer's prose:

- **Code availability** printed a raw Python dict literal as the paper's statement: `{'passage': 'P60', 'heading': 'Drawing R11-1', … 'reproduced_by_repository': False}`, the code-to-Methods check's record rather than a sentence.
- **Two supplementary tables shared the id ST3**: R7's two tables (`R7.T1`, the gate checks; `R7.T2`, the six reruns) were both numbered ST3, only one `ST3.md` and `ST3.csv` were written, the gate-checks table was lost, and the numbering skipped S4.
- **Data availability** named `research/intake/paper-c-source.tar.gz` as "the data this study analysed". Intake had filed the arXiv-style source tarball the owner handed over under Data at setup (turn 1: "The verb also listed it under Data in INTAKE.md"), though it is another paper's released code and the spec says no experiment reads it.

- Code availability renders a sentence from the code-to-Methods record (what reproduces, what does not, and why), never the record itself; a test fails on any `{`/`'` dict text reaching a part.
- Supplementary items are numbered once each, in order of first citation, with one file pair per item; a test with a result holding two tables.
- Intake files a reference tarball (an e-print source) under the references, never under Data, and Data availability is written only from what the work actually read.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#346](https://github.com/Bernaljp/wayline/issues/346) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (the paper order and what it compiles; the front matter; methods and the code), 13 (intake); ticket 122's live record.

- [ ] The availability statements and the supplement's numbering, covered over a composed fixture paper.
- [ ] Intake's sorting of an e-print tarball, covered over a temporary project.
- [ ] `python -m unittest` passes.
