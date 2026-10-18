"""The standard-library reader of Office files: what pandoc does not read in a `.docx`, and an `.xlsx` (Implementation Decision 17).

Pandoc converts a `.docx` (headings, equations as LaTeX, tracked changes accepted), but it reads no
Mendeley Cite citation and keeps no comment thread, so this reader opens the same file with `zipfile`
and `xml.etree.ElementTree` and returns what pandoc leaves out:

- every Mendeley Cite citation, decoded into the CSL-JSON of the works it cites. Mendeley Cite
  stores a citation either as a content control whose `w:tag` is `MENDELEY_CITATION_v3_` and a
  base64 JSON, or as a field whose instruction is `ADDIN MENDELEY_CITATION_V3 {json}`; both carry
  `citationItems[].itemData` in CSL-JSON;
- every comment thread, from `comments.xml` and `commentsExtended.xml` (a reply names its parent
  with `paraIdParent`, and `done` marks a resolved thread), each with the text it is anchored on;
- the counts a converter's output is checked against: paragraphs, headings, equations, tables,
  images, tracked insertions, deletions, and formatting changes;
- the text of every table, so a document's tables are kept as CSV.

It reads the accepted text, as pandoc's `--track-changes=accept` does: a deletion's text is left out
and an insertion's kept. An `.xlsx` is read sheet by sheet into rows of cell values (a formula's
cached value), one CSV per sheet. Nothing here imports a third-party package.
"""

import base64
import binascii
import json
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

__all__ = ["OfficeError", "DocxReading", "read_docx", "docx_text", "read_xlsx", "MENDELEY"]

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

MENDELEY = "MENDELEY_CITATION"
_MENDELEY_TAG = re.compile(r"^MENDELEY_CITATION_v3_(.+)$", re.IGNORECASE)
_HEADING_NAME = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
_CELL = re.compile(r"^([A-Z]+)(\d+)$")
# The largest part of a package this reader decompresses: a `.docx` body is a few megabytes at most.
PART_MAX_BYTES = 64 * 1024 * 1024


class OfficeError(ValueError):
    """A file that is not the Office package it is named as: not a zip, or missing its main part."""


def _w(name):
    return "{%s}%s" % (W, name)


def _attr(element, name, namespace=W):
    return element.get("{%s}%s" % (namespace, name))


def _part(package, name):
    try:
        info = package.getinfo(name)
    except KeyError:
        return None
    if info.file_size > PART_MAX_BYTES:
        raise OfficeError("%s is %d bytes, over the %d this reader opens" % (name, info.file_size, PART_MAX_BYTES))
    return package.read(name)


def _xml(package, name):
    data = _part(package, name)
    if data is None:
        return None
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as failure:
        raise OfficeError("%s is not well-formed XML: %s" % (name, failure)) from None


def _open(path):
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as failure:
        raise OfficeError("%s is not an Office package (a zip): %s" % (path, failure)) from None


# --- .docx ----------------------------------------------------------------------------------------


@dataclass
class DocxReading:
    """What the reader found in one `.docx`; see the module's docstring for each part."""

    paragraphs: list = field(default_factory=list)   # {"style", "level", "text"} in body order; level is a heading's, else None
    title: str = None
    abstract: str = None
    counts: dict = field(default_factory=dict)
    threads: list = field(default_factory=list)      # {"id", "anchor", "paragraph", "done", "comments": [{"id", "author", "date", "text"}]}
    citations: list = field(default_factory=list)    # {"shown", "ids", "paragraph"}: one per citation in the text
    works: list = field(default_factory=list)        # the CSL-JSON items cited, each once, in first-cited order
    tables: list = field(default_factory=list)       # each table as rows of cell texts

    @property
    def text(self):
        return "\n\n".join(paragraph["text"] for paragraph in self.paragraphs if paragraph["text"])


def _styles(package):
    """`styleId -> (name, outline level or None)` from `styles.xml`."""
    root = _xml(package, "word/styles.xml")
    styles = {}
    if root is None:
        return styles
    for style in root.iter(_w("style")):
        style_id = _attr(style, "styleId")
        name_element = style.find(_w("name"))
        name = _attr(name_element, "val") if name_element is not None else style_id
        outline = style.find("%s/%s" % (_w("pPr"), _w("outlineLvl")))
        level = int(_attr(outline, "val")) + 1 if outline is not None and (_attr(outline, "val") or "").isdigit() else None
        styles[style_id] = (name or style_id or "", level)
    return styles


