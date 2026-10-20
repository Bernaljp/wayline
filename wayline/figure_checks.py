"""The figure role's 19 machine checks (Implementation Decisions 13; research-notes 11 Section 3).

Before any figure costs a verdict, code checks it: every check here is a Type-A gate, each returns
`{id, type: "A", pass, tool, detail}`, and `run_checks` returns the list in `CHECK_IDS` order,
which is the `checks` block of `figure_result/1`. A failed check sends the figure back to the role
without spending a critic or verifier session (C6).

What each check reads:

- the final files named in `figure_result.final` (the PDF, the PNG, the caption, the notes, the
  generator, the inputs), relative to the project;
- the request's `target`, `kind`, `register`, and `forbidden_text`;
- the project's house style, `figures/style.json` (or the path `figure_request.style` names);
- `policy.figures` for `ssim_min` and `crops_dpi`;
- poppler (`pdffonts`, `pdfinfo`, `pdfimages`, `pdftotext`, `pdftoppm`) and `ruff`, found on
  `PATH` (`ruff` also through `uvx`); a tool that is not installed fails its check, because a gate
  that cannot look cannot pass;
- the artist report, written at save time by `figures/checks/artists.py` in the project's own
  environment: the harness stays standard-library, so everything that needs matplotlib runs
  there as a script. The clean-room regeneration runs the generator through that script, so one
  run gives the exit status (`generator_clean`), the regenerated files (`regenerates`), and the
  artists (`min_font_pt`, `forbidden_text`, `caption_panels`, `palette`,
  `one_ramp_per_quantity`, `required_vs_optional_line_style`, `crops`, `text_overlap`).

A generator marks what the checks cannot infer with matplotlib's `gid`: `panel:<letter>` on an
axes, `quantity:<name>` on a colormapped artist, `required:<name>` or `optional:<name>` on an
edge or curve, and `connector:<name>` or `container:<name>` on structure that must spend no color.
A generator that draws with no matplotlib artists (TikZ) produces no artist report, so the checks
that need one fail and say so rather than passing unexamined.

The PDF walk, the PNG decoder, SSIM, and the color arithmetic are here in the standard library
rather than in a script because the checks that use them need no plotting library, and the suite
can then exercise them on a machine without one.
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from wayline import HARNESS_ROOT, backends_off
from wayline.provenance import RUN_ID_RE, read_manifest, sha256_of

__all__ = [
    "CHECK_IDS", "CHECKS", "ARTISTS_SCRIPT", "MIXED_DATA_MARKER", "ToolMissing", "PngError", "Tools",
    "FigureContext", "CleanRoom", "PdfFacts", "run_checks", "check_outcome",
    "pdf_facts", "parse_pdffonts", "parse_pdfimages", "png_size", "png_luma", "ssim",
    "hex_to_rgb", "srgb_to_lab", "ciede2000", "simulate_cvd", "CVD_KINDS", "is_grey",
    "lint_caption", "forbidden_tokens", "caption_panels", "run_clean_room", "TOOL",
    "check_fonts_embedded", "check_journal_width", "check_resolution", "check_min_font_pt",
    "check_max_words", "check_forbidden_text", "check_caption_panels", "check_caption_lint",
    "check_generator_clean", "check_regenerates", "check_palette", "check_one_ramp_per_quantity",
    "check_required_vs_optional_line_style", "check_selection_representativeness",
    "check_schematic_disclosed", "check_mixed_data_disclosed", "check_crops", "check_text_overlap",
    "check_provenance", "hue_problems", "style_colors",
]

CHECK_IDS = (
    "fonts_embedded", "journal_width", "resolution", "min_font_pt", "max_words", "forbidden_text",
    "caption_panels", "caption_lint", "generator_clean", "regenerates", "palette",
    "one_ramp_per_quantity", "required_vs_optional_line_style", "selection_representativeness",
    "schematic_disclosed", "mixed_data_disclosed", "crops", "text_overlap", "provenance",
)

# The tool each check names in its outcome; a check that reads two sources names both.
TOOL = {
    "fonts_embedded": "pdffonts",
    "journal_width": "pdfinfo",
    "resolution": "pdfimages",
    "min_font_pt": "pdf-text-walk",
    "max_words": "pdftotext",
    "forbidden_text": "pdftotext",
    "caption_panels": "caption",
    "caption_lint": "caption-lint",
    "generator_clean": "ruff",
    "regenerates": "clean-room",
    "palette": "cvd-ciede2000",
    "one_ramp_per_quantity": "artists",
    "required_vs_optional_line_style": "artists",
    "selection_representativeness": "declared-tolerance",
    "schematic_disclosed": "presence",
    "mixed_data_disclosed": "presence",
    "crops": "pdftoppm",
    "text_overlap": "artists",
    "provenance": "manifest",
}

ARTISTS_SCRIPT = HARNESS_ROOT / "figures" / "checks" / "artists.py"
DEFAULT_STYLE = "figures/style.json"
MIXED_DATA_MARKER = "[[mixed-data]]"

WIDTH_TOLERANCE_MM = 0.5
FONT_TOLERANCE_PT = 0.01
IN_STYLE_DELTA_E = 2.0  # a color this close to a style color is that color, rounded on its way into the PDF
GREY_TOLERANCE = 10 / 255  # the largest channel spread a structural grey may have
OVERLAP_FRACTION = 0.10  # of the smaller text's area
EDGE_TOLERANCE_PX = 1.0
DEFAULT_SSIM_MIN = 0.99
DEFAULT_CROPS_DPI = 600
DEFAULT_RENDER_SECONDS = 600
DEFAULT_CVD_MIN_DELTA_E = 10


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class ToolMissing(RuntimeError):
    """A check needs a program that is not installed."""

    def __init__(self, tool):
        super().__init__("%s is not installed" % tool)
        self.tool = tool


class PngError(ValueError):
    """A PNG this module cannot decode (interlaced, an unsupported bit depth, or not a PNG)."""


def check_outcome(check_id, passed, detail, tool=None):
    """One entry of the report block: `{id, type: "A", pass, tool, detail}`."""
    return {"id": check_id, "type": "A", "pass": bool(passed), "tool": tool or TOOL[check_id], "detail": detail}


def check_not_run(check_id, reason, tool=None):
    """The entry of a check that cannot run on what it was given: listed as not run, never passed or
    failed (Implementation Decision 17), with `pass` null and the reason as its detail."""
    return {"id": check_id, "type": "A", "pass": None, "not_run": True, "tool": tool or TOOL.get(check_id), "detail": reason}


# --- the outside world ----------------------------------------------------------------------------


_RUNS = {}


def _runs(argv):
    """Whether `argv` exits 0, asked once per process: the cached answer for an offline `uvx ruff`."""
    key = tuple(argv)
    if key not in _RUNS:
        try:
            _RUNS[key] = subprocess.run(argv, capture_output=True, timeout=60).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _RUNS[key] = False
    return _RUNS[key]


class Tools:
    """How the checks reach programs: poppler, ruff, and the Python the generator runs in.

    `python` is the project's interpreter; by default the project's `.venv/bin/python` when there
    is one, else the interpreter running the harness. `which` is `shutil.which` unless a test
    replaces it to make a tool disappear.
    """

    def __init__(self, python=None, which=shutil.which, timeout_s=120):
        self.python = python
        self.which = which
        self.timeout_s = timeout_s

    def argv(self, name):
        found = self.which(name)
        if found:
            return [found]
        if name == "ruff" and self.which("uvx"):
            if not backends_off():
                return [self.which("uvx"), "ruff"]
            # uvx asks the package index on every run; with the backends off (the suite) it runs from its cache, and a
            # cache that holds no ruff is a machine without ruff.
            argv = [self.which("uvx"), "--offline", "ruff"]
            return argv if _runs(argv + ["--version"]) else None
        return None

    def run(self, name, args, cwd=None, timeout_s=None):
        argv = self.argv(name)
        if argv is None:
            raise ToolMissing(name)
        run = subprocess.run(
            argv + [str(arg) for arg in args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=cwd, timeout=timeout_s or self.timeout_s,
            env=dict(os.environ, NO_COLOR="1"),
        )
        # ruff through uvx colors its output even into a pipe; the checks read words, not escapes.
        run.stdout, run.stderr = _ANSI.sub("", run.stdout), _ANSI.sub("", run.stderr)
        return run

    def python_for(self, project):
        if self.python:
            return str(self.python)
        venv = Path(project) / ".venv" / "bin" / "python"
        return str(venv) if venv.exists() else sys.executable


@dataclass
class CleanRoom:
    """One run of the generator in a fresh directory holding only what it declared."""

    returncode: object  # int, or None when it never finished
    error: str
    root: object = None  # Path of the room, or None when it was never made
    report: object = None  # the artist report the run wrote, or None


class FigureContext:
    """Everything a check reads, with the clean-room run made at most once and shared."""

    def __init__(self, project, request, result, style=None, policy=None, tools=None, artists=None):
        self.project = Path(project).resolve()
        self.request = request
        self.result = result
        self.tools = tools or Tools()
        self.policy = policy if policy is not None else _figures_policy(self.project)
        self.style = style if style is not None else self._read_style()
        self.artists_error = None  # what the artist script said when it could not describe the figure
        self._artists = artists
        self._clean_room = None
        self._pdf_facts = {}

    @property
    def target(self):
        return self.request.get("target") or {}

    @property
    def final(self):
        return self.result.get("final") or {}

    def wants(self, fmt):
        return fmt in (self.target.get("formats") or [])

    def path(self, relative):
        """`relative` resolved inside the project, or None when it is absent or escapes it."""
        if not relative:
            return None
        candidate = (self.project / relative).resolve()
        if candidate != self.project and self.project not in candidate.parents:
            return None
        return candidate

    def final_file(self, key):
        """The final file under `key` when it is on disk, else None."""
        path = self.path(self.final.get(key))
        return path if path is not None and path.is_file() else None

    def read_final(self, key):
        path = self.final_file(key)
        return None if path is None else path.read_text(encoding="utf-8", errors="replace")

    def clean_room(self):
        if self._clean_room is None:
            self._clean_room = run_clean_room(self)
        return self._clean_room

    def artists(self):
        """The artist report of the final figure: given, or written by the clean-room run."""
        if self._artists is None:
            report = _figure_report(self.clean_room().report, self.final)
            if report and report.get("error"):
                self.artists_error, report = report["error"], None
            self._artists = report or False
        return self._artists or None

    def room_failure(self):
        """Why the clean-room run failed, or None when it succeeded or has not run."""
        room = self._clean_room
        if room is None or room.returncode == 0:
            return None
        return room.error or "exit %s" % room.returncode

    def pdf_facts(self, path):
        """`pdf_facts(path)`, read once however many checks ask."""
        if path not in self._pdf_facts:
            self._pdf_facts[path] = pdf_facts(path)
        return self._pdf_facts[path]

    def close(self):
        if self._clean_room is not None and self._clean_room.root is not None:
            shutil.rmtree(self._clean_room.root, ignore_errors=True)

    def _read_style(self):
        path = self.path(self.request.get("style") or DEFAULT_STYLE)
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path is not None else {}
        except (OSError, ValueError):
            return {}


def _figures_policy(project):
    from wayline.project import policy_for  # the project module imports much; only a real run needs it

    return policy_for(project).get("figures", {})


def run_checks(project, request, result, style=None, policy=None, tools=None, artists=None, only=None):
    """Run the machine checks on one figure and return the `checks` block of `figure_result`.

    `only` restricts the run to some check ids (in `CHECK_IDS` order regardless). `artists` is an
    artist report to use instead of the clean-room run's; `style` and `policy` replace what the
    project holds. A check that raises is recorded as failed with the reason, never skipped.
    """
    context = FigureContext(project, request, result, style=style, policy=policy, tools=tools, artists=artists)
    report = []
    try:
        for check_id in CHECK_IDS:
            if only is not None and check_id not in only:
                continue
            try:
                outcome = CHECKS[check_id](context)
            except ToolMissing as missing:
                outcome = check_outcome(check_id, False, "%s is not installed, so this check cannot pass" % missing.tool, tool=missing.tool)
            except (OSError, ValueError, subprocess.SubprocessError) as failure:
                outcome = check_outcome(check_id, False, "the check could not run: %s" % failure)
            report.append(outcome)
    finally:
        context.close()
    return report


# --- the clean room -------------------------------------------------------------------------------


def run_clean_room(context):
    """Run the generator in a fresh directory that holds only the generator, its declared inputs,
    and the house style, in isolated mode (`python -I`, so no user site and no `PYTHONPATH`),
    through `figures/checks/artists.py` so the same run writes the artist report.

    matplotlib's font cache lives outside the room (`~/.cache/wayline/mplconfig`), because
    rebuilding it on every run costs seconds and changes no pixel; the directory holds no
    `matplotlibrc`, so it cannot restyle the figure.
    """
    final = context.final
    generator = final.get("generator")
    source = context.final_file("generator")
    if source is None:
        return CleanRoom(None, "the generator %r is not a file in the project" % generator)
    root = Path(tempfile.mkdtemp(prefix="wayline-figure-"))
    declared = [generator] + [entry.get("path") for entry in final.get("inputs") or []]
    declared.append(context.request.get("style") or DEFAULT_STYLE)
    for relative in declared:
        original = context.path(relative)
        if original is None or not original.is_file():
            continue  # an input that is not there fails the run, which is the point
        copy = root / Path(relative)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copy)
    report_path = root / ".wayline" / "artists.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "wayline" / "mplconfig"
    cache.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root),
        "TMPDIR": str(report_path.parent),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(cache),
        "SOURCE_DATE_EPOCH": "0",
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    argv = [context.tools.python_for(context.project), "-I", str(ARTISTS_SCRIPT), "--out", str(report_path)]
    if context.target.get("width_mm"):
        argv += ["--width-mm", str(context.target["width_mm"])]
    argv.append(str(Path(generator)))
    timeout = (context.request.get("budget") or {}).get("render_seconds") or DEFAULT_RENDER_SECONDS
    try:
        run = subprocess.run(argv, cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return CleanRoom(None, "timed out after %d s" % timeout, root)
    except OSError as failure:
        return CleanRoom(None, "could not start %s: %s" % (argv[0], failure), root)
    report = None
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError:
            report = None
    return CleanRoom(run.returncode, _tail(run.stderr), root, report)


def _figure_report(report, final):
    """The artist report of the figure saved to the final PDF or PNG (a generator may save others)."""
    figures = (report or {}).get("figures") or []
    targets = {Path(path).as_posix() for path in (final.get("pdf"), final.get("png")) if path}
    for figure in reversed(figures):
        if Path(figure.get("saved_to") or "").as_posix() in targets:
            return figure
    return figures[-1] if figures else None


def _tail(text, lines=6):
    kept = [line for line in (text or "").strip().splitlines() if line.strip()]
    return " | ".join(kept[-lines:])


# --- the PDF walk ---------------------------------------------------------------------------------


@dataclass
class PdfFacts:
    """What the content streams of a PDF say: the page, every text size, every color set, rasters."""

    page_width_pt: object = None
    page_height_pt: object = None
    text_sizes: list = field(default_factory=list)
    colors: set = field(default_factory=set)
    images: int = 0


_STREAM = re.compile(rb"stream\r?\n")
_MEDIABOX = re.compile(rb"/MediaBox\s*\[\s*([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s*\]")
_DIRECT_LENGTH = re.compile(rb"/Length\s+(\d+)(?!\d)(?!\s+\d+\s+R)")  # not `/Length 12 0 R`, nor its `1`
_FILTERS = re.compile(rb"/Filter\s*(\[[^\]]*\]|/\w+)")
_NOT_CONTENT = re.compile(rb"/Length[123]\b|/Type\s*/(?:XRef|Metadata|EmbeddedFile)\b|/Subtype\s*/(?:Type1C|CIDFontType0C|OpenType|XML)\b")
_IS_IMAGE = re.compile(rb"/Subtype\s*/Image\b")
_OBJECT_STREAM = re.compile(rb"/Type\s*/ObjStm\b")
_TOKEN = re.compile(
    rb"(?P<space>[\x00\t\n\x0c\r ]+)|(?P<comment>%[^\r\n]*)|(?P<string>\()|(?P<dict><<|>>)"
    rb"|(?P<hex><[0-9A-Fa-f\x00\t\n\x0c\r ]*>)|(?P<array>[\[\]])|(?P<name>/[^\x00\t\n\x0c\r ()<>\[\]{}/%]*)"
    rb"|(?P<number>[+-]?(?:\d+\.?\d*|\.\d+)(?![^\x00\t\n\x0c\r ()<>\[\]{}/%]))"
    rb"|(?P<word>[^\x00\t\n\x0c\r ()<>\[\]{}/%]+)|(?P<other>.)",
    re.DOTALL,
)
_END_INLINE_IMAGE = re.compile(rb"\sEI(?=[\x00\t\n\x0c\r ]|$)")
_TEXT_SHOWING = frozenset([b"Tj", b"TJ", b"'", b'"'])


def pdf_facts(path):
    """Read a PDF's page size, text sizes, colors, and raster count with the standard library.

    Text sizes are `Tf` sizes scaled by the text matrix and the current transformation matrix, so
    a font set at 10 inside a `0.5 0 0 0.5 cm` counts as 5 pt. Every stream is walked with its own
    graphics state (a form XObject does not inherit its caller's matrix), which holds for
    matplotlib's and pdfTeX's output and is the approximation this walk makes. Colors are the
    DeviceRGB, DeviceGray, and DeviceCMYK operands of the color operators, as `#RRGGBB`.
    """
    data = Path(path).read_bytes()
    facts = PdfFacts()
    boxes = [match.groups() for match in _MEDIABOX.finditer(data)]
    for dictionary, body in _streams(data):
        if _IS_IMAGE.search(dictionary):
            facts.images += 1
            continue
        if _NOT_CONTENT.search(dictionary):
            continue
        decoded = _decode(dictionary, body)
        if decoded is None:
            continue
        if _OBJECT_STREAM.search(dictionary):
            boxes.extend(match.groups() for match in _MEDIABOX.finditer(decoded))
            continue
        _walk_content(decoded, facts)
    if boxes:
        x0, y0, x1, y1 = (float(value) for value in boxes[0])
        facts.page_width_pt, facts.page_height_pt = abs(x1 - x0), abs(y1 - y0)
    return facts


def _streams(data):
    for match in _STREAM.finditer(data):
        if data[max(0, match.start() - 3):match.start()] == b"end":
            continue
        head = data.rfind(b"obj", 0, match.start())
        dictionary = data[head:match.start()] if head >= 0 else b""
        length = _DIRECT_LENGTH.search(dictionary)
        if length:
            body = data[match.end():match.end() + int(length.group(1))]
        else:
            end = data.find(b"endstream", match.end())
            body = data[match.end():end if end >= 0 else len(data)]
        yield dictionary, body


def _decode(dictionary, body):
    filters = re.findall(rb"/(\w+)", b" ".join(_FILTERS.findall(dictionary)))
    if not filters:
        return body
    if filters != [b"FlateDecode"] or b"/Predictor" in dictionary:
        return None
    try:
        return zlib.decompressobj().decompress(body)
    except zlib.error:
        return None


def _mostly_text(stream):
    sample = stream[:4096]
    if not sample:
        return False
    printable = sum(1 for byte in sample if 32 <= byte < 127 or byte in (9, 10, 13))
    return printable / len(sample) >= 0.75


def _walk_content(stream, facts):
    if not _mostly_text(stream):
        return
    ctm, stack, tm, size, operands = 1.0, [], 1.0, None, []
    position, end = 0, len(stream)
    while position < end:
        match = _TOKEN.match(stream, position)
        kind, token, position = match.lastgroup, match.group(), match.end()
        if kind in ("space", "comment", "dict", "array", "other"):
            continue
        if kind == "string":
            position = _skip_string(stream, position)
            operands.append(None)
            continue
        if kind in ("hex", "name"):
            operands.append(None)
            continue
        if kind == "number":
            operands.append(float(token))
            continue
        if token == b"BI":
            found = _END_INLINE_IMAGE.search(stream, position)
            position = found.end() if found else end
        elif token in (b"d0", b"d1"):
            return  # a Type 3 glyph procedure, not page content
        elif token == b"q":
            stack.append(ctm)
        elif token == b"Q":
            ctm = stack.pop() if stack else 1.0
        elif token == b"cm":
            ctm *= _matrix_scale(operands)
        elif token == b"BT":
            tm = 1.0
        elif token == b"Tm":
            tm = _matrix_scale(operands)
        elif token == b"Tf":
            if operands and isinstance(operands[-1], float):
                size = abs(operands[-1])
        elif token in _TEXT_SHOWING:
            if size is not None:
                facts.text_sizes.append(size * tm * ctm)
        elif token in (b"rg", b"RG", b"g", b"G", b"k", b"K", b"sc", b"scn", b"SC", b"SCN"):
            color = _color(operands)
            if color is not None:
                facts.colors.add(color)
        operands = []


def _skip_string(stream, position):
    depth, end = 1, len(stream)
    while position < end and depth:
        byte = stream[position]
        if byte == 0x5C:  # backslash: the next byte is escaped
            position += 2
            continue
        if byte == 0x28:
            depth += 1
        elif byte == 0x29:
            depth -= 1
        position += 1
    return position


def _matrix_scale(operands):
    numbers = [value for value in operands[-6:] if isinstance(value, float)]
    if len(numbers) != 6:
        return 1.0
    a, b, c, d = numbers[:4]
    return math.sqrt(abs(a * d - b * c))


def _color(operands):
    numbers = []
    for value in reversed(operands):
        if not isinstance(value, float):
            break
        numbers.insert(0, value)
    if len(numbers) == 1:
        red = green = blue = numbers[0]
    elif len(numbers) == 3:
        red, green, blue = numbers
    elif len(numbers) == 4:
        cyan, magenta, yellow, black = numbers
        red, green, blue = ((1 - channel) * (1 - black) for channel in (cyan, magenta, yellow))
    else:
        return None
    return "#%02X%02X%02X" % tuple(round(min(1.0, max(0.0, channel)) * 255) for channel in (red, green, blue))


def parse_pdffonts(text):
    """The rows of `pdffonts` as `{name, type, encoding, emb}`, read from the right, since a font
    name longer than its column pushes the others along."""
    rows, seen_rule = [], False
    for line in text.splitlines():
        if line.startswith("---"):
            seen_rule = True
            continue
        tokens = line.split()
        if not seen_rule or len(tokens) < 7:
            continue
        rows.append({"name": tokens[0], "type": " ".join(tokens[1:-6]), "encoding": tokens[-6], "emb": tokens[-5]})
    return rows


def parse_pdfimages(text):
    """The rows of `pdfimages -list` as `{type, width, height, x_ppi, y_ppi}`."""
    rows, seen_rule = [], False
    for line in text.splitlines():
        if line.startswith("---"):
            seen_rule = True
            continue
        tokens = line.split()
        if not seen_rule or len(tokens) < 16:
            continue
        rows.append({"type": tokens[2], "width": int(tokens[3]), "height": int(tokens[4]),
                     "x_ppi": int(tokens[-4]), "y_ppi": int(tokens[-3])})
    return rows


# --- PNG and SSIM ---------------------------------------------------------------------------------


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def png_size(path):
    """`(width, height)` of a PNG, from its header."""
    head = Path(path).read_bytes()[:24]
    if head[:8] != _PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise PngError("%s is not a PNG" % path)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def png_luma(path):
    """`(width, height, luma)` of a PNG, luma a bytearray of Rec. 601 luma composited over white.

    Decodes 8- and 16-bit grayscale, RGB, palette, and alpha PNGs without interlacing, which
    covers what matplotlib, Pillow, and pdftoppm write.
    """
    data = Path(path).read_bytes()
    if data[:8] != _PNG_SIGNATURE:
        raise PngError("%s is not a PNG" % path)
    position, idat, palette, header = 8, [], None, None
    while position + 8 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = payload
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"IDAT":
            idat.append(payload)
        elif kind == b"IEND":
            break
    if header is None:
        raise PngError("%s has no IHDR" % path)
    width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
    depth, color_type, interlace = header[8], header[9], header[12]
    if interlace or depth not in (8, 16) or color_type not in _PNG_CHANNELS or (color_type == 3 and depth != 8):
        raise PngError("%s: interlaced or %d-bit color type %d is not decoded here" % (path, depth, color_type))
    channels = _PNG_CHANNELS[color_type]
    step = depth // 8
    bpp = channels * step
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    luma = bytearray(width * height)
    previous = bytearray(stride)
    for row in range(height):
        start = row * (stride + 1)
        line = _unfilter(raw[start], bytearray(raw[start + 1:start + 1 + stride]), previous, bpp)
        previous = line
        samples = [line[offset::bpp] for offset in range(0, bpp, step)]  # the high byte of every channel
        out = row * width
        if color_type == 0:
            luma[out:out + width] = samples[0]
        elif color_type == 4:
            luma[out:out + width] = bytes(_over_white(value, alpha) for value, alpha in zip(samples[0], samples[1]))
        elif color_type == 3:
            if palette is None:
                raise PngError("%s is a palette PNG without PLTE" % path)
            luma[out:out + width] = bytes(_luma(palette[3 * index], palette[3 * index + 1], palette[3 * index + 2]) for index in samples[0])
        elif color_type == 2:
            luma[out:out + width] = bytes(map(_luma, samples[0], samples[1], samples[2]))
        else:
            luma[out:out + width] = bytes(_over_white(_luma(r, g, b), a) for r, g, b, a in zip(*samples))
    return width, height, luma


def _unfilter(kind, line, previous, bpp):
    if kind == 0:
        return line
    if kind == 1:
        for x in range(bpp, len(line)):
            line[x] = (line[x] + line[x - bpp]) & 0xFF
    elif kind == 2:
        line = bytearray((value + above) & 0xFF for value, above in zip(line, previous))
    elif kind == 3:
        for x in range(len(line)):
            left = line[x - bpp] if x >= bpp else 0
            line[x] = (line[x] + ((left + previous[x]) >> 1)) & 0xFF
    elif kind == 4:
        for x in range(len(line)):
            left = line[x - bpp] if x >= bpp else 0
            above = previous[x]
            corner = previous[x - bpp] if x >= bpp else 0
            estimate = left + above - corner
            to_left, to_above, to_corner = abs(estimate - left), abs(estimate - above), abs(estimate - corner)
            if to_left <= to_above and to_left <= to_corner:
                predictor = left
            elif to_above <= to_corner:
                predictor = above
            else:
                predictor = corner
            line[x] = (line[x] + predictor) & 0xFF
    else:
        raise PngError("unknown PNG filter type %d" % kind)
    return line


def _luma(red, green, blue):
    return (299 * red + 587 * green + 114 * blue + 500) // 1000


def _over_white(value, alpha):
    return (value * alpha + 255 * (255 - alpha) + 127) // 255


def ssim(first, second, width, height, window=7):
    """Mean structural similarity (Wang et al. 2004) of two same-sized grayscale images.

    A uniform `window`-square window, sample covariance, and the constants K1 = 0.01, K2 = 0.03 over
    an 8-bit range, averaged over every window that fits: scikit-image's `structural_similarity`
    defaults. Identical images short-circuit to 1.0, which is the common case for a deterministic
    generator.
    """
    if len(first) != width * height or len(second) != width * height:
        raise ValueError("both images must be %d x %d" % (width, height))
    if first == second:
        return 1.0
    window = max(1, min(window, width, height))
    count = window * window
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    norm = count / (count - 1) if count > 1 else 1.0
    col = [[0.0] * width for _ in range(5)]  # per column over the window rows: a, b, aa, bb, ab

    def add(row, sign):
        base = row * width
        sum_a, sum_b, sum_aa, sum_bb, sum_ab = col
        for x in range(width):
            a, b = first[base + x], second[base + x]
            sum_a[x] += sign * a
            sum_b[x] += sign * b
            sum_aa[x] += sign * a * a
            sum_bb[x] += sign * b * b
            sum_ab[x] += sign * a * b

    for row in range(window):
        add(row, 1)
    total, windows = 0.0, 0
    for top in range(height - window + 1):
        if top:
            add(top - 1, -1)
            add(top + window - 1, 1)
        sums = [sum(column[:window]) for column in col]
        for left in range(width - window + 1):
            if left:
                for index in range(5):
                    sums[index] += col[index][left + window - 1] - col[index][left - 1]
            mean_a, mean_b = sums[0] / count, sums[1] / count
            var_a = norm * (sums[2] / count - mean_a * mean_a)
            var_b = norm * (sums[3] / count - mean_b * mean_b)
            cov = norm * (sums[4] / count - mean_a * mean_b)
            total += ((2 * mean_a * mean_b + c1) * (2 * cov + c2)) / ((mean_a ** 2 + mean_b ** 2 + c1) * (var_a + var_b + c2))
            windows += 1
    return total / windows


# --- color ----------------------------------------------------------------------------------------


# Machado, Oliveira and Fernandes (2009), severity 1.0, applied to linear RGB.
CVD_MATRICES = {
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}
CVD_KINDS = tuple(CVD_MATRICES)
_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def hex_to_rgb(value):
    """`#RRGGBB` as three channels in 0..1."""
    match = _HEX.match(value.strip())
    if not match:
        raise ValueError("%r is not a #RRGGBB color" % value)
    digits = match.group(1)
    return tuple(int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _to_linear(channel):
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _to_gamma(channel):
    return 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055


def simulate_cvd(rgb, kind):
    """An sRGB color as seen under complete protanopia, deuteranopia, or tritanopia."""
    linear = [_to_linear(channel) for channel in rgb]
    seen = [sum(weight * value for weight, value in zip(row, linear)) for row in CVD_MATRICES[kind]]
    return tuple(_to_gamma(min(1.0, max(0.0, value))) for value in seen)


def srgb_to_lab(rgb):
    """An sRGB color in CIELAB under D65."""
    red, green, blue = (_to_linear(channel) for channel in rgb)
    x = (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = (0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(first, second):
    """The CIEDE2000 color difference of two CIELAB colors (Sharma, Wu and Dalal 2005)."""
    l1, a1, b1 = first
    l2, a2, b2 = second
    c_mean = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_mean ** 7 / (c_mean ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0
    delta_l, delta_c = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        delta_h = 0.0
    else:
        delta_h = h2p - h1p
        if delta_h > 180:
            delta_h -= 360
        elif delta_h < -180:
            delta_h += 360
    delta_hh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_h / 2))
    l_mean, cp_mean = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_mean = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_mean = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        h_mean = (h1p + h2p + 360) / 2
    else:
        h_mean = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(h_mean - 30)) + 0.24 * math.cos(math.radians(2 * h_mean))
         + 0.32 * math.cos(math.radians(3 * h_mean + 6)) - 0.20 * math.cos(math.radians(4 * h_mean - 63)))
    rotation = 30 * math.exp(-(((h_mean - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(cp_mean ** 7 / (cp_mean ** 7 + 25 ** 7))
    s_l = 1 + 0.015 * (l_mean - 50) ** 2 / math.sqrt(20 + (l_mean - 50) ** 2)
    s_c = 1 + 0.045 * cp_mean
    s_h = 1 + 0.015 * cp_mean * t
    r_t = -math.sin(math.radians(2 * rotation)) * r_c
    return math.sqrt((delta_l / s_l) ** 2 + (delta_c / s_c) ** 2 + (delta_hh / s_h) ** 2 + r_t * (delta_c / s_c) * (delta_hh / s_h))


def is_grey(value):
    """True for black, white, and the greys between: structure, which spends no color."""
    rgb = hex_to_rgb(value)
    return max(rgb) - min(rgb) <= GREY_TOLERANCE + 1e-9


def _distance(first, second, kind=None):
    one, two = hex_to_rgb(first), hex_to_rgb(second)
    if kind is not None:
        one, two = simulate_cvd(one, kind), simulate_cvd(two, kind)
    return ciede2000(srgb_to_lab(one), srgb_to_lab(two))


def hue_problems(hues, style):
    """`(in_style, new, problems)` of a figure's hues against the house style: the hues the style names (within
    `IN_STYLE_DELTA_E` of one of its colors), the new ones, and each pair a new hue makes that one of the three color
    vision deficiencies brings closer than the style's `cvd_min_delta_e`. The figure checks and a drawing's plots share it."""
    allowed = _style_colors(style)
    threshold = float(style.get("cvd_min_delta_e", DEFAULT_CVD_MIN_DELTA_E))
    in_style = [color for color in hues if allowed and min(_distance(color, other) for other in allowed) <= IN_STYLE_DELTA_E]
    new = [color for color in hues if color not in in_style]
    problems = []
    for index, color in enumerate(new):
        for other in hues:
            if other == color or (other in new and new.index(other) < index):
                continue
            for kind in CVD_KINDS:
                distance = _distance(color, other, kind)
                if distance < threshold:
                    problems.append("%s and %s are %.1f apart under %s (at least %g)" % (color, other, distance, kind, threshold))
    return in_style, new, problems


def style_colors(style):
    """The colors the house style spends: its categorical ones, the diverging ends, the special hue, the parameter colors."""
    return _style_colors(style)


def _style_colors(style):
    colors = list(style.get("categorical") or [])
    diverging = style.get("diverging") or {}
    colors += [diverging[key] for key in ("low", "high") if diverging.get(key)]
    if style.get("special_hue"):
        colors.append(style["special_hue"])
    colors += list(style.get("equation_parameter_colors") or [])
    return colors


# --- text rules -----------------------------------------------------------------------------------


# British spellings an American-English caption must not carry. A list rather than a suffix rule,
# because "-ise" and "-our" also end words that are American ("precise", "hour").
_BRITISH = re.compile(
    r"\b(?:colour(?:s|ed|ing|ful|map|maps|bar|bars)?|behaviour(?:s|al)?|favour(?:s|ed|able|ite)?|"
    r"neighbour(?:s|ing|hood|hoods)?|labour|centre(?:s|d)?|fibre(?:s)?|metre(?:s)?|litre(?:s)?|"
    r"analyse|analysed|analysing|normalis(?:e|ed|es|ing|ation)|optimis(?:e|ed|es|ing|ation)|"
    r"minimis(?:e|ed|es|ing)|maximis(?:e|ed|es|ing)|visualis(?:e|ed|es|ing|ation)|organis(?:e|ed|es|ing|ation)|"
    r"recognis(?:e|ed|es|ing)|summaris(?:e|ed|es|ing)|characteris(?:e|ed|es|ing|ation)|randomis(?:e|ed|ation)|"
    r"parameteris(?:e|ed|ation)|modelling|modelled|labelled|labelling|travelled|cancelled|signalling|"
    r"grey|greys|greyscale|programme(?:s)?|licence|defence|catalogue|tumour(?:s)?|haemoglobin|leukaemia|"
    r"anaemia|paediatric|oesophageal|oestrogen|foetal|whilst|amongst)\b",
    re.IGNORECASE,
)
_FORWARD_REFERENCE = re.compile(r"\bsee(?:\s+also)?\s+(?:Figure|Fig\.)\s*S?\d+", re.IGNORECASE)
_CAPTION_PANEL = re.compile(r"\(([a-z])\)")
# Without an artist report, a panel letter is a word of one letter on its own in the PDF text.
_PANEL_TOKEN = re.compile(r"^([a-z])$")


def lint_caption(text, framework=False):
    """The caption's style problems: em dashes, British spellings, and for a framework figure a
    missing forward reference ("see also Figure N"). Empty when the caption is clean."""
    problems = []
    dashes = text.count("—")
    if dashes:
        problems.append("%d em dash(es)" % dashes)
    british = sorted({match.group(0).lower() for match in _BRITISH.finditer(text)})
    if british:
        problems.append("British spelling: %s" % ", ".join(british))
    if framework and not _FORWARD_REFERENCE.search(text):
        problems.append("a framework figure's caption needs a forward reference (see also Figure N)")
    return problems


def caption_panels(text):
    """The panel letters a caption has entries for: its `(a)`, `(b)` markers taken as the unbroken
    run from a, wherever they stand, so "(a) AUROC and (b) runtime" counts both while a unit in
    parentheses, "runtime (s)", stays outside the run of a two-panel figure."""
    letters, run = set(_CAPTION_PANEL.findall(text)), set()
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if letter not in letters:
            break
        run.add(letter)
    return run


def forbidden_tokens(text, allow=(), genes=(), datasets=()):
    """What a conceptual figure must not show: digit runs, gene names, dataset names, unless a token
    matches an `allow` pattern in full."""
    patterns = [re.compile(pattern) for pattern in allow]
    genes = set(genes)
    found = []
    for token in text.split():
        bare = token.strip(".,;:!?()[]{}\"'")
        if any(pattern.fullmatch(token) or pattern.fullmatch(bare) for pattern in patterns):
            continue
        if bare in genes:  # before digits: TP53 is a gene name first
            found.append("gene name %r" % bare)
        elif re.search(r"\d", bare):
            found.append("digits in %r" % token)
    for name in datasets:
        if re.search(r"(?<!\w)%s(?!\w)" % re.escape(name), text, re.IGNORECASE):
            found.append("dataset name %r" % name)
    return found


def _pdftotext(context, path, layout=True):
    run = context.tools.run("pdftotext", (["-layout"] if layout else []) + [str(path), "-"])
    if run.returncode != 0:
        raise ValueError("pdftotext exited %d: %s" % (run.returncode, _tail(run.stderr, 2)))
    return run.stdout


def _needs_pdf(context, check_id):
    """The final PDF, or a failed outcome saying why there is none."""
    if not context.wants("pdf"):
        return None, check_outcome(check_id, False, "this check reads the PDF, and the request's formats name none")
    pdf = context.final_file("pdf")
    if pdf is None:
        return None, check_outcome(check_id, False, "final.pdf %r is not on disk" % context.final.get("pdf"))
    return pdf, None


def _no_artists(check_id, context):
    why = ""
    if context.artists_error:
        why = " (the artist script could not describe the figure: %s)" % context.artists_error
    elif context.room_failure():
        why = " (the generator did not run in the clean room: %s)" % context.room_failure()
    return check_outcome(check_id, False, "no artist report, which only a matplotlib generator run through figures/checks/artists.py writes%s" % why)


def _shorten(items, limit=5):
    items = list(items)
    shown = "; ".join(items[:limit])
    return shown + ("; and %d more" % (len(items) - limit) if len(items) > limit else "")


# --- the checks -----------------------------------------------------------------------------------


def check_fonts_embedded(context):
    if not context.wants("pdf"):
        return check_outcome("fonts_embedded", True, "no PDF requested")
    pdf, missing = _needs_pdf(context, "fonts_embedded")
    if missing:
        return missing
    run = context.tools.run("pdffonts", [pdf])
    if run.returncode != 0:
        return check_outcome("fonts_embedded", False, "pdffonts exited %d: %s" % (run.returncode, _tail(run.stderr, 2)))
    fonts = parse_pdffonts(run.stdout)
    if not fonts:
        return check_outcome("fonts_embedded", True, "no fonts: the PDF carries no text")
    bad = ["%s is %s, embedded %s" % (font["name"], font["type"], font["emb"])
           for font in fonts if font["emb"] != "yes" or font["type"].startswith("Type 3")]
    kinds = ", ".join(sorted({font["type"] for font in fonts}))
    if bad:
        return check_outcome("fonts_embedded", False, "%d font(s) (%s); %s" % (len(fonts), kinds, _shorten(bad)))
    return check_outcome("fonts_embedded", True, "%d font(s) (%s), all embedded, none Type 3" % (len(fonts), kinds))


_PAGE_SIZE = re.compile(r"Page size:\s*([\d.]+)\s*x\s*([\d.]+)\s*pts")


def check_journal_width(context):
    if not context.wants("pdf"):
        return check_outcome("journal_width", True, "no PDF requested; the PNG's size is the resolution check's")
    pdf, missing = _needs_pdf(context, "journal_width")
    if missing:
        return missing
    run = context.tools.run("pdfinfo", [pdf])
    match = _PAGE_SIZE.search(run.stdout)
    if run.returncode != 0 or not match:
        return check_outcome("journal_width", False, "pdfinfo gave no page size: %s" % _tail(run.stderr or run.stdout, 2))
    width_mm, height_mm = (float(value) * 25.4 / 72 for value in match.groups())
    target_width = float(context.target["width_mm"])
    max_height = context.target.get("max_height_mm")
    problems = []
    if abs(width_mm - target_width) > WIDTH_TOLERANCE_MM:
        problems.append("width %.1f mm is not %.1f mm within %.1f mm" % (width_mm, target_width, WIDTH_TOLERANCE_MM))
    if max_height is not None and height_mm > float(max_height) + 0.01:
        problems.append("height %.1f mm is over the %.1f mm cap" % (height_mm, float(max_height)))
    detail = "page %.1f x %.1f mm" % (width_mm, height_mm)
    return check_outcome("journal_width", not problems, detail + ("; " + "; ".join(problems) if problems else "; within the target"))


def check_resolution(context):
    minimum = int(context.target["min_dpi"])
    width_in = float(context.target["width_mm"]) / 25.4
    parts, problems, tools = [], [], []
    if context.wants("png"):
        tools.append("png-header")
        png = context.final_file("png")
        if png is None:
            problems.append("final.png %r is not on disk" % context.final.get("png"))
        else:
            pixels = png_size(png)[0]
            dpi = pixels / width_in
            parts.append("png %d px across %.1f mm = %.0f dpi" % (pixels, float(context.target["width_mm"]), dpi))
            if (pixels + 1) / width_in < minimum:  # one pixel of rounding is not a resolution failure
                problems.append("png is %.0f dpi, under %d" % (dpi, minimum))
    if context.wants("pdf"):
        tools.append("pdfimages")
        pdf = context.final_file("pdf")
        if pdf is None:
            problems.append("final.pdf %r is not on disk" % context.final.get("pdf"))
        else:
            run = context.tools.run("pdfimages", ["-list", pdf])
            if run.returncode != 0:
                problems.append("pdfimages exited %d" % run.returncode)
            else:
                images = parse_pdfimages(run.stdout)
                low = ["%dx%d image at %dx%d ppi" % (image["width"], image["height"], image["x_ppi"], image["y_ppi"])
                       for image in images if min(image["x_ppi"], image["y_ppi"]) < minimum]
                parts.append("pdf embeds %d raster(s)" % len(images))
                if low:
                    problems.append("under %d ppi: %s" % (minimum, _shorten(low)))
    detail = "; ".join(parts + problems) or "no PDF or PNG requested"
    return check_outcome("resolution", not problems, detail, tool="+".join(tools) or None)


def check_min_font_pt(context):
    minimum = float(context.target["min_font_pt"])
    target_pt = float(context.target["width_mm"]) * 72 / 25.4
    sizes, sources = [], []
    pdf = context.final_file("pdf")
    if pdf is not None:
        facts = context.pdf_facts(pdf)
        if facts.text_sizes and facts.page_width_pt:
            scale = target_pt / facts.page_width_pt
            smallest = min(facts.text_sizes) * scale
            sizes.append(smallest)
            sources.append("PDF text walk %.2f pt" % smallest)
    artists = context.artists()
    if artists:
        texts = [text["fontsize_pt"] for text in artists.get("texts") or []]
        if texts:
            sizes.append(min(texts))
            sources.append("artists %.2f pt" % min(texts))
    if pdf is None and not artists:
        return check_outcome("min_font_pt", False, "neither a final PDF nor an artist report to read sizes from")
    if not sizes:
        return check_outcome("min_font_pt", True, "no text", tool="pdf-text-walk+artists")
    smallest = min(sizes)
    passed = smallest >= minimum - FONT_TOLERANCE_PT
    detail = "smallest %.2f pt at the target width (%s); minimum %.2f pt" % (smallest, ", ".join(sources), minimum)
    return check_outcome("min_font_pt", passed, detail, tool="pdf-text-walk+artists" if artists else "pdf-text-walk")


def check_max_words(context):
    cap = context.target.get("max_words")
    if context.request.get("kind") != "graphical_abstract" and cap is None:
        return check_outcome("max_words", True, "no word cap for a %s figure" % context.request.get("kind"))
    if cap is None:
        return check_outcome("max_words", False, "a graphical abstract needs target.max_words")
    pdf, missing = _needs_pdf(context, "max_words")
    if missing:
        return missing
    words = [token for token in _pdftotext(context, pdf, layout=False).split() if re.search(r"\w", token)]
    return check_outcome("max_words", len(words) <= int(cap), "%d words; cap %d" % (len(words), int(cap)))


def check_forbidden_text(context):
    if context.request.get("register") != "conceptual":
        return check_outcome("forbidden_text", True, "register %s: no text is forbidden" % context.request.get("register"))
    rules = context.request.get("forbidden_text") or {}
    genes = []
    if rules.get("gene_names"):
        listing = context.path(rules["gene_names"])
        if listing is None or not listing.is_file():
            return check_outcome("forbidden_text", False, "the gene name list %r is not in the project" % rules["gene_names"])
        genes = [line.strip() for line in listing.read_text(encoding="utf-8").splitlines() if line.strip()]
    allow, datasets = rules.get("allow_regex") or [], rules.get("dataset_names") or []
    pdf, missing = _needs_pdf(context, "forbidden_text")
    if missing:
        return missing
    found = ["PDF text: %s" % item for item in forbidden_tokens(_pdftotext(context, pdf), allow, genes, datasets)]
    artists = context.artists()
    if not artists:
        return _no_artists("forbidden_text", context)
    texts = artists.get("texts") or []
    found += ["artists: %s" % item for item in forbidden_tokens("\n".join(text["text"] for text in texts), allow, genes, datasets)]
    ticks = [text["text"] for text in texts if text.get("role") == "ticklabel"]
    if ticks:
        found.append("artists: %d tick label(s), e.g. %r" % (len(ticks), ticks[0]))
    detail = _shorten(found) if found else "PDF text and %d artist text(s) carry no digits, gene or dataset names, or tick labels" % len(texts)
    return check_outcome("forbidden_text", not found, detail, tool="pdftotext+artists")


def check_caption_panels(context):
    caption = context.read_final("caption")
    if caption is None:
        return check_outcome("caption_panels", False, "the caption %r is not on disk" % context.final.get("caption"))
    images = [key for key in ("pdf", "png") if context.wants(key) and context.final_file(key) is None]
    if images:
        return check_outcome("caption_panels", False, "the figure's %s is not on disk" % " and ".join(images))
    in_caption = caption_panels(caption)
    artists = context.artists()
    if artists:
        in_figure, source = {panel["label"] for panel in artists.get("panels") or []}, "artists"
    else:
        pdf, missing = _needs_pdf(context, "caption_panels")
        if missing:
            return missing
        tokens = (_PANEL_TOKEN.match(token) for token in _pdftotext(context, pdf).split())
        in_figure, source = {match.group(1) for match in tokens if match}, "pdftotext"
    if in_caption == in_figure:
        shown = ", ".join(sorted(in_figure)) or "none (a single panel)"
        return check_outcome("caption_panels", True, "panels %s in the figure and the caption" % shown, tool="caption+" + source)
    problems = []
    if in_figure - in_caption:
        problems.append("panel(s) %s have no caption entry" % ", ".join(sorted(in_figure - in_caption)))
    if in_caption - in_figure:
        problems.append("caption entries %s name no panel" % ", ".join(sorted(in_caption - in_figure)))
    return check_outcome("caption_panels", False, "; ".join(problems), tool="caption+" + source)


def check_caption_lint(context):
    caption = context.read_final("caption")
    if caption is None:
        return check_outcome("caption_lint", False, "the caption %r is not on disk" % context.final.get("caption"))
    problems = lint_caption(caption, framework=context.request.get("kind") == "framework")
    return check_outcome("caption_lint", not problems, _shorten(problems) if problems else "no em dashes, no British spellings")


def check_generator_clean(context):
    source = context.final_file("generator")
    if source is None:
        return check_outcome("generator_clean", False, "the generator %r is not on disk" % context.final.get("generator"))
    if source.suffix != ".py":
        return check_not_run("generator_clean", "generator_clean lints Python only; the generator %s is not a Python script"
                             % context.final["generator"])
    run = context.tools.run("ruff", ["check", "--isolated", "--no-cache", "--select", "F401,F841", "--output-format", "concise", source])
    problems = []
    if run.returncode != 0:
        lines = [line.replace(str(source), context.final["generator"]) for line in run.stdout.splitlines() if ": F" in line]
        problems.append("ruff: %s" % (_shorten(lines) if lines else _tail(run.stderr or run.stdout, 2)))
    context.clean_room()
    if context.room_failure():
        problems.append("the generator did not exit 0 in a fresh interpreter: %s" % context.room_failure())
    detail = _shorten(problems) if problems else "no unused imports or variables (F401, F841); exits 0 in a fresh interpreter"
    return check_outcome("generator_clean", not problems, detail, tool="ruff+python -I")


def check_regenerates(context):
    room = context.clean_room()
    if context.room_failure():
        return check_outcome("regenerates", False, "the generator did not run from its declared inputs: %s" % context.room_failure())
    minimum = float(context.policy.get("ssim_min", DEFAULT_SSIM_MIN))
    parts, problems = [], []
    if context.wants("png"):
        shipped = context.final_file("png")
        again = room.root / context.final.get("png", "") if context.final.get("png") else None
        if shipped is None or again is None or not again.is_file():
            problems.append("no PNG to compare (shipped %s, regenerated %s)" % (shipped is not None, again is not None and again.is_file()))
        else:
            width, height, first = png_luma(shipped)
            width_again, height_again, second = png_luma(again)
            if (width, height) != (width_again, height_again):
                problems.append("the regenerated PNG is %dx%d, the shipped one %dx%d" % (width_again, height_again, width, height))
            else:
                score = ssim(first, second, width, height)
                parts.append("ssim %.4f (at least %.2f)" % (score, minimum))
                if score < minimum:
                    problems.append("ssim %.4f is under %.2f" % (score, minimum))
    if context.wants("pdf"):
        shipped = context.final_file("pdf")
        again = room.root / context.final.get("pdf", "") if context.final.get("pdf") else None
        if shipped is None or again is None or not again.is_file():
            problems.append("no PDF to compare")
        else:
            if " ".join(_pdftotext(context, shipped).split()) != " ".join(_pdftotext(context, again).split()):
                problems.append("the regenerated PDF's text layer differs")
            else:
                parts.append("text layer identical")
            # The pixels too: a PDF-only figure drawn from unseeded noise keeps its text layer.
            score, why = _pdf_ssim(context, shipped, again, room.root / ".wayline")
            if score is None:
                problems.append(why)
            else:
                parts.append("pdf raster ssim %.4f" % score)
                if score < minimum:
                    problems.append("the regenerated PDF's raster ssim %.4f is under %.2f" % (score, minimum))
    detail = "; ".join(parts + problems)
    return check_outcome("regenerates", not problems, detail, tool="clean-room+ssim+pdftotext")


REGENERATE_DPI = 100  # enough pixels to see a changed mark, few enough for a standard-library SSIM


def _pdf_ssim(context, first, second, work):
    """SSIM of two PDFs' first pages rasterized in grayscale, or `(None, why)`."""
    lumas = []
    for name, pdf in (("shipped", first), ("regenerated", second)):
        stem = Path(work) / ("raster-" + name)
        run = context.tools.run("pdftoppm", ["-r", REGENERATE_DPI, "-gray", "-png", "-singlefile", pdf, stem])
        if run.returncode != 0 or not stem.with_suffix(".png").is_file():
            return None, "pdftoppm could not rasterize the %s PDF (exit %d)" % (name, run.returncode)
        lumas.append(png_luma(stem.with_suffix(".png")))
    (width, height, one), (width_again, height_again, two) = lumas
    if (width, height) != (width_again, height_again):
        return None, "the regenerated PDF rasterizes to %dx%d, the shipped one to %dx%d" % (width_again, height_again, width, height)
    return ssim(one, two, width, height), None


