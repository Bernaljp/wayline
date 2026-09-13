"""A figure drawn from unseeded noise, so no two runs agree."""

import matplotlib
import numpy

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

matplotlib.rcParams["pdf.fonttype"] = 42
figure, axes = plt.subplots(figsize=(89 / 25.4, 40 / 25.4), layout="constrained")
axes.imshow(numpy.random.default_rng().random((40, 80)), cmap="viridis", interpolation="nearest").set_gid("quantity:density")
axes.set_axis_off()
figure.savefig("figures/noisy/noisy.pdf", metadata={"CreationDate": None})
figure.savefig("figures/noisy/noisy.png", dpi=300)
