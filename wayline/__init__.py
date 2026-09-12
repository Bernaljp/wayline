"""wayline: one command that turns a research intent into REPORT.md under a Claude Code subscription.

Deterministic Python (standard library only) decides what runs, when, on which resources, and
what counts as done; models decide only content. This package is the harness; the spec is
`.scratch/wayline/spec.md` and the vocabulary is `CONTEXT.md`.
"""

from pathlib import Path

__version__ = "0.1.0"
TAG = "v" + __version__

HARNESS_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = HARNESS_ROOT / "schemas"
POLICY_PATH = HARNESS_ROOT / "policy.json"

__all__ = ["__version__", "TAG", "HARNESS_ROOT", "SCHEMAS_DIR", "POLICY_PATH"]
