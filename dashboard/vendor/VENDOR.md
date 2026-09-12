# Vendored static assets

Two JavaScript files, pinned and checked in, served by the dashboard and never imported by the
harness. Implementation Decisions 1 scopes "standard library only" to the Python package; the
dashboard front end is the one place the runtime demands JavaScript, and a checked-in file the
server hands to a browser is a static asset, not a dependency: nothing installs, builds, or
resolves it, and the workstation needs no network to serve it.

Markdown from the ledger is written by workers (models) and the dashboard grows action endpoints in
M4, so sanitizing is not optional: `DOMPurify.sanitize(marked.parse(md))` is the only path from
markdown to HTML in `app.js`. marked does not sanitize its own output and says so.

| File | Package | Version | License | Bytes | SHA-256 |
|---|---|---|---|---|---|
| `marked.umd.js` | [marked](https://github.com/markedjs/marked) | 18.0.12 | MIT | 44870 | `fa0cfbf0181339312eaa3709b577ad698fc21a9baa42d580a3fd1f267b19b4a8` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.15 | MPL-2.0 OR Apache-2.0 | 29369 | `f263b05369e050fa175d4ecb9c9358eb4253602d510297adfb31df48b2f1c4d5` |

Fetched 2026-09-12 from jsDelivr:

```
curl -sSL -o marked.umd.js  https://cdn.jsdelivr.net/npm/marked@18.0.12/lib/marked.umd.js
curl -sSL -o purify.min.js  https://cdn.jsdelivr.net/npm/dompurify@3.4.15/dist/purify.min.js
sha256sum marked.umd.js purify.min.js
```

`tests/test_dashboard.py` asserts both sizes and digests, so an upgrade is a deliberate edit of this
table rather than a file that drifted. marked's shipped size matches the 44,870 bytes
`research-notes/08-dashboard-transport.md` Section 4 recorded for the same version, and DOMPurify's
matches the 29,369 bytes recorded there for its `dist/purify.min.js`.
