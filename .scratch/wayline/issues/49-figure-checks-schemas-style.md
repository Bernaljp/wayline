# 49 - Figure machine checks, schemas, and the house style

**What to build:** Before any figure costs a verdict, code checks it: the request and result schemas, the project's color budget, and the 19 mechanical checks (fonts embedded, journal width, resolution, minimum font size, the graphical abstract's word cap, forbidden text in a conceptual register, caption and panel coverage, the caption style check, a clean generator, regeneration from the analysis, the palette, one ramp per quantity, line style for required versus optional, selection representativeness, disclosed schematic elements, disclosed mixed data, panel crops, text overlap, provenance) each run against committed good and bad samples.

**Blocked by:** 48 (The plot index)

**Status:** ready-for-agent

**Milestone:** M7 Figures, docs, paper. **Spec:** Implementation Decisions 13 (the figure role's checks, figure schemas, style); research-notes 11 Sections 3 and 4.

- [ ] `schemas/figure_request.json` (`figure_request/1`) and `schemas/figure_result.json` (`figure_result/1`) carry the fields of Implementation Decisions 13, with `register: conceptual` forced for `framework` and `graphical_abstract` kinds and `guided` requiring `revision_of` and non-empty `change_requests`.
- [ ] `figures/style.json` per project (from `figures/style.default.json`) holds the categorical set, one ramp per named quantity, the diverging pair, the single special hue, and the equation-parameter colors; `init` copies the default.
- [ ] The 19 checks are functions with the tools named in the spec (`pdffonts` for Type 42 embedding, `pdfinfo` for width, pixel math and `pdfimages -list` for resolution, the save-time artist assertion and a PDF text walk for minimum font size and forbidden text, `pdftotext` for the word cap, `ruff` for the generator, a clean-room regeneration with SSIM at or above `policy.figures.ssim_min`, the palette allowlist or a CVD-simulated CIEDE2000 distance, the declared tolerance for selection representativeness, presence checks for schematic and mixed-data disclosure, `pdftoppm -r 600` crops, window-extent overlap, the provenance manifest); checks that need Python plotting or PDF libraries run as scripts shipped under `figures/checks/` in the project's environment, and the harness stays standard-library.
- [ ] Each check returns `{id, type: "A", pass, tool, detail}`; the check runner returns the report block of `figure_result`.
- [ ] Tests run every check against committed sample PDFs and PNGs with one passing and one failing case each.
