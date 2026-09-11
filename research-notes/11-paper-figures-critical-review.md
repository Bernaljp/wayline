# 11: Critical review of the paper-figures skill for the figure role

Ticket: `.scratch/harness/issues/11-paper-figures-critical-review.md`
Sources: `~/.claude/skills/paper-figures/SKILL.md` (261 lines; line numbers below refer to it), BRIEF.md Sections 3.4 and 13.1, constraint C5.
Date: 2026-09-11

## Answer

The skill is worth mining for three things and dangerous to copy for a fourth.

Keep as doctrine: the two-mode split (design before drawing versus implement a directed change), the register rules for a framework figure (real shapes stripped of labels, no prose in panels, greyscale structure, one ramp per quantity, line style for required versus optional), the honesty discipline (verify equations against code, select for representativeness on a computed number, never draw a capability the analysis does not realize, make schematic elements self-declaring, keep the load-bearing negative), and the shape of the verification loop (crop and look, text sweep, fonts, captions, notes file).

Regenerate rather than copy: every trap in Section 4 (lines 163 to 205). They are matplotlib and TikZ facts and belong in the `known pitfalls` field of `figures/plot_index.json` for the matplotlib entries, to be regenerated per library when the index selects a different one.

Mechanize: of the skill's verification loop, fonts embedded, journal width, resolution, minimum font size, forbidden text in a conceptual register, caption and panel coverage, selection representativeness, schematic-element disclosure presence, caption style lint, dead imports, and regeneration from the analysis are all Type-A checks with concrete commands (table in Section 3). Exactly one Type-B verdict remains: "does the figure assert something the data does not," rendered by a fresh session that receives the panel crops, the spec, the caption, the claim, and the machine-check report.

The skill's largest structural assumption is a human author in the loop at four points: agreement on the design plan before code is written (lines 28 to 29 and 59 to 60), the artifact page for the proposal (lines 70 to 71), the "say so once, then comply if reaffirmed" rule (lines 223 to 226), and every "tell the author" instruction (lines 137, 159, 215). Unattended, each of these blocks forever. The harness replaces them with: candidates rendered from the plot index instead of a proposal, a critic ranking instead of agreement, a decider pick with an escalation rule instead of a human pick, structured findings emitted into the result instead of "tell the author," and a refusal record plus an honest alternative candidate instead of a reaffirmation dialogue. Section 4 gives the pipeline and the input and output JSON shapes.

## 1. Doctrine to keep

Each item gives the SKILL.md line range, the rule, and how it survives the move to an unattended role.

**Two modes, one shared core (lines 26 to 35).** Unguided means "do not start drawing; design first." Guided means "implement exactly what was asked, verify the facts you are about to draw, and object when a request would make the figure false." Keep the split. In the harness, unguided is the default path for a new figure ticket and guided is the revision path when a critic or a human returns change requests. The shared core (register, honesty, verification) is the same role prompt in both.

**Read the comparables first (lines 41 to 44).** Four to six figures from the venue and subfield, a table of structure, device, ending, and the one thing worth stealing. Keep as a step for framework figures and graphical abstracts only; result figures get their comparables from the plot index gallery links instead. The corpus must be an input: unattended sessions have no venue archive to browse. See Section 4 on `comparables`.

**Distinguish the two artworks (lines 46 to 51).** A graphical abstract (one claim, roughly sixty words, nothing below about six points at thumbnail size) and a summary Figure 1 (a contract read at full page, can carry ten panels) are different drawings. Keep, and enforce structurally: they are separate figure tickets with `kind` set to `graphical_abstract` or `framework`, and the word cap and minimum size become machine checks in the target block.

**Draw the argument, not the workflow (lines 53 to 57).** If every comparable draws the same shape, ask whether that shape is the claim. Keep as a critic rubric item ("does the layout say the claim before any label is read"), which is how a ranking can prefer a funnel-and-fan over a pipeline without a human saying so.

**Propose, then build, with color, type, and layout (lines 59 to 69).** Color inherited from the paper's existing encodings; type decided by the smallest size the figure is read at and the word count that caps; layout in one or two sentences plus a mock-up at true aspect ratio. Keep all three, but the proposal is no longer prose put in front of an author. Color comes from `figures/style.json` (the house style file, an input). Type becomes `target.min_font_pt` and a derived word budget. Layout mock-ups at true aspect ratio become the rendered candidates themselves.

