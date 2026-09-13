"""Rebuild the toy project's generated pieces: two PDFs, one arXiv-style tarball, three cassettes.

`python3 fixtures/projects/toy/make.py` writes:

- `materials/paper-a.pdf` and `materials/paper-b.pdf` (with their `.tex` sources kept alongside,
  the `fixtures/pdf/make.py` convention), built by `pdflatex`.
- `materials/paper-c-source.tar.gz`, an arXiv-style e-print source in the shape
  `fixtures/arxiv/make.py` writes, whose text names `fixtures/code/tiny-pkg.git` at its pinned
  tag `v0.1.0` as the paper's code release.
- Three recorded responses under `fixtures/fetch/`, so `wayline absorb --level 0 --fixtures
  fixtures/fetch` resolves the three references of `research/INTAKE.md` with no network: Crossref
  for the two DOIs, the arXiv API for the arXiv id. These are invented works (Implementation
  Decisions 14 says "synthetic"), so nothing here reaches a real service; the responses are
  written by hand, in the shape `wayline.scout` reads.

Nothing under `research/` or `harness.json` is generated: those are hand-authored, the way
`fixtures/projects/ten-references/` and `fixtures/projects/m0-live/` are.
"""

import os
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.parse
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS_ROOT = HERE.parents[2]
sys.path.insert(0, str(HARNESS_ROOT))

from wayline.fetch import Request, canonical_url  # noqa: E402
from wayline.scout import ARXIV_QUERY, CROSSREF_WORK, _with  # noqa: E402

EMAIL = "owner@example.org"
FETCH = HARNESS_ROOT / "fixtures" / "fetch"
TINY_PKG = HARNESS_ROOT / "fixtures" / "code" / "tiny-pkg.git"
TINY_PKG_SHA = "5de2bb44acea3892f9e0fc5c7b5b401179889958"

# --- the two PDFs -----------------------------------------------------------------------------

PAPER_A = r"""\documentclass{article}
\pdfinfoomitdate=1
\pdftrailerid{}
\pdfsuppressptexinfo=-1
\title{Interaction terms improve tabular classification on synthetic benchmarks}
\author{Ada Query}
\date{2022}
\begin{document}
\maketitle
\begin{abstract}
On a synthetic two-class set whose label depends on a linear part and one pairwise interaction
between two features, a model that also sees the interaction term reaches a higher held-out AUROC
than one that sees only the linear features. This paper is one of two written for a test fixture,
never a paper anyone submitted anywhere.
\end{abstract}
\section{Method}
Two features are drawn uniformly and multiplied; the product is added to the model's inputs
alongside the linear features already there.
\section{Result}
The interaction term raises held-out AUROC by several points over the linear-only model, on every
signal strength tried.
\end{document}
"""

PAPER_B = r"""\documentclass{article}
\pdfinfoomitdate=1
\pdftrailerid{}
\pdfsuppressptexinfo=-1
\title{A held-out evaluation protocol for small synthetic datasets}
\author{Bo Split}
\date{2020}
\begin{document}
\maketitle
\begin{abstract}
A fixed fraction of a synthetic set, drawn once and never used for fitting, is enough to compare
two models honestly as long as the draw is seeded and the split is taken from the same ordered
sequence every time. This paper is one of two written for a test fixture, never a paper anyone
submitted anywhere.
\end{abstract}
\section{Protocol}
Generate every row from one seeded stream, in order; hold out the last fifth for evaluation only.
\end{document}
"""


def build_pdf(name, tex):
    if not shutil.which("pdflatex"):
        sys.exit("pdflatex is not installed; the fixture cannot be rebuilt on this machine")
    workspace = Path.home() / ".cache" / "wayline-toy-fixture" / name
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    (workspace / (name + ".tex")).write_text(tex, encoding="utf-8")
    env = dict(os.environ, SOURCE_DATE_EPOCH="1700000000", FORCE_SOURCE_DATE="1")
    for _ in range(2):
        done = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", name + ".tex"],
            cwd=str(workspace), capture_output=True, env=env,
        )
        if done.returncode != 0:
            sys.exit(done.stdout.decode("utf-8", errors="replace")[-2000:])
    materials = HERE / "materials"
    materials.mkdir(exist_ok=True)
    shutil.copyfile(workspace / (name + ".pdf"), materials / (name + ".pdf"))
    shutil.copyfile(workspace / (name + ".tex"), materials / (name + ".tex"))
    print((materials / (name + ".pdf")).name, (materials / (name + ".pdf")).stat().st_size, "bytes")


# --- the arXiv-style tarball -------------------------------------------------------------------

