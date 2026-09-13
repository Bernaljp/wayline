"""`GOAL.json`'s `eval_command` (Implementation Decisions 10): the metric off a `toy.train` summary.

`wayline intake --goal` and the keep-if-better loop both run this on an artifact's path, exported
as `WAYLINE_ARTIFACT` (`intake.check_goal`); `{artifact}` in the command is the same path, for a
command that would rather take it as an argument. Either way the artifact is one of `toy.train`'s
summary JSONs, and this prints its `auroc` on the last line the way `intake.metric_value` reads it:
`auroc: <value>`. `--split` is accepted for the command line `research/GOAL.json` ships
(`python -m toy.eval --split held_out`) but names nothing this module reads: `toy.train` only ever
reports the held-out split, so there is no other one to ask for.
"""

import argparse
import json
import os
import sys
from pathlib import Path

METRIC = "auroc"


def read_metric(artifact):
    summary = json.loads(Path(artifact).read_text(encoding="utf-8"))
    if METRIC not in summary:
        raise SystemExit("%s: no %r in %s" % (Path(sys.argv[0]).name, METRIC, artifact))
    return summary[METRIC]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="toy.eval", description="print the held-out auroc of a toy.train summary")
    parser.add_argument("--split", default="held_out", help="accepted for GOAL.json's eval_command; toy.train reports only the held-out split")
    parser.add_argument("artifact", nargs="?", help="the summary JSON to read; WAYLINE_ARTIFACT by default")
    options = parser.parse_args(argv)
    artifact = options.artifact or os.environ.get("WAYLINE_ARTIFACT")
    if not artifact:
        raise SystemExit("toy.eval: no artifact given and WAYLINE_ARTIFACT is not set")
    print("%s: %s" % (METRIC, read_metric(artifact)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
