"""PROTOTYPE, throwaway: every plot of the general report, P01 onward, from the toy's M7 results.

`python3 general_plots.py` writes plots/general/P<nn>-<slug>.png and plots/general/plots.json
(each plot's result, chart type, and the index entries it draws on), and prints the numbers the
report quotes. Matplotlib only: it is the one plotting library installed for python3 here.
"""

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Ellipse

import toydata as T

OUT = Path(__file__).with_name("plots") / "general"
OUT.mkdir(parents=True, exist_ok=True)
# Okabe-Ito, from the project's figures/style.json
ARM_COLOR = {"raw": "#E69F00", "raw_x1x2": "#56B4E9", "raw_x3x4": "#009E73", "raw_allpairs": "#0072B2"}
SIG_COLOR = {1: "#F0E442", 2: "#E69F00", 4: "#D55E00", 8: "#CC79A7"}
CEIL = "#555555"
plt.rcParams.update({"figure.dpi": 130, "savefig.dpi": 130, "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titlesize": 10, "axes.titleweight": "bold"})
PLOTS = []


def save(fig, pid, slug, result, chart, entries, title):
    name = f"{pid}-{slug}.png"
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)
    PLOTS.append({"id": pid, "file": f"plots/general/{name}", "result": result, "chart_type": chart,
                  "index_entries": entries, "title": title})


def mean(xs):
    return sum(xs) / len(xs)


def logit(p):
    return T.logit(p)


S4 = 4
seeds = list(T.SEEDS)

# ---------------- R1: the headline gain at signal 4 ----------------
raw4 = [T.auroc(S4, "raw", s) for s in seeds]
x34 = [T.auroc(S4, "raw_x3x4", s) for s in seeds]
gain4 = T.contrast("paired_gain", S4)
lo4, hi4 = T.ci95(gain4)

fig, ax = plt.subplots(figsize=(4.2, 4))
for s, a, b in zip(seeds, raw4, x34):
    ax.plot([0, 1], [a, b], color="#999999", lw=0.8, marker="o", ms=4, mfc="white")
    ax.text(1.04, b, f"seed {s}", fontsize=6, va="center", color="#777777")
ax.plot([0, 1], [mean(raw4), mean(x34)], color="black", lw=2.2, marker="o", ms=6, label="mean of ten seeds")
ax.set_xticks([0, 1], [T.ARM_LABEL["raw"], T.ARM_LABEL["raw_x3x4"]])
ax.set_xlim(-0.3, 1.35)
ax.set_ylabel("held-out AUROC")
ax.set_title("Each seed's two arms, joined")
ax.legend(frameon=False, loc="lower right")
save(fig, "P01", "slope-raw-vs-x3x4", "R1", "connected scatter (paths)",
     ["Scatter plot with point paths on hover and search box"], "Each seed's raw and raw + x3·x4 AUROC, joined")

fig, ax = plt.subplots(figsize=(3.4, 4))
ax.boxplot([gain4], widths=0.4, showfliers=False, medianprops={"color": "#333333"})
jit = np.linspace(-0.12, 0.12, 10)
ax.scatter(1 + jit, gain4, color=ARM_COLOR["raw_x3x4"], zorder=3, s=18)
ax.errorbar([1.35], [mean(gain4)], yerr=[[mean(gain4) - lo4], [hi4 - mean(gain4)]], fmt="D", color="black", capsize=4,
            label="mean, bootstrap 95% interval")
ax.axhline(0, color="#aaaaaa", lw=0.8)
ax.set_xticks([1], ["paired gain\nsignal 4"])
ax.set_ylim(-0.01, 0.105)
ax.set_ylabel("AUROC(raw + x3·x4) − AUROC(raw)")
ax.set_title("Ten per-seed paired gains")
ax.legend(frameon=False, loc="lower right", fontsize=7)
save(fig, "P02", "box-gain-signal4", "R1", "box with points",
     ["Boxplot with individual data points", "Horizontal boxplot with observations", "Basic ggplot2 boxplot"],
     "The ten per-seed paired gains at signal 4, with the mean and its interval")

