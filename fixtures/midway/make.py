"""Rebuild the binary files of the synthetic start-midway project from the text held here.

`python3 fixtures/midway/make.py` writes `manuscript-v1.docx`, `manuscript-v2.docx`,
`measurements.xlsx`, and `supplement.pdf` byte for byte the same on every run (fixed zip
timestamps), so a rebuild that changes nothing shows as no diff. Everything is invented: the
lantern moths, the authors, the references, and every sentence.
"""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
      'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')

TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
<Override PartName="/word/commentsExtended.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
<Relationship Id="rId2" Type="http://schemas.microsoft.com/office/2011/relationships/commentsExtended" Target="commentsExtended.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLE_NAMES = {"Normal": "Normal", "Title": "Title", "Abstract": "Abstract",
               "Heading1": "heading 1", "Caption": "caption", "Bibliography": "Bibliography"}
STYLES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles {NS}>' + "".join(
    f'<w:style w:type="paragraph" w:styleId="{i}"><w:name w:val="{n}"/>'
    + ('<w:pPr><w:outlineLvl w:val="0"/></w:pPr>' if i == "Heading1" else "") + "</w:style>"
    for i, n in STYLE_NAMES.items()) + "</w:styles>")

AUTHOR = 'w:author="Ines Varga" w:date="2023-04-02T10:00:00Z"'


def r(text):
    return f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def p(style, *runs):
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{"".join(runs)}</w:p>'


def ins(i, text):
    return f'<w:ins w:id="{i}" {AUTHOR}>{r(text)}</w:ins>'


def dele(i, text):
    return (f'<w:del w:id="{i}" {AUTHOR}><w:r><w:delText xml:space="preserve">'
            f'{escape(text)}</w:delText></w:r></w:del>')


def cite(key, shown):
    """A Mendeley Cite citation: a complex field whose instruction carries the CSL JSON."""
    instr = (f' ADDIN MENDELEY_CITATION_V3 {{"citationID":"MENDELEY_CITATION_{key}",'
             f'"citationItems":[{{"id":"{key}","itemData":{{"type":"article-journal",'
             f'"id":"{key}","title":"Invented reference {key}"}}}}]}} ')
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{escape(instr)}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'{r(shown)}<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def commented(cid, text):
    return (f'<w:commentRangeStart w:id="{cid}"/>{r(text)}<w:commentRangeEnd w:id="{cid}"/>'
            f'<w:r><w:commentReference w:id="{cid}"/></w:r>')


EQUATION = ('<w:p><m:oMathPara><m:oMath><m:r><m:t>R=|</m:t></m:r><m:f><m:num><m:r><m:t>1'
            '</m:t></m:r></m:num><m:den><m:r><m:t>N</m:t></m:r></m:den></m:f><m:r><m:t>'
            '&#8721;exp(i&#966;)|</m:t></m:r></m:oMath></m:oMathPara></w:p>')


def body(newer):
    intro_edit = ([dele(1, "nightly "), ins(2, "dusk ")] if newer else [r("nightly ")])
    paras = [
        p("Title", r("Wingbeat synchrony in captive lantern moth colonies")),
        p("Abstract", r("We measure how closely lantern moths beat their wings in phase. "
                        "Across forty colonies, synchrony rises with colony size, and it "
                        "peaks at dusk.")),
        p("Heading1", r("Introduction")),
        p("Normal", r("Lantern moths gather in "), *intro_edit,
          r("swarms whose wingbeats lock together "), cite("Okafor2017", "(Okafor 2017)"),
          r(". "), commented(0, "Why they synchronize is unknown."),
          r(" Phase locking has been measured in other insects "),
          cite("Lindqvist2019", "(Lindqvist and Moreau 2019)"), r(".")),
        p("Heading1", r("Results")),
        p("Normal", r("Larger colonies beat more nearly in phase than small ones (Figure 1). "),
          commented(1, "The order parameter is lowest at dusk across every colony.")),
        p("Normal", r("The dusk sweep of 2021 repeated the size series under red light; its "
                      "recordings are kept in data/dusk-sweep-2021.csv and gave R = 0.71.")),
        EQUATION,
        p("Caption", r("Figure 1. Order parameter R against colony size, forty colonies.")),
        p("Heading1", r("Discussion")),
        p("Normal", r("Our central finding is that synchrony rises with colony size. "),
          *([ins(3, "Dusk light may be the cue. ")] if newer else [])),
        p("Heading1", r("Methods")),
        p("Normal", r("Wingbeats were filmed at 2000 frames per second; the phase of each "
                      "moth was taken from the analytic signal, as described in methods.tex.")),
        p("Heading1", r("Acknowledgements")),
        p("Normal", commented(2, "We thank the moth keepers of the invented Varga lab.")),
        p("Heading1", r("References")),
        p("Bibliography", r("Lindqvist, A. and Moreau, P. (2019). Invented phase locking in "
                            "crickets. Journal of Made-up Rhythms 4, 1-9.")),
        p("Bibliography", r("Okafor, N. (2017). Invented lantern moth swarms. Imaginary "
                            "Entomology 12, 33-40.")),
    ]
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {NS}>'
            f'<w:body>{"".join(paras)}</w:body></w:document>')


