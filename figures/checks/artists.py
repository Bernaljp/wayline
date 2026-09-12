"""Run a figure generator and record, at every save, what its matplotlib artists are.

    python -I figures/checks/artists.py --out artists.json [--width-mm 89] figures/fig1/fig1.py [args]

This script runs in the project's own environment, where matplotlib is installed; the harness
itself imports no plotting library (Implementation Decisions 1), so the checks in
`wayline.figure_checks` read the JSON this writes. The generator runs unchanged, as if started
with `python <generator>` from the working directory: `Figure.savefig` is wrapped, and before
each save the figure is drawn once and described.

The report is `{"schema": "figure_artists/1", "figures": [...]}`, one entry per save:

- `saved_to`: the path the generator saved to, relative to the working directory;
- `figure`: `width_px`, `height_px`, `dpi`, `width_in`, `height_in`, and `scale`, the factor from
  the drawn width to the target width;
- `texts`: every visible, non-empty text with `text`, `role` (`ticklabel`, `panel_label`, or
  `text`), `fontsize_pt` at the target width, `extent` in display pixels, and `haloed`;
- `panels`: `label` and `bbox`, the panel's axes (with its labels) as figure fractions from the
  bottom left; an axes with gid `panel:<letter>`, else a one-letter text in or nearest an axes;
- `marked_lines`: artists with gid `required:<name>` or `optional:<name>`, with `linestyle`;
- `structure`: artists with gid `connector:<name>` or `container:<name>`, with their `colors`;
- `mappables`: colormapped artists (not colorbars) with `cmap` and `quantity` from gid
  `quantity:<name>`;
- `colors`: the face and edge colors of every visible patch, line, and collection.
"""

import argparse
import json
import math
import os
import re
import runpy
import sys

PANEL_TEXT = re.compile(r"^\(?([a-z])\)?$")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--width-mm", type=float, default=None)
    parser.add_argument("generator")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    reports = []
    original = Figure.savefig

    def savefig(figure, fname, *args, **kwargs):
        reports.append(describe(figure, fname, options.width_mm))
        return original(figure, fname, *args, **kwargs)

    Figure.savefig = savefig
    sys.argv = [options.generator] + list(options.arguments)
    sys.path.insert(0, os.path.dirname(os.path.abspath(options.generator)))
    try:
        runpy.run_path(options.generator, run_name="__main__")
    finally:
        with open(options.out, "w", encoding="utf-8") as handle:
            json.dump({"schema": "figure_artists/1", "figures": reports}, handle, indent=1)
            handle.write("\n")


