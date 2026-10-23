"""The paper a compilation is tested on (ticket 118), shared by `tests/test_compilations.py` and the script that records the
real tool runs it replays, `fixtures/compilations/record.py`: both build the same project, so a recording is of exactly
the input a test hands the tools.

Synthetic and invented, like every fixture: a composed version 1 of `research/paper/` with every kind of tag, an equation,
a figure, and a table; four found works, one cited only in the Introduction's sentence citing several; and three
unresolved works the order answered for: `lost-work` (still failing at the last retry, its claim kept "to be resolved"),
`late-work` (found by the last retry), and `dropped-work` (dropped by the order's batch). `testconf` is a venue of a
temporary guidelines shelf, with a vendored class, a BibTeX template, a cap of four references, and a word limit the
paper exceeds.
"""

import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path

from tests import scout_net
from tests.test_references_rendered import dossier, failed
from wayline import dossier as dossiers
from wayline import paper
from wayline.ledger import Ledger
from wayline.scout import timestamp

NOW = scout_net.NOW
DAY = scout_net.DAY
LATE_DOI = "10.5555/late"
LOST_DOI = "10.5555/lost"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "compilations"
RECORDED = FIXTURES / "recorded"
TOOLS = ("pandoc", "pandoc-crossref", "latexmk", "pdfinfo")

TEXTS = {
    "title": "Noise bends a polynomial fit\n",
    "abstract": "We measure how noise bends a polynomial fit, and find that its error grows as the square of the noise "
                "{res:t2-a1/results/summary.json#rmse}.\n",
    "introduction": "## State of the art {#introduction-state-of-the-art}\n\n"
                    "Polynomial fits are standard {ref:smith-2020-fits#abstract} {ref:doi:10.5555/jones#abstract} "
                    "{ref:kim-2017-survey#abstract}. Noise is known to bias them {ref:arxiv:1801.00001#abstract}. "
                    "An earlier draft said so {doc:D1#p3}. A lost work claimed it first {ref:lost-work#abstract}, and a late "
                    "one agreed {ref:doi:10.5555/late#abstract}. A third said it again {ref:dropped-work#abstract}.\n",
    "results": "## How does noise change the fit? {#O1}\n\n### The error grows with the noise {#R1}\n\n"
               "The error of the fit follows\n\n$$ e(\\sigma) = 0.8\\,\\sigma^2 + 0.02 $$ {#eq:error}\n\n"
               "and @eq:error holds at every noise level we ran {res:t2-a1/results/summary.json#rmse}, as @fig:F1 shows "
               "{plot:R1.1}. @tbl:T1 lists the errors {res:t2-a1/results/summary.json#table}. The fit follows Smith's "
               "method {ref:smith-2020-fits#abstract}.\n",
    "discussion": "## Limits {#discussion-limits}\n\nThe noise model is Gaussian, as Lee assumed {ref:lee-2018-noise#abstract}. "
                  "A heavier tail would bend the fit further, and the next runs should try one.\n",
    "methods": "## Fitting {#methods-fitting}\n\nWe fit by least squares {code:code/fit.py#fit_poly}, as Jones did "
               "{ref:jones-2019-least#abstract}.\n",
    "supplement": "Nothing is placed in the supplement.\n",
    "front": "# Front matter\n\n## Authors\n\n- Ada Lovelace^1^ (corresponding author, ada@example.org)\n\n"
             "1. Analytical Engine Institute\n\n## Acknowledgments\n\n[TO BE GIVEN: acknowledgments]\n\n## Funding\n\n"
             "[TO BE GIVEN: funding]\n\n## Competing interests\n\nThe authors declare none.\n\n## Data availability\n\n"
             "The data are synthetic and the project's runs made them.\n\n## Code availability\n\n"
             "[TO BE GIVEN: the code repository, which setup has not settled]\n",
}

