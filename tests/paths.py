"""Paths the tests share: the harness root and the spec the tests cross-check against."""

from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = HARNESS_ROOT / ".scratch" / "wayline" / "spec.md"
SCHEMAS_DIR = HARNESS_ROOT / "schemas"
EXAMPLES_DIR = HARNESS_ROOT / "tests" / "examples"
FIXTURES_DIR = HARNESS_ROOT / "fixtures"
LEDGER_FIXTURE = FIXTURES_DIR / "ledger"
TEMPLATES_DIR = HARNESS_ROOT / "templates" / "project"
