"""The rule from code to Methods (Implementation Decision 17; ticket 107).

Methods and the code never drift apart: at each acceptance a Type-A check runs over the ticket's diff in
`code/`, with parsers that spend no tokens, and a failure sends the worker back with the list.

- **Developed methods.** Every function or class the diff adds or changes is named by a `code` tag
  (`{code:code/<path>#<symbol>}` or `#L10-L42`) in a current Methods passage, the ticket's own included.
  Plumbing is excluded by code (`plumbing`): a private or dunder name, `main` and the I/O prefixes of
  `PLUMBING_PREFIXES`, a test, and files under `tests/` and `docs/` or named `setup.py` or `conftest.py`.
  Anything else the worker calls not a method goes in the result's `not_methods`, which passes this check
  and goes to the verifier's verdict.
- **Used methods.** Every call the diff adds that the alias table (`methods/aliases.json`) lists, such
  as `scipy.signal.hilbert`, is named in a current Methods passage by one of its aliases.
- **Parameters.** Every non-default parameter the diff sets on a method (a developed one or a used one,
  or a call the documented-defaults table knows), every numeric default a developed method the diff
  adds or changes gives itself, and every sensitive default left unset (an unseeded random state,
  default solver tolerances) has a one-sentence reason in the result's `parameters`. Code fills each
  entry's value and default; an entry no parser saw is the worker's, with the value it gives.

**The parsers.** Python is read with `ast`, and a library call's defaults come from `inspect.signature`
run in the project's own environment (`environment.resolve(project, "python")`), so they are the pinned
versions' defaults; until that environment is installed a library default is recorded as "not checked"
and does not fail the check. MATLAB is parsed by tree-sitter-matlab in the tools venv
(`converters/matlab_parse.py`, run through `tools.run_recorded`), its library calls read against the
documented-defaults table (`methods/defaults.json`), and a parameter given as a variable is traced back
to its value by a backward slice through the function's assignments and its `nargin` defaults. The same
parse fills the code dossier's `methods` (`inventory`). A changed file in any other language, or a MATLAB
file the parser could not read, gets one Sonnet reading at acceptance (the `code-reader` role, about
$0.40 per 1,000 lines), and each item it names is kept only when grep finds it in the file; its usage
rides on the acceptance result, beside the ticket's own, until that language's first project files an
adapter as a harness ticket.
"""

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from wayline import HARNESS_ROOT, sections
from wayline.ledger import ledger_for
from wayline.tools import ToolsError, Tools, failure_line, run_recorded, run_tool

__all__ = [
    "CHECK", "NOT_CHECKED", "UNSET", "UNSEEDED", "READER", "READING_SCHEMA", "CODE", "MethodsError", "Item", "Outcome",
    "check", "aliases", "defaults", "plumbing", "code_tags", "methods_text", "changed_lines", "python_items",
    "matlab_parse", "matlab_items", "signatures", "SIGNATURE_PROBE", "inventory", "code_rule", "write_code_rule",
    "read_code_rule", "CODE_RULE_FILE",
]

CHECK = "wayline: the code and Methods agree"
CODE = "code"
NOT_CHECKED = "not checked"
UNSET = "unset"
UNSEEDED = "unseeded"
OWN_DEFAULT = None  # a developed method's own default has no library default behind it
READER = "code-reader"
READING_SCHEMA = "code_reading"
MATLAB_TOOL = "tree-sitter-matlab"
MATLAB_PARSER = HARNESS_ROOT / "converters" / "matlab_parse.py"
TABLES = HARNESS_ROOT / "methods"
CODE_RULE_FILE = "methods.json"  # beside a ticket attempt's session: the filled parameters and not_methods for its verdict
GIT_TIMEOUT_S = 120
PROBE_TIMEOUT_S = 300

PLUMBING_PREFIXES = ("load_", "save_", "read_", "write_", "plot_", "print_", "parse_", "test_")
PLUMBING_NAMES = frozenset({"main", "cli", "setup", "run", "test"})
PLUMBING_FILES = frozenset({"setup.py", "conftest.py", "noxfile.py", "tasks.py"})
PLUMBING_DIRS = frozenset({"tests", "test", "docs", "examples", "benchmarks"})
# Changed files the reading takes: source in a language the parsers do not read.
OTHER_SOURCES = frozenset({".jl", ".r", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".f", ".f90", ".f95", ".for", ".rs", ".go",
                           ".java", ".js", ".ts", ".cu", ".scala", ".kt", ".swift", ".rb", ".pl", ".lua", ".nim", ".zig"})
READING_MAX_CHARS = 120000  # what one reading is sent; a file past it is not read and is said to be not checked

_CODE_TAG = re.compile(r"\{code:([^#{}\s]+)#([^{}\s]+)\}")
_LINES = re.compile(r"^L([1-9][0-9]*)(?:-L?([1-9][0-9]*))?$")
_HUNK = re.compile(r"^@@ -[0-9]+(?:,[0-9]+)? \+([0-9]+)(?:,([0-9]+))? @@")

SIGNATURE_PROBE = """\
import importlib, inspect, json, sys
found = {}
for name in json.loads(sys.argv[1]):
    parts = name.split(".")
    try:
        target, rest = None, []
        for cut in range(len(parts), 0, -1):
            try:
                target = importlib.import_module(".".join(parts[:cut]))
                rest = parts[cut:]
                break
            except ImportError:
                continue
        if target is None:
            raise ImportError("no module of %s imports" % name)
        for attr in rest:
            target = getattr(target, attr)
        params = []
        for param in inspect.signature(target).parameters.values():
            empty = param.default is inspect.Parameter.empty
            params.append({"name": param.name, "kind": param.kind.name, "has_default": not empty,
                           "default": None if empty else repr(param.default)})
        found[name] = {"params": params}
    except Exception as failure:
        found[name] = {"error": "%s: %s" % (type(failure).__name__, failure)}
print(json.dumps({"signatures": found}))
"""