# The fitting session's answer at `testconf`: the Discussion's second sentence and the Introduction's last two moved to
# the supplement, every tag and number kept.
FITTED = {
    "abstract": None,
    "introduction": "## State of the art {#introduction-state-of-the-art}\n\n"
                    "Polynomial fits are standard {ref:smith-2020-fits#abstract} {ref:doi:10.5555/jones#abstract} "
                    "{ref:kim-2017-survey#abstract}. Noise is known to bias them {ref:arxiv:1801.00001#abstract}. "
                    "An earlier draft said so {doc:D1#p3}.\n",
    "results": None,
    "discussion": "## Limits {#discussion-limits}\n\nThe noise model is Gaussian, as Lee assumed {ref:lee-2018-noise#abstract}.\n",
    "methods": None,
    "supplement": "## Earlier claims {#supplement-earlier-claims}\n\nA lost work claimed it first {ref:lost-work#abstract}, "
                  "and a late one agreed {ref:doi:10.5555/late#abstract}. A third said it again {ref:dropped-work#abstract}. "
                  "A heavier tail would bend the fit further, and the next runs should try one.\n",
    "moved": ["the Introduction's earlier claims", "the Discussion's next runs"],
    "notes": "",
}

TESTCONF = {
    "schema_version": 1, "venue": "testconf", "display_name": "The Test Conference", "guidelines_url": "https://example.org/testconf",
    "date_checked": "2026-10-23",
    "length_limits": {"word_count": 120, "page_count": 9, "abstract_word_count": 150, "notes": "", "excluded_sections": ["References"]},
    "required_structure": ["Title", "Abstract", "Introduction", "Results", "Discussion", "Methods"], "structure_flexible": True,
    "figure_spec": {"max_count": 8, "formats": [], "min_dpi": None, "max_dpi": None, "color_mode": [], "max_file_size_mb": None,
                    "legend_max_words": None, "notes": ""},
    "reference_style": {"style": "natbib, author-year", "max_count": 4, "citation": "any", "csl": None, "bibtex": True},
    "reporting_checklists": [], "submission_steps": [],
    "template": {"latex_or_word_no_login": True, "url": "https://example.org/testconf/template", "notes": "", "document_class": "testconf"},
    "license_of_summary_source": {"statement": "Synthetic.", "url": "https://example.org"},
    "verification": {"fully_verified_fields": [], "unverified_fields": []},
}
TESTCONF_CLASS = "\\NeedsTeXFormat{LaTeX2e}\n\\ProvidesClass{testconf}[2026/10/23 The Test Conference]\n" \
                 "\\LoadClassWithOptions{article}\n\\RequirePackage{natbib}\n"


