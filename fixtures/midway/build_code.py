"""Build the start-midway project's code repository, with history, into a directory you name.

`python3 fixtures/midway/build_code.py DEST` makes DEST a git repository of three commits: a
Python file that develops the phase-locking method, a MATLAB file that does the same, and a
commit that sets a non-default window. Shipped as a script so no nested `.git` enters the tree.
"""

import os
import subprocess
import sys
from pathlib import Path

PY_FIRST = '''"""Phase-locking order parameter for lantern moth wingbeats (invented)."""
import numpy as np
from scipy.signal import hilbert


def order_parameter(traces, window=256):
    phases = np.angle(hilbert(traces[:, :window], axis=1))
    return np.abs(np.exp(1j * phases).mean(axis=0)).mean()
'''

PY_SECOND = PY_FIRST + '''

def colony_synchrony(traces):
    # The window used for every figure: 512 samples, not the default 256.
    return order_parameter(traces, window=512)
'''

MATLAB = '''function R = phaselock(traces, window)
%PHASELOCK Order parameter of wingbeat traces (invented), one moth per row.
if nargin < 2, window = 512; end
ph = angle(hilbert(traces(:, 1:window).').');
R = mean(abs(mean(exp(1i * ph), 1)));
end
'''

COMMITS = [
    ("Add the order parameter", {"phaselock.py": PY_FIRST}),
    ("Port the order parameter to MATLAB", {"phaselock.m": MATLAB}),
    ("Use a 512-sample window for colony synchrony", {"phaselock.py": PY_SECOND}),
]


def build(dest):
    dest = Path(dest)
    dest.mkdir(parents=True)
    env = dict(os.environ, GIT_AUTHOR_NAME="Ines Varga", GIT_AUTHOR_EMAIL="ines@example.org",
               GIT_COMMITTER_NAME="Ines Varga", GIT_COMMITTER_EMAIL="ines@example.org")
    git = lambda *a: subprocess.run(["git", "-C", str(dest), *a], check=True, env=env,
                                    capture_output=True)
    git("init", "-q", "-b", "main")
    for day, (message, files) in enumerate(COMMITS, 1):
        for name, text in files.items():
            (dest / name).write_text(text)
        git("add", "-A")
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"2022-0{day}-15T12:00:00Z"
        git("commit", "-q", "-m", message)


if __name__ == "__main__":
    build(sys.argv[1])