def check_palette(context):
    style = context.style
    if not _style_colors(style):
        return check_outcome("palette", False, "the house style has no colors (figures/style.json)")
    threshold = float(style.get("cvd_min_delta_e", DEFAULT_CVD_MIN_DELTA_E))
    allowed = _style_colors(style)
    pdf = context.final_file("pdf")
    artists = context.artists()
    if artists:
        # The report separates a colormapped artist's colors, which are its ramp's and are checked
        # as a ramp below, from the colors the figure spends one by one. The PDF cannot.
        colors = set(artists.get("colors") or [])
    elif pdf is None:
        return check_outcome("palette", False, "neither a final PDF nor an artist report to read colors from")
    else:
        facts = context.pdf_facts(pdf)
        if facts.images:
            return check_outcome("palette", False, "the PDF embeds %d raster(s) whose colormap only the artist report names" % facts.images)
        colors = set(facts.colors)
    hues = sorted(color.upper() for color in colors if not is_grey(color))
    in_style, new, problems = hue_problems(hues, style)
    ramps = set((style.get("ramp_per_quantity") or {}).values())
    if (style.get("diverging") or {}).get("cmap"):
        ramps.add(style["diverging"]["cmap"])
    cmaps = sorted({mappable["cmap"] for mappable in (artists or {}).get("mappables") or []})
    problems += ["colormap %s is not a ramp of the house style" % cmap for cmap in cmaps if cmap not in ramps]
    detail = "%d hue(s): %d from the house style, %d new" % (len(hues), len(in_style), len(new))
    if cmaps:
        detail += "; colormaps %s" % ", ".join(cmaps)
    return check_outcome("palette", not problems, detail + ("; " + _shorten(problems) if problems else ""))


