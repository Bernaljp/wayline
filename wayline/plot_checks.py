"""The five readability checks on a plot's SVG (Implementation Decision 17; ticket 77).

From the owner's notes on the research report prototype (`reaction.md` on the branch
`prototype/research-report`), five Type-A gates a plot must pass to be read at all, beside the
six figure checks a drawing uses (`wayline.figure_checks`):

- `rotated_text`: no rotated text but the y-axis label ("I usually discourage text sideways");
- `axis_label_length`: no axis label over `policy.plot_checks.axis_label_max_chars` (40)
  characters ("the x label is a whole caption");
- `stacked_titles`: no figure title above titled panels ("the figure title overlaps the plot
  titles");
- `heatmap_cell_labels`: a heatmap's cells carry labels only up to
  `policy.plot_checks.heatmap_label_max_cells` (36) cells ("heatmaps with too much text inside
  are complicated"); a grid of equal filled cells is a heatmap, and so is a raster (`imshow`) with
  labels inside it, its cells counted by its labels;
- `flat_summary_mark`: no flat summary mark ("boxplots are good, except when they are flat"): a
  box, or any rectangle a summary is drawn as, collapsed under one unit along one side. A thin
  rectangle with an edge on another rectangle's edge line in its panel is a bar of a tiny value,
  a stacked bar's segment, or a histogram's bin, not a summary; Vega names its boxes outright.

**The SVG every library writes.** The checks read the plot's SVG, never an artist report, so
they hold for whatever drew it. `read_svg` walks the document with every transform applied and
recognizes the writer, because the roles a check needs (which text is the y-axis label, which a
panel title) are written differently by each:

- matplotlib (and seaborn through it): the `figure_1`, `axes_N`, `matplotlib.axis_N`,
  `xtick_N`/`ytick_N`, and `legend_N` group ids; its text is either `<text>` (`svg.fonttype:
  none`) or, by default, glyph outlines whose string matplotlib writes as a comment;
- Vega (Altair through vl-convert): the `role-axis-title`, `role-title`, `role-scope`, and
  header classes, the axes' `aria-label`, and each mark's `aria-roledescription`;
- svglite (ggplot2's `ggsave` to `.svg`): no names at all, so roles are read from geometry: a
  clip region holding marks is a panel, one holding only text over its own background is a
  facet strip, and the text outside every panel is a title above them, an axis label on the
  outer side of the tick labels, or a legend on the right;
- cairo (R's own `svg()` device): every glyph an outline with no string, so the four checks
  that read text cannot run.

A check that cannot run on a plot is reported `not run` with the reason
(`figure_checks.check_not_run`): never passed, never failed. The two geometric checks run on any
writer; the three that need text roles run only where the writer's roles can be read.
"""

import json
import math
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

from wayline import POLICY_PATH
from wayline.figure_checks import check_not_run, check_outcome

__all__ = [
    "READABILITY_CHECK_IDS", "READABILITY_CHECKS", "DEFAULT_AXIS_LABEL_MAX_CHARS", "DEFAULT_HEATMAP_LABEL_MAX_CELLS",
    "PlotSvg", "SvgText", "SvgShape", "read_svg", "run_readability_checks",
    "check_rotated_text", "check_axis_label_length", "check_stacked_titles", "check_heatmap_cell_labels",
    "check_flat_summary_mark",
]

READABILITY_CHECK_IDS = ("rotated_text", "axis_label_length", "stacked_titles", "heatmap_cell_labels", "flat_summary_mark")

DEFAULT_AXIS_LABEL_MAX_CHARS = 40
DEFAULT_HEATMAP_LABEL_MAX_CELLS = 36

ROTATION_TOLERANCE_DEG = 0.5
FLAT_UNITS = 1.0  # a summary rectangle thinner than one SVG unit along a side is drawn as a line
MIN_MARK_UNITS = 2.0  # and the other side is long enough to be a mark, not a speck
CELL_TOLERANCE = 0.5  # two cells this close in size, or edges this close, are one size or touch
CELL_GAP = 0.25  # of a cell's size: the most space a heatmap leaves between neighbouring cells
TEXT_WIDTH_PER_SIZE = 0.55  # an estimated glyph advance, used only where the writer gives no textLength
FULL_CANVAS = 0.95  # a clip region covering this much of the canvas is the canvas, not a panel

_SKIPPED = {"defs", "clipPath", "mask", "marker", "pattern", "symbol", "metadata", "style", "title", "desc", "linearGradient", "radialGradient"}
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBERS = re.compile(_NUMBER)
_PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUMBER)
_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_URL = re.compile(r"url\(\s*#([^)\s]+)\s*\)")
_FONT_SIZE = re.compile(r"(" + _NUMBER + r")\s*(px|pt)?")
_MPL_TEXT = re.compile(r"^text_\d+$")
_MPL_AXES = re.compile(r"^axes_\d+$")
_MPL_AXIS = re.compile(r"^matplotlib\.axis_\d+$")
_MPL_TICK = re.compile(r"^([xy])tick_\d+$")
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# --- the reader -----------------------------------------------------------------------------------