dl = T.delong(S4, "raw_x3x4,raw")
fig, ax = plt.subplots(figsize=(6, 3.4))
xs = np.arange(1, 11)
diffs = [d[0] for d in dl]
ax.bar(xs, diffs, color=ARM_COLOR["raw_x3x4"], alpha=0.75, width=0.65)
ax.errorbar(xs, diffs, yerr=[[d[0] - d[1] for d in dl], [d[2] - d[0] for d in dl]], fmt="none", color="black", capsize=3)
ax.bar([12], [mean(gain4)], color="#333333", width=0.65)
ax.errorbar([12], [mean(gain4)], yerr=[[mean(gain4) - lo4], [hi4 - mean(gain4)]], fmt="none", color="black", capsize=3)
ax.set_xticks(list(xs) + [12], [str(s) for s in seeds] + ["mean"])
ax.set_xlabel("seed (bars 1–10: DeLong 95% interval on that seed's 4000 held-out rows; last bar: bootstrap over seeds)")
ax.set_ylabel("paired gain")
ax.set_title("Per-seed paired gain with its DeLong interval, signal 4")
save(fig, "P03", "bar-delong-signal4", "R1", "bar with error bars", ["Barplot with error bars"],
     "Per-seed paired gain with each seed's DeLong interval, signal 4")

boot = T.bootstrap_means(gain4)
fig, ax = plt.subplots(figsize=(5.4, 3.2))
ax.hist(boot, bins=60, color=ARM_COLOR["raw_x3x4"], alpha=0.45, density=True, label="10000 resampled means")
h = np.std(boot) * len(boot) ** (-1 / 5) * 1.06
grid = np.linspace(min(boot), max(boot), 300)
b = np.array(boot)
dens = [np.mean(np.exp(-0.5 * ((g - b[::10]) / h) ** 2)) / (h * math.sqrt(2 * math.pi)) for g in grid]
ax.plot(grid, dens, color="black", lw=1.2, label="density estimate")
for v in (lo4, hi4):
    ax.axvline(v, color="black", ls="--", lw=0.8)
ax.set_xlabel("mean paired gain at signal 4 (one resample of the ten seeds)")
ax.set_yticks([])
ax.set_title("Bootstrap distribution of the mean paired gain")
ax.legend(frameon=False, fontsize=7)
save(fig, "P04", "hist-bootstrap-signal4", "R1", "histogram + density",
     ["Histogram with Adjustable Bin Size", "Basic density plot with seaborn", "Density plot with shade in seaborn",
      "Control the bandwidth of a seaborn density plot", "Density with Some Shade", "Horizontal density plot"],
     "Bootstrap distribution of the mean paired gain at signal 4")

# held-out rows of seed 1 at signal 4, both arms' scores
held = T.held_out_rows(1, S4)
y = np.array([r["y"] for r in held])
p_raw = np.array(T.summary(S4, "raw", 1)["held_out_scores"])
p_x34 = np.array(T.summary(S4, "raw_x3x4", 1)["held_out_scores"])
oracle = np.array([T.oracle_score(r) for r in held])
fig, ax = plt.subplots(figsize=(5.6, 3.6))
data, pos, cols = [], [], []
for i, (arm, p) in enumerate((("raw", p_raw), ("raw_x3x4", p_x34))):
    for cls, side in ((0, -1), (1, 1)):
        v = ax.violinplot([p[y == cls]], positions=[i], widths=0.8, showextrema=False)
        body = v["bodies"][0]
        verts = body.get_paths()[0].vertices
        c = 0 + i
        verts[:, 0] = np.where(side < 0, np.minimum(verts[:, 0], c), np.maximum(verts[:, 0], c))
        body.set_facecolor("#888888" if cls == 0 else ARM_COLOR[arm])
        body.set_edgecolor("black")
        body.set_alpha(0.7)
ax.set_xticks([0, 1], [T.ARM_LABEL["raw"], T.ARM_LABEL["raw_x3x4"]])
ax.set_ylabel("held-out score (predicted P(y = 1))")
ax.set_title("Scores by class, seed 1, signal 4\n(gray: y = 0, colored: y = 1)")
save(fig, "P05", "violin-scores-by-class", "R1", "split violin",
     ["Grouped violinplots with split violins", "Same Color, Different Shade"],
     "Held-out scores by class for the two arms, seed 1")


def roc(scores, labels):
    order = np.argsort(-scores)
    l = labels[order]
    tp = np.cumsum(l) / l.sum()
    fp = np.cumsum(1 - l) / (1 - l).sum()
    return np.concatenate([[0], fp]), np.concatenate([[0], tp])