def check_one_ramp_per_quantity(context):
    ramps = context.style.get("ramp_per_quantity") or {}
    problems = []
    by_ramp = {}
    for quantity, ramp in ramps.items():
        by_ramp.setdefault(ramp, []).append(quantity)
    problems += ["the house style names ramp %s for %s" % (ramp, " and ".join(sorted(quantities)))
                 for ramp, quantities in sorted(by_ramp.items()) if len(quantities) > 1]
    artists = context.artists()
    if not artists:
        return _no_artists("one_ramp_per_quantity", context)
    used = {}
    for mappable in artists.get("mappables") or []:
        quantity, cmap = mappable.get("quantity"), mappable["cmap"]
        if quantity is None:
            problems.append("a %s-colormapped artist declares no quantity (gid quantity:<name>)" % cmap)
            continue
        used.setdefault(cmap, set()).add(quantity)
        if quantity not in ramps:
            problems.append("quantity %s has no ramp in the house style" % quantity)
        elif ramps[quantity] != cmap:
            problems.append("quantity %s is drawn with %s, not its ramp %s" % (quantity, cmap, ramps[quantity]))
    problems += ["colormap %s is spent on %s" % (cmap, " and ".join(sorted(quantities)))
                 for cmap, quantities in sorted(used.items()) if len(quantities) > 1]
    structure = artists.get("structure") or []
    for item in structure:
        colored = [color for color in item.get("colors") or [] if not is_grey(color)]
        if colored:
            problems.append("%s is colored %s; structure spends no color" % (item["gid"], ", ".join(colored)))
    detail = "%d colormapped artist(s), %d structural artist(s)" % (len(artists.get("mappables") or []), len(structure))
    return check_outcome("one_ramp_per_quantity", not problems, _shorten(problems) if problems else detail, tool="style+artists")