@dataclass
class SvgText:
    """One piece of text: its string, where it is, how it is turned, and what the writer made it."""

    text: str
    x: float  # the anchor, in canvas units
    y: float
    angle: float  # degrees, the baseline's direction (-90 reads bottom to top)
    size: float
    anchor: str = "start"
    width: float = 0.0
    groups: tuple = ()  # the ancestor groups, outermost first, as (id, class, aria-label)
    clip: object = None  # the nearest clip region id
    role: str = "other"  # tick, axis_label, panel_title, figure_title, legend, annotation, other
    axis: object = None  # x or y, for a tick or an axis label

    @property
    def rotated(self):
        turned = abs(((self.angle + 180) % 360) - 180)
        return turned > ROTATION_TOLERANCE_DEG

    @property
    def center(self):
        """The middle of the text's estimated box."""
        shift = {"start": 0.5, "middle": 0.0, "end": -0.5}.get(self.anchor, 0.5) * self.width
        radians = math.radians(self.angle)
        along = (math.cos(radians), math.sin(radians))
        up = (along[1], -along[0])  # toward the text's top, in a y-down canvas
        lift = 0.35 * self.size
        return (self.x + along[0] * shift + up[0] * lift, self.y + along[1] * shift + up[1] * lift)


@dataclass
class SvgShape:
    """One drawn subpath, rectangle, polygon, polyline, or line, in canvas units."""

    points: list
    closed: bool
    filled: bool
    groups: tuple = ()
    clip: object = None
    role_description: object = None  # Vega's aria-roledescription

    @property
    def bbox(self):
        xs, ys = [point[0] for point in self.points], [point[1] for point in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def is_rectangle(self):
        """Closed, at least four vertices, each on a corner of its axis-aligned box."""
        if not self.closed or len(self.points) < 4:
            return False
        x0, y0, x1, y1 = self.bbox
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for px, py in self.points:
            if not any(abs(px - cx) <= CELL_TOLERANCE and abs(py - cy) <= CELL_TOLERANCE for cx, cy in corners):
                return False
        return True


@dataclass
class PlotSvg:
    """What `read_svg` found: the writer, the canvas, the texts with roles, the shapes, the panels."""

    writer: str  # matplotlib, vega, svglite, cairo, or unknown
    width: float
    height: float
    texts: list = field(default_factory=list)
    shapes: list = field(default_factory=list)
    panels: list = field(default_factory=list)  # (x0, y0, x1, y1) of each panel
    outlined_glyphs: int = 0  # glyphs drawn as outlines with no string beside them
    images: list = field(default_factory=list)  # (x0, y0, x1, y1) of each embedded raster

    @property
    def text_readable(self):
        return self.writer != "cairo" and not (self.outlined_glyphs and not self.texts)

    @property
    def roles_read(self):
        return self.writer in ("matplotlib", "vega", "svglite")


class _Walker:
    def __init__(self, root):
        self.root = root
        self.texts, self.shapes, self.images = [], [], []
        self.clips = {}
        self.outlined_glyphs = 0
        self.mpl_axes = {}  # axes group id -> panel box
        self.mpl_axis_ticks = {}  # axis group id -> "x" or "y", from its ticks
        self.mpl_axis_order = {}  # axis group id -> (axes id, ordinal)
        self.vega = False

    def walk(self):
        for element in self.root.iter():
            if _local(element.tag) == "clipPath" and element.get("id"):
                for child in element:
                    if _local(child.tag) == "rect":
                        x0, y0, x1, y1 = _rect_box(child, _transform(element.get("transform")))
                        self.clips[element.get("id")] = (x0, y0, x1, y1)
        self._visit(self.root, IDENTITY, (), None, {"fill": "black"})

    def _visit(self, element, matrix, groups, clip, style):
        tag = _local(element.tag) if isinstance(element.tag, str) else None
        if tag is None or tag in _SKIPPED:
            return
        if element.get("display") == "none":
            return
        matrix = _multiply(matrix, _transform(element.get("transform")))
        style = _cascade(style, element)
        clip_id = _clip_id(element)
        clip = clip_id if clip_id else clip
        if tag == "g" or tag == "svg" or tag == "a":
            if tag == "g":
                entry = (element.get("id") or "", element.get("class") or "", element.get("aria-label") or "")
                groups = groups + (entry,)
                if "mark-" in entry[1] or "role-" in entry[1]:
                    self.vega = True
                self._note_matplotlib(element, entry[0], groups)
                if entry[0] and _MPL_TEXT.match(entry[0]) and self._matplotlib_glyph_text(element, matrix, groups, clip):
                    return
            for child in element:
                self._visit(child, matrix, groups, clip, style)
            return
        if tag == "text":
            self._text(element, matrix, groups, clip, style)
        elif tag == "use":
            href = element.get("{http://www.w3.org/1999/xlink}href") or element.get("href") or ""
            if "glyph" in href:
                self.outlined_glyphs += 1
        elif tag in ("path", "rect", "polygon", "polyline", "line", "circle", "ellipse"):
            self._shape(tag, element, matrix, groups, clip, style)
        elif tag == "image":
            corners = _rect_box(element, matrix)
            self.images.append(corners)
            self.shapes.append(SvgShape([(corners[0], corners[1]), (corners[2], corners[3])], False, False, groups, clip, "image"))

    def _note_matplotlib(self, element, identifier, groups):
        if _MPL_AXIS.match(identifier):
            axes = next((gid for gid, _, _ in reversed(groups[:-1]) if _MPL_AXES.match(gid)), None)
            ordinal = sum(1 for key, (owner, _) in self.mpl_axis_order.items() if owner == axes)
            self.mpl_axis_order[identifier] = (axes, ordinal)
        tick = _MPL_TICK.match(identifier)
        if tick:
            axis = next((gid for gid, _, _ in reversed(groups[:-1]) if _MPL_AXIS.match(gid)), None)
            if axis:
                self.mpl_axis_ticks.setdefault(axis, tick.group(1))

    def _matplotlib_glyph_text(self, element, matrix, groups, clip):
        """A matplotlib `text_N` group drawn as glyph outlines: its string is the comment it opens with."""
        children = list(element)
        if not children or children[0].tag is not ElementTree.Comment:
            return False
        if any(_local(node.tag) == "text" for node in element.iter() if isinstance(node.tag, str)):
            return False
        string = (children[0].text or "").strip()
        inner = next((child for child in children[1:] if isinstance(child.tag, str) and _local(child.tag) == "g"), None)
        placed = _multiply(matrix, _transform(inner.get("transform"))) if inner is not None else matrix
        size = math.sqrt(abs(placed[0] * placed[3] - placed[1] * placed[2])) * 100  # glyphs are drawn at 100 units an em
        x, y = _apply(placed, 0.0, 0.0)
        angle = math.degrees(math.atan2(placed[1], placed[0]))
        self.texts.append(SvgText(string, x, y, angle, size, "start", len(string) * TEXT_WIDTH_PER_SIZE * size, groups, clip))
        return True

    def _text(self, element, matrix, groups, clip, style):
        string = "".join(element.itertext()).strip()
        if not string:
            return
        x, y = _first_number(element.get("x")), _first_number(element.get("y"))
        scale = math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2])) or 1.0
        size = style.get("font-size", 10.0) * scale
        px, py = _apply(matrix, x, y)
        angle = math.degrees(math.atan2(matrix[1], matrix[0]))
        length = element.get("textLength")
        width = _first_number(length) * scale if length else len(string) * TEXT_WIDTH_PER_SIZE * size
        anchor = style.get("text-anchor", "start")
        entry = (element.get("id") or "", element.get("class") or "", element.get("aria-roledescription") or "")
        self.texts.append(SvgText(string, px, py, angle, size, anchor, width, groups + (entry,), clip))

    def _shape(self, tag, element, matrix, groups, clip, style):
        filled = (style.get("fill") not in (None, "none", "transparent") and style.get("fill-opacity", 1.0) > 0
                  and style.get("opacity", 1.0) > 0 and not style.get("hidden"))
        description = element.get("aria-roledescription")
        if tag == "rect":
            x0, y0, x1, y1 = _rect_box(element, IDENTITY)
            subpaths = [([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True)]
        elif tag in ("polygon", "polyline"):
            values = [float(value) for value in _NUMBERS.findall(element.get("points") or "")]
            subpaths = [(list(zip(values[0::2], values[1::2])), tag == "polygon")]
        elif tag == "line":
            subpaths = [([(_first_number(element.get("x1")), _first_number(element.get("y1"))),
                          (_first_number(element.get("x2")), _first_number(element.get("y2")))], False)]
        elif tag in ("circle", "ellipse"):
            cx, cy = _first_number(element.get("cx")), _first_number(element.get("cy"))
            rx = _first_number(element.get("r") or element.get("rx"))
            ry = _first_number(element.get("r") or element.get("ry"))
            subpaths = [([(cx + rx * math.cos(step * math.pi / 4), cy + ry * math.sin(step * math.pi / 4)) for step in range(8)], True)]
        else:
            subpaths = _path_subpaths(element.get("d") or "")
        for points, closed in subpaths:
            if not points:
                continue
            placed = [_apply(matrix, px, py) for px, py in points]
            if len(placed) > 2 and _near(placed[0], placed[-1]):
                closed = True
            self.shapes.append(SvgShape(placed, closed, filled and (closed or tag != "line"), groups, clip, description))


def read_svg(path):
    """Read one SVG into a `PlotSvg`, every text given the role its writer's conventions name."""
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    root = ElementTree.parse(str(path), parser=parser).getroot()
    walker = _Walker(root)
    walker.walk()
    width, height = _canvas(root)
    writer = _writer(root, walker)
    plot = PlotSvg(writer, width, height, walker.texts, walker.shapes, outlined_glyphs=walker.outlined_glyphs, images=walker.images)
    if writer == "matplotlib":
        _matplotlib_roles(plot, walker)
    elif writer == "vega":
        _vega_roles(plot)
    elif writer == "svglite":
        _svglite_roles(plot, walker)
    return plot


def _writer(root, walker):
    nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    credited = " ".join(node.text or "" for node in nodes if _local(node.tag) == "title")  # matplotlib's <metadata> credit
    if any(_local(node.tag) == "g" and node.get("id") == "figure_1" for node in nodes) or "Matplotlib" in credited:
        return "matplotlib"
    if (root.get("class") or "") == "marks" or walker.vega:
        return "vega"
    if any(_local(node.tag) == "g" and "svglite" in (node.get("class") or "") for node in nodes):
        return "svglite"
    if walker.outlined_glyphs and not walker.texts:
        return "cairo"
    return "unknown"


# --- roles, by writer -------------------------------------------------------------------------------


def _matplotlib_roles(plot, walker):
    panels = {}
    for shape in plot.shapes:
        axes = next((gid for gid, _, _ in shape.groups if _MPL_AXES.match(gid)), None)
        if axes is None or axes in panels:
            continue
        parent = shape.groups[-1][0] if shape.groups else ""
        if parent.startswith("patch_") and shape.is_rectangle():
            panels[axes] = shape.bbox  # the axes' background patch is drawn first
    for shape in plot.shapes:  # an axes with no background patch: the region its marks are clipped to
        axes = next((gid for gid, _, _ in shape.groups if _MPL_AXES.match(gid)), None)
        if axes is not None and axes not in panels and shape.clip in walker.clips:
            panels[axes] = walker.clips[shape.clip]
    plot.panels = list(panels.values())
    top = min((box[1] for box in plot.panels), default=plot.height)
    left = min((box[0] for box in plot.panels), default=0.0)
    right = max((box[2] for box in plot.panels), default=plot.width)
    bottom = max((box[3] for box in plot.panels), default=plot.height)
    for text in plot.texts:
        ids = [gid for gid, _, _ in text.groups]
        tick = next((_MPL_TICK.match(gid) for gid in ids if _MPL_TICK.match(gid)), None)
        axis_group = next((gid for gid in ids if _MPL_AXIS.match(gid)), None)
        axes = next((gid for gid in ids if _MPL_AXES.match(gid)), None)
        if any(gid.startswith("legend_") for gid in ids):
            text.role = "legend"
        elif tick:
            text.role, text.axis = "tick", tick.group(1)
        elif axis_group:
            ordinal = walker.mpl_axis_order.get(axis_group, (None, 0))[1]
            text.role, text.axis = "axis_label", walker.mpl_axis_ticks.get(axis_group) or ("x" if ordinal == 0 else "y")
        elif axes:
            box = panels.get(axes)
            above = box is not None and text.center[1] < box[1] and not text.rotated
            letter = len(text.text) <= 2  # a panel letter (`A`, `b)`) labels the panel; it is no title
            text.role = "panel_title" if above and not letter else "annotation"
        else:
            cx, cy = text.center
            if not text.rotated and cy < top:
                text.role = "figure_title"
            elif text.rotated and (cx < left or cx > right):
                text.role, text.axis = "axis_label", "y"  # a figure's shared y label (supylabel)
            elif not text.rotated and cy > bottom:
                text.role, text.axis = "axis_label", "x"
            else:
                text.role = "annotation"


def _vega_roles(plot):
    for text in plot.texts:
        classes = " ".join(cls for _, cls, _ in text.groups)
        if "role-legend" in classes:
            text.role = "legend"
        elif "role-axis-title" in classes:
            label = next((aria for _, cls, aria in reversed(text.groups) if "role-axis" in cls and aria), "")
            axis = "y" if label.startswith("Y") else "x" if label.startswith("X") else ("y" if text.rotated else "x")
            text.role, text.axis = "axis_label", axis
        elif "role-axis-label" in classes:
            text.role = "tick"
        elif re.search(r"role-(column|row|facet)-(header|title)", classes):
            text.role = "panel_title"
        elif "role-title" in classes:
            text.role = "panel_title" if "role-scope" in classes else "figure_title"
        elif "role-mark" in classes:
            text.role = "annotation"


def _svglite_roles(plot, walker):
    canvas_area = plot.width * plot.height
    regions = {}
    for clip, box in walker.clips.items():
        if _area(box) < FULL_CANVAS * canvas_area:
            regions[clip] = box
    panels, strips = [], []
    for clip, box in regions.items():
        shapes = [shape for shape in plot.shapes if shape.clip == clip]
        texts = [text for text in plot.texts if text.clip == clip]
        marks = [shape for shape in shapes if not _same_box(shape.bbox, box)]
        if texts and not marks:
            strips.append(box)
            for text in texts:
                text.role = "panel_title"
        elif shapes:
            panels.append(box)
            for text in texts:
                text.role = "annotation"
    plot.panels = panels
    if not panels:
        return
    left = min(box[0] for box in panels + strips)
    top = min(box[1] for box in panels + strips)
    right = max(box[2] for box in panels + strips)
    bottom = max(box[3] for box in panels + strips)
    outside = [text for text in plot.texts if text.clip not in regions]
    below = []
    for text in outside:
        cx, cy = text.center
        if not text.rotated and cy < top:
            text.role = "figure_title"
        elif cx < left:
            text.role = "tick"
        elif cx > right:
            text.role = "legend"
        elif cy > bottom:
            below.append(text)
        else:
            text.role = "annotation"
    lefts = [text for text in outside if text.role == "tick" and text.center[0] < left]
    if lefts:
        outermost = min(text.center[0] for text in lefts)
        for text in lefts:
            if text.rotated and text.center[0] <= outermost + text.size:
                text.role, text.axis = "axis_label", "y"
            else:
                text.axis = "y"
    rows = {}
    for text in below:
        rows.setdefault(round(text.y / 2.0), []).append(text)
    ordered = [rows[key] for key in sorted(rows)]
    for index, row in enumerate(ordered):
        if len(ordered) == 1:
            role = "axis_label" if len(row) == 1 else "tick"
        else:
            role = ("tick", "axis_label")[index] if index < 2 else "other"  # a caption, or a legend at the bottom
        for text in row:
            text.role, text.axis = role, "x"


# --- the checks -------------------------------------------------------------------------------------


def _shorten(items, limit=4):
    return ", ".join(items[:limit]) + (" and %d more" % (len(items) - limit) if len(items) > limit else "")


def _quote(texts):
    return _shorten(["%r" % text.text for text in texts])


def _cannot_read_roles(check_id, plot):
    if not plot.text_readable:
        return check_not_run(check_id, "the %s SVG draws its text as glyph outlines with no string, so no text can be read" % plot.writer, tool="svg")
    if not plot.roles_read:
        return check_not_run(check_id, "the SVG's writer is not one whose text roles this check can read (matplotlib, Vega, svglite)", tool="svg")
    return None


def check_rotated_text(plot, policy=None):
    """No rotated text but the y-axis label."""
    blocked = _cannot_read_roles("rotated_text", plot)
    if blocked:
        return blocked
    turned = [text for text in plot.texts if text.rotated and not (text.role == "axis_label" and text.axis == "y")]
    if turned:
        listed = _shorten(["%r (%s, %+.0f deg)" % (text.text, text.role, -text.angle) for text in turned])
        return check_outcome("rotated_text", False, "%d rotated text(s) that are not the y-axis label: %s" % (len(turned), listed), "svg-text")
    labels = sum(1 for text in plot.texts if text.rotated)
    return check_outcome("rotated_text", True, "%d text(s); %d rotated, each a y-axis label" % (len(plot.texts), labels), "svg-text")


def check_axis_label_length(plot, policy=None):
    """No axis label over the policy's character count."""
    blocked = _cannot_read_roles("axis_label_length", plot)
    if blocked:
        return blocked
    limit = int(_policy(policy).get("axis_label_max_chars", DEFAULT_AXIS_LABEL_MAX_CHARS))
    labels = [text for text in plot.texts if text.role == "axis_label"]
    long = [text for text in labels if len(_drawn(text.text)) > limit]
    if long:
        listed = "; ".join("%r is %d characters" % (_drawn(text.text), len(_drawn(text.text))) for text in long)
        return check_outcome("axis_label_length", False, "%s (at most %d)" % (listed, limit), "svg-text")
    return check_outcome("axis_label_length", True, "%d axis label(s), none over %d characters" % (len(labels), limit), "svg-text")


_MATH = re.compile(r"\$([^$]*)\$")
_TEX_COMMAND = re.compile(r"\\(?:mathrm|mathit|mathbf|mathsf|mathtt|mathcal|text|operatorname|left|right)\b|[{}^_]")
_TEX_SYMBOL = re.compile(r"\\[A-Za-z]+")


def _drawn(string):
    """A label as it is drawn: matplotlib's SVG keeps a mathtext label's source, so `$\\mu\\mathrm{m}^2$` counts as µm2."""
    def shown(match):
        body = _TEX_COMMAND.sub("", match.group(1))
        body = _TEX_SYMBOL.sub("x", body.replace("\\ ", " ").replace("\\,", " "))
        return body.replace("\\", "")

    return _MATH.sub(shown, string)


def check_stacked_titles(plot, policy=None):
    """No figure title above titled panels."""
    blocked = _cannot_read_roles("stacked_titles", plot)
    if blocked:
        return blocked
    figure = [text for text in plot.texts if text.role == "figure_title"]
    panel = [text for text in plot.texts if text.role == "panel_title"]
    if figure and panel:
        return check_outcome("stacked_titles", False, "the figure title %s stands above the panel title(s) %s" % (_quote(figure), _quote(panel)), "svg-text")
    return check_outcome("stacked_titles", True, "%d figure title(s), %d panel title(s): one level of titles" % (len(figure), len(panel)), "svg-text")


def check_heatmap_cell_labels(plot, policy=None):
    """A heatmap's cells carry labels only up to the policy's cell count."""
    limit = int(_policy(policy).get("heatmap_label_max_cells", DEFAULT_HEATMAP_LABEL_MAX_CELLS))
    heatmaps = [(cells, _union(cells), len(cells)) for cells in _heatmaps(plot.shapes)]
    for image in plot.images:  # a raster heatmap (imshow, matshow): its cells are counted by the labels inside it
        labels = [text for text in plot.texts if _inside(text.center, image)]
        if len(labels) >= 4:
            heatmaps.append(([], image, len(labels)))
    if not heatmaps:
        return check_outcome("heatmap_cell_labels", True, "no heatmap", "svg-geometry")
    large = [count for _, _, count in heatmaps if count > limit]
    if large and not plot.text_readable:
        return check_not_run("heatmap_cell_labels", "a heatmap of %d cells, and the %s SVG draws its text as glyph outlines, so its labels cannot be counted"
                             % (large[0], plot.writer), tool="svg")
    problems, sizes = [], []
    for cells, box, count in heatmaps:
        labels = [text for text in plot.texts if _inside(text.center, box)]
        counted = "%d cells" % count if cells else "%d cells, a raster counted by its labels" % count
        sizes.append("%s, %d labelled" % (counted, len(labels)))
        if count > limit and labels:
            problems.append("a heatmap of %s carries %d cell label(s); labels only up to %d cells" % (counted, len(labels), limit))
    if problems:
        return check_outcome("heatmap_cell_labels", False, "; ".join(problems), "svg-geometry+text")
    return check_outcome("heatmap_cell_labels", True, "heatmap(s): %s (labels only up to %d cells)" % ("; ".join(sizes), limit), "svg-geometry+text")


def check_flat_summary_mark(plot, policy=None):
    """No box or summary rectangle collapsed to a line."""
    candidates = [shape for shape in plot.shapes if shape.is_rectangle()]
    if plot.writer == "vega":
        candidates = [shape for shape in candidates if shape.role_description == "box"]
    flat = []
    for shape in candidates:
        x0, y0, x1, y1 = shape.bbox
        width, height = x1 - x0, y1 - y0
        if min(width, height) < FLAT_UNITS and max(width, height) >= MIN_MARK_UNITS:
            flat.append(shape)
    if plot.writer != "vega":  # Vega names its boxes; elsewhere a bar is told from a box by the edges it shares
        rectangles = [shape for shape in plot.shapes if shape.is_rectangle()]
        flat = [shape for shape in flat if not _shares_an_edge(shape, rectangles)]
    if flat:
        where = ", ".join("%.0f wide at (%.1f, %.1f)" % (max(s.bbox[2] - s.bbox[0], s.bbox[3] - s.bbox[1]), s.bbox[0], s.bbox[1]) for s in flat[:4])
        return check_outcome("flat_summary_mark", False, "%d summary mark(s) drawn flat, as a line: %s" % (len(flat), where), "svg-geometry")
    return check_outcome("flat_summary_mark", True, "%d rectangular mark(s), none flat" % len(candidates), "svg-geometry")


READABILITY_CHECKS = {
    "rotated_text": check_rotated_text,
    "axis_label_length": check_axis_label_length,
    "stacked_titles": check_stacked_titles,
    "heatmap_cell_labels": check_heatmap_cell_labels,
    "flat_summary_mark": check_flat_summary_mark,
}


def run_readability_checks(svg_path, policy=None, only=None):
    """Run the five checks on one plot's SVG; returns their outcomes in `READABILITY_CHECK_IDS` order.

    `policy` is the whole policy or its `plot_checks` block (the thresholds); None reads the
    shipped `policy.json`. An SVG that cannot be parsed fails every check with the reason.
    """
    try:
        plot = read_svg(svg_path)
    except (OSError, ElementTree.ParseError) as failure:
        plot = None
        reason = "the SVG %s could not be read: %s" % (Path(svg_path).name, failure)
    report = []
    for check_id in READABILITY_CHECK_IDS:
        if only is not None and check_id not in only:
            continue
        if plot is None:
            report.append(check_outcome(check_id, False, reason, "svg"))
        else:
            report.append(READABILITY_CHECKS[check_id](plot, policy))
    return report


def _policy(policy):
    if policy is None:  # the shipped thresholds; a project passes its own
        policy = json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))
    return policy.get("plot_checks", policy)


