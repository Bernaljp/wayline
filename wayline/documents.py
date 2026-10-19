"""Documents in: a project's own writing, converted, sorted, recorded, and indexed (Implementation Decision 17).

A **document** is one of the project's own writings handed to the harness: an earlier manuscript, a
separate Methods, a referee report, a collaborator's list of required experiments. Published work,
the project's own preprints included, is a reference, and goes to the scout instead.

Conversion is code at every autonomy, each tool run by its record in `tools.json` (seam 6):

- a `.docx` through pandoc (`--track-changes=accept`: headings, every equation as LaTeX), beside the
  standard-library reader of `wayline.office`, which decodes Mendeley Cite citations into CSL-JSON
  and reads the comment threads with their anchors. Without pandoc the `.docx` is kept, flagged as
  not converted, and its comments, citations, and tables are still read;
- a `.tex` through pandoc;
- a PDF only when no source exists beside it, through `pdftotext -layout` with the margin line
  numbers stripped, and through docling for its structure where docling is installed;
- an `.xlsx` by the standard library, one CSV per sheet;
- a `.doc` through LibreOffice into a `.docx`, which then goes the `.docx` way.

Each document lives under `research/documents/<id>/`: `source/` and `media/` (both gitignored),
`text.md` with LaTeX math and a block anchor `<a id="pN"></a>` before every block, `comments.json`,
`citations.json` (CSL-JSON), and its tables under `tables/` as CSV. It is recorded in
`research/documents.json` (schema `document`), journaled as `document`, and indexed in
`research/DOCUMENTS.md`, rendered by code and capped at `RENDER_MAX_CHARS`. A locator `D1#p3`
names block `p3` of document D1's `text.md`.

The sort has three kinds, `inherited`, `critique`, and `other`. The session sorts a document with
`wayline document add <file> --kind <kind>`; a file handed over with no kind, which is how the
dashboard's drop hands one over, gets code's cautious guess (`guess_kind`): an identifier makes it
a reference, review markers a critique, anything else `other`, never `inherited`. A PDF sorted as a
reference goes to the intake's references (`intake.drop_material`), where the absorb keeps it as
the reference's source.

Per text, one version is current: the newest, in its source format. Two files are the same text
when their names are the same once a version mark (`-v2`, `_final`, a date) is taken off; the
newest is read from the package's own timestamps for an Office file and the file's time otherwise.
A newer version handed over later is recorded as the document's next version, the earlier one's
files moving under `source/v<n>/`; taking its text in like a section edit is ticket 93's. A folder
is sorted file by file, and a `.zip` is unpacked first.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wayline import __version__
from wayline.cli import parse_args
from wayline.ledger import DOCUMENT, K_BY, K_CONVERTER, K_ID, K_KIND, K_TITLE, K_VERSION, PAYLOAD_ENUMS, Ledger, now_ts
from wayline.office import UNREADABLE, OfficeError, docx_text, read_docx, read_xlsx
from wayline.project import ProjectError, find_project, write_gitignore
from wayline.tools import ToolOutput, Tools, ToolsError, failure_line, run_recorded, run_tool

__all__ = [
    "DOCUMENTS_JSON", "DOCUMENTS_MD", "DOCUMENTS_DIR", "KINDS", "SORTS", "BY", "RENDER_MAX_CHARS", "DocumentError",
    "Conversion", "convert", "guess_kind", "text_key", "read_documents", "add_document", "add_documents",
    "drop_document", "render_documents", "anchor_blocks", "strip_line_numbers", "recording_runner", "recorded_runner",
    "document_command",
]

DOCUMENTS_JSON = "documents.json"
DOCUMENTS_MD = "DOCUMENTS.md"
DOCUMENTS_DIR = "documents"
KINDS = PAYLOAD_ENUMS[(DOCUMENT, K_KIND)]
REFERENCE = "reference"
SORTS = KINDS + (REFERENCE,)
BY = PAYLOAD_ENUMS[(DOCUMENT, K_BY)]
RENDER_MAX_CHARS = 20000
STDLIB = {"name": "wayline.office", "version": __version__}
TOOL_TIMEOUT_S = 600
TEXT_SUFFIXES = (".md", ".markdown", ".txt")
# A `.zip` hand-over is unpacked up to this many files and bytes; anything past it is refused.
ZIP_MAX_FILES = 500
ZIP_MAX_BYTES = 512 * 1024 * 1024
CONVERTERS_DIR = Path(__file__).resolve().parent.parent / "converters"

_ID = re.compile(r"^D([1-9][0-9]*)\Z")
CORE_XML = "docProps/core.xml"
STAMP = "%Y-%m-%dT%H:%M:%S"
_MODIFIED = re.compile(r"<dcterms:modified[^>]*>([^<]+)<")
_EARLIER = re.compile(r"^source/(?:v[0-9]+|earlier)/")
_VERSION_MARK = re.compile(
    r"(?:[\s._-]+(?:v|ver|version|rev|r)\s*\d+[a-z]?|[\s._-]+(?:final|draft|clean|tracked|revised|copy|new|old)"
    r"|[\s._-]*\(\d+\)|[\s._-]+\d{4}[-_.]?\d{2}[-_.]?\d{2})$", re.IGNORECASE)
_LINE_NUMBER = re.compile(r"^\s*[0-9]{1,4}(?:\s{2,}|\s*$)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+\{[^}]*\})?\s*#*\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_DISPLAY_MATH = re.compile(r"\$\$.+?\$\$", re.DOTALL)
_INLINE_MATH = re.compile(r"(?<![\\$])\$(?=\S)[^$\n]+?(?<![\s\\])\$(?!\d)")
# `\\[2pt]` is a line break with a length, not a display: an opening or closing backslash after another is no math.
_BRACKET_MATH = re.compile(r"(?<!\\)\\\(.+?(?<!\\)\\\)|(?<!\\)\\\[.+?(?<!\\)\\\]", re.DOTALL)
_TEX_HEADING = re.compile(r"\\(?:part|chapter|section|subsection|subsubsection)\*?\s*[\[{]")
_TEX_MATH_ENV = re.compile(r"\\begin\{(?:equation|align|gather|multline|eqnarray|displaymath|math)\*?\}")
_TEX_COMMENT = re.compile(r"(?<!\\)%.*$", re.MULTILINE)

# Code's cautious guess at a critique: words a review uses about the work it judges, read in the
# opening of the text. One is enough; a manuscript rarely opens with any of them.
REVIEW_MARKERS = (
    re.compile(r"\b(?:referee|reviewer)(?:'s)?\s*(?:#\s*)?(?:report|comments?|\d+)\b", re.IGNORECASE),
    re.compile(r"\breport (?:of|from) (?:the )?(?:referee|reviewer)", re.IGNORECASE),
    re.compile(r"\bcomments? (?:to|for) the authors?\b", re.IGNORECASE),
    re.compile(r"\b(?:major|minor) (?:comments|concerns|points|issues|revisions?)\b", re.IGNORECASE),
    re.compile(r"\bpoint[- ]by[- ]point\b", re.IGNORECASE),
    re.compile(r"\brequired experiments?\b", re.IGNORECASE),
    re.compile(r"\b(?:editor'?s?|decision) (?:letter|decision|comments)\b", re.IGNORECASE),
    re.compile(r"\bdear (?:dr\.?|prof\.?|professor|authors?|editor)\b", re.IGNORECASE),
)
REVIEW_HEAD_CHARS = 3000


class DocumentError(ValueError):
    """A hand-over the verb refuses: no such file, a kind outside the sort, an unreadable zip."""


# --- conversion ---------------------------------------------------------------------------------------


@dataclass
class Conversion:
    """What converting one file gave, before anything is written under `research/`.

    `files` maps a path relative to the document's directory to its bytes (`comments.json`,
    `citations.json`, `tables/<name>.csv`, `media/...`, a `.doc`'s `.docx` under `source/`).
    """

    converted: bool = False
    text: str = None
    files: dict = field(default_factory=dict)
    converters: list = field(default_factory=list)
    losses: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    damage: dict = field(default_factory=dict)
    title: str = None
    abstract: str = None
    headings: list = field(default_factory=list)


def _run(tools, name, args, run, timeout=TOOL_TIMEOUT_S):
    """`(output, entry)` of one recorded tool, or `(None, None)` when `tools.json` records none."""
    try:
        return run_recorded(name, args, tools=tools, run=run, timeout=timeout), tools.entry(name)
    except ToolsError:
        return None, None


def _named(entry, name):
    return {"name": name, "version": str((entry or {}).get("version") or "unknown")}


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _letters(text):
    return re.sub(r"[^0-9a-z]+", "", str(text or "").lower())


def _first_sentence(text, limit=160):
    flat = " ".join(str(text or "").split())
    sentence = _SENTENCE_END.split(flat, maxsplit=1)[0] if flat else ""
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + "…"


def _equations(markdown):
    """How many equations a Markdown text writes: `$$...$$`, `$...$`, `\\(...\\)`, and `\\[...\\]`."""
    count = len(_DISPLAY_MATH.findall(markdown))
    rest = _DISPLAY_MATH.sub(" ", markdown)
    count += len(_BRACKET_MATH.findall(rest))
    return count + len(_INLINE_MATH.findall(_BRACKET_MATH.sub(" ", rest)))


def _front_matter(text):
    """Split pandoc's standalone Markdown into its YAML metadata (title and abstract only) and the body."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((index for index in range(1, len(lines)) if lines[index].strip() in ("---", "...")), None)
    if end is None:
        return {}, text
    meta, key = {}, None
    for line in lines[1:end]:
        found = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if found:
            key, value = found.group(1), found.group(2).strip()
            meta[key] = "" if value in ("|", ">", "|-", ">-") else _unquote(value)
        elif key is not None and line.startswith(" "):
            meta[key] = (meta[key] + ("\n" if meta[key] and not line.strip() else " " if meta[key] else "") + line.strip()).strip(" ")
    meta = {key: " ".join(str(value).split()) if key == "title" else str(value).strip() for key, value in meta.items()}
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def _unquote(value):
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except ValueError:
            return value[1:-1]
    return value


