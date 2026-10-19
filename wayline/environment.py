"""Moving a project's environment: `wayline switch --environment shared|conda|venv|container` (Implementation Decision 17; ticket 83).

The environment is where a project's tools and packages live and its jobs run. `harness.json.environment`
is one of four, and a project without the key is `shared`:

- `shared`: the tools as `~/.wayline/tools/tools.json` records them and the project's own packages
  (ticket 82: `<project>/.venv`, the R library, the Julia environment `code/`, Octave Forge);
- `conda`: one prefix at `<project>/.wayline/env` holding the project's tools and packages;
- `venv`: one project venv at `<project>/.wayline/env-venv`, built through uv, holding the project's
  Python and its packages; a venv holds nothing but Python, so the project's other tools stay the
  shared ones;
- `container`: one Singularity image at `<project>/.wayline/env.sif`, built without root through a
  sandbox from `docker://` and micromamba (measured live on the workstation, `docs/verification/m8.md`),
  with Docker used only where the account reaches it: then the base image comes through the daemon.

A move always goes in three steps: code builds the new environment from the locks ticket 82 writes
(each conda tool's explicit export under `~/.wayline/tools/locks/`, `code/requirements.lock`,
`code/renv.lock`, `code/Manifest.toml`, `code/octave-packages.lock`), runs each recorded tool's
version check inside it (and compares the Python and Octave packages with their locks), and only
when every check passes writes `harness.json` and journals `control environment`. A failed build or
check removes what it half built, leaves the project where it was, and says which step failed. Past
results stand: nothing a job already ran is touched, and a job launched before the switch keeps the
command it was resolved to, so it finishes where it started. MATLAB is never rebuilt: it stays the
owner's install on the host, bound into the image. The decider never moves an environment (`by` is
never `decider`), and no decision class names it.

What each environment holds is recorded in `<project>/.wayline/env.json`, one record per kind, and
`resolve` reads it: `wayline job add` and `wayline tools run` resolve a tool through the project's
environment, and a job that names no tool runs inside it too (`inside`). The harness's own tools and
the machine's (pandoc, the converters, git, LaTeX) are the harness's, not the project's, and always
run as `tools.json` records them.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import sys
from collections import namedtuple
from pathlib import Path

from wayline import tools as toolbox
from wayline.ledger import now_ts
from wayline.tools import INSTALL_TIMEOUT_S, TOOL_TIMEOUT_S, Tools, ToolsError, failure_line, parse_version, run_tool

__all__ = [
    "SHARED", "CONDA", "VENV", "CONTAINER", "KINDS", "BASE_IMAGE", "IN_IMAGE", "MoveError", "setting", "place", "records",
    "carried", "move", "move_in_progress", "resolve", "inside", "Resolved", "switch_command", "PYTHON",
]

SHARED, CONDA, VENV, CONTAINER = "shared", "conda", "venv", "container"
KINDS = (SHARED, CONDA, VENV, CONTAINER)
PYTHON = "python"
WAYLINE_DIR = ".wayline"
PLACES = {CONDA: "env", VENV: "env-venv", CONTAINER: "env.sif"}
RECORD = "env.json"
MOVING = "env-move.json"
MOVE_LOCK = "env.lock"
SANDBOX = "env.sandbox"
SCRATCH = "env-tmp"
JULIA_DEPOT = "env-julia-depot"  # the writable depot a containerized Julia compiles into, before the image's own
# The base the image is built on: glibc, which conda-forge's packages need, and nothing else.
BASE_IMAGE = "debian:bookworm-slim"
IN_IMAGE = "/opt/env"           # the prefix inside the image
STAGE = "/opt/wayline"          # where the build stages the locks and the package cache inside the sandbox
CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")  # debian-slim has none, and micromamba refuses to fetch without one
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
LOCKS = {PYTHON: "requirements.lock", "r": "renv.lock", "julia": "Manifest.toml", "octave": "octave-packages.lock"}
CONDA_TOOLS = ("octave", "r")   # a project's tools whose lock is an explicit conda export (ticket 82)
BOOTSTRAP = ("pip", "setuptools", "wheel")  # what a conda-forge Python holds beside the lock: its own installers
# The image holds no locale but the C one glibc builds in, so the host's LANG would warn on every start (measured live).
IMAGE_ENV = {"LC_ALL": "C.UTF-8"}
PROJECT_NAMES = ("octave", "r", "rscript", "julia")
LICENSED = ("matlab",)
_RESTORE = ("renv::restore(lockfile = Sys.getenv('WAYLINE_LOCK'), library = Sys.getenv('WAYLINE_R_LIBRARY'), "
            "prompt = FALSE)")
_INSTANTIATE = "using Pkg; Pkg.instantiate()"
_OCTAVE_INSTALL = "pkg('install', '-forge', '-global', %s)"
_OCTAVE_LIST = "pkg('list')"

Resolved = namedtuple("Resolved", "argv env environment entry")
"""How one tool runs in the project's environment: the argv to put before its arguments, its environment
variables, the environment's kind, and what `tools.json` records of it (versions and locks are the shared ones)."""


