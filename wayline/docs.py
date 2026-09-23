"""The documentation site (Implementation Decisions 13; BRIEF 13.2). Built by ticket 51.

A package the harness implemented gets a Sphinx site someone else can use, in four parts (tutorials,
how-to guides, reference, explanation), with an API reference generated from docstrings, examples
the build runs, a figure gallery, and the Read the Docs configuration. The harness stays standard
library: Sphinx runs in the project's own environment, never in the harness's.

Three verbs, one per step of a `docs` ticket:

- `wayline docs init` chooses the theme once per project and records it, the package, and the
  layout in `harness.json.docs`, then lays out whatever part of the skeleton is missing: `conf.py`,
  the four parts, the gallery, the examples page, one reference page per public module, the
  requirements, and `.readthedocs.yaml`. It never overwrites a file, so running it again only adds
  the reference page of a module that is new since.
- `wayline docs env` installs `docs/requirements.txt` into the project's environment: the
  interpreter `harness.json.docs.python` names, or else a venv at `research/.cache/docs/venv`.
- `wayline docs build` runs the machine checks: the structure is there and names the recorded
  theme; every public symbol of the package's `ast` inventory (the code dossier's) has a
  docstring; every example runs; Sphinx builds without a warning; every public symbol is present
  in the reference (the built `objects.inv`); every part is reachable from the index, the gallery
  shows a figure and a page shows every example; and every link resolves. Exit 0 when all pass,
  1 when one fails, printing the failures last, so the tail `wayline accept` journals is the list a
  returned ticket carries; 2 when the build could not be attempted.

Every `docs` ticket is accepted by `wayline docs build` whatever its own criteria say
(`tickets.machine_acceptance`), and earns one Type-B read of the site's clarity and completeness
(`gates.DOCS_READ`). What a build writes lives under `research/.cache/docs/` of the checkout it ran
in: a worktree's never counts as the ticket's uncommitted work, and the one on `main` is the site
the outputs index serves and the report names.
"""

import argparse
import html
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from wayline import fetch
from wayline.cli import parse_args
from wayline.code_dossier import python_inventory
from wayline.jsonschema import ValidationError, check as check_schema, load_schema
from wayline.ledger import atomic_write, now_ts
from wayline.project import HARNESS_JSON, ProjectError, find_project, is_project, policy_for

__all__ = [
    "CHECKS", "CHECKS_JSON", "DEFAULT_LAYOUT", "DEFAULT_THEME", "HTML_DIR", "PARTS", "SITE_INDEX",
    "DocsError", "SphinxMissing", "Symbol", "Check", "Record",
    "public_symbols", "public_modules", "detect_package", "read_objects_inv", "docs_settings", "python_for",
    "init", "env", "build", "run_sphinx", "read_record", "docs_command",
]

# The machine checks, in the order they run and are recorded.
CHECKS = ("structure", "docstrings", "examples", "build", "reference", "site", "links")

DOCS = "docs"
CACHE = Path("research") / ".cache" / "docs"
HTML_DIR = CACHE / "html"
STAGING_DIR = CACHE / "html.new"  # where a build writes; it replaces HTML_DIR only once it has a front page
DOCTREES_DIR = CACHE / "doctrees"
RUNS_DIR = CACHE / "runs"      # one scratch working directory per example, so a run writes nothing into docs/
VENV_DIR = CACHE / "venv"
CHECKS_JSON = CACHE / "checks.json"
WARNINGS_TXT = CACHE / "warnings.txt"
SITE_INDEX = HTML_DIR / "index.html"
READTHEDOCS = ".readthedocs.yaml"
REQUIREMENTS = Path(DOCS) / "requirements.txt"

# The four parts of the structure, then the two pages the spec adds to them.
PARTS = ("tutorials", "how_to", "reference", "explanation")
DEFAULT_LAYOUT = {
    "tutorials": "docs/tutorials",
    "how_to": "docs/how-to",
    "reference": "docs/reference",
    "explanation": "docs/explanation",
    "gallery": "docs/gallery",
    "examples": "docs/examples",
}
PART_NAMES = {"tutorials": "tutorials", "how_to": "how-to guides", "reference": "reference",
              "explanation": "explanation", "gallery": "gallery", "examples": "examples"}
DEFAULT_THEME = "furo"
# The distribution each well-known theme installs from; alabaster ships with Sphinx.
THEME_PACKAGES = {"furo": "furo", "sphinx_rtd_theme": "sphinx-rtd-theme", "pydata_sphinx_theme": "pydata-sphinx-theme",
                  "sphinx_book_theme": "sphinx-book-theme", "alabaster": None, "classic": None, "nature": None}

