"""`wayline tools`: the harness's tools under `~/.wayline/tools/` and their record (Implementation Decisions 9, 17).

`wayline tools install` installs the harness's own tools without root, each by its route and each
download checked against its published digest: micromamba, uv, pandoc with pandoc-crossref, the
packages of the tools venv (matplotlib, seaborn, tree-sitter-matlab, and the converters below),
and the embedding model. It records LaTeX, poppler, LibreOffice, and git as `system` and never
changes them. Each tool is one entry under `tools` in `tools.json`, merged one entry at a time
under a lock, and is called only through it: `wayline tools run <name> -- <args>` runs one by its
absolute executable and environment, so no lookup on a `PATH` ever finds the wrong program.

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
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
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
    "SCHEMA_VERSION", "HARNESS", "OWNER", "SYSTEM", "MICROMAMBA_VERSION", "UV_VERSION", "PANDOC_VERSION", "MODEL",
    "MODEL_REVISION", "MODEL_FILES", "SYSTEM_TOOLS", "PYTHON_PACKAGES", "CONDA_TOOLS", "HARNESS_INSTALLERS",
    "micromamba_url", "uv_url", "model_url", "model_tree_url", "parse_version", "sha256_file", "blob_sha1",
    "update_record", "record_entry", "tool_entry", "mamba_env", "uv_env", "venv_python", "install_micromamba",
    "install_uv", "install_model", "ensure_venv", "record_venv_packages", "record_system_tool", "install_tool",
    "install_all", "run_recorded",
]

TOOLS = "tools"
TOOLS_JSON = "tools.json"
SCHEMA_VERSION = 2
VENV = "venv"
TOOL_TIMEOUT_S = 120
TOOL_RUN_TIMEOUT_S = 600

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


def run_tool(argv, cwd=None, timeout=TOOL_TIMEOUT_S, env=None):
    """The one place the harness starts a tool; tests replace it with a recorded runner.

    `env` holds the variables a tool's record requires, laid over this process's environment.
    """
    try:
        done = subprocess.run([str(part) for part in argv], cwd=str(cwd) if cwd else None,
                              capture_output=True, timeout=timeout, check=False,
                              env=dict(os.environ, **env) if env else None)
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

    def entry(self, name):
        """One tool's entry (absolute executable, version, environment, route, installer), or None."""
        return (self.record.get("tools") or {}).get(name)

    def names(self):
        return sorted(self.record.get("tools") or {})


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

    The venv and every package go through uv, the harness's own at `<tools>/bin/uv` unless another
    is named: `python -m venv` is no route, since it fails on a machine without `ensurepip`.
    """
    root = Path(root)
    venv = root / VENV
    venv_python = venv / "bin" / "python"
    python = python or sys.executable
    uv = str(uv or root / BIN / "uv")
    index = torch_index(cuda)
    names = list(DEFAULT) + [name for name in EXTRAS if name in extras]
    distributions = [spec for name in names for spec in PACKAGES[name][0]]
    steps = [("venv", [uv, "venv", "--python", python, str(venv)])]
    pip = [uv, "pip", "install", "--python", str(venv_python)]
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

    Returns `tools.json` as written. An existing venv is installed into again, which is how
    `--marker` is added to a machine that already has docling; the venv's fields are rewritten
    from what the venv actually holds afterwards, and every tool's entry is kept as it was, but for
    the lock of the harness's packages in the same venv, which is refreshed.
    """
    if run is run_tool:
        real_backend("the network (the tools install)")
    root = Path(root) if root is not None else tools_home()
    root.mkdir(parents=True, exist_ok=True)
    echo = echo or (lambda line: None)
    cuda = driver_cuda(run)
    uv_record = {"executable": str(uv), "env": {}} if uv is not None else install_uv(root, run, echo)
    venv_python = root / VENV / "bin" / "python"
    steps = install_steps(root, extras, cuda, python, uv_record["executable"])
    if venv_python.exists():
        steps = [step for step in steps if step[0] != "venv"]
    for name, argv in steps:
        echo("%s: %s" % (name, " ".join(str(part) for part in argv)))
        done = run(argv, timeout=INSTALL_TIMEOUT_S, env=uv_record["env"])
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
        "created": now_ts(),
        "python": str(venv_python),
        "packages": found.get("packages") or {},
        "device": found.get("device"),
        "driver_cuda": "%d.%d" % cuda if cuda else None,
        "torch_index": torch_index(cuda),
        "installer": "uv",
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
    record_venv_packages(root, uv_record, run)
    return update_record(root, lambda current: current.update(record))


