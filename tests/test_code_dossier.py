"""Code dossiers (Implementation Decisions 9; research-notes 06 Section 4).

`fixtures/code/tiny-pkg.git` is a small bare repository committed to the harness: three commits
and one tag, a package with a public function, a private one, a class, and `__all__`, an entry
point, a config, and one test. Every offline test here clones it by file path, so nothing ever
reaches the network; the venv the verified recipe builds is `--system-site-packages
--without-pip`, so it needs no `ensurepip` and installs the pinned commit with this process's own
pip, entirely offline too.
"""

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import cli
from wayline.code_dossier import (
    CodeDossierError, absorb_code, clone_at_sha, code_dossier, configs_of, data_requirements_of,
    detect_language, entry_points_of, git_metadata, parse_code_reference, python_inventory,
    _holds_a_test, _needs_pytest, _pick_check, _run_check, scripts_of, tests_of,
)
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger
from wayline.project import init_project

REPO = FIXTURES_DIR / "code" / "tiny-pkg.git"
REPO_URL = "file://%s" % REPO  # pip's git+<url> needs a scheme; plain git clone accepts the bare path either way
SHA = "eeaa815f89a84e417c21180e7b600f5a9c52c684"
TAG = "v0.1.0-2-geeaa815"

# The fixture builds with setuptools, and the recipe installs it without build isolation so that
# nothing is downloaded: a verified recipe needs setuptools already importable by this Python. The
# Python 3.12 that GitHub's check runs on ships pip without it, so the tests that need a real
# install skip there and say why; on that Python the recipe reports `verified: false` with pip's log.
NEEDS_SETUPTOOLS = unittest.skipUnless(
    importlib.util.find_spec("setuptools") is not None,
    "the fixture's build backend is setuptools, which this Python does not have",
)


class ReferenceTest(unittest.TestCase):
    def test_a_plain_url_splits_on_the_last_at(self):
        self.assertEqual(parse_code_reference("https://github.com/org/repo@%s" % SHA), ("https://github.com/org/repo", SHA))

    def test_an_ssh_remote_keeps_its_own_at(self):
        url, sha = parse_code_reference("git@github.com:org/repo.git@abc1234")
        self.assertEqual(url, "git@github.com:org/repo.git")
        self.assertEqual(sha, "abc1234")

    def test_the_sha_is_lowercased(self):
        self.assertEqual(parse_code_reference("https://example.org/repo@ABC1234")[1], "abc1234")

    def test_a_reference_with_no_sha_is_refused(self):
        with self.assertRaises(CodeDossierError):
            parse_code_reference("https://example.org/repo")

    def test_a_short_hex_run_that_is_not_a_sha_is_refused(self):
        with self.assertRaises(CodeDossierError):
            parse_code_reference("https://example.org/repo@abc")