def comment(cid, para, text):
    return (f'<w:comment w:id="{cid}" {AUTHOR} w:initials="IV"><w:p w14:paraId="{para}">'
            f'{r(text)}</w:p></w:comment>')


COMMENTS = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:comments {NS}>'
            + comment(0, "0000000A", "Cite the 2015 review here?")
            + comment(3, "0000000B", "Reply: no such review exists; leave it.")
            + comment(1, "0000000C", "This contradicts the abstract. Which is right?")
            + comment(2, "0000000D", "Add the funder.")
            + "</w:comments>")

EXTENDED = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w15:commentsEx {NS}>'
            '<w15:commentEx w15:paraId="0000000A" w15:done="1"/>'
            '<w15:commentEx w15:paraId="0000000B" w15:paraIdParent="0000000A" w15:done="1"/>'
            '<w15:commentEx w15:paraId="0000000C" w15:done="0"/>'
            '<w15:commentEx w15:paraId="0000000D" w15:done="0"/>'
            '</w15:commentsEx>')


def write_zip(path, parts, when):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=when)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)


def docx(path, newer, when):
    write_zip(path, [("[Content_Types].xml", TYPES), ("_rels/.rels", ROOT_RELS),
                     ("word/_rels/document.xml.rels", DOC_RELS),
                     ("word/document.xml", body(newer)), ("word/styles.xml", STYLES), ("word/comments.xml", COMMENTS),
                     ("word/commentsExtended.xml", EXTENDED)], when)


def sheet(rows):
    out = []
    for i, row in enumerate(rows, 1):
        cells = "".join(
            f'<c t="inlineStr"><is><t>{escape(v)}</t></is></c>' if isinstance(v, str)
            else f"<c><v>{v}</v></c>" for v in row)
        out.append(f'<row r="{i}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns='
            '"http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(out) + "</sheetData></worksheet>")


def xlsx(path):
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://'
          'schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" '
          'ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default '
          'Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml"'
          ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.'
          'main+xml"/>' + "".join(
              f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.'
              'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in (1, 2))
          + "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships"><Relationship '
            f'Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    book = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{main}"'
            f' xmlns:r="{rel}"><sheets><sheet name="Colonies" sheetId="1" r:id="rId1"/>'
            '<sheet name="Lighting" sheetId="2" r:id="rId2"/></sheets></workbook>')
    book_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
                 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" '
                           f'Target="worksheets/sheet{i}.xml"/>' for i in (1, 2))
                 + "</Relationships>")
    colonies = sheet([["colony", "size", "R"], ["C01", 12, 0.41], ["C02", 30, 0.58],
                      ["C03", 55, 0.69], ["C04", 80, 0.77]])
    lighting = sheet([["condition", "hour", "R"], ["white", 18, 0.52], ["red", 18, 0.71],
                      ["white", 22, 0.63]])
    write_zip(path, [("[Content_Types].xml", ct), ("_rels/.rels", rels),
                     ("xl/workbook.xml", book), ("xl/_rels/workbook.xml.rels", book_rels),
                     ("xl/worksheets/sheet1.xml", colonies),
                     ("xl/worksheets/sheet2.xml", lighting)], (2023, 3, 1, 0, 0, 0))


def pdf(path):
    """A one-page PDF written by hand, with a correct cross-reference table."""
    text = ("BT /F1 12 Tf 72 720 Td (Supplementary Table S1. Colony sizes and dusk order "
            "parameters, invented.) Tj ET")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def main():
    docx(HERE / "manuscript-v1.docx", False, (2022, 11, 20, 9, 0, 0))
    docx(HERE / "manuscript-v2.docx", True, (2023, 4, 2, 10, 0, 0))
    xlsx(HERE / "measurements.xlsx")
    pdf(HERE / "supplement.pdf")


if __name__ == "__main__":
    main()