class MoveError(RuntimeError):
    """A move that did not happen: the step that failed, and why. The project is where it was."""

    def __init__(self, kind, step, why, stays=SHARED):
        self.kind, self.step, self.why = kind, step, why
        super().__init__("the move to %s failed at `%s`: %s; the project stays in %s" % (kind, step, why, stays))


# --- where things are -----------------------------------------------------------------------------------


def setting(project, harness=None):
    """The project's environment: `harness.json.environment`, `shared` for a project without the key."""
    if harness is None:
        from wayline.project import HARNESS_JSON, read_harness
        if not (Path(project) / HARNESS_JSON).exists():
            return SHARED  # a folder the job runner serves without a harness.json, as a bare test project is
        harness = read_harness(project)
    value = (harness or {}).get("environment")
    return value if value in KINDS else SHARED


def place(project, kind):
    """Where an environment of `kind` lives in the project: the conda prefix, the venv, or the image; None for `shared`."""
    return Path(project) / WAYLINE_DIR / PLACES[kind] if kind in PLACES else None


def _record_path(project):
    return Path(project) / WAYLINE_DIR / RECORD


def records(project):
    """`<project>/.wayline/env.json`: what each environment built holds, by kind."""
    value = toolbox.read_json_file(_record_path(project))
    return value if isinstance(value, dict) else {}


def _write_records(project, value):
    path = _record_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    toolbox._write_record(path, value)


def _installed(entry):
    return bool(entry and entry.get("executable") and Path(entry["executable"]).exists())


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _code(project):
    return Path(project) / "code"


def python_version(project):
    """The Python a move pins: the major and minor of the project's `.venv` (its `pyvenv.cfg`), else this interpreter's.

    The lock pins the packages, not the interpreter, so the minor version is what every environment keeps.
    """
    cfg = Path(project) / ".venv" / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ("version_info", "version"):
                parts = value.strip().split(".")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    return "%s.%s" % (parts[0], parts[1])
    except OSError:
        pass
    return "%d.%d" % sys.version_info[:2]


def carried(project, tools, kind=None):
    """What a move carries into the new environment: the project's tools it names and `tools.json` records, and Python.

    A project names a tool by a ticket's `software` or by a package lock under `code/` (ticket 82).
    Python is carried when the project locks Python packages or keeps a `.venv`, and always into a venv.
    A package lock whose tool is not recorded is refused: the move could not rebuild what it locks.
    """
    from wayline import software
    from wayline.tickets import read_tickets

    named = set()
    for fields in read_tickets(project):
        for name in fields.get("software") or []:
            named.add(software.provider(name) or name)
    code = _code(project)
    for language, lock in LOCKS.items():
        if language != PYTHON and (code / lock).is_file():
            if not _installed(tools.entry(language)):
                raise MoveError(kind or "?", "read the locks", "code/%s locks %s's packages, and %s is not recorded in %s"
                                % (lock, language, language, tools.root / toolbox.TOOLS_JSON))
            named.add(language)
    if "r" in named:
        named.add("rscript")
    names = [name for name in sorted(named) if (name in PROJECT_NAMES or name in LICENSED) and _installed(tools.entry(name))]
    if kind == VENV or (code / LOCKS[PYTHON]).is_file() or (Path(project) / ".venv" / "bin" / "python").exists():
        names.append(PYTHON)
    return names


# --- the build --------------------------------------------------------------------------------------------


