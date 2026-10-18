"""A project's tools, its packages, licensed software, and the `software` decision (Implementation Decision 17; ticket 82).

Decision 17 names four kinds of software. Ticket 75 built the first, the harness's own tools, and
the record they share, `~/.wayline/tools/tools.json`. This module builds the other three on it.

**A project's tools** (Octave, R, Julia) install only after a yes, through the routes ticket 75 set
up and never with root: Octave and R from conda-forge through the harness's micromamba, one prefix
per tool at `~/.wayline/tools/envs/<tool>`, and Julia from its release tarball at
`~/.wayline/tools/julia-<version>`, checked against the checksums Julia publishes beside it.
micromamba checks every conda-forge package against the digest its repodata publishes, and the
prefix's explicit export, which names each package's URL with its digest, is the tool's lock. Each
tool is one entry in `tools.json` with `installer: harness`. An installed tool is never changed
but on the owner's word (`change=True, by="owner"`).

**A project's packages** go into the project's own environment with no ask, each gitignored and
locked under `code/`: Python through the harness's uv into `<project>/.venv` (`code/requirements.lock`),
R from conda-forge into a project library at `<project>/.wayline/packages/r` that the shared R reads
through `R_LIBS` (`code/renv.lock`, written by renv), Julia into the project environment `code/`
(`code/Project.toml` and `code/Manifest.toml`), and Octave Forge into the shared Octave prefix unless
two projects disagree on a package's version, when the project gets a prefix of its own at
`<project>/.wayline/packages/octave` (`code/octave-packages.lock`).

**Licensed software** (MATLAB and its toolboxes) is the owner's alone. The owner installs it and
says where it is; code records it with `installer: owner` and the version and toolboxes `ver`
reports, after one `matlab -batch "ver"` check, and a failing check keeps the decision open.

**The `software` decision.** A ticket names its tools (`software: ["octave"]`), and it is not
launchable until every one of them is recorded, or its decision said Go without. The conductor
opens one decision ticket of the class `software` per missing tool (`open_ask`), which pauses only
the tickets that need that tool, states the route, the sizes from a dry run, the tickets waiting,
and the cost, offers Install (recommended), Not now, and Go without, and is also an item of a
`software_ask` batch, so a mark in the marks view settles it; the first answer wins. Who answers is
the autonomy's: the owner under `interactive` and `checkpoints`, the decider under `autonomous`,
except for licensed software and a change to an installed tool, whose decisions open `human_only`.
An Install answer is acted on by `settle`, the conductor's step: the install runs as a job (the
conductor never waits on a download), a failed install is retried once, and then the decision
reopens carrying the error. A worker that finds an installed tool lacking what its code needs ends
`blocked` with `blocked_on: "software <tool>: <what it lacks>"`, and code opens the decision.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from wayline import BACKENDS_ENV, backends_off
from wayline.tools import (
    CONDA_FORGE, ENVS, HARNESS, INSTALL_TIMEOUT_S, OWNER, TOOL_TIMEOUT_S, Tools, ToolsError, failure_line,
    install_micromamba, record_entry, run_tool, tool_entry, tools_home,
)
from wayline import tools as toolbox

__all__ = [
    "SOFTWARE", "OCTAVE", "R", "JULIA", "MATLAB", "PYTHON", "PROJECT_TOOLS", "LICENSED", "LANGUAGES", "JULIA_VERSION", "UNPACKED",
    "INSTALL", "NOT_NOW", "GO_WITHOUT", "OPTIONS", "known_tools", "known_tool", "is_harness_tool", "julia_url", "julia_checksums_url",
    "dry_run", "install_project_tool", "record_licensed", "parse_ver", "install_packages", "tool_called", "project_env",
    "ask_origin", "gap_origin", "asked", "gap_of", "choice", "where", "ask_text", "open_ask", "reopen", "Settled", "settle",
    "open_gap", "setup_question", "yes_from_decision", "journal_install", "install_command", "package_command",
]

SOFTWARE = "software"  # the decision class (decision 17)
OCTAVE, R, JULIA, MATLAB = "octave", "r", "julia", "matlab"
MICROMAMBA, TARBALL, OWNER_ROUTE = "micromamba", "tarball", "owner"

# A project's tools from conda-forge: the package specs one micromamba call installs into `envs/<tool>`, and
# the programs recorded from that prefix, each as (entry name, file in bin/). R brings renv, which writes the lock.
CONDA_PROJECT_TOOLS = {
    OCTAVE: (("octave",), ((OCTAVE, "octave"),)),
    R: (("r-base", "r-renv"), ((R, "R"), ("rscript", "Rscript"))),
}
JULIA_VERSION = "1.12.7"
JULIA_RELEASE = "https://julialang-s3.julialang.org/bin/linux/%s/%s/julia-%s-linux-%s.tar.gz"
JULIA_CHECKSUMS = "https://julialang-s3.julialang.org/bin/checksums/julia-%s.sha256"
_JULIA_PLATFORMS = {"x86_64": ("x64", "x86_64"), "aarch64": ("aarch64", "aarch64")}
PROJECT_TOOLS = tuple(CONDA_PROJECT_TOOLS) + (JULIA,)
# Licensed software and the check code runs once the owner says where it is.
LICENSED = {MATLAB: ("-batch", "ver")}
LICENSED_CHECK_TIMEOUT_S = 600
# What a dry run cannot measure: how much larger a package is once unpacked. conda-forge's `.conda` archives
# and Julia's tarball both unpack to several times their download, so the disk the ask states is this many
# times the download, said to be an estimate wherever it is shown.
UNPACKED = 3


def _platform():
    machine = platform.machine()
    if sys.platform != "linux" or machine not in _JULIA_PLATFORMS:
        raise ToolsError("a project's tools install on Linux x86_64 or aarch64, not %s %s" % (sys.platform, machine))
    return _JULIA_PLATFORMS[machine]


def julia_url(version=JULIA_VERSION):
    """Julia's release tarball for this machine."""
    folder, arch = _platform()
    return JULIA_RELEASE % (folder, ".".join(version.split(".")[:2]), version, arch)


def julia_checksums_url(version=JULIA_VERSION):
    """The file Julia publishes with the SHA-256 of every file of a release, one `<hex>  <name>` line each."""
    return JULIA_CHECKSUMS % version


def known_tools():
    """Every name a ticket's `software` may hold: a project's tools, licensed software, and the harness's tools."""
    names = set(PROJECT_TOOLS) | {"rscript"} | set(LICENSED) | set(toolbox.HARNESS_INSTALLERS) | set(toolbox.SYSTEM_TOOLS) | set(toolbox.PACKAGES)
    return sorted(names)


def known_tool(name):
    return name in known_tools()


def is_harness_tool(name):
    """A tool that comes with `wayline tools install` and no ask (ticket 75), never through the `software` decision."""
    return name in toolbox.HARNESS_INSTALLERS or name in toolbox.SYSTEM_TOOLS or name in toolbox.PACKAGES


def _known(name):
    if name in LICENSED:
        return
    if name not in PROJECT_TOOLS:
        raise ToolsError("no project's tool is called %s; a project's tools are %s, and %s is licensed software the owner installs"
                         % (name, ", ".join(PROJECT_TOOLS), ", ".join(LICENSED)))


# --- the dry run ------------------------------------------------------------------------------------


def _conda_specs(name):
    return list(CONDA_PROJECT_TOOLS[name][0])