def check_required_vs_optional_line_style(context):
    artists = context.artists()
    if not artists:
        return _no_artists("required_vs_optional_line_style", context)
    marked = artists.get("marked_lines") or []
    if not marked:
        return check_outcome("required_vs_optional_line_style", True, "no edge or curve is marked required or optional")
    problems = []
    for line in marked:
        style = line.get("linestyle")
        if line["kind"] == "required" and style != "solid":
            problems.append("%s is required but drawn %s" % (line["gid"], style))
        elif line["kind"] == "optional" and style in ("solid", "none"):
            problems.append("%s is optional but drawn %s" % (line["gid"], style))
    detail = _shorten(problems) if problems else "%d marked line(s): required solid, optional dashed" % len(marked)
    return check_outcome("required_vs_optional_line_style", not problems, detail)


def check_selection_representativeness(context):
    statistics = context.result.get("selection_statistics") or []
    if not statistics:
        return check_outcome("selection_representativeness", True, "no displayed subset is declared")
    problems, shown = [], []
    for entry in statistics:
        try:
            gap = abs(float(entry["displayed"]) - float(entry["global"]))
            tolerance = float(entry["tolerance"])
        except (KeyError, TypeError, ValueError):
            problems.append("panel %s declares no displayed, global, and tolerance" % entry.get("panel"))
            continue
        line = "panel %s %s: displayed %g, global %g" % (entry.get("panel"), entry.get("criterion"), float(entry["displayed"]), float(entry["global"]))
        if gap > tolerance + 1e-12:
            problems.append("%s, off by %g, over the tolerance %g" % (line, gap, tolerance))
        else:
            shown.append("%s, within %g" % (line, tolerance))
    return check_outcome("selection_representativeness", not problems, _shorten(problems or shown))


