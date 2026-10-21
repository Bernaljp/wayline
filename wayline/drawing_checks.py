"""The machine checks a drawing's plots get at acceptance (Implementation Decision 17; ticket 100).

A drawing's script is rerun in a clean room (`rerun`): a fresh directory holding only the manifested artifacts it
declared, at their manifest paths, and the script in its drawing directory, run with `-I` in the tools venv's Python
(the one interpreter for drawings, figure scripts, and the checks' clean room), CPU only, with `WAYLINE_PROJECT` naming
the room. What it writes there is compared with what the plotter left: each PNG byte for byte or else by SSIM at
`policy.figures.ssim_min`, each CSV byte for byte, and `numbers.json` value for value.

Every plot then gets six of the figure checks, read off its SVG rather than an artist report, so they hold for
whatever library drew it:

- `min_font_pt`: no text under the house style's `min_font_pt` (6 pt when it names none);
- `text_overlap`: no two texts whose boxes overlap by more than a tenth of the smaller, and none past the canvas;
- `palette`: every hue the house style does not name stays apart from every other under the three color-vision
  deficiencies by the style's `cvd_min_delta_e`; a plot spending more distinct hues than `RAMP_MIN` is drawing a
  colormap, whose ramp the SVG cannot name, and says so;
- `generator_clean`: no unused import or variable (`ruff`, F401 and F841), and the script exits 0 in the clean room;
  Python only, so another script is not run;
- `regenerates`: the rerun drew the same plot;
- `provenance`: every artifact the plot reads is in `research/manifest.json` and still has its hash;

and the five readability checks of `wayline.plot_checks`. The numbers check closes the list: every number its
Purpose, Data, and What it shows quote must be a value `numbers.json` holds (`numbers_problems`). A check that cannot
run (no interpreter for the script, no `ruff`, text a writer drew as outlines) is `not run` with the reason, never
passed or failed.
"""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from wayline import figure_checks, numbers, plot_checks
from wayline.figure_checks import check_not_run, check_outcome

__all__ = [
    "SIX", "CHECK_IDS", "NUMBERS", "RAMP_MIN", "DEFAULT_MIN_FONT_PT", "Room", "rerun", "same_png",
    "plot_checks_for", "numbers_problems", "values_of", "read_numbers", "outcome", "not_run", "generator_clean", "check_provenance",
]

SIX = ("min_font_pt", "text_overlap", "palette", "generator_clean", "regenerates", "provenance")
NUMBERS = "numbers"
CHECK_IDS = SIX + plot_checks.READABILITY_CHECK_IDS + (NUMBERS,)
DEFAULT_MIN_FONT_PT = 6.0
RAMP_MIN = 16  # this many distinct hues or more are a colormap's ramp, not colors spent one by one
OVERLAP_FRACTION = figure_checks.OVERLAP_FRACTION
RERUN_SECONDS = 600
_TOOL = {"min_font_pt": "svg-text", "text_overlap": "svg-text", "palette": "svg-colors+cvd-ciede2000", "generator_clean": "ruff+python -I",
         "regenerates": "clean-room", "provenance": "sha256+manifest", NUMBERS: "numbers.json"}
_HEX = re.compile(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
_RGB = re.compile(r"rgb\(\s*([0-9.]+%?)\s*,\s*([0-9.]+%?)\s*,\s*([0-9.]+%?)\s*\)")
_UNIT = re.compile(r"^\s*([0-9.]+)\s*(pt|px|in|cm|mm)?\s*$")


def outcome(check_id, passed, detail):
    """One check's entry, `{id, type: "A", pass, tool, detail}`, with the tool this module reads it with."""
    return check_outcome(check_id, passed, detail, tool=_TOOL.get(check_id))


def not_run(check_id, reason):
    """The entry of a check that cannot run: listed as not run with the reason, never passed or failed."""
    return check_not_run(check_id, reason, tool=_TOOL.get(check_id))


# --- the clean room ------------------------------------------------------------------------------------------------


@dataclass
class Room:
    """One rerun of a drawing's script: its exit, why it could not run or failed, and the room it wrote into."""

    returncode: object  # int, or None when it never ran
    error: str
    root: object = None
    ran: bool = True  # False when no interpreter for the script was there to run it

    @property
    def failed(self):
        return self.ran and self.returncode != 0

    def close(self):
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)