def _heading_level(style_id, paragraph_outline, styles):
    name, level = styles.get(style_id, (style_id or "", None))
    for candidate in (name, style_id or ""):
        match = _HEADING_NAME.match(candidate.replace("Heading", "heading "))
        if match:
            return int(match.group(1))
    if paragraph_outline is not None:
        return paragraph_outline
    if level is not None and level <= 9:
        return level
    return None


class _Walk:
    """One pass over `document.xml` in body order, gathering the accepted text and what sits in it."""

    def __init__(self, styles):
        self.styles = styles
        self.paragraphs = []
        self.counts = {"paragraphs": 0, "headings": 0, "equations": 0, "tables": 0, "images": 0,
                       "insertions": 0, "deletions": 0, "formatting_changes": 0}
        self.anchors = {}        # comment id -> anchor text
        self.anchor_paragraph = {}
        self.open_ranges = []
        self.citations = []
        self.works = {}
        self.order = []
        self.fields = []         # a stack of open fields: {"instr": [...], "shown": [...], "separated": bool}
        self.tables = []
        self.buffer = None
        self.captures = []       # the text of each open Mendeley Cite content control

    # text goes to the current paragraph, every open comment range, and every open field's result
    def emit(self, text):
        if not text:
            return
        if self.buffer is not None:
            self.buffer.append(text)
        for cid in self.open_ranges:
            self.anchors[cid] = self.anchors.get(cid, "") + text
        for open_field in self.fields:
            if open_field["separated"]:
                open_field["shown"].append(text)
        for capture in self.captures:
            capture.append(text)

    def body(self, root):
        body = root.find(_w("body"))
        for child in list(body) if body is not None else []:
            self.block(child)

    def block(self, element):
        tag = element.tag
        if tag == _w("p"):
            self.paragraph(element)
        elif tag == _w("tbl"):
            self.table(element)
        elif tag == _w("sdt"):
            self.content_control(element, block=True)
        elif tag in (_w("ins"), _w("customXml")):
            for child in element:
                self.block(child)

    def table(self, element):
        self.counts["tables"] += 1
        rows = []
        for row in element.iter(_w("tr")):
            cells = []
            for cell in row.findall(_w("tc")):
                texts = []
                for paragraph in cell.findall(".//" + _w("p")):
                    texts.append(self.paragraph(paragraph))
                cells.append(" ".join(text for text in texts if text))
            rows.append(cells)
        self.tables.append(rows)

    def paragraph(self, element):
        properties = element.find(_w("pPr"))
        style_id, outline = None, None
        if properties is not None:
            style = properties.find(_w("pStyle"))
            style_id = _attr(style, "val") if style is not None else None
            level = properties.find(_w("outlineLvl"))
            if level is not None and (_attr(level, "val") or "").isdigit():
                outline = int(_attr(level, "val")) + 1
            if properties.find(_w("pPrChange")) is not None:
                self.counts["formatting_changes"] += 1
        saved, self.buffer = self.buffer, []
        index = len(self.paragraphs)
        for child in element:
            if child.tag == _w("pPr"):
                continue
            self.inline(child, index)
        text = " ".join("".join(self.buffer).split())
        self.buffer = saved
        name = self.styles.get(style_id, (style_id or "", None))[0]
        level = _heading_level(style_id, outline, self.styles) if name.lower() not in ("title", "subtitle") else None
        self.paragraphs.append({"style": name or style_id or "Normal", "level": level, "text": text})
        self.counts["paragraphs"] += 1
        if level is not None and text:
            self.counts["headings"] += 1
        if self.buffer is not None:
            self.buffer.append(text)
        return text

    def inline(self, element, index):
        tag = element.tag
        if tag == _w("r"):
            self.run(element)
        elif tag == _w("del"):
            self.counts["deletions"] += 1  # the accepted text leaves a deletion's text out
        elif tag == _w("ins"):
            self.counts["insertions"] += 1
            for child in element:
                self.inline(child, index)
        elif tag == _w("commentRangeStart"):
            cid = _attr(element, "id")
            self.open_ranges.append(cid)
            self.anchors.setdefault(cid, "")
            self.anchor_paragraph.setdefault(cid, index)
        elif tag == _w("commentRangeEnd"):
            cid = _attr(element, "id")
            if cid in self.open_ranges:
                self.open_ranges.remove(cid)
        elif tag == _w("sdt"):
            self.content_control(element, index=index)
        elif tag == "{%s}oMathPara" % M or tag == "{%s}oMath" % M:
            self.math(element)
        elif tag == _w("fldSimple"):
            for child in element:
                self.inline(child, index)
        elif tag in (_w("hyperlink"), _w("smartTag"), _w("customXml"), _w("bdo"), _w("dir")):
            for child in element:
                self.inline(child, index)

    def math(self, element):
        equations = [element] if element.tag == "{%s}oMath" % M else list(element.iter("{%s}oMath" % M))
        self.counts["equations"] += len(equations)
        self.emit("".join(text.text or "" for text in element.iter("{%s}t" % M)))

    def run(self, element):
        if element.find(_w("rPr")) is not None and element.find("%s/%s" % (_w("rPr"), _w("rPrChange"))) is not None:
            self.counts["formatting_changes"] += 1
        for child in element:
            tag = child.tag
            if tag == _w("t"):
                self.emit(child.text or "")
            elif tag == _w("tab"):
                self.emit(" ")
            elif tag in (_w("br"), _w("cr")):
                self.emit(" ")
            elif tag == _w("drawing") or tag == _w("pict"):
                self.counts["images"] += 1
            elif tag == _w("fldChar"):
                self.field_char(_attr(child, "fldCharType"))
            elif tag == _w("instrText") and self.fields and not self.fields[-1]["separated"]:
                self.fields[-1]["instr"].append(child.text or "")
            elif tag == "{%s}oMath" % M:
                self.math(child)

    def field_char(self, kind):
        if kind == "begin":
            self.fields.append({"instr": [], "shown": [], "separated": False})
        elif kind == "separate" and self.fields:
            self.fields[-1]["separated"] = True
        elif kind == "end" and self.fields:
            done = self.fields.pop()
            instruction = "".join(done["instr"])
            if MENDELEY in instruction.upper() and "BIBLIOGRAPHY" not in instruction.upper():
                start = instruction.find("{")
                self.citation(_json(instruction[start:]) if start >= 0 else None, "".join(done["shown"]))

    def content_control(self, element, block=False, index=None):
        tag = element.find("%s/%s" % (_w("sdtPr"), _w("tag")))
        match = _MENDELEY_TAG.match(_attr(tag, "val") or "") if tag is not None else None
        content = element.find(_w("sdtContent"))
        children = list(content) if content is not None else []
        if match is not None:
            self.captures.append([])
        for child in children:
            self.block(child) if block else self.inline(child, index)
        if match is None:
            return
        shown = "".join(self.captures.pop())
        try:
            decoded = base64.b64decode(match.group(1) + "=" * (-len(match.group(1)) % 4)).decode("utf-8")
        except (binascii.Error, ValueError):
            decoded = None
        self.citation(_json(decoded) if decoded else None, shown)

    def citation(self, value, shown):
        ids = []
        for item in (value or {}).get("citationItems") or []:
            data = item.get("itemData") if isinstance(item, dict) else None
            if not isinstance(data, dict):
                continue
            work_id = str(data.get("id") or item.get("id") or "")
            if not work_id:
                continue
            ids.append(work_id)
            if work_id not in self.works:
                self.works[work_id] = dict(data, id=work_id)
                self.order.append(work_id)
        self.citations.append({"shown": " ".join(shown.split()), "ids": ids, "paragraph": len(self.paragraphs)})