class MethodsError(ValueError):
    """The check could not read the ticket's diff: no `main`, a git that failed."""


@dataclass
class Item:
    """One thing a parser saw in the diff: a developed method, a used method, or a parameter."""

    kind: str                 # "developed", "used", or "parameter"
    path: str                 # project-relative, under code/
    name: str                 # the symbol; the call's qualified name; the parameter's name
    line: int
    end: int = None
    method: str = None        # a used method's plain name; a parameter's method (the callee or the developed method)
    value: str = None
    default: str = None
    what: str = "set"         # a parameter: "set", "own default", "unseeded", or "tolerance"
    needs_reason: bool = True
    aliases: tuple = ()

    @property
    def where(self):
        return "%s:%d" % (self.path, self.line)


@dataclass
class Outcome:
    """What the check found: `problems` sends the worker back; the rest is for the verdict and the ticket's Result."""

    problems: list = field(default_factory=list)
    parameters: list = field(default_factory=list)   # the result's `parameters`, each with code's value and default
    not_methods: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    items: list = field(default_factory=list)
    reading: dict = None                              # the Sonnet reading's session, model, usage, and lines, when one ran
    refused: object = None                            # the `UsageLimited` a usage window refused the reading with

    @property
    def passed(self):
        return not self.problems

    def acceptance_result(self):
        """The check as one acceptance result, the shape `gates.run_machine_acceptance` gives a command."""
        developed = sum(1 for item in self.items if item.kind == "developed")
        used = sum(1 for item in self.items if item.kind == "used")
        summary = ("%d developed method(s), %d used method(s), and %d parameter(s) with reasons agree with Methods"
                   % (developed, used, len(self.parameters)))
        lines = list(self.problems) if self.problems else [summary]
        lines += self.notes
        result = {"cmd": CHECK, "exit_code": 1 if self.problems else 0, "seconds": 0.0, "tail": "\n".join(lines)}
        if self.reading is not None:
            result["reading"] = dict(self.reading)
        return result

    def code_rule(self):
        return {"parameters": [dict(entry) for entry in self.parameters], "not_methods": [dict(entry) for entry in self.not_methods]}


# --- the tables ----------------------------------------------------------------------------------------


def _table(name):
    return json.loads((TABLES / ("%s.json" % name)).read_text(encoding="utf-8"))


def aliases():
    """The alias table: `{language: {call: {method, aliases}}}`."""
    table = _table("aliases")
    return {language: table.get(language) or {} for language in ("python", "matlab")}


def defaults():
    """The documented-defaults table: Python's tolerances, seeds, and global random states; MATLAB's functions."""
    table = _table("defaults")
    return {"python": table.get("python") or {}, "matlab": table.get("matlab") or {}}


# --- plumbing --------------------------------------------------------------------------------------------


def plumbing(path, name):
    """Whether code excludes `name` in `path` from the rule: plumbing rather than a method the paper describes."""
    parts = Path(path).parts
    base = Path(path).name
    if base in PLUMBING_FILES or any(part in PLUMBING_DIRS for part in parts[:-1]):
        return True
    if base.startswith("test_") or base.endswith("_test.py"):
        return True
    last = name.split(".")[-1]
    if last.startswith("_"):
        return True
    lowered = last.lower()
    return lowered in PLUMBING_NAMES or lowered.startswith(PLUMBING_PREFIXES)


# --- the diff ---------------------------------------------------------------------------------------------


def _git(run, cwd, *args):
    done = run(["git", "-C", str(cwd), *args], timeout=GIT_TIMEOUT_S)
    if done.returncode != 0:
        raise MethodsError("git %s: %s" % (" ".join(args), failure_line(done)))
    return done.stdout.decode("utf-8", errors="replace")


def changed_lines(worktree, base="main", run=run_tool):
    """`{path: set of changed line numbers, or None for a whole new file}` of `code/` against `base`'s merge base.

    The working tree is compared, so a change not yet committed counts, and an untracked file under `code/` is
    a new file. A deleted file is not listed; a deletion inside a file marks the line it was cut at.
    """
    base_commit = _git(run, worktree, "merge-base", base, "HEAD").strip()
    names = _git(run, worktree, "diff", "--name-status", "--no-renames", base_commit, "--", CODE + "/")
    changed = {}
    for line in names.splitlines():
        status, _, path = line.partition("\t")
        if status.startswith("D") or not path:
            continue
        changed[path] = None if status.startswith("A") else set()
    for path in _git(run, worktree, "ls-files", "--others", "--exclude-standard", "--", CODE + "/").splitlines():
        if path.strip():
            changed[path.strip()] = None
    modified = [path for path, lines in changed.items() if lines is not None]
    if modified:
        current = None
        for line in _git(run, worktree, "diff", "-U0", "--no-renames", base_commit, "--", *modified).splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else None
                continue
            found = _HUNK.match(line)
            if found and current in changed and changed[current] is not None:
                start, count = int(found.group(1)), int(found.group(2) if found.group(2) is not None else 1)
                changed[current].update(range(start, start + count) if count else (max(start, 1), start + 1))
    return changed


def _touches(lines, start, end):
    return lines is None or any(start <= number <= (end or start) for number in lines)


# --- Methods ---------------------------------------------------------------------------------------------


