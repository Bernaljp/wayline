"""What the project tests share: a temporary `~/.wayline`, a fake harness, and a tree hash.

Every test that touches the per-machine pointers points `WAYLINE_HOME` at a temporary directory,
so the suite never reads or writes the owner's own `~/.wayline/`.
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.paths import HARNESS_ROOT, LEDGER_FIXTURE, TEMPLATES_DIR

SKILLS = ("wayline-absorb", "wayline-figure")
WORKFLOWS = ("absorb.js", "panel.js")


class ProjectTestCase(unittest.TestCase):
    """A test with its own `WAYLINE_HOME`, a temporary directory, and a fake harness checkout."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-test-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.wayline_home = self.temp / "home"
        previous = os.environ.get("WAYLINE_HOME")
        os.environ["WAYLINE_HOME"] = str(self.wayline_home)
        self.addCleanup(self._restore_home, previous)

    @staticmethod
    def _restore_home(previous):
        if previous is None:
            os.environ.pop("WAYLINE_HOME", None)
        else:
            os.environ["WAYLINE_HOME"] = previous

    def fake_harness(self, skills=SKILLS, workflows=WORKFLOWS, name="harness"):
        """A harness checkout with the real templates and policy and a few skills and workflow scripts."""
        root = self.temp / name
        (root / "skills").mkdir(parents=True, exist_ok=True)
        (root / "workflows").mkdir(parents=True, exist_ok=True)
        shutil.copytree(TEMPLATES_DIR, root / "templates" / "project", dirs_exist_ok=True)
        shutil.copy(HARNESS_ROOT / "policy.json", root / "policy.json")
        (root / "figures").mkdir(exist_ok=True)
        shutil.copy(HARNESS_ROOT / "figures" / "style.default.json", root / "figures" / "style.default.json")
        for skill in skills:
            directory = root / "skills" / skill
            directory.mkdir(exist_ok=True)
            (directory / "SKILL.md").write_text("# %s\n" % skill, encoding="utf-8")
        for workflow in workflows:
            (root / "workflows" / workflow).write_text("// %s\n" % workflow, encoding="utf-8")
        return root

    def ledger_fixture(self, name="fixture-project"):
        """A writable copy of `fixtures/ledger/`, the project every status test reads."""
        target = self.temp / name
        shutil.copytree(LEDGER_FIXTURE, target)
        return target


def tree_hash(root, skip=(".git",)):
    """A hash of every file, directory, and symlink under `root`, with names, modes, and contents.

    This is what the idempotence test compares before and after a second `init`.
    """
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(root.rglob("*"), key=lambda item: str(item)):
        relative = path.relative_to(root)
        if any(part in skip for part in relative.parts):
            continue
        digest.update(str(relative).encode("utf-8") + b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0" + os.readlink(path).encode("utf-8") + b"\0")
        elif path.is_dir():
            digest.update(b"dir\0")
        else:
            digest.update(b"file\0%o\0" % (path.stat().st_mode & 0o777))
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()
