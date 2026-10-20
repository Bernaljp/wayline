"""The plotting library (Implementation Decision 17; ticket 102).

A project draws its results in one library, `harness.json`'s `plotting`: Python with matplotlib and seaborn (the
default, and what a project without the key draws with), Altair, or R with ggplot2. The owner switches it at any time
and back with `wayline switch --plotting <library>` (`set_plotting`, which the dashboard calls too): `harness.json` is
written first and then `control plotting` is journaled, with a conductor running or not. It applies at each result's
next drawing: a drawing records the library it was opened in, and its script, the clean-room rerun, and the checks
run in that library, the checks reading the SVG it writes. A drawing already accepted keeps its library.

The owner's word is the yes to install what the library needs: a library whose tools `tools.json` does not record
is installed first, synchronously, through `wayline tools install`'s routes (Altair into the tools venv through
uv, R with ggplot2 from conda-forge), and a failed install leaves the setting as it was and says why. The decider
never changes the setting under any autonomy: `set_plotting` takes the owner's word alone, from the command line or
the dashboard.
"""

import sys
from collections import namedtuple
from pathlib import Path

from wayline.tools import Tools, ToolsError, run_tool, tools_home

__all__ = ["MATPLOTLIB", "ALTAIR", "GGPLOT2", "LIBRARIES", "DEFAULT", "BY", "Library", "setting", "missing", "interpreter",
           "install", "set_plotting", "brief_lines", "switch_command"]

MATPLOTLIB, ALTAIR, GGPLOT2 = "matplotlib", "altair", "ggplot2"
DEFAULT = MATPLOTLIB
BY = ("cli", "dashboard")  # the owner's word: the conversation's verb or the dashboard's select, never the decider

# `tools`: what tools.json must record; `runner`: the entry whose executable draws and reruns the script.
Library = namedtuple("Library", "name label tools runner script how")
LIBRARIES = {
    MATPLOTLIB: Library(MATPLOTLIB, "Python with matplotlib and seaborn", ("matplotlib", "seaborn"), "matplotlib", "draw.py",
                        "write each plot with matplotlib (seaborn on top where it helps), saving it with `savefig` as PNG and SVG"),
    ALTAIR: Library(ALTAIR, "Python with Altair", (ALTAIR,), ALTAIR, "draw.py",
                    "build each plot as an Altair chart and save it with `chart.save(...)` as PNG and SVG (vl-convert is installed)"),
    GGPLOT2: Library(GGPLOT2, "R with ggplot2", (GGPLOT2,), GGPLOT2, "draw.R",
                     "build each plot with ggplot2 and save it with `ggsave` as PNG and SVG (svglite is installed), writing "
                     "numbers.json with jsonlite"),
}


def setting(harness):
    """The library a project draws in now: `harness.json`'s `plotting`, matplotlib when it has none."""
    value = (harness or {}).get("plotting")
    return value if value in LIBRARIES else DEFAULT


def _library(name):
    if name not in LIBRARIES:
        raise ToolsError("the plotting library is one of %s, got %r" % (", ".join(LIBRARIES), name))
    return LIBRARIES[name]


def _present(entry):
    return bool(entry and entry.get("executable") and Path(entry["executable"]).exists())


def missing(library, tools=None):
    """The tools `library` needs that `tools.json` does not record, or records at a path no longer there."""
    tools = tools if tools is not None else Tools()
    return [name for name in _library(library).tools if not _present(tools.entry(name))]


def interpreter(library, tools=None):
    """The executable a drawing in `library` is drawn and rerun with, or None when its tools are not installed."""
    tools = tools if tools is not None else Tools()
    entry = tools.entry(_library(library).runner)
    return entry["executable"] if _present(entry) else None


