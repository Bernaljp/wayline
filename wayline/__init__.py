"""wayline: one command that turns a research intent into REPORT.md under a Claude Code subscription.

Deterministic Python (standard library only) decides what runs, when, on which resources, and
what counts as done; models decide only content. This package is the harness; the spec is
`.scratch/wayline/spec.md` and the vocabulary is `CONTEXT.md`.
"""

import os
from pathlib import Path

__version__ = "1.0.0"
TAG = "v" + __version__

HARNESS_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = HARNESS_ROOT / "schemas"
POLICY_PATH = HARNESS_ROOT / "policy.json"

BACKENDS_ENV = "WAYLINE_BACKENDS"


class BackendTouched(BaseException):
    """A real backend reached while `WAYLINE_BACKENDS=none` says none may be.

    The suite sets it (ticket 47): the `claude` executable and the network each call `real_backend`
    at their door, so a test that reaches one fails loudly instead of spending the subscription or
    waiting on the network. The GPU probe reads as a machine with no GPU instead (`backends_off`),
    because a box without one is a normal CPU-only degrade that `status` and the dashboard read,
    not a failure; the suite then reads the same machine everywhere it runs. It derives from
    `BaseException` so that no `except Exception` in the harness can take it for a failure it handles.
    """


def backends_off():
    """Whether `WAYLINE_BACKENDS=none` keeps this process off the real backends."""
    return os.environ.get(BACKENDS_ENV) == "none"


def real_backend(name):
    """Raise `BackendTouched` naming `name` when `WAYLINE_BACKENDS=none`; otherwise nothing."""
    if backends_off():
        raise BackendTouched("%s is a real backend, and %s=none keeps this process off it" % (name, BACKENDS_ENV))


__all__ = ["__version__", "TAG", "HARNESS_ROOT", "SCHEMAS_DIR", "POLICY_PATH", "BACKENDS_ENV", "BackendTouched",
           "backends_off", "real_backend"]