def _blocks(body):
    """The blocks of a Markdown body: runs of lines between blank lines, a fenced block or a `$$` display kept whole."""
    blocks, current, fence, math = [], [], None, False
    for line in body.split("\n"):
        stripped = line.strip()
        if fence is None and not math and not stripped:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
        elif stripped.count("$$") % 2 == 1:
            math = not math
    if current:
        blocks.append("\n".join(current))
    return blocks


def anchor_blocks(body):
    """`(text, blocks)`: the body with `<a id="pN"></a>` before every block, and the blocks as `{locator, text}`."""
    blocks = [{"locator": "p%d" % number, "text": block} for number, block in enumerate(_blocks(body), 1)]
    text = "".join('<a id="%s"></a>\n\n%s\n\n' % (block["locator"], block["text"]) for block in blocks)
    return text, blocks


def _headings(blocks):
    """Each heading of the anchored blocks with its level, locator, and the first sentence after it."""
    headings = []
    for index, block in enumerate(blocks):
        found = _HEADING.match(block["text"].strip()) if "\n" not in block["text"].strip() else None
        if not found:
            continue
        following = next((later["text"] for later in blocks[index + 1:] if not _HEADING.match(later["text"].strip())), "")
        nested = next((later for later in blocks[index + 1:index + 2] if _HEADING.match(later["text"].strip())), None)
        headings.append({"level": len(found.group(1)), "text": found.group(2).strip(), "locator": block["locator"],
                         "first_sentence": "" if nested else _first_sentence(following)})
    return headings


def _abstract_from(blocks):
    for index, block in enumerate(blocks):
        found = _HEADING.match(block["text"].strip())
        if found and found.group(2).strip().lower().rstrip(".:") == "abstract" and index + 1 < len(blocks):
            return " ".join(blocks[index + 1]["text"].split())
    return None


def _finish(conversion, meta_text, front=None):
    """Anchor the converted Markdown, read its headings, and keep the front matter above the blocks."""
    text, blocks = anchor_blocks(meta_text)
    conversion.headings = _headings(blocks)
    conversion.counts.setdefault("blocks", len(blocks))
    conversion.counts.setdefault("headings", len(conversion.headings))
    if conversion.abstract is None:
        conversion.abstract = _abstract_from(blocks)
    if conversion.title is None and conversion.headings:
        conversion.title = conversion.headings[0]["text"]
    conversion.text = (front or "") + text
    conversion.converted = True
    return blocks


def _front(meta):
    """The YAML front matter kept at the top of `text.md`: a document's title and abstract are read, never deconstructed."""
    if not meta:
        return ""
    lines = ["---"]
    for key in ("title", "abstract"):
        if meta.get(key):
            lines.append("%s: %s" % (key, json.dumps(meta[key], ensure_ascii=False)))
    return "\n".join(lines + ["---", "", ""]) if len(lines) > 1 else ""


def _warnings(output):
    lines = (output.stderr or b"").decode("utf-8", errors="replace").splitlines()
    return ["pandoc: %s" % line.split("]", 1)[-1].strip() for line in lines if line.startswith("[WARNING]")]


def _cite(body, citations):
    """Write each Mendeley citation's shown text as a pandoc citation `[@id; @id]`; returns the body and how many found no place."""
    unplaced, position = 0, 0
    for citation in citations:
        if not citation["ids"] or not citation["shown"]:
            unplaced += 1 if citation["ids"] else 0
            continue
        marker = "[%s]" % "; ".join("@" + work_id for work_id in citation["ids"])
        for shown in ("^%s^" % citation["shown"], citation["shown"]):
            at = body.find(shown, position)
            if at < 0:
                at = body.find(shown)
            if at >= 0:
                body = body[:at] + marker + body[at + len(shown):]
                position = at + len(marker)
                break
        else:
            unplaced += 1
    return body, unplaced