def methods_text(project_or_ledger, result):
    """The current Methods passages' texts once this result's are taken in: what the tags and aliases are read from.

    The ledger's current Methods passages, less any the result's passages replace, and the result's own Methods
    passages, which are filed only once the ticket is integrated.
    """
    book = ledger_for(project_or_ledger)
    own = [item for item in (result or {}).get("passages") or [] if isinstance(item, dict) and item.get("section") == "methods"]
    replaced = {item.get("replaces") for item in own if item.get("replaces")}
    held = [item for item in sections.read_passages(book) if item.get("section") == "methods"]
    current = [item for item in sections.arrange(held).current() if item.get("id") not in replaced]
    return [str(item.get("text") or "") for item in current] + [str(item.get("text") or "") for item in own]


def code_tags(texts):
    """Every `code` tag in `texts`, as `(path, locator)`."""
    return [found.groups() for text in texts for found in _CODE_TAG.finditer(text)]


def _same_path(tag_path, path):
    tag_path = tag_path[2:] if tag_path.startswith("./") else tag_path
    return tag_path == path or "%s/%s" % (CODE, tag_path) == path


def _tagged(item, tags):
    for tag_path, locator in tags:
        if not _same_path(tag_path, item.path):
            continue
        lines = _LINES.match(locator)
        if lines:
            start, end = int(lines.group(1)), int(lines.group(2) or lines.group(1))
            if start <= (item.end or item.line) and item.line <= end:
                return True
        elif locator == item.name or item.name.startswith(locator + ".") or item.name.split(".")[-1] == locator:
            return True
    return False


def _names(alias, text):
    return re.search(r"(?<!\w)%s(?!\w)" % re.escape(alias), text, re.IGNORECASE) is not None


def _short(name):
    return str(name or "").split(".")[-1].split("#")[-1].strip().lower()


# --- Python -------------------------------------------------------------------------------------------------


def _literal(node):
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _numeric(node):
    ok, value = _literal(node)
    return ok and isinstance(value, (int, float)) and not isinstance(value, bool)


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return list(reversed(parts))
    return None


def _imports(tree, local_roots):
    """`{local name: qualified name}`, and the names that come from the project's own code."""
    names, local = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                names[bound] = alias.name if alias.asname else alias.name.split(".")[0]
                if alias.name.split(".")[0] in local_roots:
                    local.add(bound)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                names[bound] = "%s.%s" % (node.module, alias.name) if node.module else alias.name
                if node.level or (node.module or "").split(".")[0] in local_roots:
                    local.add(bound)
    return names, local


def _definitions(tree):
    """`(qualified name, node, start, end)` of every module-level function and class and every class's methods."""
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
            found.append((node.name, node, start, node.end_lineno))
            if isinstance(node, ast.ClassDef):
                for inner in node.body:
                    if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        inner_start = min([inner.lineno] + [decorator.lineno for decorator in inner.decorator_list])
                        found.append(("%s.%s" % (node.name, inner.name), inner, inner_start, inner.end_lineno))
    return found


def _own_defaults(node):
    """`(name, default node)` of a function's parameters that carry a default."""
    arguments = node.args
    positional = arguments.posonlyargs + arguments.args
    pairs = list(zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults))
    pairs += [(arg, default) for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults) if default is not None]
    return [(arg.arg, default) for arg, default in pairs]


def _ast_signature(node):
    """A project function's parameters in the probe's shape, its defaults as source text."""
    defaults = dict(_own_defaults(node))
    arguments = node.args
    params = [{"name": arg.arg, "kind": "POSITIONAL_OR_KEYWORD", "has_default": arg.arg in defaults,
               "default": ast.unparse(defaults[arg.arg]) if arg.arg in defaults else None}
              for arg in arguments.posonlyargs + arguments.args]
    params += [{"name": arg.arg, "kind": "KEYWORD_ONLY", "has_default": arg.arg in defaults,
                "default": ast.unparse(defaults[arg.arg]) if arg.arg in defaults else None} for arg in arguments.kwonlyargs]
    if params and params[0]["name"] in ("self", "cls"):
        params = params[1:]
    return params


def project_functions(worktree):
    """`{bare name: signature}` of every function the project's Python under `code/` defines, and its top-level names."""
    root = Path(worktree) / CODE
    found, roots = {}, set()
    if not root.is_dir():
        return found, roots
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        roots.add(relative.parts[0][:-3] if len(relative.parts) == 1 else relative.parts[0])
        if relative.parts[0] == "src" and len(relative.parts) > 1:
            roots.add(relative.parts[1][:-3] if len(relative.parts) == 2 else relative.parts[1])
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for name, node, _, _ in _definitions(tree):
            if isinstance(node, ast.ClassDef):
                init = next((inner for inner in node.body if isinstance(inner, ast.FunctionDef) and inner.name == "__init__"), None)
                found.setdefault(name, _ast_signature(init) if init is not None else [])
            else:
                found.setdefault(name.split(".")[-1], _ast_signature(node))
    return found, roots


def _enclosing_assignments(tree, call):
    """A backward slice: `({name: value node}, parameter names)` before `call` in its innermost function (or the module).

    Each name keeps its last single-name assignment by line before the call; the parameter names are the enclosing
    function's own, which a call that passes one on forwards rather than sets.
    """
    scope = tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= call.lineno <= (node.end_lineno or node.lineno):
            if scope is tree or node.lineno >= scope.lineno:
                scope = node
    found = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and node.lineno < call.lineno:
            for target in node.targets:
                if isinstance(target, ast.Name) and (target.id not in found or found[target.id][0] <= node.lineno):
                    found[target.id] = (node.lineno, node.value)
    params = set()
    if scope is not tree:
        arguments = scope.args
        params = {arg.arg for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}
    return {name: value for name, (_, value) in found.items()}, params


def _value_of(node, assigned, depth=0):
    """`(source text, literal or None, known)` of an argument, following a name back through its assignments."""
    ok, value = _literal(node)
    if ok:
        return ast.unparse(node), value, True
    if isinstance(node, ast.Name) and node.id in assigned and depth < 5:
        return _value_of(assigned[node.id], assigned, depth + 1)
    return ast.unparse(node), None, False