class _Build:
    """One move's build: runs each step through the tool runner, and names the step that failed."""

    def __init__(self, project, kind, tools, run, which, echo):
        self.project, self.kind, self.tools, self.run, self.which = Path(project), kind, tools, run, which
        self.echo = echo or (lambda line: None)
        self.names = carried(project, tools, kind)
        self.python = python_version(project)
        self.record = {"kind": kind, "built": None, "place": None, "image": None, "runner": None, "binds": [], "base": None,
                       "tools": {}}

    def fail(self, step, why):
        raise MoveError(self.kind, step, why)

    def step(self, step, argv, env=None, timeout=INSTALL_TIMEOUT_S):
        self.echo("%s: %s" % (step, " ".join(str(part) for part in argv)))
        done = self.run(argv, timeout=timeout, env=env)
        if done.returncode != 0:
            self.fail(step, failure_line(done))
        return done

    def entry(self, name):
        return self.tools.entry(name) or {}

    def lock_of(self, name):
        """A conda tool's explicit lock, checked against the digest `tools.json` recorded for it."""
        lock = self.entry(name).get("lock") or {}
        path = lock.get("path") if isinstance(lock, dict) else None
        if not path or not Path(path).is_file():
            self.fail("build %s" % name, "%s has no lock recorded in %s" % (name, self.tools.root / toolbox.TOOLS_JSON))
        if lock.get("sha256") and _sha256(path) != lock["sha256"]:
            self.fail("build %s" % name, "its lock %s changed since %s was recorded" % (path, name))
        return Path(path)

    def micromamba(self):
        entry = self.entry("micromamba")
        if not _installed(entry):
            self.fail("build", "micromamba, the harness's tool, is not recorded (wayline tools install micromamba)")
        return entry

    def uv(self):
        entry = self.entry("uv")
        if not _installed(entry):
            self.fail("build python", "uv, the harness's tool, is not recorded (wayline tools install uv)")
        return entry

    # -- conda ---------------------------------------------------------------------------------------------

    def conda(self):
        prefix = place(self.project, CONDA)
        self.record["place"] = str(prefix)
        micromamba = self.micromamba()
        verb = ["create"]

        def mamba(step, specs):
            argv = [micromamba["executable"], verb[0], "-y", "-p", str(prefix)] + specs
            verb[0] = "install"
            self.step(step, argv, env=micromamba.get("env") or None)

        for name in CONDA_TOOLS:
            if name in self.names:
                mamba("build %s" % name, ["--file", str(self.lock_of(name))])
        if PYTHON in self.names:
            mamba("build python", ["-c", toolbox.CONDA_FORGE, "--override-channels", "python=%s" % self.python])
        prefix.mkdir(parents=True, exist_ok=True)
        for name, program in (("octave", "octave"), ("r", "R"), ("rscript", "Rscript")):
            if name in self.names:
                self.record["tools"][name] = {"executable": str(prefix / "bin" / program), "env": {}}
        if PYTHON in self.names:
            self.record["tools"][PYTHON] = {"executable": str(prefix / "bin" / "python"), "env": {}}
            self.python_packages(str(prefix / "bin" / "python"))
        if "julia" in self.names:
            folder = self.copy_julia(prefix)
            depot = prefix / "julia-depot"
            self.record["tools"]["julia"] = {"executable": str(folder / "bin" / "julia"), "env": {"JULIA_DEPOT_PATH": str(depot)}}
        self.packages(lambda argv: argv, lambda name: self.record["tools"][name])
        self.licensed()

    def copy_julia(self, under, inner=None):
        """Julia's tree, as its install checked it against the published digest, copied in: the same build, not a new download."""
        source = Path(self.entry("julia")["executable"]).parent.parent
        target = Path(under) / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, symlinks=True)
        return Path(inner) / source.name if inner else target

    def python_packages(self, python, wrap=None, env=None, lock=None):
        lock = lock or _code(self.project) / LOCKS[PYTHON]
        if not (_code(self.project) / LOCKS[PYTHON]).is_file():
            return
        uv = self.uv()
        executable = "/usr/local/bin/uv" if wrap else uv["executable"]
        argv = [executable, "pip", "sync", "--python", python, str(lock)]
        self.step("build python packages", wrap(argv) if wrap else argv, env=env if wrap else (uv.get("env") or None))

    def packages(self, wrap, tool, env=None, code=None):
        """Each language's packages restored from its lock inside the new environment: R through renv, Julia through Pkg, Octave Forge."""
        code = Path(code) if code else _code(self.project)
        if "r" in self.names and (_code(self.project) / LOCKS["r"]).is_file():
            rscript = tool("rscript")
            library = str(Path(rscript["executable"]).parent.parent / "lib" / "R" / "library")
            variables = dict(env or {}, WAYLINE_LOCK=str(code / LOCKS["r"]), WAYLINE_R_LIBRARY=library)
            self.step("build r packages", wrap([rscript["executable"], "-e", _RESTORE]), env=self._env(variables, wrap))
        if "julia" in self.names and (_code(self.project) / LOCKS["julia"]).is_file():
            julia = tool("julia")
            variables = dict(env or {}, **(julia.get("build_env") or julia["env"]))
            self.step("build julia packages", wrap([julia["executable"], "--project=%s" % code, "-e", _INSTANTIATE]),
                      env=self._env(variables, wrap))
        if "octave" in self.names and (_code(self.project) / LOCKS["octave"]).is_file():
            names = sorted(_octave_rows((_code(self.project) / LOCKS["octave"]).read_bytes()))
            if names:
                octave = tool("octave")
                self.step("build octave packages", wrap([octave["executable"], "--no-gui", "--eval",
                                                         _OCTAVE_INSTALL % ", ".join("'%s'" % name for name in names)]),
                          env=self._env(dict(env or {}), wrap))

    def _env(self, variables, wrap):
        if self.kind == CONTAINER:
            return {"SINGULARITYENV_%s" % key: value for key, value in variables.items()} or None
        return variables or None

    def licensed(self, binds=False):
        """Licensed software stays the owner's install on the host: never rebuilt, bound into an image."""
        for name in LICENSED:
            if name in self.names:
                executable = self.entry(name)["executable"]
                self.record["tools"][name] = {"executable": executable, "env": dict(self.entry(name).get("env") or {})}
                if binds:
                    self.record["binds"].append(str(Path(executable).parent.parent))

    # -- venv ----------------------------------------------------------------------------------------------

    def venv(self):
        folder = place(self.project, VENV)
        self.record["place"] = str(folder)
        uv = self.uv()
        self.step("build python", [uv["executable"], "venv", "--python", self.python, str(folder)], env=uv.get("env") or None)
        python = folder / "bin" / "python"
        self.record["tools"][PYTHON] = {"executable": str(python), "env": {}}
        self.python_packages(str(python))
        from wayline import software

        for name in self.names:  # a venv holds only Python: the project's other tools stay the shared ones
            if name != PYTHON and name not in LICENSED:
                entry = self.entry(name)
                self.record["tools"][name] = {"executable": entry["executable"],
                                              "env": dict(entry.get("env") or {}, **software.project_env(self.project, name))}
        self.licensed()

    # -- container -----------------------------------------------------------------------------------------

    def runner(self):
        entry = self.tools.entry("singularity")
        if not _installed(entry):
            try:
                entry = toolbox.record_system_tool("singularity", self.tools.root, self.run, self.which)
            except ToolsError as failure:
                self.fail("build base image", "%s; a container needs SingularityCE, which this machine's owner installs" % failure)
            self.tools.record = toolbox.read_json_file(self.tools.root / toolbox.TOOLS_JSON) or {}
        return entry["executable"]

    def docker(self):
        """Docker's absolute path when this account reaches its daemon, else None: Docker is used only then."""
        found = self.which("docker")
        if not found:
            return None
        done = self.run([found, "info", "--format", "{{.ServerVersion}}"], timeout=TOOL_TIMEOUT_S)
        return found if done.returncode == 0 else None

    def container(self):
        singularity = self.runner()
        wayline = self.project / WAYLINE_DIR
        sandbox, scratch = wayline / SANDBOX, wayline / SCRATCH
        image, building = place(self.project, CONTAINER), wayline / (PLACES[CONTAINER] + ".new")
        for leftover in (sandbox, scratch):
            if leftover.exists():
                shutil.rmtree(leftover)
        scratch.mkdir(parents=True)
        cache = self.tools.root / "singularity" / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        build_env = {"SINGULARITY_CACHEDIR": str(cache), "SINGULARITY_TMPDIR": str(scratch)}
        try:
            docker = self.docker()
            if docker:
                self.step("build base image", [docker, "pull", BASE_IMAGE])
                source = "docker-daemon://%s" % BASE_IMAGE
            else:
                source = "docker://%s" % BASE_IMAGE
            self.record["base"] = source
            self.step("build base image", [singularity, "build", "--sandbox", str(sandbox), source], env=build_env)
            self.stage(sandbox)
            pkgs = Path((self.micromamba().get("env") or {}).get("CONDA_PKGS_DIRS") or self.tools.root / "mamba" / "pkgs")
            pkgs.mkdir(parents=True, exist_ok=True)

            def wrap(argv):
                return [singularity, "exec", "--writable", "--containall", "--bind", "%s:%s/pkgs" % (pkgs, STAGE), str(sandbox)] + list(argv)

            inner_env = {"MAMBA_ROOT_PREFIX": STAGE + "/mamba", "CONDA_PKGS_DIRS": STAGE + "/pkgs", "UV_CACHE_DIR": STAGE + "/uv-cache",
                         "HOME": STAGE + "/home"}
            verb = ["create"]

            def mamba(step, specs):
                argv = ["/usr/local/bin/micromamba", verb[0], "-y", "-p", IN_IMAGE] + specs
                verb[0] = "install"
                self.step(step, wrap(argv), env=self._env(inner_env, wrap))

            for name in CONDA_TOOLS:
                if name in self.names:
                    mamba("build %s" % name, ["--file", "%s/locks/%s.txt" % (STAGE, name)])
            if PYTHON in self.names:
                mamba("build python", ["-c", toolbox.CONDA_FORGE, "--override-channels", "python=%s" % self.python])
            (sandbox / IN_IMAGE.lstrip("/")).mkdir(parents=True, exist_ok=True)
            for name, program in (("octave", "octave"), ("r", "R"), ("rscript", "Rscript")):
                if name in self.names:
                    self.record["tools"][name] = {"executable": "%s/bin/%s" % (IN_IMAGE, program), "env": {}}
            if PYTHON in self.names:
                self.record["tools"][PYTHON] = {"executable": IN_IMAGE + "/bin/python", "env": {}}
                self.python_packages(IN_IMAGE + "/bin/python", wrap=wrap, env=self._env(inner_env, wrap),
                                     lock="%s/locks/%s" % (STAGE, LOCKS[PYTHON]))
            if "julia" in self.names:
                folder = self.copy_julia(sandbox / "opt", inner="/opt")
                depot = self.project / WAYLINE_DIR / JULIA_DEPOT
                self.record["tools"]["julia"] = {"executable": str(folder / "bin" / "julia"),
                                                 "env": {"JULIA_DEPOT_PATH": "%s:/opt/julia-depot" % depot},
                                                 "build_env": {"JULIA_DEPOT_PATH": "/opt/julia-depot"}}
            self.packages(wrap, lambda name: self.record["tools"][name], env=inner_env, code=STAGE + "/code")
            if "julia" in self.record["tools"]:
                self.record["tools"]["julia"].pop("build_env", None)
            self.licensed(binds=True)
            for name, tool in self.record["tools"].items():
                if name not in LICENSED:
                    tool["env"] = dict(IMAGE_ENV, **tool["env"])
            for staged in ("pkgs", "uv-cache", "mamba/pkgs", "home"):
                shutil.rmtree(sandbox / STAGE.lstrip("/") / staged, ignore_errors=True)
            self.step("build image", [singularity, "build", str(building), str(sandbox)], env=build_env)
            os.replace(building, image)  # a job still running the old image keeps it open; the next ones run the new
        finally:
            for leftover in (sandbox, scratch, building):
                if leftover.is_dir():
                    shutil.rmtree(leftover, ignore_errors=True)
                elif leftover.exists():
                    leftover.unlink()
        self.record.update({"place": str(image), "image": str(image), "runner": singularity})

    def stage(self, sandbox):
        """What the build needs inside the sandbox: micromamba and uv, the CA bundle, the locks, and the package locks of `code/`."""
        stage = sandbox / STAGE.lstrip("/")
        for folder in ("locks", "pkgs", "code", "home"):
            (stage / folder).mkdir(parents=True, exist_ok=True)
        binaries = sandbox / "usr" / "local" / "bin"
        binaries.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.micromamba()["executable"], binaries / "micromamba")
        if PYTHON in self.names and (_code(self.project) / LOCKS[PYTHON]).is_file():
            shutil.copy2(self.uv()["executable"], binaries / "uv")
            shutil.copy2(_code(self.project) / LOCKS[PYTHON], stage / "locks" / LOCKS[PYTHON])
        if CA_BUNDLE.is_file():
            (sandbox / "etc" / "ssl" / "certs").mkdir(parents=True, exist_ok=True)
            shutil.copy2(CA_BUNDLE, sandbox / "etc" / "ssl" / "certs" / CA_BUNDLE.name)
        for name in CONDA_TOOLS:
            if name in self.names:
                shutil.copy2(self.lock_of(name), stage / "locks" / ("%s.txt" % name))
        for language in ("r", "julia", "octave"):
            if language in self.names:
                for lock in (LOCKS[language],) + (("Project.toml",) if language == "julia" else ()):
                    if (_code(self.project) / lock).is_file():
                        shutil.copy2(_code(self.project) / lock, stage / "code" / lock)

    # -- shared ----------------------------------------------------------------------------------------------

    def shared(self):
        """Back to the shared tools: the project's `.venv` is rebuilt from the lock only when it is gone; nothing else is built."""
        from wayline import software

        venv = self.project / ".venv"
        if PYTHON in self.names:
            if not (venv / "bin" / "python").exists() and (_code(self.project) / LOCKS[PYTHON]).is_file():
                uv = self.uv()
                self.step("build python", [uv["executable"], "venv", "--python", self.python, str(venv)], env=uv.get("env") or None)
                self.python_packages(str(venv / "bin" / "python"))
            self.record["tools"][PYTHON] = {"executable": str(venv / "bin" / "python"), "env": {}}
        for name in self.names:
            if name != PYTHON:
                entry = self.entry(name)
                self.record["tools"][name] = {"executable": entry["executable"],
                                              "env": dict(entry.get("env") or {}, **software.project_env(self.project, name))}

    # -- the checks -------------------------------------------------------------------------------------------

    def check(self):
        """Each carried tool's version check inside the new environment, then the Python and Octave packages against their locks."""
        from wayline import software

        record = self.record
        for name in sorted(record["tools"]):
            tool = record["tools"][name]
            argv = _wrapped(self.project, record, [tool["executable"]])
            if name in LICENSED:
                done = self.run(argv + list(software.LICENSED[name]), timeout=software.LICENSED_CHECK_TIMEOUT_S, env=tool["env"] or None)
                found = software.parse_ver(_text(done)) if done.returncode == 0 else None
                printed = found["version"] if found else None
                wanted = self.entry(name).get("version")
            else:
                done = self.run(argv + ["--version"], timeout=TOOL_TIMEOUT_S, env=tool["env"] or None)
                printed = parse_version(_text(done)) if done.returncode == 0 else None
                wanted = self.python if name == PYTHON else self.entry(name).get("version")
                if name == PYTHON and printed:
                    printed = ".".join(printed.split(".")[:2])
            if done.returncode != 0:
                self.fail("check %s" % name, failure_line(done))
            if printed != wanted:
                self.fail("check %s" % name, "%s printed version %s inside the %s environment, and %s records %s"
                          % (name, printed, self.kind, "the project's .venv" if name == PYTHON else "tools.json", wanted))
            tool["version"] = printed
        if PYTHON in record["tools"] and (_code(self.project) / LOCKS[PYTHON]).is_file():
            python = record["tools"][PYTHON]["executable"]
            if self.kind == CONTAINER:
                argv = _wrapped(self.project, record, ["/usr/local/bin/uv", "pip", "freeze", "--python", python])
                env = {"SINGULARITYENV_UV_NO_CACHE": "1"}
            else:
                uv = self.uv()
                argv, env = [uv["executable"], "pip", "freeze", "--python", python], uv.get("env") or None
            done = self.run(argv, timeout=TOOL_TIMEOUT_S, env=env)
            if done.returncode != 0:
                self.fail("check python packages", failure_line(done))
            self.compare("check python packages", _requirements((_code(self.project) / LOCKS[PYTHON]).read_bytes()),
                         _requirements(done.stdout or b""))
        if "octave" in record["tools"] and (_code(self.project) / LOCKS["octave"]).is_file() and self.kind in (CONDA, CONTAINER):
            tool = record["tools"]["octave"]
            done = self.run(_wrapped(self.project, record, [tool["executable"], "--no-gui", "--eval", _OCTAVE_LIST]),
                            timeout=TOOL_TIMEOUT_S, env=tool["env"] or None)
            if done.returncode != 0:
                self.fail("check octave packages", failure_line(done))
            self.compare("check octave packages", {"%s %s" % row for row in _octave_rows((_code(self.project) / LOCKS["octave"]).read_bytes()).items()},
                         {"%s %s" % row for row in _octave_rows(done.stdout or b"").items()})

    def compare(self, step, locked, found):
        missing = sorted(locked - found)
        # conda-forge's Python brings its own installers, which uv's venv, where the lock was frozen, does not (measured live).
        extra = sorted(line for line in found - locked if line.split("==")[0].split(" @ ")[0] not in BOOTSTRAP)
        if missing or extra:
            self.fail(step, "the environment differs from the lock (%s)" % "; ".join(
                part for part in ("missing %s" % ", ".join(missing) if missing else "", "not locked %s" % ", ".join(extra) if extra else "") if part))