def rerun(project, source, folder, script, inputs, python, timeout=RERUN_SECONDS):
    """Rerun `script` from the drawing directory `source` in a fresh room, where it stands at `folder/script`.

    The room holds the declared `inputs`, copied from the project at their manifest paths, and the script in its
    drawing directory (`folder`, relative to the project); nothing else. `python` is the plotting library's
    interpreter (ticket 102): a Python script runs in it with `-I`, an R script (`.R`) with `--vanilla` as its
    Rscript; anything else is not run.
    """
    suffix = Path(str(script)).suffix
    if suffix not in (".py", ".R"):
        return Room(None, "the clean room reruns a Python or an R script; %s is neither, so it was not rerun" % script, ran=False)
    if not python:
        return Room(None, "no interpreter: the plotting library's tools are not installed (wayline switch --plotting, "
                          "or wayline tools install)", ran=False)
    project = Path(project)
    root = Path(tempfile.mkdtemp(prefix="wayline-drawing-"))
    for relative in inputs:
        original = project / relative
        if original.is_file():
            copy = root / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, copy)
    target = root / folder / script
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(source) / script, target)
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "wayline" / "mplconfig"
    cache.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root), "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(cache),
           "SOURCE_DATE_EPOCH": "0", "PYTHONHASHSEED": "0", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "CUDA_VISIBLE_DEVICES": "",
           "WAYLINE_PROJECT": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        done = subprocess.run([str(python), "-I" if suffix == ".py" else "--vanilla", str(target)], cwd=str(root), env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return Room(None, "the script did not finish in %d s" % timeout, root)
    except OSError as failure:
        return Room(None, "could not start %s: %s" % (python, failure), root)
    tail = " | ".join([line for line in (done.stderr or "").splitlines() if line.strip()][-6:])
    return Room(done.returncode, tail, root)


def same_png(shipped, again, ssim_min):
    """`(same, detail)`: two PNGs byte for byte, else by SSIM over their luma at `ssim_min`."""
    if not Path(again).is_file():
        return False, "the rerun wrote no %s" % Path(again).name
    if Path(shipped).read_bytes() == Path(again).read_bytes():
        return True, "the rerun wrote the same PNG, byte for byte"
    try:
        width, height, first = figure_checks.png_luma(shipped)
        width_again, height_again, second = figure_checks.png_luma(again)
    except (figure_checks.PngError, OSError, ValueError) as failure:
        return False, "the PNGs could not be compared: %s" % failure
    if (width, height) != (width_again, height_again):
        return False, "the rerun's PNG is %dx%d, the drawing's %dx%d" % (width_again, height_again, width, height)
    score = figure_checks.ssim(first, second, width, height)
    return score >= ssim_min, "ssim %.4f (at least %.2f)" % (score, ssim_min)


# --- the SVG checks ------------------------------------------------------------------------------------------------


def _unit_scale(svg_path):
    """Points per canvas unit, from the root's width and viewBox: 1 for matplotlib's points, 0.75 for pixels."""
    try:
        root = ElementTree.parse(str(svg_path)).getroot()
    except (OSError, ElementTree.ParseError):
        return 1.0
    found = _UNIT.match(root.get("width") or "")
    box = (root.get("viewBox") or "").replace(",", " ").split()
    if not found:
        return 0.75
    value, unit = float(found.group(1)), found.group(2) or "px"
    per_unit = {"pt": 1.0, "px": 0.75, "in": 72.0, "cm": 72 / 2.54, "mm": 72 / 25.4}[unit]
    width_units = float(box[2]) if len(box) == 4 else value
    return value * per_unit / width_units if width_units else per_unit


def _text_box(text):
    # The writer's width where it gives one, unless the text is a mathtext source, whose drawn characters are fewer.
    estimate = plot_checks.TEXT_WIDTH_PER_SIZE * text.size * len(plot_checks.drawn_text(text.text))
    width = min(text.width, estimate) if text.width else estimate
    start = {"start": 0.0, "middle": -0.5, "end": -1.0}.get(text.anchor, 0.0) * width
    if text.rotated:
        radians = math.radians(text.angle)
        corners = [(text.x + math.cos(radians) * along - math.sin(radians) * up, text.y + math.sin(radians) * along + math.cos(radians) * up)
                   for along in (start, start + width) for up in (-0.8 * text.size, 0.2 * text.size)]
        xs, ys = [point[0] for point in corners], [point[1] for point in corners]
        return (min(xs), min(ys), max(xs), max(ys))
    return (text.x + start, text.y - 0.8 * text.size, text.x + start + width, text.y + 0.2 * text.size)


def _area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _shared(first, second):
    return _area((max(first[0], second[0]), max(first[1], second[1]), min(first[2], second[2]), min(first[3], second[3])))


def _shorten(items, limit=4):
    items = list(items)
    return "; ".join(items[:limit]) + ("; and %d more" % (len(items) - limit) if len(items) > limit else "")


def check_min_font_pt(plot, svg_path, style):
    if not plot.text_readable:
        return not_run("min_font_pt", "the %s SVG draws its text as outlines with no string, so its sizes cannot be read" % plot.writer)
    minimum = float((style or {}).get("min_font_pt") or DEFAULT_MIN_FONT_PT)
    scale = _unit_scale(svg_path)  # one parse of the root, however many texts the plot holds
    sizes = [text.size * scale for text in plot.texts if text.text.strip() and text.size]
    if not sizes:
        return outcome("min_font_pt", True, "no text")
    smallest = min(sizes)
    return outcome("min_font_pt", smallest >= minimum - figure_checks.FONT_TOLERANCE_PT,
                    "smallest %.2f pt; the house style's minimum %.2f pt" % (smallest, minimum))


def check_text_overlap(plot, svg_path, style):
    if not plot.text_readable:
        return not_run("text_overlap", "the %s SVG draws its text as outlines with no string, so its boxes cannot be read" % plot.writer)
    texts = [(text, _text_box(text)) for text in plot.texts if text.text.strip()]
    problems = []
    for text, box in texts:
        if box[0] < -figure_checks.EDGE_TOLERANCE_PX or box[1] < -figure_checks.EDGE_TOLERANCE_PX \
                or box[2] > plot.width + figure_checks.EDGE_TOLERANCE_PX or box[3] > plot.height + figure_checks.EDGE_TOLERANCE_PX:
            problems.append("%r runs past the canvas" % text.text)
    for index, (first, one) in enumerate(texts):
        for second, two in texts[index + 1:]:
            shared = _shared(one, two)
            if shared > 1 and shared > OVERLAP_FRACTION * min(_area(one), _area(two)):
                problems.append("%r and %r overlap" % (first.text, second.text))
    detail = _shorten(problems) if problems else "%d text(s), none past the canvas or overlapping" % len(texts)
    return outcome("text_overlap", not problems, detail)


def _colors(svg_path):
    """Every color the SVG paints with, as `#RRGGBB`: fill and stroke attributes and style declarations."""
    try:
        root = ElementTree.parse(str(svg_path)).getroot()
    except (OSError, ElementTree.ParseError):
        return set()
    found = set()
    for element in root.iter():
        values = [element.get(name) or "" for name in ("fill", "stroke", "stop-color", "color")] + [element.get("style") or ""]
        for value in values:
            for match in _HEX.finditer(value):
                digits = match.group(1)
                found.add("#" + (digits if len(digits) == 6 else "".join(char * 2 for char in digits)).upper())
            for match in _RGB.finditer(value):
                channels = [float(part[:-1]) * 2.55 if part.endswith("%") else float(part) for part in match.groups()]
                found.add("#%02X%02X%02X" % tuple(int(round(min(255, max(0, channel)))) for channel in channels))
    return found


def check_palette(plot, svg_path, style):
    """The figure checks' palette rule (`figure_checks.hue_problems`) over the hues the SVG paints with."""
    if not figure_checks.style_colors(style or {}):
        return outcome("palette", False, "the house style has no colors (figures/style.json)")
    hues = sorted(color for color in _colors(svg_path) if not figure_checks.is_grey(color))
    if len(hues) >= RAMP_MIN:
        return outcome("palette", True, "%d hues: a colormap's ramp, which the SVG does not name, so its ramp is not checked here" % len(hues))
    in_style, new, problems = figure_checks.hue_problems(hues, style or {})
    detail = "%d hue(s): %d from the house style, %d new" % (len(hues), len(in_style), len(new))
    return outcome("palette", not problems, detail + ("; " + _shorten(problems) if problems else ""))


def generator_clean(script_path, room):
    """The `generator_clean` outcome of one script, shared by every plot it draws."""
    script_path = Path(script_path)
    if script_path.suffix != ".py":
        return not_run("generator_clean", "generator_clean lints Python only; the script %s is not a Python script" % script_path.name)
    problems, notes = [], []
    tools = figure_checks.Tools()
    try:
        run = tools.run("ruff", ["check", "--isolated", "--no-cache", "--select", "F401,F841", "--output-format", "concise", script_path])
    except figure_checks.ToolMissing:
        run = None
        notes.append("ruff is not installed, so the lint did not run")
    except (OSError, subprocess.SubprocessError) as failure:
        run = None
        notes.append("ruff could not run: %s" % failure)
    if run is not None and run.returncode != 0:
        lines = [line.replace(str(script_path), script_path.name) for line in run.stdout.splitlines() if ": F" in line]
        problems.append("ruff: %s" % (_shorten(lines) if lines else (run.stderr or run.stdout).strip()[:200]))
    if not room.ran:
        notes.append(room.error)
    elif room.failed:
        problems.append("the script did not exit 0 in a fresh interpreter: %s" % (room.error or "exit %s" % room.returncode))
    if problems:
        return outcome("generator_clean", False, _shorten(problems + notes))
    if run is None and not room.ran:
        return not_run("generator_clean", _shorten(notes))
    detail = "; ".join(part for part in (
        "no unused imports or variables (F401, F841)" if run is not None else None,
        "exits 0 in a fresh interpreter" if room.ran else None) if part)
    return outcome("generator_clean", True, detail + ("; " + _shorten(notes) if notes else ""))


def check_provenance(project, inputs, manifest):
    """Every artifact a plot reads is manifested and still has the manifest's hash."""
    from wayline.provenance import sha256_of
    if not inputs:
        return outcome("provenance", False, "the plot names no input: nothing traces it to a run")
    problems = []
    for relative in inputs:
        entry = manifest.get(relative)
        path = Path(project) / relative
        if entry is None:
            problems.append("%s is not in research/manifest.json" % relative)
        elif not path.is_file():
            problems.append("%s is not a file in the project" % relative)
        elif sha256_of(path) != entry.get("sha256"):
            problems.append("%s no longer has the hash the manifest holds for run %s" % (relative, entry.get("run_id")))
    detail = _shorten(problems) if problems else "%d input(s), each manifested with its hash" % len(inputs)
    return outcome("provenance", not problems, detail)


def plot_checks_for(plot_svg, style, policy, script_outcome, regenerates, provenance, number_problems):
    """Every check of one plot, in `CHECK_IDS` order, from its SVG and the outcomes the drawing shares."""
    try:
        plot = plot_checks.read_svg(plot_svg)
    except (OSError, ElementTree.ParseError) as failure:
        plot = None
        unreadable = "the SVG %s could not be read: %s" % (Path(plot_svg).name, failure)
    report = []
    for check_id, function in (("min_font_pt", check_min_font_pt), ("text_overlap", check_text_overlap), ("palette", check_palette)):
        report.append(outcome(check_id, False, unreadable) if plot is None else function(plot, plot_svg, style))
    report += [script_outcome, regenerates, provenance]
    report += plot_checks.run_readability_checks(plot_svg, policy)
    report.append(outcome(NUMBERS, not number_problems, _shorten(number_problems) if number_problems
                           else "every number it quotes is a value in numbers.json"))
    return report


# --- the numbers ---------------------------------------------------------------------------------------------------


def values_of(data):
    """Every number `numbers.json` holds, however deep."""
    if isinstance(data, bool) or data is None:
        return []
    if isinstance(data, (int, float)):
        return [float(data)]
    if isinstance(data, str):
        return [number.value for number in numbers.numbers_in(data)]
    if isinstance(data, dict):
        return [value for child in data.values() for value in values_of(child)]
    if isinstance(data, list):
        return [value for child in data for value in values_of(child)]
    return []


def numbers_problems(texts, values, exempt=()):
    """The numbers in `texts` (`[(label, text)]`) that are no value of `values`, each as `label quotes N`."""
    problems = []
    for label, text in texts:
        for number in numbers.numbers_in(text, exempt):
            if not numbers.matches(number, values):
                problems.append("%s quotes %s, which numbers.json does not hold" % (label, number.raw))
    return problems


def read_numbers(path):
    """`numbers.json` parsed, or `(None, why)`."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except OSError:
        return None, "%s is not there" % Path(path).name
    except ValueError as failure:
        return None, "%s is not JSON: %s" % (Path(path).name, failure)
