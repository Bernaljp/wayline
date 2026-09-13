"""Rebuild the figure-check samples: `python fixtures/figures/make.py` from the harness root.

Needs matplotlib and numpy (the suite itself needs neither). What it writes, all committed:

- `project/`: a project with two result runs in `results/`, their `research/manifest.json`, the
  default house style with one ramp, and three figures, each with its generator, the files the
  generator saved, a caption, notes, and a `result.json`:
  - `fig1`, a two-panel figure that passes every check;
  - `undeclared`, whose generator reads a file its result does not declare, so it cannot
    regenerate in the clean room;
  - `noisy`, whose generator draws unseeded noise, so a regeneration does not match.
  `request.json` is the figure_request the three share.
- `samples/`: one passing and one failing file per check that reads a PDF or PNG with a tool;
  `samples/artists/`, the artist reports `figures/checks/artists.py` wrote for small generators,
  for the checks that read one (committed, so those checks are tested where matplotlib is not
  installed); and the captions, notes, generators, and declared statistics and inputs the
  caption and disclosure checks read.

Every PDF is saved without a creation date so a rebuild changes no byte that does not matter.
"""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent.parent
PROJECT = HERE / "project"
SAMPLES = HERE / "samples"
MM = 1 / 25.4
NO_DATE = {"CreationDate": None}

FIG1 = '''"""Figure 1: held-out AUROC per method (a) and AUROC against runtime (b)."""

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
'''

UNDECLARED = '''"""A figure whose generator reads a file its result never declared."""

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
'''