# --- geometry -----------------------------------------------------------------------------------------


def _heatmaps(shapes):
    """Each grid of equal filled cells touching one another, at least two across and two down."""
    cells = [shape.bbox for shape in shapes if shape.filled and shape.is_rectangle()]
    cells = [box for box in cells if box[2] - box[0] >= MIN_MARK_UNITS and box[3] - box[1] >= MIN_MARK_UNITS]
    groups = []
    for box in cells:
        size = (box[2] - box[0], box[3] - box[1])
        for group in groups:
            if abs(group[0][0] - size[0]) <= CELL_TOLERANCE and abs(group[0][1] - size[1]) <= CELL_TOLERANCE:
                group[1].append(box)
                break
        else:
            groups.append((size, [box]))
    found = []
    for _, members in groups:
        for component in _touching(members):
            columns = {round(box[0] / CELL_TOLERANCE) for box in component}
            rows = {round(box[1] / CELL_TOLERANCE) for box in component}
            if len(columns) >= 2 and len(rows) >= 2:
                found.append(component)
    return found


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _touching(boxes):
    """The boxes split into groups that share an edge, cell to cell."""
    remaining, components = list(boxes), []
    while remaining:
        component = [remaining.pop()]
        frontier = [component[0]]
        while frontier:
            current = frontier.pop()
            near = [box for box in remaining if _adjacent(current, box)]
            for box in near:
                remaining.remove(box)
            component.extend(near)
            frontier.extend(near)
        components.append(component)
    return components