def dry_run(name, root=None, run=run_tool):
    """What installing a project's tool would download and take on disk, without installing it.

    Returns `{route, source, download_bytes, disk_bytes, packages, estimated}`. A conda-forge tool asks
    micromamba to solve it (`create --dry-run --json`): the download is the size of every package it
    would fetch, and the disk is what it would link, `UNPACKED` times over (`estimated`). Julia's
    download is the size its server states for the tarball. Licensed software has none: the owner
    installs it.
    """
    _known(name)
    root = Path(root) if root is not None else tools_home()
    if run is run_tool and backends_off():
        raise ToolsError("the dry run reads the network, and %s=none keeps this process off it" % BACKENDS_ENV)
    if name in LICENSED:
        return {"route": OWNER_ROUTE, "source": None, "download_bytes": None, "disk_bytes": None, "packages": None, "estimated": False}
    if name == JULIA:
        url = julia_url()
        done = toolbox._ok(run(["curl", "-fsSIL", url], timeout=TOOL_TIMEOUT_S), "reading the size of %s" % url)
        lengths = re.findall(r"(?im)^content-length:\s*(\d+)", done.stdout.decode("utf-8", errors="replace"))
        size = int(lengths[-1]) if lengths else None
        return {"route": TARBALL, "source": url, "download_bytes": size, "disk_bytes": size * UNPACKED if size else None,
                "packages": 1, "estimated": True}
    micromamba = install_micromamba(root, run)  # a harness tool: it comes with no ask
    argv = [micromamba["executable"], "create", "--dry-run", "--json", "-y", "-p", str(root / ENVS / name),
            "-c", CONDA_FORGE, "--override-channels"] + _conda_specs(name)
    done = toolbox._ok(run(argv, timeout=INSTALL_TIMEOUT_S, env=micromamba["env"]), "micromamba's dry run of %s" % name)
    try:
        actions = json.loads(done.stdout.decode("utf-8", errors="replace"))["actions"]
        fetched = sum(int(item["size"]) for item in actions.get("FETCH") or [])
        linked = actions.get("LINK") or []
        disk = sum(int(item["size"]) for item in linked) * UNPACKED
    except (ValueError, KeyError, TypeError):
        raise ToolsError("micromamba's dry run of %s printed no plan (%s)" % (name, failure_line(done))) from None
    return {"route": MICROMAMBA, "source": CONDA_FORGE, "download_bytes": fetched, "disk_bytes": disk, "packages": len(linked),
            "estimated": True}


# --- the install ------------------------------------------------------------------------------------


def _installed(entry):
    return bool(entry and entry.get("executable") and Path(entry["executable"]).exists())


def install_project_tool(name, root=None, run=run_tool, echo=None, change=False, by=None):
    """Install a project's tool by its route and merge its entry into `tools.json`; returns its entry.

    Called only after a yes (the verb checks for one). A tool already installed is returned as it is:
    code never changes what is installed, and `change=True` (a newer build through the same route) is
    refused unless `by` is `owner`. Licensed software is refused outright: code never installs it.
    """
    _known(name)
    if name in LICENSED:
        raise ToolsError("%s is licensed software: the owner installs it and says where it is "
                         "(wayline tools install %s --at <path>); code never installs it" % (name, name))
    root = Path(root) if root is not None else tools_home()
    echo = echo or (lambda line: None)
    current = Tools(root).entry(name)
    if _installed(current):
        if not change:
            return current
        if by != OWNER:
            raise ToolsError("%s is installed (%s %s); changing an installed tool is the owner's word alone"
                             % (name, current.get("executable"), current.get("version")))
    elif change:
        change = False  # nothing installed to change: an ordinary install
    root.mkdir(parents=True, exist_ok=True)
    if name == JULIA:
        return _install_julia(root, run, echo)
    return _install_conda(name, root, run, echo, change)[name]


def _install_conda(name, root, run, echo, change):
    specs, programs = CONDA_PROJECT_TOOLS[name]
    micromamba = install_micromamba(root, run, echo)
    prefix = root / ENVS / name
    env = micromamba["env"]
    exists = (prefix / "conda-meta").is_dir() or (prefix / "bin").is_dir()
    if change and exists:
        argv = [micromamba["executable"], "update", "-y", "-p", str(prefix), "-c", CONDA_FORGE, "--override-channels", "--all"]
    else:
        argv = [micromamba["executable"], "install" if exists else "create", "-y", "-p", str(prefix), "-c", CONDA_FORGE,
                "--override-channels"] + list(specs)
    echo("%s: %s" % (name, " ".join(argv)))
    toolbox._ok(run(argv, timeout=INSTALL_TIMEOUT_S, env=env), "micromamba %s %s" % (argv[1], name))
    exported = toolbox._ok(run([micromamba["executable"], "env", "export", "-p", str(prefix), "--explicit"], timeout=TOOL_TIMEOUT_S, env=env),
                           "exporting the %s prefix's lock" % name).stdout
    lock = toolbox._write_lock(root, name, exported)
    entries = {}
    for entry_name, program in programs:
        executable = prefix / "bin" / program
        version = toolbox._version_of(executable, run)
        entries[entry_name] = record_entry(root, entry_name, tool_entry(
            executable, version, MICROMAMBA, installer=HARNESS, source=CONDA_FORGE, lock=lock, prefix=str(prefix)))
    return entries


def _published_julia_sha256(url, run):
    name = url.rsplit("/", 1)[-1]
    for line in toolbox._fetch_text(julia_checksums_url(), run).splitlines():
        words = line.split()
        if len(words) == 2 and words[1] == name and re.fullmatch(r"[0-9a-f]{64}", words[0]):
            return words[0]
    raise ToolsError("%s lists no SHA-256 for %s" % (julia_checksums_url(), name))


def _install_julia(root, run, echo):
    url = julia_url()
    expected = _published_julia_sha256(url, run)
    folder = root / ("julia-%s" % JULIA_VERSION)
    staging = Path(tempfile.mkdtemp(dir=str(root), prefix=".julia-"))
    try:
        echo("julia: %s" % url)
        tarball = toolbox._download(url, staging / "julia.tar.gz", run, toolbox._sha256_check(url, expected))
        unpacked = staging / "unpacked"
        unpacked.mkdir()
        with tarfile.open(tarball) as archive:
            archive.extractall(unpacked, filter="data")  # no absolute path, no `..`, no link leaving the folder
        top = unpacked / ("julia-%s" % JULIA_VERSION)
        if not (top / "bin" / "julia").is_file():
            raise ToolsError("%s holds no julia-%s/bin/julia" % (url, JULIA_VERSION))
        if folder.exists():
            shutil.rmtree(folder)
        os.replace(top, folder)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    executable = folder / "bin" / "julia"
    env = {"JULIA_DEPOT_PATH": str(root / "julia" / "depot")}
    return record_entry(root, JULIA, tool_entry(
        executable, toolbox._version_of(executable, run, env=env), TARBALL, installer=HARNESS, env=env, source=url,
        digest="sha256:" + expected))


# --- licensed software ------------------------------------------------------------------------------

_MATLAB_VERSION = re.compile(r"(?m)^MATLAB Version:\s*(\S+)\s*\((R\d{4}[ab])\)")
_PRODUCT = re.compile(r"(?m)^(\S.*?)\s{2,}Version\s+(\S+)\s+\((R\d{4}[ab])\)\s*$")


def parse_ver(text):
    """What MATLAB's `ver` printed: `{version, release, toolboxes: {name: version}}`, or None without its version line.

    The license number it also prints is never kept.
    """
    found = _MATLAB_VERSION.search(text or "")
    if found is None:
        return None
    toolboxes = {product.strip(): version for product, version, _ in _PRODUCT.findall(text) if product.strip() != "MATLAB"}
    return {"version": found.group(1), "release": found.group(2), "toolboxes": dict(sorted(toolboxes.items()))}


def record_licensed(name, executable, root=None, run=run_tool, output=None, exists=os.path.exists):
    """Record licensed software where the owner installed it, after its check; returns the entry.

    The check is one `matlab -batch "ver"`, run here when `output` is None (a setup conversation) or
    read from the check job's log when the conductor ran it. A check that fails, or that prints no
    version, raises `ToolsError` and records nothing, so the decision stays open.
    """
    if name not in LICENSED:
        raise ToolsError("%s is not licensed software; the licensed software code records is %s" % (name, ", ".join(LICENSED)))
    executable = str(executable or "").strip()
    if not executable or not os.path.isabs(executable):
        raise ToolsError("say where %s is installed by the absolute path of its executable, got %r" % (name, executable))
    if not exists(executable):
        raise ToolsError("%s is not at %s; the owner installs it and says where it is" % (name, executable))
    root = Path(root) if root is not None else tools_home()
    if output is None:
        done = run([executable] + list(LICENSED[name]), timeout=LICENSED_CHECK_TIMEOUT_S)
        if done.returncode != 0:
            raise ToolsError("the check `%s %s` failed (%s)" % (name, " ".join('"%s"' % part if part == "ver" else part for part in LICENSED[name]),
                                                               failure_line(done)))
        output = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", errors="replace")
    found = parse_ver(output)
    if found is None:
        raise ToolsError("the check `%s -batch \"ver\"` printed no MATLAB Version line" % name)
    return record_entry(root, name, tool_entry(
        executable, found["version"], OWNER_ROUTE, installer=OWNER, release=found["release"], toolboxes=found["toolboxes"]))