class CloneTest(unittest.TestCase):
    def setUp(self):
        self.dest = Path(tempfile.mkdtemp(prefix="wayline-clone-test-"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)

    def test_the_pinned_sha_is_checked_out(self):
        clone_at_sha(str(REPO), SHA, self.dest)
        self.assertEqual(subprocess.run(["git", "-C", str(self.dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), SHA)
        self.assertTrue((self.dest / "tinypkg" / "core.py").is_file())

    def test_an_unknown_sha_is_refused(self):
        with self.assertRaises(CodeDossierError):
            clone_at_sha(str(REPO), "0" * 40, self.dest)

    def test_metadata_names_the_url_sha_tag_and_no_submodules(self):
        clone_at_sha(str(REPO), SHA, self.dest)
        metadata = git_metadata(self.dest, str(REPO))
        self.assertEqual(metadata["url"], str(REPO))
        self.assertEqual(metadata["sha"], SHA)
        self.assertEqual(metadata["tag"], TAG)
        self.assertIsNotNone(metadata["author_date"])
        self.assertEqual(metadata["submodules"], [])

    def test_recloning_into_the_same_destination_replaces_it(self):
        clone_at_sha(str(REPO), SHA, self.dest)
        (self.dest / "stray.txt").write_text("left behind by a previous run\n", encoding="utf-8")
        clone_at_sha(str(REPO), SHA, self.dest)
        self.assertFalse((self.dest / "stray.txt").exists())


class InventoryTest(unittest.TestCase):
    """The mechanical inventory over the fixture's checkout, independent of any clone or venv."""

    @classmethod
    def setUpClass(cls):
        cls.dest = Path(tempfile.mkdtemp(prefix="wayline-inventory-test-"))
        clone_at_sha(str(REPO), SHA, cls.dest)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dest, ignore_errors=True)

    def test_the_repository_is_seen_as_python(self):
        self.assertEqual(detect_language(self.dest), "python")

    def test_functions_classes_and_dunder_all_are_read_off_core_py(self):
        inventory = python_inventory(self.dest)
        modules = {module["path"]: module for module in inventory["modules"]}
        core = modules["tinypkg/core.py"]
        self.assertEqual(core["all"], ["add", "Greeter"])
        self.assertEqual({function["name"] for function in core["functions"]}, {"add", "_helper"})
        self.assertEqual([cls["name"] for cls in core["classes"]], ["Greeter"])
        self.assertEqual(set(core["public_symbols"]), {"add", "Greeter"})
        add = next(function for function in core["functions"] if function["name"] == "add")
        self.assertTrue(add["public"])
        self.assertEqual(add["docstring"], "Add two numbers.")
        helper = next(function for function in core["functions"] if function["name"] == "_helper")
        self.assertFalse(helper["public"])
        self.assertEqual(inventory["note"], None)
        self.assertGreater(inventory["symbols_total"], 0)

    def test_entry_points_come_from_pyproject_scripts(self):
        entries = entry_points_of(self.dest)
        self.assertEqual(entries, [{"name": "tinypkg-greet", "value": "tinypkg.core:Greeter", "group": "console_scripts", "source": "pyproject.toml"}])

    def test_configs_tests_and_scripts_are_found_by_glob(self):
        # `*.toml` is one of research-notes 06's config globs, so the project's own pyproject.toml counts too.
        self.assertEqual(configs_of(self.dest), ["configs/example.yaml", "pyproject.toml"])
        self.assertEqual(tests_of(self.dest), ["tests/test_core.py"])
        self.assertEqual(scripts_of(self.dest), [])

    def test_the_fixture_names_no_data_requirement(self):
        self.assertEqual(data_requirements_of(self.dest), [])


class NonPythonTest(unittest.TestCase):
    """A repository with no `.py` file: language is set, symbols stay empty, and a note explains why."""

    def setUp(self):
        self.dest = Path(tempfile.mkdtemp(prefix="wayline-non-python-test-"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)
        (self.dest / "src").mkdir()
        (self.dest / "src" / "main.f90").write_text("program main\nend program\n", encoding="utf-8")
        (self.dest / "README.md").write_text("# a fortran solver\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "-m", "init"]):
            subprocess.run(["git", "-C", str(self.dest), *args], check=True)

    def test_language_is_unknown_and_the_inventory_is_empty_with_a_note(self):
        self.assertEqual(detect_language(self.dest), "unknown")
        sha = subprocess.run(["git", "-C", str(self.dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dossier = code_dossier("smith-2019-a-fortran-solver", str(self.dest), sha, self.dest)
        self.assertEqual(dossier["language"], "unknown")
        self.assertEqual(dossier["inventory"]["modules"], [])
        self.assertEqual(dossier["inventory"]["symbols_total"], 0)
        self.assertIn("not yet wired", dossier["inventory"]["note"])
        self.assertEqual(dossier["api_map"], [])


class RecordTest(unittest.TestCase):
    """The whole mechanical dossier, including a run of the verified recipe, offline."""

    @classmethod
    def setUpClass(cls):
        cls.dest = Path(tempfile.mkdtemp(prefix="wayline-record-test-"))
        clone_at_sha(REPO_URL, SHA, cls.dest)
        cls.dossier = code_dossier("vaswani-2017-attention", REPO_URL, SHA, cls.dest)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dest, ignore_errors=True)

    def test_the_dossier_validates(self):
        self.assertEqual(validate(self.dossier, load_schema("code_dossier")), [])

    @NEEDS_SETUPTOOLS
    def test_the_pinned_commit_installs_and_the_smallest_test_runs(self):
        self.assertTrue(self.dossier["verified"], self.dossier["recipe"]["log"])
        self.assertEqual(self.dossier["recipe"]["install_exit_code"], 0)
        self.assertEqual(self.dossier["recipe"]["checked_path"], "tests/test_core.py")
        self.assertEqual(self.dossier["recipe"]["exit_code"], 0)

    def test_the_api_map_has_one_empty_entry_per_module(self):
        self.assertEqual(len(self.dossier["api_map"]), len(self.dossier["inventory"]["modules"]))
        for entry in self.dossier["api_map"]:
            self.assertEqual(entry["good"], [])
            self.assertIsNone(entry["how_to_call"])


class AbsorbTest(ProjectTestCase):
    """`absorb_code` end to end: the clone, the dossier, and the journal, under a real project."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        (self.project / "research").mkdir(parents=True)
        self.ledger = Ledger(self.project)

    def test_the_code_dossier_lands_next_to_the_papers_dossier(self):
        dossier, path = absorb_code(self.project, "vaswani-2017-attention", REPO_URL, SHA)
        self.assertEqual(path, self.project / "research" / "refs" / "vaswani-2017-attention" / "code_dossier.json")
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["source"]["sha"], SHA)
        self.assertTrue((self.project / "research" / "refs" / "vaswani-2017-attention" / "code" / "tinypkg" / "core.py").is_file())

    def test_absorbing_journals_absorbed(self):
        absorb_code(self.project, "vaswani-2017-attention", REPO_URL, SHA)
        events, _ = self.ledger.read_events()
        absorbed = [event for event in events if event["event"] == "absorbed"]
        self.assertEqual(len(absorbed), 1)
        self.assertEqual(absorbed[0]["payload"]["slug"], "vaswani-2017-attention")


class VerbTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None)

    def run_verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    @NEEDS_SETUPTOOLS
    def test_the_code_verb_builds_and_prints_a_verified_dossier(self):
        code, printed, _ = self.run_verb("absorb", "--code", "vaswani-2017-attention", "%s@%s" % (REPO_URL, SHA), "--project", str(self.project))
        self.assertEqual(code, 0)
        self.assertIn("verified       True", printed)
        self.assertTrue((self.project / "research" / "refs" / "vaswani-2017-attention" / "code_dossier.json").is_file())

    @NEEDS_SETUPTOOLS
    def test_the_report_comes_back_as_json_when_it_is_asked_for(self):
        code, printed, _ = self.run_verb("absorb", "--code", "vaswani-2017-attention", "%s@%s" % (REPO_URL, SHA), "--project", str(self.project), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(printed)["verified"])

    def test_an_unresolvable_reference_is_a_clean_failure(self):
        code, _, complaint = self.run_verb("absorb", "--code", "nowhere", "%s@%s" % (REPO_URL, "0" * 40), "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("wayline absorb --code:", complaint)


class CheckPickTest(unittest.TestCase):
    """Which file the recipe runs, and how: a file with no test is skipped, a pytest file runs under pytest."""

    def setUp(self):
        self.dest = Path(tempfile.mkdtemp(prefix="wayline-check-test-"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)
        (self.dest / "pkg" / "tests").mkdir(parents=True)

    def write(self, relpath, text):
        path = self.dest / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return relpath

    def test_an_empty_test_file_and_a_data_file_are_not_checks(self):
        empty = self.write("pkg/tests/test_empty.py", "")
        data = self.write("tests/data.txt", "1")
        helper = self.write("pkg/tests/test_helpers.py", "VALUE = 1\n")
        real = self.write("pkg/tests/test_real.py", "def test_one():\n    assert 1 + 1 == 2\n")
        self.assertEqual(_pick_check(self.dest, [data, empty, helper, real], []), (real, "test"))

    def test_a_test_class_counts_as_a_test(self):
        self.assertTrue(_holds_a_test(self.dest / self.write("t1.py", "import unittest\nclass Core(unittest.TestCase):\n    pass\n")))
        self.assertTrue(_holds_a_test(self.dest / self.write("t2.py", "class TestCore:\n    pass\n")))
        self.assertFalse(_holds_a_test(self.dest / self.write("t3.py", "def helper():\n    pass\n")))
        self.assertFalse(_holds_a_test(self.dest / self.write("t4.py", "def broken(:\n")))

    def test_a_file_importing_pytest_or_under_a_conftest_is_a_pytest_file(self):
        self.assertTrue(_needs_pytest(self.dest / self.write("a/test_a.py", "import pytest\n"), self.dest))
        self.assertTrue(_needs_pytest(self.dest / self.write("b/test_b.py", "from pytest import raises\n"), self.dest))
        self.write("pkg/conftest.py", "")
        self.assertTrue(_needs_pytest(self.dest / self.write("pkg/tests/test_c.py", "def test_c(iris):\n    pass\n"), self.dest))
        self.assertFalse(_needs_pytest(self.dest / self.write("d/test_d.py", "import unittest\n"), self.dest))

    def test_a_pytest_file_gets_pytest_in_the_venv_and_runs_under_it(self):
        relpath = self.write("pkg/tests/test_p.py", "import pytest\ndef test_p():\n    pass\n")
        calls = []

        def run(argv, **options):
            calls.append(argv)
            missing = argv[1:] == ["-c", "import pytest"]
            return subprocess.CompletedProcess(argv, 1 if missing else 0, "", "")

        with unittest.mock.patch("wayline.code_dossier.subprocess.run", side_effect=run):
            outcome = _run_check(Path("/venv/bin/python3"), self.dest, relpath, "test", self.dest)
        self.assertEqual(outcome["command"], "python -m pytest -q -p no:cacheprovider pkg/tests/test_p.py")
        self.assertEqual(outcome["result"].returncode, 0)
        self.assertEqual(calls[1][-4:], ["--python", "/venv/bin/python3", "install", "pytest"])
        self.assertEqual(calls[2][:4], ["/venv/bin/python3", "-m", "pytest", "-q"])
        self.assertIn("$ pip install pytest", outcome["setup"][0])

    def test_a_failed_pytest_install_is_the_check_s_failure(self):
        relpath = self.write("pkg/tests/test_p.py", "import pytest\ndef test_p():\n    pass\n")
        with unittest.mock.patch("wayline.code_dossier.subprocess.run",
                                 side_effect=lambda argv, **options: subprocess.CompletedProcess(argv, 1, "", "no network")):
            outcome = _run_check(Path("/venv/bin/python3"), self.dest, relpath, "test", self.dest)
        self.assertEqual(outcome["command"], "pip install pytest")
        self.assertEqual(outcome["result"].returncode, 1)
        self.assertEqual(outcome["setup"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
