"""The package imports only the standard library (Implementation Decisions 1, Language)."""

import ast
import importlib
import sys
import unittest

from tests.paths import HARNESS_ROOT

PACKAGE_DIR = HARNESS_ROOT / "wayline"

# The module set Implementation Decisions 1 lists for the package.
EXPECTED_MODULES = {
    "cli", "conductor", "worker", "resources", "tick", "tickets", "ledger", "registry", "dossier",
    "kb", "scout", "gates", "provenance", "evolve", "figures", "docs", "dashboard", "guidelines",
    "notify", "fetch", "frontmatter", "jsonschema",
}


def imported_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # a relative import stays inside the package
            yield node.lineno, (node.module or "").split(".")[0]


class ImportGraphTest(unittest.TestCase):
    def test_every_module_imports_only_the_standard_library(self):
        allowed = set(sys.stdlib_module_names) | {"wayline"}
        offenders = []
        for path in sorted(PACKAGE_DIR.rglob("*.py")):
            for lineno, name in imported_names(path):
                if name not in allowed:
                    offenders.append("%s:%d imports %s" % (path.relative_to(HARNESS_ROOT), lineno, name))
        self.assertEqual(offenders, [])

    def test_the_module_set_of_decision_1_is_importable(self):
        for name in sorted(EXPECTED_MODULES):
            with self.subTest(module=name):
                importlib.import_module("wayline." + name)

    def test_bin_script_imports_only_the_standard_library(self):
        allowed = set(sys.stdlib_module_names) | {"wayline"}
        for _, name in imported_names(HARNESS_ROOT / "bin" / "wayline"):
            self.assertIn(name, allowed)


if __name__ == "__main__":
    unittest.main()