def _adjacent(first, second):
    """Neighbours in a grid: in one row or column, with at most `CELL_GAP` of a cell between them (`geom_tile(width = 0.9)`)."""
    tol = CELL_TOLERANCE
    width, height = first[2] - first[0], first[3] - first[1]

    def gap(near_edge, far_edge, size):
        return -tol <= far_edge - near_edge <= CELL_GAP * size + tol

    side_by_side = abs(first[1] - second[1]) <= tol and (gap(first[2], second[0], width) or gap(second[2], first[0], width))
    stacked = abs(first[0] - second[0]) <= tol and (gap(first[3], second[1], height) or gap(second[3], first[1], height))
    return side_by_side or stacked


def _shares_an_edge(thin, rectangles):
    """Whether a thin rectangle has an edge on a line another rectangle's edge lies on, in the same
    panel: bars on one baseline, a stacked bar's segments, or a histogram's bins. A box drawn flat
    stands alone. A rectangle thin across (a bar of a tiny value) shares a horizontal line; one thin
    down may share either (a histogram's narrow bins, or a horizontal bar of a tiny value)."""
    tol = CELL_TOLERANCE
    flat = thin.bbox
    thin_down = (flat[2] - flat[0]) < (flat[3] - flat[1])
    for other in rectangles:
        box = other.bbox
        if other is thin or _same_box(box, flat) or (thin.clip and other.clip and thin.clip != other.clip):
            continue
        across = any(abs(a - b) <= tol for a in (flat[1], flat[3]) for b in (box[1], box[3]))
        down = thin_down and any(abs(a - b) <= tol for a in (flat[0], flat[2]) for b in (box[0], box[2]))
        if across or down:
            return True
    return False