def _write_record(path, record):
    """`tools.json` by write-to-temp-then-rename; it lives outside any project, so not through a ledger."""
    path = Path(path)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".tools-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(record, out, indent=2)
        out.write("\n")
    os.replace(temporary, path)
    return path


# --- the harness's tools ---------------------------------------------------------------------------
#
# What the harness installs for itself, beside the converter venv, with no ask at any autonomy
# (Implementation Decisions 17, "Tools, packages, and environments"): micromamba's static binary,
# uv, pandoc with pandoc-crossref from conda-forge, matplotlib, seaborn, and tree-sitter-matlab in
# the tools venv, and the embedding model at a pinned revision. Never root, and every download is
# checked against the digest its publisher publishes beside it. Each tool gets one entry under
# `tools` in `tools.json`, merged one entry at a time under a lock, and is called only through it.

TOOLS_LOCK = ".tools.lock"
BIN = "bin"
MAMBA = "mamba"
ENVS = "envs"
MODELS = "models"
LOCKS = "locks"
HARNESS, OWNER, SYSTEM = "harness", "owner", "system"

MICROMAMBA_VERSION = "2.9.0-0"
MICROMAMBA_RELEASE = "https://github.com/mamba-org/micromamba-releases/releases/download/%s/micromamba-%s"
UV_VERSION = "0.12.24"
UV_RELEASE = "https://github.com/astral-sh/uv/releases/download/%s/uv-%s.tar.gz"
CONDA_FORGE = "conda-forge"
MODEL = "BAAI/bge-base-en-v1.5"
MODEL_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
MODEL_HUB = "https://huggingface.co"
# What loading the model for sentence embeddings reads; the ONNX export and the PyTorch pickle are left out.
MODEL_FILES = (
    "config.json", "config_sentence_transformers.json", "modules.json", "sentence_bert_config.json",
    "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt", "model.safetensors",
    "1_Pooling/config.json",
)
# The programs the machine already has that the harness calls, recorded by absolute path and never changed,
# each with the flag that makes it print its version: LaTeX, poppler, LibreOffice, git, and gh (which creates the code repository).
SYSTEM_TOOLS = {
    "latexmk": "--version", "pdflatex": "--version", "xelatex": "--version",
    "pdfinfo": "-v", "pdftotext": "-v", "pdfimages": "-v", "pdftoppm": "-v",
    "soffice": "--version", "git": "--version", "gh": "--version",
}
_PLATFORMS = {"x86_64": ("linux-64", "x86_64-unknown-linux-gnu"), "aarch64": ("linux-aarch64", "aarch64-unknown-linux-gnu")}
_VERSION = re.compile(r"\d+(?:\.\d+)+(?:-[\d.]+)*")


def _platform(index):
    machine = platform.machine()
    if sys.platform != "linux" or machine not in _PLATFORMS:
        raise ToolsError("the harness's tools install on Linux x86_64 or aarch64, not %s %s" % (sys.platform, machine))
    return _PLATFORMS[machine][index]


def micromamba_url(version=MICROMAMBA_VERSION):
    """micromamba's static binary on its GitHub release; its digest is the same URL with `.sha256`."""
    return MICROMAMBA_RELEASE % (version, _platform(0))


def uv_url(version=UV_VERSION):
    """uv's release tarball; its digest is the same URL with `.sha256`."""
    return UV_RELEASE % (version, _platform(1))


def model_url(path, revision=MODEL_REVISION):
    """One of the model's files at the pinned revision."""
    return "%s/%s/resolve/%s/%s" % (MODEL_HUB, MODEL, revision, path)


def model_tree_url(revision=MODEL_REVISION):
    """The Hub's listing of the model's files at the revision, which publishes each one's digest."""
    return "%s/api/models/%s/tree/%s?recursive=true" % (MODEL_HUB, MODEL, revision)


