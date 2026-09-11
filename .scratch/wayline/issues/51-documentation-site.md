# 51 - The documentation site

**What to build:** A package the harness implemented gets documentation someone else can use: a site with tutorials, how-to guides, reference, and explanation, an API reference generated from docstrings, executed examples, a figure gallery, and the Read the Docs configuration; code checks that every public symbol is documented and present, every example runs, the build is warning-free, and links resolve; one independent read judges clarity and completeness against the package's purpose.

**Blocked by:** 34 (Plan: the planner, plan-time checks, and ticket assignment), 43 (M5 overnight demo: the toy project end to end across a window boundary)

**Status:** ready-for-agent

**Milestone:** M7 Figures, docs, paper. **Spec:** Implementation Decisions 13 (documentation), 10 (the planner's docs rule); BRIEF 13.2; OPEN-10 (map ticket 22).

- [ ] `roles/documentarian/` exists; a `docs` ticket runs it in the project's own environment (Sphinx installed there, not in the harness) to produce the four-part structure, the API reference from docstrings, executed examples, a figure gallery, and the Read the Docs configuration under the project's `docs/`.
- [ ] `wayline docs build` runs the machine checks: every public symbol from the package's `ast` inventory is documented and present in the reference, every example runs, the build is warning-free, and links resolve; failures return the ticket with the list.
- [ ] One Type-B read through the gate of ticket 32 judges clarity and completeness against the package's purpose; the theme and layout are chosen once per project and recorded in `harness.json.docs`.
- [ ] The docs site is part of done whenever a `code` ticket added public API: the report lists it and the outputs index serves it.
- [ ] Tests run the checks on a fixture package with a deliberately undocumented symbol and a broken example; live: the toy project's package gets a site that passes the checks, recorded in `docs/verification/m7.md`.
