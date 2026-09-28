# 04 Math and zoom in the dashboard's document viewer

Ticket: [#180](https://github.com/Bernaljp/wayline/issues/180), "Math and zoom in the dashboard's document viewer", on the map [#173](https://github.com/Bernaljp/wayline/issues/173). Brief: `.scratch/living-paper/owner-brief.md` section 1.7 (and question 13 of section 5). Resolved 2026-09-28. The throwaway demo and every check that produced a number below are in [`04-viewer-demo/`](04-viewer-demo/); section 9 says how to rebuild and rerun them.

## Answer

- **Vendor KaTeX 0.18.9, not MathJax.** The dashboard would vendor 22 files, 557,335 bytes: `katex.min.js` (272,755), `katex.min.css` (24,788), and the 20 `woff2` fonts (259,792). The code and the fonts are MIT. `katex.renderToString` is synchronous, so `renderMarkdown` stays a plain function. The stylesheet finds its fonts at the relative URL `fonts/`, and nothing is fetched from the network: in Chromium 149 and Firefox 156 every request stayed on `127.0.0.1`, and the sample document used 8 fonts. The dashboard's server already serves nested paths under `dashboard/` and sends `.woff2` as `font/woff2`.
- **Why not MathJax 4.1.3.** Fully offline without speech it is 188 files and 3,414,116 bytes (another 4,683,997 with speech). It is asynchronous by design. Its default font path in a browser is jsDelivr: with no network and the default configuration, typesetting failed outright ("dynamic file 'double-struck' failed to load") and 0 formulas rendered. It also needs its `ui/safe` extension, because by default `\href{javascript:...}` made a clickable link whose script ran, `\style` fetched a remote image, and `\cssId{viewer}` stamped `id="viewer"` into the page. MathJax 3.2.2 (24 files, 1,675,494 bytes, last released 2022-06-08) has been superseded by version 4.
- **KaTeX's coverage of a paper's LaTeX, and the small additions that close its gaps.**
  - Out of the box KaTeX handles `align`, `align*`, `aligned`, `gather`, `equation`, `split`, `cases`, `\tag`, `\notag`, `\mathbf`, `\boldsymbol`, `\bm`, and user macros (`\newcommand`, `\def`, and the `macros` option).
  - It lacks `\label`, `\ref`, `\eqref`, `\DeclareMathOperator`, and `multline`, and it refuses `\newcommand` for names it predefines but LaTeX does not (`\R`, `\N`, `\Z`, `\argmin`).
  - Four small additions in the math code fix these: `\label` as a no-op macro; `\DeclareMathOperator` as a `\def` macro; a retry that changes the one `\newcommand` KaTeX names in its error into `\renewcommand`; and a pass of 57 lines of code (70 with comments) in marked's `processAllTokens` hook ([`equation-refs.js`](04-viewer-demo/equation-refs.js)). That pass numbers equations the way amsmath does, turns each `\label` into its row's `\tag`, maps `multline`, and resolves `\eqref` and `\ref`, forward references included.
  - Per expression this passes 36 of 46 constructs, the same as MathJax 4's 36, and the references work at the document level. Neither engine renders siunitx, physics, bbm, dsfont, `subequations`, or `\cite` without more work.
- **Math through Markdown: one marked extension written into `app.js`, not placeholders.** It has two tokenizers, and marked tries them before its own at every position:
  - block: `$$...$$`, `\[...\]`, and a bare `\begin{equation|align|...}` at the start of a line;
  - inline: `$...$` under Pandoc's rule, `\(...\)`, and `$$...$$` or `\[...\]` inside a paragraph.

  It also uses marked's `emStrongMask` hook, so a `*` or `_` inside math never pairs with one outside it. Today's pipeline turns `$a^*b^*$` into `a^<em>b^</em>`, drops `\(`, `\{`, and `\,`, and makes an `align` row that starts with `+` into a list item. With the extension, all of these render. Prices (`$20,000 to $30,000`), escaped dollars, code spans, and fenced code stay text, and an unclosed `$$` costs one paragraph. marked-katex-extension was not chosen: it knows only `$` and `$$`, and it throws on bad math unless configured not to.
- **Math through sanitizing: render with KaTeX first, then sanitize the whole page.** The call is `DOMPurify.sanitize(html, { ADD_TAGS: ['semantics', 'annotation'], FORBID_TAGS: ['style'] })`, and KaTeX runs with:

  ```js
  { throwOnError: false, trust: false, strict: 'ignore', maxSize: 20, maxExpand: 1000, output: 'htmlAndMathml', globalGroup: true, macros /* one object per document */ }
  ```

  DOMPurify's defaults strip the `<semantics>` and `<annotation>` that wrap every KaTeX formula's MathML. That changed 23 of 23 formulas and left the raw TeX as stray text inside each `<math>`. With the two tags added, 0 of 23 changed. `annotation-xml`, the MathML integration point where DOMPurify's threat model says "much mXSS lives", stays forbidden, and DOMPurify's namespace check still removed an `<annotation>` placed outside MathML. Sanitizing KaTeX's output is the defense KaTeX's own advisories name: the 2026 one says exploitation "requires the consuming application to insert KaTeX output into a web page without a separate sanitizer".

  Every injection attempt came out harmless: `<script>`, `onerror`, raw and Markdown `javascript:` links, `<iframe>`, `<svg><script>`, MathML namespace payloads, TeX that closes a `</span>`, a `\color` breakout, the error path, a macro loop, and `\href`, `\url`, `\html*`, and `\includegraphics` under `trust: false`. Nothing ran in Chromium, and the audit of the final DOM found nothing that runs or carries a `javascript:` URL.
- **Refuse `<style>` too; this was found on the way.** Today's sanitizer keeps a `<style>` element from a document (measured), and that stylesheet applies to the whole dashboard. DOMPurify's threat model says it "is not a CSS sanitizer", does not stop "CSS-based data exfiltration (attribute-selector + resource-URL tricks)", and advises dropping unneeded CSS with `FORBID_TAGS: ['style']`. The outputs list's links carry the token in their URLs. KaTeX never writes a `<style>`, though it does need `style` attributes, which stay.
- **The popup: a native `<dialog>` opened with `showModal()`, placed in `index.html` beside `#node-card`.** It must sit outside the panels the polls redraw: `renderOutputs` rebuilds `#outputs-body`, the in-place `#outputs-preview` included, whenever the outputs change (app.js:1089-1098). Measured in Chromium 149, with the first three points also measured in Firefox 156:
  - focus lands in the document (`autofocus` on its scroll container);
  - Escape closes the viewer and returns focus to the view button;
  - a click on the backdrop lands on the `<dialog>` element, and a three-line handler closes it (`closedby="any"` does this natively in Chrome 134 and Firefox 141, but only in a Safari preview);
  - the page behind is inert: a click on it is refused, and Tab never reaches it;
  - the document scrolls inside the dialog, and `html:has(dialog[open]) { overflow: hidden }` keeps the page behind from scrolling under the backdrop (2,485 px of scroll without the rule, 0 with it).
- **Zoom: CSS `zoom` on the document element alone,** stepped from 50% to 300%.
  - Controls: a minus, level, and plus group in the viewer's bar. The keys `+` (or `=`), `-`, and `0` work inside the dialog. Ctrl and Cmd are left to the browser. The level is remembered in `localStorage` inside `try`/`catch`.
  - Why not `transform: scale`: the CSS Viewport draft says "Unlike transform, scaling the zoom property affects layout". On a 390 px phone at 150%, `zoom` rewrapped a paragraph to the screen (layout width 358 to 239 CSS px, height 121 to 241 px). `transform: scale(1.5)` kept the 358 px layout and drew every line 537 px wide, past the screen's edge.
  - Support, per MDN's compat data: Chrome, Firefox 126 (SVG zooms correctly from 131), and Safari 3.1; MDN marks it Baseline 2024.
- **From a phone through the tunnel.**
  - Below 720 px the viewer fills the screen (`100vw` by `100dvh`) with 44 px buttons. Zoom rewraps the text, a display equation wider than the screen scrolls inside itself, and pinch zoom still works.
  - The first view costs 427,639 bytes through the tunnel for the sample (the script, the stylesheet, and 8 fonts). After that the server's `ETag` with `Cache-Control: no-cache` turns each file into a 304.
  - Not verified: Safari on iOS (no WebKit here), a real phone, and the phone's SSH client.
- **Cost.** The 2.6 KB sample renders in about 10 ms. The 60 KB stress document with 1,051 formulas took 792 ms in Chromium on this 64-core workstation, 459 ms of it in DOMPurify; a laptop or a phone is slower. If that ever matters, sanitizing first and then calling `katex.render()` into placeholders skips the sanitizer on KaTeX's output, at the price of the second line of defense.
- **For the build ticket.**
  - `dashboard/vendor/katex/` with the 22 files. `VENDOR.md` gains their rows, and `tests/test_dashboard.py` gains them in `VENDORED` (line 47) and in the vendor-directory test (line 997), which today lists only flat files.
  - `index.html` gains a `<link>` to the KaTeX stylesheet, the KaTeX `<script>`, and the `<dialog>`.
  - `renderMarkdown` becomes `DOMPurify.sanitize(markdownWithMath().parse(text), MATH_PURIFY)`, as [`markdown-math.js`](04-viewer-demo/markdown-math.js) writes it. That keeps one path from Markdown to HTML, so the position memo (app.js:312) and ticket bodies (app.js:936) render math as well.
  - `outputRow` and `previewOutput` open the viewer instead of the in-place preview; the viewer's code is [`viewer.js`](04-viewer-demo/viewer.js), with its styles in [`viewer.css`](04-viewer-demo/viewer.css).
  - `.markdown { counter-reset: katexEqnNo mmlEqnNo }` restarts equation numbers in each rendered document.
  - Spec decision 8 says the outputs view renders Markdown and images "inline through `DOMPurify.sanitize(marked.parse(md))`". `/to-spec` should change that to the popup, with the math and the sanitizer settings above.
  - Found on the way: a relative image path inside rendered Markdown, such as a report's plot, resolves against the dashboard's root and is not served (`static_file('/figures/a.png')` returns `None`). The viewer should rewrite relative `src` and `href` values to the project's download URL, relative to the document's directory.

## Evidence

### 1. How it was measured

- **Machine and tools:** Linux 6.8.0-117-generic on an AMD Ryzen Threadripper PRO 3995WX. Node 22.22.3 and npm 10.9.8 from `~/.local/bin`. The packages were installed in a scratch directory outside the repository, with the exact versions in [`checks/package.json`](04-viewer-demo/checks/package.json):
  - katex 0.18.9, mathjax 4.1.3 (with @mathjax/mathjax-newcm-font 4.1.3), mathjax 3.2.2 (as the alias `mathjax3`);
  - marked 18.0.12 and dompurify 3.4.15, byte-identical to `dashboard/vendor/` (the same SHA-256 values as `VENDOR.md`);
  - jsdom 30.1.1, playwright-core 1.61.1, and puppeteer-core 25.12.0.
- **The KaTeX files:** `npm pack katex@0.18.9` gave files whose SRI hashes match the ones KaTeX publishes for 0.18.9 in `docs/browser.md`: `katex.min.js` is `sha384-19KE2cFb3U+RUWmyhBz7aLOGDG8WrRC6hE3oY/HTZZlAAVWYTdmvLC//+TIV3zUx`, and `katex.min.css` is `sha384-lPx0C4zIUZLpveABMwOFcFeGZwsvKBJfhJ85FN1PYOV7xApBcFMhcAEMVKF8loOI`.
- **Node checks:** they run the dashboard's own vendored `marked.umd.js` and `purify.min.js`, KaTeX's browser build, and the demo's scripts inside a jsdom window, evaluated the way classic `<script>` tags share one global scope (`checks/common.js`).
- **Browser checks:**
  - Chromium 149.0.7827.55 (Playwright's cached build 1228) was driven by playwright-core, desktop at 1280x800 and a phone at 390x844 with touch and device scale 2.
  - Firefox 156.0.1 (the snap's own binary) was driven over WebDriver BiDi by puppeteer-core.
  - A copy of the demo was served by `python3 -m http.server --bind 127.0.0.1`. Every request to any other host was aborted and logged, and every console message was kept.
- **What was not run:** the dashboard's own server (its content types and caching are read from `wayline/dashboard.py`, section 8), and no browser engine other than these two.

### 2. The renderer: size, license, timing, run-time needs

`node checks/sizes.js` (raw bytes are what the dashboard's server sends, since it does not compress; gzip is shown for comparison only):

| set | files | bytes | gzip -9 bytes |
|---|---|---|---|
| KaTeX 0.18.9: katex.min.js | 1 | 272,755 | 76,085 |
| KaTeX 0.18.9: katex.min.css | 1 | 24,788 | 3,514 |
| KaTeX 0.18.9: fonts/*.woff2 | 20 | 259,792 | 260,282 |
| **KaTeX 0.18.9: the set (js, css, woff2)** | 22 | 557,335 | 339,881 |
| KaTeX 0.18.9: fonts/*.woff and *.ttf, not needed | 40 | 816,780 | 612,541 |
| KaTeX 0.18.9: contrib/mhchem.min.js, optional | 1 | 33,706 | 8,453 |
| MathJax 4.1.3: tex-chtml.js | 1 | 997,445 | 281,508 |
| MathJax 4.1.3: input/tex/extensions/ | 41 | 236,579 | 87,316 |
| MathJax 4.1.3: newcm font chtml/woff2/ | 105 | 1,623,040 | 1,623,216 |
| MathJax 4.1.3: newcm font chtml/dynamic/ | 40 | 550,677 | 133,309 |
| MathJax 4.1.3: ui/safe.js | 1 | 6,375 | 2,492 |
| **MathJax 4.1.3: offline set without speech** | 188 | 3,414,116 | 2,127,841 |
| MathJax 4.1.3: sre/ (speech worker and locale maps) | 19 | 4,683,997 | 623,233 |
| MathJax 3.2.2: es5/tex-chtml-full.js | 1 | 1,327,522 | 302,534 |
| MathJax 3.2.2: es5/output/chtml/fonts/woff-v2/ | 23 | 347,972 | 348,126 |
| **MathJax 3.2.2: the set (tex-chtml-full.js, woff-v2)** | 24 | 1,675,494 | 650,660 |
| marked 18.0.12 and DOMPurify 3.4.15, vendored today | 2 | 74,239 | 24,734 |

**Only the woff2 fonts are needed.** KaTeX's stylesheet lists `woff2`, `woff`, and `ttf` in that order in every `@font-face`, for example `src:url(fonts/KaTeX_AMS-Regular.woff2) format("woff2"),url(fonts/KaTeX_AMS-Regular.woff) format("woff"),...`. A browser that reads woff2 never requests the other two: the logged requests held only `.woff2` files, in both engines.

**Licenses.**
- KaTeX is MIT (`katex/LICENSE`, "Copyright (c) 2013-2020 Khan Academy and other contributors"). Its fonts come from `KaTeX/katex-fonts`, also MIT ("Copyright (c) 2018 Khan Academy").
- MathJax and its font package are Apache-2.0.

**Synchronous or not.**
- KaTeX: `katex.renderToString` returns a string, and `katex.render` builds DOM nodes and appends them (`katex.ts:49-51`: `baseNode.textContent = ""; const node = renderToDomTree(expression, options).toNode(); baseNode.appendChild(node);`). Neither returns a promise.
- MathJax 4: its documentation says output "is now potentially an asynchronous process" because font data loads in ranges. It says to use the promise calls, and that the synchronous ones can throw "MathJax retry" (`upgrading/whats-new-4.0/promises.rst:14-32`, `web/retry.rst`).

**What each needs at run time.**
- KaTeX needs its stylesheet, with the fonts "in a directory called `fonts` which is a sibling of the `katex.min.css` stylesheet" (`docs/font.md`). The fonts use `font-display: block` (`docs/browser.md`).
- MathJax 4 in a browser takes its fonts from jsDelivr unless `output.fontPath` points elsewhere. The documentation says so: "For in-browser use, this will obtain the font and its data from `cdn.jsdelivr.net`" (`upgrading/whats-new-4.0/fonts.rst:91-93`). The shipped bundle says it too: `tex-chtml.js` sets `fonts:mi.window?"https://cdn.jsdelivr.net/npm/@mathjax":"@mathjax"`. MathJax also autoloads TeX extensions from its own `input/tex/extensions/` (the sample pulled `boldsymbol.js`, `html.js`, and `color.js`), and with speech on it starts a worker that loads `sre/speech-worker.js`, `base.json`, `en.json`, and `nemeth.json`.

**MathJax 4 in Chromium** (`node checks/mathjax.js`, through [`mathjax.html`](04-viewer-demo/mathjax.html), with the same tokenizers emitting `\(...\)` and `\[...\]`):

| configuration | result | MathJax files, bytes | typeset |
|---|---|---|---|
| default | failed: "dynamic file 'double-struck' failed to load"; blocked `jsdelivr: @mathjax/mathjax-newcm-font@4.1.3/chtml/dynamic/double-struck.js`; 0 formulas | 4, 1,009,536 | none |
| `fontPath` local, speech on | 28 formulas | 19, 2,387,862 | 1,004 ms |
| `fontPath` local, speech off | 28 formulas | 15, 1,153,773 | 94 ms |
| the same, long.md (1,051 formulas) | all rendered | 12, 1,141,682 | 1,036 ms |
| the same, [`mjprobe.md`](04-viewer-demo/mjprobe.md) | `\eqref` and `\ref` resolved before and after the equation: "see (1) and 1", "After: (2), and inside math (1)" | 5, 1,133,782 | 44 ms |

In the same probe, MathJax's default TeX setup did the following:
- `\href{javascript:void(window.__pwned='mjhref')}{click me}` made a link, and clicking it ran the script (`ran: mjhref`);
- `\style{background:url(https://example.com/mj.png)}` made the browser request that image (blocked here);
- `\cssId{viewer}{w}` gave an element `id="viewer"`, and `\class{evil}` a class;
- `\ce` asked jsDelivr for `@mathjax/mathjax-mhchem-font-extension`.

MathJax's `html` extension defines exactly these macros and is loaded by autoload (`input/tex/extensions/html.rst`). Its `ui/safe` extension filters them and "is designed to support sites that allow users to enter mathematics that is viewed by others" (`options/safe.rst`).

**Versions and history.**
- npm: katex 0.18.9 was published 2026-09-23; mathjax 4.1.3 on 2026-07-03 (4.0.0 on 2025-08-04); mathjax 3.2.2 on 2022-06-08.
- KaTeX 0.18.0 (2026-07-17) prefixed KaTeX's CSS classes, a breaking change for "allowlists targeting KaTeX's internal classes" (`CHANGELOG.md`). Tags are now `.katex-tag`, which matters to any selector the build writes, and not to DOMPurify, which does not filter classes.

### 3. Coverage of a paper's LaTeX

`node checks/coverage.js` renders each construct in display mode. A pass means no KaTeX parse error and no red undefined command. For MathJax (`tags: 'ams'`, default TeX packages plus autoload, in Node) a pass means no `<merror>` and no red `<mtext>`. "KaTeX with shims" is `katexRenderer` from `markdown-math.js`.

| construct | KaTeX 0.18.9 | KaTeX with shims | MathJax 4.1.3 | MathJax 3.2.2 |
|---|---|---|---|---|
| align, align*, aligned, equation, gather, split, cases | ok | ok | ok | ok |
| multline | no | no (yes with the refs pass) | ok | ok |
| `\tag`, `\tag` in an align row, `\notag`, `\nonumber` | ok | ok | ok | ok |
| `\label` | no | ok | ok | ok |
| `\eqref`, `\ref` | no | no (yes with the refs pass) | ok | ok |
| `\mathbf`, `\boldsymbol`, `\mathbb \mathcal \mathrm \mathsf` | ok | ok | ok | ok |
| `\bm` | ok | ok | no | no |
| `\operatorname`, `\operatorname*` | ok | ok | ok | ok |
| `\DeclareMathOperator` | no | ok | ok | ok |
| `\newcommand` with an argument, `\def`, `\renewcommand{\R}` | ok | ok | ok | ok |
| `\newcommand{\R}` | no | ok | ok | ok |
| `\providecommand` | ok | ok | no | no |
| `\left \middle \right`, `\big`, `\text{... $x$ ...}`, `\xrightarrow`, `\overset`, `\underbrace`, `\substack`, `\lVert \rVert`, `\top \intercal \odot \otimes`, `\color`, accents, `\mathop \limits`, `array` with rules, `pmatrix`, `bmatrix`, `smallmatrix` | ok | ok | ok | ok |
| `\coloneqq` (mathtools) | ok | ok | no | no |
| `\mathbbm` (bbm), `\mathds` (dsfont), `\SI` (siunitx), `\qty` (physics) | no | no | no | no |
| `\ce` (mhchem) | no | no | no (needs its font extension from jsDelivr) | ok |
| `subequations`, `\cite` | no | no | no | no |
| **passed, of 46** | **33** | **36** | **36** | **37** |

KaTeX's own documentation agrees:
- `support_table.md:391`, `:556`, and `:905` list `\eqref`, `\label`, and `\ref` as "Not supported" (KaTeX issue #350);
- `supported.md:123-124` limits `\tag` rows to top-level `align`, `alignat`, and `gather` and their starred forms;
- `src/macros.ts:851-853` defines `\N`, `\R`, and `\Z` (from texvc), which is why a paper's `\newcommand{\R}` fails;
- `src/macros.ts:163-168` holds the two errors that `\newcommand` and `\renewcommand` raise.

`node checks/shims.js` counts failure marks with and without the shims:

| input | KaTeX alone | with the shims |
|---|---|---|
| `\begin{equation} a = b \label{eq:ab} \end{equation}` | 3 | 0 |
| `\newcommand{\R}{\mathcal{R}}\newcommand{\E}{\mathbb{E}} \R(\theta) = \E[\ell]` | 2 | 0 |
| `\DeclareMathOperator{\Tr}{Tr} \Tr(A)` | 9 | 0 |
| `\DeclareMathOperator*{\argmin}{arg\,min} \argmin_x f(x)` | 3 | 0 |

On [`refs.md`](04-viewer-demo/refs.md), without the refs pass KaTeX gave 1 error (`multline`), 3 CSS-counter numbers, and literal `\eqref{...}` text. With [`equation-refs.js`](04-viewer-demo/equation-refs.js) it gave 0 errors and these tags, display by display:
- the `equation`: `(1)`;
- the `align`: `(2)`, `(ELBO)`, `(3)`, the `\notag` row unnumbered;
- the `align*`: none;
- the `multline`: `(4)`.

The prose read "Bayes' rule is (1), the bound is (4), and row 3 closes the system" and "After: (2), (ELBO), ... a missing one (??)", matching amsmath.

Without the refs pass, KaTeX numbers unstarred environments with a CSS counter that `katex.min.css` resets on `body` (`body{counter-reset:katexEqnNo mmlEqnNo}`), so numbers would run on across everything on the page. Hence the `.markdown` reset in the build list.

### 4. Math through Markdown

**What today's pipeline does to math** (`node checks/pipeline.js`, P0 on [`sample.md`](04-viewer-demo/sample.md)):

```
<p>Inline dollars with underscores and stars: $x_i^* = \arg\min_{x} f(x_1, x_2)$ and $a^<em>b^</em>$ and ${x_i}_{i=1}^n$.
Parenthesis delimiters: (\mathbf{W}^\top \boldsymbol{\mu} \in \R^{d}) and a thin space (a,b;c!d).
<li>\log p(x) &amp;\ge \mathbb{E}_{q}\left[\log p(x, z) - \log q(z)\right] \tag{ELBO}
  a = b \
```

The CommonMark rules marked follows explain each of these:
- "Any ASCII punctuation character may be backslash-escaped" (spec 0.31.2, section 2.4), so `\(`, `\[`, `\{`, `\,`, `\;`, `\!`, and the `\\` of a row break lose their backslash;
- `+` is a bullet list marker (section 5.2), so an `align` row that starts with `+` becomes a list item;
- the `*` pairs in `a^*b^*` form emphasis (section 6.2).

**The extension** ([`markdown-math.js`](04-viewer-demo/markdown-math.js)) uses marked's documented extension API. An inline-level extension "will be handled inside each block-level token, before any of the inline-level tokenizer methods", a block-level one "before any of the block-level tokenizer methods", and `start()` tells marked where the next token may begin (`docs/USING_PRO.md`, "Custom Extensions"). The rules:
- **Delimiters.** `$` follows Pandoc's rule: "The opening `$` must have a non-space character immediately to its right, while the closing `$` must have a non-space character immediately to its left, and must not be followed immediately by a digit." Displayed math holds no blank line, also as in Pandoc: "there can be no blank lines between the opening and closing `$$` delimiters" (`MANUAL.txt:5514-5524`). These match GitHub's Markdown, which uses `$...$` and `$$...$$` (plus `` $`...`$ `` and ```` ```math ```` blocks, which the build may add).
- **Where a block starts.** The block `start()` reports only positions at a line's start, so a paragraph is never cut mid-line.
- **The emphasis mask.** marked's `emStrongMask` hook exists to "Mask part of the content that should not be interpreted as Markdown em/strong delimiters"; the example in marked's docs masks `$...$` for MathJax.

`node checks/edges.js` (math drawn as `[[...]]`):

| case | output |
|---|---|
| `*see $a*b$ here*` | `<em>see [[a*b]] here</em>`; without the mask hook `<em>see $a</em>b$ here*` |
| `**bold $x_1^*$ text**`, `_the value $x_i$ and $y_j$_` | strong and em around the math, math intact |
| `[the loss $\mathcal{L}$](https://example.com)`, a heading, list items | math inside each |
| `a formula $a +` newline `b$ across lines` | one formula |
| `costs \$5 and \$10`, `from $20,000 to $30,000`, `a $ b $ c` | text |
| an unclosed `$$` followed by two paragraphs and `$$y$$` | the paragraphs stay paragraphs; `y` renders |
| `$$`, `a`, blank line, `b`, `$$` | text (a display holds no blank line) |
| bare `\begin{align}` with a row starting `+ c` | one display |
| `` `$x$` and $y$ `` | a code span, then math |
| `| $|x|$ | ... |` in a GFM table | the pipe splits the cell; write `\lvert x \rvert` (which works) in tables |

Placeholders set aside before parsing were not needed. The tokenizers see only what marked has not already claimed as code, so fenced code and code spans are protected by marked itself, which a regular expression run before marked would have to redo.

### 5. Math through sanitizing

`node checks/pipeline.js` runs [`sample.md`](04-viewer-demo/sample.md) plus five payloads: three MathML namespace attempts, an `<annotation>` outside MathML, and a `<style>` with an attribute-selector `url()`. The sample itself carries, each in a block of its own, `<script>`, an `<img onerror>`, a raw and a Markdown `javascript:` link, an `<iframe>`, an `<svg><script>`, an mXSS `mglyph`/`style` nest, and a paragraph of TeX that tries to escape. marked emits the Markdown link as `<a href="javascript:...">`, and DOMPurify strips the `href`. The audit walks the final DOM for `script`, `iframe`, `object`, `embed`, `link`, `meta`, `base`, `style`, `foreignObject`, and `annotation-xml`, for any `on*` attribute, and for any `javascript:`, `vbscript:`, or `data:` URL.

| pipeline | formulas | annotations kept | DOMPurify removed (its `removed` list, a report and never a check) | audit |
|---|---|---|---|---|
| P0 today: `DOMPurify.sanitize(marked.parse(md))` | 0 | n/a | 2 `script`, 5 `onerror`, 2 `href`, 1 `iframe`, 1 `mglyph`, 2 `semantics`, 3 `annotation`, 1 `annotation-xml`, 1 `style` | a `<style>` survives |
| P1 render, then DOMPurify's defaults | 23 | 0 | 25 `semantics`, 26 `annotation`, 2 `script`, 3 `onerror`, 2 `href`, 1 `iframe`, 1 `mglyph`, 1 `annotation-xml`, 1 `style` | a `<style>` survives |
| P2 DOMPurify's defaults, then `katex.render()` | 22 | 22 | 2 `script`, 3 `onerror`, 2 `href`, 1 `iframe`, 1 `mglyph`, 2 `semantics`, 3 `annotation`, 1 `annotation-xml`, 1 `style` | a `<style>` survives |
| **P3 render, then `MATH_PURIFY`** | **23** | **23** | 2 `script`, 3 `onerror`, 2 `href`, 1 `iframe`, 1 `mglyph`, 1 `annotation-xml`, 2 `style`, 1 `annotation` (the one outside MathML) | **nothing** |

From P1 on, two of the five `onerror` payloads sit inside `$...$`, so they are TeX and render as KaTeX's red source. P2 calls `katex.render()` without the shims, so its `\newcommand{\R}` is an error and it counts 22 formulas.

**What DOMPurify does to KaTeX's output.** The same `renderToString` output, compared formula by formula before and after sanitizing, changed in 23 of 23 formulas under DOMPurify's defaults and in 0 of 23 under `MATH_PURIFY`. Under the defaults, each `<math>` ends with its TeX as loose text. The first one, for example, ends `...ommand{\norm}[1]{\left\lVert #1 \right\rVert}`, left behind by the removed `<annotation>`, which screen readers would read out.

**Why `semantics` and `annotation` are safe to add.**
- DOMPurify's source lists them in `mathMlDisallowed` beside `annotation-xml` (`purify.es.mjs:310`), but only `annotation-xml` is an HTML integration point (`DEFAULT_HTML_INTEGRATION_POINTS = ['annotation-xml']`, `:756`). DOMPurify's threat model names "Foreign content: namespace confusion and integration points (`foreignObject`, `annotation-xml`)" as "where much mXSS lives".
- The payload `<math><semantics>...<annotation encoding="text/html"><img onerror=...>` came out as an empty `<annotation>`: the `<img>` broke out of MathML, as the HTML parser makes it, and lost its `onerror`.
- `<annotation><style>...` lost its `<style>`, and an `<annotation>` outside MathML was removed by DOMPurify's namespace check.
- The README asks readers to check that threat model list before using `ADD_TAGS`, and to "not use" `DOMPurify.removed` "for making any security critical decisions"; the audit above is the check.

**KaTeX's side.**
- `trust: false` refuses `\url`, `\href`, `\includegraphics`, `\htmlClass`, `\htmlId`, `\htmlStyle`, and `\htmlData` (`docs/options.md`); in the browser run they produced no link and no image.
- `maxExpand` stopped `\def\a{\a}\a` ("Too many expansions"), and `maxSize` caps `\rule{9999em}{9999em}` at 20 em.
- `throwOnError: false` renders a bad expression "as its source code with hover text giving the error", so one bad formula never blanks the page. Four such errors in the sample were all injection attempts or the macro loop.
- `strict: 'ignore'` keeps KaTeX from writing `console.warn`.

KaTeX's advisories (GitHub security advisories of `KaTeX/KaTeX`) concern trust-gated commands and `maxExpand`:
- `\htmlData` attribute names (CVE-2025-23207, fixed 0.16.21) and `\includegraphics` quoting (CVE-2024-28245, fixed 0.16.10) could put script in the page. Both list "Sanitize HTML output from KaTeX" among their workarounds.
- Inherited `trust` through prototype pollution elsewhere on the page (GHSA-238p-pmpm-9mq7, fixed 0.18.2) says exploitation "requires the consuming application to insert KaTeX output into a web page without a separate sanitizer".
- The protocol case of a `trust` function (CVE-2024-28246) and two `maxExpand` bypasses (CVE-2024-28243 and CVE-2024-28244, denial of service) were fixed in 0.16.10.

This is why the recommendation sanitizes after rendering rather than trusting `katex.render()`.

**In the browser** (`node checks/chromium.js`), the sample's page showed:
- 23 formulas, 5 displays, 23 annotations, and 0 `<style>` elements;
- `window.__pwned` still undefined after 500 ms, so no handler and no script ran;
- no request left `127.0.0.1`;
- as console messages, only the 404s for the payloads' `<img src=x>`.

**Cost of sanitizing KaTeX's output** (Chromium, medians of five, this workstation):

| document | marked with KaTeX | DOMPurify | into the DOM | marked alone |
|---|---|---|---|---|
| sample.md, 2,623 bytes | 2.7 ms | 5.9 ms | 1.0 ms | 0.6 ms |
| long.md, 60,459 bytes, 1,051 formulas | 148.0 ms | 459.0 ms | 80.0 ms | 6.2 ms |

The viewer's whole render of long.md, from text to the new document, took 792 ms.

### 6. The popup

**What the HTML Standard says about `<dialog>`** (checked against the standard's `source` file, fetched 2026-09-28).
- `showModal()` sets the document "to be blocked by the modal dialog", sets the dialog's "previously focused element to the focused element", and runs the dialog focusing steps.
- While blocked, "every node that is connected to document, with the exception of the subject element and its flat tree descendants, must become inert", and for an inert node "Hit-testing must act as if the 'pointer-events' CSS property were set to 'none'".
- The focusing steps take the dialog's focus delegate: a descendant with `autofocus`, else, for a dialog, its first sequentially focusable descendant, else the dialog itself.
- Closing a dialog that was modal runs the focusing steps for its previously focused element.
- Escape is a close request, which fires `cancel` and then closes.
- `closedby="any"` means "Close requests or clicks outside close the dialog".

**Measured** (`node checks/chromium.js`, `node checks/firefox.js`):

| behavior | Chromium 149 | Firefox 156 |
|---|---|---|
| focus on open (`autofocus` on the scroll container) | `div#viewer-body` | `div#viewer-body` |
| PageDown | the document scrolls 615 px; the page 0 | not run |
| Escape | closed; focus on the view button | closed; focus on the view button |
| click at (5, 5) on the backdrop | `elementFromPoint` is the `<dialog>`; closed | closed |
| a click on a page button while open | Playwright refused it: "`<dialog>` ... intercepts pointer events" | not run |
| Tab from the document | 3 wide displays, then the browser's own chrome (reported as `body`), then minus, level, plus, download, close, the document | not run |
| wheel over the document (5 x 600 px) | document 2,400 px (3,000 in an earlier run; smooth scrolling varies); page 0 | not run |
| wheel past the end, then over the backdrop | page 0 | not run |
| wheel over the backdrop without `html:has(dialog[open]) { overflow: hidden }` | page 2,485 px | not run |
| `closedBy` in `HTMLDialogElement.prototype` | yes | yes |

Chromium makes a display equation that scrolls sideways a Tab stop of its own, which lets the keyboard scroll it.

**Browser support** (MDN browser-compat-data, main, fetched 2026-09-28):
- `<dialog>` and `showModal()`: Chrome 37, Firefox 98, Safari 15.4;
- `::backdrop` on a dialog: Chrome 32, Firefox 98, Safari 15.4;
- `closedby`: Chrome 134, Firefox 141, Safari "preview", hence the three-line click handler;
- `:has()`: Chrome 105, Firefox 121, Safari 15.4;
- `dvh`: Chrome 108, Firefox 101, Safari 15.4;
- `overscroll-behavior`: Chrome 63, Firefox 59, and Safari 16 with a partial note ("no effect on scroll containers that have no scrollable overflow", which does not apply to a scrolling document), in full from Chrome 144 and Firefox 150.

**Where it lives.** The in-place preview is `<div id="outputs-preview">`, which `renderOutputs` pushes into `#outputs-body` and replaces on every change of the outputs index (app.js:1089-1098). A `<dialog>` there would be removed from under the owner during a run. `index.html` already keeps one such element outside the panels, `#node-card` (line 175).

### 7. Zoom

- **The CSS Viewport Module Level 1 editor's draft** (`css-viewport-1/Overview.bs:476-493`, fetched 2026-09-28) says the used value of a property "is pre-multiplied ... by the used value of 'zoom' for the element", "Nested values of 'zoom' multiply", and "Unlike 'transform', scaling the 'zoom' property affects layout".
- **MDN:** "Baseline 2024 ... Since May 2024, this feature works across the latest devices and browser versions". It also says `scale()` "will not cause layout recalculation", and "If using `scale()` makes the contents larger than the containing element, then `overflow` comes into effect".
- **Compat data:** Chrome 1, Firefox 126 ("Before Firefox 131, SVG elements are not zoomed properly"), Safari 3.1, Safari on iOS 3.

Measured, second paragraph of the sample (on-screen width x height in px; layout width in CSS px):

| window | 100% | `zoom: 1.5` | `transform: scale(1.5)` |
|---|---|---|---|
| Chromium, 1280x800 | 580x83, layout 580 | 870x126, layout 580 | 870x125, layout 580 |
| Chromium phone, 390x844 | 358x121, layout 358 | **358x241, layout 239** (rewrapped) | **537x181, layout 358** (lines run past the edge) |
| Firefox, 390x844 window | 346x124, layout 346 | 346x270, layout 231 (rewrapped) | not run |

In a wide window the paragraph is capped at 78ch, so both methods look alike; on a phone only `zoom` keeps the text on the screen. Wide displays scroll inside themselves through `.katex-display { overflow-x: auto }`. At 150% on the phone, three things outside the displays were still wider than the screen, and no paragraph text was:
- the fenced code line, inside its `<pre>`, which scrolls on its own;
- the empty `<svg>` an injection payload left (300x150 by default);
- the 20 em rule of the capped `\rule{9999em}{9999em}`.

For those, the document scrolls sideways. The first inline formula grew from 150x17 to 221x26 under `zoom` (225x26 under `transform`). The desktop, phone, and Firefox renders at 150% were inspected by eye: KaTeX's glyphs and SVG delimiters scale cleanly.

The keys `+`/`=`, `-`, and `0` are handled on the dialog, skip form fields, and leave Ctrl, Cmd, and Alt alone, so the browser's own zoom still works on the whole page. `app.js` has no `keydown` handler today, so nothing conflicts.

### 8. From a phone, through the tunnel

- **Fit.** The phone run tapped the view button and got a viewer at `[0, 0, 390, 844]`, the whole window, with bar buttons 44 px tall (the demo's rule below 720 px).
- **Bytes through the tunnel.** The first view of the sample fetched `katex.min.js`, `katex.min.css`, and 8 fonts (AMS, Caligraphic, Main regular and bold, Math italic and bold italic, Size1, Size2): 427,639 bytes, on top of what the dashboard already loads. `refs.md` added `KaTeX_Size4`. The dashboard's server answers static files with an `ETag` and `Cache-Control: no-cache` (`wayline/dashboard.py:1568-1576`) and a 304 when unchanged (`:1594`). It maps `.woff2` to `font/woff2` (`:130`), and `static_file` serves any path under `dashboard/` (`:1059`), so `vendor/katex/fonts/...` resolves.
- **Pinch zoom.** The dashboard's `<meta name="viewport" content="width=device-width, initial-scale=1">` does not disable it. It magnifies without rewrapping; the zoom control rewraps.

### 9. Not verified, and how to rebuild

**Not verified:**
- Safari and Safari on iOS: no WebKit build is installed here, so their support rests on MDN's compat data.
- A real phone, or a phone's SSH client forwarding the port.
- The real dashboard server serving KaTeX: the demo was served by Python's `http.server`, and the server's behavior was read from code.
- A screen reader's reading of the MathML.
- Timings on the owner's laptop or phone.
- MathJax 3.2.2 in a browser: coverage only, in Node.
- mXSS resistance beyond the payloads listed, in jsdom, Chromium, and Firefox.
- The refs pass beyond the cases in `refs.md`: `\label` inside `split`, `\\` inside `\text{}`, and `subequations` were not tried.

**Rebuild and rerun** (Node and npm; nothing is installed in the repository):

```
# packages, outside the repository
mkdir -p /tmp/viewer-checks && cd /tmp/viewer-checks
cp <repo>/.scratch/living-paper/research-notes/04-viewer-demo/checks/package.json . && npm install

# a served copy of the demo, with its vendored files (and MathJax, for the probe)
cp -r <repo>/.scratch/living-paper/research-notes/04-viewer-demo /tmp/viewer-demo
bash /tmp/viewer-demo/fetch-vendor.sh <repo> --mathjax
python3 /tmp/viewer-demo/make-long.py
python3 -m http.server 8792 --bind 127.0.0.1 --directory /tmp/viewer-demo &

# the checks, from the repository
cd <repo>/.scratch/living-paper/research-notes/04-viewer-demo
export NODE_PATH=/tmp/viewer-checks/node_modules DEMO_URL=http://127.0.0.1:8792/ OUT=/tmp/viewer-shots
node checks/sizes.js; node checks/coverage.js; node checks/shims.js; node checks/edges.js; node checks/pipeline.js
node checks/chromium.js; node checks/mathjax.js; node checks/firefox.js
```

The demo itself is `http://127.0.0.1:8792/index.html`; `?open=sample.md&zoom=150` opens the viewer on load.

## Sources

- KaTeX 0.18.9 package: `dist/katex.min.css` (the `@font-face` rules and `body{counter-reset:katexEqnNo mmlEqnNo}`), `katex.ts:49-51`, `src/macros.ts:145-202` and `:851-853`, `LICENSE`. <https://www.npmjs.com/package/katex>
- KaTeX documentation, `docs/` at <https://github.com/KaTeX/KaTeX/tree/main/docs>: `options.md`, `security.md`, `font.md`, `browser.md` (SRI hashes, `font-display`), `api.md`, `supported.md:102-124`, `support_table.md:391,556,905`. Also `CHANGELOG.md` (0.17.0 to 0.18.9).
- KaTeX security advisories: <https://github.com/KaTeX/KaTeX/security/advisories> (GHSA-238p-pmpm-9mq7, CVE-2025-23207, CVE-2024-28243, CVE-2024-28244, CVE-2024-28245, CVE-2024-28246).
- KaTeX fonts license: <https://github.com/KaTeX/katex-fonts/blob/main/LICENSE>
- MathJax documentation, <https://github.com/mathjax/MathJax-docs> (master), rendered at <https://docs.mathjax.org/>: `web/hosting.rst`, `upgrading/whats-new-4.0/fonts.rst:91-93`, `upgrading/whats-new-4.0/promises.rst:14-32`, `web/retry.rst`, `input/tex/eqnumbers.rst`, `input/tex/delimiters.rst`, `input/tex/extensions/html.rst`, `options/safe.rst`, `web/components/combined.rst`, `options/accessibility.rst`.
- MathJax 4.1.3 package, `tex-chtml.js` (the `fonts:mi.window?"https://cdn.jsdelivr.net/npm/@mathjax":"@mathjax"` default). <https://www.npmjs.com/package/mathjax>
- marked 18.0.12 documentation: `docs/USING_PRO.md` (extensions, `start`, hooks including `emStrongMask` and `processAllTokens`), `docs/USING_ADVANCED.md`, and `README.md` (the sanitizing warning), at <https://github.com/markedjs/marked/tree/v18.0.12>. Also `lib/marked.esm.js` (`parseMarkdown`: preprocess, lex, processAllTokens, walkTokens, parse, postprocess).
- marked-katex-extension 5.1.13, `lib/index.cjs` (its `$` and `$$` rules). <https://github.com/UziTech/marked-katex-extension>
- DOMPurify 3.4.15: `README.md` at <https://github.com/cure53/DOMPurify/tree/3.4.15> (default profiles, `removed`, `FORBID_TAGS`, `ADD_TAGS`), `dist/purify.es.mjs:299,310,756`. Threat model, lines 31-32 ("CSS-based attacks", "HTTP leaks") and 79 (`math`, `svg`) of the wiki page: <https://github.com/cure53/DOMPurify/wiki/Security-Goals-&-Threat-Model#dangerous-tags-and-attributes-think-twice-before-allow-listing>
- CommonMark spec 0.31.2, sections 2.4, 5.2, 6.2: <https://spec.commonmark.org/0.31.2/>
- Pandoc manual, `MANUAL.txt:5512-5524` ("Extension: `tex_math_dollars`"): <https://github.com/jgm/pandoc/blob/main/MANUAL.txt>
- GitHub, "Writing mathematical expressions": <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/writing-mathematical-expressions>
- HTML Standard (its `source` file at <https://github.com/whatwg/html>, fetched 2026-09-28): the dialog element and `showModal()` <https://html.spec.whatwg.org/multipage/interactive-elements.html#the-dialog-element>, the dialog focusing steps <https://html.spec.whatwg.org/multipage/interactive-elements.html#dialog-focusing-steps>, `closedby` <https://html.spec.whatwg.org/multipage/interactive-elements.html#attr-dialog-closedby>, inert <https://html.spec.whatwg.org/multipage/interaction.html#inert>, blocked by a modal dialog <https://html.spec.whatwg.org/multipage/interaction.html#blocked-by-a-modal-dialog>, the focus delegate <https://html.spec.whatwg.org/multipage/interaction.html#focus-delegate>
- CSS Viewport Module Level 1, editor's draft, the `zoom` property: <https://drafts.csswg.org/css-viewport-1/#zoom-property>, from `css-viewport-1/Overview.bs:476-493` at <https://github.com/w3c/csswg-drafts>
- MDN, `zoom` (page source `files/en-us/web/css/reference/properties/zoom/index.md:13-17` in mdn/content): <https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/zoom>
- MDN browser-compat-data (main, fetched 2026-09-28): `css/properties/zoom.json`, `html/elements/dialog.json`, `api/HTMLDialogElement.json`, `css/selectors/has.json`, `css/selectors/backdrop.json`, `css/types/length.json`, `css/properties/overscroll-behavior.json`, at <https://github.com/mdn/browser-compat-data>
- This repository: `dashboard/app.js:159-167,312,936,1073-1077,1089-1144`, `dashboard/index.html:175-184`, `dashboard/style.css:756-800`, `dashboard/vendor/VENDOR.md`, `wayline/dashboard.py:115-131,1059-1076,1568-1576,1594`, `tests/test_dashboard.py:47-50,953,997-999,1019-1034`; `.scratch/wayline/spec.md` decision 8; `.scratch/wayline/issues/58-dashboard-design-pass.md`.