def parse_version(text):
    """The first version number in what a program printed about itself, or its first line when there is none."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    match = _VERSION.search(lines[0])
    return match.group(0) if match else lines[0][:80]


def _digest_file(path, digest):
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path):
    return _digest_file(path, hashlib.sha256())


def blob_sha1(path):
    """The git object id of a file: the digest Hugging Face publishes for a file kept outside LFS."""
    return _digest_file(path, hashlib.sha1(b"blob %d\0" % Path(path).stat().st_size))


@contextlib.contextmanager
def _record_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / TOOLS_LOCK, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def update_record(root, change):
    """Change `tools.json` under its lock: read what is there now, apply `change`, write it back.

    Two installs never lose each other's entries, because each reads the record afresh while it
    holds the lock instead of rewriting what it read when it started.
    """
    root = Path(root)
    with _record_lock(root):
        record = read_json_file(root / TOOLS_JSON) or {}
        change(record)
        record["schema_version"] = SCHEMA_VERSION
        record.setdefault("tools", {})
        _write_record(root / TOOLS_JSON, record)
    return record


def record_entry(root, name, entry):
    """Merge one tool's entry into `tools.json`, leaving every other entry as it was.

    An entry recorded again with the same executable and version keeps the time it was first
    installed, so re-recording what is already there does not move "installed when".
    """
    def merge(record):
        entries = record.setdefault("tools", {})
        before = entries.get(name) or {}
        if before.get("installed") and (before.get("executable"), before.get("version")) == (entry.get("executable"), entry.get("version")):
            entry["installed"] = before["installed"]
        entries[name] = entry

    update_record(root, merge)
    return entry


def _write_lock(root, name, data):
    """Keep a lock under `<tools>/locks/<name>.txt` and return its record: where it is and its SHA-256."""
    lock = Path(root) / LOCKS / ("%s.txt" % name)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(data)
    return {"path": str(lock), "sha256": hashlib.sha256(data).hexdigest()}


def _quiet(line):
    """The `echo` of an install nobody watches."""


def tool_entry(executable, version, route, installer=HARNESS, env=None, source=None, lock=None, digest=None, revision=None, **more):
    """One tool's record: the absolute executable, its version, the environment it needs, and how it came."""
    entry = {
        "executable": str(executable) if executable else None, "version": version, "env": dict(env or {}),
        "route": route, "source": source, "lock": lock, "digest": digest, "revision": revision,
        "installed": now_ts(), "installer": installer,
    }
    entry.update(more)
    return entry


def _ok(done, what):
    if done.returncode != 0:
        raise ToolsError("%s failed (%s)" % (what, failure_line(done)))
    return done


def _fetch_text(url, run):
    done = _ok(run(["curl", "-fsSL", "--retry", "2", url], timeout=TOOL_TIMEOUT_S), "fetching %s" % url)
    return done.stdout.decode("utf-8", errors="replace")


def _published_sha256(url, run):
    """The hex digest a publisher keeps beside a download (`<url>.sha256`, the digest first)."""
    words = _fetch_text(url + ".sha256", run).split()
    if not words or not re.fullmatch(r"[0-9a-f]{64}", words[0]):
        raise ToolsError("%s.sha256 holds no SHA-256 digest" % url)
    return words[0]


