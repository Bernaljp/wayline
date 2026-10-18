# Vendored static assets

marked, DOMPurify, and KaTeX with its fonts, pinned and checked in, served by the dashboard and never imported by the
harness. Implementation Decisions 1 scopes "standard library only" to the Python package; the
dashboard front end is the one place the runtime demands JavaScript, and a checked-in file the
server hands to a browser is a static asset, not a dependency: nothing installs, builds, or
resolves it, and the workstation needs no network to serve it.

Markdown from the ledger is written by workers (models) and the dashboard grows action endpoints in
M4, so sanitizing is not optional: `DOMPurify.sanitize(marked.parse(md))` is the only path from
markdown to HTML in `app.js`. marked does not sanitize its own output and says so.

Since ticket 74 that one path renders math first and sanitizes after: KaTeX runs under
`trust: false` inside marked's extension, and the whole page then goes through
`DOMPurify.sanitize(html, { ADD_TAGS: ['semantics', 'annotation'], FORBID_TAGS: ['style'] })`.
The two added tags are the MathML wrappers KaTeX writes around every formula; `<style>` is refused
because a document's stylesheet would restyle the whole dashboard (the v1.0.1 hole). The fonts
live at `katex/fonts/`, the sibling directory `katex.min.css` names in its relative
`url(fonts/...)`, so no font is fetched from anywhere but the dashboard. Only the woff2 fonts are
vendored: the stylesheet lists woff2 first in every `@font-face`, and a browser that reads woff2
never asks for the woff and ttf fallbacks (research note 04, `research/viewer-math-and-zoom`).