def _forwarded(node, assigned, params):
    """Whether an argument passes on the enclosing function's own parameter, unchanged: its value is the caller's."""
    return isinstance(node, ast.Name) and node.id in params and node.id not in assigned


def _differs(value_text, value, default_text):
    if default_text is None:
        return True
    try:
        return ast.literal_eval(default_text) != value
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return value_text != default_text


def python_items(path, text, lines, functions=None, roots=(), tables=None, signatures_of=None):
    """What the Python parser sees in one changed file: `(items, library calls whose signatures it wants)`.

    `lines` is the set of changed lines (None for a new file); `functions` and `roots` are `project_functions`';
    `signatures_of(names)` answers `{name: params}` from the project's environment for the library calls the file makes
    that the tables know, or None when that environment is not installed (every such default is then not checked).
    """
    tables = tables or {"aliases": aliases(), "defaults": defaults()}
    functions = functions or {}
    used_table = tables["aliases"]["python"]
    python = tables["defaults"]["python"]
    tolerances, seeds = python.get("tolerances") or {}, python.get("seeds") or {}
    seed_names = set(python.get("seed_names") or ())
    seeds_first = set(python.get("seeds_first") or ())
    global_random = python.get("global_random") or {}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [Item("developed", path, "<the whole file>", 1, None, needs_reason=False, what="unparsed")], []
    items, wanted = [], set()
    for name, node, start, end in _definitions(tree):
        if isinstance(node, ast.ClassDef):
            inner = [(inner.lineno, inner.end_lineno) for inner in node.body if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))]
            own = [number for number in range(start, (end or start) + 1) if not any(a <= number <= b for a, b in inner)]
            touched = lines is None or any(number in lines for number in own)
        else:
            touched = _touches(lines, start, end)
        if not touched or plumbing(path, name):
            continue
        items.append(Item("developed", path, name, start, end))
        if not isinstance(node, ast.ClassDef):
            for param, default in _own_defaults(node):
                if _numeric(default):
                    items.append(Item("parameter", path, param, default.lineno, method=name, value=ast.unparse(default),
                                      default=OWN_DEFAULT, what="own default"))
    imported, local = _imports(tree, set(roots))
    defined_here = {name.split(".")[-1] for name, _, _, _ in _definitions(tree)}
    seeded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if dotted and dotted[0] in imported and dotted[0] not in local:
                seeded.add(".".join([imported[dotted[0]]] + dotted[1:]))
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _touches(lines, node.lineno, node.end_lineno):
            continue
        dotted = _dotted(node.func)
        if not dotted:
            continue
        if dotted[0] in local or (len(dotted) == 1 and dotted[0] in defined_here):
            callee, is_local = dotted[-1], True
        elif dotted[0] in imported:
            callee, is_local = ".".join([imported[dotted[0]]] + dotted[1:]), False
        else:
            continue
        calls.append((node, callee, is_local))
        if not is_local and (callee in used_table or callee in tolerances or callee in seeds):
            wanted.add(callee)
    signatures = signatures_of(sorted(wanted)) if signatures_of is not None else None
    for node, callee, is_local in calls:
        if is_local:
            if plumbing(path, callee) or callee not in functions:
                continue
            params, checked = functions[callee], True
        elif callee in wanted:
            entry = (signatures or {}).get(callee) if signatures is not None else None
            params, checked = ((entry or {}).get("params") or [], signatures is not None and "params" in (entry or {}))
            if callee in used_table:
                items.append(Item("used", path, callee, node.lineno, node.end_lineno, method=used_table[callee].get("method"),
                                  aliases=tuple(used_table[callee].get("aliases") or ()) + (used_table[callee].get("method") or "",),
                                  needs_reason=False))
        else:
            module, _, attr = callee.rpartition(".")
            random = global_random.get(module)
            if random and attr in (random.get("draws") or ()) and random.get("seeded_by") not in seeded:
                items.append(Item("parameter", path, "seed", node.lineno, method=callee, value=UNSET, default=UNSEEDED,
                                  what=UNSEEDED))
            continue
        assigned, enclosing = _enclosing_assignments(tree, node)
        by_name = {param["name"]: param for param in params}
        given = {}
        positional = [param for param in params if param.get("kind") in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
        for index, argument in enumerate(node.args):
            if isinstance(argument, ast.Starred) or index >= len(positional):
                break
            given[positional[index]["name"]] = argument
        for keyword in node.keywords:
            if keyword.arg is not None:
                given[keyword.arg] = keyword.value
        documented = tolerances.get(callee) or {}
        for name, argument in given.items():
            param = by_name.get(name)
            if _forwarded(argument, assigned, enclosing):
                continue  # the enclosing method's own parameter passed on: its default is checked where it is defined
            value_text, value, known = _value_of(argument, assigned)
            if name in documented:
                default_shown = documented[name]
            elif not checked:
                items.append(Item("parameter", path, name, argument.lineno, method=callee, value=value_text, default=NOT_CHECKED,
                                  needs_reason=False))
                continue
            elif param is None or not param.get("has_default"):
                continue  # a required argument is the method's data; a keyword the signature does not name goes to **kwargs
            else:
                default_shown = param.get("default")
            # A value the slice cannot resolve is set all the same: only the worker can say what it is and why.
            if known and not _differs(value_text, value, default_shown):
                continue
            items.append(Item("parameter", path, name, argument.lineno, method=callee, value=value_text, default=default_shown))
        for name, default_text in documented.items():
            if name not in given:
                items.append(Item("parameter", path, name, node.lineno, method=callee, value=UNSET, default=default_text,
                                  what="tolerance"))
        seed = seeds.get(callee)
        if seed and callee in seeds_first and node.args and not isinstance(node.args[0], ast.Starred):
            given.setdefault(seed, node.args[0])  # a generator seeded by its first positional argument, with no signature to say so
        if seed in given and _literal(given[seed]) == (True, None):
            del given[seed]  # `seed=None` draws fresh entropy: unseeded
        names = {seed} if seed else set()
        names |= {param["name"] for param in params
                  if param["name"] in seed_names and param.get("has_default") and param.get("default") == "None"}
        for name in sorted(names):
            if name not in given:
                items.append(Item("parameter", path, name, node.lineno, method=callee, value=UNSET, default=UNSEEDED, what=UNSEEDED))
    return items, sorted(wanted)


# --- MATLAB -------------------------------------------------------------------------------------------------


def matlab_parse(path, run=run_tool, tools=None):
    """tree-sitter-matlab's parse of one `.m` file, through the tool runner; `ToolsError` when it cannot be read."""
    done = run_recorded(MATLAB_TOOL, [str(MATLAB_PARSER), str(path)], tools=tools, run=run)
    if done.returncode != 0:
        raise ToolsError("tree-sitter-matlab could not parse %s: %s" % (path, failure_line(done)))
    try:
        parsed = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        raise ToolsError("tree-sitter-matlab printed no parse for %s" % path) from None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("functions"), list):
        raise ToolsError("tree-sitter-matlab printed no parse for %s" % path)
    if parsed.get("has_error"):
        raise ToolsError("tree-sitter-matlab read %s only in part: it has a syntax error" % path)
    return parsed


