#!/bin/bash
# Rebuild the demo's vendor/ directory: marked and DOMPurify as the dashboard pins them, and KaTeX
# 0.18.9's browser build with its woff2 fonts only (the stylesheet lists woff2 first, and a browser
# that reads woff2 never asks for the woff and ttf fallbacks). With --mathjax, also vendor-mj/:
# MathJax 4.1.3 and its default font, for the mathjax.html probe.
#
# Usage: fetch-vendor.sh <wayline repository> [--mathjax]
# Needs npm once, for `npm pack` in a temporary directory; nothing is fetched when the page runs.
repo="${1:?usage: fetch-vendor.sh <wayline repository> [--mathjax]}"
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)" || exit 1
mkdir -p "$here/vendor/katex/fonts" || exit 1
cp "$repo/dashboard/vendor/marked.umd.js" "$repo/dashboard/vendor/purify.min.js" "$here/vendor/" || exit 1
(cd "$work" && npm pack katex@0.18.9 --silent >/dev/null && tar -xzf katex-0.18.9.tgz) || exit 1
cp "$work/package/dist/katex.min.js" "$work/package/dist/katex.min.css" "$here/vendor/katex/" || exit 1
cp "$work/package/dist/fonts/"*.woff2 "$here/vendor/katex/fonts/" || exit 1
if [ "$2" = "--mathjax" ]; then
  mkdir -p "$here/vendor-mj" "$work/mj" "$work/font" || exit 1
  (cd "$work/mj" && npm pack mathjax@4.1.3 --silent >/dev/null && tar -xzf mathjax-4.1.3.tgz) || exit 1
  (cd "$work/font" && npm pack @mathjax/mathjax-newcm-font@4.1.3 --silent >/dev/null && tar -xzf mathjax-mathjax-newcm-font-4.1.3.tgz) || exit 1
  rm -rf "$here/vendor-mj/mathjax" "$here/vendor-mj/mathjax-newcm-font"
  cp -r "$work/mj/package" "$here/vendor-mj/mathjax" || exit 1
  cp -r "$work/font/package" "$here/vendor-mj/mathjax-newcm-font" || exit 1
fi
rm -rf "$work"
(cd "$here/vendor" && sha256sum marked.umd.js purify.min.js katex/katex.min.js katex/katex.min.css)