def check_schematic_disclosed(context):
    elements = context.result.get("schematic_elements") or []
    if not elements:
        return check_outcome("schematic_disclosed", True, "no schematic element is declared")
    caption, notes, generator = context.read_final("caption"), context.read_final("notes"), context.read_final("generator")
    missing = [key for key, text in (("caption", caption), ("notes", notes), ("generator", generator)) if text is None]
    if missing:
        return check_outcome("schematic_disclosed", False, "not on disk: %s" % ", ".join(missing))
    comments = [comment.lower() for comment in re.findall(r"#\s*schematic:\s*(.*)", generator)]
    problems = []
    for entry in elements:
        element = entry.get("element", "")
        if entry.get("caption_phrase", "").lower() not in caption.lower():
            problems.append("the caption does not say %r for %s" % (entry.get("caption_phrase"), element))
        if element.lower() not in notes.lower():
            problems.append("the notes do not name %s" % element)
        if not any(element.lower() in comment for comment in comments):
            problems.append("the generator has no '# schematic: %s' comment" % element)
    detail = _shorten(problems) if problems else "%d schematic element(s) named in the caption, the notes, and the generator" % len(elements)
    return check_outcome("schematic_disclosed", not problems, detail)


def check_mixed_data_disclosed(context):
    scopes = {}
    for entry in context.final.get("inputs") or []:
        for panel in entry.get("panels") or ["*"]:
            scopes.setdefault(panel, set()).add(entry.get("path"))  # an artifact, not a run: one run writes several
    for panel in scopes:
        if panel != "*":
            scopes[panel] |= scopes.get("*", set())
    mixed = {panel: runs for panel, runs in scopes.items() if len(runs) > 1 and (panel != "*" or len(scopes) == 1)}
    if not mixed:
        return check_outcome("mixed_data_disclosed", True, "no panel draws from more than one result artifact")
    where = "; ".join("%s from %s" % ("the figure" if panel == "*" else "panel " + panel, ", ".join(sorted(map(str, runs))))
                      for panel, runs in sorted(mixed.items()))
    caption = context.read_final("caption")
    if caption is None:
        return check_outcome("mixed_data_disclosed", False, "%s, and the caption is not on disk" % where)
    if MIXED_DATA_MARKER in caption:
        return check_outcome("mixed_data_disclosed", True, "%s; the caption carries %s" % (where, MIXED_DATA_MARKER))
    return check_outcome("mixed_data_disclosed", False, "%s; the caption does not carry %s" % (where, MIXED_DATA_MARKER))


