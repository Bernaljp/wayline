"""Code dossiers (Implementation Decisions 9; research-notes 06 Section 4): a paper's code, pinned.

A code dossier is a paper's code at the commit the owner names, inventoried by machinery alone:
`wayline absorb --code <slug> <url>@<sha>` clones it, walks every `*.py` with the standard
library `ast`, reads entry points from `pyproject.toml` and `setup.cfg`, finds its configs,
tests, scripts, and data requirements by glob and grep, and then installs the pinned commit into
a fresh venv and runs the smallest test or example it found. `verified` is true only when both
the install and that run exited 0; nothing here reads the code for meaning, which is the
consultant's job over the `api_map` this module leaves empty.

The clone lives at `refs/<slug>/code/`, next to the paper's own `dossier.json`; only
`code_dossier.json` goes through the ledger, the same way the scout's cache under
`.cache/scout/` is written directly instead of through it: a git working tree is not a single
atomic write, and re-running the absorb is what keeps it in step with a moved tag or a new sha.
"""

import argparse
import ast
import configparser
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import ledger_for, now_ts
from wayline.project import ProjectError, find_project

__all__ = [
    "CodeDossierError", "REFS", "CODE_DIR", "LOG_MAX",
    "parse_code_reference", "clone_at_sha", "git_metadata", "detect_language",
    "python_inventory", "entry_points_of", "configs_of", "tests_of", "scripts_of",
    "data_requirements_of", "run_recipe", "code_dossier", "write_code_dossier",
    "absorb_code", "code_command",
]

REFS = "refs"
CODE_DIR = "code"
LOG_MAX = 20000  # characters of install+run output kept in the record

_CONFIG_DIRS = ("configs", "config")
_CONFIG_GLOBS = ("*.yaml", "*.yml", "*.json", "*.toml")
_TEST_DIRS = ("tests", "test")
_TEST_GLOBS = ("test_*.py", "*_test.py", "conftest.py")
_SCRIPT_DIRS = ("scripts", "bin")
_VENDORED = frozenset({".git", "build", "dist", ".eggs", ".venv", "venv", "__pycache__"})
_DATA_CALL = re.compile(r"\b(?:hf_hub_download|load_dataset|urlretrieve|requests\.get|wget|curl)\b")
_DATA_URL = re.compile(r"https?://\S+\.(?:tar\.gz|tgz|zip)\b")
_MAIN_IDIOM = re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", re.MULTILINE)
_SHA_SUFFIX = re.compile(r"^(?P<url>.+)@(?P<sha>[0-9a-fA-F]{7,40})$")

_MICRO_RUNNER = """\
import importlib.util
import sys
import unittest

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("_wayline_check", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

cases = [value for value in vars(module).values() if isinstance(value, type) and issubclass(value, unittest.TestCase)]
if cases:
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in cases:
        suite.addTests(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

functions = [value for name, value in vars(module).items() if name.startswith("test") and callable(value)]
if not functions:
    print("no test function or TestCase found in %s" % path)
    sys.exit(1)
failures = 0
for function in functions:
    try:
        function()
        print("PASSED", function.__name__)
    except Exception as failure:
        failures += 1
        print("FAILED", function.__name__, repr(failure))
sys.exit(0 if failures == 0 else 1)
"""


class CodeDossierError(ValueError):
    """A code dossier the harness will not build: a reference it cannot parse, a clone that failed."""


# --- the reference --------------------------------------------------------------------------------


def parse_code_reference(text):
    """`<url>@<sha>` split from the right, so an ssh remote's own `@` (`git@host:org/repo`) survives."""
    match = _SHA_SUFFIX.match(str(text or "").strip())
    if not match:
        raise CodeDossierError("%r is not <url>@<sha>; a code dossier is pinned to a full or abbreviated commit sha" % (text,))
    return match.group("url"), match.group("sha").lower()


# --- the clone -------------------------------------------------------------------------------------