NOISY = '''"""A figure drawn from unseeded noise, so no two runs agree."""

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
'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path, payload):
    return write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def build_project():
    shutil.rmtree(PROJECT, ignore_errors=True)
    style = json.loads((HARNESS / "figures" / "style.default.json").read_text(encoding="utf-8"))
    style["ramp_per_quantity"] = {"density": "viridis"}
    write_json(PROJECT / "figures" / "style.json", style)
    scores = PROJECT / "results" / "t7-a1" / "scores.csv"
    timing = PROJECT / "results" / "t8-a1" / "timing.csv"
    scores.parent.mkdir(parents=True)
    timing.parent.mkdir(parents=True)
    with open(scores, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([["method", "auroc"], ["X", "0.91"], ["A", "0.84"], ["B", "0.79"]])
    with open(timing, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([["method", "seconds", "auroc"], ["X", "12", "0.91"], ["A", "4", "0.84"], ["B", "30", "0.79"]])
    write(PROJECT / "data" / "extra.txt", "1 3 2 5 4\n")
    manifest = {"entries": [
        {"path": path.relative_to(PROJECT).as_posix(), "size": path.stat().st_size, "sha256": sha256(path),
         "job": None, "run_id": run_id, "ticket": ticket, "ts": "2026-09-12T00:00:00Z"}
        for path, run_id, ticket in ((scores, "t7-a1", "7"), (timing, "t8-a1", "8"))
    ]}
    write_json(PROJECT / "research" / "manifest.json", manifest)
    inputs = [
        {"path": "results/t7-a1/scores.csv", "sha256": sha256(scores), "run_id": "t7-a1", "panels": ["a"]},
        {"path": "results/t8-a1/timing.csv", "sha256": sha256(timing), "run_id": "t8-a1", "panels": ["b"]},
    ]
    write_json(PROJECT / "request.json", {
        "schema": "figure_request/1", "ticket": "49", "figure_id": "fig1", "mode": "unguided", "kind": "result",
        "register": "quantitative",
        "claim": {"claim_id": "C1", "text": "Method X has the highest held-out AUROC at a moderate runtime.", "claim_type": "comparison"},
        "data": [{"path": item["path"], "sha256": item["sha256"], "run_id": item["run_id"]} for item in inputs],
        "style": "figures/style.json",
        "target": {"venue": None, "width_mm": 89, "max_height_mm": 120, "min_font_pt": 5, "min_dpi": 300,
                   "max_words": None, "formats": ["pdf", "png"], "library": "matplotlib"},
        "forbidden_text": {"gene_names": None, "dataset_names": [], "allow_regex": []},
        "budget": {"render_seconds": 120},
    })
    for figure_id, source, caption, figure_inputs in (
        ("fig1", FIG1, "**Figure 1.** (a) Held-out AUROC of methods X, A and B. (b) AUROC against runtime for the same three methods.\n", inputs),
        ("undeclared", UNDECLARED, "**Figure S1.** A trace drawn from a file the result does not declare.\n", inputs[:1]),
        ("noisy", NOISY, "**Figure S2.** Unseeded noise.\n", inputs[:1]),
    ):
        directory = PROJECT / "figures" / figure_id
        write(directory / (figure_id + ".py"), source)
        write(directory / "caption.md", caption)
        write(directory / "notes.md", "Generated by %s.py from the declared inputs.\n" % figure_id)
        subprocess.run([sys.executable, "figures/%s/%s.py" % (figure_id, figure_id)], cwd=PROJECT, check=True,
                       env=dict(os.environ, MPLBACKEND="Agg"))
        write_json(directory / "result.json", {
            "schema": "figure_result/1", "ticket": "49", "figure_id": figure_id, "status": "selected",
            "candidates": [{"rank": 1, "index_id": "ranking/bar/matplotlib", "rendered": True}],
            "selected": {"rank": 1, "by": "decider", "margin": 3, "margin_low": False},
            "final": {
                "generator": "figures/%s/%s.py" % (figure_id, figure_id),
                "pdf": "figures/%s/%s.pdf" % (figure_id, figure_id),
                "png": "figures/%s/%s.png" % (figure_id, figure_id),
                "caption": "figures/%s/caption.md" % figure_id,
                "notes": "figures/%s/notes.md" % figure_id,
                "crops": [],
                "inputs": figure_inputs,
            },
        })


def page(path, width_mm, height_mm, draw, fonttype=42, dpi=None):
    matplotlib.rcParams["pdf.fonttype"] = fonttype
    figure = plt.figure(figsize=(width_mm * MM, height_mm * MM))
    draw(figure)
    figure.savefig(SAMPLES / path, **({"dpi": dpi} if dpi else {"metadata": NO_DATE}))
    plt.close(figure)
    matplotlib.rcParams["pdf.fonttype"] = 42


def words(count):
    return " ".join("word%s" % chr(97 + index % 26) for index in range(count))


def build_samples():
    shutil.rmtree(SAMPLES, ignore_errors=True)
    SAMPLES.mkdir()

    def label(text, size=7, x=0.1, y=0.5):
        return lambda figure: figure.text(x, y, text, fontsize=size)

    page("type42.pdf", 89, 30, label("Held-out AUROC"))
    page("type3.pdf", 89, 30, label("Held-out AUROC"), fonttype=3)
    page("width-89mm.pdf", 89, 30, label("Held-out AUROC"))
    page("width-120mm.pdf", 120, 30, label("Held-out AUROC"))
    page("png-300dpi.png", 89, 30, label("Held-out AUROC"), dpi=300)
    page("png-100dpi.png", 89, 30, label("Held-out AUROC"), dpi=100)

    def raster(size):
        def draw(figure):
            axes = figure.add_axes([0, 0, 1, 1])
            # "none" embeds the array's own pixels in a PDF; any other interpolation resamples it.
            axes.imshow([[(row * size + column) % 7 for column in range(size)] for row in range(size)], interpolation="none")
            axes.set_axis_off()
        return draw

    page("raster-1200px.pdf", 89, 89, raster(1200))
    page("raster-10px.pdf", 89, 89, raster(10))
    page("font-6pt.pdf", 89, 30, label("Held-out AUROC", size=6))
    page("font-3pt.pdf", 89, 30, label("Held-out AUROC", size=3))
    # A 40 mm figure drawn at 20 mm: the target width halves every size.
    page("font-6pt-at-half-width.pdf", 40, 30, label("Held-out AUROC", size=6))
    page("abstract-8-words.pdf", 89, 60, label(words(8)))
    page("abstract-80-words.pdf", 89, 60, lambda figure: [figure.text(0.05, 0.9 - 0.1 * row, words(10), fontsize=6) for row in range(8)])

    def conceptual(texts):
        def draw(figure):
            for index, text in enumerate(texts):
                figure.text(0.05 + 0.3 * index, 0.5, text, fontsize=8)
        return draw

    page("conceptual-clean.pdf", 89, 30, conceptual(["a", "Encoder", "Decoder"]))
    page("conceptual-digits.pdf", 89, 30, conceptual(["a", "Stage 1", "PBMC3k"]))

    def lines(colors):
        def draw(figure):
            axes = figure.add_axes([0.1, 0.1, 0.8, 0.8])
            for index, color in enumerate(colors):
                axes.plot([0, 1], [index, index + 1], color=color)
            axes.set_axis_off()
        return draw

    page("palette-okabe-ito.pdf", 89, 30, lines(["#E69F00", "#56B4E9", "#009E73"]))
    page("palette-red-green.pdf", 89, 30, lines(["#CC3311", "#339933"]))
    page("palette-new-distinct.pdf", 89, 30, lines(["#0072B2", "#882255"]))
    write(SAMPLES / "unused_import.py", "import os\nimport sys\n\n\ndef main():\n    unused = 1\n    return sys.argv\n")
    write(SAMPLES / "clean_generator.py", "import sys\n\n\ndef main():\n    return sys.argv\n")
    build_artist_reports()
    build_text_samples()


# Each generator saves out.pdf; the artist report written for it is samples/artists/<name>.json.
ARTIST_GENERATORS = {
    "ramp-allowed": """
figure, axes = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
values = numpy.linspace(0, 1, 40)
axes.scatter(values, values ** 2, c=values, cmap="viridis", s=6, gid="quantity:density")
axes.plot(values, values, color="#E69F00")
""",
    "ramp-wrong": """
figure, axes = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
axes.imshow(numpy.arange(16).reshape(4, 4), cmap="magma").set_gid("quantity:density")
axes.add_patch(Rectangle((0, 0), 2, 2, fill=False, edgecolor="#E69F00", gid="container:stage"))
""",
    "lines-good": """
figure, axes = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
axes.add_collection(LineCollection([[(0, 0), (1, 1)], [(0, 1), (1, 0)]], colors="#000000", linestyle="solid", gid="required:edges"))
axes.plot([0, 1], [0.5, 0.5], "--", color="#808080", gid="optional:feedback")
axes.add_patch(Rectangle((0.1, 0.1), 0.2, 0.2, fill=False, edgecolor="#808080", gid="container:stage"))
""",
    "lines-bad": """
figure, axes = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
axes.plot([0, 1], [0, 1], "--", color="#000000", gid="required:edge")
axes.add_collection(LineCollection([[(0, 1), (1, 0)]], colors="#000000", linestyle="solid", gid="optional:feedback"))
""",
    "text-clear": """
figure = plt.figure(figsize=(89 / 25.4, 30 / 25.4))
figure.text(0.1, 0.5, "AUROC", fontsize=7)
figure.text(0.6, 0.5, "Runtime", fontsize=7)
""",
    "text-overlap": """
figure = plt.figure(figsize=(89 / 25.4, 30 / 25.4))
figure.text(0.1, 0.5, "AUROC", fontsize=7)
figure.text(0.13, 0.5, "Runtime", fontsize=7)
figure.text(0.93, 0.2, "Clipped label", fontsize=7)
""",
    "panels-ab": """
figure, (left, right) = plt.subplots(1, 2, figsize=(89 / 25.4, 45 / 25.4), layout="constrained")
left.plot([0, 1], [0, 1], label="y", color="#0072B2")
left.set_xlabel("x")
left.legend()
left.set_title("a", loc="left", fontweight="bold")
right.bar(["X", "A"], [0.9, 0.8], color="#E69F00")
right.set_title("b", loc="left", fontweight="bold")
""",
}

ARTIST_PRELUDE = """import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle
matplotlib.rcParams["pdf.fonttype"] = 42
"""


def build_artist_reports():
    directory = SAMPLES / "artists"
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in ARTIST_GENERATORS.items():
        with tempfile.TemporaryDirectory() as work:
            write(Path(work) / "gen.py", ARTIST_PRELUDE + body + 'figure.savefig("out.pdf", metadata={"CreationDate": None})\n')
            subprocess.run([sys.executable, "-I", str(HARNESS / "figures" / "checks" / "artists.py"), "--out", "report.json", "--width-mm", "89", "gen.py"],
                           cwd=work, check=True, env=dict(os.environ, MPLBACKEND="Agg"))
            report = json.loads((Path(work) / "report.json").read_text(encoding="utf-8"))
        write_json(directory / (name + ".json"), report)


def build_text_samples():
    write(SAMPLES / "caption-ab.md", "**Figure 1.** (a) Held-out AUROC of methods X and A and (b) their runtime (s).\n")
    write(SAMPLES / "caption-a-only.md", "**Figure 1.** (a) Held-out AUROC of methods X and A; runtime (s) is not shown.\n")
    write(SAMPLES / "caption-abc.md", "**Figure 1.** (a) Held-out AUROC. (b) Runtime. (c) Memory.\n")
    write(SAMPLES / "caption-clean.md", "**Figure 1.** (a) Held-out AUROC per method, normalized to the baseline color scale.\n")
    write(SAMPLES / "caption-british.md", "**Figure 1.** (a) Held-out AUROC — normalised, in colour.\n")
    write(SAMPLES / "caption-framework.md", "**Figure 2.** (a) The pipeline from reads to networks.\n")
    write(SAMPLES / "caption-framework-referenced.md", "**Figure 2.** (a) The pipeline from reads to networks (see also Figure 3).\n")
    for name, caption, notes, generator in (
        ("disclosed", "**Figure 2.** (b) The regulatory motif is schematic.\n", "Panel b draws the regulatory motif by hand.\n",
         "# schematic: regulatory motif, drawn by hand\nprint('motif')\n"),
        ("undisclosed", "**Figure 2.** (b) The regulatory motif.\n", "Panel b.\n", "print('motif')\n"),
    ):
        write(SAMPLES / "schematic" / name / "caption.md", caption)
        write(SAMPLES / "schematic" / name / "notes.md", notes)
        write(SAMPLES / "schematic" / name / "generator.py", generator)
    write_json(SAMPLES / "selection-within.json", [{"panel": "c", "criterion": "sign_balance", "displayed": 0.55, "global": 0.57, "tolerance": 0.10}])
    write_json(SAMPLES / "selection-outside.json", [{"panel": "c", "criterion": "sign_balance", "displayed": 0.55, "global": 0.75, "tolerance": 0.10}])

    def inputs(first, second, second_path="results/t8-a1/y.csv"):
        return [{"path": "results/t7-a1/x.csv", "sha256": "0" * 64, "run_id": "t7-a1", "panels": first},
                {"path": second_path, "sha256": "0" * 64, "run_id": second_path.split("/")[1], "panels": second}]

    write_json(SAMPLES / "inputs-one-per-panel.json", inputs(["a"], ["b"]))
    write_json(SAMPLES / "inputs-two-in-a-panel.json", inputs(["a"], ["a"]))
    write_json(SAMPLES / "inputs-two-artifacts-of-one-run.json", inputs(["a"], ["a"], second_path="results/t7-a1/y.csv"))
    write(SAMPLES / "caption-mixed.md", "**Figure 1.** (a) Both results [[mixed-data]].\n")
    write(SAMPLES / "caption-unmixed.md", "**Figure 1.** (a) Both results.\n")


if __name__ == "__main__":
    build_project()
    build_samples()