fig, ax = plt.subplots(figsize=(4, 4))
for name, sc, col, ls in (("raw", p_raw, ARM_COLOR["raw"], "-"), ("raw + x3·x4", p_x34, ARM_COLOR["raw_x3x4"], "-"),
                          ("Bayes ceiling (true f(x))", oracle, CEIL, "--")):
    fx, ty = roc(sc, y)
    ax.plot(fx, ty, color=col, ls=ls, lw=1.4, label=name)
ax.plot([0, 1], [0, 1], color="#cccccc", lw=0.8)
ax.set_xlabel("false positive rate")
ax.set_ylabel("true positive rate")
ax.set_title("ROC curves, seed 1, signal 4")
ax.legend(frameon=False, fontsize=7, loc="lower right")
save(fig, "P06", "roc-seed1", "R1", "ROC curve (not in the index)", [],
     "ROC curves of both arms and the Bayes ceiling, seed 1")

x3 = np.array([r["x3"] for r in held])
x4 = np.array([r["x4"] for r in held])
dlog = np.array([logit(b) - logit(a) for a, b in zip(p_raw, p_x34)])
fig, ax = plt.subplots(figsize=(4.6, 4))
hb = ax.hexbin(x3, x4, C=dlog, reduce_C_function=np.mean, gridsize=14, cmap="RdBu_r",
               norm=TwoSlopeNorm(vcenter=0, vmin=-4, vmax=4))
fig.colorbar(hb, ax=ax, label="mean change in log-odds, raw + x3·x4 minus raw")
ax.set_xlabel("x3")
ax.set_ylabel("x4")
ax.set_title("Where the new column moves the score")
save(fig, "P07", "hexbin-x3-x4", "R1", "hexbin", ["Hexbin plot with marginal distributions", "Plot a Basic 2D Histogram using Matplotlib"],
     "Mean change in a row's log-odds over the x3, x4 plane, seed 1")

lr = np.array([logit(a) for a in p_raw])
lx = np.array([logit(b) for b in p_x34])
fig = plt.figure(figsize=(5, 5))
gs = fig.add_gridspec(4, 4, hspace=0.05, wspace=0.05)
ax = fig.add_subplot(gs[1:, :3])
axt = fig.add_subplot(gs[0, :3], sharex=ax)
axr = fig.add_subplot(gs[1:, 3], sharey=ax)
for cls, col in ((0, "#888888"), (1, ARM_COLOR["raw_x3x4"])):
    m = y == cls
    ax.scatter(lr[m], lx[m], s=3, alpha=0.35, color=col, label=f"y = {cls}")
    axt.hist(lr[m], bins=40, color=col, alpha=0.5)
    axr.hist(lx[m], bins=40, color=col, alpha=0.5, orientation="horizontal")
ax.plot([-6, 6], [-6, 6], color="black", lw=0.6)
ax.set_xlabel("log-odds, raw arm")
ax.set_ylabel("log-odds, raw + x3·x4 arm")
ax.legend(frameon=False, markerscale=4, fontsize=7)
axt.axis("off")
axr.axis("off")
axt.set_title("Each held-out row scored by both arms, seed 1, signal 4")
save(fig, "P08", "joint-scores", "R1", "joint histogram", ["Joint and marginal histograms"],
     "Each held-out row's score under both arms, with marginals per class")

# ---------------- R2: the gain belongs to x3*x4 ----------------
fig, ax = plt.subplots(figsize=(6.6, 3.6))
w = 0.2
for i, arm in enumerate(T.ARMS):
    ms, errs = [], [[], []]
    for j, s in enumerate(T.SIGNALS):
        v = [T.auroc(s, arm, k) for k in seeds]
        lo, hi = T.ci95(v)
        ms.append(mean(v))
        errs[0].append(mean(v) - lo)
        errs[1].append(hi - mean(v))
    xpos = np.arange(4) + (i - 1.5) * w
    ax.bar(xpos, np.array(ms) - 0.5, bottom=0.5, width=w, color=ARM_COLOR[arm], label=T.ARM_LABEL[arm])
    ax.errorbar(xpos, ms, yerr=errs, fmt="none", color="black", capsize=2, lw=0.8)
    for xp, m in zip(xpos, ms):
        ax.text(xp, m + 0.012, f"{m:.3f}", ha="center", va="bottom", fontsize=5.5, rotation=90)
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.set_ylim(0.5, 1.04)
ax.set_ylabel("mean held-out AUROC\n(bars start at chance, 0.5)")
ax.set_title("Mean AUROC per arm and signal")
ax.legend(frameon=False, fontsize=7, ncol=4, loc="upper left")
save(fig, "P09", "grouped-bar-auroc", "R2", "grouped bar with error bars and labels",
     ["Grouped barplots", "Grouped Bar Chart with xOffset and overlapping bars", "A Bar Plot With 2 Variables",
      "Barplot with error bars", "Bar Chart with Labels based on Measured Luminance"],
     "Mean AUROC of the four arms at each signal")

