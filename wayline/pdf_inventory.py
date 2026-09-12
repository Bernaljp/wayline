"""The inventory of a PDF without source (Implementation Decisions 9, non-arXiv PDFs).

An arXiv paper is inventoried off its LaTeX (`wayline.dossier.build_inventory`). Everything else
arrives as a PDF, and a PDF stores no sections, no equation numbers, and no figure captions as
such, only glyphs on pages. This module builds the same `inventory.json` from one as far as the
tools allow, and marks every field a reader has to confirm.

Two layers, in the order research-notes 06 Section 1 gives them:

- **The always-on layer** runs on every PDF, in seconds, with no model: `pdfinfo` for the page
  count, `pdftotext -layout` for the text layer, `pdfimages -list` for the embedded images, and
  pdfplumber (from the tools venv, or skipped with a note) for word and character boxes and ruled
  tables. These are exact, and they are what the converters' output is checked against.
- **The converters** read structure off the page with layout models: docling first (typed items
  with page and bbox, pictures and tables to PNG, formula enrichment on the GPU), marker and then
  MinerU when docling fails on a document, and GROBID for the structured references and the
  header metadata. They live in the optional tools venv of `wayline tools install` and the
  harness only ever runs them as subprocesses; a missing one records `converter: none` and the
  reader pass has more to do.

Every field a converter filled carries `provenance: "<tool>-<version>"` and keeps the page and
the bbox, so a reader can look at the crop (`pdftoppm -r 150 -f P -l P`). Equation LaTeX from a
converter is OCR-derived and marked so; equation numbers are recovered by regex from an adjacent
`(N)`; algorithms and theorems are found by the heading regex of the spec with their boundaries
left to a reader; appendices are found by the header regex.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import namedtuple
from html.parser import HTMLParser
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.jsonschema import check, load_schema
from wayline.ledger import ledger_for, now_ts

__all__ = [
    "Run", "run_tool", "TOOLS", "TOOLS_JSON", "tools_home", "Tools", "CONVERTERS_DIR",
    "poppler_version", "parse_pdfinfo", "split_pages", "parse_pdfimages_list", "always_on_layer",
    "summarize_boxes", "heading_number", "is_appendix_heading", "environment_heading",
    "equation_number", "caption_number", "text_layer_environments", "record_tool_outputs",
    "recorded_runner",
]

TOOLS = "tools"
TOOLS_JSON = "tools.json"
VENV = "venv"
CONVERTERS_DIR = HARNESS_ROOT / "converters"
TOOL_TIMEOUT_S = 120
# A converter reads a whole paper with layout models; the first run also downloads them.
CONVERTER_TIMEOUT_S = 3600

Run = namedtuple("Run", "returncode stdout stderr")
"""What one subprocess left: the exit code and its two streams as bytes. 127 is "not found"."""


def run_tool(argv, cwd=None, timeout=TOOL_TIMEOUT_S):
    """The one place this module starts a process; tests replace it with `recorded_runner`."""
    try:
        done = subprocess.run([str(part) for part in argv], cwd=str(cwd) if cwd else None,
                              capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as failure:
        return Run(127, b"", str(failure).encode("utf-8"))
    except subprocess.TimeoutExpired:
        return Run(124, b"", ("%s did not finish in %d s" % (Path(str(argv[0])).name, timeout)).encode("utf-8"))
    except (OSError, subprocess.SubprocessError) as failure:
        return Run(126, b"", str(failure).encode("utf-8"))
    return Run(done.returncode, done.stdout, done.stderr)


def _text(data):
    return (data or b"").decode("utf-8", errors="replace")


def _failure(run):
    """One line saying why a run failed, for a note."""
    lines = [line.strip() for line in _text(run.stderr).splitlines() if line.strip()]
    return "exit %d%s" % (run.returncode, (": " + lines[-1][:240]) if lines else "")


# --- the tools venv ------------------------------------------------------------------------------


def tools_home():
    """`~/.wayline/tools/`, moved with `WAYLINE_HOME` like every per-machine pointer."""
    from wayline.project import home

    return home() / TOOLS


class Tools:
    """What `wayline tools install` put on this machine, read from `~/.wayline/tools/tools.json`.

    The record is the authority on versions: a converter's provenance names the version the
    install recorded, and the venv's Python is what runs the helper scripts in `converters/`.
    """

    def __init__(self, root=None, record=None):
        self.root = Path(root) if root is not None else tools_home()
        self.record = record if record is not None else self._read()

    def _read(self):
        try:
            value = json.loads((self.root / TOOLS_JSON).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @property
    def python(self):
        """The venv's interpreter, or None when there is no venv that still runs."""
        path = self.root / VENV / "bin" / "python"
        return path if self.record and path.exists() else None

    def version(self, package):
        return (self.record.get("packages") or {}).get(package)

    def has(self, package):
        return self.python is not None and bool(self.version(package))

    def docker_image(self, name):
        return (self.record.get("docker_images") or {}).get(name)

    def device(self):
        """The device the install found torch able to use: cuda, cpu, or None when it was not asked."""
        return self.record.get("device")


# --- the always-on layer: poppler ----------------------------------------------------------------

_POPPLER_VERSION = re.compile(r"version\s+([0-9][0-9.]*)")
_PDFINFO_LINE = re.compile(r"^([A-Za-z][A-Za-z ]*?):\s*(.*)$")


def poppler_version(run=run_tool):
    """`24.02.0`, out of `pdfinfo -v` (poppler prints its version on stderr); None when absent."""
    done = run(["pdfinfo", "-v"])
    if done.returncode == 127:
        return None
    match = _POPPLER_VERSION.search(_text(done.stderr) + _text(done.stdout))
    return match.group(1).rstrip(".") if match else "unknown"


def parse_pdfinfo(text):
    """`pdfinfo`'s key-value lines: `pages` as an integer, the rest as the strings poppler printed."""
    info = {}
    for line in str(text or "").splitlines():
        match = _PDFINFO_LINE.match(line)
        if not match:
            continue
        key = match.group(1).strip().lower().replace(" ", "_")
        info[key] = match.group(2).strip()
    if "pages" in info:
        try:
            info["pages"] = int(info["pages"])
        except ValueError:
            info["pages"] = None
    return info