def check_crops(context):
    pdf, missing = _needs_pdf(context, "crops")
    if missing:
        return missing
    facts = context.pdf_facts(pdf)
    if not facts.page_width_pt:
        return check_outcome("crops", False, "the PDF has no MediaBox to crop against")
    dpi = int(context.policy.get("crops_dpi", DEFAULT_CROPS_DPI))
    width_px, height_px = facts.page_width_pt / 72 * dpi, facts.page_height_pt / 72 * dpi
    artists = context.artists()
    panels = (artists or {}).get("panels") or []
    regions = [(panel["label"], panel["bbox"]) for panel in panels] or [("full", [0.0, 0.0, 1.0, 1.0])]
    directory = pdf.parent / "crops"
    directory.mkdir(parents=True, exist_ok=True)
    made, problems = [], []
    for label, (x0, y0, x1, y1) in regions:
        left, top = max(0, math.floor(x0 * width_px)), max(0, math.floor((1 - y1) * height_px))
        width = max(1, min(math.ceil((x1 - x0) * width_px), math.ceil(width_px) - left))
        height = max(1, min(math.ceil((y1 - y0) * height_px), math.ceil(height_px) - top))
        stem = directory / label
        run = context.tools.run("pdftoppm", ["-r", dpi, "-png", "-singlefile", "-x", left, "-y", top, "-W", width, "-H", height, pdf, stem])
        crop = stem.with_suffix(".png")
        if run.returncode != 0 or not crop.is_file():
            problems.append("%s: pdftoppm exited %d" % (label, run.returncode))
            continue
        made.append(crop.relative_to(context.project).as_posix())
    detail = "%d crop(s) at %d dpi: %s" % (len(made), dpi, ", ".join(made))
    return check_outcome("crops", not problems and bool(made), detail + ("; " + _shorten(problems) if problems else ""))