fig, ax = plt.subplots(figsize=(4.4, 4.2))
for s in T.SIGNALS:
    ax.scatter(T.contrast("paired_gain", s), T.contrast("credit_margin", s), color=SIG_COLOR[s], edgecolor="black",
               lw=0.4, s=26, label=f"signal {s}", marker={1: "o", 2: "s", 4: "^", 8: "D"}[s])
ax.plot([0, 0.13], [0, 0.13], color="#999999", lw=0.8, ls="--")
ax.set_xlabel("paired gain (vs raw)")
ax.set_ylabel("credit margin (vs raw + x1·x2)")
ax.set_title("Per seed: gain over raw against margin over the wrong pair")
ax.legend(frameon=False, fontsize=7)
save(fig, "P10", "scatter-gain-vs-credit", "R2", "scatter, hue and shape",
     ["Scatterplot with multiple semantics", "The Shapes of a Scatter Plot", "Using Letters as Shapes"],
     "Per-seed paired gain against credit margin, every signal")

fig, ax = plt.subplots(figsize=(5, 3.4))
vals = [T.contrast("wrong_pair_vs_raw", s) for s in T.SIGNALS]
ax.boxplot(vals, widths=0.45, showfliers=False, medianprops={"color": "#333333"})
for i, v in enumerate(vals):
    ax.scatter(i + 1 + jit, v, s=12, color=ARM_COLOR["raw_x1x2"], zorder=3)
ax.axhline(0, color="#aaaaaa", lw=0.8)
ax.set_xticks(range(1, 5), [f"signal {s}" for s in T.SIGNALS])
ax.set_ylabel("AUROC(raw + x1·x2) − AUROC(raw)")
ax.set_title("The wrong product column, per seed")
save(fig, "P11", "grouped-box-wrong-pair", "R2", "grouped box with points", ["Grouped boxplots", "Boxplot with individual data points"],
     "What the wrong product column adds over raw, per seed and signal")

# ---------------- R3: across the signal sweep ----------------
fig, ax = plt.subplots(figsize=(5.4, 3.6))
for name, col, lab in (("paired_gain", ARM_COLOR["raw_x3x4"], "paired gain (vs raw)"),
                       ("credit_margin", ARM_COLOR["raw_x1x2"], "credit margin (vs raw + x1·x2)")):
    m, lo, hi = [], [], []
    for s in T.SIGNALS:
        v = T.contrast(name, s)
        a, b = T.ci95(v)
        m.append(mean(v)); lo.append(a); hi.append(b)
        off = 1.03 if name == "credit_margin" else 0.97
        ax.scatter([s * off] * 10, v, s=6, color=col, alpha=0.5)
    ax.fill_between(T.SIGNALS, lo, hi, color=col, alpha=0.25)
    ax.plot(T.SIGNALS, m, color=col, marker="o", label=lab)
ax.set_xscale("log", base=2)
ax.set_xticks(T.SIGNALS, [str(s) for s in T.SIGNALS])
ax.axhline(0, color="#aaaaaa", lw=0.8)
ax.set_xlabel("signal (log scale; measured at 1, 2, 4, 8 only)")
ax.set_ylabel("AUROC difference")
ax.set_title("Gain and margin across the sweep, band = bootstrap 95%")
ax.legend(frameon=False, fontsize=7)
save(fig, "P12", "line-band-sweep", "R3", "line with band", ["Timeseries plot with error bands"],
     "Mean paired gain and credit margin across signals with bootstrap bands")

fig, axs = plt.subplots(1, 4, figsize=(9, 2.8), sharey=True)
for ax, arm in zip(axs, T.ARMS):
    for k in seeds:
        ax.plot(T.SIGNALS, [T.auroc(s, arm, k) for s in T.SIGNALS], color=ARM_COLOR[arm], lw=0.5, alpha=0.5)
    ax.plot(T.SIGNALS, [mean([T.auroc(s, arm, k) for k in seeds]) for s in T.SIGNALS], color=ARM_COLOR[arm], lw=2)
    ax.plot(T.SIGNALS, [mean(T.ceiling(s)) for s in T.SIGNALS], color=CEIL, ls="--", lw=1)
    ax.axhline(T.TARGET, color="#bbbbbb", lw=0.6, ls=":")
    ax.set_xscale("log", base=2)
    ax.set_xticks(T.SIGNALS, [str(s) for s in T.SIGNALS])
    ax.set_title(T.ARM_LABEL[arm], fontsize=8)
    ax.set_xlabel("signal")