def _download(url, dest, run, check):
    """Download `url` to `dest` through a temporary file, kept only when `check(temporary)` passes."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=str(dest.parent), prefix="." + dest.name + ".", suffix=".part")
    os.close(handle)
    temporary = Path(name)
    try:
        _ok(run(["curl", "-fsSL", "--retry", "2", "-o", temporary, url], timeout=INSTALL_TIMEOUT_S), "downloading %s" % url)
        check(temporary)
        os.replace(temporary, dest)
    finally:
        if temporary.exists():
            temporary.unlink()
    return dest


def _sha256_check(url, expected):
    def check(path):
        found = sha256_file(path)
        if found != expected:
            raise ToolsError("digest mismatch for %s: published sha256 %s, downloaded %s" % (url, expected, found))
    return check


def _version_of(executable, run, flag="--version", env=None):
    done = _ok(run([executable, flag], timeout=TOOL_TIMEOUT_S, env=env), "%s %s" % (Path(str(executable)).name, flag))
    return parse_version(((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", errors="replace"))


def _current(root, name, source):
    """The entry already recorded for this tool from this very source, when its executable is still there."""
    entry = Tools(root).entry(name)
    if entry and entry.get("source") == source and entry.get("executable") and Path(entry["executable"]).exists():
        return entry
    return None


def mamba_env(root):
    """What micromamba needs to keep its environments and its package cache under the tools home."""
    root = Path(root)
    return {"MAMBA_ROOT_PREFIX": str(root / MAMBA), "CONDA_PKGS_DIRS": str(root / MAMBA / "pkgs")}


def install_micromamba(root, run=run_tool, echo=None):
    """micromamba's static binary at `<tools>/bin/micromamba`, checked against the release's `.sha256`."""
    root = Path(root)
    url = micromamba_url()
    current = _current(root, "micromamba", url)
    if current:
        return current
    expected = _published_sha256(url, run)
    binary = _download(url, root / BIN / "micromamba", run, _sha256_check(url, expected))
    binary.chmod(0o755)
    env = mamba_env(root)
    return record_entry(root, "micromamba", tool_entry(
        binary, _version_of(binary, run, env=env), "release", env=env, source=url, digest="sha256:" + expected))


def uv_env(root):
    """What uv needs to keep its cache and any Python it fetches under the tools home."""
    root = Path(root)
    return {"UV_CACHE_DIR": str(root / "uv" / "cache"), "UV_PYTHON_INSTALL_DIR": str(root / "uv" / "python")}


def install_uv(root, run=run_tool, echo=None):
    """uv and uvx from uv's release tarball into `<tools>/bin/`, checked against the release's `.sha256`."""
    root = Path(root)
    url = uv_url()
    current = _current(root, "uv", url)
    if current:
        return current
    expected = _published_sha256(url, run)
    staging = Path(tempfile.mkdtemp(dir=str(root), prefix=".uv-"))
    try:
        tarball = _download(url, staging / "uv.tar.gz", run, _sha256_check(url, expected))
        with tarfile.open(tarball) as archive:
            members = {Path(member.name).name: member for member in archive.getmembers() if member.isfile()}
            if "uv" not in members:
                raise ToolsError("%s holds no uv binary" % url)
            (root / BIN).mkdir(parents=True, exist_ok=True)
            for name in ("uv", "uvx"):
                if name in members:
                    with archive.extractfile(members[name]) as source, open(staging / name, "wb") as out:
                        shutil.copyfileobj(source, out)
                    (staging / name).chmod(0o755)
                    os.replace(staging / name, root / BIN / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    binary = root / BIN / "uv"
    env = uv_env(root)
    return record_entry(root, "uv", tool_entry(
        binary, _version_of(binary, run, env=env), "release", env=env, source=url, digest="sha256:" + expected))


# The harness's packages in the tools venv: the distributions each installs, in order (the last is the
# one whose version its entry names), and the environment a call needs. matplotlib and seaborn make the
# venv's Python the one interpreter for drawings, figure scripts, and the checks' clean room.
PYTHON_PACKAGES = {
    "matplotlib": (("matplotlib",), {"MPLBACKEND": "Agg"}),
    "seaborn": (("seaborn",), {"MPLBACKEND": "Agg"}),
    "tree-sitter-matlab": (("tree-sitter", "tree-sitter-matlab"), {}),
}
PYPI = "https://pypi.org/simple"

# Run inside the tools venv: the installed version of each distribution named.
_VERSIONS_PROBE = (
    "import json, importlib.metadata as m\n"
    "found = {}\n"
    "for name in %r:\n"
    "    try:\n"
    "        found[name] = m.version(name)\n"
    "    except m.PackageNotFoundError:\n"
    "        pass\n"
    "print(json.dumps({'packages': found}))\n"
)


def venv_python(root):
    return Path(root) / VENV / "bin" / "python"


def ensure_venv(root, uv, run=run_tool, echo=None):
    """The tools venv, created by the harness's uv when it is not there yet; never `python -m venv`."""
    python = venv_python(root)
    if not python.exists():
        argv = [uv["executable"], "venv", "--python", sys.executable, str(Path(root) / VENV)]
        (echo or _quiet)("venv: " + " ".join(argv))
        _ok(run(argv, timeout=INSTALL_TIMEOUT_S, env=uv["env"]), "creating the tools venv")
    return python


def _venv_versions(python, names, run):
    done = _ok(run([python, "-c", _VERSIONS_PROBE % (sorted(names),)], timeout=INSTALL_TIMEOUT_S), "reading the tools venv's versions")
    try:
        return json.loads(done.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])["packages"]
    except (ValueError, IndexError, KeyError, TypeError):
        raise ToolsError("reading the tools venv's versions printed no versions (%s)" % failure_line(done)) from None


def record_venv_packages(root, uv, run=run_tool):
    """Freeze the tools venv into `locks/venv.txt` and record every package of the harness's it now holds.

    The harness's packages and the converters (docling, pdfplumber, and marker or MinerU when
    installed) each get an entry. Every entry in the venv carries the same lock, so it is
    refreshed for all of them whenever any install changes the venv.
    """
    root = Path(root)
    python = venv_python(root)
    frozen = _ok(run([uv["executable"], "pip", "freeze", "--python", str(python)], timeout=INSTALL_TIMEOUT_S, env=uv["env"]),
                 "freezing the tools venv").stdout
    lock = _write_lock(root, "venv", frozen)
    wanted = {name: (dists, env) for name, (dists, env) in PYTHON_PACKAGES.items()}
    wanted.update((name, ((dist,), {})) for name, (_, dist) in PACKAGES.items())
    found = _venv_versions(python, {dist for dists, _ in wanted.values() for dist in dists}, run)
    recorded = {}
    for name, (dists, env) in wanted.items():
        if all(dist in found for dist in dists):
            recorded[name] = record_entry(root, name, tool_entry(
                python, found[dists[-1]], "uv", env=env, source=PYPI, lock=lock,
                packages={dist: found[dist] for dist in sorted(dists)}))
    return recorded


