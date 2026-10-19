# Documents in: two more synthetic documents and the recorded tool runs (ticket 84)

Beside the synthetic start-midway project of `fixtures/midway/`, invented like it (nothing of any real
project):

| File | What it is | What it exercises |
|---|---|---|
| `numbered-draft.pdf` | a one-page draft whose every line carries a margin number | stripping the margin line numbers off `pdftotext -layout` |
| `required-experiments.doc` | a collaborator's list of required experiments, as a legacy Word file | LibreOffice turning a `.doc` into a `.docx` before pandoc |
| `line-breaks.tex` | a LaTeX section whose lines break with `\\[2pt]`, beside one display equation `\[...\]` | counting a `.tex`'s equations without taking a line break for one |
| `make.py` | rebuilds both (the `.doc` through `soffice` on the PATH) | |
| `record.py` | converts every synthetic document with the tools `~/.wayline/tools/tools.json` records, keeping each run under `recorded/` | |
| `recorded/<tool>/<input>/` | what pandoc, `pdftotext`, LibreOffice (`soffice`), and docling printed (`stdout`, `stderr`, `returncode`) and wrote (`files/`) for one input | the tests' replay, `wayline.documents.recorded_runner` |

The recordings were made on the owner's workstation: pandoc 3.11, poppler 24.02.0, LibreOffice 24.2.7.2,
and docling 2.126.0. The scratch directory a conversion ran in is kept as `{work}` and the home directory
as `~`. After `make.py` or `fixtures/midway/make.py` changes a document, rerun
`python3 fixtures/documents/record.py`.