axs[0].set_ylabel("held-out AUROC")
fig.suptitle("Each arm across the sweep: thin lines are seeds, dashed is the Bayes ceiling, dotted is 0.82", fontsize=9)
save(fig, "P13", "faceted-lines-arms", "R3", "line, faceted", ["Line plots on multiple facets", "Weather Forecast"],
     "Each arm's AUROC across signals, one panel per arm")

fig, axs = plt.subplots(1, 4, figsize=(9, 2.4), sharey=True)
for ax, s in zip(axs, T.SIGNALS):
    ax.hist(T.contrast("paired_gain", s), bins=6, color=SIG_COLOR[s], edgecolor="black")
    ax.set_title(f"signal {s}", fontsize=8)
    ax.set_xlabel("paired gain")
axs[0].set_ylabel("seeds")
fig.suptitle("Per-seed paired gain, one histogram per signal (ten values each)", fontsize=9)
save(fig, "P14", "faceted-hist-gain", "R3", "histogram, faceted", ["Facetting histograms by subsets of data"],
     "Histograms of the ten per-seed gains, one per signal")

fig, ax = plt.subplots(figsize=(5.4, 3))
for s in T.SIGNALS:
    v = np.array(T.contrast("paired_gain", s))
    g = np.linspace(-0.005, 0.13, 400)
    hh = 0.004
    d = [np.mean(np.exp(-0.5 * ((x - v) / hh) ** 2)) / (hh * math.sqrt(2 * math.pi)) for x in g]
    ax.fill_between(g, d, color=SIG_COLOR[s], alpha=0.45, label=f"signal {s}")
    ax.plot(g, d, color="black", lw=0.6)
ax.set_yticks([])
ax.set_xlabel("per-seed paired gain (kernel bandwidth 0.004)")
ax.set_title("Density of the per-seed gains, one curve per signal")
ax.legend(frameon=False, fontsize=7)
save(fig, "P15", "density-gain-by-signal", "R3", "density, several groups",
     ["Density plot of several variables"], "Density of the per-seed gains per signal")

fig, ax = plt.subplots(figsize=(5, 3.2))
for i, s in enumerate(T.SIGNALS):
    v = T.contrast("paired_gain", s)
    ax.scatter([i] * 10 + np.linspace(-0.08, 0.08, 10), v, s=12, color=SIG_COLOR[s], edgecolor="black", lw=0.3)
    ax.plot([i - 0.25, i + 0.25], [mean(v)] * 2, color="black", lw=2)
    ax.text(i + 0.3, mean(v), f"{100 * mean(v):.1f} pts", va="center", fontsize=7)
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.axhline(0, color="#aaaaaa", lw=0.8)
ax.set_ylabel("paired gain (1 point = 0.01 AUROC)")
ax.set_title("Mean gain with every seed, per signal")
save(fig, "P16", "means-with-obs", "R3", "means with observations", ["Conditional means with observations"],
     "Mean paired gain with every seed's value, per signal")


def ellipse(ax, xs, ys, col):
    cov = np.cov(xs, ys)
    vals, vecs = np.linalg.eigh(cov)
    ang = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))
    k = math.sqrt(5.991)
    ax.add_patch(Ellipse((np.mean(xs), np.mean(ys)), 2 * k * math.sqrt(vals[1]), 2 * k * math.sqrt(vals[0]), angle=ang,
                         facecolor=col, alpha=0.2, edgecolor=col))


fig, ax = plt.subplots(figsize=(4.6, 4.4))
for s in T.SIGNALS:
    a = [T.auroc(s, "raw", k) for k in seeds]
    b = [T.auroc(s, "raw_x3x4", k) for k in seeds]
    ax.scatter(a, b, s=14, color=SIG_COLOR[s], edgecolor="black", lw=0.3, label=f"signal {s}")
    ellipse(ax, a, b, SIG_COLOR[s])
