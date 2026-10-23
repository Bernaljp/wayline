"""Record the real tool runs a compilation makes, for the tests to replay (ticket 118; seam 6).

`python3 fixtures/compilations/record.py` builds the synthetic paper of `tests/compile_fixture.py` in a scratch project
and compiles it with the tools `~/.wayline/tools/tools.json` records on this machine (pandoc and pandoc-crossref from
conda-forge, `latexmk` with xelatex, `pdfinfo`), through `wayline.compilations.recording_runner`, keeping what each call
printed and wrote under `recorded/<compilation>/<tool>/<output>/`: the order's compilations (`plain`, and `nature`, the
venue it names) after the last retry over the fixture's scripted network, and `testconf` with its vendored class, its
`.bib`, and its fitting (`testconf-fitted`), the fitting session scripted through the fake launcher. Nothing is installed
and nothing is written outside the scratch directory and `recorded/`. Rerun it after the fixture or the compilation's
commands change; a replay of a stale recording says so.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

TOOLS_JSON = Path.home() / ".wayline" / "tools" / "tools.json"


def main():
    from wayline import worker  # noqa: E402
    from wayline.tools import Tools  # noqa: E402

    tools = Tools(TOOLS_JSON.parent)  # read before WAYLINE_HOME moves to the scratch directory
    scratch = Path(tempfile.mkdtemp(prefix="wayline-record-compilations-"))
    os.environ["WAYLINE_HOME"] = str(scratch / "home")
    from tests import compile_fixture as fixture  # noqa: E402  (sets the suite's environment, which runs no backend)
    from wayline import compilations, project as projects  # noqa: E402
    from wayline.worker import Envelope  # noqa: E402

    target = HERE / "recorded"
    shutil.rmtree(target, ignore_errors=True)
    run = compilations.recording_runner(target)
    try:
        path = scratch / "paper-project"
        projects.init_project(path, harness_root=ROOT, git=False)
        fixture.make_paper(path)
        fetcher, _ = fixture.fetcher()
        done = compilations.after_order(path, {"order": 1, "venue": "nature"}, tools=tools, run=run, fetcher=fetcher,
                                        clock=lambda: fixture.NOW, say=print)
        print("retried: %s" % done["retried"])
        shelf = fixture.guidelines_shelf(scratch / "shelf")
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output=fixture.fitted_answer(), session_id="fit-1"), role="writer")
            made = compilations.compile_paper(path, "testconf", guidelines_root=shelf, tools=tools, run=run, say=print)
        print("testconf: %s, fitting %s" % (made["outcome"], (made["fitting"] or {}).get("outcome")))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