**Register of a framework figure (lines 75 to 110).** Keep verbatim as doctrine, since none of it is library-specific:
- Conceptual labels, real shapes (lines 79 to 85): no numeric values, tick values, gene names, or dataset names, but every data panel is plotted from the real fit and then stripped. This is the rule that makes the figure regenerate with the analysis, and it is what makes the "no numeric labels" check and the "regenerates from the analysis" check meaningful.
- No explanatory prose inside panels (lines 87 to 89).
- The caption names nothing and forward-references (lines 91 to 94).
- Structure spends no color; greyscale rails and connectors (lines 96 to 98).
- One ramp per quantity, with a written color budget (lines 100 to 103). The budget is `figures/style.json`.
- Required versus optional is line style, not color (lines 105 to 106).
- Color the parameters of equations and reuse those colors everywhere (lines 108 to 111).
- Line 112 to 114 (typeset in-figure lists in LaTeX, not matplotlib text) is library-specific and moves to the index; see Section 2.

**Honesty discipline (lines 118 to 159).** Keep every rule; this is the part the BRIEF names as the strongest inspiration (3.4, 13.1).
- Verify every equation against the code before drawing it (lines 122 to 126). The suggested fan-out "several readers, each auditing one subsystem, each adversarially checked" maps directly onto a Workflow script that launches one verifier session per equation (C4: composition lives in code).
- Watch for selection artifacts; select for representativeness against the global statistic and write the reason into the code (lines 128 to 132). Becomes a declared criterion in the spec and a Type-A tolerance check (Section 3).
- Do not draw a capability the analysis does not realize (lines 134 to 138). The "tell the author, because it bears on a sentence in the Results" clause becomes a structured `findings_for_text` entry in the output that the conductor can turn into a ticket.
- Make schematic elements self-declaring in code, caption, and notes (lines 140 to 142). Becomes the `schematic_elements` list in the output, with a presence check on the caption.
- If two sub-plots show different data, the caption must say so (lines 144 to 146).
- Show the change, not the comparison, when the comparison is invisible (lines 148 to 150).
- Keep the load-bearing negative; a third glyph state for "tested, does not transfer," distinct from "not applicable" (lines 152 to 155). This aligns with C8 ("negative results are findings").
- Measure, do not guess, when choosing what to show; report the number (lines 157 to 159). The number goes into `selection_statistics`.

**Guided iteration (lines 209 to 229).** Keep four of five rules. Crop and look at high resolution (lines 211 to 213); diagnose rather than treat the symptom (lines 215 to 217); measure placement against the rendered bounding box rather than nudging (lines 219 to 221); report what changed with numbers (lines 228 to 229). The fifth, "say so once, then comply if reaffirmed" (lines 223 to 226), keeps its first half (object with the nearest honest alternative) and loses its second half in unattended mode, because reaffirmation of a falsifying request is a human-only act. See Section 4.

**Verification loop (lines 233 to 243) and notes file (lines 247 to 253).** Keep the shape and the notes file requirement (generator path, register, load-bearing choices with their measurement, schematic elements, traps hit). The loop itself is converted into the checklist of Section 3. The notes file becomes `figures/<id>/notes.md` plus the machine-readable `figure_result.json`; the `traps_hit` field is what feeds the evolve loop for the plot index.

**Drop.** Section 8 (lines 255 to 261) ties the skill to `research-paper`, which the harness does not call (C5). The regex warning (lines 204 to 205) is a general tooling note, not figure doctrine, and belongs in a worker guideline.

### What assumes a human author and would fail unattended

Being explicit, since this is the review the BRIEF asked for:

1. Lines 28 to 29 and 59 to 60: "propose a structure, get agreement" and "put it in front of the author before writing generator code." Unattended, there is no one to agree. The session either stalls or, worse, treats its own proposal as agreed and draws one figure with no alternatives.
2. Lines 70 to 71: publish the proposal as an artifact page. Human-facing output; no consumer in `claude -p`.
3. Lines 41 to 43: "collect four to six figures from the venue ... render them, and actually look." Presumes browsing a venue archive and presumes the author session's own taste. The comparables must be an input, and "look" must be a fresh critic session, not the session that will draw (C6).
4. Line 137, line 159, line 228: "tell the author," "report the number when you tell the author," "report what you changed." Prose reports vanish in a headless session unless they are fields in a structured result.
5. Lines 215 to 217: "when an author reports 'the title is covering an arrow'." No author reports defects unattended; defect discovery has to come from the crop-and-look step performed by a critic on the machine-produced crops.
6. Lines 223 to 226: comply if the author reaffirms a falsifying request. A decider must never be allowed to reaffirm; only a human can, and only through the human queue (C7 spirit: irreversible or integrity-affecting actions stay human-gated).
7. Lines 60 to 64: colors "derived from the paper's own existing encodings." Presumes the session knows the project's encodings from context. Needs `figures/style.json` as a hard input; if absent, the role should create it from the first figure and the conductor should treat it as project state (C3).
8. Lines 236 to 243: "style lint ... verify before fixing them" and "dead imports after a refactor" are instructions to a human-supervised editor. Unattended they must be pass/fail checks with no discretion.

## 2. Library-specific material: regenerate from the plot index

Everything in Section 4 (lines 163 to 205) is a fact about one renderer and should not be copied into the figure role. BRIEF 13.1 gives `figures/plot_index.json` a `known pitfalls` field per library implementation; the skill's traps are the seed content for the matplotlib and TikZ entries, and the evolve loop grows them from `traps_hit` in figure results. When the index selects Altair, plotnine, or R, the role reads that library's pitfalls instead, and the matplotlib ones never enter the prompt.

Classification of the skill's traps:

| Lines | Trap | Scope | Index placement |
|---|---|---|---|
| 167 to 170 | Figure patches paint over axes; give panel boxes negative zorder | matplotlib | pitfalls for any multi-panel layout in matplotlib |
| 172 to 176 | `set_aspect("equal", adjustable="datalim")` discards prior limits; expand by hand and use `aspect="auto"` | matplotlib | pitfalls for embedding and quiver types |
| 178 to 182 | Equations cannot be normalized by bounding-box height; solve for one shared scale | matplotlib mathtext, also true of any rendered-equation embedding | pitfalls for equation rows, tagged general-with-matplotlib-recipe |
| 184 to 187 | No `letterspacing`; `Axes3D.text` versus `text2D`; `set_box_aspect(zoom=)`; log axes keep minor ticks after `set_xticks([])` | matplotlib | per-type pitfalls (3D, log axes) |
| 189 to 191 | `withStroke` path effects emit text as outlines; `pdftotext` misses them | matplotlib plus PDF text layer | pitfall and a note on the text-sweep check's blind spot (Section 3) |
| 193 to 194 | No flat-bar arrowhead; draw signed regulatory graphs in TikZ | matplotlib limitation, TikZ recipe | network family: prefer TikZ or graphviz for signed edges |
| 196 to 202 | The TikZ bridge (standalone, arrows.meta, pdflatex, pdftoppm 600 dpi, transparent white, generate from data, cache renders) | TikZ | network family, TikZ implementation entry |
| 112 to 114 | Typeset in-figure lists in LaTeX, not matplotlib text | matplotlib typography | pitfall for any figure with a symbol legend |
| 204 to 205 | Backtracking regex on long lines | not a plotting trap | worker guideline, not the index |

Two things the role should do with these that the skill does not:

- Make the pitfalls list a required read before rendering each candidate: the input carries `index_ids`, the role reads the pitfalls for each and records `pitfalls_consulted` in the candidate record. That is what makes "regenerated per library" auditable.
- Make every new trap a structured `traps_hit` entry (`library`, `chart_type`, `description`, `fix`, `promote_to_index`), so the evolve loop can merge it into the index without a human retyping it.

## 3. Verification steps: machine checks versus the one Type-B verdict

Every check is Type-A unless stated. Commands assume poppler (`pdffonts`, `pdftotext`, `pdfinfo`, `pdfimages`, `pdftoppm`), which is installed on the workstation, and Python. Targets come from `figure_request.target` and `figures/style.json`.