# --- a project's packages ---------------------------------------------------------------------------

PYTHON = "python"
LANGUAGES = (PYTHON, R, JULIA, OCTAVE)
VENV = ".venv"
PACKAGES = Path(".wayline") / "packages"
CODE = "code"
LOCKS = {PYTHON: "requirements.lock", R: "renv.lock", JULIA: "Manifest.toml", OCTAVE: "octave-packages.lock"}
OCTAVE_FORGE = "octave-forge.json"  # under <tools>/locks/: which projects put which Octave Forge package in the shared prefix
_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*(?:(?:==|>=|<=|~=|!=|=|>|<)[A-Za-z0-9][A-Za-z0-9._*+-]*)?$")
# renv writes the lock; the paths reach R through the environment, so none is ever spliced into R code.
_RENV_SNAPSHOT = ("renv::snapshot(project = Sys.getenv('WAYLINE_CODE'), library = Sys.getenv('WAYLINE_R_LIBRARY'), "
                  "lockfile = Sys.getenv('WAYLINE_LOCK'), type = 'all', prompt = FALSE)")
_JULIA_ADD = "using Pkg; Pkg.add(ARGS)"
_OCTAVE_SHARED = "pkg('install', '-forge', '-global', %s)"
_OCTAVE_LOCAL = ("d = getenv('WAYLINE_OCTAVE_PKG'); pkg('prefix', d, d); pkg('local_list', fullfile(d, 'octave_packages')); "
                 "pkg('install', '-forge', %s)")
_OCTAVE_LIST = "d = getenv('WAYLINE_OCTAVE_PKG'); if !isempty(d) pkg('local_list', fullfile(d, 'octave_packages')); end; pkg('list')"
_OCTAVE_ROW = re.compile(r"^\s*(\S+?)\s*\*?\s*\|\s*(\S+)\s*\|", re.M)


def _package_names(names):
    names = [str(name).strip() for name in names or ()]
    if not names:
        raise ToolsError("name at least one package")
    bad = [name for name in names if not _PACKAGE.match(name)]
    if bad:
        raise ToolsError("%s %s not a package name (a name, or a name with one version pin such as six==1.17.0)"
                         % (", ".join(repr(name) for name in bad), "is" if len(bad) == 1 else "are"))
    return names


def _tool_for_packages(language, tools):
    entry = tools.entry(language)
    if not _installed(entry):
        raise ToolsError("%s is a project's tool that is not recorded in %s; its software decision comes first, "
                         "and its packages after it" % (language, tools.root / toolbox.TOOLS_JSON))
    return entry


def install_packages(project, language, names, code_dir=None, root=None, run=run_tool):
    """Install a project's packages into its own environment, with no ask, and write the lock under `code/`.

    Returns `{language, environment, lock, packages}`. `code_dir` is where the lock goes: the project's
    `code/`, or a worker's worktree's when the worker runs the verb, so the lock is committed with its
    ticket. Python needs only the harness's uv (installed with no ask when it is missing); R, Julia, and
    Octave need their tool recorded, which is the `software` decision's to settle.
    """
    if language not in LANGUAGES:
        raise ToolsError("a project's packages are %s, got %r" % (", ".join(LANGUAGES), language))
    names = _package_names(names)
    project = Path(project).resolve()
    code_dir = Path(code_dir).resolve() if code_dir is not None else project / CODE
    root = Path(root) if root is not None else tools_home()
    tools = Tools(root)
    if language != PYTHON:
        _tool_for_packages(language, tools)
    code_dir.mkdir(parents=True, exist_ok=True)
    lock = code_dir / LOCKS[language]
    if language == PYTHON:
        environment = _python_packages(project, names, lock, root, run)
    elif language == R:
        environment = _r_packages(project, names, code_dir, lock, root, tools, run)
    elif language == JULIA:
        environment = _julia_packages(names, code_dir, tools, run)
    else:
        environment = _octave_packages(project, names, lock, root, tools, run)
    if not lock.is_file():
        raise ToolsError("the %s packages were installed but %s was not written" % (language, lock))
    return {"language": language, "environment": str(environment), "lock": str(lock), "packages": names}


def _python_packages(project, names, lock, root, run):
    uv = Tools(root).entry("uv")
    if not _installed(uv):
        root.mkdir(parents=True, exist_ok=True)
        uv = toolbox.install_uv(root, run)  # a harness tool: it comes with no ask
    venv = project / VENV
    python = venv / "bin" / "python"
    if not python.exists():
        toolbox._ok(run([uv["executable"], "venv", "--python", sys.executable, str(venv)], timeout=INSTALL_TIMEOUT_S, env=uv["env"]),
                    "creating %s" % venv)
    toolbox._ok(run([uv["executable"], "pip", "install", "--python", str(python)] + names, timeout=INSTALL_TIMEOUT_S, env=uv["env"]),
                "installing %s into %s" % (", ".join(names), venv))
    frozen = toolbox._ok(run([uv["executable"], "pip", "freeze", "--python", str(python)], timeout=TOOL_TIMEOUT_S, env=uv["env"]),
                         "freezing %s" % venv).stdout
    lock.write_bytes(b"# uv pip freeze of <project>/.venv (wayline tools package python)\n" + frozen)
    return venv


def _r_packages(project, names, code_dir, lock, root, tools, run):
    r_entry = _tool_for_packages(R, tools)
    rscript = tools.entry("rscript") or r_entry
    micromamba = tools.entry("micromamba")
    if not _installed(micromamba):
        micromamba = install_micromamba(root, run)
    library = project / PACKAGES / R
    exists = (library / "conda-meta").is_dir()
    # The project's library holds the same R the shared prefix does, so the shared R loads what it holds.
    specs = ["r-base=%s" % r_entry["version"]] + ["r-%s" % name.lower() for name in names]
    argv = [micromamba["executable"], "install" if exists else "create", "-y", "-p", str(library), "-c", CONDA_FORGE, "--override-channels"] + specs
    toolbox._ok(run(argv, timeout=INSTALL_TIMEOUT_S, env=micromamba["env"]), "micromamba %s %s" % (argv[1], " ".join(specs[1:])))
    env = dict(rscript.get("env") or {}, R_LIBS=str(library / "lib" / "R" / "library"),
               WAYLINE_CODE=str(code_dir), WAYLINE_R_LIBRARY=str(library / "lib" / "R" / "library"), WAYLINE_LOCK=str(lock))
    toolbox._ok(run([rscript["executable"], "-e", _RENV_SNAPSHOT], timeout=INSTALL_TIMEOUT_S, env=env), "renv's snapshot into %s" % lock)
    return library


def _julia_packages(names, code_dir, tools, run):
    julia = _tool_for_packages(JULIA, tools)
    toolbox._ok(run([julia["executable"], "--project=%s" % code_dir, "-e", _JULIA_ADD] + names, timeout=INSTALL_TIMEOUT_S,
                    env=julia.get("env") or None), "Pkg.add %s" % " ".join(names))
    return code_dir


def _octave_wanted(names):
    """`signal` or `signal=1.4.5` (also `==`) as `(name, version or None)`."""
    wanted = []
    for name in names:
        package, _, version = name.replace("==", "=").partition("=")
        wanted.append((package, version or None))
    return wanted