EXAMPLE_TIMEOUT_S = 300
SPHINX_TIMEOUT_S = 1800
LIST_MAX = 20  # failures printed per check; checks.json keeps them all
_NOT_A_PACKAGE = frozenset({"tests", "test", "docs", "research", "results", "scripts", ".worktrees", "build", "dist"})
_INDEXES = ("index.rst", "index.md")
_THEME_LINE = re.compile(r"^html_theme\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_INVENTORY_LINE = re.compile(r"^(.+?)\s+(\S+:\S+)\s+(-?\d+)\s+(\S*)\s+(.*)$")
_WARNING = re.compile(r"\b(WARNING|ERROR|CRITICAL|SEVERE)\b")
_RETRY_WITH_GET = frozenset({403, 405, 501})  # servers that refuse HEAD but answer GET
_RATE_LIMITED = 429


class DocsError(ValueError):
    """A docs verb that could not act: no package, no harness.json, a theme already chosen."""


class SphinxMissing(DocsError):
    """The project's environment has no Sphinx, or no interpreter at all."""


# --- the package's public symbols (the code dossier's ast inventory) ------------------------------


@dataclass(frozen=True)
class Symbol:
    name: str          # the dotted name the reference documents it under
    path: str          # the module file, relative to the root
    lineno: int
    documented: bool

    @property
    def where(self):
        return "%s:%d" % (self.path, self.lineno)


def _module_name(package_dir, relative):
    parts = Path(relative).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if (parts and parts[-1] == "__main__") or any(part.startswith("_") or part in ("tests", "test") for part in parts):
        return None  # a private module, an entry point, or the package's own tests: not its public API
    return ".".join((package_dir.name,) + parts)


def _inventory(root, package):
    """`[(module, path, inventory module record)]` for the package's public modules."""
    root = Path(root)
    package_dir = root / package
    if not (package_dir / "__init__.py").is_file():
        raise DocsError("%s is not a package (no __init__.py); record the right one with `wayline docs init --package <path>`" % package)
    modules = []
    for record in python_inventory(package_dir)["modules"]:
        module = _module_name(package_dir, record["path"])
        if module is not None:
            modules.append((module, (Path(package) / record["path"]).as_posix(), record))
    return modules


def public_symbols(root, package):
    """Every public top-level function and class of the package, whether it has a docstring, sorted by name.

    Public is the code dossier's rule (`__all__` when the module has one, else no leading underscore),
    over the modules a reader imports: not a private module, not `__main__`, not the package's tests.
    """
    symbols = []
    for module, path, record in _inventory(root, package):
        for symbol in record["functions"] + record["classes"]:
            if symbol["public"]:
                symbols.append(Symbol("%s.%s" % (module, symbol["name"]), path, symbol["lineno"], bool(symbol["docstring"])))
    return sorted(symbols, key=lambda symbol: symbol.name)


def public_modules(root, package):
    """The dotted names of the modules that define a public symbol: one reference page each."""
    return sorted({symbol.name.rsplit(".", 1)[0] for symbol in public_symbols(root, package)})


def detect_package(root):
    """The one package under `src/`, or else at the top of the root; None when there is not exactly one."""
    root = Path(root)
    for base in (root / "src", root):
        found = sorted(path.parent for path in base.glob("*/__init__.py") if path.parent.name not in _NOT_A_PACKAGE)
        if len(found) == 1:
            return found[0].relative_to(root).as_posix()
        if found:
            return None
    return None


def read_objects_inv(path):
    """`{name: domain:role}` from a Sphinx version 2 inventory: four header lines, then zlib."""
    data = Path(path).read_bytes()
    parts = data.split(b"\n", 4)
    if len(parts) < 5 or not parts[0].startswith(b"# Sphinx inventory version 2"):
        raise DocsError("%s is not a version 2 Sphinx inventory" % path)
    try:
        body = zlib.decompress(parts[4]).decode("utf-8")
    except (zlib.error, UnicodeDecodeError) as failure:
        raise DocsError("%s cannot be read: %s" % (path, failure)) from None
    found = {}
    for line in body.splitlines():
        match = _INVENTORY_LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


# --- settings: harness.json.docs ---------------------------------------------------------------


def _harness_path(root, project):
    """The `harness.json` a build reads: the checkout's own (a worktree carries the branch's), else the project's."""
    for base in (Path(root), Path(project)):
        if (base / HARNESS_JSON).is_file():
            return base / HARNESS_JSON
    raise DocsError("neither %s nor %s holds a %s" % (root, project, HARNESS_JSON))


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        raise DocsError("%s cannot be read: %s" % (path, failure)) from None


def docs_settings(root, project=None):
    """`harness.json.docs` of the checkout, `{}` when nothing is recorded yet; a layout outside `docs/` is refused."""
    settings = dict(_read_json(_harness_path(root, project or root)).get("docs") or {})
    _check_layout(settings.get("layout"))
    return settings


def _check_layout(layout):
    """Every part of a layout is a directory under `docs/`, where Sphinx's source is; a DocsError names the first that is not."""
    for part, place in sorted((layout or {}).items()):
        parts = Path(str(place)).parts
        if len(parts) < 2 or parts[0] != DOCS or ".." in parts:
            raise DocsError("harness.json.docs.layout.%s is %r; every part of the site is a directory under docs/, "
                            "which Sphinx reads as its source" % (part, place))


def python_for(project, settings):
    """The interpreter of the project's environment: the recorded one, else the venv `wayline docs env` makes."""
    named = (settings or {}).get("python")
    if named:
        path = Path(named).expanduser()
        return str(path if path.is_absolute() or os.sep not in named else Path(project) / path)
    return str(Path(project) / VENV_DIR / "bin" / "python")


def _environment(root, package):
    """The process environment the examples and Sphinx run in: the checkout's package first on the path."""
    base = (Path(root) / package).parent if package else Path(root)
    existing = os.environ.get("PYTHONPATH")
    return dict(os.environ, PYTHONPATH=str(base) + (os.pathsep + existing if existing else ""), PYTHONDONTWRITEBYTECODE="1")


# --- init: the theme, once, and the skeleton ----------------------------------------------------


def init(root, theme=None, package=None):
    """Record the theme, package, and layout in `harness.json.docs` and lay out the missing skeleton.

    Returns the paths written, relative to `root`, in the order written; `[]` when there was nothing
    to do. A theme other than the recorded one is refused: the theme is chosen once per project, and
    changing it is the owner's edit of `harness.json`.
    """
    root = Path(root).resolve()
    harness_path = root / HARNESS_JSON
    harness = _read_json(harness_path)
    recorded = dict(harness.get("docs") or {})
    if recorded.get("theme") and theme and theme != recorded["theme"]:
        raise DocsError("the theme is chosen once per project, and harness.json.docs records %r; %r is refused "
                        "(the owner changes it by editing harness.json)" % (recorded["theme"], theme))
    chosen = dict(recorded)
    chosen["theme"] = recorded.get("theme") or theme or DEFAULT_THEME
    chosen["package"] = package or recorded.get("package") or detect_package(root)
    if not chosen["package"]:
        raise DocsError("no single package found under %s or %s/src; name it with --package <path>" % (root, root))
    chosen["layout"] = recorded.get("layout") or dict(DEFAULT_LAYOUT)
    _check_layout(chosen["layout"])
    written = []
    if chosen != recorded:
        harness["docs"] = chosen
        try:
            check_schema(harness, load_schema("harness"), name=str(harness_path))
        except ValidationError as failure:
            raise DocsError(str(failure)) from None
        atomic_write(harness_path, json.dumps(harness, indent=2) + "\n")
        written.append(HARNESS_JSON)
    for relative, text in _skeleton(root, chosen):
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, text)
        written.append(relative)
    return written