ax.plot([0.55, 1], [0.55, 1], color="#999999", ls="--", lw=0.8)
ax.set_xlabel("AUROC, raw")
ax.set_ylabel("AUROC, raw + x3·x4")
ax.set_title("Seeds as points, 95% ellipse per signal")
ax.legend(frameon=False, fontsize=7)
save(fig, "P17", "scatter-ellipses", "R3", "scatter with CI ellipses", ["Confidence Interval Ellipses"],
     "Each seed's two AUROCs, an ellipse per signal")

fig, axs = plt.subplots(1, 4, figsize=(9, 2.5))
slopes = {}
for ax, s in zip(axs, T.SIGNALS):
    a = np.array([T.auroc(s, "raw", k) for k in seeds])
    g = np.array(T.contrast("paired_gain", s))
    ax.scatter(a, g, s=14, color=SIG_COLOR[s], edgecolor="black", lw=0.3)
    sl, ic = np.polyfit(a, g, 1)
    r = np.corrcoef(a, g)[0, 1]
    slopes[s] = (sl, r)
    xx = np.linspace(a.min(), a.max(), 10)
    ax.plot(xx, sl * xx + ic, color="black", lw=0.8)
    ax.set_title(f"signal {s}: r = {r:.2f}", fontsize=8)
    ax.set_xlabel("AUROC, raw")
axs[0].set_ylabel("paired gain")
fig.suptitle("Is the gain larger on seeds where raw does worse? One panel per signal, least-squares line", fontsize=9)
fig.tight_layout()
save(fig, "P18", "faceted-scatter-fit", "R3", "faceted scatter with fit", ["Anscombe’s quartet", "Anscombe’s Quartet"],
     "Paired gain against the raw arm's AUROC per seed, one panel per signal")

fig, ax = plt.subplots(figsize=(5.4, 3.4))
mr = [mean([T.auroc(s, "raw", k) for k in seeds]) for s in T.SIGNALS]
mx = [mean([T.auroc(s, "raw_x3x4", k) for k in seeds]) for s in T.SIGNALS]
ax.fill_between(T.SIGNALS, 0.5, mr, color=ARM_COLOR["raw"], alpha=0.5, label="raw over chance")
ax.fill_between(T.SIGNALS, mr, mx, color=ARM_COLOR["raw_x3x4"], alpha=0.6, label="paired gain")
ax.plot(T.SIGNALS, mx, color="black", lw=0.8)
ax.set_xscale("log", base=2)
ax.set_xticks(T.SIGNALS, [str(s) for s in T.SIGNALS])
ax.set_ylim(0.5, 1)
ax.set_xlabel("signal (log scale)")
ax.set_ylabel("mean held-out AUROC")
ax.set_title("The gain as the band between the two arms")
ax.legend(frameon=False, fontsize=7, loc="upper left")
save(fig, "P19", "area-gain", "R3", "area", ["Basic Area Chart", "Improved Area Chart", "Area chart with base R", "Coal Production", "Area Chart and Faceting"],
     "The paired gain drawn as the area between the arms' mean AUROC")

# ---------------- R4: the all-pairs cost (brief; the current report goes deeper) ----------------
fig, ax = plt.subplots(figsize=(5, 3.2))
for i, s in enumerate(T.SIGNALS):
    v = T.contrast("allpairs_cost", s)
    lo, hi = T.ci95(v)
    ax.bar(i, mean(v), color=ARM_COLOR["raw_allpairs"], alpha=0.75, width=0.55)
    ax.errorbar(i, mean(v), yerr=[[mean(v) - lo], [hi - mean(v)]], fmt="none", color="black", capsize=4)
ax.axhline(0, color="black", lw=0.6)
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.set_ylabel("AUROC(raw + all pairs) − AUROC(raw + x3·x4)")
ax.set_title("What not knowing the pair costs, bootstrap 95%")
save(fig, "P20", "bar-allpairs-cost", "R4", "bar with error bars", ["Barplot with error bars"],
     "Mean all-pairs cost per signal with its interval")

# ---------------- R5: the Bayes ceiling ----------------
mc = [mean(T.ceiling(s)) for s in T.SIGNALS]
fig, ax = plt.subplots(figsize=(5.4, 3.4))
ax.stackplot(T.SIGNALS, np.array(mr) - 0.5, np.array(mx) - np.array(mr), np.array(mc) - np.array(mx),
             colors=[ARM_COLOR["raw"], ARM_COLOR["raw_x3x4"], CEIL], alpha=0.75, baseline="zero",
             labels=["raw over chance", "paired gain", "left to the ceiling"])
