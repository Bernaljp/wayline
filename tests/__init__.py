"""The suite never reaches the owner's user manager (Implementation Decisions 7).

`WAYLINE_UNITS=none` is set before any test module is imported, and every process a test starts
inherits it, so `init` writes no unit into `~/.config/systemd/user` and `run` starts no dashboard
service. The tests of the units stand `wayline.tick.use_fake_systemd` in for the manager instead.

`WAYLINE_UNPINNED=1` likewise lets `run` start against a harness checkout that is not at the
project's pin (Implementation Decisions 5). The suite runs between tags by construction, and a
shallow clone has no tags at all. The tests of the pin pass their own environment instead.
"""

import os

os.environ["WAYLINE_UNITS"] = "none"
os.environ["WAYLINE_UNPINNED"] = "1"