def _title(text, mark="="):
    return "%s\n%s\n" % (text, mark * len(text))


def _skeleton(root, settings):
    """`[(relative path, text)]`: every file of a fresh site, parts first, one reference page per public module."""
    layout, package, theme = settings["layout"], settings["package"], settings["theme"]
    name = Path(package).name
    docs = root / DOCS

    def under_docs(part):
        return Path(layout[part]).relative_to(DOCS).as_posix()

    to_package = os.path.relpath(root / Path(package).parent, docs)
    files = [
        ("docs/conf.py", CONF_PY.format(name=name, path=to_package, theme=theme)),
        ("docs/index.rst", _title(name) + INDEX_BODY.format(name=name) + "".join(
            "   %s/index\n" % under_docs(part) for part in PARTS + ("gallery", "examples"))),
        (REQUIREMENTS.as_posix(), "sphinx>=7\n" + ("%s\n" % THEME_PACKAGES.get(theme, theme.replace("_", "-"))
                                                   if THEME_PACKAGES.get(theme, theme) else "")),
        (READTHEDOCS, READTHEDOCS_YAML),
    ]
    for part in PARTS + ("gallery", "examples"):
        title, lead = PART_PAGES[part]
        body = _title(title) + "\n" + lead + "\n"
        if part in PARTS:
            body += "\n.. toctree::\n   :maxdepth: 1\n   :glob:\n\n   *\n"
        files.append(("%s/index.rst" % layout[part], body))
    for module in public_modules(root, package):
        files.append(("%s/%s.rst" % (layout["reference"], module),
                      _title(module) + "\n.. automodule:: %s\n   :members:\n" % module))
    return files