def install(library, project=None, root=None, run=run_tool, echo=None):
    """Install what `library` needs and `tools.json` does not record, journaling each as `tool_installed`; returns the names.

    The harness's own matplotlib and seaborn come with `wayline tools install` and no ask; Altair and ggplot2 are a
    project's tools, and the owner's switch is their yes. A failure is journaled and raised.
    """
    from wayline import software, tools as toolbox

    root = Path(root) if root is not None else tools_home()
    wanted = missing(library, Tools(root))
    if wanted and run is run_tool:
        from wayline import real_backend
        real_backend("the network (a plotting library's tools)")
    for name in wanted:
        try:
            if name in software.PROJECT_TOOLS:
                entry = software.install_project_tool(name, root=root, run=run, echo=echo)
            else:
                entry = toolbox.install_tool(name, root=root, run=run, echo=echo)
        except ToolsError as failure:
            software.journal_install(project, None, name, "failed", reason=str(failure))
            raise
        software.journal_install(project, None, name, "installed", entry.get("version"))
    return wanted


def set_plotting(project, library, by="cli", root=None, run=run_tool, echo=None):
    """`wayline switch --plotting`: install what the library needs, write `harness.json`, then journal `control plotting`.

    Accepted at any time, with a conductor running or not: a drawing already open keeps its library, and the next
    drawing of each result reads `harness.json`. `by` is `cli` or `dashboard`; anything else, the decider above all,
    is refused. An explicit library on a project without the key is a change: it records the owner's answer.

    Returns `{from, to, changed, conductor, installed}`.
    """
    from wayline import project as projects
    from wayline.jsonschema import check, load_schema
    from wayline.ledger import Ledger, atomic_write
    import json

    if by not in BY:
        raise projects.ProjectError("the plotting library is the owner's word alone (from the conversation or the dashboard); "
                                    "%s may not change it" % by)
    if library not in LIBRARIES:
        raise projects.ProjectError("the plotting library is one of %s, got %r" % (", ".join(LIBRARIES), library))
    project = Path(project).resolve()
    harness = projects.read_harness(project)
    report = {"from": setting(harness), "to": library, "changed": harness.get("plotting") != library,
              "conductor": projects.conductor_holder(project), "installed": []}
    if not report["changed"]:
        return report
    try:
        report["installed"] = install(library, project, root=root, run=run, echo=echo)
    except ToolsError as failure:
        raise projects.ProjectError("plotting stays %s: installing what %s needs failed: %s"
                                    % (report["from"], LIBRARIES[library].label, failure)) from None
    ledger = Ledger(project)
    with ledger.lock():
        harness = projects.read_harness(project)
        updated = dict(harness, plotting=library)
        check(updated, load_schema("harness"), name=projects.HARNESS_JSON)
        atomic_write(project / projects.HARNESS_JSON, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
        projects.control(project, "plotting", {"plotting": library, "from": report["from"]}, by=by)
    return report


def brief_lines(library):
    """What a drawing's brief says of its library: which one, the script, how it runs, and what the checks read."""
    chosen = _library(library)
    return ["Draw in %s, the library this drawing was opened in. Your one script is `%s` in your drawing directory; run it with "
            "`wayline tools run %s -- %s`, as the clean room reruns it. In it, %s. The checks read each plot's SVG, so every "
            "plot has one." % (chosen.label, chosen.script, chosen.runner, chosen.script, chosen.how)]


def switch_command(options):
    """`wayline switch --plotting <library> [--project <path>]`."""
    from wayline import project as projects
    from wayline.jsonschema import ValidationError

    try:
        project = projects.find_project(options.project)
        report = set_plotting(project, options.plotting, root=tools_home(), run=run_tool,
                              echo=lambda line: print(line, file=sys.stderr))
    except (projects.ProjectError, ValidationError, OSError) as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 1
    if not report["changed"]:
        print("plotting is already %s on %s" % (report["to"], project))
        return 0
    for name in report["installed"]:
        print("  installed %s" % name)
    print("plotting from %s to %s on %s" % (report["from"], report["to"], project))
    print("  each result's next drawing is drawn in %s; drawings already accepted keep their library" % LIBRARIES[report["to"]].label)
    if report["conductor"] is not None:
        print("  journaled for the conductor (pid %s)" % report["conductor"].get("pid", "?"))
    return 0