def clone_at_sha(url, sha, dest):
    """Clone `url` at `sha` into `dest`: the partial clone research-notes 06 verified, or its fallback.

    `git clone --filter=blob:none --no-checkout` then `git checkout <sha>` is tried first; a sha
    the clone's own refs never reached (or a server that refuses the filter and the checkout
    both) falls back to `git init` and `fetch --depth 1 <url> <sha>`, which asks the server for
    that one commit directly.
    """
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cloned = subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(dest)], capture_output=True, text=True,
    )
    if cloned.returncode == 0:
        checkout = subprocess.run(["git", "-C", str(dest), "checkout", sha], capture_output=True, text=True)
        if checkout.returncode == 0:
            return dest
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    init = subprocess.run(["git", "init", "-q", str(dest)], capture_output=True, text=True)
    if init.returncode != 0:
        raise CodeDossierError("git init failed for %s: %s" % (dest, (init.stderr or init.stdout).strip()))
    fetch = subprocess.run(["git", "-C", str(dest), "fetch", "--depth", "1", url, sha], capture_output=True, text=True)
    if fetch.returncode != 0:
        raise CodeDossierError("could not clone %s at %s: %s" % (url, sha, (fetch.stderr or fetch.stdout).strip()))
    checkout = subprocess.run(["git", "-C", str(dest), "checkout", "FETCH_HEAD"], capture_output=True, text=True)
    if checkout.returncode != 0:
        raise CodeDossierError("could not check out %s@%s: %s" % (url, sha, (checkout.stderr or checkout.stdout).strip()))
    return dest


def git_metadata(dest, url):
    """`url, sha, author_date, nearest tag, submodules`, read off the clone the acceptance criterion asks for."""
    return {
        "url": url,
        "sha": _git_out(dest, "rev-parse", "HEAD") or "",
        "author_date": _git_out(dest, "log", "-1", "--format=%aI"),
        "tag": _git_out(dest, "describe", "--tags", "--always"),
        "submodules": _submodules(dest),
    }


def _git_out(dest, *args):
    done = subprocess.run(["git", "-C", str(dest), *args], capture_output=True, text=True)
    return done.stdout.strip() or None if done.returncode == 0 else None


_SUBMODULE_LINE = re.compile(r"^[\s\-+U]([0-9a-fA-F]{40})\s+(\S+)")


