"""A figure whose generator reads a file its result never declared."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

matplotlib.rcParams["pdf.fonttype"] = 42
values = [float(line) for line in Path("data/extra.txt").read_text(encoding="utf-8").split()]
figure, axes = plt.subplots(figsize=(89 / 25.4, 40 / 25.4), layout="constrained")
axes.plot(values, color="#0072B2")
figure.savefig("figures/undeclared/undeclared.pdf", metadata={"CreationDate": None})
figure.savefig("figures/undeclared/undeclared.png", dpi=300)