def _octave_packages(project, names, lock, root, tools, run):
    octave = _tool_for_packages(OCTAVE, tools)
    shared = Path(octave.get("prefix") or Path(octave["executable"]).parent.parent)
    wanted = _octave_wanted(names)
    path = Path(root) / toolbox.LOCKS / OCTAVE_FORGE
    held = toolbox.read_json_file(path) or {}
    local = project / PACKAGES / OCTAVE
    # Two projects disagree when one asks a version of a package that the shared prefix holds at another version.
    disagree = any(version and (held.get(name) or {}).get("version") not in (None, version) for name, version in wanted)
    quoted = ", ".join("'%s'" % name for name, _ in wanted)
    env = dict(octave.get("env") or {})
    if disagree:
        local.mkdir(parents=True, exist_ok=True)
        env["WAYLINE_OCTAVE_PKG"] = str(local)
        expression = _OCTAVE_LOCAL % quoted
    else:
        expression = _OCTAVE_SHARED % quoted
    toolbox._ok(run([octave["executable"], "--no-gui", "--eval", expression], timeout=INSTALL_TIMEOUT_S, env=env or None),
                "pkg install -forge %s" % " ".join(name for name, _ in wanted))
    listed = toolbox._ok(run([octave["executable"], "--no-gui", "--eval", _OCTAVE_LIST], timeout=TOOL_TIMEOUT_S, env=env or None),
                         "pkg list").stdout
    lock.write_bytes(b"% pkg list of the Octave Forge packages this project uses (wayline tools package octave)\n" + listed)
    if not disagree:
        versions = dict(_OCTAVE_ROW.findall(listed.decode("utf-8", errors="replace")))

        def merge(record):
            for name, _ in wanted:
                entry = record.setdefault(name, {"version": None, "projects": []})
                entry["version"] = versions.get(name, entry.get("version"))
                entry["projects"] = sorted(set(entry.get("projects") or []) | {str(project)})

        with toolbox._record_lock(root):
            record = toolbox.read_json_file(path) or {}
            merge(record)
            path.parent.mkdir(parents=True, exist_ok=True)
            toolbox._write_record(path, record)
    return local if disagree else shared


def tool_called(name, entry):
    """What a job record keeps of one tool it calls: its name, version, and lock digest (the lock's SHA-256, else its download's digest)."""
    entry = entry or {}
    lock = entry.get("lock")
    digest = (lock or {}).get("sha256") if isinstance(lock, dict) else None
    return {"name": name, "version": entry.get("version"), "lock": digest or entry.get("digest") or entry.get("revision")}


def project_env(project, name):
    """What a call to one of a project's tools needs beyond the tool's own environment: where the project's packages are."""
    project = Path(project)
    if name in (R, "rscript"):
        library = project / PACKAGES / R / "lib" / "R" / "library"
        return {"R_LIBS": str(library)} if library.is_dir() else {}
    if name == JULIA:
        return {"JULIA_PROJECT": str(project / CODE)}
    return {}


# --- the `software` decision ------------------------------------------------------------------------

INSTALL, NOT_NOW, GO_WITHOUT = "Install", "Not now", "Go without"
OPTIONS = (INSTALL, NOT_NOW, GO_WITHOUT)
WHERE = "the absolute path of the owner's %s executable"  # the first option of a licensed ask
BATCH_KIND = "software_ask"
APPROVE, DECLINE = "approve", "decline"
ATTEMPTS = 2  # an install and its one retry
INSTALL_JOB, CHECK_JOB = "install", "check"
JOB_WALLCLOCK_MINUTES = 90
_ORIGIN = re.compile(r"^software ([a-z][a-z0-9-]*)(?: gap ([0-9a-f]{12}))?$")
_GAP = re.compile(r"^\s*software\s+([a-z][a-z0-9-]*)\s*[:,]\s*(\S.*)$", re.IGNORECASE | re.DOTALL)
_PATH = re.compile(r"(/[^\s'\"`]+)")


def ask_origin(name):
    """The origin of the ask about a missing tool: one decision ticket per tool."""
    return "software %s" % name


def gap_origin(name, gap):
    """The origin of the ask about a gap a worker found in an installed tool: one per tool and gap."""
    return "software %s gap %s" % (name, hashlib.sha256(" ".join(str(gap).split()).encode("utf-8")).hexdigest()[:12])


def asked(fields):
    """`(tool, is_gap)` of a `software` decision ticket, from its origin; None for any other ticket."""
    if (fields or {}).get("kind") != "decision":
        return None
    found = _ORIGIN.match(str(fields.get("origin") or ""))
    return (found.group(1), found.group(2) is not None) if found else None


def gap_of(blocked_on):
    """`(tool, gap)` when a worker's `blocked_on` reads `software <tool>: <what it lacks>`, else None."""
    found = _GAP.match(str(blocked_on or ""))
    if found is None or not known_tool(found.group(1).lower()):
        return None
    return found.group(1).lower(), " ".join(found.group(2).split())


def choice(answer, licensed=False):
    """What an answer to a `software` decision chooses: `Install`, `Not now`, or `Go without`, read off its first words.

    A mark reads the same way (`approve` is Install, `decline` is Not now). For licensed software an
    answer that names an absolute path is the owner saying where it is, which is its Install, and an
    Install that names none is asked again for the path. An answer that matches nothing is Not now:
    nothing is installed on a word the harness cannot read.
    """
    text = " ".join(str(answer or "").split()).lower()
    if text.startswith("go without"):
        return GO_WITHOUT
    if text.startswith("not now") or text.startswith(DECLINE):
        return NOT_NOW
    if licensed and _PATH.search(str(answer or "")):
        return INSTALL
    if text.startswith("install") or text.startswith(APPROVE) or text in ("yes", "y"):
        return INSTALL
    return NOT_NOW


def where(answer):
    """The absolute path an answer to a licensed ask names, or None."""
    found = _PATH.search(str(answer or ""))
    return found.group(1).rstrip(".,;:)") if found else None


def _mib(size):
    return "%d MB" % round(size / 1e6) if size else "an unknown size"


def _route_line(name, dry):
    if name in LICENSED:
        return "route: none; %s is licensed software, which the owner installs and code only records (installer: owner) " \
               "after one `%s -batch \"ver\"` check" % (name, name)
    if name == JULIA:
        return "route: Julia %s's release tarball (%s) into ~/.wayline/tools/julia-%s, checked against the SHA-256 Julia publishes, no root" \
               % (JULIA_VERSION, julia_url(), JULIA_VERSION)
    return "route: conda-forge through the harness's micromamba (%s) into ~/.wayline/tools/envs/%s, each package checked against " \
           "its published digest, no root" % (" ".join(_conda_specs(name)), name)


def _size_lines(name, dry, problem):
    if name in LICENSED:
        return []
    if problem:
        return ["sizes: the dry run failed (%s), so the sizes are unknown" % problem]
    return ["sizes from a dry run: %s to download, about %s on disk once unpacked (an estimate: %d times what it links)"
            % (_mib(dry.get("download_bytes")), _mib(dry.get("disk_bytes")), UNPACKED)]


def _cost_line(name, gap=False):
    if name in LICENSED:
        return "cost: a license the owner holds; code never installs or changes licensed software, and the check costs no model turn"
    if gap:
        return "cost: changing an installed tool can change what earlier results ran on, which is why only the owner says so; no money"
    return "cost: no money (free software), no model turn, and the disk above under ~/.wayline/tools; the install runs as a job, " \
           "so no run waits on the download"


def _named(identifiers):
    return ("ticket %s" if len(identifiers) == 1 else "tickets %s") % ", ".join(str(identifier) for identifier in identifiers)


def ask_text(name, waiting, gap=None):
    """The question a `software` decision asks."""
    if gap is not None:
        return ("%s found that the installed %s lacks what its code needs (%s): change the installed %s?"
                % (_named(waiting).capitalize(), name, gap, name))
    if name in LICENSED:
        return ("%s %s %s, licensed software this machine does not have recorded: where did you install it?"
                % (_named(waiting).capitalize(), "needs" if len(waiting) == 1 else "need", name))
    return ("%s %s %s, which this machine does not have: install it?"
            % (_named(waiting).capitalize(), "needs" if len(waiting) == 1 else "need", name))