CONF_PY = '''"""Sphinx configuration, laid out by `wayline docs init`.

The theme is recorded in harness.json.docs and chosen once per project: `wayline docs build` fails
while this file names another.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("{path}"))

project = "{name}"
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]
autodoc_mock_imports = []  # imports the package needs and the docs environment does not install
exclude_patterns = ["_build"]
html_theme = "{theme}"
'''

INDEX_BODY = """
Documentation for the ``{name}`` package.

.. toctree::
   :maxdepth: 2

"""

PART_PAGES = {
    "tutorials": ("Tutorials", "Lessons that take a newcomer from nothing to a first working result, one step at a time."),
    "how_to": ("How-to guides", "Recipes for one task each, for a reader who already knows what they want to do."),
    "reference": ("Reference", "Every public module, class, and function, generated from the docstrings."),
    "explanation": ("Explanation", "Why the package is built the way it is: the design, the choices, and their limits."),
    "gallery": ("Gallery", "The figures the package makes, each with the example or the result it comes from."),
    "examples": ("Examples", "Scripts the documentation build runs; each one here runs as it is shown."),
}

READTHEDOCS_YAML = """version: 2
build:
  os: ubuntu-24.04
  tools:
    python: "3.12"
sphinx:
  configuration: docs/conf.py
  fail_on_warning: true
python:
  install:
    - requirements: docs/requirements.txt
"""


# --- env: the project's own environment ------------------------------------------------------------


def env(root, project=None, run=subprocess.run):
    """Install `docs/requirements.txt` into the project's environment, making the default venv first.

    Returns the commands run. `run` is `subprocess.run`'s shape, so a test can record instead.
    """
    root = Path(root).resolve()
    project = Path(project or root).resolve()
    requirements = root / REQUIREMENTS
    if not requirements.is_file():
        raise DocsError("%s is missing; `wayline docs init` writes it" % REQUIREMENTS)
    settings = docs_settings(root, project)
    ran = []

    def step(command):
        ran.append(command)
        try:
            return run(command, check=False).returncode
        except FileNotFoundError:
            raise DocsError("no interpreter at %s; name the project's own in harness.json.docs.python, or remove "
                            "the key for the venv `wayline docs env` makes" % command[0]) from None

    python = python_for(project, settings)
    install = [python, "-m", "pip", "install", "-r", str(requirements)]
    venv = project / VENV_DIR

    def usable():
        return (venv / "bin" / "python").exists() and step([python, "-m", "pip", "--version"]) == 0

    if not settings.get("python") and not usable():
        # A venv a failed run left half-made has an interpreter and no pip; it is made again, not trusted.
        shutil.rmtree(venv, ignore_errors=True)
        if step([sys.executable, "-m", "venv", str(venv)]) != 0 or not usable():
            # A Python without ensurepip (Debian's, without python3-venv) cannot seed pip into a venv; the
            # venv then sees the interpreter's own pip through its site packages, as the code dossier's does.
            shutil.rmtree(venv, ignore_errors=True)
            fallback = [sys.executable, "-m", "venv", "--system-site-packages", "--without-pip", str(venv)]
            if step(fallback) != 0 or not usable():
                raise DocsError("no venv with pip could be made at %s, with or without its own pip" % venv)
    if step(install) != 0:
        raise DocsError("`%s` exited non-zero" % " ".join(install))
    return ran


# --- build: the machine checks -------------------------------------------------------------------


@dataclass
class Check:
    id: str
    failures: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    skipped: Optional[str] = None  # why the check could not run; a skipped check has not passed

    @property
    def passed(self):
        return not self.failures and self.skipped is None

    def payload(self):
        return {"check": self.id, "pass": self.passed, "skipped": self.skipped,
                "failures": list(self.failures), "notes": list(self.notes)}


