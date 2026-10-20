"""Record what the parsers of the rule from code to Methods print, for `tests/test_methods.py` to replay.

`python3 fixtures/methods/record.py [PYTHON]` runs, live:

- tree-sitter-matlab (`converters/matlab_parse.py` in the tools venv `wayline tools install` made) on the
  start-midway fixture's `phaselock.m` and on each of `FILES` here, each kept as
  `recorded/matlab_parse/<first 16 hex of the file's sha256>.json`;
- `inspect.signature` (`wayline.methods.SIGNATURE_PROBE`) under PYTHON, a Python with scipy and numpy
  (`python3` by default), for each name in `NAMES`, kept as `recorded/signatures/<name>.json`.

The recordings of 2026-10-19 came from tree-sitter-matlab 1.3.1 (tree-sitter 0.26.0) and from
Python 3.12.3 with scipy 1.11.4 and numpy 1.26.4.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from wayline.methods import MATLAB_PARSER, SIGNATURE_PROBE  # noqa: E402
from wayline.tools import Tools  # noqa: E402

FILES = ("phaselock_sweep.m", "phaselock_drift.m", "phaselock_defaults.m", "phaselock_broken.m")
NAMES = ("scipy.signal.hilbert", "numpy.random.default_rng", "scipy.integrate.solve_ivp")


def midway_matlab():
    spec = importlib.util.spec_from_file_location("midway_build_code", ROOT / "fixtures" / "midway" / "build_code.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MATLAB


def record_matlab(folder):
    python = Tools().entry("tree-sitter-matlab")["executable"]
    out = HERE / "recorded" / "matlab_parse"
    out.mkdir(parents=True, exist_ok=True)
    midway = Path(folder) / "phaselock.m"
    midway.write_text(midway_matlab(), encoding="utf-8")
    for path in [midway] + [HERE / name for name in FILES]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        printed = subprocess.run([python, str(MATLAB_PARSER), str(path)], capture_output=True, check=True).stdout
        (out / ("%s.json" % digest)).write_bytes(printed)
        print("matlab_parse %s -> %s.json" % (path.name, digest))


def record_signatures(python):
    out = HERE / "recorded" / "signatures"
    out.mkdir(parents=True, exist_ok=True)
    printed = subprocess.run([python, "-c", SIGNATURE_PROBE, json.dumps(list(NAMES))], capture_output=True, check=True, text=True).stdout
    for name, signature in json.loads(printed)["signatures"].items():
        (out / ("%s.json" % name)).write_text(json.dumps(signature, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("signature %s" % name)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="wayline-methods-record-") as folder:
        record_matlab(folder)
    record_signatures(sys.argv[1] if len(sys.argv) > 1 else "python3")