| File | Package | Version | License | Bytes | SHA-256 |
|---|---|---|---|---|---|
| `marked.umd.js` | [marked](https://github.com/markedjs/marked) | 18.0.12 | MIT | 44870 | `fa0cfbf0181339312eaa3709b577ad698fc21a9baa42d580a3fd1f267b19b4a8` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.15 | MPL-2.0 OR Apache-2.0 | 29369 | `f263b05369e050fa175d4ecb9c9358eb4253602d510297adfb31df48b2f1c4d5` |
| `katex/LICENSE` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 1107 | `766ccc1f306c885aa45542a9846bbd0a505b27a0374f146778171c2254ce18e3` |
| `katex/katex.min.js` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 272755 | `155f6c2d673c5912e3b48f45d8830eaad18ae1953915939ceb648ea8b9c3e7e2` |
| `katex/katex.min.css` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 24788 | `b9ce0e8ce93f0c18c4986fe1f1c3c269d921b56a69e6c97f83a507916b38aab5` |
| `katex/fonts/KaTeX_AMS-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 28076 | `0cdd387c9590a1a9f9794560022dbb59654a7d86f187aa0c81495ad42d3a7308` |
| `katex/fonts/KaTeX_Caligraphic-Bold.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 6912 | `de7701e42cf1f4cf0b766c03fb27977207eee2f4fd5d76fa82188406da43ea4c` |
| `katex/fonts/KaTeX_Caligraphic-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 6908 | `5d53e70ad607c2352162dec9e0923fb54ecdafaccbf604cd8dcf7d00facb989b` |
| `katex/fonts/KaTeX_Fraktur-Bold.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 11348 | `74444efd593c005e3f4573b44524704c0af0a937fe911cca9e94068d0d140d3f` |
| `katex/fonts/KaTeX_Fraktur-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 11316 | `51814d270d06ff0255dba0799994fa4d8c84d11f09951d47595f4abb1f3602dc` |
| `katex/fonts/KaTeX_Main-Bold.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 25324 | `0f60d1b897938ec918c8ce073092411baf9438f6739465693ff18b0f9d20b021` |
| `katex/fonts/KaTeX_Main-BoldItalic.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 16780 | `99cd42a3c072d918f2f44984a807cf7aa16e13545fd0875fc07c6c65f99e715b` |
| `katex/fonts/KaTeX_Main-Italic.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 16988 | `97479ca6cce906abc961ecac96faa5f9ca2e61b8e7670d475826bcdee9a7c267` |
| `katex/fonts/KaTeX_Main-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 26272 | `c2342cd8b869e01752a9321dc17213fc40d4d04c79688c1d43f2cf316abd7866` |
| `katex/fonts/KaTeX_Math-BoldItalic.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 16400 | `dc47344dbb6cb5b655c8460d561f4df5f501b90c804ad3c6cec65fe322351ab1` |
| `katex/fonts/KaTeX_Math-Italic.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 16440 | `7af58c5ec8f132a2ddde9027c6d7814decce4d3b822a11192a42a20e2e973264` |
| `katex/fonts/KaTeX_SansSerif-Bold.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 12216 | `e99ae51144bf1232efcc1bfe5add36262c6866b0faab24fa75740e1b98577a62` |
| `katex/fonts/KaTeX_SansSerif-Italic.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 12028 | `00b26ac825e2095056396e0553b8ac26d3f8ad158c3826e28b4c45b385c4714a` |
| `katex/fonts/KaTeX_SansSerif-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 10344 | `68e8c73ef42afd3ccec58bf0fba302cce448938e7fc020a5e31f8a952eee1342` |
| `katex/fonts/KaTeX_Script-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 9644 | `036d4e95149b69ff9bcc0cd55771efeb25ffa3947293e69acd78d5ac328c684b` |
| `katex/fonts/KaTeX_Size1-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 5468 | `6b47c40166b6dbe21a5dfca7718413f2147fd2399be1ba605d8ad39cedf25dfe` |
| `katex/fonts/KaTeX_Size2-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 5208 | `d04c54219f9eaec6d4d4fd42dfb28785975a4794d6b2fc71e566b9cd6db842dd` |
| `katex/fonts/KaTeX_Size3-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 3624 | `73d591271b1604960cb10bb90fee021670af7297017e0e98480b332d11f51995` |
| `katex/fonts/KaTeX_Size4-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 4928 | `a4af7d414440a1c1790825cfb700cf9cf43b0f2c4b04f0ebc523011ad9853ec0` |
| `katex/fonts/KaTeX_Typewriter-Regular.woff2` | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.18.9 | MIT | 13568 | `71d517d67827787cfabdf186914cc3358eda539e37931941f2b2fd4a21f68c0b` |

Fetched 2026-09-12 from jsDelivr:

```
curl -sSL -o marked.umd.js  https://cdn.jsdelivr.net/npm/marked@18.0.12/lib/marked.umd.js
curl -sSL -o purify.min.js  https://cdn.jsdelivr.net/npm/dompurify@3.4.15/dist/purify.min.js
sha256sum marked.umd.js purify.min.js
```

KaTeX 0.18.9 was fetched 2026-10-18 with `npm pack`; its `katex.min.js` and `katex.min.css` match
the SRI hashes KaTeX publishes for 0.18.9 in `docs/browser.md`
(`sha384-19KE2cFb3U+RUWmyhBz7aLOGDG8WrRC6hE3oY/HTZZlAAVWYTdmvLC//+TIV3zUx` and
`sha384-lPx0C4zIUZLpveABMwOFcFeGZwsvKBJfhJ85FN1PYOV7xApBcFMhcAEMVKF8loOI`):

```
npm pack katex@0.18.9 && tar -xzf katex-0.18.9.tgz
cp package/LICENSE package/dist/katex.min.js package/dist/katex.min.css katex/
cp package/dist/fonts/*.woff2 katex/fonts/
```

`tests/test_dashboard.py` asserts every size and digest, so an upgrade is a deliberate edit of this
table rather than a file that drifted. marked's shipped size matches the 44,870 bytes
`research-notes/08-dashboard-transport.md` Section 4 recorded for the same version, and DOMPurify's
matches the 29,369 bytes recorded there for its `dist/purify.min.js`.