def _text(done):
    return ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", errors="replace")


def _requirements(data):
    """The pinned lines of a requirements lock or a freeze, normalized: comments and blanks dropped, names lowercased."""
    lines = set()
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, sep, version = line.partition("==")
            lines.add("%s%s%s" % (name.strip().lower().replace("_", "-"), sep, version.strip()))
    return lines


def _octave_rows(data):
    from wayline import software
    return dict(software._OCTAVE_ROW.findall(data.decode("utf-8", errors="replace")))


def _wrapped(project, record, argv):
    """`argv` as it runs in the environment `record` describes: inside the image for a container, as it is otherwise."""
    if record.get("kind") != CONTAINER:
        return list(argv)
    binds = []
    project = Path(project).resolve()
    home = Path.home().resolve()
    if home != project and home not in project.parents:  # the home is bound by default, and the project in it with it
        binds += ["--bind", str(project)]
    for bind in record.get("binds") or []:
        binds += ["--bind", bind]
    return [record["runner"], "exec"] + binds + [record["image"]] + list(argv)


# --- the move -------------------------------------------------------------------------------------------


def _marker(project):
    return Path(project) / WAYLINE_DIR / MOVING


def move_in_progress(project):
    """The move under way, `{from, to, started, pid}`, or None: the Run view shows it (ticket 110)."""
    found = toolbox.read_json_file(_marker(project))
    if not found:
        return None
    try:
        os.kill(int(found.get("pid")), 0)
    except (OSError, TypeError, ValueError):
        return None
    return found