def _slice(name, function, line, parsed, depth=0):
    """A MATLAB variable's value at `line`: its last assignment before it in `function`, else its `nargin` default.

    Returns `(text, known)`: a number or a string is known; anything else is the text it was assigned.
    """
    assigned = [entry for entry in parsed.get("assignments") or []
                if entry.get("name") == name and entry.get("function") == function and entry.get("line", 0) < line]
    if not assigned:
        for entry in parsed.get("nargin_defaults") or []:
            if entry.get("name") == name and entry.get("function") == function:
                return entry.get("value"), entry.get("kind") in ("number", "string")
        return name, False
    last = max(assigned, key=lambda entry: entry.get("line", 0))
    if last.get("kind") == "identifier" and depth < 5:
        return _slice(last.get("value"), function, last.get("line", 0), parsed, depth + 1)
    return last.get("value"), last.get("kind") in ("number", "string")


def _unquote(text):
    text = str(text or "").strip()
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" else text


def _same(value, default):
    """Whether a MATLAB value is its default as written: equal numbers (`0.001` and `1e-3`), or equal text unquoted."""
    if value is None or default is None:
        return False
    try:
        return float(str(value).strip()) == float(str(default).strip())
    except ValueError:
        return " ".join(_unquote(value).lower().split()) == " ".join(_unquote(default).lower().split())


def matlab_items(path, parsed, lines, tables=None):
    """What the MATLAB parse shows in one changed file, read against the alias and documented-defaults tables."""
    tables = tables or {"aliases": aliases(), "defaults": defaults()}
    used_table, documented = tables["aliases"]["matlab"], tables["defaults"]["matlab"]
    items = []
    functions = parsed.get("functions") or []
    for function in functions:
        name = function.get("name") or ""
        if not name or not _touches(lines, function.get("start", 1), function.get("end")) or plumbing(path, name):
            continue
        items.append(Item("developed", path, name, function.get("start", 1), function.get("end")))
        for entry in parsed.get("nargin_defaults") or []:
            if entry.get("function") == name and entry.get("kind") == "number":
                items.append(Item("parameter", path, entry.get("name"), entry.get("line", 1), method=name, value=entry.get("value"),
                                  default=OWN_DEFAULT, what="own default"))
    variables = {}
    for function in functions:
        variables.setdefault(function.get("name"), set()).update(function.get("params") or [])
    for entry in parsed.get("assignments") or []:
        variables.setdefault(entry.get("function"), set()).add(entry.get("name"))
    seeded_at = [call.get("line", 0) for call in parsed.get("calls") or [] if call.get("name") == "rng"]
    by_line = {}
    for call in parsed.get("calls") or []:
        by_line.setdefault((call.get("function"), call.get("line")), []).append(call)
    for call in parsed.get("calls") or []:
        name, where, line = call.get("name"), call.get("function"), call.get("line", 1)
        if name in variables.get(where, ()) or not _touches(lines, line, call.get("end")):
            continue  # indexing into a variable is written the way a call is
        if name in used_table:
            entry = used_table[name]
            items.append(Item("used", path, name, line, call.get("end"), method=entry.get("method"),
                              aliases=tuple(entry.get("aliases") or ()) + (entry.get("method") or "",), needs_reason=False))
        spec = documented.get(name)
        if spec is None:
            continue
        if spec.get("random") and not any(seed < line for seed in seeded_at):
            items.append(Item("parameter", path, "seed", line, method=name, value=UNSET, default=UNSEEDED, what=UNSEEDED))
        arguments = call.get("args") or []
        positional = list(spec.get("args") or [])
        name_values = spec.get("name_values") or {}
        options_arg = spec.get("options")
        options_given = None
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            text = argument.get("text") or ""
            if argument.get("kind") == "string" and _unquote(text) in name_values and index + 1 < len(arguments):
                option = _unquote(text)
                value, known = _value_at(arguments[index + 1], where, line, parsed)
                if value is not None and not _same(value, name_values[option]):
                    items.append(Item("parameter", path, option, line, method=name, value=value, default=name_values[option],
                                      needs_reason=True))
                index += 2
                continue
            if index < len(positional):
                param = positional[index]
                if param == options_arg:
                    options_given = argument
                elif param not in (spec.get("data") or ()) and text.strip() != "[]":
                    value, known = _value_at(argument, where, line, parsed)
                    default = (spec.get("defaults") or {}).get(param)
                    if value is not None and not _same(value, default):
                        items.append(Item("parameter", path, param, line, method=name, value=value,
                                          default=default if default is not None else "none (required)", needs_reason=True))
            index += 1
        tolerances = spec.get("tolerances") or {}
        if tolerances:
            # A tolerance the options structure sets is the `odeset` call's own parameter, read where that call is; one
            # it leaves out runs at the solver's default.
            set_options = _options_set(options_given, where, line, parsed, by_line)
            for option, default in tolerances.items():
                if option not in set_options:
                    items.append(Item("parameter", path, option, line, method=name, value=UNSET, default=default, what="tolerance"))
    return items