def split_pages(text):
    """The text layer page by page: `pdftotext` ends every page with a form feed."""
    pages = str(text or "").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def parse_pdfimages_list(text):
    """The rows of `pdfimages -list`: one per image object drawn on a page.

    The columns are poppler's: page, num, type, width, height, color, comp, bpc, enc, interp,
    object, ID, x-ppi, y-ppi, size, ratio. A `smask` or `stencil` row is the transparency of the
    image before it rather than an image of its own, and is kept apart in `type`.
    """
    rows = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) < 16 or not parts[0].isdigit():
            continue
        rows.append({
            "page": int(parts[0]), "num": int(parts[1]), "type": parts[2],
            "width": _int(parts[3]), "height": _int(parts[4]), "color": parts[5], "enc": parts[8],
            "x_ppi": _int(parts[12]), "y_ppi": _int(parts[13]), "size": parts[14],
        })
    return rows


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_SIZE = re.compile(r"^([0-9.]+)([BKMG])$")
_SIZE_UNITS = {"B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}


def _size_bytes(size):
    match = _SIZE.match(str(size or ""))
    return int(float(match.group(1)) * _SIZE_UNITS[match.group(2)]) if match else None


def always_on_layer(pdf, workspace, tools=None, run=run_tool):
    """The poppler layer and pdfplumber over one PDF: what every PDF gets, converters or not.

    Returns a dict with `poppler` (the version, None when poppler is absent), `info`, `text`,
    `pages` (the text split per page), `images` (the `pdfimages -list` rows), `boxes` (the
    pdfplumber dump, None when it did not run), `plumber_version`, and `notes`. Nothing here
    writes under `research/`; the caller hands the ledger what is to be kept.
    """
    pdf, workspace = Path(pdf), Path(workspace)
    tools = tools if tools is not None else Tools()
    layer = {"poppler": poppler_version(run), "info": {}, "text": None, "pages": [], "images": [],
             "boxes": None, "plumber_version": None, "notes": []}
    if layer["poppler"] is None:
        layer["notes"].append("poppler is not installed, so there is no page count, text layer, or image list; "
                              "install poppler-utils, which every other layer is checked against")
    else:
        info = run(["pdfinfo", pdf])
        if info.returncode == 0:
            layer["info"] = parse_pdfinfo(_text(info.stdout))
        else:
            layer["notes"].append("pdfinfo could not read the PDF (%s)" % _failure(info))
        text = run(["pdftotext", "-layout", pdf, "-"])
        if text.returncode == 0:
            layer["text"] = _text(text.stdout)
            layer["pages"] = split_pages(layer["text"])
            if not "".join(layer["pages"]).strip():
                layer["notes"].append("the PDF has no text layer (a scan); every text field needs OCR, which only a converter does")
        else:
            layer["notes"].append("pdftotext could not read the PDF (%s)" % _failure(text))
        images = run(["pdfimages", "-list", pdf])
        if images.returncode == 0:
            layer["images"] = parse_pdfimages_list(_text(images.stdout))
        else:
            layer["notes"].append("pdfimages could not list the images (%s)" % _failure(images))

    if tools.has("pdfplumber"):
        out = workspace / "pdfplumber.json"
        done = run([tools.python, CONVERTERS_DIR / "pdfplumber_dump.py", pdf, out], timeout=CONVERTER_TIMEOUT_S)
        dumped = _read_json_file(out) if done.returncode == 0 else None
        if dumped is None:
            layer["notes"].append("pdfplumber did not run (%s); there are no word or character boxes and no ruled tables" % _failure(done))
        else:
            layer["boxes"] = dumped
            layer["plumber_version"] = dumped.get("version") or tools.version("pdfplumber")
    else:
        layer["notes"].append(
            "pdfplumber is not in the tools venv (wayline tools install puts it there), so the word and "
            "character boxes and the ruled tables were skipped"
        )
    return layer


def _read_json_file(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def summarize_boxes(boxes):
    """How much the pdfplumber dump holds: pages, words, characters, and ruled tables."""
    pages = (boxes or {}).get("pages") or []
    return {
        "pages": len(pages),
        "words": sum(len(page.get("words") or []) for page in pages),
        "chars": sum(len(page.get("chars") or []) for page in pages),
        "ruled_tables": sum(len(page.get("tables") or []) for page in pages),
    }


# --- the regexes of research-notes 06 ----------------------------------------------------------

# "3", "3.2", "3.2.1", "A.1", or a lone letter; a trailing dot is a style, not part of the number.
_HEADING_NUMBER = re.compile(r"^\s*(?P<number>\d{1,2}(?:\.\d{1,2}){0,3}|[A-Z](?:\.\d{1,2}){1,3}|[A-Z])\.?\s+(?P<title>\S.*)$")
_APPENDIX_HEADING = re.compile(
    r"^\s*(?:appendix|appendices|supplementary\s+(?:material|information|note|methods?|text)s?|online\s+methods?\s+appendix)\b",
    re.IGNORECASE,
)
# The spec's heading regex, verbatim: `^(Algorithm|Theorem|Lemma|Proposition|Definition|Corollary)\s+\d`.
ENVIRONMENT_HEADING = re.compile(r"^(Algorithm|Theorem|Lemma|Proposition|Definition|Corollary)\s+\d")
_ENVIRONMENT_NUMBER = re.compile(r"^(?:Algorithm|Theorem|Lemma|Proposition|Definition|Corollary)\s+(\d+(?:\.\d+)*)")
# An equation's number as a document prints it at the right of the display: (3), (3a), (A.2), (S1).
_EQUATION_NUMBER = re.compile(r"\(\s*((?:[A-Z]\.?|S)?\d{1,3}[a-z]?)\s*\)\s*[.,;]?\s*$")
_EQUATION_NUMBER_ALONE = re.compile(r"^\s*\(\s*((?:[A-Z]\.?|S)?\d{1,3}[a-z]?)\s*\)\s*$")
_CAPTION_NUMBER = re.compile(
    r"^\s*(?:Supplementary\s+|Extended\s+Data\s+)?(?P<word>Figure|Fig\.?|Table|Tab\.?)\s*(?P<number>[A-Z]?\d+[a-z]?|[IVXLC]+)\b",
    re.IGNORECASE,
)
_COLUMN_GAP = re.compile(r"\s{3,}")


def heading_number(title, in_appendix=False):
    """`(number, title)` for a heading's text, or `(None, title)` when it carries no number.

    A lone capital letter is only a number in the appendix ("B Proofs"), because "A Simple
    Model" is a title everywhere else; a letter with a dot or a subsection ("A.", "A.2") is a
    number anywhere.
    """
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    match = _HEADING_NUMBER.match(text)
    if match is None:
        return None, text
    number = match.group("number")
    if re.fullmatch(r"[A-Z]", number) and not in_appendix and not re.match(r"^\s*[A-Z]\.\s", text):
        return None, text
    return number, match.group("title").strip()


def is_appendix_heading(title, number=None):
    """Whether a heading opens or sits in an appendix: `Appendix ...`, or a lettered number."""
    if _APPENDIX_HEADING.match(str(title or "")):
        return True
    return bool(number) and bool(re.match(r"^[A-Z](?:\.\d+)*$", number))


def environment_heading(text):
    """`(kind, word, number)` when a line opens an algorithm or a theorem-like block, else None."""
    line = str(text or "").strip()
    if not ENVIRONMENT_HEADING.match(line):
        return None
    word = line.split()[0]
    number = _ENVIRONMENT_NUMBER.match(line)
    return ("algorithm" if word == "Algorithm" else "theorem", word.lower(), number.group(1) if number else None)


def equation_number(text):
    """The `(N)` a display ends with, which is where a PDF keeps an equation's number; else None."""
    match = _EQUATION_NUMBER.search(str(text or ""))
    return match.group(1).replace(" ", "") if match else None


def equation_number_alone(text):
    """The number when a text item is nothing but `(N)`, which is how a converter splits one off."""
    match = _EQUATION_NUMBER_ALONE.match(str(text or ""))
    return match.group(1).replace(" ", "") if match else None


def caption_number(text):
    """`(word, number)` for a caption's "Figure 3:" or "Table II", else None."""
    match = _CAPTION_NUMBER.match(str(text or ""))
    if match is None:
        return None
    word = match.group("word").lower().rstrip(".")
    return ("table" if word.startswith("tab") else "figure"), match.group("number")


_HEADING_WORD = re.compile(r"(?<!\S)(Algorithm|Theorem|Lemma|Proposition|Definition|Corollary)\s+\d")
# What follows a heading's number when it is a heading and not a mention: "Lemma 1." "Theorem 2 (Name)"
# "Algorithm 1 Do nothing"; a mention runs on in lower case ("Lemma 1 is left to the reader").
_HEADING_TAIL = re.compile(r"\s+\d+(?:\.\d+)*\s*(?:[.:(]|[A-Z])")
_COLUMN_START = re.compile(r"\s{2,}(?=\S)")


def text_layer_environments(pages, filename="text.txt"):
    """Algorithms and theorems found by the heading regex in the `pdftotext -layout` text.

    A two-column page sets both columns on one line, and a justified left column runs to within
    one space of the right one: "...which is the point. The Lemma 1. Some tiny papers..." is one
    line with a heading in its second column, which the spec's `^` cannot see. (Plain `pdftotext`
    is no better: it joins the columns wherever they share a baseline.) So a heading is taken
    where it opens its line, by the spec's regex as written, and also in the middle of a line when
    it starts at a column the page's other lines start a column at and is set like a heading
    rather than mentioned in a sentence.

    Returns items with a `text.txt:<line>` locator and the page; their boundaries are always a
    reader's to confirm, because nothing in a text layer says where a theorem ends.
    """
    found, first_line = [], 1
    for page_number, page in enumerate(pages, start=1):
        lines = page.split("\n")
        starts = _column_starts(lines)
        for index, line in enumerate(lines):
            opens_at = len(line) - len(line.lstrip())
            for match in _HEADING_WORD.finditer(line):
                position = match.start()
                fragment = line[position:]
                if position != opens_at:
                    at_a_column = any(abs(position - start) <= 2 for start in starts)
                    if not at_a_column or not _HEADING_TAIL.match(fragment, len(match.group(1))):
                        continue
                heading = environment_heading(fragment)
                if heading is None:
                    continue
                kind, word, number = heading
                title = _COLUMN_GAP.split(fragment.strip())[0]
                found.append({"kind": kind, "environment": word, "number": number, "title": title[:300],
                              "page": page_number, "locator": "%s:%d" % (filename, first_line + index)})
        first_line += len(lines) - 1
    return found


def _column_starts(lines):
    """The character columns at which at least two lines of a page start a second column of text."""
    width = max((len(line) for line in lines), default=0)
    counts = {}
    for line in lines:
        for match in _COLUMN_START.finditer(line):
            column = match.end()
            if column >= width * 0.25:
                counts[column] = counts.get(column, 0) + 1
    return {column for column, count in counts.items() if count >= 2}


# --- recorded tool outputs, for a machine without the tools ----------------------------------------

_RECORDED_POPPLER = {"pdfinfo": "pdfinfo.txt", "pdftotext": "pdftotext.txt", "pdfimages": "pdfimages.txt"}


def record_tool_outputs(pdf, target, tools=None, run=run_tool):
    """Run every tool this machine has on `pdf` and keep what each one printed or wrote under `target`.

    What `recorded_runner` replays: `pdfinfo-v.txt`, `pdfinfo.txt`, `pdftotext.txt`,
    `pdfimages.txt`, `pdfplumber.json`, and `docling/` (the converter's output directory, as
    `converters/docling_convert.py` leaves it). Returns one line per tool saying what happened.
    """
    pdf, target = Path(pdf), Path(target)
    tools = tools if tools is not None else Tools()
    target.mkdir(parents=True, exist_ok=True)
    lines = []
    version = run(["pdfinfo", "-v"])
    if version.returncode == 127:
        lines.append("poppler: not installed, nothing recorded")
    else:
        (target / "pdfinfo-v.txt").write_bytes(version.stderr + version.stdout)
        for name, argv in (("pdfinfo.txt", ["pdfinfo", pdf]), ("pdftotext.txt", ["pdftotext", "-layout", pdf, "-"]),
                           ("pdfimages.txt", ["pdfimages", "-list", pdf])):
            done = run(argv)
            (target / name).write_bytes(done.stdout)
            lines.append("%s: exit %d, %d bytes" % (name, done.returncode, len(done.stdout)))
    if tools.has("pdfplumber"):
        done = run([tools.python, CONVERTERS_DIR / "pdfplumber_dump.py", pdf, target / "pdfplumber.json"], timeout=CONVERTER_TIMEOUT_S)
        lines.append("pdfplumber: %s" % ("recorded" if done.returncode == 0 else _failure(done)))
    else:
        lines.append("pdfplumber: not in the tools venv, nothing recorded")
    if tools.has("docling"):
        out = target / "docling"
        shutil.rmtree(out, ignore_errors=True)
        done = run([tools.python, CONVERTERS_DIR / "docling_convert.py", pdf, out], timeout=CONVERTER_TIMEOUT_S)
        lines.append("docling: %s" % ("recorded" if done.returncode == 0 else _failure(done)))
    else:
        lines.append("docling: not in the tools venv, nothing recorded")
    return lines


def recorded_runner(root, missing=()):
    """A `run` that answers from `record_tool_outputs`' directory instead of starting anything.

    A tool named in `missing` answers as if it were not installed (exit 127), which is how a test
    runs the chain on a machine with poppler but without a converter, or the other way round.
    The helper scripts are recognized by their file name and "write" their output by copying the
    recorded file or directory to the path the chain asked for.
    """
    root = Path(root)
    missing = set(missing)

    def run(argv, cwd=None, timeout=None):
        argv = [str(part) for part in argv]
        name = Path(argv[0]).name
        if name in _RECORDED_POPPLER or name == "pdfinfo":
            if name in missing:
                return Run(127, b"", ("%s: not found" % name).encode("utf-8"))
            if argv[1:] == ["-v"]:
                return Run(0, b"", _read_bytes(root / "pdfinfo-v.txt"))
            return Run(0, _read_bytes(root / _RECORDED_POPPLER[name]), b"")
        script = Path(argv[1]).stem if len(argv) > 1 else ""
        if script == "pdfplumber_dump":
            if "pdfplumber" in missing or not (root / "pdfplumber.json").is_file():
                return Run(1, b"", b"ModuleNotFoundError: No module named 'pdfplumber'")
            shutil.copyfile(root / "pdfplumber.json", argv[3])
            return Run(0, b"", b"")
        if script in _CONVERTER_SCRIPTS:
            tool = _CONVERTER_SCRIPTS[script]
            recorded = root / tool
            if tool in missing or not recorded.is_dir():
                return Run(1, b"", ("%s failed on this document" % tool).encode("utf-8"))
            shutil.copytree(recorded, argv[3], dirs_exist_ok=True)
            return Run(0, b"", b"")
        return Run(127, b"", ("%s: nothing recorded" % name).encode("utf-8"))

    return run


_CONVERTER_SCRIPTS = {"docling_convert": "docling", "marker_convert": "marker", "mineru_convert": "mineru", "grobid_convert": "grobid"}


def _read_bytes(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def _environment_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


# --- items shared by every converter --------------------------------------------------------------

ITEM_KEYS = ("sections", "appendices", "equations", "figures", "tables", "algorithms", "theorems")
_PREFIXES = {"sections": "sec", "appendices": "app", "equations": "eq", "figures": "fig", "tables": "tab",
             "algorithms": "alg", "theorems": "thm"}
_SECTION_WORDS = re.compile(r"^(abstract|introduction|background|methods?|results|discussion|conclusions?|references|bibliography|acknowledge?ments?)\b", re.IGNORECASE)
_REFERENCES_HEADING = re.compile(r"^\s*(references|bibliography|literature cited|works cited)\s*$", re.IGNORECASE)


def _tidy(value, limit=2000):
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", str(value)).strip()
    return collapsed[:limit] if len(collapsed) > limit else collapsed


def _locator(pdf_name, page):
    """`source/paper.pdf#page=3`: a PDF open parameter a viewer follows to the page."""
    return "%s#page=%d" % (pdf_name, page) if page else pdf_name


def new_record():
    record = {key: [] for key in ITEM_KEYS}
    record["notes"] = []
    record["title"] = None
    record["counts"] = {}
    return record


def _add(record, bucket, item):
    item["id"] = "%s-%d" % (_PREFIXES[bucket], len(record[bucket]) + 1)
    record[bucket].append({key: value for key, value in item.items() if value is not None and value != []})
    return record[bucket][-1]


def _join_numbers(numbers):
    """One string for several numbers: a range when they run in sequence, a list otherwise."""
    numbers = [number for number in numbers if number]
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    if all(number.isdigit() for number in numbers) and int(numbers[-1]) - int(numbers[0]) == len(numbers) - 1:
        return "%s-%s" % (numbers[0], numbers[-1])
    return ", ".join(numbers)


class Headings:
    """The numbering state a reading of the headings carries: whether the appendix has begun.

    A converter's layout model says an item is a heading and nothing about its number or its
    level, so both come from the heading's own text: "3.2 Results" is a level-2 section numbered
    3.2, "Appendix" or a lettered number opens the appendix, and once a paper has numbered its
    sections with digits, a heading that starts with a lone "A" is appendix A.
    """

    def __init__(self):
        self.in_appendix = False
        self.numbered = False
        self.after_references = False

    def read(self, text, converter_level=None):
        text = _tidy(text) or ""
        number, title = heading_number(text, self.in_appendix)
        if number is None and self.numbered and re.match(r"^A\s+\S", text):
            number, title = heading_number(text, True)
        if number and number[0].isdigit():
            self.numbered = True
        if is_appendix_heading(title, number if number and not number[0].isdigit() else None):
            self.in_appendix = True
        references = bool(_REFERENCES_HEADING.match(title))
        if references:
            self.after_references = True
        if number:
            level = number.count(".") + 1
        else:
            level = converter_level if isinstance(converter_level, int) and 1 <= converter_level <= 6 else 1
        # The bibliography is part of the paper whichever side of the appendix a class sets it on.
        return {"number": number, "title": title, "level": min(level, 6), "appendix": self.in_appendix and not references}


def _environment_item(text, page, bbox, locator, provenance):
    heading = environment_heading(text)
    if heading is None:
        return None
    kind, word, number = heading
    return kind, {"kind": kind, "environment": word, "number": number, "title": _tidy(text, 300), "page": page,
                  "bbox": bbox, "locator": locator, "provenance": provenance, "confirm": True,
                  "confirm_fields": ["boundary"]}


# --- docling --------------------------------------------------------------------------------------

_DOCLING_TEXT_LABELS = frozenset(["text", "paragraph", "code", "list_item", "caption", "footnote", "formula", "section_header", "title"])


def _resolve(document, reference):
    """`#/texts/12` to the item it names, or None."""
    parts = str((reference or {}).get("$ref") or "").lstrip("#/").split("/")
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    items = document.get(parts[0]) or []
    index = int(parts[1])
    return items[index] if index < len(items) else None


def _docling_walk(document):
    """Every item the body reaches, in reading order; a picture's or a table's own children are not text of the page."""
    out, stack, seen = [], list(reversed((document.get("body") or {}).get("children") or [])), set()
    while stack:
        reference = stack.pop()
        key = (reference or {}).get("$ref")
        if key in seen:
            continue
        seen.add(key)
        item = _resolve(document, reference)
        if item is None:
            continue
        out.append(item)
        if key.startswith("#/groups/") or key.startswith("#/body"):
            stack.extend(reversed(item.get("children") or []))
    return out


def _docling_bbox(item, pages):
    """The first provenance's page and its bbox as `[x0, top, x1, bottom]` in points from the top left."""
    prov = (item.get("prov") or [None])[0]
    if not prov:
        return None, None
    page = prov.get("page_no")
    box = prov.get("bbox") or {}
    try:
        left, right = float(box["l"]), float(box["r"])
        top, bottom = float(box["t"]), float(box["b"])
    except (KeyError, TypeError, ValueError):
        return page, None
    if str(box.get("coord_origin", "")).upper() == "BOTTOMLEFT":
        height = float(((pages or {}).get(str(page)) or {}).get("size", {}).get("height") or 0)
        if height:
            top, bottom = height - top, height - bottom
    return page, [round(left, 1), round(min(top, bottom), 1), round(right, 1), round(max(top, bottom), 1)]


def docling_items(document, meta, pdf_name="source/paper.pdf"):
    """The inventory items of a `DoclingDocument`, with what a reader must confirm marked on each.

    `meta` is what `converters/docling_convert.py` wrote beside it: the version, whether formula
    enrichment ran, and the image file of each picture and table. Returns a record with the item
    lists, `title` (the first page's unnumbered opening heading, which docling calls a section),
    `images` (item id to the converter's image file), `counts`, and `notes`.
    """
    provenance = "docling-%s" % (meta.get("version") or "unknown")
    enriched = bool(meta.get("formula_enrichment"))
    pages = document.get("pages") or {}
    record = new_record()
    record["images"] = {}
    headings = Headings()
    walked = _docling_walk(document)
    boxes = {}
    for item in walked:
        boxes[item.get("self_ref")] = _docling_bbox(item, pages)
    linked_captions = set()
    for item in walked:
        for reference in item.get("captions") or []:
            linked_captions.add(reference.get("$ref"))

    pictures = [boxes.get(item.get("self_ref")) for item in walked if str(item.get("self_ref", "")).startswith("#/pictures/")]
    numbered_paper = sum(1 for item in walked if item.get("label") == "section_header"
                         and (heading_number(_tidy(item.get("text")))[0] or "")[:1].isdigit()) >= 3
    first_heading, inside_figures, figure_tables = True, 0, 0
    pending_captions = []  # (kind, number, text item) of captions no picture or table linked
    for item in walked:
        label = item.get("label")
        ref = item.get("self_ref") or ""
        page, bbox = boxes.get(ref) or (None, None)
        locator = _locator(pdf_name, page)
        text = _tidy(item.get("text"))
        if ref.startswith("#/pictures/"):
            caption = _captions(document, item)
            figure = _add(record, "figures", {
                "kind": "figure", "number": (caption_number(caption) or (None, None))[1] if caption else None,
                "caption": caption, "page": page, "bbox": bbox, "locator": locator, "provenance": provenance,
                "confirm": True, "confirm_fields": ["meaning"],
            })
            if meta.get("images", {}).get(ref):
                record["images"][figure["id"]] = meta["images"][ref]
            continue
        if ref.startswith("#/tables/"):
            caption = _captions(document, item)
            if caption and (caption_number(caption) or ("",))[0] == "figure":
                # A panel of numbers set as a figure ("Fig. 10 Comparison with...") is a figure the
                # table model recognized; the caption is the document's own word for what it is.
                figure_tables += 1
                figure = _add(record, "figures", {
                    "kind": "figure", "number": caption_number(caption)[1], "caption": caption, "cells": _docling_cells(item),
                    "page": page, "bbox": bbox, "locator": locator, "provenance": provenance,
                    "confirm": True, "confirm_fields": ["meaning"],
                })
                if meta.get("images", {}).get(ref):
                    record["images"][figure["id"]] = meta["images"][ref]
                continue
            table = _add(record, "tables", {
                "kind": "table", "number": (caption_number(caption) or (None, None))[1] if caption else None,
                "caption": caption, "cells": _docling_cells(item), "page": page, "bbox": bbox,
                "locator": locator, "provenance": provenance,
            })
            if meta.get("images", {}).get(ref):
                record["images"][table["id"]] = meta["images"][ref]
            continue
        if label not in _DOCLING_TEXT_LABELS or not text:
            continue
        if label in ("section_header", "title"):
            # The title first: it is often set just above a first-page figure, which is where the
            # figure-label rule below would otherwise claim it.
            if (first_heading and page == 1 and (label == "title" or not heading_number(text)[0])
                    and not _SECTION_WORDS.match(text) and not _inside_any(page, bbox, pictures)):
                record["title"] = text
                first_heading = False
                continue
            # A label drawn inside a figure, or set just above a panel ("Input-Input Layer5"), is not a
            # heading of the paper. Near a figure only counts in a paper that numbers its headings and
            # for an unnumbered heading that is none of the usual unnumbered ones, because a paper whose
            # headings carry no numbers sets "Results" wherever the figure above it ends.
            if label == "section_header" and (_inside_any(page, bbox, pictures) or (
                    numbered_paper and not heading_number(text)[0] and not _UNNUMBERED_HEADINGS.match(text)
                    and _near_any(page, bbox, pictures, FIGURE_LABEL_MARGIN))):
                inside_figures += 1
                continue
            first_heading = False
            heading = headings.read(text, item.get("level"))
            bucket = "appendices" if heading["appendix"] else "sections"
            _add(record, bucket, {
                "kind": "appendix" if heading["appendix"] else "section", "number": heading["number"],
                "title": heading["title"], "level": heading["level"], "page": page, "bbox": bbox,
                "locator": locator, "provenance": provenance,
            })
            continue
        if label == "formula":
            orig = _tidy(item.get("orig"))
            latex = text if enriched and text and text != orig else None
            numbers = [equation_number(orig)] if equation_number(orig) else latex_equation_numbers(text)
            if not numbers:
                numbers = _numbers_beside(walked, boxes, page, bbox)
            _add(record, "equations", {
                "kind": "equation", "number": _join_numbers(numbers), "latex": latex, "page": page, "bbox": bbox,
                "locator": locator, "provenance": provenance, "ocr": bool(latex), "confirm": True,
                "confirm_fields": ["latex", "number"] if latex else ["number"],
            })
            continue
        if label == "caption" and ref not in linked_captions:
            found = caption_number(text)
            if found:
                pending_captions.append((found, text, page, bbox))
        environment = _environment_item(text, page, bbox, locator, provenance)
        if environment is not None:
            kind, entry = environment
            _add(record, "algorithms" if kind == "algorithm" else "theorems", entry)

    _attach_unlinked_captions(record, pending_captions)
    folded, dropped = _fold_small_pictures(record, pages)
    if dropped:
        record["notes"].append(
            "%d picture(s) smaller than %d%% of their page, with no caption and no captioned figure on the page "
            "(a journal badge, a logo), are not inventoried as figures" % (dropped, int(SMALL_PICTURE * 100))
        )
    if not enriched:
        record["notes"].append("docling ran without formula enrichment, so no equation carries LaTeX; a reader types each one out")
    record["counts"] = {
        "headings": len(record["sections"]) + len(record["appendices"]),
        "figures_with_caption": len([item for item in record["figures"] if item.get("caption")]),
        "tables_with_caption": len([item for item in record["tables"] if item.get("caption")]),
        "numbered_equations": len([item for item in record["equations"] if item.get("number")]),
        "reference_list_items": _reference_list_items(walked),
        "headings_inside_figures": inside_figures,
        "tables_captioned_as_figures": figure_tables,
        "pictures_folded_into_figures": folded,
        "small_pictures_left_out": dropped,
    }
    return record


# An uncaptioned picture under this share of its page is a panel of a figure or a badge, not a figure.
SMALL_PICTURE = 0.02


def _fold_small_pictures(record, pages):
    """Small uncaptioned pictures: folded into the captioned figure on their page, else left out.

    A layout model cuts a two-panel figure into two pictures and links the caption to one of them,
    and it finds the journal's badges and logos on the first page. The first is still one figure,
    so its bbox grows to cover the panel the caption did not reach; the second is not a figure at
    all. Only a picture with no caption and under `SMALL_PICTURE` of its page is either: a large
    uncaptioned picture stays a figure for a reader to name. Returns `(folded, left out)`.
    """
    images = record["images"]
    old_images = {item["id"]: images.pop(item["id"]) for item in record["figures"] if item["id"] in images}
    kept, folded, dropped = [], 0, 0
    for item in record["figures"]:
        size = ((pages or {}).get(str(item.get("page"))) or {}).get("size") or {}
        area = float(size.get("width") or 0) * float(size.get("height") or 0)
        bbox = item.get("bbox")
        small = bool(area and bbox and not item.get("caption") and (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) < SMALL_PICTURE * area)
        if not small:
            kept.append(item)
            continue
        host = next((other for other in record["figures"] if other.get("caption") and other.get("page") == item.get("page")), None)
        if host is None:
            dropped += 1
            continue
        if host.get("bbox"):
            host["bbox"] = [min(host["bbox"][0], bbox[0]), min(host["bbox"][1], bbox[1]),
                            max(host["bbox"][2], bbox[2]), max(host["bbox"][3], bbox[3])]
        folded += 1
    record["figures"] = kept
    remembered = [(item, old_images.get(item["id"])) for item in kept]
    _renumber(record, "figures")
    for item, image in remembered:
        if image:
            images[item["id"]] = image
    return folded, dropped


_LATEX_ROW_BREAK = re.compile(r"\\\\")
_LATEX_ENVIRONMENT = re.compile(r"\\(?:begin|end)\s*\{[^}]*\}")
# OCR spaces every glyph: "( 1 2 )" is equation 12.
_LATEX_ROW_NUMBER = re.compile(r"\(\s*((?:[A-Z]\s*\.?\s*|S\s*)?(?:\d\s*){1,3}[a-z]?)\s*\)\s*[.,;]?\s*$")


def latex_equation_numbers(latex):
    """The numbers an OCR-derived display carries at the end of its rows: `\\tag{2}`, `\\quad ( 2 )`.

    A formula model reads the printed "(2)" at the right margin as part of the formula, one glyph
    at a time, so the number is found at the end of each row and its spaces are closed up.
    """
    numbers = []
    for row in _LATEX_ROW_BREAK.split(_LATEX_ENVIRONMENT.sub(" ", str(latex or ""))):
        tag = _TAG.search(row)
        match = None if tag else _LATEX_ROW_NUMBER.search(row.strip())
        found = tag.group(1) if tag else (match.group(1) if match else None)
        if found:
            numbers.append(re.sub(r"\s+", "", found))
    return numbers


def _inside_any(page, bbox, boxes):
    """Whether the centre of `bbox` falls inside any of `boxes` (`(page, bbox)` pairs) on the same page."""
    if not bbox:
        return False
    x, y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return any(other_page == page and other and other[0] <= x <= other[2] and other[1] <= y <= other[3]
               for other_page, other in (entry or (None, None) for entry in boxes))


# The headings a numbered paper leaves unnumbered on purpose.
_UNNUMBERED_HEADINGS = re.compile(
    r"^\s*(abstract|references|bibliography|acknowledge?ments?|appendi(x|ces)|supplementary|contents|keywords|"
    r"data availability|code availability|author contributions|competing interests|conflicts? of interest|funding|"
    r"additional information|ethics|broader impact|limitations|impact statement)\b",
    re.IGNORECASE,
)
# How far above or below a picture a panel's own title can sit (50 pt on the Attention paper's page 14).
FIGURE_LABEL_MARGIN = 60.0


def _near_any(page, bbox, boxes, margin):
    """Whether `bbox` overlaps one of `boxes` horizontally and lies within `margin` points of it vertically."""
    if not bbox:
        return False
    for other_page, other in (entry or (None, None) for entry in boxes):
        if other_page != page or not other or bbox[2] < other[0] or bbox[0] > other[2]:
            continue
        gap = max(other[1] - bbox[3], bbox[1] - other[3], 0)
        if gap <= margin:
            return True
    return False


def _title_key(title):
    return re.sub(r"[^a-z0-9]", "", str(title or "").lower())[:60]


def _renumber(record, bucket):
    for index, item in enumerate(record[bucket], start=1):
        item["id"] = "%s-%d" % (_PREFIXES[bucket], index)


def _captions(document, item):
    texts = [_tidy((_resolve(document, reference) or {}).get("text")) for reference in item.get("captions") or []]
    joined = " ".join(text for text in texts if text)
    return joined or None


def _docling_cells(item):
    grid = ((item.get("data") or {}).get("grid")) or []
    return [[_tidy(cell.get("text")) if isinstance(cell, dict) else None for cell in row] for row in grid]


def _numbers_beside(walked, boxes, page, bbox):
    """Equation numbers docling split off a display: `(N)` text to the right of it, level with it.

    A multi-row display keeps one bbox for all its rows, so every `(N)` that starts a text item
    overlapping the display's height is one of its numbers, top to bottom. docling sometimes
    glues the number to the paragraph of the next column ("(3) The proof of..."), which is why the
    number is read off the start of the text rather than required to be the whole of it.
    """
    if not bbox:
        return []
    found = []
    for item in walked:
        if item.get("label") == "formula":
            continue
        other_page, other = boxes.get(item.get("self_ref")) or (None, None)
        if other_page != page or not other:
            continue
        if other[0] < bbox[0] or other[3] < bbox[1] or other[1] > bbox[3]:
            continue
        match = re.match(r"^\s*\(\s*((?:[A-Z]\.?|S)?\d{1,3}[a-z]?)\s*\)", item.get("text") or "")
        if match:
            found.append((other[1], match.group(1)))
    return [number for _, number in sorted(found)]


def _attach_unlinked_captions(record, pending):
    """A caption the converter found but tied to nothing goes to the nearest captionless figure or table on its page.

    This is the caption-splitting failure mode: the layout model sees both the picture and the
    caption and does not link them. The caption is attached by page and distance, and the item
    says a reader must confirm it.
    """
    for (kind, number), text, page, bbox in pending:
        bucket = "tables" if kind == "table" else "figures"
        candidates = [item for item in record[bucket] if not item.get("caption") and item.get("page") == page]
        if not candidates:
            record["notes"].append("a %s caption on page %s matched no %s: %s" % (kind, page, kind, _tidy(text, 120)))
            continue
        target = min(candidates, key=lambda item: _distance(item.get("bbox"), bbox))
        target["caption"] = text
        target["number"] = number
        target["confirm"] = True
        target["confirm_fields"] = sorted(set(target.get("confirm_fields") or []) | {"caption"})


def _distance(one, other):
    if not one or not other:
        return float("inf")
    return abs((one[1] + one[3]) / 2 - (other[1] + other[3]) / 2) + abs((one[0] + one[2]) / 2 - (other[0] + other[2]) / 2)


def _reference_list_items(walked):
    """List items after a References heading: what a reader or GROBID would turn into references."""
    counting, count = False, 0
    for item in walked:
        label = item.get("label")
        if label == "section_header":
            counting = bool(_REFERENCES_HEADING.match(_tidy(item.get("text")) or ""))
            continue
        if counting and label == "list_item":
            count += 1
    return count


# --- GROBID ---------------------------------------------------------------------------------------

_TEI = "{http://www.tei-c.org/ns/1.0}"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def grobid_tei(tei_text, version=None, pdf_name="source/paper.pdf"):
    """`(metadata, references)` out of GROBID's TEI: the header and every `biblStruct` of the bibliography."""
    import xml.etree.ElementTree as ElementTree

    provenance = "grobid-%s" % (version or "unknown")
    root = ElementTree.fromstring(tei_text)
    header = root.find(_TEI + "teiHeader")
    metadata = {}
    if header is not None:
        title = header.find(".//%sfileDesc/%stitleStmt/%stitle" % (_TEI, _TEI, _TEI))
        if title is not None and _tidy("".join(title.itertext())):
            metadata["title"] = _tidy("".join(title.itertext()))
        source = header.find(".//%ssourceDesc/%sbiblStruct" % (_TEI, _TEI))
        if source is not None:
            metadata["authors"] = _tei_authors(source.find(_TEI + "analytic") if source.find(_TEI + "analytic") is not None else source)
            doi = source.find(".//%sidno[@type='DOI']" % _TEI)
            if doi is not None and _tidy(doi.text):
                metadata["doi"] = _tidy(doi.text)
    references = []
    for bibl in root.iter(_TEI + "biblStruct"):
        if header is not None and _within(header, bibl):
            continue
        analytic = bibl.find(_TEI + "analytic")
        monogr = bibl.find(_TEI + "monogr")
        title = None
        for holder in (analytic, monogr):
            element = holder.find(_TEI + "title") if holder is not None else None
            if element is not None and _tidy("".join(element.itertext())):
                title = _tidy("".join(element.itertext()))
                break
        raw = bibl.find("%snote[@type='raw_reference']" % _TEI)
        doi = bibl.find(".//%sidno[@type='DOI']" % _TEI)
        date = bibl.find(".//%sdate" % _TEI)
        page = _tei_page(bibl.get("coords"))
        references.append({key: value for key, value in {
            "id": "ref-%d" % (len(references) + 1),
            "key": bibl.get(_XML_ID),
            "text": _tidy("".join(raw.itertext())) if raw is not None else None,
            "title": title,
            "authors": _tei_authors(analytic if analytic is not None else monogr),
            "year": (date.get("when") or "")[:4] or None if date is not None else None,
            "doi": _tidy(doi.text) if doi is not None else None,
            "page": page,
            "locator": _locator(pdf_name, page),
            "provenance": provenance,
        }.items() if value not in (None, [])})
    return metadata, references


def _within(ancestor, element):
    return any(candidate is element for candidate in ancestor.iter())


def _tei_authors(holder):
    if holder is None:
        return []
    names = []
    for person in holder.findall(".//%sauthor/%spersName" % (_TEI, _TEI)):
        parts = [_tidy("".join(part.itertext())) for part in person if part.tag in (_TEI + "forename", _TEI + "surname")]
        name = " ".join(part for part in parts if part)
        if name:
            names.append(name)
    return names


def _tei_page(coords):
    """The page of GROBID's first coordinate box: `page,x,y,w,h;...`."""
    first = str(coords or "").split(";")[0].split(",")[0]
    return int(first) if first.isdigit() else None


# --- marker and MinerU, the fallbacks --------------------------------------------------------------


class _HtmlText(HTMLParser):
    """The text of an HTML fragment, and the rows of the first table in it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.rows, self._row, self._cell = [], [], None, None

    def handle_starttag(self, tag, attributes):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("br", "p", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_tidy("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        self.parts.append(data)
        if self._cell is not None:
            self._cell.append(data)


def html_text(fragment):
    reader = _HtmlText()
    reader.feed(str(fragment or ""))
    return _tidy("".join(reader.parts)) or None


def html_cells(fragment):
    reader = _HtmlText()
    reader.feed(str(fragment or ""))
    return reader.rows


_MARKER_PAGE = re.compile(r"/page/(\d+)/")
_MATH = re.compile(r"<math[^>]*>(.*?)</math>", re.DOTALL)
_TAG = re.compile(r"\\tag\s*\{([^}]*)\}")


def marker_items(document, meta, pdf_name="source/paper.pdf"):
    """The inventory items of marker's JSON rendering, which is a tree of typed blocks.

    marker names a block's page in its id (`/page/0/Figure/3`, from 0) and gives a bbox in points
    from the top left. A `Caption` block follows the figure or table it belongs to among its
    siblings, which is how it is attached here; one that follows nothing waits for the nearest
    captionless item on its page and asks a reader to confirm the pairing.
    """
    provenance = "marker-%s" % (meta.get("version") or "unknown")
    record = new_record()
    record["images"] = {}
    headings = Headings()
    pending = []
    blocks = list(_marker_blocks(document))
    previous = None
    for block in blocks:
        kind = block.get("block_type")
        page = _marker_page(block)
        bbox = _points(block.get("bbox"))
        locator = _locator(pdf_name, page)
        text = html_text(block.get("html"))
        if kind in ("Figure", "Picture"):
            item = _add(record, "figures", {"kind": "figure", "page": page, "bbox": bbox, "locator": locator,
                                            "provenance": provenance, "confirm": True, "confirm_fields": ["meaning"]})
            image = (meta.get("images") or {}).get(block.get("id"))
            if image:
                record["images"][item["id"]] = image
            previous = ("figures", item)
            continue
        if kind == "Table":
            item = _add(record, "tables", {"kind": "table", "cells": html_cells(block.get("html")), "page": page,
                                           "bbox": bbox, "locator": locator, "provenance": provenance})
            previous = ("tables", item)
            continue
        if kind == "Caption" and text:
            found = caption_number(text)
            if previous is not None and not previous[1].get("caption"):
                previous[1]["caption"] = text
                previous[1]["number"] = found[1] if found else None
            elif found:
                pending.append((found, text, page, bbox))
            previous = None
            continue
        previous = None
        if kind == "SectionHeader" and text:
            heading = headings.read(text)
            _add(record, "appendices" if heading["appendix"] else "sections", {
                "kind": "appendix" if heading["appendix"] else "section", "number": heading["number"],
                "title": heading["title"], "level": heading["level"], "page": page, "bbox": bbox,
                "locator": locator, "provenance": provenance,
            })
            continue
        if kind == "Equation":
            math = _MATH.search(block.get("html") or "")
            latex = _tidy(html_text(math.group(1)) if math else text)
            tag = _TAG.search(latex or "")
            number = tag.group(1).strip() if tag else equation_number(text)
            _add(record, "equations", {"kind": "equation", "number": number, "latex": latex, "page": page, "bbox": bbox,
                                       "locator": locator, "provenance": provenance, "ocr": bool(latex), "confirm": True,
                                       "confirm_fields": ["latex", "number"] if latex else ["number"]})
            continue
        if kind in ("Text", "ListItem", "Code", "TextInlineMath") and text:
            environment = _environment_item(text, page, bbox, locator, provenance)
            if environment is not None:
                _add(record, "algorithms" if environment[0] == "algorithm" else "theorems", environment[1])
    _attach_unlinked_captions(record, pending)
    return record


def _marker_blocks(block):
    """Every block below the document in reading order; the document and page blocks hold, they are not items."""
    for child in (block or {}).get("children") or []:
        if child.get("block_type") not in ("Page", "Document", "FigureGroup", "TableGroup", "PictureGroup", "ListGroup"):
            yield child
        yield from _marker_blocks(child)


def _marker_page(block):
    match = _MARKER_PAGE.search(str(block.get("id") or ""))
    return int(match.group(1)) + 1 if match else None


def _points(bbox):
    try:
        return [round(float(value), 1) for value in bbox][:4] if bbox and len(bbox) >= 4 else None
    except (TypeError, ValueError):
        return None


def mineru_items(content, meta, pdf_name="source/paper.pdf"):
    """The inventory items of MinerU's `content_list`, one entry per block in reading order.

    MinerU numbers pages from 0 and, in the versions research-notes 06 read, gives each bbox on its
    own normalized scale rather than in points, so the page is kept and the bbox is not: a reader
    opens the page. Captions arrive attached to their image or table, which spares the pairing.
    """
    provenance = "mineru-%s" % (meta.get("version") or "unknown")
    record = new_record()
    record["images"] = {}
    headings = Headings()
    for index, entry in enumerate(content if isinstance(content, list) else []):
        kind = entry.get("type")
        page = entry.get("page_idx") + 1 if isinstance(entry.get("page_idx"), int) else None
        locator = _locator(pdf_name, page)
        if kind == "image":
            caption = _tidy(" ".join(entry.get("image_caption") or entry.get("img_caption") or [])) or None
            item = _add(record, "figures", {"kind": "figure", "number": (caption_number(caption) or (None, None))[1] if caption else None,
                                            "caption": caption, "page": page, "locator": locator, "provenance": provenance,
                                            "confirm": True, "confirm_fields": ["meaning"]})
            image = (meta.get("images") or {}).get(str(index))
            if image:
                record["images"][item["id"]] = image
            continue
        if kind == "table":
            caption = _tidy(" ".join(entry.get("table_caption") or [])) or None
            item = _add(record, "tables", {"kind": "table", "number": (caption_number(caption) or (None, None))[1] if caption else None,
                                           "caption": caption, "cells": html_cells(entry.get("table_body")), "page": page,
                                           "locator": locator, "provenance": provenance})
            image = (meta.get("images") or {}).get(str(index))
            if image:
                record["images"][item["id"]] = image
            continue
        text = _tidy(entry.get("text"))
        if not text:
            continue
        if kind == "equation":
            latex = text.strip("$").strip()
            tag = _TAG.search(latex)
            _add(record, "equations", {"kind": "equation", "number": tag.group(1).strip() if tag else equation_number(latex),
                                       "latex": latex, "page": page, "locator": locator, "provenance": provenance,
                                       "ocr": True, "confirm": True, "confirm_fields": ["latex", "number"]})
            continue
        if kind == "text" and entry.get("text_level"):
            heading = headings.read(text, entry.get("text_level"))
            _add(record, "appendices" if heading["appendix"] else "sections", {
                "kind": "appendix" if heading["appendix"] else "section", "number": heading["number"],
                "title": heading["title"], "level": heading["level"], "page": page, "locator": locator,
                "provenance": provenance,
            })
            continue
        environment = _environment_item(text, page, None, locator, provenance)
        if environment is not None:
            _add(record, "algorithms" if environment[0] == "algorithm" else "theorems", environment[1])
    return record


# --- running the converters -----------------------------------------------------------------------

REFS = "refs"
SOURCE = "source"
FIGURES = "figures"
INVENTORY = "inventory.json"
TEXT_LAYER = "text.txt"
BOXES = "boxes.json"
PDF_NAME = "paper.pdf"
# docling first; marker and then MinerU only when the one before failed on this document.
CONVERTER_ORDER = ("docling", "marker", "mineru")
GROBID_URL = "http://localhost:8070"
GROBID_CONTAINER = "wayline-grobid"
GROBID_START_S = 180
_PDF_MAGIC = b"%PDF"
# A converter that says it succeeded but found no heading, figure, table, or equation in a paper
# with this much text has failed on it as surely as one that exited 1.
_EMPTY_CONVERSION_CHARS = 2000


def _read_docling(out):
    document = _read_json_file(Path(out) / "document.json")
    meta = _read_json_file(Path(out) / "meta.json")
    if document is None or meta is None:
        return None, "docling left no readable document.json and meta.json"
    return docling_items(document, meta), None


def _read_marker(out):
    document = _read_json_file(Path(out) / "document.json")
    meta = _read_json_file(Path(out) / "meta.json")
    if document is None or meta is None:
        return None, "marker left no readable document.json and meta.json"
    return marker_items(document, meta), None


def _read_mineru(out):
    try:
        content = json.loads((Path(out) / "document.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        content = None
    meta = _read_json_file(Path(out) / "meta.json")
    if not isinstance(content, list) or meta is None:
        return None, "MinerU left no readable content list and meta.json"
    return mineru_items(content, meta), None


# Every converter name maps to the function that turns its output directory into a record.
READERS = {"docling": _read_docling, "marker": _read_marker, "mineru": _read_mineru}


def run_converters(pdf, workspace, tools, run=run_tool, text_chars=0):
    """docling, then marker, then MinerU, stopping at the first that reads the document.

    Returns `(record, provenance, out_dir, notes, formula_enrichment)`; the record is None and
    the provenance `none` when nothing is installed or everything installed failed. A converter
    that is not installed is noted once, so the record says which fallbacks were never there.
    """
    notes = []
    missing = [name for name in CONVERTER_ORDER if READERS.get(name) is None or not tools.has(name)]
    for name in CONVERTER_ORDER:
        reader = READERS.get(name)
        if name in missing:
            continue
        out = Path(workspace) / name
        shutil.rmtree(out, ignore_errors=True)
        argv = [tools.python, CONVERTERS_DIR / ("%s_convert.py" % name), pdf, out]
        if name == "docling":
            argv += ["--device", "auto"]
        done = run(argv, timeout=CONVERTER_TIMEOUT_S)
        if done.returncode != 0:
            notes.append("%s failed on this document (%s)" % (name, _failure(done)))
            continue
        record, problem = reader(out)
        if record is None:
            notes.append("%s ran but %s" % (name, problem))
            continue
        if text_chars > _EMPTY_CONVERSION_CHARS and not any(record[key] for key in ("sections", "appendices", "equations", "figures", "tables")):
            notes.append("%s found no heading, figure, table, or equation in %d characters of text; taken as a failure" % (name, text_chars))
            continue
        meta = _read_json_file(out / "meta.json") or {}
        version = meta.get("version") or tools.version(name) or "unknown"
        if missing:
            notes.append("not installed, so never tried: %s" % ", ".join(missing))
        return record, "%s-%s" % (name, version), out, notes, meta.get("formula_enrichment")
    if missing:
        notes.append("no structural converter %s installed (%s); wayline tools install puts docling in the tools venv"
                     % ("is" if len(missing) == len(CONVERTER_ORDER) else "else is", ", ".join(missing)))
    return None, "none", None, notes, None


def grobid_references(pdf, tools, run=run_tool, sleep=time.sleep, url=None):
    """GROBID's header metadata and structured references, when a GROBID server can be had.

    A server already answering at `WAYLINE_GROBID_URL` (default `http://localhost:8070`) is used
    as it is. Otherwise, when `wayline tools install --grobid` pulled the image, a container is
    started for this one document and stopped afterwards. The PDF goes to the server with `curl`,
    which keeps GROBID a subprocess like every other tool. Returns `(metadata, references,
    provenance, notes)`; the provenance is `none` when GROBID did not run.
    """
    url = (url or os.environ.get("WAYLINE_GROBID_URL") or tools.record.get("grobid_url") or GROBID_URL).rstrip("/")
    notes, started = [], False
    alive = run(["curl", "-sf", "--max-time", "5", url + "/api/isalive"]).returncode == 0
    image = tools.docker_image("grobid")
    if not alive and image:
        done = run(["docker", "run", "-d", "--rm", "--name", GROBID_CONTAINER, "-p", "8070:8070", image])
        if done.returncode != 0:
            notes.append("GROBID's container would not start (%s); references and metadata stay converter: none" % _failure(done))
            return {}, [], "none", notes
        started = True
        waited = 0
        while waited < GROBID_START_S:
            if run(["curl", "-sf", "--max-time", "5", url + "/api/isalive"]).returncode == 0:
                alive = True
                break
            sleep(3)
            waited += 3
    try:
        if not alive:
            notes.append(
                "GROBID is not running at %s and no image is installed (wayline tools install --grobid), so "
                "references and metadata are converter: none and the reader pass lists the references" % url
                if not image else "GROBID did not answer at %s within %d s; references and metadata stay converter: none" % (url, GROBID_START_S)
            )
            return {}, [], "none", notes
        version = _text(run(["curl", "-sf", "--max-time", "5", url + "/api/version"]).stdout).strip() or "unknown"
        done = run(["curl", "-sS", "-f", "--max-time", "600", "-F", "input=@%s" % pdf, "-F", "includeRawCitations=1",
                    "-F", "teiCoordinates=biblStruct", url + "/api/processFulltextDocument"], timeout=CONVERTER_TIMEOUT_S)
        if done.returncode != 0:
            notes.append("GROBID could not process the PDF (%s)" % _failure(done))
            return {}, [], "none", notes
        try:
            metadata, references = grobid_tei(_text(done.stdout), version)
        except Exception as failure:  # ElementTree raises its own ParseError; a malformed TEI is GROBID's problem, not a crash
            notes.append("GROBID's TEI did not parse (%s)" % failure)
            return {}, [], "none", notes
        return metadata, references, "grobid-%s" % version, notes
    finally:
        if started:
            run(["docker", "stop", GROBID_CONTAINER])


# --- one PDF's inventory --------------------------------------------------------------------------


def build_pdf_inventory(project_or_ledger, slug, pdf, tools=None, run=run_tool, source=None, sleep=time.sleep):
    """Keep one PDF under `refs/<slug>/source/` and write `refs/<slug>/inventory.json` from it.

    The always-on layer always runs; the converters run when the tools venv has them; GROBID runs
    when a server or its image is there. Nothing that is missing stops the inventory: each field
    says what filled it, `none` included, and the notes say what the reader pass has to make up
    for. `source` carries what the caller knows about where the PDF came from (the arXiv answer
    of a PDF-only submission); a PDF the owner handed over records its own path. Returns the
    inventory written.
    """
    ledger = ledger_for(project_or_ledger)
    tools = tools if tools is not None else Tools()
    pdf = Path(pdf)
    payload = pdf.read_bytes()
    if payload[:4] != _PDF_MAGIC:
        raise ValueError("%s is not a PDF (it does not begin with %%PDF)" % pdf)
    base = "%s/%s" % (REFS, slug)
    source = dict(source or {})
    name = source.pop("name", None) or PDF_NAME
    pdf_rel = "%s/%s" % (SOURCE, name)
    kept = ledger.research / REFS / slug / SOURCE / name
    if not (kept.is_file() and kept.resolve() == pdf.resolve()):
        ledger.write_bytes("%s/%s" % (base, pdf_rel), payload)
    previous = _read_json_file(ledger.research / REFS / slug / INVENTORY) or {}

    workspace = Path(tempfile.mkdtemp(prefix="wayline-pdf-"))
    try:
        layer = always_on_layer(kept, workspace, tools, run)
        text = layer["text"] or ""
        if layer["text"] is not None:
            ledger.write_markdown("%s/%s" % (base, TEXT_LAYER), text)
        if layer["boxes"] is not None:
            ledger.write_json("%s/%s/%s" % (base, SOURCE, BOXES), layer["boxes"])
        record, converter, out, converter_notes, enrichment = run_converters(kept, workspace, tools, run, len(text.strip()))
        metadata, references, references_by, grobid_notes = grobid_references(kept, tools, run, sleep)
        inventory = _assemble(ledger, slug, layer, record, converter, out, metadata, references, references_by, pdf_rel)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    notes = layer["notes"] + converter_notes + grobid_notes + inventory.pop("notes")
    inventory["source"] = dict({
        "kind": "pdf",
        "url": pdf.resolve().as_uri(),
        "arxiv_id": None,
        "version": None,
        "etag": None,
        "fetched": now_ts(),
        "from_cache": False,
        "files": 1,
        "flattened_by": None,
        "compiled": False,
    }, **source)
    inventory["source"].update({
        "bytes": len(payload),
        "main": pdf_rel,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "converter": converter,
        "references_by": references_by,
        "formula_enrichment": enrichment if converter != "none" else None,
    })
    if inventory["source"].get("arxiv_id"):
        inventory["metadata"]["arxiv_id"] = inventory["source"]["arxiv_id"]
    inventory["notes"] = notes
    inventory["created"] = previous.get("created") or now_ts()
    if previous:
        inventory["updated"] = now_ts()
    check(inventory, load_schema("inventory"), name="%s/%s" % (base, INVENTORY))
    ledger.write_json("%s/%s" % (base, INVENTORY), inventory, schema="inventory")
    return inventory


def _assemble(ledger, slug, layer, record, converter, out, metadata, references, references_by, pdf_rel):
    """The inventory's fields out of the layers that ran, each with the provenance of what filled it."""
    base = "%s/%s" % (REFS, slug)
    poppler = layer["poppler"]
    by_poppler = (lambda tool: "%s-%s" % (tool, poppler)) if poppler else (lambda tool: "none")
    plumber = "pdfplumber-%s" % layer["plumber_version"] if layer["boxes"] is not None else None
    notes = []
    converted = record is not None
    record = record if converted else new_record()
    images = record.pop("images", {}) if converted else {}
    converter_title = record.pop("title", None)
    converter_counts = record.pop("counts", {})
    notes.extend(record.pop("notes", []))

    # A layout model calls the title a heading when nothing marks it apart; the PDF's own Title field says it is not one.
    known_title = _tidy(layer["info"].get("title")) or converter_title
    if known_title and len(_title_key(known_title)) >= 20:
        kept = [item for item in record["sections"]
                if not (item.get("page") == 1 and not item.get("number") and len(_title_key(item.get("title"))) >= 20
                        and _title_key(item.get("title")) in (_title_key(known_title), _title_key(known_title)[:len(_title_key(item.get("title")))]))]
        if len(kept) != len(record["sections"]):
            removed = [item for item in record["sections"] if item not in kept]
            converter_title = converter_title or removed[0].get("title")
            record["sections"] = kept
            _renumber(record, "sections")

    if not converted and plumber:
        for page in layer["boxes"].get("pages") or []:
            for table in page.get("tables") or []:
                _add(record, "tables", {
                    "kind": "table", "cells": table.get("cells") or [], "page": page.get("page"),
                    "bbox": [round(float(value), 1) for value in table.get("bbox") or []] or None,
                    "locator": _locator(pdf_rel, page.get("page")), "provenance": plumber,
                    "confirm": True, "confirm_fields": ["caption", "cells"],
                })
    found_in_text = text_layer_environments(layer["pages"], TEXT_LAYER) if layer["pages"] else []
    known = {(item.get("environment"), item.get("number"), item.get("page")) for item in record["algorithms"] + record["theorems"]}
    for entry in found_in_text:
        if (entry["environment"], entry["number"], entry["page"]) in known:
            continue
        entry.update({"provenance": by_poppler("pdftotext"), "confirm": True, "confirm_fields": ["boundary"]})
        _add(record, "algorithms" if entry["kind"] == "algorithm" else "theorems", entry)

    ledger.remove_tree("%s/%s" % (base, FIGURES))
    for bucket in ("figures", "tables"):
        for item in record[bucket]:
            image = images.get(item["id"])
            if image and out is not None and (Path(out) / image).is_file():
                name = "%s/%s.png" % (FIGURES, item["id"])
                ledger.write_bytes("%s/%s" % (base, name), (Path(out) / image).read_bytes())
                item["file"] = name

    provenance = {}
    for key in ITEM_KEYS:
        if record[key]:
            provenance[key] = record[key][0]["provenance"]
        elif converted:
            provenance[key] = converter  # the converter looked and found none, which is itself a reading
        elif key in ("algorithms", "theorems") and layer["pages"]:
            provenance[key] = by_poppler("pdftotext")
        elif key == "tables" and plumber:
            provenance[key] = plumber
        else:
            provenance[key] = "none"

    info = layer["info"]
    if references_by != "none":
        inventory_metadata = {key: value for key, value in metadata.items() if value}
        provenance["metadata"] = references_by
    elif info.get("title") or info.get("author"):
        inventory_metadata = {"title": info.get("title") or None, "authors": [info["author"]] if info.get("author") else []}
        provenance["metadata"] = by_poppler("pdfinfo")
    elif converter_title:
        inventory_metadata = {"title": converter_title}
        provenance["metadata"] = converter
    else:
        inventory_metadata = {}
        provenance["metadata"] = "none"
    provenance["references"] = references_by
    provenance["page_count"] = by_poppler("pdfinfo") if info.get("pages") is not None else "none"
    provenance["text_layer"] = by_poppler("pdftotext") if layer["text"] is not None else "none"
    provenance["raw_images"] = by_poppler("pdfimages") if poppler else "none"
    if plumber:
        provenance["boxes"] = plumber

    raw_images = [{
        "path": "%s#page=%d&image=%d" % (pdf_rel, row["page"], row["num"]), "format": row["enc"],
        "bytes": _size_bytes(row["size"]), "page": row["page"], "width": row["width"], "height": row["height"],
        "ppi": row["x_ppi"], "provenance": by_poppler("pdfimages"),
    } for row in layer["images"] if row["type"] == "image"]

    boxes = None
    if plumber:
        summary = summarize_boxes(layer["boxes"])
        boxes = dict(summary, path="%s/%s" % (SOURCE, BOXES), provenance=plumber)

    counts = {
        "pages": info.get("pages") or 0,
        "sections": len(record["sections"]),
        "appendices": len(record["appendices"]),
        "section_headings": len(record["sections"]) + len(record["appendices"]),
        "equations": len(record["equations"]),
        "numbered_equations": len([item for item in record["equations"] if item.get("number")]),
        "figures": len(record["figures"]),
        "figures_with_caption": len([item for item in record["figures"] if item.get("caption")]),
        "figure_files": len([item for item in record["figures"] if item.get("file")]),
        "tables": len(record["tables"]),
        "algorithms": len(record["algorithms"]),
        "theorems": len(record["theorems"]),
        "references": len(references),
        "raw_images": len(raw_images),
        "text_layer_headings": len(found_in_text),
    }
    if converter_counts.get("reference_list_items"):
        counts["reference_list_items"] = converter_counts["reference_list_items"]
    if boxes:
        counts.update({"words": boxes["words"] or 0, "chars": boxes["chars"] or 0, "ruled_tables": boxes["ruled_tables"] or 0})

    confirms = {}
    for key in ITEM_KEYS:
        for item in record[key]:
            for field in item.get("confirm_fields") or []:
                confirms[field] = confirms.get(field, 0) + 1
    if confirms:
        notes.append("the reader pass confirms: " + ", ".join("%s on %d item(s)" % (field, confirms[field]) for field in sorted(confirms)))
    if not converted:
        notes.append("no structural converter read this PDF, so its sections, equations, and figures are the reader pass's to find; "
                     "the text layer, the page count, the image list, and the ruled tables are what the harness could read")

    inventory = {
        "schema_version": 1,
        "slug": slug,
        "source_type": "pdf",
        "provenance": provenance,
        "counts": counts,
        "page_count": info.get("pages"),
        "text_layer": {"path": TEXT_LAYER, "chars": len(layer["text"]), "provenance": by_poppler("pdftotext")} if layer["text"] is not None else None,
        "boxes": boxes,
        "raw_images": raw_images,
        "references": references,
        "metadata": inventory_metadata,
        "notes": notes,
    }
    for key in ITEM_KEYS:
        inventory[key] = record[key]
    return inventory