def _submodules(dest):
    done = subprocess.run(["git", "-C", str(dest), "submodule", "status"], capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip():
        return []
    urls = _submodule_urls(dest)
    submodules = []
    for line in done.stdout.splitlines():
        match = _SUBMODULE_LINE.match(line)
        if not match:
            continue
        sha, path = match.groups()
        submodules.append({"path": path, "url": urls.get(path, ""), "sha": sha})
    return submodules


def _submodule_urls(dest):
    path = Path(dest) / ".gitmodules"
    if not path.is_file():
        return {}
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return {}
    urls = {}
    for section in parser.sections():
        sub_path = parser[section].get("path")
        if sub_path:
            urls[sub_path] = parser[section].get("url") or ""
    return urls


# --- the inventory -----------------------------------------------------------------------------


def detect_language(dest):
    """`"python"` when the clone has a `*.py` file outside vendored directories, else `"unknown"`."""
    dest = Path(dest)
    for path in dest.rglob("*.py"):
        if not _is_vendored(path, dest):
            return "python"
    return "unknown"


def _is_vendored(path, root):
    return any(part in _VENDORED or part.endswith(".egg-info") for part in path.relative_to(root).parts)


def python_inventory(dest):
    """Every module's functions, classes, `__all__`, and public symbols, read with the stdlib `ast`.

    A module `ast` cannot parse (a syntax error, an encoding it cannot decode) is skipped rather
    than failing the whole dossier: one broken file in a large repository should not cost the
    inventory of every other one.
    """
    dest = Path(dest)
    modules = []
    total = 0
    for path in sorted(dest.rglob("*.py")):
        if _is_vendored(path, dest):
            continue
        rel = path.relative_to(dest).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        dunder_all = _dunder_all(tree)
        functions = [_symbol(node, dunder_all) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [_symbol(node, dunder_all) for node in tree.body if isinstance(node, ast.ClassDef)]
        if dunder_all is not None:
            public_symbols = list(dunder_all)
        else:
            public_symbols = sorted({symbol["name"] for symbol in functions + classes if symbol["public"]})
        modules.append({"path": rel, "all": dunder_all, "functions": functions, "classes": classes, "public_symbols": public_symbols})
        total += len(functions) + len(classes)
    return {"modules": modules, "symbols_total": total, "note": None}


def _dunder_all(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            try:
                return [str(name) for name in ast.literal_eval(node.value)]
            except (ValueError, TypeError):
                return None
    return None


def _symbol(node, dunder_all):
    public = (node.name in dunder_all) if dunder_all is not None else not node.name.startswith("_")
    try:
        decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
    except Exception:  # pragma: no cover - ast.unparse covers every valid decorator expression
        decorators = []
    return {
        "name": node.name,
        "lineno": node.lineno,
        "end_lineno": getattr(node, "end_lineno", None),
        "decorators": decorators,
        "docstring": ast.get_docstring(node),
        "public": public,
    }


def entry_points_of(dest):
    """Entry points from `[project.scripts]`/`[project.entry-points]` and `setup.cfg`'s own table."""
    dest = Path(dest)
    return _pyproject_entry_points(dest / "pyproject.toml") + _setup_cfg_entry_points(dest / "setup.cfg")


def _pyproject_entry_points(path):
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    project = data.get("project") or {}
    entries = [
        {"name": name, "value": value, "group": "console_scripts", "source": "pyproject.toml"}
        for name, value in (project.get("scripts") or {}).items()
    ]
    for group, table in (project.get("entry-points") or {}).items():
        entries.extend({"name": name, "value": value, "group": group, "source": "pyproject.toml"} for name, value in (table or {}).items())
    return entries


def _setup_cfg_entry_points(path):
    if not path.is_file():
        return []
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return []
    if not parser.has_section("options.entry_points"):
        return []
    entries = []
    for group, block in parser.items("options.entry_points"):
        for line in str(block or "").splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            name, value = (part.strip() for part in line.split("=", 1))
            entries.append({"name": name, "value": value, "group": group, "source": "setup.cfg"})
    return entries


def configs_of(dest):
    """Configs by `research-notes/06`: the `configs/`/`config/` directories and the config globs."""
    return _glob_relative(dest, _CONFIG_DIRS, _CONFIG_GLOBS)


def tests_of(dest):
    return _glob_relative(dest, _TEST_DIRS, _TEST_GLOBS)


def _glob_relative(dest, directories, globs):
    dest = Path(dest)
    found = set()
    for directory in directories:
        base = dest / directory
        if base.is_dir():
            found.update(path for path in base.rglob("*") if path.is_file())
    for pattern in globs:
        found.update(dest.rglob(pattern))
    return sorted(path.relative_to(dest).as_posix() for path in found if path.is_file() and not _is_vendored(path, dest))


def scripts_of(dest):
    """Scripts by `scripts/`, `bin/`, `*.sh`, and the `if __name__ == "__main__"` idiom."""
    dest = Path(dest)
    found = set()
    for directory in _SCRIPT_DIRS:
        base = dest / directory
        if base.is_dir():
            found.update(path for path in base.rglob("*") if path.is_file())
    found.update(dest.rglob("*.sh"))
    for path in dest.rglob("*.py"):
        if _is_vendored(path, dest):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _MAIN_IDIOM.search(text):
            found.add(path)
    return sorted(path.relative_to(dest).as_posix() for path in found if not _is_vendored(path, dest))


def data_requirements_of(dest):
    """Every line that names a download call or a data-archive URL, by grep, with its file and line."""
    dest = Path(dest)
    found = []
    for path in sorted(dest.rglob("*.py")):
        if _is_vendored(path, dest):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(dest).as_posix()
        for lineno, line in enumerate(lines, 1):
            match = _DATA_CALL.search(line) or _DATA_URL.search(line)
            if match:
                found.append({"path": rel, "line": lineno, "match": match.group(0)})
    return found


# --- the verified recipe ------------------------------------------------------------------------


_NOT_A_CHECK = frozenset({"__init__.py", "conftest.py"})


def _parsed(path):
    try:
        return ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None


def _holds_a_test(path):
    """Whether a file defines a test: a `test*` function, or a `Test*` or `*TestCase` class.

    UMAP's `umap/tests/test_umap.py` is empty at 0.5.12, and the smallest file is not a proof of
    anything when it holds no test.
    """
    tree = _parsed(path)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            return True
        if isinstance(node, ast.ClassDef):
            bases = [base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "") for base in node.bases]
            if node.name.startswith("Test") or any(name.endswith("TestCase") for name in bases):
                return True
    return False


def _needs_pytest(path, dest):
    """Whether a test file is written for pytest: it imports pytest, or a `conftest.py` sits above it."""
    tree = _parsed(path)
    for node in ast.walk(tree) if tree is not None else ():
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
            [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        if any(name == "pytest" or name.startswith("pytest.") or name.startswith("_pytest") for name in names):
            return True
    dest = Path(dest).resolve()
    directory = Path(path).resolve().parent
    while directory.is_relative_to(dest):
        if (directory / "conftest.py").is_file():
            return True
        if directory == dest:
            break
        directory = directory.parent
    return False


def _pick_check(dest, tests, scripts):
    """The smallest test or example, by file size: the "verified" recipe runs the cheapest proof.

    `tests` also carries `conftest.py`, every `__init__.py`, and the data files under `tests/`
    (research-notes 06 counts the whole directory), none of which holds a test to run; the recipe
    skips them, and any test file that defines no test, and picks the smallest file that does.
    """
    dest = Path(dest)
    candidates = [
        ((dest / relpath).stat().st_size, relpath, "test")
        for relpath in tests
        if relpath.endswith(".py") and Path(relpath).name not in _NOT_A_CHECK and _holds_a_test(dest / relpath)
    ]
    candidates += [((dest / relpath).stat().st_size, relpath, "script") for relpath in scripts if relpath.endswith(".py")]
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], candidates[0][2]


def run_recipe(url, sha, dest, tests, scripts):
    """Install `<url>@<sha>` into a fresh venv and run the smallest test or example found.

    The venv is built `--system-site-packages --without-pip` and driven by this process's own
    `pip --python <venv>`: a fresh `venv` module needs `ensurepip`, which is not always installed
    alongside Python, and the recipe only means to prove the pinned commit installs and runs, not
    to sandbox it from what is already on the machine. Everything the install and the check
    printed is kept in `log`, trimmed to `LOG_MAX` characters, and `verified` is true only when
    both exited 0.
    """
    checked_path, kind = _pick_check(dest, tests, scripts)
    install_command = "pip install --no-build-isolation git+%s@%s" % (url, sha)
    log = []
    work = Path(tempfile.mkdtemp(prefix="wayline-code-recipe-"))
    try:
        venv_dir = work / "venv"
        created = subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", "--without-pip", str(venv_dir)],
            capture_output=True, text=True,
        )
        log.append(_transcript("python -m venv --system-site-packages --without-pip %s" % venv_dir, created))
        if created.returncode != 0:
            return _recipe_record(install_command, created.returncode, checked_path, None, None, log), False
        venv_python = venv_dir / "bin" / "python3"
        install = subprocess.run(
            [sys.executable, "-m", "pip", "--python", str(venv_python), "install", "--no-build-isolation", "git+%s@%s" % (url, sha)],
            capture_output=True, text=True,
        )
        log.append(_transcript(install_command, install))
        if install.returncode != 0 or checked_path is None:
            return _recipe_record(install_command, install.returncode, checked_path, None, None, log), False
        run = _run_check(venv_python, Path(dest), checked_path, kind, work)
        run_command = run["command"]
        log.extend(run.get("setup") or [])
        log.append(_transcript(run_command, run["result"]))
        verified = install.returncode == 0 and run["result"].returncode == 0
        return _recipe_record(install_command, install.returncode, checked_path, run_command, run["result"].returncode, log), verified
    finally:
        shutil.rmtree(work, ignore_errors=True)


PYTEST_INSTALL = "pip install pytest"


def _run_check(venv_python, dest, checked_path, kind, work):
    """Run the picked file; a pytest-style test runs under pytest, installed into the venv first.

    Most research code tests with pytest and its fixtures, which a plain unittest runner cannot
    call, so a test that imports pytest or sits under a `conftest.py` gets pytest in the recipe's
    venv (unless the venv already sees one) and is run as `python -m pytest -q <file>`.
    """
    if kind == "test" and _needs_pytest(dest / checked_path, dest):
        setup = []
        present = subprocess.run([str(venv_python), "-c", "import pytest"], capture_output=True, text=True)
        if present.returncode != 0:
            installed = subprocess.run(
                [sys.executable, "-m", "pip", "--python", str(venv_python), "install", "pytest"], capture_output=True, text=True,
            )
            setup.append(_transcript(PYTEST_INSTALL, installed))
            if installed.returncode != 0:
                return {"command": PYTEST_INSTALL, "result": installed, "setup": setup[:-1]}
        command = "python -m pytest -q -p no:cacheprovider %s" % checked_path
        result = subprocess.run([str(venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider", str(dest / checked_path)],
                                capture_output=True, text=True, cwd=str(dest))
        return {"command": command, "result": result, "setup": setup}
    if kind == "test":
        runner = work / "_wayline_check_runner.py"
        runner.write_text(_MICRO_RUNNER, encoding="utf-8")
        command = "python %s" % checked_path
        result = subprocess.run([str(venv_python), str(runner), str(dest / checked_path)], capture_output=True, text=True, cwd=str(dest))
    else:
        command = "python %s" % checked_path
        result = subprocess.run([str(venv_python), str(dest / checked_path)], capture_output=True, text=True, cwd=str(dest))
    return {"command": command, "result": result}


def _transcript(command, done):
    return "$ %s\n%s%s" % (command, done.stdout, done.stderr)


def _recipe_record(install_command, install_exit_code, checked_path, run_command, exit_code, log):
    return {
        "install_command": install_command,
        "install_exit_code": install_exit_code,
        "checked_path": checked_path,
        "run_command": run_command,
        "exit_code": exit_code,
        "log": "\n".join(log)[-LOG_MAX:],
    }


# --- the record ----------------------------------------------------------------------------------


def code_dossier(slug, url, sha, dest, created=None):
    """The mechanical inventory and the verified recipe for one pinned commit, as a validated record."""
    dest = Path(dest)
    language = detect_language(dest)
    if language == "python":
        inventory = python_inventory(dest)
        entry_points = entry_points_of(dest)
    else:
        inventory = {"modules": [], "symbols_total": 0, "note": "universal-ctags or tree-sitter is not yet wired for %s" % language}
        entry_points = []
    tests = tests_of(dest)
    scripts = scripts_of(dest)
    recipe, verified = run_recipe(url, sha, dest, tests, scripts)
    dossier = {
        "schema_version": 1,
        "slug": slug,
        "source": git_metadata(dest, url),
        "language": language,
        "inventory": inventory,
        "entry_points": entry_points,
        "configs": configs_of(dest),
        "tests": tests,
        "scripts": scripts,
        "data_requirements": data_requirements_of(dest),
        "verified": verified,
        "recipe": recipe,
        "api_map": [
            {"module": module["path"], "good": [], "bad": [], "risky": [], "reusable": [], "how_to_call": None}
            for module in inventory["modules"]
        ],
        "created": created or now_ts(),
    }
    check(dossier, load_schema("code_dossier"), name="refs/%s/code_dossier.json" % slug)
    return dossier


def write_code_dossier(project_or_ledger, dossier):
    """Write `refs/<slug>/code_dossier.json` and journal the absorption."""
    ledger = ledger_for(project_or_ledger)
    path = ledger.write_json("%s/%s/code_dossier.json" % (REFS, dossier["slug"]), dossier, schema="code_dossier")
    ledger.append_event("absorbed", {"slug": dossier["slug"]})
    return path


def absorb_code(project, slug, url, sha, ledger=None):
    """Clone `url` at `sha` under `refs/<slug>/code/`, build its dossier, and write it. Returns `(dossier, path)`."""
    project = Path(project)
    ledger = ledger_for(ledger if ledger is not None else project)
    dest = ledger.research / REFS / slug / CODE_DIR
    clone_at_sha(url, sha, dest)
    dossier = code_dossier(slug, url, sha, dest)
    path = write_code_dossier(ledger, dossier)
    return dossier, path


# --- the verb --------------------------------------------------------------------------------------


def code_command(args):
    parser = argparse.ArgumentParser(prog="wayline absorb --code", description="build a code dossier for one paper's pinned commit")
    parser.add_argument("--code", nargs=2, metavar=("SLUG", "URL@SHA"), required=True, help="the refs/ slug and the <url>@<sha> to pin")
    parser.add_argument("--project", help="the project to absorb into; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the code dossier as JSON instead of text")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    slug, reference = options.code
    try:
        url, sha = parse_code_reference(reference)
        project = find_project(options.project)
        dossier, path = absorb_code(project, slug, url, sha)
    except (ProjectError, CodeDossierError, ValidationError, ValueError, OSError) as failure:
        print("wayline absorb --code: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(dossier, ensure_ascii=False, indent=2))
    else:
        print(_render(dossier, path))
    return 0 if dossier["verified"] else 1


def _render(dossier, path):
    lines = [
        "code dossier   %s" % path,
        "slug           %s" % dossier["slug"],
        "sha            %s" % dossier["source"]["sha"],
        "language       %s" % dossier["language"],
        "modules        %d  (%d symbols)" % (len(dossier["inventory"]["modules"]), dossier["inventory"]["symbols_total"]),
        "entry points   %d" % len(dossier["entry_points"]),
        "tests          %d" % len(dossier["tests"]),
        "verified       %s" % dossier["verified"],
    ]
    log = dossier["recipe"]["log"].strip()
    if not dossier["verified"] and log:
        lines.append("  recipe: %s" % log.splitlines()[-1])
    return "\n".join(lines)