def _value_at(argument, function, line, parsed):
    """`(text, known)` of a MATLAB argument; `(None, False)` for the enclosing function's own argument passed on."""
    if argument.get("kind") == "identifier":
        text, known = _slice(argument.get("text"), function, line, parsed)
        params = next((entry.get("params") or [] for entry in parsed.get("functions") or [] if entry.get("name") == function), [])
        if not known and text == argument.get("text") and text in params:
            return None, False
        return text, known
    return argument.get("text"), argument.get("kind") in ("number", "string")


def _options_set(argument, function, line, parsed, by_line):
    """The name-value options an options structure sets: `odeset(...)` traced back from the argument that carries it."""
    if argument is None:
        return {}
    call_line = None
    if argument.get("kind") == "identifier":
        assigned = [entry for entry in parsed.get("assignments") or []
                    if entry.get("name") == argument.get("text") and entry.get("function") == function and entry.get("line", 0) < line]
        if assigned:
            call_line = max(assigned, key=lambda entry: entry.get("line", 0)).get("line")
    elif argument.get("kind") == "function_call":
        call_line = line
    found = {}
    for call in by_line.get((function, call_line), []):
        if call.get("name") not in ("odeset", "optimset", "optimoptions"):
            continue
        arguments = call.get("args") or []
        for index in range(len(arguments) - 1):
            if arguments[index].get("kind") == "string":
                value, _ = _value_at(arguments[index + 1], function, line, parsed)
                found[_unquote(arguments[index].get("text"))] = value
    return found


# --- the project's environment ------------------------------------------------------------------------------


def signatures(project, names, run=run_tool, tools=None):
    """`{name: {params} or {error}}` from `inspect.signature` in the project's environment; None when it is not installed."""
    if not names:
        return {}
    from wayline import environment

    try:
        resolved = environment.resolve(project, environment.PYTHON, tools)
    except (ToolsError, ValueError, OSError):
        return None
    done = run(list(resolved.argv) + ["-c", SIGNATURE_PROBE, json.dumps(list(names))], timeout=PROBE_TIMEOUT_S,
               env=resolved.env or None)
    if done.returncode != 0:
        return None
    try:
        found = json.loads(done.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]).get("signatures")
    except (ValueError, IndexError, AttributeError):
        return None
    return found if isinstance(found, dict) else None


# --- the reading of another language ------------------------------------------------------------------------


def _numbered(text):
    return "\n".join("%5d  %s" % (number, line) for number, line in enumerate(text.splitlines(), start=1))


def _reading_prompt(files):
    parts = ["# The changed files", "",
             "Each file is given whole, with its line numbers, and the lines this ticket changed (all of them for a new "
             "file). Report what the changed lines develop, use, and set, as the schema asks, and nothing else."]
    for path, text, lines in files:
        changed = "all (a new file)" if lines is None else ", ".join(str(number) for number in sorted(lines)) or "none"
        parts += ["", "## `%s`" % path, "", "Changed lines: %s" % changed, "", "```", _numbered(text), "```"]
    return "\n".join(parts) + "\n"


def _reading(project, files, *, policy, harness_root, ticket=None, attempt=None):
    """One Sonnet reading of `files` (`(path, text, lines)`): its structured answer and the envelope's accounting."""
    from wayline import provenance, worker

    role = worker.read_role(READER, harness_root, project)
    base = provenance.session_dir(project, "code-reading") if ticket is None else \
        Path(project) / "research" / "sessions" / str(ticket) / str(attempt or 1) / "code-reading"
    run_dir = base
    number = 1
    while run_dir.exists():
        number += 1
        run_dir = base.parent / ("%s-%d" % (base.name, number))
    prompt = _reading_prompt(files) + "\n" + worker.schema_section("# What you return", READING_SCHEMA)
    request = provenance.structured_request(project, role, policy, harness_root, prompt, READING_SCHEMA, "small", run_dir)
    envelope = worker.launch(request)
    provenance.raise_if_refused(envelope, "code reading", request.model)
    problem = provenance.schema_problem(envelope, READING_SCHEMA)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, provenance.RESUME_STRUCTURED % problem)
        provenance.raise_if_refused(envelope, "code reading", request.model)
        problem = provenance.schema_problem(envelope, READING_SCHEMA)
    accounting = {"session_id": envelope.session_id, "model": envelope.model or request.model, "usage": envelope.usage,
                  "lines": sum(len(text.splitlines()) for _, text, _ in files), "files": [path for path, _, _ in files]}
    if problem is not None:
        raise MethodsError("the code reading's answer could not be used: %s" % problem)
    return envelope.structured_output, accounting


def _grepped(word, text):
    """Whether `word` is in `text`: as a whole word when it starts and ends with one, else as it is written."""
    word = str(word or "").strip()
    if not word:
        return False
    if re.match(r"^\w", word) and re.search(r"\w$", word):
        return _names(word, text)
    return word in text


