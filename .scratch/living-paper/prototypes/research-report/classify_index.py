"""PROTOTYPE, throwaway: sorts the M7 plot index's 75 entries by the data shape each can draw.

The index's own `data_shape` is "unspecified" on all 75 entries, so this is a hand reading of
each entry's title and cached page, written once. Shapes:
  dist      one numeric variable, one or more groups (seeds, signals, arms)
  xy        two numeric variables per observation
  series    a value along an ordered x, with or without a band
  category  one value per category, with or without an interval
  whole     parts that add up to a whole, per category or along x
  matrix    a value per pair of categories
  multivar  rows of many variables
  none      not a chart type for research data: styling, tutorial, map, art, interaction, animation
"""
import json
from collections import Counter
from pathlib import Path

INDEX = Path.home() / "wayline-m7/toy/figures/plot_index.json"
# chart_type title -> (canonical chart type, shape, note)
MAP = {
    "Basic density plot with seaborn": ("density", "dist", ""),
    "Density plot with shade in seaborn": ("density", "dist", "variant: shading"),
    "Horizontal density plot": ("density", "dist", "variant: orientation"),
    "Control the bandwidth of a seaborn density plot": ("density", "dist", "variant: bandwidth"),
    "Density plot of several variables": ("density, several groups", "dist", ""),
    "Contour Plot using Seaborn": ("2D density contour", "xy", ""),
    "Plot a Basic 2D Histogram using Matplotlib": ("2D histogram", "xy", ""),
    "Animated 3D chart": (None, "none", "animation; a static report cannot carry it"),
    "Basic Area Chart": ("area", "series", ""),
    "Improved Area Chart": ("area", "series", "variant: styling"),
    "Area Chart and Faceting": ("area, faceted", "series", ""),
    "Plotting a Horizontal Barplot using Matplotlib": ("bar", "category", "variant: horizontal"),
    "Control the color of barplots built with matplotlib": (None, "none", "styling of a bar"),
    "Add a title and axis labels to your charts using matplotlib": (None, "none", "styling tutorial"),
    "Control width and space in barplots using matplotlib": (None, "none", "styling of a bar"),
    "Stacked area chart with R": ("stacked area", "whole", ""),
    "Area chart with base R": ("area", "series", "duplicate of area"),
    "Basic barplot with ggplot2": ("bar", "category", ""),
    "Reorder a variable with ggplot2": (None, "none", "ordering tutorial"),
    "Barplot with variable width": ("bar, variable width", "category", "width encodes a count"),
    "Barplot with error bars": ("bar with error bars", "category", ""),
    "Most basic barplot": ("bar", "category", "duplicate of bar"),
    "Basic R barplot customization": (None, "none", "styling of a bar"),
    "Advanced R barplot customization": (None, "none", "styling of a bar"),
    "Barplot with number of observation": ("bar with n", "category", ""),
    "Base R graph parameters: a cheatsheet.": (None, "none", "cheatsheet"),
    "Base R margins: a cheatsheet.": (None, "none", "cheatsheet"),
    "Boxplot with individual data points": ("box with points", "dist", ""),
    "Basic ggplot2 boxplot": ("box", "dist", ""),
    "Ggplot2 boxplot parameters": (None, "none", "styling of a box"),
    "Andrews Curves": ("Andrews curves", "multivar", "rows of many variables as curves"),
    "Bar Chart with Highlighting on Hover and Selection on Click": ("bar", "category", "interaction lost in a static report; duplicate of bar"),
    "Bar Chart with Labels based on Measured Luminance": ("bar with value labels", "category", ""),
    "Confidence Interval Ellipses": ("scatter with CI ellipses", "xy", ""),
    "Faceted County": (None, "none", "map"),
    "Filter a Time Series with Date and Number Inputs": (None, "none", "interactive time filter"),
    "Grouped Bar Chart with xOffset and overlapping bars": ("grouped bar", "category", ""),
    "Histogram with Adjustable Bin Size": ("histogram", "dist", "the slider is lost in a static report"),
    "Interactive Chart with Aggregation": (None, "none", "interactive"),
    "Interactive Selection of Columns": (None, "none", "interactive"),
    "Interval Selection on a Map": (None, "none", "map"),
    "Mosaic Chart with Labels": ("mosaic", "whole", "two categorical variables"),
    "Polar Bar Chart": ("polar bar", "category", ""),
    "Reorder stacked bar segments": ("stacked bar", "whole", "duplicate of stacked bar"),
    "Scatter plot with point paths on hover and search box": ("connected scatter (paths)", "xy", "hover lost; paths drawn static"),
    "Anscombe’s quartet": ("faceted scatter with fit", "xy", ""),
    "Scatterplot with multiple semantics": ("scatter, hue and size", "xy", ""),
    "Timeseries plot with error bands": ("line with band", "series", ""),
    "Facetting histograms by subsets of data": ("histogram, faceted", "dist", ""),
    "Line plots on multiple facets": ("line, faceted", "series", ""),
    "Grouped barplots": ("grouped bar", "category", "duplicate of grouped bar"),
    "Grouped boxplots": ("grouped box", "dist", ""),
    "Grouped violinplots with split violins": ("split violin", "dist", ""),
    "Scatterplot heatmap": ("scatter heatmap", "matrix", ""),
    "Hexbin plot with marginal distributions": ("hexbin with marginals", "xy", ""),
    "Stacked histogram on a log scale": ("stacked histogram, log scale", "dist", ""),
    "Horizontal boxplot with observations": ("box with points", "dist", "duplicate of box with points"),
    "Conditional means with observations": ("means with observations", "dist", ""),
    "Joint and marginal histograms": ("joint histogram", "xy", ""),
    "Joint kernel density estimate": ("joint density", "xy", ""),
    "Weather Forecast": ("line, segments", "series", "duplicate of line"),
    "Using Letters as Shapes": ("scatter, text markers", "xy", "duplicate of scatter"),
    "The Shapes of a Scatter Plot": ("scatter, shapes", "xy", "duplicate of scatter"),
    "The Territories of Westeros": (None, "none", "map"),
    "Stacked Bar Chart": ("stacked bar", "whole", ""),
    "Same Color, Different Shade": ("split violin", "dist", "duplicate of violin"),
    "Periodic Table": ("tile grid with labels", "matrix", "geom_tile plus text: an annotated heatmap"),
    "Oh My Bubbles": ("bubble", "xy", "scatter with size"),
    "Mondrian": (None, "none", "art"),
    "Infant Deaths in North Carolina": (None, "none", "map"),
    "Horizontal Bar Chart": ("bar", "category", "duplicate of bar"),
    "Density with Some Shade": ("density", "dist", "duplicate of density"),
    "Coal Production": ("area", "series", "duplicate of area"),
    "A Bar Plot With 2 Variables": ("grouped bar", "category", "duplicate of grouped bar"),
    "Anscombe’s Quartet": ("faceted scatter with fit", "xy", "duplicate"),
}

entries = json.loads(INDEX.read_text())["entries"]
missing = [e["chart_type"] for e in entries if e["chart_type"] not in MAP]
assert not missing, missing
out = []
for e in entries:
    ct, shape, note = MAP[e["chart_type"]]
    out.append({"id": e["id"], "title": e["chart_type"], "site": e["source_site"],
                "chart_type": ct, "shape": shape, "note": note})
Path(__file__).with_name("index_shapes.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
types = {o["chart_type"] for o in out if o["chart_type"]}
print("entries", len(out), "| not a chart type:", sum(o["shape"] == "none" for o in out),
      "| distinct chart types:", len(types))
print(dict(Counter(o["shape"] for o in out)))
by_shape = {}
for o in out:
    if o["chart_type"]:
        by_shape.setdefault(o["shape"], set()).add(o["chart_type"])
for k, v in sorted(by_shape.items()):
    print(k, len(v), sorted(v))