def _python_package_installer(name):
    def install_package(root, run=run_tool, echo=None):
        uv = install_uv(root, run, echo)
        python = ensure_venv(root, uv, run, echo)
        argv = [uv["executable"], "pip", "install", "--python", str(python)] + list(PYTHON_PACKAGES[name][0])
        (echo or _quiet)("%s: %s" % (name, " ".join(argv)))
        _ok(run(argv, timeout=INSTALL_TIMEOUT_S, env=uv["env"]), "installing %s" % name)
        recorded = record_venv_packages(root, uv, run)
        if name not in recorded:
            raise ToolsError("%s was installed but the tools venv does not hold it" % name)
        return recorded[name]

    install_package.__doc__ = "%s into the tools venv through the harness's uv." % name
    return install_package


# conda-forge packages the harness keeps in prefixes of their own: the prefix, the package specs of
# each micromamba call in order, and the programs in it that get an entry. pandoc's route is
# conda-forge (research note 03: the release tarball's very binary). pandoc-crossref must be built
# with the pandoc it filters for, and conda-forge's 0.3.25 is built with pandoc 3.11 while its
# metadata asks for pandoc below 3.10, so the solver would pick pandoc 3.9 and the filter warns of
# "strange things" on every run (measured 2026-10-18): pandoc is pinned and pandoc-crossref is
# added without its declared dependency. Its entry records the pandoc it was built with.
PANDOC_VERSION = "3.11"
CONDA_TOOLS = {
    "pandoc": ((("pandoc=%s" % PANDOC_VERSION,), ("--no-deps", "pandoc-crossref")), ("pandoc", "pandoc-crossref")),
}
_BUILT_WITH = re.compile(r"built with Pandoc v([\d.]+)")


def _conda_installer(prefix_name):
    calls, programs = CONDA_TOOLS[prefix_name]

    def install_prefix(root, run=run_tool, echo=None):
        root = Path(root)
        micromamba = install_micromamba(root, run, echo)
        prefix = root / ENVS / prefix_name
        env = micromamba["env"]
        for specs in calls:
            verb = "install" if (prefix / "conda-meta").is_dir() or (prefix / "bin").is_dir() else "create"
            argv = [micromamba["executable"], verb, "-y", "-p", str(prefix), "-c", CONDA_FORGE, "--override-channels"] + list(specs)
            (echo or _quiet)("%s: %s" % (prefix_name, " ".join(argv)))
            _ok(run(argv, timeout=INSTALL_TIMEOUT_S, env=env), "micromamba %s %s" % (verb, " ".join(specs)))
        exported = _ok(run([micromamba["executable"], "env", "export", "-p", str(prefix), "--explicit"], timeout=TOOL_TIMEOUT_S, env=env),
                       "exporting the %s prefix's lock" % prefix_name).stdout
        lock_record = _write_lock(root, prefix_name, exported)
        entries = {}
        for program in programs:
            executable = prefix / "bin" / program
            done = _ok(run([executable, "--version"], timeout=TOOL_TIMEOUT_S), "%s --version" % program)
            printed = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", errors="replace")
            more = {"prefix": str(prefix)}
            built_with = _BUILT_WITH.search(printed)
            if built_with:
                more["built_with"] = built_with.group(1)
                pandoc = entries.get("pandoc")
                if pandoc and pandoc["version"] != built_with.group(1):
                    more["note"] = "built with pandoc %s, run through pandoc %s" % (built_with.group(1), pandoc["version"])
            entries[program] = record_entry(root, program, tool_entry(
                executable, parse_version(printed), "micromamba", source=CONDA_FORGE, lock=lock_record, **more))
        return entries

    return install_prefix


def _published_model_digests(run):
    """Each model file's digest as the Hub publishes it: `("sha256", hex)` for LFS files, `("sha1", git blob id)` otherwise."""
    try:
        listing = json.loads(_fetch_text(model_tree_url(), run))
    except ValueError:
        raise ToolsError("the Hub's listing of %s at %s is not JSON" % (MODEL, MODEL_REVISION)) from None
    digests = {}
    for item in listing if isinstance(listing, list) else []:
        if isinstance(item, dict) and item.get("type") == "file":
            lfs = item.get("lfs") or {}
            digests[item.get("path")] = ("sha256", lfs["oid"]) if lfs.get("oid") else ("sha1", item.get("oid"))
    return digests


def _model_check(path, digest):
    kind, expected = digest

    def check(local):
        found = sha256_file(local) if kind == "sha256" else blob_sha1(local)
        if found != expected:
            raise ToolsError("digest mismatch for %s at %s: published %s %s, downloaded %s" % (path, MODEL_REVISION, kind, expected, found))
    return check


