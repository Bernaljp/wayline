"""Draw the Altair readability-check samples (ticket 77): `python fixtures/plots/make_altair.py fixtures/plots/samples`.

Needs altair, vl-convert-python, numpy, and pandas; the SVGs it writes (vl-convert's, as Altair saves them) are committed.
"""
import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)
GROUPS = {"raw": rng.normal(0.70, 0.03, 12), "x3x4": rng.normal(0.78, 0.03, 12)}
LONG = "mean paired gain over ten seeds at signal 4"
long = pd.DataFrame([(arm, float(v), s) for s, shift in (("signal 2", 0), ("signal 4", 0.02))
                     for arm, values in GROUPS.items() for v in values + shift], columns=["arm", "AUROC", "signal"])
one = long[long.signal == "signal 2"]


def save(chart, name):
    chart.save(str(OUT / (name + ".svg")))


def box(data, x_title="arm", y_title="AUROC", angle=0):
    return alt.Chart(data).mark_boxplot().encode(
        x=alt.X("arm:N", title=x_title, axis=alt.Axis(labelAngle=angle)),
        y=alt.Y("AUROC:Q", title=y_title, scale=alt.Scale(zero=False)),
    ).properties(width=140, height=140)


def heatmap(rows, cols, missing=0):
    cells = [(r, c, round(float(rng.uniform(0, 1)), 2)) for r in range(rows) for c in range(cols)]
    cells = cells[:len(cells) - missing]
    data = pd.DataFrame(cells, columns=["signal", "seed", "value"])
    base = alt.Chart(data).encode(x=alt.X("seed:O", axis=alt.Axis(labelAngle=0)), y=alt.Y("signal:O"))  # Vega turns ordinal labels sideways by default
    return (base.mark_rect().encode(color="value:Q")
            + base.mark_text(fontSize=7).encode(text=alt.Text("value:Q", format=".2f"))).properties(width=200, height=150)


save(alt.hconcat(box(one).properties(title="Signal 2"), box(long[long.signal == "signal 4"]).properties(title="Signal 4")), "altair-clean")
save(heatmap(6, 6), "altair-heatmap-36")
save(heatmap(5, 8, missing=3), "altair-heatmap-37")
save(box(one, angle=-45), "altair-rotated-ticks")
save(box(one, x_title=LONG), "altair-long-label")
save(alt.hconcat(box(one).properties(title="Signal 2"), box(long[long.signal == "signal 4"]).properties(title="Signal 4"))
     .properties(title="AUROC by arm"), "altair-suptitle")
flat = pd.DataFrame({"arm": ["raw"] * 11 + ["x3x4"] * 12, "AUROC": [0.7] * 9 + [0.72, 0.68] + [float(v) for v in GROUPS["x3x4"]]})
save(box(flat), "altair-flat-box")