@dataclass
class Record:
    root: Path
    python: str
    checks: list
    site: Optional[Path]
    ran_at: str

    @property
    def passed(self):
        return all(check.passed for check in self.checks)

    def check(self, identifier):
        return next(check for check in self.checks if check.id == identifier)

    def payload(self):
        return {
            "ran_at": self.ran_at, "root": str(self.root), "python": self.python, "pass": self.passed,
            "site": self.site.relative_to(self.root).as_posix() if self.site else None,
            "checks": [check.payload() for check in self.checks],
        }

    def text(self):
        failed = [check for check in self.checks if not check.passed]
        lines = ["wayline docs build: %s" % ("pass" if not failed else "FAIL (%d of %d checks)" % (len(failed), len(self.checks))),
                 "  site    %s" % (self.site.relative_to(self.root).as_posix() if self.site else "not built"),
                 "  record  %s" % CHECKS_JSON.as_posix(),
                 "  python  %s" % self.python]
        for check in self.checks:
            if check.passed:
                lines.append("  pass  %s" % check.id)
                lines.extend("      note: %s" % note for note in check.notes)
        for check in failed:
            if check.skipped is not None:
                lines.append("  FAIL  %s (not run: %s)" % (check.id, check.skipped))
                continue
            lines.append("  FAIL  %s (%d)" % (check.id, len(check.failures)))
            lines.extend("      note: %s" % note for note in check.notes)
            shown = check.failures[:LIST_MAX]
            if len(check.failures) > LIST_MAX:
                lines.append("      ... %d more in %s" % (len(check.failures) - LIST_MAX, CHECKS_JSON.as_posix()))
            lines.extend("      - %s" % failure for failure in shown)
        return "\n".join(lines)


class _Deadline:
    """The seconds a build has left: every stage fits in the acceptance timeout, so the record is always written."""

    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    def left(self):
        return max(0.0, self.end - time.monotonic())


def budget_for(project):
    """The seconds a build may take: `policy.acceptance_timeout_s` less a margin for the record, since
    `wayline accept` and the conductor kill a command at that timeout and a killed build lists nothing."""
    try:
        timeout = policy_for(project).get("acceptance_timeout_s", 600)
    except (ProjectError, OSError, ValueError):
        timeout = 600
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = 600
    return max(30.0, timeout * 0.9 - 15)


def build(root, project=None, *, python=None, sphinx=None, fetcher=None, offline=False, budget_s=None):
    """Run every check on the site under `root` and write `research/.cache/docs/checks.json` there.

    `root` is the checkout (a ticket's worktree, or the project on `main`); `project` is the project,
    whose environment Sphinx runs in. `sphinx` is the seam `run_sphinx` fills, `fetcher` the fetch
    seam for external links, which `offline` leaves unasked. `budget_s` bounds the whole build
    (`budget_for` by default): a stage that would outlast it is cut short and says so.

    Sphinx builds into a staging directory, and the checks read that; only a build that wrote a front
    page replaces the site under `research/.cache/docs/html/`, so the site the dashboard serves stays
    up while a build runs and survives a build that failed before it wrote anything.
    """
    root = Path(root).resolve()
    project = Path(project or root).resolve()
    settings = docs_settings(root, project)
    layout = settings.get("layout") or dict(DEFAULT_LAYOUT)
    package = settings.get("package") or detect_package(root)
    python = python or python_for(project, settings)
    environment = _environment(root, package)
    deadline = _Deadline(budget_for(project) if budget_s is None else budget_s)

    structure = _check_structure(root, settings, layout)
    docstrings, symbols = _check_docstrings(root, package)
    examples = _check_examples(root, layout, python, environment, deadline)
    build_check, staged = _run_build(root, python, environment, sphinx or run_sphinx, deadline)
    site = None
    if staged is None:
        reason = "the site was not built"
        later = [Check("reference", skipped=reason), Check("site", skipped=reason), Check("links", skipped=reason)]
    else:
        out = staged.parent
        pages = _read_pages(out)
        later = [_check_reference(out, symbols), _check_site(root, out, pages, layout),
                 _check_links(out, pages, None if offline else (fetcher or fetch.Fetcher()), offline, deadline)]
        site = _publish(root, out)
    shutil.rmtree(root / STAGING_DIR, ignore_errors=True)
    record = Record(root, python, [structure, docstrings, examples, build_check] + later, site, now_ts())
    target = root / CHECKS_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, json.dumps(record.payload(), indent=2) + "\n")
    return record