| # | Check | Type | Concrete check | Source in skill |
|---|---|---|---|---|
| 1 | Fonts embedded, no Type 3 | A | `pdffonts fig.pdf`: every row has `emb yes` and `type` is TrueType or CID TrueType, not Type 3. Prevention in the generator: `matplotlib.rcParams["pdf.fonttype"] = 42` and `ps.fonttype = 42` (default is 3, meaning Type 3; matplotlib's shipped `matplotlibrc` documents the option as "Output Type 3 (Type3) or Type 42 (TrueType)", https://matplotlib.org/stable/users/explain/customizing.html, confirmed against the template at https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/mpl-data/matplotlibrc). | line 238 |
| 2 | Journal width | A | `pdfinfo fig.pdf` page size, or the MediaBox via pypdf, converted to mm; must equal `target.width_mm` within 0.5 mm. Height must not exceed `target.max_height_mm`. | line 23 (house style), BRIEF 13.1 |
| 3 | Resolution | A | For PNG: pixel width divided by `target.width_mm / 25.4` must be at least `target.min_dpi` (300 for images, 600 for line art). For rasters embedded in a PDF (TikZ bridge, imshow panels): `pdfimages -list fig.pdf`, every `x ppi` and `y ppi` at or above `target.min_dpi`. | line 197 |
| 4 | Minimum font size | A | Walk the PDF text with pdfminer.six (`LTChar.size`) or, at generation time, every `Text` artist's `get_fontsize()` scaled by figure width to final width; all at or above `target.min_font_pt`. The graphical abstract uses its own, larger threshold. | lines 47 to 49, 65 to 66 |
| 5 | Word cap for the graphical abstract | A | `pdftotext fig.pdf - | wc -w` at or below `target.max_words` (skill: roughly sixty). | line 48 |
| 6 | No forbidden text in a conceptual register | A | When `register == conceptual`: `pdftotext -layout fig.pdf -` must match no digit run, no entry in the project's gene or dataset name list, no tick labels. Allowlist by regex in the spec (panel letters, exponents inside equations). Known blind spot (lines 189 to 191): haloed text is outlined and invisible to `pdftotext`, so the generator also asserts at save time over every registered text artist, which has no blind spot. Optional third layer: OCR of the 600 dpi raster. | lines 79 to 81, 236 to 237 |
| 7 | Every panel has a caption entry and vice versa | A | Panel letters found in the PDF text (`^[a-z]$` artists, or the spec's panel list) equal the set of letters in the caption's `(a)`, `(b)` markers. Figure referenced in the manuscript exists on disk with both image and caption. | line 239 |
| 8 | Caption style lint | A | The paper linter over `caption.md`: zero em dashes, no British spellings, forward-reference present for a framework figure ("see also Figure N"). | lines 91 to 94, 240 to 241 |
| 9 | Dead imports, generator runs clean | A | `ruff check --select F401,F841 fig.py`; generator exits 0 in a fresh interpreter. | line 242 |
| 10 | Regenerates from the analysis | A | Run the generator in a clean environment with the declared `inputs[]` (paths plus sha256); the produced PDF's text layer and the PNG's perceptual hash (or SSIM at or above 0.99) match the shipped files. Hooks deny reads outside the declared inputs during the run, so a figure cannot depend on an undeclared file. Any panel that cannot be regenerated must be listed in `schematic_elements`. | lines 81 to 84, 249 to 251 |
| 11 | Colorblind-safe palette | A, with a declared allowlist | Extract every fill and stroke color used (from the style module's exported palette, or by parsing the SVG export). Categorical colors must be a subset of `style.json.categorical` (a vetted set such as Okabe-Ito) or, if new, pairwise CIEDE2000 distance under simulated deuteranopia, protanopia, and tritanopia (colorspacious or an equivalent CVD simulation) at or above a threshold. Sequential and diverging ramps must be in the allowlist. Whether the encoding reads well remains part of the Type-B critic rubric. | line 23, BRIEF 13.1 |
| 12 | One ramp per quantity; structure spends no color | A, partial | From the spec's color budget: each ramp name appears for exactly one quantity; connector and container artists in the generator carry only greyscale colors (check saturation of their declared colors). | lines 96 to 103 |
| 13 | Required versus optional by line style | A | Spec marks edges or curves `required` or `optional`; generator asserts solid versus dashed on those artists. | lines 105 to 106 |
| 14 | Selection representativeness | A | Spec declares, per displayed subset, the criterion and the global statistic; the check recomputes the statistic on the displayed subset and requires it within `tolerance` of the global value (the skill's 55 percent versus 75 percent case would fail). | lines 128 to 132, 157 to 159 |
| 15 | Schematic elements disclosed | A for presence | Every entry in `schematic_elements` must be mentioned in `caption.md` and in `notes.md`, and its generator code must carry a `# schematic:` comment. Adequacy of the disclosure is Type-B. | lines 140 to 142 |
| 16 | Two datasets in one panel disclosed | A for presence | If a panel's `inputs` span more than one result artifact, the caption must name that fact (a declared phrase or a `[[mixed-data]]` marker resolved by the paper linter). | lines 144 to 146 |
| 17 | Panel-level crops produced | A | `pdftoppm -r 600` then crop each panel's bbox (from the generator's axes positions) into `figures/<id>/crops/<panel>.png`. Producing them is mechanical; looking at them is Type-B. | lines 211 to 213, 243 |
| 18 | Text overlap and clipping | A, crude | At save time, every `Text` artist's window extent must lie inside the figure bbox and not intersect another text extent beyond a small tolerance. Catches the common collisions; the critic catches the rest. | lines 212 to 217 |
| 19 | Provenance manifest present | A | `figure_result.final.inputs[]` non-empty, every path exists, every sha256 matches, every input traces to a run id (C8). | line 249 |
| 20 | Equations match the code | B | A fresh verifier session per equation compares the drawn form (from the generator source or the TikZ) against the implementation. Fanned out by a Workflow script, one session per subsystem, as the skill suggests. This is a sub-verdict that feeds check 21; it is not automatable. | lines 122 to 126 |
| 21 | Does the figure assert something the data does not | B, the single honesty verdict | A fresh independent session (different model where possible) receives: the panel crops, the full PNG, `figure_request.claim`, `caption.md`, the spec (register, schematic elements, selection statistics), summaries of the result artifacts, and the report from checks 1 to 20. It returns pass or fail with findings tagged by rule: capability not realized (lines 134 to 138), selection artifact beyond the declared statistic (128 to 132), invisible comparison (148 to 150), omitted load-bearing negative (152 to 155), undisclosed mixed data (144 to 146), equation mismatch (from check 20), layout that implies a claim the caption does not make (lines 18 to 19). Fail blocks the figure and emits `findings_for_text`. | Section 3 entire, BRIEF 13.1 |

Machine pre-checks (1 to 19) run before the paid verdict (21), as C6 requires; a failed pre-check returns the figure to the role without spending a critic session.

## 4. Ending the unguided mode in ranked candidates; the figure role's schemas

### 4.1 The pipeline

The skill's unguided mode ends with a prose proposal awaiting agreement. The harness version ends with rendered candidates and a ranking, then a pick, then hardening. Every step is either code or a session with a single job:

1. **Classify the data shape (code, A).** From the result artifact's schema: number of variables, their types (numeric, categorical, ordinal, time), cardinalities, grouping keys, whether there is a paired or before-and-after structure, whether there is a matrix, a graph, or coordinates. For `framework` and `graphical_abstract` kinds, the "data" is the list of panels and their sources rather than one table.
2. **Take candidates from the index (code, A).** Filter `plot_index.json` by data shape, then by the chart families that suit the claim type (a `comparison` claim maps to ranking and distribution families, a `trend` claim to evolution, and so on, a small table maintained with the index), then by the library the project has fixed in `style.json`. Cap at `candidates.max` (default 5). For framework figures, the candidates are layout structures (pipeline, funnel-and-fan, grid, before-and-after) drawn from a small structure index seeded by the comparables table of lines 41 to 44.
3. **Render quick drafts (one worker session, or one per candidate under a Workflow script, A for "it rendered").** Each candidate is a generator script plus a PNG at true aspect ratio, using real data and the house palette but no polish. The session reads the index pitfalls for each candidate first and records them. Failure to render is recorded, not hidden, and the candidate drops out.
4. **Critic ranks (fresh session, B).** Rubric: does the shape carry the claim before any label is read; is anything asserted the data does not support; venue fit against the comparables; data-ink and legibility at target size. Output is a full ranking with scores and reasons, not a single winner, so a human can overrule cheaply later.
5. **Pick (code or human).** In interactive mode the human picks from the ranking. Unattended, the decider takes rank 1 if its margin over rank 2 exceeds a configured threshold; otherwise it takes rank 1 and flags `selected.margin_low = true` so the human queue shows the alternatives. No session picks its own candidate.
6. **Apply house style and finish (worker session, guided mode internally).** Full register rules, caption, notes.
7. **Machine checks (code, A)**, then **honesty verdict (fresh session, B)**, per Section 3.
8. **Return `figure_result.json`.** The conductor files `findings_for_text` as tickets, merges `traps_hit` into the index through the evolve loop, and queues `refusals` for the human.

Guided mode is the same role entered at step 6 with `revision_of` set and `change_requests[]` filled. The one honesty-critical difference: if a change request would make the figure assert something false, the role does not comply. It records a `refusal` with the reason and renders the nearest honest alternative as a new candidate (the skill's "offer the nearest honest alternative first," line 224). Only a human, through the queue, can mark a refusal `overridden`, and an override is recorded in the caption and notes as the skill demands (lines 225 to 226). A decider never overrides.

### 4.2 Input schema: `figure_request.json`

```json
{
  "schema": "figure_request/1",
  "ticket": "P-042",
  "figure_id": "fig3",
  "mode": "unguided",
  "kind": "result",
  "register": "quantitative",
  "claim": {
    "claim_id": "C2",
    "text": "Method X recovers the sign of regulatory edges more often than baselines A and B across five datasets.",
    "claim_type": "comparison",
    "evidence": ["results/run_017/metrics.json", "results/run_018/metrics.json"]
  },
  "data": [
    {
      "path": "results/run_017/edge_signs.parquet",
      "sha256": "…",
      "run_id": "run_017",
      "shape": {
        "rows": 1250,
        "columns": [
          {"name": "method", "type": "categorical", "cardinality": 3},
          {"name": "dataset", "type": "categorical", "cardinality": 5},
          {"name": "sign_accuracy", "type": "numeric", "range": [0, 1]},
          {"name": "seed", "type": "categorical", "cardinality": 10}
        ],
        "grouping": ["method", "dataset"],
        "paired": false
      }
    }
  ],
  "style": "figures/style.json",
  "target": {
    "venue": "nature-methods",
    "width_mm": 183,
    "max_height_mm": 247,
    "min_font_pt": 5,
    "min_dpi": 300,
    "max_words": null,
    "formats": ["pdf", "png"],
    "library": "matplotlib"
  },
  "candidates": {"max": 5, "families": null, "exclude_index_ids": []},
  "comparables": ["figures/comparables/nmeth_2025_fig1.png"],
  "forbidden_text": {"gene_names": "data/gene_symbols.txt", "dataset_names": ["PBMC3k", "Tabula"], "allow_regex": ["^[a-h]$"]},
  "revision_of": null,
  "change_requests": [],
  "budget": {"render_seconds": 600, "critic_sessions": 1, "verifier_sessions": 2}
}
```

Notes on the shape. `kind` is one of `result`, `framework`, `graphical_abstract`; `register` is `quantitative` or `conceptual` (framework and graphical abstract are always conceptual, and the schema validator enforces it). `mode` is `unguided` or `guided`; guided requires `revision_of` and a non-empty `change_requests`, each `{"id": "cr1", "text": "…", "from": "human" | "critic", "session": "…"}`. `comparables` is optional and, unattended, is populated by the literature role from figures of the cited papers or by the human at intake. `forbidden_text` is what check 6 in Section 3 reads. `style` points to the project's color budget: categorical set, one ramp per named quantity, the diverging pair, the single special hue, and the equation-parameter colors (lines 100 to 111).

### 4.3 Output schema: `figure_result.json`

```json
{
  "schema": "figure_result/1",
  "ticket": "P-042",
  "figure_id": "fig3",
  "version": 1,
  "status": "verified",
  "data_shape": {"family_hint": ["distribution", "ranking"], "n_groups": 15, "n_per_group": 10},
  "candidates": [
    {
      "rank": 1,
      "index_id": "distribution/boxplot-grouped/matplotlib",
      "chart_type": "grouped boxplot with seed points",
      "library": "matplotlib",
      "generator": "figures/fig3/cand_01.py",
      "png": "figures/fig3/cand_01.png",
      "rendered": true,
      "pitfalls_consulted": ["matplotlib/log-minor-ticks", "matplotlib/patch-zorder"],
      "score": {"claim_legibility": 5, "honesty": 5, "venue_fit": 4, "legibility_at_size": 4, "total": 18},
      "critic_reasons": "Sign accuracy per method is read in one glance; seeds visible; no dataset is hidden."
    },
    {"rank": 2, "index_id": "ranking/dot-plot/matplotlib", "rendered": true, "score": {"total": 15}, "critic_reasons": "…"},
    {"rank": null, "index_id": "distribution/ridgeline/matplotlib", "rendered": false, "error": "…"}
  ],
  "critic": {"session": "…", "model": "…", "rubric_version": "1"},
  "selected": {"rank": 1, "by": "decider", "margin": 3, "margin_low": false},
  "final": {
    "generator": "figures/fig3/fig3.py",
    "pdf": "figures/fig3/fig3.pdf",
    "png": "figures/fig3/fig3.png",
    "caption": "figures/fig3/caption.md",
    "notes": "figures/fig3/notes.md",
    "crops": ["figures/fig3/crops/a.png", "figures/fig3/crops/b.png"],
    "inputs": [{"path": "results/run_017/edge_signs.parquet", "sha256": "…", "run_id": "run_017"}],
    "output_sha256": {"pdf": "…", "png": "…"}
  },
  "checks": [
    {"id": "fonts_embedded", "type": "A", "pass": true, "tool": "pdffonts", "detail": "3 fonts, all TrueType, emb yes"},
    {"id": "journal_width", "type": "A", "pass": true, "detail": "183.0 mm"},
    {"id": "resolution", "type": "A", "pass": true, "detail": "png 2162 px = 300 dpi"},
    {"id": "min_font_pt", "type": "A", "pass": true, "detail": "smallest 5.5 pt"},
    {"id": "forbidden_text", "type": "A", "pass": true, "detail": "register quantitative; check skipped"},
    {"id": "caption_panels", "type": "A", "pass": true},
    {"id": "caption_lint", "type": "A", "pass": true},
    {"id": "generator_clean", "type": "A", "pass": true, "tool": "ruff"},
    {"id": "regenerates", "type": "A", "pass": true, "detail": "ssim 0.998"},
    {"id": "palette", "type": "A", "pass": true, "detail": "3 categorical colors from style.json"},
    {"id": "selection_representativeness", "type": "A", "pass": true, "detail": "n/a, all data shown"},
    {"id": "schematic_disclosed", "type": "A", "pass": true},
    {"id": "text_overlap", "type": "A", "pass": true},
    {"id": "provenance", "type": "A", "pass": true}
  ],
  "honesty_verdict": {
    "type": "B",
    "verdict": "pass",
    "session": "…",
    "model": "…",
    "findings": []
  },
  "schematic_elements": [],
  "selection_statistics": [],
  "findings_for_text": [],
  "refusals": [],
  "traps_hit": [
    {"library": "matplotlib", "chart_type": "boxplot", "description": "…", "fix": "…", "promote_to_index": true}
  ],
  "sessions": [{"role": "figure-worker", "session": "…"}, {"role": "figure-critic", "session": "…"}, {"role": "figure-verifier", "session": "…"}]
}
```

`status` is one of `candidates_ranked` (waiting for a human pick when `margin_low` and the autonomy mode requires it), `selected`, `verified`, `failed_checks`, `honesty_failed`, `refused` (a guided change request was refused and no honest alternative was possible), `blocked`. For a framework figure, `schematic_elements` entries are `{"panel": "b", "element": "regulatory motif", "reason": "mechanism exists but magnitude below threshold in all runs", "caption_phrase": "schematic"}` and `selection_statistics` entries are `{"panel": "c", "criterion": "sign_balance", "displayed": 0.55, "global": 0.57, "tolerance": 0.10}`. `findings_for_text` entries are `{"text": "…", "manuscript_locator": "results.md#S3", "suggested_ticket": true}` and are the unattended replacement for every "tell the author" in the skill. `refusals` entries are `{"change_request": "cr2", "reason": "would show a transfer the data does not support", "alternative_candidate": "figures/fig3/cand_04.png", "overridden_by": null}`.

### 4.4 What this changes relative to the skill

- The design plan (color, type, layout) still exists but is no longer a document awaiting agreement; it is split into `style.json` (color), `target` (type), and the rendered candidates (layout).
- "Get agreement" becomes a ranking plus a pick rule, and the ranking is preserved so a human can overrule after the fact at the cost of one guided revision rather than a redesign.
- The honesty discipline stays a discipline for the drawing session and additionally becomes a rubric for one independent verdict, which is the only place taste is paid for.
- Every trap the skill lists, and every new one, lives in the plot index and reaches the session through `pitfalls_consulted`, so the role prompt never carries library facts.