@contextlib.contextmanager
def _one_move(project, kind):
    folder = Path(project) / WAYLINE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / MOVE_LOCK, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            under_way = move_in_progress(project) or {}
            raise MoveError(kind, "start", "a move to %s is already under way (pid %s)" % (under_way.get("to", "another environment"),
                                                                                         under_way.get("pid", "?"))) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _live_jobs_in(project, kind):
    from wayline.resources import LIVE_JOB_STATUSES
    found = []
    for path in sorted((Path(project) / "research" / "jobs").glob("*.json")):
        record = toolbox.read_json_file(path) or {}
        if record.get("environment") == kind and record.get("status") in LIVE_JOB_STATUSES:
            found.append(record.get("id") or path.stem)
    return found


def _current(project, kind, tools):
    """Whether the project already is in `kind`, with everything it now carries built there."""
    built = records(project).get(kind)
    if kind == SHARED:
        return True
    if not built:
        return False
    wanted = set(carried(project, tools, kind))
    where = built.get("image") or built.get("place")
    return wanted <= set(built.get("tools") or {}) and bool(where) and Path(where).exists()


def move(project, kind, by="cli", run=run_tool, tools=None, which=shutil.which, echo=None):
    """`wayline switch --environment <kind>`: build `kind` from the locks, check every tool inside it, and only then switch.

    Accepted with a conductor running or not: the build runs here, jobs keep running in the old
    environment while it does, and `harness.json` changes only once every check passed; then
    `control environment` is journaled. A project already in `kind`, with everything it carries
    built there, changes nothing. The decider never moves a project (`by` is `cli`, the
    conversation's, or `dashboard`).

    Returns `{from, to, changed, conductor, record}`; raises `MoveError` naming the failing step
    otherwise, with `harness.json`, the journal, and the old environment as they were.
    """
    from wayline.jsonschema import check, load_schema
    from wayline.ledger import Ledger, atomic_write, conductor_holder
    from wayline.project import HARNESS_JSON, ProjectError, control, read_harness

    project = Path(project).resolve()
    if kind not in KINDS:
        raise ProjectError("the environment is one of %s, got %r" % (", ".join(KINDS), kind))
    if by == "decider":
        raise ProjectError("the decider never sets the environment; moving a project is the owner's word alone")
    if run is run_tool and kind != SHARED:
        from wayline import real_backend
        real_backend("the network (building an environment)")
    tools = tools if tools is not None else Tools()
    before = setting(project)
    report = {"from": before, "to": kind, "changed": False, "conductor": conductor_holder(project), "record": records(project).get(kind)}
    if before == kind and _current(project, kind, tools):
        return report
    with _one_move(project, kind):
        live = _live_jobs_in(project, kind) if kind in (CONDA, VENV) else []
        if live:
            raise MoveError(kind, "start", "job %s still runs in the %s environment a rebuild would replace; move once it ended"
                            % (", ".join(live), kind), stays=before)
        marker = _marker(project)
        toolbox._write_record(marker, {"from": before, "to": kind, "started": now_ts(), "pid": os.getpid()})
        build = None
        try:
            build = _Build(project, kind, tools, run, which, echo)
            if kind in (CONDA, VENV):
                target = place(project, kind)
                if target.exists():
                    shutil.rmtree(target)
            getattr(build, kind)()
            build.check()
        except MoveError as failure:
            if kind in (CONDA, VENV) and place(project, kind).exists():
                shutil.rmtree(place(project, kind), ignore_errors=True)
            raise MoveError(kind, failure.step, failure.why, stays=before) from None
        finally:
            if marker.exists():
                marker.unlink()
        build.record["built"] = now_ts()
        build.record["python"] = build.python if PYTHON in build.record["tools"] else None
        ledger = Ledger(project)
        with ledger.lock():
            stored = records(project)
            stored[kind] = build.record
            _write_records(project, stored)
            harness = read_harness(project)
            if harness.get("environment") != kind:
                updated = dict(harness, environment=kind)
                check(updated, load_schema("harness"), name=HARNESS_JSON)
                atomic_write(project / HARNESS_JSON, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
            control(project, "environment", {"environment": kind, "from": before}, by=by)
    report.update({"changed": True, "record": build.record})
    return report


# --- resolving a tool -------------------------------------------------------------------------------------


def resolve(project, name, tools=None, kind=None):
    """How the tool `name` runs in the project's environment now: a `Resolved`, or `ToolsError` saying why it cannot.

    A project's tools and Python resolve through the environment's record (inside the image for a
    container), licensed software stays the host's (bound into the image), and the harness's and
    the machine's tools always run as `tools.json` records them.
    """
    from wayline import software

    project = Path(project).resolve()
    tools = tools if tools is not None else Tools()
    kind = kind or setting(project)
    entry = tools.entry(name)
    ours = name == PYTHON or name in PROJECT_NAMES or name in LICENSED
    if kind == SHARED or not ours:
        if name == PYTHON:
            python = project / ".venv" / "bin" / "python"
            if not python.exists():
                raise ToolsError("the project has no Python environment at %s (wayline tools package python <name> makes it)" % python.parent.parent)
            return Resolved([str(python)], {}, kind, _python_entry(project))
        if not entry or not entry.get("executable"):
            raise ToolsError("%s is not recorded in %s" % (name, tools.root / toolbox.TOOLS_JSON))
        env = dict(entry.get("env") or {})
        if kind == SHARED:
            env.update(software.project_env(project, name))
        return Resolved([str(entry["executable"])], env, kind, entry)
    built = records(project).get(kind)
    if not built:
        raise ToolsError("the project's environment is %s, and %s holds no record of its build; wayline switch --environment %s "
                         "builds it again" % (kind, _record_path(project), kind))
    tool = (built.get("tools") or {}).get(name)
    if tool is None:
        raise ToolsError("%s is not in the project's %s environment, which was built before the project needed it; "
                         "wayline switch --environment %s builds it again with it" % (name, kind, kind))
    return Resolved(_wrapped(project, built, [tool["executable"]]), dict(tool.get("env") or {}), kind,
                    _python_entry(project) if name == PYTHON else entry)


def _python_entry(project):
    """What a job record keeps of the project's Python: its minor version and the digest of its lock."""
    lock = _code(project) / LOCKS[PYTHON]
    return {"version": python_version(project), "lock": {"sha256": _sha256(lock)} if lock.is_file() else None}


def inside(project, command, env, kind=None):
    """A job's command and environment as they run inside the project's environment, for a job that names no tool.

    In a conda prefix or a venv its `bin/` comes first on the `PATH` and a bare program name it holds
    is made absolute; in a container the whole command runs in the image, with the prefix first on its
    `PATH`. `shared` changes nothing.
    """
    project = Path(project).resolve()
    kind = kind or setting(project)
    command, env = list(command), dict(env or {})
    if kind == SHARED:
        return command, env
    built = records(project).get(kind)
    if not built:
        raise ToolsError("the project's environment is %s, and %s holds no record of its build; wayline switch --environment %s "
                         "builds it again" % (kind, _record_path(project), kind))
    if kind == CONTAINER:
        env.setdefault("SINGULARITYENV_PREPEND_PATH", IN_IMAGE + "/bin")
        for key, value in IMAGE_ENV.items():
            env.setdefault(key, value)
        return _wrapped(project, built, command), env
    folder = Path(built["place"]) / "bin"
    if command and "/" not in command[0] and (folder / command[0]).exists():
        command[0] = str(folder / command[0])
    env.setdefault("PATH", "%s:%s" % (folder, DEFAULT_PATH))
    env.setdefault("CONDA_PREFIX" if kind == CONDA else "VIRTUAL_ENV", built["place"])
    return command, env


# --- the verb ---------------------------------------------------------------------------------------------


def switch_command(options):
    """`wayline switch --environment <kind> [--project <path>]`: the conversation calls it when the owner says so."""
    from wayline.project import ProjectError, find_project

    try:
        project = find_project(options.project)
        report = move(project, options.environment, echo=lambda line: print(line, file=sys.stderr, flush=True))
    except MoveError as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 1
    except (ProjectError, ToolsError, OSError) as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 1
    if not report["changed"]:
        print("the environment is already %s on %s" % (report["to"], project))
        return 0
    print("environment moved from %s to %s on %s" % (report["from"], report["to"], project))
    for name, tool in sorted((report["record"] or {}).get("tools", {}).items()):
        print("  %-10s %-12s %s" % (name, tool.get("version") or "-", tool.get("executable")))
    if report["conductor"] is not None:
        print("  journaled for the conductor (pid %s); jobs already launched finish where they started"
              % report["conductor"].get("pid", "?"))
    else:
        print("  every job and tool run launched from now on runs in %s" % report["to"])
    return 0