def open_ask(project, name, waiting, root=None, run=run_tool, notify=None, gap=None, error=None):
    """Open the `software` decision about one tool, pausing only `waiting`; returns the `open_decision` report.

    The ticket states the route, the sizes from a dry run, the tickets waiting, and the cost, and offers
    Install (recommended), Not now, and Go without; a licensed tool's first option is where the owner
    installed it, and a gap's is changing the installed tool, both `human_only`. An ask about a tool
    that already has one only adds the new pause edges. Each new ask is also an item of a
    `software_ask` batch, so a mark settles it.
    """
    from wayline import decisions  # the decision tickets import the project module, which imports the tools record

    project = Path(project).resolve()
    waiting = sorted(set(waiting))
    licensed = name in LICENSED
    origin = gap_origin(name, gap) if gap is not None else ask_origin(name)
    exists = any(fields.get("origin") == origin for fields in _read_tickets(project) if fields.get("kind") == "decision")
    dry, problem = {}, None
    if not exists and not licensed and gap is None:
        try:
            dry = dry_run(name, root=root, run=run)
        except ToolsError as failure:
            problem = str(failure)
    evidence = [_route_line(name, dry)] + _size_lines(name, dry, problem) + [
        "waiting: %s, and only %s; every other ticket goes on" % (_named(waiting), "it" if len(waiting) == 1 else "they"),
        _cost_line(name, gap is not None),
    ]
    if gap is not None:
        evidence.append("the gap, as the worker reported it: %s" % gap)
    if error:
        evidence.append("the last install failed: %s" % error)
    if licensed:
        options = [WHERE % name, NOT_NOW, GO_WITHOUT]
        recommended = None
    elif gap is not None:
        options, recommended = [INSTALL, NOT_NOW, GO_WITHOUT], None
    else:
        options, recommended = list(OPTIONS), INSTALL
    title = ("Where is %s installed?" % name) if licensed else ("Change the installed %s?" % name) if gap is not None else ("Install %s?" % name)
    report = decisions.open_decision(
        project, ask_text(name, waiting, gap), options=options, recommended=recommended, evidence=evidence, blocking="subgraph",
        human_only=licensed or gap is not None, pauses=waiting, proposed_by="conductor", origin=origin, title=title,
        notify=notify, decision_class=SOFTWARE)
    _ensure_batch(project, report["ticket"])
    return report


def _read_tickets(project):
    from wayline.tickets import read_tickets
    return read_tickets(project)


def _ensure_batch(project, identifier):
    """The open ask's item in a `software_ask` batch: one open batch per unanswered ask, opened again when it is asked again."""
    from wayline import batches
    from wayline.decisions import decision_question
    from wayline.tickets import answer_section, filename, read_ticket, tickets_dir

    fields = {ticket["id"]: ticket for ticket in _read_tickets(project)}.get(identifier)
    if fields is None or fields["status"] != "open" or asked(fields) is None:
        return None
    if any(batch["decision"] == identifier and batch["kind"] == BATCH_KIND for batch in batches.read_batches(project, status="open")):
        return None
    body = read_ticket(tickets_dir(project) / filename(fields))[1]
    if answer_section(body):
        return None
    name, gap = asked(fields)
    default = APPROVE if not gap and name not in LICENSED else None
    text = decision_question(fields, body)
    if name in LICENSED:
        text += " Approve with the path in the note."
    return batches.open_batch(project, BATCH_KIND, fields["title"], [{"ref": fields["origin"], "text": text, "default": default}],
                              decision=identifier)


def reopen(project, identifier, why, notify=None):
    """Ask a `software` decision again, carrying `why` (the install's error, the failed check): returns True when it was reopened.

    The answer stops being its answer (`ticket_rerun` with `by: code`, the `## Answer` heading retired),
    the error joins the evidence the owner and the decider read, the ticket is open again, and
    `decision_opened` is journaled and the owner notified as for any decision ticket.
    """
    from wayline import decisions, grill
    from wayline.ledger import DECISION_OPENED, TICKET_RERUN, Ledger
    from wayline.notify import notify as send_notification
    from wayline.tickets import filename, read_ticket, retire_answer, tickets_dir, write_ticket

    project = Path(project).resolve()
    why = " ".join(str(why).split())
    ledger = Ledger(project)
    with ledger.lock():
        fields = {ticket["id"]: ticket for ticket in _read_tickets(project)}.get(identifier)
        if fields is None or asked(fields) is None:
            return False
        fields, body = read_ticket(tickets_dir(project) / filename(fields))
        ledger.append_event(TICKET_RERUN, {"ticket": identifier, "by": "code"}, ticket=identifier)
        body = retire_answer(body)
        try:
            record = decisions.decision_record(body)
        except ValueError:
            record = None
        if record is not None:
            evidence = list(record.get("evidence") or []) + ["asked again: %s" % why]
            body = body.replace(grill.machine_line(record), grill.machine_line(dict(record, evidence=evidence)))
        body = body.rstrip("\n") + "\n\n## Asked again\n\n%s\n" % why.replace("<!--", "<\\!--")
        fields = dict(fields, status="open")
        write_ticket(ledger, fields, body)
        ledger.append_event(DECISION_OPENED, {"ticket": identifier, "blocking": fields.get("blocking"),
                                              "human_only": bool(fields.get("human_only"))}, ticket=identifier)
    _ensure_batch(project, identifier)
    (notify or send_notification)(DECISION_OPENED, "%s: decision ticket %d is asked again: %s. It asks: %s Answer with wayline answer %d "
                                  "\"<answer>\", in the dashboard's decisions view, or with a mark in the marks view."
                                  % (project.name, identifier, why, decisions.decision_question(fields, body), identifier),
                                  project, identifier)
    return True


# --- the conductor's step ---------------------------------------------------------------------------


class Settled:
    """What one wave's `settle` leaves the conductor: the tools gone without, whether a job is under way, and why each ticket waits."""

    def __init__(self):
        self.waived = set()
        self.in_flight = []
        self.waiting = {}
        self.said = []

    def missing(self, entry, tools):
        """The tools a ticket needs that are neither recorded nor gone without: it is launchable only when this is empty."""
        return [name for name in (entry.get("software") or []) if name not in self.waived and not _installed(tools.entry(name))]


class _Lazy:
    """The job runner made only when a job is launched or read: a wave with no install to start never builds one."""

    def __init__(self, make):
        self._make, self._made = make, None

    def __getattr__(self, name):
        if self._made is None:
            self._made = self._make()
        return getattr(self._made, name)


class _Ask:
    """One `software` decision ticket read back from its file and the journal."""

    def __init__(self, fields, name, gap):
        self.fields, self.name, self.gap = fields, name, gap
        self.id = fields["id"]
        self.licensed = name in LICENSED
        self.since = -1            # the index of the latest `ticket_rerun`: what came before it was another asking
        self.answer = None         # (index, answer, decided_by) of the answer since then
        self.jobs = []             # [(index, job id)] launched since the answer
        self.ended = {}            # job id: (exit code or None, reason)
        self.outcomes = {}         # attempt: (outcome, version, reason) of `tool_installed`


def _job_prefix(identifier, kind, name):
    return "t%d-%s-%s-" % (identifier, kind, name)


def _read_asks(project, events, fields_by_id):
    from wayline.ledger import DECISION, JOB_CANCELLED, JOB_FAILED, JOB_FINISHED, JOB_LAUNCHED, TICKET_RERUN, TOOL_INSTALLED

    asks = {}
    for fields in fields_by_id.values():
        found = asked(fields)
        if found is not None:
            asks[fields["id"]] = _Ask(fields, *found)
    by_job = {}
    for index, event in enumerate(events):
        name, payload = event.get("event"), event.get("payload") or {}
        ticket = event.get("ticket") if event.get("ticket") is not None else payload.get("ticket")
        ask = asks.get(ticket)
        if name == TICKET_RERUN and ask is not None:
            ask.since, ask.answer, ask.jobs, ask.outcomes = index, None, [], {}
        elif name == DECISION and ask is not None:
            ask.answer, ask.jobs, ask.outcomes = (index, payload.get("answer"), payload.get("decided_by")), [], {}
        elif name == JOB_LAUNCHED and ask is not None and ask.answer is not None:
            job = event.get("job") or payload.get("job")
            if job and (job.startswith(_job_prefix(ask.id, INSTALL_JOB, ask.name)) or job.startswith(_job_prefix(ask.id, CHECK_JOB, ask.name))):
                ask.jobs.append((index, job))
                by_job[job] = ask
        elif name in (JOB_FINISHED, JOB_FAILED, JOB_CANCELLED):
            job = event.get("job") or payload.get("job")
            if job in by_job:
                by_job[job].ended[job] = (payload.get("exit_code") if name == JOB_FINISHED else None,
                                          None if name == JOB_FINISHED else (payload.get("reason") or name))
        elif name == TOOL_INSTALLED and ask is not None and ask.answer is not None and payload.get("name") == ask.name:
            ask.outcomes[payload.get("attempt")] = (payload.get("outcome"), payload.get("version"), payload.get("reason"))
    return asks