def read_record(root):
    """The last build's `checks.json` under `root`, or None when no build ran there."""
    try:
        return json.loads((Path(root) / CHECKS_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _check_structure(root, settings, layout):
    check = Check("structure")
    failures = check.failures
    conf = root / DOCS / "conf.py"
    recorded = settings.get("theme")
    if not conf.is_file():
        failures.append("docs/conf.py is missing (the Sphinx configuration)")
    if not recorded:
        failures.append("harness.json.docs records no theme: choose it once with `wayline docs init --theme <name>`")
    elif conf.is_file():
        match = _THEME_LINE.search(conf.read_text(encoding="utf-8", errors="replace"))
        if match is None:
            failures.append("docs/conf.py sets no html_theme, and harness.json.docs records %r" % recorded)
        elif match.group(1) != recorded:
            failures.append("docs/conf.py sets html_theme = %r, and harness.json.docs records %r; the theme is chosen once per project"
                            % (match.group(1), recorded))
    if not any((root / DOCS / name).is_file() for name in _INDEXES):
        failures.append("docs/index.rst is missing (the site's front page)")
    for part in PARTS + ("gallery", "examples"):
        if not any((root / layout[part] / name).is_file() for name in _INDEXES):
            failures.append("%s has no index.rst or index.md (the %s part of the site)" % (layout[part], PART_NAMES[part]))
    if (root / layout["examples"]).is_dir() and not _examples(root, layout):
        failures.append("%s holds no example (a .py file the build runs)" % layout["examples"])
    if not (root / REQUIREMENTS).is_file():
        failures.append("%s is missing (what the docs environment and Read the Docs install)" % REQUIREMENTS)
    readthedocs = root / READTHEDOCS
    if not readthedocs.is_file():
        failures.append("%s is missing (the Read the Docs configuration)" % READTHEDOCS)
    else:
        text = readthedocs.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^version:\s*2\s*$", text, re.MULTILINE):
            failures.append("%s does not say `version: 2`" % READTHEDOCS)
        if not re.search(r"^\s+configuration:\s*docs/conf\.py\s*$", text, re.MULTILINE):
            failures.append("%s does not point sphinx.configuration at docs/conf.py" % READTHEDOCS)
    return check


def _check_docstrings(root, package):
    check = Check("docstrings")
    if not package:
        check.failures.append("no package to document: record it with `wayline docs init --package <path>`")
        return check, []
    try:
        symbols = public_symbols(root, package)
    except DocsError as failure:
        check.failures.append(str(failure))
        return check, []
    check.failures.extend("%s (%s) has no docstring" % (symbol.name, symbol.where) for symbol in symbols if not symbol.documented)
    check.notes.append("%d public symbol(s) in %s" % (len(symbols), package))
    return check, symbols


def _examples(root, layout):
    directory = root / layout["examples"]
    return sorted(path for path in directory.glob("*.py") if path.is_file()) if directory.is_dir() else []


def _check_examples(root, layout, python, environment, deadline):
    """Run every example with the project's interpreter, each in a scratch directory of its own."""
    check = Check("examples")
    for script in _examples(root, layout):
        relative = script.relative_to(root).as_posix()
        timeout = min(EXAMPLE_TIMEOUT_S, deadline.left())
        if timeout < 1:
            check.failures.append("%s was not run: the build's time ran out (policy.acceptance_timeout_s)" % relative)
            continue
        workdir = root / RUNS_DIR / script.stem
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            done = subprocess.run([python, str(script)], cwd=workdir, env=environment, capture_output=True,
                                  text=True, timeout=timeout, check=False)
        except FileNotFoundError:
            check.failures.append("%s could not run: no interpreter at %s (`wayline docs env` makes one)" % (relative, python))
            continue
        except subprocess.TimeoutExpired:
            check.failures.append("%s ran past %d s" % (relative, timeout))
            continue
        if done.returncode != 0:
            last = [line.strip() for line in (done.stderr or done.stdout or "").splitlines() if line.strip()]
            check.failures.append("%s exited %d: %s" % (relative, done.returncode, last[-1] if last else "no output"))
    return check


def run_sphinx(python, source, out, doctrees, warnings_path, env, timeout_s):
    """`python -m sphinx -b html`, fresh (`-E -a`), warnings to `warnings_path`; `(exit code, output)`."""
    try:
        probe = subprocess.run([python, "-c", "import sphinx"], env=env, capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError:
        raise SphinxMissing("no interpreter at %s: run `wayline docs env`, which makes the project's docs environment "
                            "and installs docs/requirements.txt there" % python) from None
    if probe.returncode != 0:
        raise SphinxMissing("Sphinx is not installed in %s: run `wayline docs env`, which installs docs/requirements.txt there" % python)
    try:
        done = subprocess.run([python, "-m", "sphinx", "-b", "html", "-E", "-a", "-q", "-d", str(doctrees),
                               "-w", str(warnings_path), str(source), str(out)],
                              env=env, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return 124, "sphinx ran past %d s" % timeout_s
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _run_build(root, python, environment, sphinx, deadline):
    """Sphinx into the staging directory; `(check, staged front page or None)`."""
    check = Check("build")
    out, doctrees, warnings = root / STAGING_DIR, root / DOCTREES_DIR, root / WARNINGS_TXT
    shutil.rmtree(out, ignore_errors=True)  # a page removed from the sources must not go on resolving links
    shutil.rmtree(doctrees, ignore_errors=True)
    warnings.parent.mkdir(parents=True, exist_ok=True)
    warnings.write_text("", encoding="utf-8")
    if not (root / DOCS / "conf.py").is_file():
        check.skipped = "docs/conf.py is missing"
        return check, None
    timeout = min(SPHINX_TIMEOUT_S, deadline.left())
    if timeout < 1:
        check.failures.append("sphinx was not run: the build's time ran out on the examples (policy.acceptance_timeout_s)")
        return check, None
    try:
        code, output = sphinx(python, root / DOCS, out, doctrees, warnings, environment, timeout)
    except SphinxMissing as missing:
        check.failures.append(str(missing))
        return check, None
    prefix = str(root) + os.sep
    lines = [line.rstrip().replace(prefix, "") for line in warnings.read_text(encoding="utf-8", errors="replace").splitlines()]
    flagged = [line for line in lines if _WARNING.search(line)] or [line for line in lines if line.strip()]
    check.failures.extend(flagged)
    if code != 0 and not flagged:
        tail = [line for line in output.splitlines() if line.strip()][-3:]
        check.failures.append("sphinx exited %d: %s" % (code, " | ".join(tail) or "no output"))
    site = out / "index.html"
    return check, (site if site.is_file() else None)


def _publish(root, staged):
    """Put the staged build where the site is served from; returns the served front page."""
    served = root / HTML_DIR
    shutil.rmtree(served, ignore_errors=True)
    os.replace(staged, served)
    return served / "index.html"


def _check_reference(out, symbols):
    check = Check("reference")
    inventory = out / "objects.inv"
    if not inventory.is_file():
        check.failures.append("the build wrote no objects.inv, so the reference cannot be checked")
        return check
    try:
        present = read_objects_inv(inventory)
    except DocsError as failure:
        check.failures.append(str(failure))
        return check
    check.failures.extend("%s is not in the reference (objects.inv)" % symbol.name for symbol in symbols if symbol.name not in present)
    return check


class _Page(html.parser.HTMLParser):
    """The links, ids, image count, and text of one built page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.ids, self.images, self.text = [], set(), 0, []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"])
        if tag == "img":
            self.images += 1
        for attribute in {"a": ("href",), "link": ("href",), "img": ("src",), "script": ("src",)}.get(tag, ()):
            if values.get(attribute):
                self.links.append(values[attribute])

    def handle_data(self, data):
        self.text.append(data)


def _read_pages(out):
    pages = {}
    for path in sorted(out.rglob("*.html")):
        parser = _Page()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        parser.close()
        pages[path] = parser
    return pages


def _resolve(out, page, link):
    """`(target file, fragment)` for an internal link, or None for one to leave alone."""
    parts = urlsplit(link)
    if parts.scheme or parts.netloc:
        return None
    if not parts.path:
        return page, parts.fragment
    base = out if parts.path.startswith("/") else page.parent
    target = (base / unquote(parts.path.lstrip("/"))).resolve()
    if target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def _check_site(root, out, pages, layout):
    """Every part reachable from the front page, a figure in the gallery, and every example shown."""
    check = Check("site")
    front = out / "index.html"
    linked = set()
    if front in pages:
        for link in pages[front].links:
            resolved = _resolve(out, front, link)
            if resolved is not None:
                linked.add(resolved[0])
    for part in PARTS + ("gallery", "examples"):
        page = (out / Path(layout[part]).relative_to(DOCS) / "index.html").resolve()
        name = page.relative_to(out.resolve()).as_posix()
        if page not in pages and not page.is_file():
            check.failures.append("the %s part was not built (%s)" % (PART_NAMES[part], name))
        elif page not in linked:
            check.failures.append("the %s part (%s) is not linked from index.html" % (PART_NAMES[part], name))
        if part == "gallery" and page in pages and pages[page].images == 0:
            check.failures.append("the gallery (%s) shows no figure" % name)
    texts = [html.unescape("".join(parser.text)) for parser in pages.values()]
    for script in _examples(root, layout):
        lines = [line.strip() for line in script.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        probe = max(lines, key=len) if lines else ""
        if probe and not any(probe in text for text in texts):
            check.failures.append("%s is run but no page of the site shows it" % script.relative_to(root).as_posix())
    return check


def _check_links(out, pages, fetcher, offline, deadline):
    """Every internal link and anchor resolves; every external link answers, unless `offline`.

    Only an answer the link's own server gave fails the check (a 4xx other than 429): a host that
    cannot be reached, a 5xx, or a link the build's time ran out before is a note, since acceptance
    runs this three times and a network's bad minute is not a fault of the site.
    """
    check = Check("links")
    external = {}
    seen = set()
    for page, parser in pages.items():
        name = page.relative_to(out).as_posix()
        for link in parser.links:
            if link.startswith(("mailto:", "javascript:", "data:", "tel:")):
                continue
            parts = urlsplit(link)
            if parts.scheme in ("http", "https") or (not parts.scheme and parts.netloc):
                url = link if parts.scheme else "https:" + link  # a protocol-relative link is fetched over https
                external.setdefault(url.split("#", 1)[0], (name, link))
                continue
            if parts.scheme:
                continue
            target, fragment = _resolve(out, page, link)
            failure = None
            if not target.is_file():
                failure = "%s links to %s, which does not exist" % (name, link)
            elif fragment and target.suffix == ".html":
                ids = pages[target].ids if target in pages else _ids_of(target)
                if unquote(fragment) not in ids:
                    failure = "%s links to %s, whose anchor is not on that page" % (name, link)
            if failure and failure not in seen:
                seen.add(failure)
                check.failures.append(failure)
    if offline or fetcher is None:
        if external:
            check.notes.append("%d external link(s) not checked (--offline)" % len(external))
        return check
    unasked = []
    for url in sorted(external):
        page, link = external[url]
        if deadline.left() < 1:
            unasked.append(url)
            continue
        try:
            answer = fetcher.fetch(url, method="HEAD")
            if answer.status in _RETRY_WITH_GET:
                answer = fetcher.fetch(url)
        except fetch.FetchError as failure:
            check.notes.append("%s could not be reached, not counted (%s)" % (url, failure))
            continue
        if answer.status == _RATE_LIMITED or answer.status >= 500:
            check.notes.append("%s answered %d, not counted" % (url, answer.status))
        elif answer.status >= 400:
            check.failures.append("%s links to %s, which answered %d" % (page, link, answer.status))
    if unasked:
        check.notes.append("%d external link(s) not checked: the build's time ran out" % len(unasked))
    return check


def _ids_of(path):
    parser = _Page()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.ids


# --- the verb ------------------------------------------------------------------------------------


def _project_of(explicit):
    """The project: `--project`, `WAYLINE_PROJECT`, the repository a worktree belongs to, else the active one."""
    if explicit:
        return find_project(explicit)
    named = os.environ.get("WAYLINE_PROJECT")
    if named and is_project(named):
        return Path(named).resolve()
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=False)
    if common.returncode == 0 and common.stdout.strip():
        candidate = Path(common.stdout.strip()).parent
        if is_project(candidate):
            return candidate.resolve()
    return find_project(None)


def _root_of(explicit, project):
    """The checkout: `--root`, else the working directory when it holds a harness.json (a worktree, or `main`), else the project."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    here = Path.cwd()
    return here.resolve() if is_project(here) else project


def docs_command(args):
    parser = argparse.ArgumentParser(prog="wayline docs", description="the documentation site (Implementation Decisions 13)")
    sub = parser.add_subparsers(dest="action", required=True)
    for action, text in (("init", "record the theme once and lay out the missing skeleton"),
                         ("env", "install docs/requirements.txt into the project's environment"),
                         ("build", "build the site and run the machine checks (exit 1 on a failure)")):
        command = sub.add_parser(action, help=text, description=text)
        command.add_argument("--project", help="the project; by default WAYLINE_PROJECT, the worktree's repository, or the active one")
        command.add_argument("--root", help="the checkout to act on; by default the working directory when it holds a harness.json")
        if action == "init":
            command.add_argument("--theme", help="the html_theme, chosen once per project (default %s)" % DEFAULT_THEME)
            command.add_argument("--package", help="the package directory, relative to the project (detected when there is one)")
        if action == "build":
            command.add_argument("--offline", action="store_true", help="do not ask the external links")
            command.add_argument("--python", help="run in this interpreter instead of the project's docs environment")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = _project_of(options.project)
        root = _root_of(options.root, project)
        if options.action == "init":
            written = init(root, theme=options.theme, package=options.package)
            print("\n".join("wrote %s" % path for path in written) if written else "nothing to write: the skeleton is in place")
            return 0
        if options.action == "env":
            for command in env(root, project):
                print("ran %s" % " ".join(command))
            return 0
        record = build(root, project, python=options.python, offline=options.offline)
    except (DocsError, ProjectError) as failure:
        print("wayline docs %s: %s" % (options.action, failure), file=sys.stderr)
        return 1 if options.action == "init" else 2
    print(record.text())
    return 0 if record.passed else 1