def reading_items(answer, texts):
    """The reading's items kept where grep finds them in the file, and a note on each dropped."""
    items, dropped = [], []
    for entry in answer.get("files") or []:
        path = entry.get("path")
        text = texts.get(path)
        if text is None:
            continue
        for found in entry.get("developed") or []:
            if _grepped(found.get("name"), text):
                items.append(Item("developed", path, found["name"], found.get("line") or 1, found.get("end_line")))
            else:
                dropped.append("%s#%s" % (path, found.get("name")))
        for found in entry.get("used") or []:
            if _grepped(found.get("call"), text):
                label = found.get("method") or found.get("call")
                items.append(Item("used", path, found["call"], found.get("line") or 1, method=label,
                                  aliases=(label,) + tuple(found.get("aliases") or ()), needs_reason=False))
            else:
                dropped.append("%s: %s" % (path, found.get("call")))
        for found in entry.get("parameters") or []:
            if _grepped(found.get("name"), text) and (found.get("value") in (None, UNSET) or str(found.get("value")) in text):
                unset = found.get("value") in (None, UNSET)
                items.append(Item("parameter", path, found["name"], found.get("line") or 1, method=found.get("method"),
                                  value=UNSET if unset else str(found.get("value")), default=found.get("default"),
                                  what=found.get("what") or ("tolerance" if unset else "set")))
            else:
                dropped.append("%s: %s" % (path, found.get("name")))
    return items, dropped


# --- the check ----------------------------------------------------------------------------------------------


def _not_method(item, entries):
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if name in (item.name, "%s#%s" % (item.path, item.name)) or ("%s/%s" % (CODE, name)) == "%s#%s" % (item.path, item.name):
            return entry
    return None


def _matches(entry, item):
    return str(entry.get("name") or "").strip() == item.name and _short(entry.get("method")) == _short(item.method)


def check(project_or_ledger, worktree, result, *, base="main", run=run_tool, tools=None, policy=None, harness_root=HARNESS_ROOT,
          ticket=None, attempt=None):
    """The rule from code to Methods over one ticket's diff in `code/`: an `Outcome`, or None when the diff changed no code.

    `worktree` is where the ticket's branch is checked out and `base` the branch it is compared with; `result` is the
    worker's result, whose Methods passages, `parameters`, and `not_methods` the check reads. The parsers run through
    `run`, the tool runner tests replace with recordings.
    """
    book = ledger_for(project_or_ledger)
    project = book.research.parent
    worktree = Path(worktree)
    tools = tools if tools is not None else Tools()
    result = result if isinstance(result, dict) else {}
    changed = changed_lines(worktree, base)  # git itself, never the parsers' runner
    if not changed:
        return None
    tables = {"aliases": aliases(), "defaults": defaults()}
    outcome = Outcome()
    functions, roots = project_functions(worktree)
    others = []
    environment_missing = False
    for path in sorted(changed):
        lines = changed[path]
        suffix = Path(path).suffix.lower()
        full = worktree / path
        if not full.is_file():
            continue
        if suffix == ".py":
            text = full.read_text(encoding="utf-8", errors="replace")
            known = {}

            def signatures_of(names):
                nonlocal environment_missing
                found = signatures(project, names, run, tools)
                if found is None and names:
                    environment_missing = True
                known.update(found or {})
                return found

            items, _ = python_items(path, text, lines, functions, roots, tables, signatures_of)
            outcome.items.extend(items)
        elif suffix == ".m":
            try:
                parsed = matlab_parse(full, run, tools)
            except ToolsError as failure:
                outcome.notes.append("%s goes to the reading: %s" % (path, failure))
                others.append(path)
                continue
            outcome.items.extend(matlab_items(path, parsed, lines, tables))
        elif suffix in OTHER_SOURCES:
            others.append(path)
    if others:
        _read_others(outcome, project, worktree, others, changed, policy, harness_root, ticket, attempt)
    if environment_missing:
        outcome.notes.append("the project's Python environment is not installed, so library defaults are %s" % NOT_CHECKED)
    _judge(outcome, methods_text(book, result), result)
    return outcome


def _read_others(outcome, project, worktree, paths, changed, policy, harness_root, ticket, attempt):
    from wayline import gates, project as projects

    files, size = [], 0
    for path in paths:
        text = (worktree / path).read_text(encoding="utf-8", errors="replace")
        if size + len(text) > READING_MAX_CHARS:
            outcome.notes.append("%s is past what one reading takes (%d characters), so it is %s" % (path, READING_MAX_CHARS, NOT_CHECKED))
            continue
        size += len(text)
        files.append((path, text, changed.get(path)))
    if not files:
        return
    try:
        policy = policy if policy is not None else projects.policy_for(project, harness_root)
        answer, accounting = _reading(project, files, policy=policy, harness_root=harness_root, ticket=ticket, attempt=attempt)
    except gates.UsageLimited as refused:
        # A closed window is not a reading: the files stay unread and the acceptance fails until they are read.
        outcome.refused = refused
        outcome.problems.append("the code reading of %s was refused by the usage limit (%s); nothing here is wrong with the "
                                "work: return the same result, and the files are read once the window allows"
                                % (", ".join(path for path, _, _ in files), refused))
        return
    except (MethodsError, gates.GateError, ValueError, OSError) as failure:
        outcome.notes.append("the reading of %s could not be taken, so they are %s: %s"
                             % (", ".join(path for path, _, _ in files), NOT_CHECKED, failure))
        return
    outcome.reading = accounting
    items, dropped = reading_items(answer, {path: text for path, text, _ in files})
    outcome.items.extend(items)
    if dropped:
        outcome.notes.append("the reading named %d item(s) grep did not find, which were dropped: %s" % (len(dropped), "; ".join(dropped)))