def _marked_first(project, ask, events):
    """The settled mark of the ask's latest batch, when it was given before any answer since the asking: `(mark, note, by)`."""
    from wayline import batches
    from wayline.ledger import MARKED

    found = [batch for batch in batches.read_batches(project) if batch["decision"] == ask.id and batch["kind"] == BATCH_KIND]
    if not found:
        return None, None
    batch = found[-1]
    item = batch["items"][0]
    at = None
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if event.get("event") == MARKED and payload.get("batch") == batch["id"] and payload.get("mark") is not None:
            at = index
            break
    return batch, (at, item) if item["mark"] is not None and at is not None and at > ask.since else None


def settle(project, runner, tools=None, run=run_tool, notify=None, say=None, harness_root=None):
    """The conductor's `software` step of one wave: marks and answers kept in step, answers acted on, missing tools asked for.

    1. A mark on an ask's batch item answers its decision when nothing has (the owner's as the owner's,
       the decider's as the decider's), and an answer settles the item it left open: the first wins.
    2. An Install answer launches the install as a job through `runner`; an install that ended without
       the tool recorded is retried once, and then the decision is asked again with the error
       (`reopen`). A licensed tool's answer names where it is, and one `matlab -batch "ver"` check job
       runs: a pass records it, a failure asks again. Go without lets the tickets that need the tool
       launch without it; Not now leaves them waiting. A gap's Install changes the installed tool (on
       the owner's word only) and its Install or Go without opens the blocked ticket again.
    3. Every open or failed ticket naming a tool that is neither recorded nor gone without is paused by
       that tool's ask, which is opened when there is none.

    Returns a `Settled`. Idempotent: everything it does is read back from the journal, the job files,
    the batches, and `tools.json`, so a second call, or a restarted conductor, starts nothing twice.
    """
    from wayline import batches, decisions, replay
    from wayline.ledger import Ledger
    from wayline.project import ProjectError, answer as answer_ticket

    project = Path(project).resolve()
    tools = tools if tools is not None else Tools()
    say = say or (lambda line: None)
    runner = runner if hasattr(runner, "launch") else _Lazy(runner)
    settled = Settled()
    ledger = Ledger(project)

    def said(line):
        settled.said.append(line)
        say(line)

    def current():
        events, _ = ledger.read_events()
        fields_by_id = {fields["id"]: fields for fields in _read_tickets(project)}
        return events, fields_by_id, _read_asks(project, events, fields_by_id)

    events, fields_by_id, asks = current()
    # 1. marks and answers in step
    changed = False
    for ask in asks.values():
        batch, marked = _marked_first(project, ask, events)
        if batch is None:
            continue
        item = batch["items"][0]
        if marked is not None and ask.answer is None:
            text = _answer_from_mark(ask, item)
            if text is None:
                said("  decision ticket %d: the mark approves %s but its note names no path; answer it with where %s is"
                     % (ask.id, ask.name, ask.name))
                continue
            try:
                if item["by"] == batches.DECIDER:
                    decisions.decide(project, ask.id, text, "the decider's mark on item 1 of %s" % batch["id"])
                else:
                    answer_ticket(project, ask.id, text, rationale="the owner's mark on item 1 of %s" % batch["id"])
                changed = True
                said("  decision ticket %d answered by the %s's mark in %s: %s" % (ask.id, item["by"], batch["id"], text))
            except ProjectError as failure:
                said("  decision ticket %d: the mark in %s is not taken (%s)" % (ask.id, batch["id"], failure))
        elif ask.answer is not None and item["mark"] is None:
            picked = choice(ask.answer[1], ask.licensed)
            try:
                batches.mark(project, batch["id"], 1, APPROVE if picked == INSTALL else DECLINE,
                             note=GO_WITHOUT if picked == GO_WITHOUT else None,
                             by=batches.DECIDER if ask.answer[2] == "decider" else batches.OWNER)
                changed = True
            except batches.BatchError:
                pass
    if changed:
        events, fields_by_id, asks = current()

    # 2. answers acted on
    for ask in asks.values():
        if ask.answer is None:
            continue
        at, answer, decided_by = ask.answer
        _, marked = _marked_first(project, ask, events)
        if marked is not None and marked[0] < at and _answer_from_mark(ask, marked[1]) is not None:
            # A mark given before the answer journaled since: the first answer wins.
            answer = _answer_from_mark(ask, marked[1])
            decided_by = "decider" if marked[1]["by"] == batches.DECIDER else "human"
        picked = choice(answer, ask.licensed)
        if picked == GO_WITHOUT and not ask.gap:
            settled.waived.add(ask.name)
        if ask.gap:
            _act_on_gap(project, ask, picked, decided_by, runner, settled, said, notify, harness_root, fields_by_id)
        elif picked == INSTALL and ask.licensed:
            _act_on_licensed(project, ask, answer, runner, tools, settled, said, notify)
        elif picked == INSTALL:
            _act_on_install(project, ask, runner, tools, settled, said, notify, harness_root)

    # 3. missing tools asked for
    events, fields_by_id, asks = current()
    by_tool = {}
    for fields in sorted(fields_by_id.values(), key=lambda item: item["id"]):
        if fields["kind"] == "decision" or fields["status"] not in ("open", "failed"):
            continue
        for name in settled.missing(fields, tools):
            if is_harness_tool(name):
                settled.waiting.setdefault(fields["id"], []).append(
                    "%s is a harness tool that tools.json does not record; `wayline tools install` records it" % name)
            elif not known_tool(name):
                settled.waiting.setdefault(fields["id"], []).append("%s is no tool the harness knows" % name)
            else:
                by_tool.setdefault(name, []).append(fields["id"])
    for name, waiting in sorted(by_tool.items()):
        found = [ask for ask in asks.values() if ask.name == name and not ask.gap]
        ask = found[0] if found else None
        if ask is None or any(ask.id not in fields_by_id[identifier]["blocked_by"] for identifier in waiting):
            try:
                report = open_ask(project, name, waiting, root=tools.root, run=run, notify=notify)
            except (ValueError, OSError) as failure:
                said("  %s wait for %s, and its software decision could not be opened: %s" % (_named(waiting), name, failure))
                continue
            if report["opened"]:
                said("  %s %s %s: decision ticket %d asks whether to install it" % (
                    _named(waiting), "needs" if len(waiting) == 1 else "need", name, report["ticket"]))
            identifier = report["ticket"]
        else:
            identifier = ask.id
        for ticket in waiting:
            settled.waiting.setdefault(ticket, []).append(_waiting_line(name, identifier, asks.get(identifier), tools))
    for ask in asks.values():
        if ask.answer is None and ask.fields["status"] == "open":
            _ensure_batch(project, ask.id)
    return settled


def _answer_from_mark(ask, item):
    if item["mark"] == DECLINE:
        return GO_WITHOUT if (item.get("note") or "").strip().lower().startswith("go without") else NOT_NOW
    if ask.licensed:
        return where(item.get("note"))
    return INSTALL


def _waiting_line(name, identifier, ask, tools):
    if ask is None or ask.answer is None:
        return "%s is not installed; decision ticket %d asks about it" % (name, identifier)
    picked = choice(ask.answer[1], ask.licensed)
    if picked == NOT_NOW:
        return "%s is not installed; decision ticket %d was answered %s" % (name, identifier, NOT_NOW)
    return "%s is being installed (decision ticket %d)" % (name, identifier)


def _launch(project, runner, spec):
    """Write one job file of a `software` decision and launch it now; the conductor polls it like any job."""
    from wayline import resources

    [record] = resources.add_jobs(project, spec, ticket=spec["ticket"], tools=Tools(record={}))
    return runner.launch(resources.spec_from_record(record))


def _pending(project, ask, kind):
    """A job file of this ask that was written and never launched (a crash between the two): it is launched rather than written again."""
    folder = Path(project) / "research" / "jobs"
    launched = {job for _, job in ask.jobs}
    for path in sorted(folder.glob(_job_prefix(ask.id, kind, ask.name) + "*.json")):
        record = toolbox.read_json_file(path) or {}
        if record.get("status") == "pending" and record.get("id") not in launched:
            return record
    return None


def _next_job_id(project, ask, kind):
    folder = Path(project) / "research" / "jobs"
    numbers = [int(path.stem.rsplit("-", 1)[-1]) for path in folder.glob(_job_prefix(ask.id, kind, ask.name) + "*.json")
               if path.stem.rsplit("-", 1)[-1].isdigit()]
    return "%s%d" % (_job_prefix(ask.id, kind, ask.name), max(numbers, default=0) + 1)