ax.set_xscale("log", base=2)
ax.set_xticks(T.SIGNALS, [str(s) for s in T.SIGNALS])
ax.set_xlabel("signal (log scale)")
ax.set_ylabel("AUROC above chance (0.5)")
ax.set_title("What the ceiling is made of, stacked")
ax.legend(frameon=False, fontsize=7, loc="upper left")
save(fig, "P21", "stacked-area-ceiling", "R5", "stacked area", ["Stacked area chart with R"],
     "The Bayes ceiling split into raw, the paired gain, and what is left")

fig, ax = plt.subplots(figsize=(5.4, 3.4))
parts = [np.array(mr) - 0.5, np.array(mx) - np.array(mr), np.array(mc) - np.array(mx)]
bottom = np.zeros(4)
for part, col, lab in zip(parts, [ARM_COLOR["raw"], ARM_COLOR["raw_x3x4"], CEIL], ["raw over chance", "paired gain", "left to the ceiling"]):
    ax.bar(range(4), part, bottom=bottom, color=col, label=lab, width=0.6)
    for i, (b0, pv) in enumerate(zip(bottom, part)):
        if pv > 0.02:
            ax.text(i, b0 + pv / 2, f"{pv:.3f}", ha="center", va="center", fontsize=7, color="white")
    bottom += part
for i, v in enumerate(parts[2]):
    ax.text(i, bottom[i] + 0.008, f"+{v:.4f}", ha="center", fontsize=6.5)
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.set_ylabel("AUROC above chance (0.5)")
ax.set_title("The same split as bars, values labelled")
ax.legend(frameon=False, fontsize=7, loc="upper left")
save(fig, "P22", "stacked-bar-ceiling", "R5", "stacked bar", ["Stacked Bar Chart", "Reorder stacked bar segments"],
     "The Bayes ceiling split per signal, as stacked bars")

fig, ax = plt.subplots(figsize=(5.4, 3.2))
gaps = [[c - T.auroc(s, "raw_x3x4", k) for c, k in zip(T.ceiling(s), seeds)] for s in T.SIGNALS]
allg = [g for gs in gaps for g in gs]
minpos = min(g for g in allg if g > 0)
bins = np.logspace(math.log10(minpos * 0.8), math.log10(max(allg) * 1.2), 14)
ax.hist([[max(g, minpos) for g in gs] for gs in gaps], bins=bins, stacked=True, color=[SIG_COLOR[s] for s in T.SIGNALS],
        edgecolor="black", lw=0.3, label=[f"signal {s}" for s in T.SIGNALS])
ax.set_xscale("log")
ax.set_xlabel("Bayes ceiling − AUROC(raw + x3·x4), per seed (log scale)")
ax.set_ylabel("seeds")
ax.set_title("How far each seed's fit is from the ceiling")
ax.legend(frameon=False, fontsize=7)
save(fig, "P23", "stacked-hist-log-gap", "R5", "stacked histogram, log scale", ["Stacked histogram on a log scale"],
     "Each seed's distance to the ceiling, stacked by signal, log scale")

fig, ax = plt.subplots(figsize=(4.6, 4.4))
for s in T.SIGNALS:
    c = T.ceiling(s)
    b = [T.auroc(s, "raw_x3x4", k) for k in seeds]
    g = T.contrast("paired_gain", s)
    ax.scatter(c, b, s=[600 * x for x in g], color=SIG_COLOR[s], edgecolor="black", lw=0.4, alpha=0.8, label=f"signal {s}")
ax.plot([0.58, 0.97], [0.58, 0.97], color="#999999", ls="--", lw=0.8)
ax.set_xlabel("Bayes ceiling on the seed's held-out rows")
ax.set_ylabel("AUROC, raw + x3·x4")
ax.set_title("Fit against ceiling, bubble size = paired gain")
ax.legend(frameon=False, fontsize=7, markerscale=0.5)
save(fig, "P24", "bubble-ceiling", "R5", "bubble", ["Oh My Bubbles"],
     "Each seed's fit against its ceiling, sized by the paired gain")

# ---------------- R6: the 0.82 target ----------------
counts = np.array([[sum(T.auroc(s, arm, k) >= T.TARGET for k in seeds) for s in T.SIGNALS] for arm in T.ARMS])
means = np.array([[mean([T.auroc(s, arm, k) for k in seeds]) for s in T.SIGNALS] for arm in T.ARMS])
fig, ax = plt.subplots(figsize=(4.8, 3.2))
for i, arm in enumerate(T.ARMS):
    for j, s in enumerate(T.SIGNALS):
        ax.scatter(j, i, s=30 + 60 * counts[i, j], c=[means[i, j]], cmap="viridis", vmin=0.55, vmax=0.95, edgecolor="black", lw=0.4)