def _inside(point, box):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _same_box(first, second):
    return all(abs(a - b) <= CELL_TOLERANCE for a, b in zip(first, second))


def _near(first, second):
    return abs(first[0] - second[0]) <= 1e-6 and abs(first[1] - second[1]) <= 1e-6


# --- SVG primitives -----------------------------------------------------------------------------------


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else tag


def _first_number(value):
    found = _NUMBERS.search(value or "")
    return float(found.group(0)) if found else 0.0


def _canvas(root):
    box = _NUMBERS.findall(root.get("viewBox") or "")
    if len(box) == 4:
        return float(box[2]), float(box[3])
    return _first_number(root.get("width")), _first_number(root.get("height"))


def _multiply(first, second):
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def _apply(matrix, x, y):
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _transform(text):
    matrix = IDENTITY
    for name, arguments in _TRANSFORM.findall(text or ""):
        values = [float(value) for value in _NUMBERS.findall(arguments)]
        if name == "matrix" and len(values) == 6:
            step = tuple(values)
        elif name == "translate":
            step = (1.0, 0.0, 0.0, 1.0, values[0] if values else 0.0, values[1] if len(values) > 1 else 0.0)
        elif name == "scale":
            sx = values[0] if values else 1.0
            step = (sx, 0.0, 0.0, values[1] if len(values) > 1 else sx, 0.0, 0.0)
        elif name == "rotate":
            angle = math.radians(values[0] if values else 0.0)
            turn = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0.0, 0.0)
            if len(values) == 3:
                cx, cy = values[1], values[2]
                turn = _multiply(_multiply((1.0, 0.0, 0.0, 1.0, cx, cy), turn), (1.0, 0.0, 0.0, 1.0, -cx, -cy))
            step = turn
        elif name == "skewX":
            step = (1.0, 0.0, math.tan(math.radians(values[0] if values else 0.0)), 1.0, 0.0, 0.0)
        elif name == "skewY":
            step = (1.0, math.tan(math.radians(values[0] if values else 0.0)), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        matrix = _multiply(matrix, step)
    return matrix


def _rect_box(element, matrix):
    x, y = _first_number(element.get("x")), _first_number(element.get("y"))
    width, height = _first_number(element.get("width")), _first_number(element.get("height"))
    corners = [_apply(matrix, px, py) for px, py in ((x, y), (x + width, y), (x + width, y + height), (x, y + height))]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _clip_id(element):
    value = element.get("clip-path") or _style_attributes(element).get("clip-path")
    found = _URL.search(value or "")
    return found.group(1) if found else None


def _style_attributes(element):
    declared = {}
    for part in (element.get("style") or "").split(";"):
        key, colon, value = part.partition(":")
        if colon:
            declared[key.strip()] = value.strip()
    return declared


def _cascade(inherited, element):
    """The inherited style with this element's presentation attributes and `style` declarations on top."""
    style = dict(inherited)
    declared = {key: element.get(key) for key in ("fill", "fill-opacity", "opacity", "font-size", "text-anchor", "font") if element.get(key) is not None}
    declared.update(_style_attributes(element))
    if "opacity" in style:
        style.pop("opacity")  # opacity does not inherit; only a node's own counts toward its own fill
    for key, value in declared.items():
        if key == "fill":
            style["fill"] = value.strip()
        elif key in ("fill-opacity", "opacity"):
            style[key] = _first_number(value)
        elif key == "font-size":
            style["font-size"] = _font_size(value, style.get("font-size", 10.0))
        elif key == "font":
            found = _FONT_SIZE.search(value)
            if found:
                style["font-size"] = _font_size(found.group(0), style.get("font-size", 10.0))
        elif key == "text-anchor":
            style["text-anchor"] = value.strip()
    if style.get("opacity", 1.0) <= 0:
        style["hidden"] = True  # a group drawn at no opacity hides everything inside it
    return style


def _font_size(value, current):
    found = _FONT_SIZE.search(value or "")
    if not found:
        return current
    size = float(found.group(1))
    return size * 4 / 3 if found.group(2) == "pt" else size


def _path_subpaths(d):
    """The vertices of each subpath of a path's `d`, curves and arcs taken at their end points."""
    tokens = _PATH_TOKEN.findall(d)
    subpaths, points, closed = [], [], False
    x = y = start_x = start_y = 0.0
    command, index = None, 0

    def take(count):
        nonlocal index
        values = []
        while len(values) < count and index < len(tokens) and not tokens[index].isalpha():
            values.append(float(tokens[index]))
            index += 1
        if len(values) < count:
            raise ValueError("a path command is short of its numbers")
        return values

    def finish():
        nonlocal points, closed
        if points:
            subpaths.append((points, closed))
        points, closed = [], False

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                closed = True
                x, y = start_x, start_y
                finish()
                continue
        elif command is None:
            break
        relative = command.islower()
        kind = command.upper()
        try:
            if kind == "M":
                finish()
                nx, ny = take(2)
                x, y = (x + nx, y + ny) if relative else (nx, ny)
                start_x, start_y = x, y
                points.append((x, y))
                command = "l" if relative else "L"  # numbers after a moveto are linetos
            elif kind == "L" or kind == "T":
                nx, ny = take(2)
                x, y = (x + nx, y + ny) if relative else (nx, ny)
                points.append((x, y))
            elif kind == "H":
                (nx,) = take(1)
                x = x + nx if relative else nx
                points.append((x, y))
            elif kind == "V":
                (ny,) = take(1)
                y = y + ny if relative else ny
                points.append((x, y))
            elif kind in ("C", "S", "Q", "A"):
                count = {"C": 6, "S": 4, "Q": 4, "A": 7}[kind]
                values = take(count)
                nx, ny = values[-2], values[-1]
                x, y = (x + nx, y + ny) if relative else (nx, ny)
                points.append((x, y))
            else:
                index += 1
        except ValueError:
            break
    finish()
    return subpaths
