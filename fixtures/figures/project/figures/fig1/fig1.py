"""Figure 1: held-out AUROC per method (a) and AUROC against runtime (b)."""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["font.size"] = 6

OUT = Path("figures/fig1")
STYLE = json.loads(Path("figures/style.json").read_text(encoding="utf-8"))


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


scores = rows("results/t7-a1/scores.csv")
timing = rows("results/t8-a1/timing.csv")

figure, (left, right) = plt.subplots(1, 2, figsize=(89 / 25.4, 48 / 25.4), layout="constrained")
left.set_gid("panel:a")
right.set_gid("panel:b")
left.bar([row["method"] for row in scores], [float(row["auroc"]) for row in scores], color=STYLE["categorical"][1:1 + len(scores)])
left.set_ylabel("Held-out AUROC")
right.scatter([float(row["seconds"]) for row in timing], [float(row["auroc"]) for row in timing], color=STYLE["categorical"][5], s=8)
right.set_xlabel("Runtime (s)")
right.set_ylabel("AUROC")
for axes, letter in ((left, "a"), (right, "b")):
    axes.set_title(letter, loc="left", fontweight="bold", fontsize=8)
figure.savefig(OUT / "fig1.pdf", metadata={"CreationDate": None})
figure.savefig(OUT / "fig1.png", dpi=300)
