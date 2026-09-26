"""`wayline tools install`: the optional converter venv under `~/.wayline/tools/` (Implementation Decisions 9).

The harness imports no third-party package. The PDF converters research-notes 06 recommends are
Python packages with models behind them (docling and pdfplumber by default, marker and MinerU on
request), so they live in a venv of their own that the owner installs once, and the harness only
ever runs them as subprocesses through the helper scripts in `converters/`. GROBID is a Docker
image and is pulled on request. What was installed, at which version, and whether torch can see
the GPU is recorded in `~/.wayline/tools/tools.json`, which `Tools` reads: a converter's
provenance names the version recorded here.

Torch is installed before the converters, from the PyTorch index that matches the machine. The
default PyPI wheel is built for the newest CUDA, and a driver older than that wheel leaves torch
unable to see the GPU at all (`torch 2.14.0+cu130` on a 535 driver, which speaks CUDA 12.2, is
the case this box hit): CUDA 12 drivers take the `cu126` wheels, which CUDA's minor-version
compatibility lets any 12.x driver run, and a machine with no GPU takes the CPU wheels, which
are a tenth of the size.

This module also holds the one subprocess seam the PDF chain and the install share, `run_tool`,
which tests replace with a runner that answers from recordings.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

from wayline import backends_off, real_backend
from wayline.cli import parse_args
from wayline.ledger import now_ts

__all__ = [
    "ToolsError", "ToolOutput", "run_tool", "failure_line", "read_json_file", "TOOLS", "TOOLS_JSON", "VENV",
    "tools_home", "Tools", "PACKAGES", "EXTRAS", "GROBID_IMAGE", "TORCH_INDEX", "driver_cuda", "torch_index",
    "install_steps", "install", "tools_command",
]

TOOLS = "tools"
TOOLS_JSON = "tools.json"
VENV = "venv"
TOOL_TIMEOUT_S = 120

# The distributions each converter name installs, and the distribution whose version is recorded.
PACKAGES = {
    "docling": (["docling"], "docling"),
    "pdfplumber": (["pdfplumber"], "pdfplumber"),
    "marker": (["marker-pdf"], "marker-pdf"),
    "mineru": (["mineru[pipeline]"], "mineru"),
}
DEFAULT = ("docling", "pdfplumber")
EXTRAS = ("marker", "mineru")
GROBID_IMAGE = "grobid/grobid:0.9.1-crf"
TORCH_INDEX = "https://download.pytorch.org/whl/%s"
INSTALL_TIMEOUT_S = 3600
_CUDA_VERSION = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")


class ToolsError(RuntimeError):
    """An install step that failed; the message names the step and what it printed last."""


# --- the subprocess seam ----------------------------------------------------------------------------

ToolOutput = namedtuple("ToolOutput", "returncode stdout stderr")
"""What one tool left: the exit code and its two streams as bytes. 127 is "not found"."""


def run_tool(argv, cwd=None, timeout=TOOL_TIMEOUT_S):
    """The one place the PDF chain and the install start a tool; tests replace it with a recorded runner."""
    try:
        done = subprocess.run([str(part) for part in argv], cwd=str(cwd) if cwd else None,
                              capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as failure:
        return ToolOutput(127, b"", str(failure).encode("utf-8"))
    except subprocess.TimeoutExpired:
        return ToolOutput(124, b"", ("%s did not finish in %d s" % (Path(str(argv[0])).name, timeout)).encode("utf-8"))
    except (OSError, subprocess.SubprocessError) as failure:
        return ToolOutput(126, b"", str(failure).encode("utf-8"))
    return ToolOutput(done.returncode, done.stdout, done.stderr)


def failure_line(output):
    """One line saying why a tool failed, for a note or an error: the exit code and the last line it printed."""
    streams = (output.stderr or b"") + (output.stdout or b"")
    lines = [line.strip() for line in streams.decode("utf-8", errors="replace").splitlines() if line.strip()]
    return "exit %d%s" % (output.returncode, (": " + lines[-1][:240]) if lines else "")


def read_json_file(path):
    """A JSON object from a file outside the ledger (a tool's output, `tools.json`); None when it is not one."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# --- the tools venv ---------------------------------------------------------------------------------


def tools_home():
    """`~/.wayline/tools/`, moved with `WAYLINE_HOME` like every per-machine pointer."""
    from wayline.project import home

    return home() / TOOLS


class Tools:
    """What `wayline tools install` put on this machine, read from `~/.wayline/tools/tools.json`.

    The record is the authority on versions: a converter's provenance names the version the
    install recorded, and the venv's Python is what runs the helper scripts in `converters/`.
    """

    def __init__(self, root=None, record=None):
        self.root = Path(root) if root is not None else tools_home()
        self.record = record if record is not None else (read_json_file(self.root / TOOLS_JSON) or {})

    @property
    def python(self):
        """The venv's interpreter, or None when there is no venv that still runs."""
        path = self.root / VENV / "bin" / "python"
        return path if self.record and path.exists() else None

    def version(self, package):
        return (self.record.get("packages") or {}).get(package)

    def has(self, package):
        return self.python is not None and bool(self.version(package))

    def docker_image(self, name):
        return (self.record.get("docker_images") or {}).get(name)


# --- the install ------------------------------------------------------------------------------------


def driver_cuda(run=run_tool):
    """`(major, minor)` of the CUDA version the NVIDIA driver speaks, or None without a GPU."""
    if run is run_tool and backends_off():  # `WAYLINE_BACKENDS=none`: a machine with no GPU
        return None
    done = run(["nvidia-smi"])
    if done.returncode != 0:
        return None
    match = _CUDA_VERSION.search(done.stdout.decode("utf-8", errors="replace"))
    return (int(match.group(1)), int(match.group(2))) if match else None


def torch_index(cuda):
    """The PyTorch wheel index for a driver: `cpu`, `cu118`, `cu126`, or None for PyPI's default build."""
    if cuda is None:
        return "cpu"
    if cuda[0] >= 13:
        return None
    if cuda[0] == 12:
        return "cu126"
    return "cu118"


def install_steps(root, extras=(), cuda=None, python=None, uv=None):
    """The commands an install runs, in order, as `(name, argv)`; `wayline tools install --dry-run` prints them.

    With `uv` on the path the venv and the packages go through it (minutes rather than tens of
    minutes for torch); without it, `python -m venv` and the venv's own pip do the same work.
    """
    root = Path(root)
    venv = root / VENV
    venv_python = venv / "bin" / "python"
    python = python or sys.executable
    index = torch_index(cuda)
    names = list(DEFAULT) + [name for name in EXTRAS if name in extras]
    distributions = [spec for name in names for spec in PACKAGES[name][0]]
    steps = []
    if uv:
        steps.append(("venv", [uv, "venv", "--python", python, str(venv)]))
        pip = [uv, "pip", "install", "--python", str(venv_python)]
    else:
        steps.append(("venv", [python, "-m", "venv", str(venv)]))
        steps.append(("pip", [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"]))
        pip = [str(venv_python), "-m", "pip", "install"]
    if index is not None:
        steps.append(("torch", pip + ["--index-url", TORCH_INDEX % index, "torch", "torchvision"]))
    steps.append(("converters", pip + distributions))
    return steps


# Run inside the venv: the versions of what was installed, and whether torch sees a GPU.
_PROBE = (
    "import json, importlib.metadata as m\n"
    "names = %r\n"
    "found = {}\n"
    "for short, dist in names.items():\n"
    "    try:\n"
    "        found[short] = m.version(dist)\n"
    "    except m.PackageNotFoundError:\n"
    "        pass\n"
    "device = None\n"
    "try:\n"
    "    import torch\n"
    "    device = 'cuda' if torch.cuda.is_available() else 'cpu'\n"
    "except Exception:\n"
    "    pass\n"
    "print(json.dumps({'packages': found, 'device': device}))\n"
)


def install(extras=(), grobid=False, root=None, run=run_tool, python=None, uv=None, echo=None):
    """Create the tools venv, install the converters, pull GROBID on request, and record the versions.

    Returns the record written to `tools.json`. An existing venv is installed into again, which
    is how `--marker` is added to a machine that already has docling; the record is rewritten
    from what the venv actually holds afterwards, never merged with what it said before.
    """
    if run is run_tool:
        real_backend("the network (the tools install)")
    root = Path(root) if root is not None else tools_home()
    root.mkdir(parents=True, exist_ok=True)
    echo = echo or (lambda line: None)
    cuda = driver_cuda(run)
    uv = uv if uv is not None else shutil.which("uv")
    venv_python = root / VENV / "bin" / "python"
    steps = install_steps(root, extras, cuda, python, uv)
    if venv_python.exists():
        steps = [step for step in steps if step[0] != "venv"]
    for name, argv in steps:
        echo("%s: %s" % (name, " ".join(str(part) for part in argv)))
        done = run(argv, timeout=INSTALL_TIMEOUT_S)
        if done.returncode != 0:
            raise ToolsError("the %s step failed (%s)" % (name, failure_line(done)))

    wanted = {short: dist for short, (_, dist) in PACKAGES.items()}
    wanted["torch"] = "torch"
    probe = run([venv_python, "-c", _PROBE % wanted], timeout=INSTALL_TIMEOUT_S)
    try:
        found = json.loads(probe.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ToolsError("the venv was built but reading its versions failed (%s)" % failure_line(probe)) from None

    record = {
        "schema_version": 1,
        "created": now_ts(),
        "python": str(venv_python),
        "packages": found.get("packages") or {},
        "device": found.get("device"),
        "driver_cuda": "%d.%d" % cuda if cuda else None,
        "torch_index": torch_index(cuda),
        "installer": "uv" if uv else "pip",
        "docker_images": {},
        "notes": [],
    }
    if cuda and record["device"] != "cuda":
        record["notes"].append(
            "the driver speaks CUDA %d.%d but torch in the venv cannot see the GPU; docling will run on the CPU, "
            "about ten times slower with formula enrichment" % cuda
        )
    if grobid:
        echo("grobid: docker pull %s" % GROBID_IMAGE)
        pulled = run(["docker", "pull", GROBID_IMAGE], timeout=INSTALL_TIMEOUT_S)
        if pulled.returncode == 0:
            record["docker_images"]["grobid"] = GROBID_IMAGE
        else:
            record["notes"].append("docker pull %s failed (%s); references and metadata stay converter: none" % (GROBID_IMAGE, failure_line(pulled)))
    _write_record(root / TOOLS_JSON, record)
    return record


def _write_record(path, record):
    """`tools.json` by write-to-temp-then-rename; it lives outside any project, so not through a ledger."""
    path = Path(path)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".tools-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(record, out, indent=2)
        out.write("\n")
    os.replace(temporary, path)
    return path


def tools_command(args):
    parser = argparse.ArgumentParser(prog="wayline tools", description="the optional converter venv under ~/.wayline/tools/")
    parser.add_argument("action", choices=["install", "show"], help="install the converters, or show what tools.json records")
    parser.add_argument("--marker", action="store_true", help="also install marker (fallback A; its OCR needs a GPU and a vLLM server)")
    parser.add_argument("--mineru", action="store_true", help="also install MinerU's pipeline backend (fallback B; 20 GB of models)")
    parser.add_argument("--grobid", action="store_true", help="also pull the GROBID CRF Docker image for references and metadata")
    parser.add_argument("--dry-run", action="store_true", help="print the commands and change nothing")
    parser.add_argument("--json", action="store_true", help="print the record as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    root = tools_home()
    extras = [name for name in EXTRAS if getattr(options, name)]
    if options.action == "show":
        try:
            print((root / TOOLS_JSON).read_text(encoding="utf-8").rstrip())
        except OSError:
            print("wayline tools: nothing installed; %s does not exist (wayline tools install)" % (root / TOOLS_JSON), file=sys.stderr)
            return 1
        return 0
    if options.dry_run:
        cuda = driver_cuda()
        print("driver CUDA %s, torch index %s" % ("%d.%d" % cuda if cuda else "none", torch_index(cuda) or "PyPI default"))
        for name, argv in install_steps(root, extras, cuda, uv=shutil.which("uv")):
            print("%-10s %s" % (name, " ".join(str(part) for part in argv)))
        if options.grobid:
            print("%-10s docker pull %s" % ("grobid", GROBID_IMAGE))
        return 0
    try:
        record = install(extras, grobid=options.grobid, root=root, echo=lambda line: print(line, file=sys.stderr))
    except ToolsError as failure:
        print("wayline tools install: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(record, indent=2))
    else:
        print("installed under %s" % root)
        for name, version in sorted(record["packages"].items()):
            print("  %-12s %s" % (name, version))
        print("  %-12s %s" % ("device", record["device"]))
        for name, image in sorted(record["docker_images"].items()):
            print("  %-12s %s" % (name, image))
        for note in record["notes"]:
            print("  note         %s" % note)
    return 0
