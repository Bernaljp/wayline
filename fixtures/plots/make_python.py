"""Draw the matplotlib and seaborn readability-check samples (ticket 77): `python fixtures/plots/make_python.py fixtures/plots/samples`.

Needs matplotlib, seaborn, numpy, and pandas (the suite itself needs none of them); the SVGs it writes are committed.
matplotlib draws its text as glyph outlines (its default) and seaborn as `<text>`, so both ways matplotlib writes text are read.
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["svg.hashsalt"] = "wayline"
plt.rcParams["svg.fonttype"] = "path"  # matplotlib's default; seaborn below writes <text>
rng = np.random.default_rng(7)
GROUPS = {"raw": rng.normal(0.70, 0.03, 12), "x3x4": rng.normal(0.78, 0.03, 12)}
LONG = "mean paired gain over ten seeds at signal 4"  # 43 characters
assert len(LONG) > 40
SHORT = "paired gain"


def save(fig, name):
    fig.savefig(OUT / (name + ".svg"), metadata={"Date": None})
    plt.close(fig)


def grid(rows, cols, missing=0):
    values = np.round(rng.uniform(0, 1, (rows, cols)), 2)
    flat = values.ravel()
    flat[len(flat) - missing:] = np.nan
    return flat.reshape(rows, cols)


# --- matplotlib ---------------------------------------------------------------------------------

def mpl_box(ax, data):
    ax.boxplot(list(data.values()))
    ax.set_xticks([1, 2], list(data))


def mpl_heatmap(ax, values):
    mesh = ax.pcolormesh(values, cmap="viridis")
    for (row, col), value in np.ndenumerate(values):
        if not np.isnan(value):
            ax.text(col + 0.5, row + 0.5, "%.2f" % value, ha="center", va="center", fontsize=6)
    return mesh


fig, axes = plt.subplots(1, 2, figsize=(6, 3), layout="constrained")
mpl_box(axes[0], GROUPS)
axes[0].set_title("Signal 2")
axes[0].set_ylabel("AUROC")
axes[0].set_xlabel("arm")
mpl_box(axes[1], {k: v + 0.02 for k, v in GROUPS.items()})
axes[1].set_title("Signal 4")
axes[1].set_xlabel("arm")
save(fig, "matplotlib-clean")

fig, ax = plt.subplots(figsize=(4, 3.6), layout="constrained")
mpl_heatmap(ax, grid(6, 6))
ax.set_xlabel("seed")
ax.set_ylabel("signal")
save(fig, "matplotlib-heatmap-36")

fig, ax = plt.subplots(figsize=(5, 3.6), layout="constrained")
mpl_heatmap(ax, grid(5, 8, missing=3))
ax.set_xlabel("seed")
ax.set_ylabel("signal")
save(fig, "matplotlib-heatmap-37")

fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
mpl_box(ax, GROUPS)
ax.set_ylabel("AUROC")
ax.set_xlabel("arm")
ax.tick_params(axis="x", labelrotation=45)
save(fig, "matplotlib-rotated-ticks")

fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
mpl_box(ax, GROUPS)
ax.set_ylabel("AUROC")
ax.set_xlabel(LONG)
save(fig, "matplotlib-long-label")

fig, axes = plt.subplots(1, 2, figsize=(6, 3), layout="constrained")
for ax, title in zip(axes, ("Signal 2", "Signal 4")):
    mpl_box(ax, GROUPS)
    ax.set_title(title)
axes[0].set_ylabel("AUROC")
fig.suptitle("AUROC by arm")
save(fig, "matplotlib-suptitle")

fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
mpl_box(ax, {"raw": np.array([0.7] * 9 + [0.72, 0.68]), "x3x4": GROUPS["x3x4"]})
ax.set_ylabel("AUROC")
ax.set_xlabel("arm")
save(fig, "matplotlib-flat-box")

# --- seaborn (text written as <text>, the other way matplotlib writes an SVG) -------------------

plt.rcParams["svg.fonttype"] = "none"
sns.set_theme(style="whitegrid")
long = pd.DataFrame([(arm, v, s) for s, shift in (("signal 2", 0), ("signal 4", 0.02))
                     for arm, values in GROUPS.items() for v in values + shift], columns=["arm", "AUROC", "signal"])

grid_plot = sns.catplot(long, x="arm", y="AUROC", col="signal", kind="box", height=3, aspect=1)
grid_plot.set_titles("{col_name}")
save(grid_plot.figure, "seaborn-clean")


def sns_heatmap(values, name):
    fig, ax = plt.subplots(figsize=(5, 3.6), layout="constrained")
    sns.heatmap(pd.DataFrame(values), annot=True, fmt=".2f", ax=ax, cbar=True, annot_kws={"fontsize": 6})
    ax.set_xlabel("seed")
    ax.set_ylabel("signal")
    ax.tick_params(axis="y", labelrotation=0)  # seaborn turns a heatmap's row labels sideways by default
    save(fig, name)


sns_heatmap(grid(6, 6), "seaborn-heatmap-36")
sns_heatmap(grid(5, 8, missing=3), "seaborn-heatmap-37")

fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
sns.boxplot(long[long.signal == "signal 2"], x="arm", y="AUROC", ax=ax)
ax.tick_params(axis="x", labelrotation=90)
save(fig, "seaborn-rotated-ticks")

fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
sns.boxplot(long[long.signal == "signal 2"], x="arm", y="AUROC", ax=ax)
ax.set_ylabel(LONG)
save(fig, "seaborn-long-label")

grid_plot = sns.catplot(long, x="arm", y="AUROC", col="signal", kind="box", height=3, aspect=1)
grid_plot.set_titles("{col_name}")
grid_plot.figure.suptitle("AUROC by arm")
grid_plot.figure.subplots_adjust(top=0.82)
save(grid_plot.figure, "seaborn-suptitle")

flat = pd.DataFrame({"arm": ["raw"] * 11 + ["x3x4"] * 12,
                     "AUROC": [0.7] * 9 + [0.72, 0.68] + list(GROUPS["x3x4"])})
fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
sns.boxplot(flat, x="arm", y="AUROC", ax=ax)
save(fig, "seaborn-flat-box")