def install_model(root, run=run_tool, echo=None):
    """The embedding model's files at the pinned revision into `<tools>/models/`, each checked against the Hub's digest."""
    root = Path(root)
    folder = root / MODELS / MODEL.replace("/", "--")
    digests = _published_model_digests(run)
    for path in MODEL_FILES:
        if path not in digests:
            raise ToolsError("the Hub lists no %s for %s at %s" % (path, MODEL, MODEL_REVISION))
        check = _model_check(path, digests[path])
        local = folder / path
        if local.exists():
            try:
                check(local)
                continue
            except ToolsError:
                local.unlink()
        (echo or _quiet)("embedding-model: %s" % path)
        _download(model_url(path), local, run, check)
    python = ensure_venv(root, install_uv(root, run, echo), run, echo)  # the interpreter its entry names
    return record_entry(root, "embedding-model", tool_entry(
        python, MODEL_REVISION[:12], "huggingface", env={"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        source="%s/%s" % (MODEL_HUB, MODEL), revision=MODEL_REVISION, model=MODEL, path=str(folder)))


def _one_program(installer, program):
    def install_program(root, run=run_tool, echo=None):
        return installer(root, run, echo)[program]

    return install_program


HARNESS_INSTALLERS = {
    "micromamba": install_micromamba,
    "uv": install_uv,
    "embedding-model": install_model,
}
for _prefix, (_calls, _programs) in CONDA_TOOLS.items():
    HARNESS_INSTALLERS.update((_program, _one_program(_conda_installer(_prefix), _program)) for _program in _programs)
HARNESS_INSTALLERS.update((name, _python_package_installer(name)) for name in PYTHON_PACKAGES)


def run_recorded(name, args, tools=None, run=run_tool, timeout=TOOL_RUN_TIMEOUT_S, exists=os.path.exists):
    """Run a recorded tool by its absolute executable and the environment its entry requires.

    A tool `tools.json` does not record is refused, and so is one whose executable is gone: no
    lookup on the `PATH` ever stands in for the record.
    """
    tools = tools if tools is not None else Tools()
    entry = tools.entry(name)
    if not entry or not entry.get("executable"):
        from wayline import software

        if name in HARNESS_INSTALLERS or name in SYSTEM_TOOLS or name == "docling":
            hint = "wayline tools install %s" % name
        elif name in software.PROJECT_TOOLS:
            hint = "a project's tool, installed after a yes on its software decision"
        elif name in software.LICENSED:
            hint = "licensed software, which the owner installs and says where it is"
        else:
            hint = "the harness's tools are %s" % ", ".join(HARNESS_INSTALLERS)
        raise ToolsError("%s is not recorded in %s (%s)" % (name, tools.root / TOOLS_JSON, hint))
    if not exists(entry["executable"]):
        raise ToolsError("%s is recorded at %s, which is no longer there (wayline tools install %s)" % (name, entry["executable"], name))
    return run([entry["executable"]] + list(args), timeout=timeout, env=entry.get("env") or None)


def install_all(root=None, run=run_tool, which=shutil.which, extras=(), grobid=False, echo=None):
    """`wayline tools install`: every harness tool by its route, the converter venv, and the system tools recorded.

    Returns `{name: (outcome, detail)}` with the outcome `installed`, `recorded` (a system tool),
    `absent` (a system tool this machine lacks), or `failed` with the error. A tool that fails
    fails alone: the next one is installed regardless, and only what is installed through it
    (pandoc through micromamba, the venv's packages through uv) fails with it.
    """
    if run is run_tool:
        real_backend("the network (the tools install)")
    root = Path(root) if root is not None else tools_home()
    root.mkdir(parents=True, exist_ok=True)
    echo = echo or _quiet
    results = {}

    def attempt(names, action):
        try:
            action()
        except ToolsError as failure:
            for name in names:
                results[name] = ("failed", str(failure))
            echo("%s: failed: %s" % (", ".join(names), failure))
            return
        for name in names:
            entry = Tools(root).entry(name)
            results[name] = ("installed", entry.get("version") if entry else None)

    attempt(["micromamba"], lambda: install_micromamba(root, run, echo))
    attempt(["uv"], lambda: install_uv(root, run, echo))
    for name in PYTHON_PACKAGES:
        attempt([name], lambda name=name: HARNESS_INSTALLERS[name](root, run, echo))
    try:
        record = install(extras, grobid=grobid, root=root, run=run, echo=echo)
        results["docling"] = ("installed", (record.get("packages") or {}).get("docling"))
    except ToolsError as failure:
        results["docling"] = ("failed", str(failure))
    for prefix, (_, programs) in CONDA_TOOLS.items():
        attempt(list(programs), lambda prefix=prefix: _conda_installer(prefix)(root, run, echo))
    attempt(["embedding-model"], lambda: install_model(root, run, echo))
    for name in SYSTEM_TOOLS:
        try:
            entry = record_system_tool(name, root, run, which)
            results[name] = ("recorded", entry.get("version"))
        except ToolsError as failure:
            results[name] = ("absent" if not which(name) else "failed", str(failure))
    return results


def record_system_tool(name, root, run=run_tool, which=shutil.which):
    """Record a program the machine already has as `system`, by the absolute path `which` finds; never change it.

    Only its version flag is run. An entry the owner made for the same name stays as it is.
    """
    root = Path(root)
    current = Tools(root).entry(name)
    if current and current.get("installer") == OWNER:
        return current
    found = which(name)
    if not found:
        raise ToolsError("%s is not on this machine; the harness records it but never installs it" % name)
    executable = Path(found).absolute()
    return record_entry(root, name, tool_entry(
        executable, _version_of(executable, run, SYSTEM_TOOLS[name]), SYSTEM, installer=SYSTEM))


def install_tool(name, root=None, run=run_tool, echo=None, which=shutil.which):
    """Install one tool by its route, or record a system one, and merge its entry into `tools.json`; returns the entry."""
    if name not in HARNESS_INSTALLERS and name not in SYSTEM_TOOLS:
        raise ToolsError("no tool is called %s; the harness installs %s and records %s" % (
            name, ", ".join(sorted(HARNESS_INSTALLERS)), ", ".join(SYSTEM_TOOLS)))
    root = Path(root) if root is not None else tools_home()
    if name in SYSTEM_TOOLS:
        return record_system_tool(name, root, run, which)
    if run is run_tool:
        real_backend("the network (the tools install)")
    root.mkdir(parents=True, exist_ok=True)
    return HARNESS_INSTALLERS[name](root, run=run, echo=echo or _quiet)


# --- the verb ---------------------------------------------------------------------------------------


def _say(line):
    print(line, file=sys.stderr)


def _write_stream(stream, data):
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        buffer.write(data)
        buffer.flush()
    else:
        stream.write(data.decode("utf-8", errors="replace"))


def _tools_run(args):
    """`wayline tools run <name> -- <args>`: a session's short call to a recorded tool."""
    if not args or args[0].startswith("-"):
        print("usage: wayline tools run <name> -- <args>", file=sys.stderr)
        return 2
    name, rest = args[0], list(args[1:])
    if rest[:1] == ["--"]:
        rest = rest[1:]
    try:
        done = run_recorded(name, rest)
    except ToolsError as failure:
        print("wayline tools run: %s" % failure, file=sys.stderr)
        return 2
    _write_stream(sys.stdout, done.stdout or b"")
    _write_stream(sys.stderr, done.stderr or b"")
    return done.returncode


def _entry_line(name, entry):
    return "%-20s %-26s %-8s %s" % (name, entry.get("version") or "-", entry.get("installer") or "-", entry.get("executable") or "-")


def _show(root, as_json):
    path = root / TOOLS_JSON
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        print("wayline tools: nothing installed; %s does not exist (wayline tools install)" % path, file=sys.stderr)
        return 1
    if as_json:
        print(text.rstrip())
        return 0
    tools = Tools(root, read_json_file(path) or {})
    for name in tools.names():
        print(_entry_line(name, tools.entry(name)))
    if tools.record.get("python"):
        print("%-20s %s" % ("converter venv", tools.record["python"]))
        for name, version in sorted((tools.record.get("packages") or {}).items()):
            print("  %-18s %s" % (name, version))
        print("  %-18s %s" % ("device", tools.record.get("device")))
        for note in tools.record.get("notes") or []:
            print("  note               %s" % note)
    return 0


def _dry_run(root, extras, grobid):
    print("micromamba  %s (digest beside it, .sha256) -> %s" % (micromamba_url(), root / BIN / "micromamba"))
    print("uv          %s (digest beside it, .sha256) -> %s" % (uv_url(), root / BIN / "uv"))
    uv = root / BIN / "uv"
    for name, (dists, _) in PYTHON_PACKAGES.items():
        print("%-11s %s" % (name, " ".join([str(uv), "pip", "install", "--python", str(venv_python(root))] + list(dists))))
    cuda = driver_cuda()
    print("converters  driver CUDA %s, torch index %s" % ("%d.%d" % cuda if cuda else "none", torch_index(cuda) or "PyPI default"))
    for name, argv in install_steps(root, extras, cuda):
        print("  %-9s %s" % (name, " ".join(str(part) for part in argv)))
    if grobid:
        print("  %-9s docker pull %s" % ("grobid", GROBID_IMAGE))
    for prefix, (calls, _) in CONDA_TOOLS.items():
        for specs in calls:
            print("%-11s micromamba create|install -y -p %s -c %s --override-channels %s" % (prefix, root / ENVS / prefix, CONDA_FORGE, " ".join(specs)))
    print("embedding   %s at %s, %d files checked against %s -> %s" % (
        MODEL, MODEL_REVISION, len(MODEL_FILES), model_tree_url(), root / MODELS / MODEL.replace("/", "--")))
    for name in SYSTEM_TOOLS:
        print("%-11s system, recorded at %s, never changed" % (name, shutil.which(name) or "(not on this machine)"))
    return 0


def _install_one(name, root, extras, grobid):
    if name == "docling":
        install(extras, grobid=grobid, root=root, echo=_say)
        return Tools(root).entry("docling") or {}
    return install_tool(name, root=root, echo=_say)


def tools_command(args):
    from wayline import software  # a project's tools and packages, which build on this record (ticket 82)

    if args[:1] == ["run"]:
        return _tools_run(args[1:])
    if args[:1] == ["package"]:
        return software.package_command(args[1:])
    if args[:1] == ["needs"]:
        return software.needs_command(args[1:])
    parser = argparse.ArgumentParser(
        prog="wayline tools", description="the harness's tools under ~/.wayline/tools/, each recorded in tools.json",
        epilog="wayline tools run <name> -- <args> runs a recorded tool by its absolute path and environment; "
               "wayline tools package <python|r|julia|octave> <name>... installs a project's packages")
    parser.add_argument("action", choices=["install", "show"], help="install the tools (or one), or show what tools.json records")
    parser.add_argument("name", nargs="?", help="install only this tool (%s, docling, or a system tool), or a project's tool (%s) after "
                        "a yes, or record licensed software (%s) with --at" % (", ".join(HARNESS_INSTALLERS), ", ".join(software.PROJECT_TOOLS),
                                                                               ", ".join(software.LICENSED)))
    parser.add_argument("--marker", action="store_true", help="also install marker (fallback A; its OCR needs a GPU and a vLLM server)")
    parser.add_argument("--mineru", action="store_true", help="also install MinerU's pipeline backend (fallback B; 20 GB of models)")
    parser.add_argument("--grobid", action="store_true", help="also pull the GROBID CRF Docker image for references and metadata")
    parser.add_argument("--dry-run", action="store_true", help="print the routes and commands and change nothing")
    parser.add_argument("--json", action="store_true", help="print the record as JSON")
    parser.add_argument("--yes", action="store_true", help="a project's tool: the owner said yes in the setup conversation")
    parser.add_argument("--decision", type=int, help="a project's tool: the software decision ticket answered Install")
    parser.add_argument("--attempt", type=int, help="which install of that answer this is, as journaled in tool_installed")
    parser.add_argument("--project", help="the project whose journal records the install; WAYLINE_PROJECT or the active one by default")
    parser.add_argument("--change", action="store_true", help="change an installed project's tool; the owner's word alone")
    parser.add_argument("--at", help="licensed software: the absolute path of the executable the owner installed")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    root = tools_home()
    if options.action == "install" and options.name in software.PROJECT_TOOLS + tuple(software.LICENSED):
        return software.install_command(options.name, options, root=root)
    extras = [name for name in EXTRAS if getattr(options, name)]
    if options.action == "show":
        return _show(root, options.json)
    if options.dry_run:
        return _dry_run(root, extras, options.grobid)
    if options.name:
        if options.name != "docling" and options.name not in HARNESS_INSTALLERS and options.name not in SYSTEM_TOOLS:
            print("wayline tools install: no tool is called %s; the harness installs %s, docling, and records %s" % (
                options.name, ", ".join(HARNESS_INSTALLERS), ", ".join(SYSTEM_TOOLS)), file=sys.stderr)
            return 2
        try:
            entry = _install_one(options.name, root, extras, options.grobid)
        except ToolsError as failure:
            print("wayline tools install: %s" % failure, file=sys.stderr)
            return 1
        print(_entry_line(options.name, entry))
        return 0
    results = install_all(root=root, extras=extras, grobid=options.grobid, echo=_say)
    if options.json:
        print(json.dumps({name: {"outcome": outcome, "detail": detail} for name, (outcome, detail) in results.items()}, indent=2))
    else:
        print("installed under %s" % root)
        for name, (outcome, detail) in results.items():
            print("  %-20s %-9s %s" % (name, outcome, detail or ""))
    return 1 if any(outcome == "failed" for outcome, _ in results.values()) else 0