def _table_csv(rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def _safe_name(name, taken):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-.") or "sheet"
    candidate, number = stem, 2
    while candidate.lower() in taken:
        candidate, number = "%s-%d" % (stem, number), number + 1
    taken.add(candidate.lower())
    return candidate


def _docx(path, work, tools, run, conversion):
    try:
        reading = read_docx(path)
    except OfficeError as failure:
        conversion.losses.append("not converted: %s" % failure)
        return conversion
    conversion.converters.append(dict(STDLIB))
    conversion.counts.update(reading.counts)
    conversion.title, conversion.abstract = reading.title, reading.abstract
    conversion.files["citations.json"] = _json_bytes(reading.works)
    for number, rows in enumerate(reading.tables, 1):
        conversion.files["tables/table-%d.csv" % number] = _table_csv(rows)
    if reading.counts.get("insertions") or reading.counts.get("deletions"):
        conversion.losses.append("tracked changes accepted: %s kept, %s dropped" % (
            _plural(reading.counts["insertions"], "insertion"), _plural(reading.counts["deletions"], "deletion")))
    if reading.counts.get("formatting_changes"):
        conversion.losses.append("%s not kept" % _plural(reading.counts["formatting_changes"], "tracked formatting change"))
    if reading.threads:
        conversion.losses.append("comments are kept in comments.json, not in text.md")
    media = work / "media"
    output, entry = _run(tools, "pandoc", ["-s", "-f", "docx", "-t", "markdown", "--wrap=none", "--track-changes=accept",
                                            "--extract-media=%s" % media, str(path)], run)
    blocks = []
    if output is None:
        conversion.losses.insert(0, "not converted: pandoc is not recorded in tools.json (wayline tools install pandoc)")
    elif output.returncode != 0:
        conversion.losses.insert(0, "not converted: pandoc failed (%s)" % failure_line(output))
    else:
        conversion.converters.insert(0, _named(entry, "pandoc"))
        conversion.losses.extend(_warnings(output))
        meta, body = _front_matter(output.stdout.decode("utf-8", errors="replace").replace("%s/" % work, ""))
        body, unplaced = _cite(body, reading.citations)
        conversion.title = conversion.title or meta.get("title") or None
        conversion.abstract = conversion.abstract or meta.get("abstract") or None
        source_headings = reading.counts.get("headings", 0)
        source_equations = reading.counts.get("equations", 0)
        blocks = _finish(conversion, body, _front({"title": conversion.title, "abstract": conversion.abstract}))
        conversion.counts["headings"] = source_headings
        conversion.damage = {"headings": max(0, source_headings - len(conversion.headings)),
                             "equations": max(0, source_equations - _equations(body)), "citations": unplaced}
        for found in sorted(media.rglob("*")) if media.is_dir() else []:
            if found.is_file():
                conversion.files[str(found.relative_to(work))] = found.read_bytes()
    threads = []
    for thread in reading.threads:
        block = _anchor_block(thread["anchor"], blocks)
        threads.append({"id": thread["id"], "anchor": {"text": thread["anchor"], "block": block}, "done": thread["done"],
                        "comments": thread["comments"]})
    conversion.files["comments.json"] = _json_bytes({"threads": threads})
    if conversion.converted:
        conversion.damage["comments"] = sum(1 for thread in threads if thread["anchor"]["block"] is None)
    return conversion


def _anchor_block(anchor, blocks):
    wanted = _letters(anchor)
    if not wanted:
        return None
    for block in blocks:
        if wanted in _letters(block["text"]):
            return block["locator"]
    return None


def _tex(path, work, tools, run, conversion):
    source = path.read_text(encoding="utf-8", errors="replace")
    plain = _TEX_COMMENT.sub("", source)
    source_headings = len(_TEX_HEADING.findall(plain))
    source_equations = len(_TEX_MATH_ENV.findall(plain)) + _equations(plain)
    output, entry = _run(tools, "pandoc", ["-s", "-f", "latex", "-t", "markdown", "--wrap=none", str(path)], run)
    if output is None:
        conversion.losses.append("not converted: pandoc is not recorded in tools.json (wayline tools install pandoc)")
        return conversion
    if output.returncode != 0:
        conversion.losses.append("not converted: pandoc failed (%s)" % failure_line(output))
        return conversion
    conversion.converters.append(_named(entry, "pandoc"))
    conversion.losses.extend(_warnings(output))
    meta, body = _front_matter(output.stdout.decode("utf-8", errors="replace"))
    conversion.title, conversion.abstract = meta.get("title") or None, meta.get("abstract") or None
    _finish(conversion, body, _front(meta))
    conversion.counts["equations"] = _equations(body)
    conversion.damage = {"headings": max(0, source_headings - len(conversion.headings)),
                         "equations": max(0, source_equations - conversion.counts["equations"])}
    return conversion


def strip_line_numbers(text):
    """`(text, count)`: `pdftotext -layout` output with a manuscript's margin line numbers taken off.

    Only when at least half of the non-blank lines open with a number set apart from the text, so a
    table whose rows start with a number is left as it is.
    """
    lines = text.split("\n")
    filled = [line for line in lines if line.strip() and line.strip() != "\f"]
    numbered = [line for line in filled if _LINE_NUMBER.match(line.lstrip("\f"))]
    if not filled or len(numbered) * 2 < len(filled):
        return text, 0
    out = []
    for line in lines:
        page = "\f" if line.startswith("\f") else ""
        body = line.lstrip("\f")
        out.append(page + (_LINE_NUMBER.sub("", body, count=1) if _LINE_NUMBER.match(body) else body))
    return "\n".join(out), len(numbered)


def _pdftotext_markdown(text, headings=None):
    """The `pdftotext -layout` text as Markdown: one block per run of lines, each line taken off its layout indent.

    `headings` maps a heading's letters to its level, from docling's structure: a line whose letters
    are a heading's becomes that heading, on a block of its own. Returns `(markdown, pages, marked)`.
    """
    headings = headings or {}
    pages = text.split("\f")
    blocks, marked = [], 0
    for page in pages:
        current = []
        for line in page.split("\n"):
            flat = " ".join(line.split())
            level = headings.get(re.sub(r"[^a-z]+", "", flat.lower())) if flat else None
            if not flat or level:
                if current:
                    blocks.append(_escape_block("\n".join(current)))
                    current = []
                if level:
                    blocks.append("#" * level + " " + flat)
                    marked += 1
                continue
            current.append(flat)
        if current:
            blocks.append(_escape_block("\n".join(current)))
    return "\n\n".join(blocks) + "\n", max(1, len([page for page in pages if page.strip()])), marked


def _escape_block(block):
    """Keep a line of text from reading as Markdown structure: a leading `#`, `>`, `-`, or `1.` is escaped."""
    return "\n".join(re.sub(r"^([#>+*-]|\d+[.)])(\s)", lambda found: "\\" + found.group(1) + found.group(2), line) for line in block.split("\n"))


def _docling_headings(document):
    """The headings docling found, as `{letters: level}`: its title at level 1, a section header one below its own level."""
    from wayline.pdf_inventory import _docling_walk  # one walk of the body in reading order, shared with the PDF inventory

    headings = {}
    for item in _docling_walk(document):
        letters = re.sub(r"[^a-z]+", "", str(item.get("text") or "").lower())
        if not letters:
            continue
        if item.get("label") == "title":
            headings.setdefault(letters, 1)
        elif item.get("label") == "section_header":
            headings.setdefault(letters, min(6, 1 + int(item.get("level") or 1)))
    return headings


def _pdf(path, work, tools, run, conversion):
    output, entry = _run(tools, "pdftotext", ["-layout", str(path), "-"], run)
    if output is None:
        conversion.losses.append("not converted: pdftotext is not recorded in tools.json (wayline tools install pdftotext)")
        return conversion
    if output.returncode != 0:
        conversion.losses.append("not converted: pdftotext failed (%s)" % failure_line(output))
        return conversion
    conversion.converters.append(_named(entry, "pdftotext"))
    text, numbered = strip_line_numbers(output.stdout.decode("utf-8", errors="replace"))
    out = work / "docling"
    done, docling = _run(tools, "docling", [str(CONVERTERS_DIR / "docling_convert.py"), str(path), str(out), "--no-formulas"], run)
    headings = None
    if done is not None and done.returncode == 0:
        try:
            headings = _docling_headings(json.loads((out / "document.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            conversion.losses.append("docling left no document.json it could read, so the text has no headings")
    elif done is not None:
        conversion.losses.append("docling failed (%s), so the text has no headings" % failure_line(done))
    else:
        conversion.losses.append("docling is not installed (wayline tools install docling), so the text has no headings")
    if headings is not None:
        conversion.converters.append(_named(docling, "docling"))
    body, pages, marked = _pdftotext_markdown(text, headings)
    if headings is not None and not marked:
        conversion.losses.append("docling found no heading in it, so the text has none")
    conversion.counts.update(pages=pages, line_numbers_stripped=numbered)
    conversion.losses.append("a PDF is the lossy copy: math is Unicode letters rather than LaTeX, and tables and figures are kept as their text")
    if numbered:
        conversion.losses.append("%d margin line numbers stripped" % numbered)
    _finish(conversion, body)
    conversion.counts["equations"] = _equations(body)
    return conversion


def _xlsx(path, work, tools, run, conversion):
    try:
        sheets = read_xlsx(path)
    except OfficeError as failure:
        conversion.losses.append("not converted: %s" % failure)
        return conversion
    conversion.converters.append(dict(STDLIB))
    taken, lines, cells = set(), [], 0
    for name, rows in sheets:
        safe = _safe_name(name, taken)
        conversion.files["tables/%s.csv" % safe] = _table_csv(rows)
        cells += sum(1 for row in rows for value in row if value != "")
        header = ", ".join(value for value in (rows[0] if rows else []) if value)
        lines += ["## %s" % name, "", "`tables/%s.csv`: %d rows, %d columns%s." % (
            safe, len(rows), max((len(row) for row in rows), default=0), "; the first row reads %s" % header if header else "")]
        lines.append("")
    conversion.counts.update(sheets=len(sheets), rows=sum(len(rows) for _, rows in sheets), cells=cells)
    conversion.losses.append("formulas are kept as their cached values; formatting and merged ranges are not kept")
    _finish(conversion, "\n".join(lines))
    conversion.counts["headings"] = 0
    conversion.headings = []
    conversion.title = path.stem
    return conversion


def _doc(path, work, tools, run, conversion):
    outdir = work / "soffice"
    output, entry = _run(tools, "soffice", ["--headless", "--norestore", "-env:UserInstallation=file://%s" % (work / "lo-profile"),
                                             "--convert-to", "docx", "--outdir", str(outdir), str(path)], run)
    made = outdir / (path.stem + ".docx")
    if output is None:
        conversion.losses.append("not converted: LibreOffice (soffice) is not recorded in tools.json (wayline tools install soffice)")
        return conversion
    if output.returncode != 0 or not made.is_file():
        conversion.losses.append("not converted: LibreOffice did not turn it into a .docx (%s)" % failure_line(output))
        return conversion
    conversion.converters.append(_named(entry, "soffice"))
    conversion.files["source/%s.docx" % path.stem] = made.read_bytes()
    converters = list(conversion.converters)
    _docx(made, work, tools, run, conversion)
    conversion.converters = converters + [converter for converter in conversion.converters if converter not in converters]
    return conversion


def _text(path, work, tools, run, conversion):
    body = path.read_text(encoding="utf-8", errors="replace")
    _finish(conversion, body)
    conversion.counts["equations"] = _equations(body)
    return conversion


ROUTES = {".docx": _docx, ".tex": _tex, ".pdf": _pdf, ".xlsx": _xlsx, ".doc": _doc}


def convert(path, tools=None, run=None, work=None):
    """Convert one file into a `Conversion`; nothing is written under `research/`.

    `run` is the tool runner (`tools.run_tool` unless a test passes the recorded one), and every tool
    is called by its record in `tools`. A file no route reads is kept as given and not converted.
    """
    path = Path(path)
    tools = tools if tools is not None else Tools()
    run = run or run_tool
    conversion = Conversion()
    suffix = path.suffix.lower()
    with tempfile.TemporaryDirectory(prefix="wayline-document-") as scratch:
        work = Path(work or scratch)
        if suffix in ROUTES:
            ROUTES[suffix](path, work, tools, run, conversion)
        elif suffix in TEXT_SUFFIXES:
            _text(path, work, tools, run, conversion)
        else:
            conversion.losses.append("not converted: no converter reads %s; the file is kept as given" % (suffix or "a file with no suffix"))
    if conversion.title is None:
        conversion.title = path.stem
    return conversion


# --- the sort -----------------------------------------------------------------------------------------


def _has_identifier(path):
    """Whether a file names a published work: a PDF whose DOI or arXiv id can be read, or a reference list."""
    from wayline import intake  # the intake imports the gates, which nothing else here needs

    if path.suffix.lower() == ".pdf":
        gathered = intake.gather({"materials": [str(path)]}, path.parent, path.parent)
        return any(item.get("identifier") for item in gathered.references)
    if path.suffix.lower() in TEXT_SUFFIXES:
        try:
            return intake.reference_list(path.read_text(encoding="utf-8", errors="replace")) is not None
        except OSError:
            return False
    return False


def _opening(path, tools=None, run=None):
    """The opening of a file's text, for the review markers: a `.docx` through the reader, a PDF through `pdftotext`."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_text(path)[:REVIEW_HEAD_CHARS]
    if suffix in TEXT_SUFFIXES or suffix == ".tex":
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read(REVIEW_HEAD_CHARS)
        except OSError:
            return ""
    if suffix == ".pdf":
        output, _ = _run(tools if tools is not None else Tools(), "pdftotext", ["-l", "2", "-layout", str(path), "-"], run or run_tool)
        if output is not None and output.returncode == 0:
            return output.stdout.decode("utf-8", errors="replace")[:REVIEW_HEAD_CHARS]
    return ""


def guess_kind(path, tools=None, run=None):
    """Code's cautious guess at a file handed over with no session: `reference`, `critique`, or `other`, never `inherited`."""
    path = Path(path)
    opening = _opening(path, tools, run)
    if any(marker.search(opening) for marker in REVIEW_MARKERS):
        return "critique"  # before the identifiers: a referee report cites published work too
    if _has_identifier(path):
        return REFERENCE
    return "other"


def text_key(name):
    """The name two versions of one text share: the file's stem with its version marks taken off."""
    stem = Path(str(name)).stem.lower()
    while True:
        shorter = _VERSION_MARK.sub("", stem)
        if shorter == stem or not shorter.strip(" ._-"):
            break
        stem = shorter
    return re.sub(r"[^0-9a-z]+", "-", stem).strip("-") or "document"


def _dated(path):
    """When a file was last saved, in UTC: an Office package's `dcterms:modified`, else its newest entry, else the file's time.

    Word stamps every entry of a `.docx` 1980-01-01, so only `docProps/core.xml` says when it was
    saved; an entry time from 1980 is no time at all. A package's entry times carry no zone and are
    read as UTC.
    """
    if path.suffix.lower() in (".docx", ".xlsx"):
        try:
            with zipfile.ZipFile(path) as package:
                core = package.read(CORE_XML) if CORE_XML in package.namelist() else b""
                stamps = [info.date_time for info in package.infolist() if info.date_time[0] > 1980]
        except UNREADABLE:
            core, stamps = b"", []
        modified = _core_modified(core)
        if modified is not None:
            return modified
        if stamps:
            return datetime(*max(stamps)).strftime(STAMP)
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime(STAMP)


def _core_modified(core):
    found = _MODIFIED.search(core.decode("utf-8", errors="replace")) if core else None
    if found is None:
        return None
    try:
        when = datetime.fromisoformat(found.group(1).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when.astimezone(timezone.utc) if when.tzinfo else when).strftime(STAMP)


# --- the record ---------------------------------------------------------------------------------------


def read_documents(project):
    """The documents of `research/documents.json` in id order; empty when the project has none yet."""
    ledger = Ledger(project)
    if not ledger.path(DOCUMENTS_JSON).is_file():
        return []
    record = ledger.read_json(DOCUMENTS_JSON)
    if not isinstance(record, dict) or not isinstance(record.get("documents"), list):
        raise ValueError("research/%s is not an object holding a `documents` list" % DOCUMENTS_JSON)
    return list(record["documents"])


def _next_id(documents):
    numbers = [int(match.group(1)) for match in (_ID.match(str(document.get("id"))) for document in documents) if match]
    return "D%d" % (max(numbers, default=0) + 1)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file(relpath, data, copy=False):
    entry = {"path": relpath, "sha256": _sha(data), "size": len(data)}
    if copy:
        entry["copy"] = True
    return entry


def _converter_line(converters):
    return ", ".join("%s %s" % (converter["name"], converter["version"]) for converter in converters) or None


def _write(ledger, documents, document, by):
    """Write the record, journal the change to `document`, and render DOCUMENTS.md; the caller holds the lock."""
    ledger.write_json(DOCUMENTS_JSON, {"documents": documents}, schema="document")
    ledger.append_event(DOCUMENT, {K_ID: document["id"], K_TITLE: document["title"], K_KIND: document["kind"],
                                   K_VERSION: document["version"],
                                   K_CONVERTER: _converter_line(document["converters"]) if document["converted"] else None, K_BY: by})
    ledger.write_markdown(DOCUMENTS_MD, render_documents(documents))


def _match(documents, key, kind):
    """The document a file of `key` is a version of, or None. A critique has no versions: a second one is another critique."""
    if kind == "critique":
        return None
    for document in documents:
        if document.get("key") == key and document.get("kind") != "critique":
            return document
    return None


def _known(document, digest):
    """Whether these bytes are already one of the document's files, now or in an earlier version."""
    files = list(document.get("files") or []) + [entry for earlier in document.get("history") or [] for entry in earlier.get("files") or []]
    return any(entry.get("sha256") == digest for entry in files)


def _plan(documents, key, kind, digest, dated, as_copy):
    """`(what, document)`: what keeping these bytes comes to, `already`, `copy`, `earlier`, `next` (version), or `new`."""
    for document in documents:
        if document.get("key") == key and _known(document, digest):
            return "already", document
    found = _match(documents, key, kind)
    if found is None:
        return "new", None
    if as_copy:
        return "copy", found
    if dated < (found.get("dated") or ""):
        return "earlier", found
    return "next", found


def add_document(project, path, kind=None, by=None, tools=None, run=None, name=None, as_copy=False, key=None):
    """Keep one file as a document (or hand a reference to the intake); returns what was done.

    `kind` is the session's sort (`inherited`, `critique`, `other`, or `reference`), recorded with
    `by: session`; None takes code's cautious guess, recorded with `by: code`. The result is
    `{name, sorted, by, said, ...}`: for a document also `id`, `version`, `title`, `already` (these
    bytes were kept before) and `earlier` (recorded as an earlier version, not the current one); for
    a reference, what `intake.drop_material` returned. With `as_copy` the file is kept beside the
    document of the same text (a PDF of a `.docx`) and not converted. `key` is the text the file is
    a version of (`text_key` of its name unless a folder's hand-over names its subfolder too).

    The conversion runs outside the ledger's lock, since a converter may take minutes, and only for
    a version that becomes the current one; the record is planned again under the lock, and a
    change in between plans it once more.
    """
    project, path = Path(project).resolve(), Path(path)
    name = name or path.name
    if not path.is_file():
        raise DocumentError("%s is not a file" % path)
    if kind is not None and kind not in SORTS:
        raise DocumentError("a document is sorted as one of %s, got %r" % (", ".join(SORTS), kind))
    by = by or ("session" if kind is not None else "code")
    if by not in BY:
        raise DocumentError("a document is sorted by one of %s, got %r" % (", ".join(BY), by))
    kind = kind or guess_kind(path, tools, run)
    write_gitignore(project)
    if kind == REFERENCE:
        return _to_intake(project, path, name, by)
    data = path.read_bytes()
    digest, key, dated = _sha(data), key or text_key(name), _dated(path)
    ledger, conversion = Ledger(project), None
    for _ in range(3):
        what, _found = _plan(read_documents(project), key, kind, digest, dated, as_copy)
        if what in ("new", "next") and conversion is None:
            conversion = convert(path, tools=tools, run=run)
        with ledger.lock():
            documents = read_documents(project)
            what, found = _plan(documents, key, kind, digest, dated, as_copy)
            if what in ("new", "next") and conversion is None:
                continue  # the record changed while nothing was converted: plan again, outside the lock
            result = {"name": name, "by": by, "already": what == "already", "earlier": what == "earlier"}
            if what == "already":
                return _said(dict(result, sorted=found["kind"], id=found["id"], version=found["version"], title=found["title"]))
            if what == "copy":
                document = _keep_copy(ledger, found, name, data)
                result["copy"] = True
            elif what == "earlier":
                document = _keep_earlier(ledger, found, name, data, dated)
            elif what == "next":
                document = _next_version(ledger, found, kind if by == "session" else found["kind"], by, name, data, dated, conversion)
            else:
                document = _new_document(ledger, _next_id(documents), kind, by, key, name, data, dated, conversion)
                documents.append(document)
            _write(ledger, documents, document, by)
        return _said(dict(result, sorted=document["kind"], id=document["id"], version=document["version"], title=document["title"]))
    raise DocumentError("research/%s kept changing while %s was handed over; hand it over again" % (DOCUMENTS_JSON, name))


def _said(result):
    """The result with `said`, the one line the dashboard and the verb print for it."""
    if result.get("sorted") == REFERENCE:
        taken = result.get("taken")
        where = ("there is no INTAKE.md yet, so the next wayline intake takes it" if taken is None
                 else "added to INTAKE.md under %s" % ", ".join(taken) if taken else "INTAKE.md already lists it")
        result["said"] = "sorted as a reference%s: kept as %s; %s" % (" (code's guess)" if result.get("by") == "code" else "",
                                                                       result.get("path"), where)
    elif result.get("already"):
        result["said"] = "already kept as %s version %d (%s)" % (result["id"], result["version"], result["sorted"])
    elif result.get("copy"):
        result["said"] = "kept beside %s as a copy, not converted: the source format is converted" % result["id"]
    elif result.get("earlier"):
        result["said"] = "kept as an earlier version of %s, which stays at version %d" % (result["id"], result["version"])
    else:
        result["said"] = "kept as %s version %d, sorted %s%s" % (result["id"], result["version"], result["sorted"],
                                                                  " (code's guess)" if result["by"] == "code" else "")
    return result


def _to_intake(project, path, name, by):
    """A reference goes to the intake's references, kept under `research/intake/` (gitignored for a PDF) by `drop_material`."""
    from wayline.intake import drop_material, plain_name  # the intake imports the gates, which nothing else here needs

    result = drop_material(project, plain_name(name), path.read_bytes())
    return _said(dict(result, name=name, sorted=REFERENCE, by=by))


def _write_files(ledger, document_id, conversion, name, data):
    """Write the source and everything the conversion gave under `documents/<id>/`; returns the file entries."""
    base = "%s/%s" % (DOCUMENTS_DIR, document_id)
    entries = []
    source = "source/%s" % name
    ledger.write_bytes("%s/%s" % (base, source), data)
    entries.append(_file(source, data))
    outputs = dict(conversion.files)
    if conversion.converted:
        outputs["text.md"] = conversion.text.encode("utf-8")
    for relpath in sorted(outputs):
        ledger.write_bytes("%s/%s" % (base, relpath), outputs[relpath])
        entries.append(_file(relpath, outputs[relpath]))
    return entries


def _fields(conversion):
    return {"title": " ".join(str(conversion.title or "").split()) or "untitled", "converted": conversion.converted,
            "converters": list(conversion.converters), "losses": list(conversion.losses), "counts": dict(conversion.counts),
            "damage": dict(conversion.damage), "abstract": conversion.abstract, "headings": list(conversion.headings)}


def _new_document(ledger, document_id, kind, by, key, name, data, dated, conversion):
    document = {"id": document_id, "kind": kind, "version": 1, "key": key, "origin": name, "dated": dated,
                "sorted_by": by, "added": now_ts()}
    document.update(_fields(conversion))
    document["files"] = _write_files(ledger, document_id, conversion, name, data)
    document["history"] = []
    return document


def _next_version(ledger, document, kind, by, name, data, dated, conversion):
    """The document's next version: its current files move under `source/v<n>/` (the source) or go (the rest)."""
    base = "%s/%s" % (DOCUMENTS_DIR, document["id"])
    earlier = {"version": document["version"], "origin": document["origin"], "dated": document.get("dated"),
               "added": document.get("added"), "files": []}
    for entry in document.get("files") or []:
        current = "%s/%s" % (base, entry["path"])
        if entry["path"].startswith("source/") and not _EARLIER.match(entry["path"]):
            moved = "source/v%d/%s" % (document["version"], entry["path"][len("source/"):])
            try:
                ledger.write_bytes("%s/%s" % (base, moved), ledger.path(current).read_bytes())
                ledger.remove_file(current)
                earlier["files"].append(dict(entry, path=moved))
            except OSError:
                earlier["files"].append(entry)
        else:
            earlier["files"].append(entry)
            if ledger.path(current).is_file():
                ledger.remove_file(current)
    if ledger.path(base + "/media").is_dir():
        ledger.remove_tree(base + "/media")
    document.update(_fields(conversion))
    document.update(kind=kind, version=document["version"] + 1, origin=name, dated=dated, sorted_by=by, added=now_ts())
    document["files"] = _write_files(ledger, document["id"], conversion, name, data)
    document["history"] = list(document.get("history") or []) + [earlier]
    return document


def _keep_earlier(ledger, document, name, data, dated):
    """A version older than the current one, handed over late: kept under `source/earlier/`, recorded in the history as version 0."""
    relpath = "source/earlier/%s" % name
    ledger.write_bytes("%s/%s/%s" % (DOCUMENTS_DIR, document["id"], relpath), data)
    document["history"] = sorted(list(document.get("history") or []) + [
        {"version": 0, "origin": name, "dated": dated, "added": now_ts(), "files": [_file(relpath, data)]}],
        key=lambda earlier: (earlier.get("dated") or "", earlier.get("version") or 0))
    return document


def _keep_copy(ledger, document, name, data):
    relpath = "source/%s" % name
    ledger.write_bytes("%s/%s/%s" % (DOCUMENTS_DIR, document["id"], relpath), data)
    document["files"] = [entry for entry in document.get("files") or [] if entry["path"] != relpath] + [_file(relpath, data, copy=True)]
    return document


# --- folders and zips ---------------------------------------------------------------------------------


def _unpack(archive, target):
    """Unpack a `.zip` into `target`, refusing a path outside it, a link, and more than the caps allow."""
    try:
        package = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as failure:
        raise DocumentError("%s is not a zip that can be read: %s" % (archive, failure)) from None
    with package:
        members = [info for info in package.infolist() if not info.is_dir()]
        if len(members) > ZIP_MAX_FILES or sum(info.file_size for info in members) > ZIP_MAX_BYTES:
            raise DocumentError("%s holds more than %d files or %d bytes; unpack it and hand over the folder" % (archive, ZIP_MAX_FILES, ZIP_MAX_BYTES))
        root = Path(target).resolve()
        for info in members:
            parts = Path(info.filename).parts
            if info.filename.startswith("/") or ".." in parts or any(part.startswith(".") or part == "__MACOSX" for part in parts):
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # a symbolic link
            destination = (root / info.filename).resolve()
            if root not in destination.parents:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with package.open(info) as source, open(destination, "wb") as out:
                    shutil.copyfileobj(source, out)
            except UNREADABLE as failure:
                raise DocumentError("%s: %s cannot be unpacked (%s), so nothing in it was kept" % (archive, info.filename, failure)) from None
    return root


def _folder_key(folder, path):
    """The text a file in a hand-over folder is a version of: its name's `text_key`, under its subfolder when it has one.

    `chapter1/main.tex` and `chapter2/main.tex` are two texts, and so are `round-1/report.pdf` and
    `round-2/report.pdf`.
    """
    parent = path.relative_to(folder).parent
    stem = text_key(path.name)
    return stem if parent == Path(".") else "%s/%s" % (re.sub(r"[^0-9a-z/]+", "-", parent.as_posix().lower()).strip("-"), stem)


def _files_in(folder):
    return sorted(path for path in Path(folder).rglob("*")
                  if path.is_file() and not any(part.startswith(".") or part == "__MACOSX" for part in path.relative_to(folder).parts))


def add_documents(project, path, kind=None, by=None, tools=None, run=None):
    """Hand over a file, a folder, or a `.zip`; returns one result per file, in the order they were kept.

    A folder is sorted file by file (a `.zip` is unpacked first). Files that are versions of one text
    are kept oldest first, so the newest in its source format ends as the current version; a PDF
    beside a source of the same text is kept as a copy and not converted.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise DocumentError("%s does not exist" % path)
    if path.is_file() and path.suffix.lower() != ".zip":
        return [add_document(project, path, kind=kind, by=by, tools=tools, run=run)]
    with tempfile.TemporaryDirectory(prefix="wayline-unpack-") as scratch:
        folder = _unpack(path, scratch) if path.is_file() else path
        groups = {}
        for found in _files_in(folder):
            groups.setdefault(_folder_key(folder, found), []).append(found)
        results = []
        for key in sorted(groups):
            members = groups[key]
            sources = sorted((member for member in members if member.suffix.lower() != ".pdf"), key=lambda member: (_dated(member), member.name))
            pdfs = sorted((member for member in members if member.suffix.lower() == ".pdf"), key=lambda member: (_dated(member), member.name))
            if sources:
                for member in sources:
                    results.append(add_document(project, member, kind=kind, by=by, tools=tools, run=run, key=key))
                for member in pdfs:
                    if kind == REFERENCE or (kind is None and _has_identifier(member)):
                        results.append(add_document(project, member, kind=REFERENCE, by=by, tools=tools, run=run))
                    else:  # beside its source, a PDF takes the source's sort, and whoever sorted it
                        results.append(add_document(project, member, kind=kind or results[-1].get("sorted"), by=by or results[-1].get("by"),
                                                    tools=tools, run=run, as_copy=True, key=key))
            else:
                for member in pdfs:
                    results.append(add_document(project, member, kind=kind, by=by, tools=tools, run=run, key=key))
        return results


# --- the dashboard's drop -----------------------------------------------------------------------------


def drop_document(project, name, data, tools=None, run=None):
    """A file dropped on the dashboard with no session: code's cautious guess sorts it, a `.zip` file by file.

    The name and the size are checked as the intake's drop checks them. Returns the result of
    `add_document` for one file, or `{name, said, files: [...]}` for a `.zip`.
    """
    from wayline.intake import check_drop  # the intake imports the gates, which nothing else here needs

    name, data = check_drop(name, data, verb="wayline document add <path>")
    with tempfile.TemporaryDirectory(prefix="wayline-drop-") as scratch:
        dropped = Path(scratch) / name
        dropped.write_bytes(data)
        if dropped.suffix.lower() == ".zip":
            results = add_documents(project, dropped, tools=tools, run=run)
            return {"name": name, "files": results, "said": "unpacked, %d file%s sorted: %s" % (
                len(results), "" if len(results) == 1 else "s", "; ".join("%s %s" % (result["name"], result["said"]) for result in results))}
        return add_document(project, dropped, tools=tools, run=run)


# --- DOCUMENTS.md -------------------------------------------------------------------------------------

# How much each pass keeps: a first sentence's length, an abstract's, the deepest heading level listed.
_DETAIL = ((200, 1500, 6), (100, 600, 6), (0, 300, 6), (0, 200, 2), (0, 0, 0))


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:max(0, limit - 1)].rstrip() + "…"


def _counted(key, value):
    """`1 equation`, `2 equations`: a count's key read as the plural it is, made singular for one."""
    words = key.replace("_", " ")
    return "%d %s" % (value, words[:-1] if value == 1 and words.endswith("s") else words)


def _counts_line(counts):
    shown = [_counted(key, value) for key, value in counts.items() if isinstance(value, int)]
    return ", ".join(shown) or "none"


def _damage_line(damage):
    shown = [_counted(key, value) for key, value in damage.items() if isinstance(value, int) and value]
    return ("lost in conversion: " + ", ".join(shown)) if shown else "none counted"


def _document_lines(document, sentence, abstract, depth):
    earlier = ["v%d %s" % (entry["version"], entry["origin"]) for entry in document.get("history") or []]
    copies = [entry["path"][len("source/"):] for entry in document.get("files") or [] if entry.get("copy")]
    lines = ["## %s %s" % (document["id"], document["title"]), "",
             "- Kind: %s, version %d (%s%s)" % (document["kind"], document["version"], document["origin"],
                                                "; earlier: %s" % ", ".join(earlier) if earlier else ""),
             "- Converted: %s" % (_converter_line(document["converters"]) or "as given") if document["converted"]
             else "- Not converted: kept as given in `source/`",
             "- Counts: %s" % _counts_line(document.get("counts") or {}),
             "- Damage: %s" % _damage_line(document.get("damage") or {}),
             "- Losses: %s" % ("; ".join(document.get("losses") or []) or "none")]
    if copies:
        lines.append("- Also kept: %s (not converted: the source format is)" % ", ".join(copies))
    if document["kind"] == "inherited" and abstract and document.get("abstract"):
        lines.append("- Abstract: %s" % _clip(document["abstract"], abstract))
    headings = [heading for heading in document.get("headings") or [] if heading["level"] <= depth]
    if headings:
        lines.append("- Headings:")
        for heading in headings:
            line = "  %s- `%s#%s` %s" % ("  " * (heading["level"] - 1), document["id"], heading["locator"], heading["text"])
            if sentence and heading.get("first_sentence"):
                line += ": %s" % _clip(heading["first_sentence"], sentence)
            lines.append(line)
    elif document.get("headings"):
        lines.append("- Headings: %d, listed in `documents/%s/text.md`" % (len(document["headings"]), document["id"]))
    lines.append("")
    return lines


def render_documents(documents, max_chars=RENDER_MAX_CHARS):
    """DOCUMENTS.md: every document's kind, version, losses, counts, abstract (inherited only), and headings with locators.

    It stays at or under `max_chars`: each pass keeps less (shorter first sentences, then none,
    shorter abstracts, only the top two heading levels, then no headings) until it fits, and a
    project with more documents than even one line each allows lists as many as fit and says so.
    """
    def order(document):
        match = _ID.match(str(document.get("id")))
        return int(match.group(1)) if match else 0

    documents = sorted(documents, key=order)
    head = ["# Documents", "",
            "Rendered by code from `research/documents.json`; `wayline document add <file> --kind inherited|critique|other` "
            "keeps one. Each lives under `research/documents/<id>/`: `text.md` with a block anchor `<a id=\"pN\"></a>` before "
            "every block, `comments.json`, `citations.json` (CSL-JSON), and its tables under `tables/` as CSV. A locator "
            "`D1#p3` names block p3 of D1's `text.md`.", ""]
    if not documents:
        return "\n".join(head + ["No document is kept yet.", ""])
    for sentence, abstract, depth in _DETAIL:
        lines = list(head)
        for document in documents:
            lines += _document_lines(document, sentence, abstract, depth)
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text
    lines, shown = list(head), 0
    note = "%d more documents are in `research/documents.json`; the index is capped at %d characters."
    for document in documents:
        line = "- %s %s: %s, version %d" % (document["id"], _clip(document["title"], 80), document["kind"], document["version"])
        if len("\n".join(lines + [line, "", note % (len(documents), max_chars)])) > max_chars:
            break
        lines.append(line)
        shown += 1
    if shown < len(documents):
        lines += ["", note % (len(documents) - shown, max_chars)]
    return "\n".join(lines) + "\n"


# --- recorded tool runs, for a machine without the tools ----------------------------------------------

def _call_key(argv):
    """`(tool, input name, output dir, scratch dir)` of one tool call the conversion makes.

    The output dir is where the tool writes files (pandoc's media, LibreOffice's `.docx`, docling's
    directory), and the scratch dir the path pandoc prints media links under, or None.
    """
    argv = [str(part) for part in argv]
    tool = Path(argv[0]).name
    if len(argv) > 3 and Path(argv[1]).stem == "docling_convert":
        return "docling", Path(argv[2]).name, Path(argv[3]), None
    if tool == "soffice" and "--outdir" in argv:
        return tool, Path(argv[-1]).name, Path(argv[argv.index("--outdir") + 1]), None
    if tool == "pdftotext":
        return ("pdftotext-first-pages" if "-l" in argv else tool), Path(argv[-2]).name, None, None
    media = next((part.split("=", 1)[1] for part in argv if part.startswith("--extract-media=")), None)
    return tool, Path(argv[-1]).name, Path(media) if media else None, Path(media).parent if media else None


def recording_runner(target, run=run_tool):
    """A `run` that runs each tool for real and keeps what it printed and wrote under `target/<tool>/<input>/`.

    What `recorded_runner` replays: `stdout`, `stderr`, `returncode`, and `files/`, the files the tool
    wrote into its output directory. The scratch directory's path in the output is kept as `{work}`.
    """
    target = Path(target)

    def recording(argv, cwd=None, timeout=None, env=None):
        tool, source, outdir, work = _call_key(argv)
        done = run(argv, timeout=timeout, env=env)
        where = target / tool / source
        shutil.rmtree(where, ignore_errors=True)
        where.mkdir(parents=True)
        home = str(Path.home()).encode()
        stdout = done.stdout.replace(str(work).encode(), b"{work}") if work else done.stdout
        (where / "stdout").write_bytes(stdout.replace(home, b"~"))
        (where / "stderr").write_bytes(done.stderr.replace(home, b"~"))
        (where / "returncode").write_text("%d\n" % done.returncode, encoding="utf-8")
        if outdir is not None and outdir.is_dir():
            shutil.copytree(outdir, where / "files")
        return done

    return recording


def recorded_runner(root, missing=()):
    """A `run` that answers from `recording_runner`'s directory instead of starting anything.

    A tool named in `missing`, or one with nothing recorded for its input, answers as if it were not
    installed (exit 127). Recorded files are copied into the output directory the call names.
    """
    root, missing = Path(root), set(missing)

    def replay(argv, cwd=None, timeout=None, env=None):
        tool, source, outdir, work = _call_key(argv)
        where = root / tool / source
        if tool in missing or not where.is_dir():
            return ToolOutput(127, b"", ("%s: nothing recorded for %s" % (tool, source)).encode("utf-8"))
        if outdir is not None and (where / "files").is_dir():
            shutil.copytree(where / "files", outdir, dirs_exist_ok=True)
        stdout = (where / "stdout").read_bytes()
        if work is not None:
            stdout = stdout.replace(b"{work}", str(work).encode())
        return ToolOutput(int((where / "returncode").read_text(encoding="utf-8").strip() or 0), stdout, (where / "stderr").read_bytes())

    return replay


# --- the verb -----------------------------------------------------------------------------------------


def document_command(args):
    parser = argparse.ArgumentParser(
        prog="wayline document",
        description="keep the project's own writing as documents: converted, sorted, recorded in research/documents.json, "
                    "and indexed in research/DOCUMENTS.md")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="keep a file, a folder (sorted file by file), or a .zip (unpacked first)")
    add.add_argument("path", help="the file, folder, or .zip the owner handed over")
    add.add_argument("--kind", choices=SORTS,
                     help="the session's sort: inherited (an earlier manuscript, a separate Methods, a supplement, a thesis "
                          "chapter), critique (a referee report, an editor's letter with points, a collaborator's list of "
                          "required experiments), other (read only), or reference (a published work's PDF); without it, "
                          "code's cautious guess, which is never inherited")
    add.add_argument("--project", help="the project; the active one by default")
    add.add_argument("--json", action="store_true", help="print the results as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    from wayline.intake import IntakeError

    try:
        project = find_project(options.project)
        results = add_documents(project, options.path, kind=options.kind)
    except (DocumentError, IntakeError) as failure:
        print("wayline document: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, OSError, ValueError) as failure:
        print("wayline document: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print("%s: %s" % (result["name"], result["said"]))
    return 0
