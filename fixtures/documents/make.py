"""Build the two documents ticket 84 adds beside the synthetic start-midway project of `fixtures/midway/`.

`python3 fixtures/documents/make.py` writes:

- `numbered-draft.pdf`, a one-page draft with margin line numbers, written by hand byte for byte the
  same on every run, for stripping the numbers off `pdftotext -layout`'s text;
- `required-experiments.doc`, a collaborator's list of required experiments as a legacy Word file:
  a `.docx` written here, turned into a `.doc` by LibreOffice (`soffice` on the PATH), since only
  LibreOffice writes one. LibreOffice stamps the file, so a rebuild changes its bytes.

Everything is invented, like the rest of the midway project. After a rebuild, rerun
`python3 fixtures/documents/record.py` so the recorded tool runs match.
"""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

DRAFT = [
    "Wingbeat synchrony: a draft for the lab meeting",
    "Introduction",
    "Lantern moths gather in dusk swarms whose wingbeats lock together.",
    "We ask whether the lock depends on colony size.",
    "Results",
    "Larger colonies beat more nearly in phase than small ones.",
    "The order parameter rose from 0.41 to 0.77 across four colonies.",
]

EXPERIMENTS = [
    "Required experiments, from Tomas Brandt",
    "1. Film each colony under red light as well as white light.",
    "2. Repeat the size series with a second camera at 4000 frames per second.",
    "3. Report the number of moths filmed per colony.",
]


def numbered_pdf(path):
    """A page whose every line carries a margin number at the left edge, the way a submitted manuscript does."""
    lines, y = [], 720
    for number, text in enumerate(DRAFT, 1):
        lines.append("BT /F1 10 Tf 40 %d Td (%d) Tj ET" % (y, number))
        lines.append("BT /F1 12 Tf 90 %d Td (%s) Tj ET" % (y, text.replace("(", "\\(").replace(")", "\\)")))
        y -= 36 if number in (1, 4) else 18
    stream = "\n".join(lines)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            "<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, o)).encode()
    xref = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    out += b"".join(("%010d 00000 n \n" % o).encode() for o in offsets)
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)).encode()
    path.write_bytes(out)


def experiments_docx(path):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(line) for line in EXPERIMENTS)
    parts = [
        ("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.'
         'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxml'
         'formats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName='
         '"/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'),
        ("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.'
         'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
         'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'),
        ("word/document.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document %s><w:body>%s</w:body>'
         '</w:document>' % (ns, body)),
    ]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=(2023, 5, 1, 9, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data)


def legacy_doc(path):
    soffice = shutil.which("soffice")
    if soffice is None:
        print("make.py: soffice is not on the PATH, so %s was not rebuilt" % path.name, file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as scratch:
        docx = Path(scratch) / (path.stem + ".docx")
        experiments_docx(docx)
        subprocess.run([soffice, "--headless", "--norestore", "-env:UserInstallation=file://%s/profile" % scratch,
                        "--convert-to", "doc", "--outdir", scratch, str(docx)], check=True, capture_output=True)
        shutil.copyfile(Path(scratch) / path.name, path)


def main():
    numbered_pdf(HERE / "numbered-draft.pdf")
    legacy_doc(HERE / "required-experiments.doc")


if __name__ == "__main__":
    main()