sc = ax.scatter([], [], c=[], cmap="viridis", vmin=0.55, vmax=0.95)
fig.colorbar(sc, ax=ax, label="mean AUROC")
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.set_yticks(range(4), [T.ARM_LABEL[a] for a in T.ARMS])
ax.set_xlim(-0.5, 3.5); ax.set_ylim(-0.5, 3.5)
ax.set_title("Seeds at or above 0.82 (size) and mean AUROC (color)")
save(fig, "P25", "scatter-heatmap-target", "R6", "scatter heatmap", ["Scatterplot heatmap"],
     "Seeds reaching 0.82 and the mean AUROC, arm by signal")

fig, ax = plt.subplots(figsize=(5, 3.2))
ax.imshow(counts, cmap="Greens", vmin=0, vmax=10, aspect="auto")
for i in range(4):
    for j in range(4):
        ax.text(j, i, f"{counts[i, j]}/10\n{means[i, j]:.3f}", ha="center", va="center", fontsize=7,
                color="white" if counts[i, j] > 6 else "black")
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.set_yticks(range(4), [T.ARM_LABEL[a] for a in T.ARMS])
ax.set_title("Seeds at or above 0.82, and mean AUROC, per tile")
save(fig, "P26", "tiles-target", "R6", "tile grid with labels", ["Periodic Table"],
     "Seeds reaching 0.82 per arm and signal, as labelled tiles")

fig, ax = plt.subplots(figsize=(7, 3.4))
for j, s in enumerate(T.SIGNALS):
    for i, arm in enumerate(T.ARMS):
        v = [T.auroc(s, arm, k) for k in seeds]
        x = j + (i - 1.5) * 0.2
        bp = ax.boxplot([v], positions=[x], widths=0.15, showfliers=False, patch_artist=True,
                        medianprops={"color": "black"})
        bp["boxes"][0].set_facecolor(ARM_COLOR[arm])
        ax.scatter([x] * 10, v, s=4, color="black", zorder=3)
ax.axhline(T.TARGET, color="#D62728", lw=1, ls="--")
ax.text(3.6, T.TARGET, "0.82", color="#D62728", va="center", fontsize=7)
ax.set_xticks(range(4), [f"signal {s}" for s in T.SIGNALS])
ax.set_ylabel("held-out AUROC")
ax.set_title("Every seed's AUROC per arm and signal against the 0.82 line")
from matplotlib.patches import Patch

ax.legend(handles=[Patch(color=ARM_COLOR[a], label=T.ARM_LABEL[a]) for a in T.ARMS], frameon=False, fontsize=7, ncol=4, loc="upper left")
save(fig, "P27", "grouped-box-target", "R6", "grouped box", ["Grouped boxplots", "Basic ggplot2 boxplot"],
     "Every seed's AUROC per arm and signal, with the 0.82 line")

(OUT / "plots.json").write_text(json.dumps(PLOTS, indent=1, ensure_ascii=False) + "\n")

# ---------------- numbers the report quotes ----------------
print("plots", len(PLOTS), "| index entries drawn on:", len({e for p in PLOTS for e in p["index_entries"]}))
for s in T.SIGNALS:
    row = {}
    for name in T.CONTRASTS:
        v = T.contrast(name, s)
        lo, hi = T.ci95(v)
        row[name] = f"{mean(v):+.4f} [{lo:+.4f}, {hi:+.4f}] pos={sum(x > 0 for x in v)}"
    print(f"signal {s}:", json.dumps(row, indent=None))
    print("   ceiling mean", f"{mean(T.ceiling(s)):.4f}", "gap", f"{mean(gaps[T.SIGNALS.index(s)]):.5f}",
          "min gap", f"{min(gaps[T.SIGNALS.index(s)]):.5f}", "slope/r gain~raw", slopes[s])
print("counts >= 0.82 (arms x signals)\n", counts)
print("means\n", np.round(means, 4))
print("seed1 s4 raw-vs-x34 logit diff by quadrant sign(x3*x4):",
      float(np.mean(dlog[(x3 * x4) > 0.25])), float(np.mean(dlog[(x3 * x4) < -0.25])), float(np.mean(dlog[np.abs(x3 * x4) < 0.05])))