MS = r"""\documentclass{article}
\title{A tiny code repository for reproducible toy experiments}
\author{Cy Repo}
\begin{document}
\maketitle
\begin{abstract}
The toy project's dataset generator and training script are released as a small package, tagged
once, so a reader can reproduce a run from the exact commit this paper names. This paper is
written for a test fixture, never a paper anyone submitted anywhere.
\end{abstract}
\input{sections/availability}
\end{document}
"""

AVAILABILITY = r"""\section{Code availability}
The package is tagged \texttt{v0.1.0} at commit \texttt{%s}.
""" % TINY_PKG_SHA

README_JSON = """{
  "process": {"compiler": "pdflatex"},
  "sources": [
    {"filename": "ms.tex", "usage": "toplevelfile"},
    {"filename": "sections/availability.tex", "usage": "include"}
  ]
}
"""


def write_tarball(target, files):
    raw_path = target.with_suffix(".tar")
    with tarfile.open(raw_path, mode="w") as archive:
        for name, payload in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = 1700000000
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, __import__("io").BytesIO(payload))
    with open(raw_path, "rb") as source, open(target, "wb") as handle:
        with __import__("gzip").GzipFile(fileobj=handle, mode="wb", mtime=0) as zipped:
            zipped.write(source.read())
    raw_path.unlink()
    return target


def build_tarball():
    files = {
        "00README.json": README_JSON.encode("utf-8"),
        "ms.tex": MS.encode("utf-8"),
        "sections/availability.tex": AVAILABILITY.encode("utf-8"),
    }
    materials = HERE / "materials"
    materials.mkdir(exist_ok=True)
    target = write_tarball(materials / "paper-c-source.tar.gz", files)
    print(target.name, target.stat().st_size, "bytes")


# --- the three cassettes -------------------------------------------------------------------------

DOI_A = "10.9999/wayline.toy.a"
DOI_B = "10.9999/wayline.toy.b"
ARXIV_ID = "2401.00001"

CROSSREF_A = {
    "status": "ok", "message-type": "work",
    "message": {
        "DOI": DOI_A, "URL": "https://doi.org/%s" % DOI_A,
        "title": ["Interaction terms improve tabular classification on synthetic benchmarks"],
        "author": [{"given": "Ada", "family": "Query"}],
        "issued": {"date-parts": [[2022]]},
        "container-title": ["Journal of Synthetic Machine Learning"],
        "type": "journal-article",
        "abstract": "<jats:p>On a synthetic two-class set whose label depends on a linear part and "
                     "one pairwise interaction between two features, a model that also sees the "
                     "interaction term reaches a higher held-out AUROC.</jats:p>",
    },
}

CROSSREF_B = {
    "status": "ok", "message-type": "work",
    "message": {
        "DOI": DOI_B, "URL": "https://doi.org/%s" % DOI_B,
        "title": ["A held-out evaluation protocol for small synthetic datasets"],
        "author": [{"given": "Bo", "family": "Split"}],
        "issued": {"date-parts": [[2020]]},
        "container-title": ["Proceedings of Toy Benchmarks"],
        "type": "proceedings-article",
        "abstract": "<jats:p>A fixed fraction of a synthetic set, drawn once and never used for "
                     "fitting, is enough to compare two models honestly.</jats:p>",
    },
}

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/%(id)s</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>A tiny code repository for reproducible toy experiments</title>
    <summary>The toy project's dataset generator and training script are released as a small
package, tagged once, so a reader can reproduce a run from the exact commit this paper names.</summary>
    <author><name>Cy Repo</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/%(id)s" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.LG"/>
  </entry>
</feed>
""" % {"id": ARXIV_ID}


def _hash_only_headers():
    """The one header `request_hash` takes into account: `Fetcher.fetch` always sets `Accept: */*`."""
    return {"Accept": "*/*"}


def write_cassette(url, status, body):
    request = Request(url, _hash_only_headers(), "GET")
    path = FETCH / request.host / (request.hash + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "request": {"method": "GET", "url": canonical_url(url), "hash": request.hash},
        "response": {"url": canonical_url(url), "status": status, "headers": {}, "encoding": "utf-8", "body": body},
    }
    path.write_text(__import__("json").dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(HARNESS_ROOT))
    return path


def build_cassettes():
    import json

    write_cassette(_with(CROSSREF_WORK % urllib.parse.quote(DOI_A, safe=""), mailto=EMAIL), 200,
                    json.dumps(CROSSREF_A))
    write_cassette(_with(CROSSREF_WORK % urllib.parse.quote(DOI_B, safe=""), mailto=EMAIL), 200,
                    json.dumps(CROSSREF_B))
    write_cassette(_with(ARXIV_QUERY, id_list=ARXIV_ID, max_results="1"), 200, ARXIV_FEED)


def main():
    build_pdf("paper-a", PAPER_A)
    build_pdf("paper-b", PAPER_B)
    build_tarball()
    build_cassettes()


if __name__ == "__main__":
    main()