def describe(figure, fname, width_mm):
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import Collection
    from matplotlib.colors import to_hex, to_rgba
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.text import Text

    # The texts are the ones this draw actually draws: a tick label beyond the view limits, on an
    # axis turned off, or under an invisible parent is an artist that never reaches the page.
    drawn, seen_texts = [], set()
    original_draw = Text.draw

    def draw(text, renderer):
        if id(text) not in seen_texts and text.get_visible() and text.get_text().strip():
            seen_texts.add(id(text))
            drawn.append(text)
        return original_draw(text, renderer)

    Text.draw = draw
    try:
        figure.canvas.draw()
    finally:
        Text.draw = original_draw
    renderer = figure.canvas.get_renderer()
    width_px, height_px = figure.bbox.width, figure.bbox.height
    width_in = figure.get_figwidth()
    scale = (width_mm / 25.4) / width_in if width_mm else 1.0

    tick_labels = set()
    for axes in figure.axes:
        for axis in (axes.xaxis, axes.yaxis):
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                tick_labels.update((tick.label1, tick.label2))

    texts, panel_texts = [], []
    for text in drawn:
        content = text.get_text()
        role = "ticklabel" if text in tick_labels else ("panel_label" if PANEL_TEXT.match(content.strip()) else "text")
        extent = text.get_window_extent(renderer)
        texts.append({
            "text": content,
            "role": role,
            "fontsize_pt": round(text.get_fontsize() * scale, 3),
            "extent": [round(value, 2) for value in (extent.x0, extent.y0, extent.x1, extent.y1)],
            "haloed": bool(text.get_path_effects()),
        })
        if role == "panel_label":
            panel_texts.append(text)

    panels, seen = [], set()
    for axes in figure.axes:
        gid = axes.get_gid() or ""
        if gid.startswith("panel:"):
            _add_panel(panels, seen, gid.split(":", 1)[1], axes, renderer, width_px, height_px)
    for text in panel_texts:
        axes = text.axes or _nearest_axes(figure, text, renderer)
        if axes is not None:
            _add_panel(panels, seen, PANEL_TEXT.match(text.get_text().strip()).group(1), axes, renderer, width_px, height_px)

    marked, structure, mappables, colors = [], [], [], set()
    for artist in figure.findobj():
        if not _shown(artist):
            continue
        gid = artist.get_gid() or ""
        kind = gid.split(":", 1)[0]
        own = _colors(artist, to_rgba, to_hex, Line2D, Patch, Collection)
        colors.update(own)
        if kind in ("required", "optional"):
            marked.append({"gid": gid, "kind": kind, "linestyle": _linestyle(artist)})
        elif kind in ("connector", "container"):
            structure.append({"gid": gid, "colors": sorted(own)})
        if isinstance(artist, ScalarMappable) and artist.get_array() is not None:
            if getattr(getattr(artist, "axes", None), "_colorbar", None) is not None:
                continue  # a colorbar repeats its mappable's colormap
            mappables.append({"cmap": artist.get_cmap().name, "quantity": gid.split(":", 1)[1] if kind == "quantity" else None})

    return {
        "saved_to": _relative(fname),
        "figure": {
            "width_px": round(width_px, 2), "height_px": round(height_px, 2), "dpi": figure.dpi,
            "width_in": width_in, "height_in": figure.get_figheight(), "scale": scale,
        },
        "texts": texts,
        "panels": panels,
        "marked_lines": marked,
        "structure": structure,
        "mappables": mappables,
        "colors": sorted(colors),
    }


def _shown(artist):
    """Visible, and inside an axes that is visible too (a Figure's `.axes` is a list, not a parent)."""
    from matplotlib.axes import Axes

    if not artist.get_visible():
        return False
    parent = getattr(artist, "axes", None)
    return not (isinstance(parent, Axes) and parent is not artist and not parent.get_visible())


def _add_panel(panels, seen, label, axes, renderer, width_px, height_px):
    if label in seen:
        return
    seen.add(label)
    box = axes.get_tightbbox(renderer)
    bbox = [box.x0 / width_px, box.y0 / height_px, box.x1 / width_px, box.y1 / height_px]
    panels.append({"label": label, "bbox": [round(min(1.0, max(0.0, value)), 5) for value in bbox]})


def _nearest_axes(figure, text, renderer):
    extent = text.get_window_extent(renderer)
    x, y = (extent.x0 + extent.x1) / 2, (extent.y0 + extent.y1) / 2
    best, distance = None, math.inf
    for axes in figure.axes:
        corner = axes.get_window_extent(renderer)
        gap = math.hypot(corner.x0 - x, corner.y1 - y)  # a panel letter sits by its axes' top left
        if gap < distance:
            best, distance = axes, gap
    return best


def _linestyle(artist):
    style = artist.get_linestyle()
    if isinstance(style, str):
        return {"-": "solid", "--": "dashed", "-.": "dashdot", ":": "dotted", "None": "none", " ": "none", "": "none"}.get(style, style)
    return "dashed"  # a dash tuple


def _colors(artist, to_rgba, to_hex, line_type, patch_type, collection_type):
    found = []
    if isinstance(artist, line_type):
        found = [artist.get_color(), artist.get_markerfacecolor(), artist.get_markeredgecolor()]
    elif isinstance(artist, patch_type):
        found = [artist.get_facecolor(), artist.get_edgecolor()]
    elif isinstance(artist, collection_type):
        found = list(artist.get_facecolors()) + list(artist.get_edgecolors())
    hexes = set()
    for color in found:
        try:
            rgba = to_rgba(color)
        except (ValueError, TypeError):
            continue
        if rgba[3] > 0:
            hexes.add(to_hex(rgba, keep_alpha=False).upper())
    return hexes


def _relative(fname):
    try:
        return os.path.relpath(os.path.abspath(os.fspath(fname)))
    except TypeError:
        return None  # a file object, not a path


if __name__ == "__main__":
    main()
