"""Record the real tool runs a document's conversion makes, for the tests to replay (ticket 84; seam 6).

`python3 fixtures/documents/record.py` converts every synthetic document of `fixtures/midway/` and of
this directory with the tools `~/.wayline/tools/tools.json` records on this machine (pandoc,
`pdftotext`, LibreOffice, docling), through `wayline.documents.recording_runner`, and keeps what
each tool printed and wrote under `recorded/<tool>/<input>/`. Nothing is written under a project:
`convert` returns what it read and the script prints one line per file. Rerun it after
`fixtures/midway/make.py` or `make.py` here changes a document; `record.py <name>...` records only
the files named, leaving the other recordings as they are.
"""

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from wayline.documents import convert, guess_kind, recording_runner  # noqa: E402
from wayline.tools import Tools  # noqa: E402

MIDWAY = HERE.parent / "midway"
FILES = [MIDWAY / "manuscript-v2.docx", MIDWAY / "manuscript-v1.docx", MIDWAY / "methods.tex", MIDWAY / "supplement.pdf",
         MIDWAY / "measurements.xlsx", HERE / "numbered-draft.pdf", HERE / "required-experiments.doc",
         HERE.parent / "pdf" / "tiny-paper.pdf", HERE / "line-breaks.tex"]


def main(names):
    target = HERE / "recorded"
    if not names:
        shutil.rmtree(target, ignore_errors=True)
    tools, run = Tools(), recording_runner(target)
    for path in [path for path in FILES if not names or path.name in names]:
        if path.suffix == ".pdf":
            guess_kind(path, tools=tools, run=run)
        done = convert(path, tools=tools, run=run)
        print("%s: %s, %s" % (path.name, "converted" if done.converted else "not converted",
                              ", ".join("%s %s" % (c["name"], c["version"]) for c in done.converters) or "no converter"))


if __name__ == "__main__":
    main(sys.argv[1:])