def _json(text):
    if not text:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text.strip())
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _threads(package, anchors, anchor_paragraph):
    """The comment threads: each root comment with its replies, its anchor, and whether it is done."""
    root = _xml(package, "word/comments.xml")
    if root is None:
        return []
    comments, by_para = [], {}
    for comment in root.iter(_w("comment")):
        cid = _attr(comment, "id")
        paragraphs = comment.findall(_w("p"))
        para = _attr(paragraphs[-1], "paraId", W14) if paragraphs else None
        text = "\n".join(" ".join("".join(t.text or "" for t in p.iter(_w("t"))).split()) for p in paragraphs).strip()
        entry = {"id": cid, "author": _attr(comment, "author"), "date": _attr(comment, "date"), "text": text}
        comments.append((entry, para))
        if para:
            by_para[para] = cid
    extended = _xml(package, "word/commentsExtended.xml")
    parent, done = {}, {}
    if extended is not None:
        for ex in extended.iter("{%s}commentEx" % W15):
            para = _attr(ex, "paraId", W15)
            cid = by_para.get(para)
            if cid is None:
                continue
            done[cid] = _attr(ex, "done", W15) == "1"
            if _attr(ex, "paraIdParent", W15) in by_para:
                parent[cid] = by_para[_attr(ex, "paraIdParent", W15)]

    def root_of(cid):
        seen = set()
        while cid in parent and cid not in seen:
            seen.add(cid)
            cid = parent[cid]
        return cid

    threads, index = [], {}
    for entry, _para in comments:
        top = root_of(entry["id"])
        if top not in index:
            index[top] = {"id": top, "anchor": None, "paragraph": None, "done": False, "comments": []}
            threads.append(index[top])
        index[top]["comments"].append(entry)
    for thread in threads:
        anchor = anchors.get(thread["id"])
        thread["anchor"] = " ".join(anchor.split()) if anchor is not None else None
        thread["paragraph"] = anchor_paragraph.get(thread["id"])
        thread["done"] = bool(done.get(thread["id"], False))
        # the root comment first, then the replies in the order Word wrote them
        thread["comments"].sort(key=lambda entry: entry["id"] != thread["id"])
    return threads