def check_text_overlap(context):
    artists = context.artists()
    if not artists:
        return _no_artists("text_overlap", context)
    figure = artists.get("figure") or {}
    width, height = figure.get("width_px"), figure.get("height_px")
    texts = [text for text in artists.get("texts") or [] if _area(text["extent"]) > 0]
    problems = []
    for text in texts:
        x0, y0, x1, y1 = text["extent"]
        if width and height and (x0 < -EDGE_TOLERANCE_PX or y0 < -EDGE_TOLERANCE_PX or x1 > width + EDGE_TOLERANCE_PX or y1 > height + EDGE_TOLERANCE_PX):
            problems.append("%r is clipped at the figure's edge" % text["text"])
    for index, first in enumerate(texts):
        for second in texts[index + 1:]:
            shared = _intersection(first["extent"], second["extent"])
            if shared > 1 and shared > OVERLAP_FRACTION * min(_area(first["extent"]), _area(second["extent"])):
                problems.append("%r and %r overlap" % (first["text"], second["text"]))
    detail = _shorten(problems) if problems else "%d text(s), none clipped or overlapping" % len(texts)
    return check_outcome("text_overlap", not problems, detail)


def _area(extent):
    x0, y0, x1, y1 = extent
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _intersection(first, second):
    return _area((max(first[0], second[0]), max(first[1], second[1]), min(first[2], second[2]), min(first[3], second[3])))


