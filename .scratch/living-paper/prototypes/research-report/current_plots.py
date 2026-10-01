"""PROTOTYPE, throwaway: plots of the current report on the all-pairs cost (C01 onward)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse
import toydata as T

OUT = Path(__file__).with_name("plots") / "current"
OUT.mkdir(parents=True, exist_ok=True)
COL = {"raw": "#E69F00", "raw_x1x2": "#56B4E9", "raw_x3x4": "#009E73", "raw_allpairs": "#0072B2"}
plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 120, "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 10})
S = T.SIGNALS
cost = {s: np.array(T.contrast("allpairs_cost", s)) for s in S}
ci = {s: T.ci95(list(cost[s])) for s in S}
mean = {s: cost[s].mean() for s in S}
B = 1e3  # show in 0.001 AUROC units
cols = {1: "#F0E442", 2: "#E69F00", 4: "#D55E00", 8: "#CC79A7"}


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


def zero(ax, horizontal=True):
    (ax.axhline if horizontal else ax.axvline)(0, color="#555", lw=0.8, ls="--")


rng = np.random.default_rng(0)
m = np.array([mean[s] for s in S]) * B
lo = np.array([ci[s][0] for s in S]) * B
hi = np.array([ci[s][1] for s in S]) * B

# C01 box with points
fig, ax = plt.subplots(figsize=(6, 3.8))
ax.boxplot([cost[s] * B for s in S], positions=range(4), widths=0.5, showfliers=False,
           medianprops={"color": "#333"}, boxprops={"color": "#666"}, whiskerprops={"color": "#666"}, capprops={"color": "#666"})
for i, s in enumerate(S):
    ax.scatter(i + rng.uniform(-.12, .12, 10), cost[s] * B, color=COL["raw_allpairs"], s=24, zorder=3, alpha=.85)
zero(ax)
ax.set_xticks(range(4))
ax.set_xticklabels([f"signal {s}" for s in S])
ax.set_ylabel("all-pairs cost (0.001 AUROC)")
ax.set_title("Per-seed all-pairs cost, 10 seeds per signal")
save(fig, "C01-cost-box-with-points")

# C02 bar with error bars
fig, ax = plt.subplots(figsize=(6, 3.8))
ax.bar(range(4), m, color=COL["raw_allpairs"], alpha=.8, width=.55)
ax.errorbar(range(4), m, yerr=[m - lo, hi - m], fmt="none", ecolor="#222", capsize=5)
zero(ax)
ax.set_xticks(range(4))
ax.set_xticklabels([f"signal {s}" for s in S])
ax.set_ylabel("mean all-pairs cost (0.001 AUROC)")
ax.set_title("Mean cost with 95% bootstrap interval")
save(fig, "C02-cost-mean-bar-ci")

# C03 line with band
fig, ax = plt.subplots(figsize=(6, 3.8))
ax.fill_between(range(4), lo, hi, color=COL["raw_allpairs"], alpha=.25, label="95% bootstrap interval")
ax.plot(range(4), m, "o-", color=COL["raw_allpairs"], label="mean")
zero(ax)
ax.set_xticks(range(4))
ax.set_xticklabels([str(s) for s in S])
ax.set_xlabel("signal (ordinal axis)")
ax.set_ylabel("cost (0.001 AUROC)")
ax.legend(frameon=False)
ax.set_title("Cost shrinks toward 0 as signal rises")
save(fig, "C03-cost-vs-signal-band")

# C04 per-seed cost, faceted
fig, axs = plt.subplots(1, 4, figsize=(10, 2.8), sharex=True)
for ax, s in zip(axs, S):
    ax.plot(T.SEEDS, cost[s] * B, "o-", color=COL["raw_allpairs"], lw=1, ms=4)
    zero(ax)
    ax.set_title(f"signal {s}")
    ax.set_xlabel("seed")
axs[0].set_ylabel("cost (0.001 AUROC)")
fig.suptitle("Per-seed cost in seed order (independent y scales)", y=1.03, fontsize=10)
fig.tight_layout()
save(fig, "C04-cost-by-seed-faceted")

# C05 DeLong per-seed forest
fig, axs = plt.subplots(1, 4, figsize=(11, 3.6))
ninc = {}
for ax, s in zip(axs, S):
    d = np.array(T.delong(s, "raw_allpairs,raw_x3x4")) * B
    inc = (d[:, 1] <= 0) & (d[:, 2] >= 0)
    ninc[s] = int(inc.sum())
    for k in range(10):
        ax.plot(d[k, 1:], [k, k], color="#888" if inc[k] else "#D55E00", lw=2)
    ax.scatter(d[:, 0], range(10), color=COL["raw_allpairs"], zorder=3, s=18)
    zero(ax, False)
    ax.set_yticks(range(10))
    ax.set_yticklabels(T.SEEDS)
    ax.invert_yaxis()
    ax.set_title(f"signal {s}: {10 - ninc[s]} of 10 exclude 0")
    ax.set_xlabel("0.001 AUROC")
axs[0].set_ylabel("seed")
fig.suptitle("Per-seed DeLong 95% intervals of the difference (orange: excludes 0)", y=1.02, fontsize=10)
fig.tight_layout()
save(fig, "C05-delong-intervals-by-seed")

# C06 density of bootstrap means
fig, ax = plt.subplots(figsize=(6.5, 3.8))
for s in S:
    bm = np.array(T.bootstrap_means(list(cost[s]))) * B
    ax.hist(bm, bins=60, density=True, histtype="step", lw=1.8, color=cols[s], label=f"signal {s}")
    ax.hist(bm, bins=60, density=True, alpha=.15, color=cols[s])
zero(ax, False)
ax.set_xlabel("bootstrap mean cost (0.001 AUROC)")
ax.set_ylabel("density")
ax.legend(frameon=False)
ax.set_title("Bootstrap distribution of the mean cost (10000 resamples)")
save(fig, "C06-bootstrap-means-density")

# C07 grouped bar of mean AUROC by arm
fig, ax = plt.subplots(figsize=(7, 3.8))
w = .2
for j, a in enumerate(T.ARMS):
    mm = [np.mean([T.auroc(s, a, k) for k in T.SEEDS]) for s in S]
    ax.bar(np.arange(4) + (j - 1.5) * w, mm, w, color=COL[a], label=T.ARM_LABEL[a])
ax.set_ylim(.5, 1)
ax.set_xticks(range(4))
ax.set_xticklabels([f"signal {s}" for s in S])
ax.set_ylabel("mean held-out AUROC")
ax.legend(frameon=False, ncol=2, loc="upper left")
ax.set_title("Mean AUROC by arm")
save(fig, "C07-auroc-grouped-bar")

# C08 gain over raw
fig, ax = plt.subplots(figsize=(6.5, 3.8))
gain = np.array([np.mean(T.contrast("paired_gain", s)) for s in S]) * B
ap = np.array([np.mean(T.contrast("allpairs_vs_raw", s)) for s in S]) * B
ax.bar(np.arange(4) - .2, gain, .4, color=COL["raw_x3x4"], label="raw + x3·x4 minus raw")
ax.bar(np.arange(4) + .2, ap, .4, color=COL["raw_allpairs"], label="raw + all pairs minus raw")
ax.set_xticks(range(4))
ax.set_xticklabels([f"signal {s}" for s in S])
ax.set_ylabel("mean AUROC gain over raw (0.001)")
ax.legend(frameon=False, loc="upper left")
ax.set_title("Both arms recover almost the same gain over raw")
save(fig, "C08-gain-over-raw-grouped-bar")

# C09 connected paths across signals
fig, ax = plt.subplots(figsize=(6, 3.8))
for k in range(10):
    ax.plot(range(4), [cost[s][k] * B for s in S], "o-", color=COL["raw_allpairs"], alpha=.5, lw=1, ms=3)
ax.plot(range(4), m, "s-", color="#222", lw=2, label="mean")
zero(ax)
ax.set_xticks(range(4))
ax.set_xticklabels([str(s) for s in S])
ax.set_xlabel("signal")
ax.set_ylabel("cost (0.001 AUROC)")
ax.legend(frameon=False)
ax.set_title("Each seed's cost across signals")
save(fig, "C09-cost-paths-across-signals")

# C10 correlation matrix
Cm = np.corrcoef([cost[s] for s in S])
fig, ax = plt.subplots(figsize=(4.8, 3.8))
im = ax.imshow(Cm, cmap="RdBu_r", vmin=-1, vmax=1)
for i in range(4):
    for j in range(4):
        ax.text(j, i, f"{Cm[i, j]:.2f}", ha="center", va="center", fontsize=9)
ax.set_xticks(range(4))
ax.set_xticklabels(S)
ax.set_yticks(range(4))
ax.set_yticklabels(S)
ax.set_xlabel("signal")
ax.set_ylabel("signal")
fig.colorbar(im, ax=ax, label="Pearson r over 10 seeds")
ax.set_title("Seed-to-seed agreement of the cost")
save(fig, "C10-cost-correlation-matrix")

# C11 scatter with ellipses
fig, ax = plt.subplots(figsize=(5.6, 5))
for s in S:
    a = np.array([T.auroc(s, "raw_x3x4", k) for k in T.SEEDS])
    b = np.array([T.auroc(s, "raw_allpairs", k) for k in T.SEEDS])
    ax.scatter(a, b, color=cols[s], edgecolor="#333", s=28, label=f"signal {s}", zorder=3)
    ev, evec = np.linalg.eigh(np.cov(a, b))
    ang = np.degrees(np.arctan2(evec[1, 1], evec[0, 1]))
    ax.add_patch(Ellipse((a.mean(), b.mean()), 4 * np.sqrt(ev[1]), 4 * np.sqrt(ev[0]) + 1e-6, angle=ang, fill=False, ec=cols[s], lw=1.5))
ax.plot([.5, 1], [.5, 1], color="#555", lw=.8, ls="--")
ax.set_xlim(.58, .97)
ax.set_ylim(.58, .97)
ax.set_aspect("equal")
ax.set_xlabel("AUROC, raw + x3·x4")
ax.set_ylabel("AUROC, raw + all pairs")
ax.legend(frameon=False, loc="upper left")
ax.set_title("Per-seed AUROC pairs (ellipses: 2 sd)")
save(fig, "C11-auroc-pairs-scatter-ellipses")

# C12 faceted scatter with fit (coupling check)
fig, axs = plt.subplots(1, 4, figsize=(11, 2.9))
rs = {}
for ax, s in zip(axs, S):
    a = np.array([T.auroc(s, "raw_x3x4", k) for k in T.SEEDS])
    ax.scatter(a, cost[s] * B, color=COL["raw_x3x4"], s=20)
    p = np.polyfit(a, cost[s] * B, 1)
    xx = np.array([a.min(), a.max()])
    ax.plot(xx, np.polyval(p, xx), color="#333", lw=1)
    rs[s] = np.corrcoef(a, cost[s])[0, 1]
    zero(ax)
    ax.set_title(f"signal {s}: r = {rs[s]:.2f}")
    ax.set_xlabel("AUROC, raw + x3·x4")
axs[0].set_ylabel("cost (0.001)")
fig.suptitle("Cost against one of its own terms (built-in coupling)", y=1.03, fontsize=10)
fig.tight_layout()
save(fig, "C12-cost-vs-own-term-faceted-fit")


def rows(s, k):
    a = np.array(T.summary(s, "raw_x3x4", k)["held_out_scores"])
    b = np.array(T.summary(s, "raw_allpairs", k)["held_out_scores"])
    y = np.array(T.summary(s, "raw_x3x4", k)["held_out_labels"])
    return a, b, y


def lg(p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


# C13 hexbin with marginals
a, b, y = rows(2, 1)
fig = plt.figure(figsize=(5.6, 5.6))
gs = fig.add_gridspec(2, 2, width_ratios=(4, 1), height_ratios=(1, 4), hspace=.05, wspace=.05)
ax = fig.add_subplot(gs[1, 0])
axt = fig.add_subplot(gs[0, 0], sharex=ax)
axr = fig.add_subplot(gs[1, 1], sharey=ax)
ax.hexbin(a, b, gridsize=40, cmap="Blues", mincnt=1, bins="log")
ax.plot([0, 1], [0, 1], color="#D55E00", lw=.8)
axt.hist(a, bins=50, color=COL["raw_x3x4"])
axr.hist(b, bins=50, orientation="horizontal", color=COL["raw_allpairs"])
axt.axis("off")
axr.axis("off")
ax.set_xlabel("score, raw + x3·x4")
ax.set_ylabel("score, raw + all pairs")
fig.suptitle("Held-out scores of the two arms, seed 1, signal 2 (4000 rows)", y=.93, fontsize=10)
save(fig, "C13-score-hexbin-marginals")

# C14 faceted histogram of per-row logit difference
fig, axs = plt.subplots(1, 4, figsize=(11, 2.9))
rowstat = {}
for ax, s in zip(axs, S):
    a, b, y = rows(s, 1)
    d = lg(b) - lg(a)
    rowstat[s] = (d.std(), d.mean(), np.corrcoef(a, b)[0, 1])
    ax.hist(d, bins=60, color=COL["raw_allpairs"])
    ax.axvline(0, color="#555", ls="--", lw=.8)
    ax.set_title(f"signal {s}: sd {d.std():.2f}")
    ax.set_xlabel("logit(all pairs) - logit(x3·x4)")
axs[0].set_ylabel("rows")
fig.suptitle("Per-row score change from the six extra columns, seed 1", y=1.03, fontsize=10)
fig.tight_layout()
save(fig, "C14-row-logit-difference-hist")

# C15 split violin by label
fig, ax = plt.subplots(figsize=(6.5, 3.8))
for i, s in enumerate(S):
    a, b, y = rows(s, 1)
    d = lg(b) - lg(a)
    for lab, side, c in ((0, -1, "#999999"), (1, 1, COL["raw_allpairs"])):
        h, e = np.histogram(d[y == lab], bins=40, range=(-1, 1), density=True)
        h = h / h.max() * .45
        ax.fill_betweenx((e[:-1] + e[1:]) / 2, i, i + side * h, color=c, alpha=.8, step="mid", lw=0)
ax.axhline(0, color="#555", ls="--", lw=.8)
ax.set_xticks(range(4))
ax.set_xticklabels([f"signal {s}" for s in S])
ax.set_ylabel("logit(all pairs) - logit(x3·x4)")
ax.set_title("Row score change by label (left gray: label 0, right blue: label 1), seed 1")
save(fig, "C15-row-change-split-violin-by-label")

# C16 row change against the true score
fig, axs = plt.subplots(1, 2, figsize=(9, 3.6))
for ax, s in zip(axs, (2, 8)):
    a, b, y = rows(s, 1)
    held = T.held_out_rows(1, s)
    o = np.array([T.oracle_score(r) for r in held])
    d = lg(b) - lg(a)
    ax.hexbin(o, d, gridsize=35, cmap="Blues", mincnt=1, bins="log")
    ax.axhline(0, color="#D55E00", lw=.8)
    ax.set_xlabel("true score 0.6·x1 - 0.4·x2 + 1.1·x3·x4")
    ax.set_title(f"signal {s}, seed 1")
axs[0].set_ylabel("logit(all pairs) - logit(x3·x4)")
fig.suptitle("Row-level change along the true score", y=1.02, fontsize=10)
fig.tight_layout()
save(fig, "C16-row-change-vs-true-score")

print("means", {s: round(mean[s] * B, 3) for s in S})
print("ci", {s: tuple(round(x * B, 3) for x in ci[s]) for s in S})
print("neg seeds", {s: int((cost[s] < 0).sum()) for s in S})
print("delong incl0", ninc)
print("cost sd", {s: round(cost[s].std(ddof=1) * B, 3) for s in S})
print("r own term", {s: round(rs[s], 2) for s in S})
print("gain", gain.round(2), "ap", ap.round(2))
print("corr\n", Cm.round(2))
print("rows (sd, mean, corr)", {s: tuple(round(float(x), 3) for x in v) for s, v in rowstat.items()})