def _job_env():
    return {"WAYLINE_HOME": os.environ["WAYLINE_HOME"]} if os.environ.get("WAYLINE_HOME") else {}


def _attempts(ask, kind):
    """`[(job, ended)]` of this ask's jobs of `kind` since its answer, `ended` None while the job runs."""
    return [(job, ask.ended.get(job)) for _, job in ask.jobs if job.startswith(_job_prefix(ask.id, kind, ask.name))]


def _failure(ask, attempt, ended):
    outcome = ask.outcomes.get(attempt)
    if outcome is not None and outcome[0] == "failed" and outcome[2]:
        return outcome[2]
    if ended[1]:
        return "the install job %s" % ended[1]
    return "the install job exited %s and %s is still not recorded" % (ended[0], ask.name)


def _run_install(project, ask, runner, settled, said, harness_root, change=False):
    """Launch the next install job of an Install answer, or the pending one; the decision's own job, never a worker's."""
    from wayline import HARNESS_ROOT
    from wayline import resources

    pending = _pending(project, ask, INSTALL_JOB)
    if pending is not None:
        try:
            runner.launch(resources.spec_from_record(pending))
        except (resources.JobError, OSError, ValueError) as failure:
            said("  decision ticket %d: the install job %s could not be launched: %s" % (ask.id, pending["id"], failure))
            return
        settled.in_flight.append(pending["id"])
        return
    attempt = len(_attempts(ask, INSTALL_JOB)) + 1
    job = _next_job_id(project, ask, INSTALL_JOB)
    command = [str(Path(harness_root or HARNESS_ROOT) / "bin" / "wayline"), "tools", "install", ask.name, "--project", str(project),
               "--decision", str(ask.id), "--attempt", str(attempt)] + (["--change"] if change else [])
    try:
        _launch(project, runner, {"id": job, "ticket": ask.id, "command": command, "cwd": str(project), "env": _job_env(),
                                  "wallclock_minutes": JOB_WALLCLOCK_MINUTES})
    except (ValueError, OSError) as failure:
        said("  decision ticket %d: the install job %s could not be launched: %s" % (ask.id, job, failure))
        return
    settled.in_flight.append(job)
    said("  decision ticket %d: installing %s, attempt %d of %d, as job %s" % (ask.id, ask.name, attempt, ATTEMPTS, job))


def _act_on_install(project, ask, runner, tools, settled, said, notify, harness_root):
    if _installed(tools.entry(ask.name)):
        return
    attempts = _attempts(ask, INSTALL_JOB)
    running = [job for job, ended in attempts if ended is None]
    if running:
        settled.in_flight.extend(running)
        return
    if len(attempts) < ATTEMPTS:
        _run_install(project, ask, runner, settled, said, harness_root)
        return
    why = "installing %s failed %d times; the last: %s" % (ask.name, len(attempts), _failure(ask, len(attempts), attempts[-1][1]))
    if reopen(project, ask.id, why, notify=notify):
        said("  decision ticket %d is asked again: %s" % (ask.id, why))


