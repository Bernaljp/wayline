# 78 - The synthetic start-midway project

**What to build:** A synthetic project that starts midway, the way PINF_Project did, so every ticket that handles a project's own documents and code tests against the same materials, and nothing of PINF_Project enters the repository. It is a fixture beside the toy under `fixtures/`, made of invented text on an invented question:

- an earlier manuscript as `.docx` with tracked changes (insertions and deletions), open and resolved Word comment threads, Mendeley Cite citations, equations, headings that map to Introduction, Results, Discussion, and Methods plus one that does not, a title, an abstract, captions, and a reference list;
- the same manuscript's older version, so "the newest in its source format" can be chosen;
- a separate Methods as `.tex`, with one stated parameter that disagrees with the code;
- a supplement as a PDF with no source;
- an `.xlsx` with two sheets;
- a critique: a referee report with numbered points, one two-point item, one praise paragraph, and a point near-identical to one in a second, shorter critique;
- a claim repeated across two sections in different words, and one pair of contradicting sentences;
- a small code repository with history, holding one MATLAB and one Python file that develop a method, call a used method, and set a non-default parameter, shipped as a git bundle or a script that builds it, so no nested `.git` enters the tree;
- a missing-material case: one inherited result whose data is absent.

A short README in the fixture lists what each file is there to exercise. A test opens every file with the standard library (the `.docx` and `.xlsx` as zip archives, the bundle with `git`) so a broken fixture fails the suite.

Not part of this ticket:

- converting, sorting, or deconstructing these files (84, 93), splitting the critiques (96), absorbing the code (85).

**Blocked by:** None - can start immediately. It blocks 84 and 85.

**Status:** ready-for-agent

**GitHub:** [#225](https://github.com/Bernaljp/wayline/issues/225) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (documents, critiques, and concerns; inherited passages and repeated claims; Methods and the code), Testing Decisions (decision 17's document fixtures: "an earlier manuscript as `.docx` with tracked changes, comments, and Mendeley citations, a `.tex` Methods, a critique, a small code repository with a MATLAB and a Python file"); M8 criteria 9 and 10 (the synthetic materials they are covered with); user stories 101, 175.

- [ ] The fixture holds every item listed above, all invented; no file, name, or sentence comes from PINF_Project.
- [ ] The `.docx` carries tracked insertions and deletions, at least one open and one resolved comment thread, Mendeley Cite citation fields, an equation, and the headings listed; an older version is beside it.
- [ ] The `.tex` Methods, the source-less PDF, the two-sheet `.xlsx`, the two critiques, the repeated claim, and the contradicting pair are present as described.
- [ ] The code repository builds from a bundle or a script into a temporary directory with at least two commits, one MATLAB file and one Python file, and no nested `.git` is tracked.
- [ ] The fixture's README maps each file to what it exercises.
- [ ] A test opens every file with the standard library and `git` and checks the markers above are present (tracked-change elements, comment parts, citation fields, sheets, commits).
- [ ] `python -m unittest` passes.