def png(width=8, height=6):
    """A small solid PNG, made with the standard library."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x33\x66\x99" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def guidelines_shelf(root):
    """A guidelines shelf holding `testconf` with its vendored class; returns `root`."""
    venue = Path(root) / "guidelines" / "testconf"
    venue.mkdir(parents=True, exist_ok=True)
    (venue / "guidelines.json").write_text(json.dumps(TESTCONF, indent=2) + "\n", encoding="utf-8")
    (venue / "testconf.cls").write_text(TESTCONF_CLASS, encoding="utf-8")
    return Path(root)


def make_paper(project):
    """Write the composed paper, its records, and the dossiers it cites into an initialized `project`."""
    book = Ledger(project)
    for record in (
        dossier("smith-2020-fits", title="Polynomial fits in practice", authors=("Ann Smith", "Bo Li"), year=2020,
                container="Journal of Fits", identifiers={"doi": "10.5555/smith"}),
        dossier("jones-2019-least", title="Least squares for curves", authors=("Cy Jones",), year=2019,
                container="Numerical Notes", identifiers={"doi": "10.5555/jones"}),
        dossier("lee-2018-noise", title="Noise and bias in fits", authors=("Di Lee", "Ed Hall"), year=2018, container="arXiv",
                identifiers={"arxiv_id": "1801.00001"}),
        dossier("kim-2017-survey", title="A survey of fitting", authors=("Fay Kim",), year=2017, container="Fitting Reviews",
                identifiers={"doi": "10.5555/kim"}),
        dossier("lost-work", existence="unresolved", query={"kind": "doi", "value": LOST_DOI}, attempts=failed(),
                retry={"service": "crossref", "failure": "HTTP 503", "date": timestamp(NOW - 2 * DAY), "since": timestamp(NOW - 3 * DAY)}),
        dossier("late-work", existence="unresolved", query={"kind": "doi", "value": LATE_DOI}, attempts=failed(),
                retry={"service": "crossref", "failure": "HTTP 503", "date": timestamp(NOW - 3600), "since": timestamp(NOW - DAY)}),
        dossier("dropped-work", existence="unresolved", query={"kind": "title", "value": "A paper nobody wrote"}),
    ):
        dossiers.write_l0(book, record)
    for part, text in TEXTS.items():
        book.write_markdown("paper/%s.md" % part, text)
    book.write_markdown("paper/tables/T1.csv", "noise,rmse\n0.1,0.03\n0.2,0.05\n0.4,0.15\n")
    book.write_markdown("paper/tables/T1.md", paper._table_markdown({"id": "T1", "caption": "The error of the fit at each noise level.",
                                                                     "csv": "noise,rmse\n0.1,0.03\n0.2,0.05\n0.4,0.15\n"}))
    book.write_bytes("paper/figures/F1/figure.png", png())
    book.write_markdown("paper/figures/F1/caption.md", "The error of the fit grows with the noise.\n")
    book.write_json("front.json", {"authors": [{"name": "Ada Lovelace", "affiliations": ["Analytical Engine Institute"],
                                                "corresponding": True, "email": "ada@example.org"}]})
    answers = [{"ref": "reference:%s" % name, "text": "Unresolved reference %s" % name, "mark": mark, "by": "owner", "batch": "B1",
                "item": number, "note": None}
               for number, (name, mark) in enumerate((("lost-work", paper.TO_BE_RESOLVED), ("late-work", paper.TO_BE_RESOLVED),
                                                      ("dropped-work", paper.DROP)), start=1)]
    book.write_json("paper/paper.json", {
        "version": 1, "order": 1, "by": "owner", "commit": None, "composed": "2026-10-23T09:00:00.000Z", "model": None,
        "parts": {part: {"version": 1, "inputs": "0" * 64, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
                  for part, text in TEXTS.items()},
        "tables": ["T1"], "alternatives": [], "answers": answers, "unchecked": None, "left_out": [], "proposals": [],
        "reworded": [], "kept_edits": [], "gated": False, "usage": None,
    }, schema="paper")
    book.append_event("paper_order", {"order": 1, "action": "ordered", "by": "owner", "run": "stopped", "batch": None, "venue": "nature"})
    book.append_event("paper_order", {"order": 1, "action": "composed", "by": "owner", "version": 1, "commit": None,
                                      "parts": list(paper.PARTS)})
    return book


def fetcher():
    """The network at the last retry, and the network: Crossref finds the late work, every service fails on the lost one,
    and nothing matches the dropped one's title."""
    def quoted(doi):
        return doi.replace("/", "%2F")
    answers = {"api.crossref.org/works/" + quoted(LATE_DOI): scout_net.crossref_work(doi=LATE_DOI, title="A late agreement",
                                                                                    family="Late", year=2024),
               quoted(LOST_DOI): scout_net.DOWN,
               "query.bibliographic": (200, json.dumps({"status": "ok", "message": {"items": []}})),
               "api.openalex.org/works?search": (200, json.dumps({"results": []})),
               "api.openalex.org": scout_net.NOT_FOUND, "api.unpaywall.org": scout_net.NOT_FOUND,
               "www.ebi.ac.uk": scout_net.EMPTY_EUROPEPMC}
    return scout_net.net_fetcher(answers)


def fitted_answer():
    return dict(FITTED)


def tools_record(root, executables):
    """A `tools.json` under `root` recording the compilation's tools at `executables` (`{name: path}`)."""
    from wayline.tools import Tools
    record = {"schema_version": 2, "tools": {name: {"executable": str(path), "version": version, "env": {}, "installer": "harness"}
                                             for name, (path, version) in executables.items()}}
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return Tools(root)


def fake_tools(root):
    """Stand-in executables named as the real ones, recorded in a `tools.json` of their own: what a replay runs."""
    root = Path(root)
    (root / "bin").mkdir(parents=True, exist_ok=True)
    versions = {"pandoc": "3.11", "pandoc-crossref": "0.3.25", "latexmk": "4.83", "pdfinfo": "24.02.0"}
    for name in TOOLS:
        (root / "bin" / name).write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    return tools_record(root, {name: (root / "bin" / name, versions[name]) for name in TOOLS})


def clean(path):
    shutil.rmtree(path, ignore_errors=True)