def _judge(outcome, texts, result):
    tags = code_tags(texts)
    joined = "\n".join(texts)
    not_methods = [entry for entry in result.get("not_methods") or [] if isinstance(entry, dict)]
    entries = [dict(entry) for entry in result.get("parameters") or [] if isinstance(entry, dict)]
    matched, extra = set(), []
    for item in outcome.items:
        if item.kind == "developed":
            if item.what == "unparsed":
                outcome.problems.append("%s does not parse, so its methods cannot be checked against Methods" % item.path)
            elif not _tagged(item, tags) and _not_method(item, not_methods) is None:
                outcome.problems.append(
                    "the developed method `%s` (%s) has no `code` tag in a current Methods passage: add a Methods passage "
                    "that describes it, ending with {code:%s#%s}, or list it in `not_methods` with why it is not a method"
                    % (item.name, item.where, item.path, item.name))
        elif item.kind == "used":
            if not any(_names(alias, joined) for alias in item.aliases if alias):
                outcome.problems.append(
                    "the used method `%s` (%s, %s) is not named in a Methods passage: name it (as %s) in the Methods passage "
                    "that describes the step" % (item.name, item.method, item.where, " or ".join('"%s"' % alias for alias in item.aliases[:3])))
        else:
            candidates = [number for number, entry in enumerate(entries) if _matches(entry, item)]
            if candidates:
                # The entry that names this value, else one not yet filled, else the first: one reason may cover a
                # method's own default and a call that sets it again, and each value then gets its own filled row.
                exact = [number for number in candidates if number not in matched and entries[number].get("value") is not None
                         and str(entries[number]["value"]) == str(item.value)]
                fresh = [number for number in candidates if number not in matched]
                index = (exact or fresh or candidates)[0]
                filled = {"value": item.value, "default": item.default, "path": item.path, "line": item.line}
                if index in matched:
                    extra.append(dict(entries[index], **filled))
                else:
                    matched.add(index)
                    entries[index].update(filled)
                continue
            if not item.needs_reason:
                if item.default == NOT_CHECKED:
                    outcome.notes.append("`%s` of `%s` (%s) is set to %s; its default is %s" % (item.name, item.method, item.where,
                                                                                               item.value, NOT_CHECKED))
                continue
            outcome.problems.append(_parameter_problem(item))
    outcome.parameters = entries + extra
    outcome.not_methods = [dict(entry) for entry in not_methods]


def _parameter_problem(item):
    if item.what == UNSEEDED:
        said = "draws from a random state no seed fixes (`%s` is unset)" % item.name
    elif item.what == "tolerance":
        said = "leaves `%s` at its default (%s)" % (item.name, item.default)
    elif item.what == "own default":
        said = "gives `%s` the default %s" % (item.name, item.value)
    else:
        said = "sets `%s` to %s where its default is %s" % (item.name, item.value, item.default)
    return ("`%s` (%s) %s: give it a one-sentence reason in `parameters` as {method: %s, name: %s, reason}"
            % (item.method, item.where, said, json.dumps(item.method), json.dumps(item.name)))


# --- what the verdict reads -----------------------------------------------------------------------------------


def code_rule(result):
    """The `parameters` and `not_methods` of a result, as the verdict judges them; None when it carries neither."""
    result = result if isinstance(result, dict) else {}
    parameters = [entry for entry in result.get("parameters") or [] if isinstance(entry, dict)]
    not_methods = [entry for entry in result.get("not_methods") or [] if isinstance(entry, dict)]
    if not parameters and not not_methods:
        return None
    return {"parameters": parameters, "not_methods": not_methods}


def write_code_rule(session_dir, rule):
    """Keep a ticket attempt's code rule beside its session, so a restarted conductor's verdict reads the same items."""
    path = Path(session_dir) / CODE_RULE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rule or {}, indent=2) + "\n", encoding="utf-8")
    return path


def read_code_rule(session_dir):
    try:
        rule = json.loads((Path(session_dir) / CODE_RULE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return code_rule(rule)


# --- the code dossier's methods ------------------------------------------------------------------------------


def inventory(dest, language, run=run_tool, tools=None):
    """The methods a repository develops and uses, for the code dossier: `(modules, methods, note)`.

    MATLAB is read by the same parse the check uses: each file's functions become a module's functions and the
    repository's developed methods, and each call the alias table lists a used method. Python's methods are read with
    `ast` the same way. A file the parser cannot read is named in the note.
    """
    from wayline.code_dossier import _is_vendored

    dest = Path(dest)
    tables = {"aliases": aliases(), "defaults": defaults()}
    modules, found, unread = [], [], []
    suffix = {"matlab": ".m", "python": ".py"}[language]
    for path in sorted(dest.rglob("*" + suffix)):
        relative = path.relative_to(dest).as_posix()
        if _is_vendored(path, dest) or any(part.startswith(".") for part in path.relative_to(dest).parts):
            continue
        if language == "matlab":
            try:
                parsed = matlab_parse(path, run, tools)
            except ToolsError as failure:
                unread.append("%s (%s)" % (relative, failure))
                continue
            items = matlab_items(relative, parsed, None, tables)
            functions = [{"name": function.get("name"), "lineno": function.get("start", 1), "end_lineno": function.get("end"),
                          "decorators": [], "docstring": None, "public": not plumbing(relative, function.get("name") or "")}
                         for function in parsed.get("functions") or [] if function.get("name")]
            modules.append({"path": relative, "all": None, "functions": functions, "classes": [],
                            "public_symbols": sorted(function["name"] for function in functions if function["public"])})
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                unread.append(relative)
                continue
            items, _ = python_items(relative, text, None, tables=tables)
        for item in items:
            if item.kind in ("developed", "used") and item.what != "unparsed":
                entry = {"kind": item.kind, "name": item.name, "path": relative, "line": item.line}
                if item.kind == "used":
                    entry["method"] = item.method
                found.append(entry)
    note = "not parsed: %s" % "; ".join(unread) if unread else None
    return modules, found, note