def check_provenance(context):
    inputs = context.final.get("inputs") or []
    if not inputs:
        return check_outcome("provenance", False, "final.inputs is empty: nothing traces the figure to a run")
    manifest = {entry["path"]: entry for entry in read_manifest(context.project).get("entries", [])}
    problems = []
    for entry in inputs:
        relative, digest, run_id = entry.get("path"), entry.get("sha256"), entry.get("run_id")
        path = context.path(relative)
        if path is None or not path.is_file():
            problems.append("%s is not a file in the project" % relative)
            continue
        if sha256_of(path) != digest:
            problems.append("%s does not match its sha256" % relative)
        if not RUN_ID_RE.match(run_id or ""):
            problems.append("%s names run %r, not t<ticket>-a<attempt>" % (relative, run_id))
        manifested = manifest.get(Path(relative).as_posix())
        if manifested is None:
            problems.append("%s is not in research/manifest.json" % relative)
        elif manifested.get("sha256") != digest or manifested.get("run_id") != run_id:
            problems.append("%s is manifested as run %s with another hash or run" % (relative, manifested.get("run_id")))
    detail = _shorten(problems) if problems else "%d input(s), each on disk, hashed, and manifested to its run" % len(inputs)
    return check_outcome("provenance", not problems, detail, tool="sha256+manifest")


CHECKS = {
    "fonts_embedded": check_fonts_embedded,
    "journal_width": check_journal_width,
    "resolution": check_resolution,
    "min_font_pt": check_min_font_pt,
    "max_words": check_max_words,
    "forbidden_text": check_forbidden_text,
    "caption_panels": check_caption_panels,
    "caption_lint": check_caption_lint,
    "generator_clean": check_generator_clean,
    "regenerates": check_regenerates,
    "palette": check_palette,
    "one_ramp_per_quantity": check_one_ramp_per_quantity,
    "required_vs_optional_line_style": check_required_vs_optional_line_style,
    "selection_representativeness": check_selection_representativeness,
    "schematic_disclosed": check_schematic_disclosed,
    "mixed_data_disclosed": check_mixed_data_disclosed,
    "crops": check_crops,
    "text_overlap": check_text_overlap,
    "provenance": check_provenance,
}