def _act_on_licensed(project, ask, answer, runner, tools, settled, said, notify):
    from wayline import resources
    from wayline.ledger import Ledger, TOOL_INSTALLED

    path = where(answer)
    entry = tools.entry(ask.name)
    if entry and entry.get("executable") == path and _installed(entry):
        return
    if path is None or not os.path.isfile(path):
        why = "%s is not at %s; say where the owner installed it by the absolute path of its executable" % (ask.name, path) if path \
            else "the answer names no absolute path to %s" % ask.name
        if reopen(project, ask.id, why, notify=notify):
            said("  decision ticket %d is asked again: %s" % (ask.id, why))
        return
    checks = _attempts(ask, CHECK_JOB)
    if not checks:
        pending = _pending(project, ask, CHECK_JOB)
        try:
            if pending is not None:
                runner.launch(resources.spec_from_record(pending))
                job = pending["id"]
            else:
                job = _next_job_id(project, ask, CHECK_JOB)
                _launch(project, runner, {"id": job, "ticket": ask.id, "command": [path] + list(LICENSED[ask.name]), "cwd": str(project),
                                          "wallclock_minutes": LICENSED_CHECK_TIMEOUT_S // 60})
        except (ValueError, OSError) as failure:
            said("  decision ticket %d: the check of %s could not be launched: %s" % (ask.id, ask.name, failure))
            return
        settled.in_flight.append(job)
        said("  decision ticket %d: checking %s at %s with `%s -batch \"ver\"`, as job %s" % (ask.id, ask.name, path, ask.name, job))
        return
    job, ended = checks[-1]
    if ended is None:
        settled.in_flight.append(job)
        return
    record = runner.read(job) or {}
    text = resources.log_tail(record.get("log") or "")
    ledger = Ledger(project)
    try:
        if ended[0] != 0:
            raise ToolsError("the check `%s -batch \"ver\"` failed (%s)%s" % (
                ask.name, ended[1] or "exit %s" % ended[0], (": " + text.strip().splitlines()[-1][:240]) if text.strip() else ""))
        entry = record_licensed(ask.name, path, root=tools.root, output=text)
    except ToolsError as failure:
        ledger.append_event(TOOL_INSTALLED, {"ticket": ask.id, "name": ask.name, "outcome": "failed", "version": None, "attempt": len(checks),
                                             "reason": str(failure)}, ticket=ask.id)
        if reopen(project, ask.id, str(failure), notify=notify):
            said("  decision ticket %d is asked again: %s" % (ask.id, failure))
        return
    ledger.append_event(TOOL_INSTALLED, {"ticket": ask.id, "name": ask.name, "outcome": "recorded", "version": entry["version"],
                                         "attempt": len(checks), "reason": None}, ticket=ask.id)
    tools.record = toolbox.read_json_file(tools.root / toolbox.TOOLS_JSON) or {}
    said("  decision ticket %d: %s %s recorded at %s (installer: owner, %d toolboxes)" % (
        ask.id, ask.name, entry["version"], path, len(entry.get("toolboxes") or {})))


def _act_on_gap(project, ask, picked, decided_by, runner, settled, said, notify, harness_root, fields_by_id):
    if picked == NOT_NOW:
        return
    if picked == INSTALL:
        if decided_by != "human":
            said("  decision ticket %d: changing the installed %s is the owner's word alone; the %s's answer is not acted on"
                 % (ask.id, ask.name, decided_by))
            return
        if not any(outcome[0] == "installed" for outcome in ask.outcomes.values()):
            attempts = _attempts(ask, INSTALL_JOB)
            running = [job for job, ended in attempts if ended is None]
            if running:
                settled.in_flight.extend(running)
                return
            if len(attempts) < ATTEMPTS:
                _run_install(project, ask, runner, settled, said, harness_root, change=True)
                return
            why = "changing %s failed %d times; the last: %s" % (ask.name, len(attempts), _failure(ask, len(attempts), attempts[-1][1]))
            if reopen(project, ask.id, why, notify=notify):
                said("  decision ticket %d is asked again: %s" % (ask.id, why))
            return
    _reopen_blocked(project, ask, fields_by_id, said)


def _reopen_blocked(project, ask, fields_by_id, said):
    """The tickets a gap blocked go back to open once the owner changed the tool or said to go without it."""
    from wayline.ledger import TICKET_RERUN, Ledger
    from wayline.tickets import filename, read_ticket, tickets_dir, write_ticket

    ledger = Ledger(project)
    for fields in sorted(fields_by_id.values(), key=lambda item: item["id"]):
        if fields["status"] != "blocked" or ask.id not in fields["blocked_by"]:
            continue
        with ledger.lock():
            current, body = read_ticket(tickets_dir(project) / filename(fields))
            if current["status"] != "blocked":
                continue
            ledger.append_event(TICKET_RERUN, {"ticket": current["id"], "by": "code"}, ticket=current["id"])
            write_ticket(ledger, dict(current, status="open"), body)
        said("  ticket %d is open again: decision ticket %d answered its gap in %s" % (fields["id"], ask.id, ask.name))


def open_gap(project, ticket, name, gap, notify=None):
    """The decision a worker's gap opens: whether to change the installed tool, pausing the blocked ticket and what waits on it."""
    fields = {item["id"]: item for item in _read_tickets(project)}
    dependents = sorted(item["id"] for item in fields.values() if ticket in item["blocked_by"])
    return open_ask(project, name, [ticket] + dependents, notify=notify, gap=gap)


def setup_question(project, tools=None, root=None, run=run_tool):
    """The one setup question under `autonomous`: every tool the planned work needs and does not have, with its route and sizes.

    Returns `{question, tools: [{name, tickets, route, download_bytes, disk_bytes, licensed}]}`, or None when the
    planned work needs nothing this machine lacks. The setup conversation asks it once; after setup the decider
    answers each tool's `software` decision.
    """
    tools = tools if tools is not None else Tools(root)
    needed = {}
    for fields in _read_tickets(project):
        if fields["kind"] == "decision" or fields["status"] not in ("open", "failed"):
            continue
        for name in fields.get("software") or []:
            if not _installed(tools.entry(name)) and not is_harness_tool(name) and known_tool(name):
                needed.setdefault(name, []).append(fields["id"])
    if not needed:
        return None
    listed, lines = [], []
    for name, waiting in sorted(needed.items()):
        try:
            dry = dry_run(name, root=tools.root, run=run)
        except ToolsError:
            dry = {"route": None, "download_bytes": None, "disk_bytes": None}
        listed.append({"name": name, "tickets": sorted(waiting), "route": dry.get("route"), "download_bytes": dry.get("download_bytes"),
                       "disk_bytes": dry.get("disk_bytes"), "licensed": name in LICENSED})
        if name in LICENSED:
            lines.append("- %s (licensed: you install it and say where; %s)" % (name, _named(sorted(waiting))))
        else:
            lines.append("- %s through %s, %s to download, about %s on disk (%s)" % (
                name, dry.get("route") or "its route", _mib(dry.get("download_bytes")), _mib(dry.get("disk_bytes")), _named(sorted(waiting))))
    question = ("The planned work needs software this machine does not have. Install each free tool now (yes, or name the ones to "
                "leave), and say where any licensed software is installed:\n" + "\n".join(lines))
    return {"question": question, "tools": listed}


# --- the verbs ----------------------------------------------------------------------------------------


def _project_for(explicit, required):
    from wayline.project import ProjectError, find_project

    named = explicit or os.environ.get("WAYLINE_PROJECT")
    try:
        return find_project(named)
    except ProjectError:
        if required:
            raise
        return None


def yes_from_decision(project, identifier, name, change=False):
    """The yes a `--decision` names: a `software` decision about this tool whose answer is Install; raises `ToolsError` otherwise.

    A change to an installed tool also needs the answer to be the owner's.
    """
    from wayline import replay
    from wayline.ledger import Ledger

    fields = {ticket["id"]: ticket for ticket in _read_tickets(project)}.get(identifier)
    found = asked(fields) if fields else None
    if found is None or found[0] != name:
        raise ToolsError("ticket %s of %s is no software decision about %s" % (identifier, project, name))
    if change and not found[1]:
        raise ToolsError("decision ticket %d asks whether to install %s, not to change it; changing an installed tool is the owner's "
                         "word alone" % (identifier, name))
    events, _ = Ledger(project).read_events()
    answered = replay.replay(events).answers.get(identifier)
    if answered is None or choice(answered.get("answer"), name in LICENSED) != INSTALL:
        raise ToolsError("decision ticket %d is not answered %s" % (identifier, INSTALL))
    if change and answered.get("decided_by") != "human":
        raise ToolsError("decision ticket %d was answered by the %s; changing an installed tool is the owner's word alone"
                         % (identifier, answered.get("decided_by")))
    return answered


def journal_install(project, identifier, name, outcome, version=None, attempt=None, reason=None):
    """`tool_installed` in the project's journal, when there is a project to journal it in."""
    from wayline.ledger import TOOL_INSTALLED, Ledger

    if project is None:
        return None
    return Ledger(project).append_event(TOOL_INSTALLED, {"ticket": identifier, "name": name, "outcome": outcome, "version": version,
                                                         "attempt": attempt, "reason": reason}, ticket=identifier)


def _entry_line(name, entry):
    return "%-20s %-26s %-8s %s" % (name, entry.get("version") or "-", entry.get("installer") or "-", entry.get("executable") or "-")


def install_command(name, options, root=None, run=run_tool, say=None):
    """`wayline tools install <octave|r|julia|matlab> ...`: a project's tool after a yes, or licensed software where the owner put it."""
    from wayline import real_backend
    from wayline.project import ProjectError

    say = say or (lambda line: print(line, file=sys.stderr))
    root = Path(root) if root is not None else tools_home()
    if options.dry_run:
        try:
            dry = dry_run(name, root=root, run=run)
        except ToolsError as failure:
            print("wayline tools install: %s" % failure, file=sys.stderr)
            return 1
        print("%s  %s" % (name, _route_line(name, dry)))
        for line in _size_lines(name, dry, None):
            print("  " + line)
        return 0
    try:
        project = _project_for(options.project, required=options.decision is not None)
    except ProjectError as failure:
        print("wayline tools install: %s" % failure, file=sys.stderr)
        return 2
    if name in LICENSED:
        if not options.at:
            print("wayline tools install: %s is licensed software: the owner installs it and says where (wayline tools install %s --at "
                  "<path to its executable>); code only records it" % (name, name), file=sys.stderr)
            return 2
        try:
            entry = record_licensed(name, options.at, root=root, run=run)
        except ToolsError as failure:
            journal_install(project, options.decision, name, "failed", attempt=options.attempt, reason=str(failure))
            print("wayline tools install: %s" % failure, file=sys.stderr)
            return 1
        journal_install(project, options.decision, name, "recorded", entry["version"], options.attempt)
        print(_entry_line(name, entry))
        return 0
    if options.decision is None and not options.yes:
        print("wayline tools install: %s is a project's tool, which installs only after a yes: its software decision answered %s "
              "(--decision <id>), or the owner's yes in the setup conversation (--yes)" % (name, INSTALL), file=sys.stderr)
        return 2
    try:
        if options.decision is not None:
            yes_from_decision(project, options.decision, name, change=options.change)
        if run is run_tool:
            real_backend("the network (a project's tool)")
        entry = install_project_tool(name, root=root, run=run, echo=say, change=options.change,
                                     by=OWNER if options.change else None)
    except ToolsError as failure:
        journal_install(project, options.decision, name, "failed", attempt=options.attempt, reason=str(failure))
        print("wayline tools install: %s" % failure, file=sys.stderr)
        return 1
    journal_install(project, options.decision, name, "installed", entry.get("version"), options.attempt)
    print(_entry_line(name, entry))
    return 0


def _code_dir(project):
    """Where a lock goes: the worktree's `code/` when the verb runs inside one of the project's worktrees, else the project's."""
    here = Path.cwd().resolve()
    worktrees = (Path(project) / ".worktrees").resolve()
    if worktrees in here.parents:
        return worktrees / here.relative_to(worktrees).parts[0] / CODE
    return Path(project) / CODE


def package_command(args, root=None, run=run_tool):
    """`wayline tools package <python|r|julia|octave> <name>... [--project <path>] [--code <dir>]`: a project's packages, with no ask."""
    import argparse

    from wayline import real_backend
    from wayline.cli import parse_args
    from wayline.project import ProjectError

    parser = argparse.ArgumentParser(prog="wayline tools package",
                                     description="install a project's packages into its own environment, with no ask, locked under code/")
    parser.add_argument("language", choices=list(LANGUAGES))
    parser.add_argument("names", nargs="+", help="the packages, each a name or a name with one version pin (six==1.17.0)")
    parser.add_argument("--project", help="the project; WAYLINE_PROJECT or the active one by default")
    parser.add_argument("--code", help="where the lock goes; the worktree's code/ inside a worktree, else the project's")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = _project_for(options.project, required=True)
        if run is run_tool:
            real_backend("the network (a project's packages)")
        done = install_packages(project, options.language, options.names, code_dir=options.code or _code_dir(project), root=root, run=run)
    except (ToolsError, ProjectError) as failure:
        print("wayline tools package: %s" % failure, file=sys.stderr)
        return 1
    print("%s packages %s into %s, locked in %s" % (done["language"], " ".join(done["packages"]), done["environment"], done["lock"]))
    return 0