def read_docx(path):
    """Read a `.docx` with the standard library; returns a `DocxReading`. Raises `OfficeError` for a file that is not one."""
    with _open(path) as package:
        root = _xml(package, "word/document.xml")
        if root is None:
            raise OfficeError("%s has no word/document.xml, so it is not a .docx" % path)
        walk = _Walk(_styles(package))
        walk.body(root)
        threads = _threads(package, walk.anchors, walk.anchor_paragraph)
    reading = DocxReading(paragraphs=walk.paragraphs, counts=walk.counts, threads=threads, citations=walk.citations,
                          works=[walk.works[work_id] for work_id in walk.order], tables=walk.tables)
    for paragraph in walk.paragraphs:
        style = paragraph["style"].lower()
        if style == "title" and reading.title is None and paragraph["text"]:
            reading.title = paragraph["text"]
        elif style == "abstract" and paragraph["text"]:
            reading.abstract = (reading.abstract + "\n\n" if reading.abstract else "") + paragraph["text"]
    reading.counts.update(comments=sum(len(thread["comments"]) for thread in threads), threads=len(threads),
                          citations=len(walk.citations), works=len(reading.works))
    return reading


def docx_text(path):
    """The accepted text of a `.docx`, paragraph by paragraph, for code's guess at its kind; empty when it cannot be read."""
    try:
        return read_docx(path).text
    except OfficeError:
        return ""


# --- .xlsx ----------------------------------------------------------------------------------------


def _column(letters):
    number = 0
    for letter in letters:
        number = number * 26 + (ord(letter) - ord("A") + 1)
    return number - 1


def _shared_strings(package):
    root = _xml(package, "xl/sharedStrings.xml")
    if root is None:
        return []
    return ["".join(t.text or "" for t in item.iter("{%s}t" % SHEET)) for item in root.iter("{%s}si" % SHEET)]


def _sheet_paths(package):
    """`(name, part)` for every sheet in the workbook's order."""
    book = _xml(package, "xl/workbook.xml")
    if book is None:
        raise OfficeError("the workbook has no xl/workbook.xml, so it is not an .xlsx")
    rels = _xml(package, "xl/_rels/workbook.xml.rels")
    targets = {}
    if rels is not None:
        for rel in rels.iter("{%s}Relationship" % PKG_REL):
            target = rel.get("Target") or ""
            targets[rel.get("Id")] = target.lstrip("/") if target.startswith("/") else "xl/" + target
    sheets = []
    for position, sheet in enumerate(book.iter("{%s}sheet" % SHEET), 1):
        rid = sheet.get("{%s}id" % REL)
        sheets.append((sheet.get("name") or "Sheet%d" % position, targets.get(rid, "xl/worksheets/sheet%d.xml" % position)))
    return sheets


def _cell_value(cell, strings):
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter("{%s}t" % SHEET))
    value = cell.find("{%s}v" % SHEET)
    text = value.text if value is not None and value.text is not None else ""
    if kind == "s" and text.isdigit():
        index = int(text)
        return strings[index] if index < len(strings) else ""
    if kind == "b":
        return "TRUE" if text == "1" else "FALSE"
    return text


def read_xlsx(path):
    """Every sheet of an `.xlsx` as `(name, rows)`, each row a list of cell texts with the gaps filled; a formula gives its cached value."""
    sheets = []
    with _open(path) as package:
        strings = _shared_strings(package)
        for name, part in _sheet_paths(package):
            root = _xml(package, part)
            rows = []
            for row in (root.iter("{%s}row" % SHEET) if root is not None else []):
                values, next_column = [], 0
                for cell in row.findall("{%s}c" % SHEET):
                    match = _CELL.match(cell.get("r") or "")
                    column = _column(match.group(1)) if match else next_column
                    values.extend([""] * max(0, column - len(values)))
                    values.append(_cell_value(cell, strings))
                    next_column = column + 1
                number = int(row.get("r")) if (row.get("r") or "").isdigit() else len(rows) + 1
                rows.extend([[]] * max(0, number - 1 - len(rows)))
                rows.append(values)
            width = max((len(row) for row in rows), default=0)
            sheets.append((name, [row + [""] * (width - len(row)) for row in rows]))
    return sheets
