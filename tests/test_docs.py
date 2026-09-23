"""The documentation site (Implementation Decisions 13; ticket 51).

`fixtures/docs/tinydocs/` is a small project with a site laid out as `wayline docs init` lays one out,
and two deliberate faults: `tinydocs.core.undocumented_helper` has no docstring, and
`docs/examples/broken.py` imports a name the package does not have. Sphinx is never installed where
the suite runs, so the build goes through `tests.sphinx_fake.FakeSphinx` at the `sphinx` seam; the
examples run for real, on this interpreter; external links go through the fetch seam, faked here.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.sphinx_fake import FakeSphinx, write_objects_inv
from tests.test_conductor import ConductorCase
from tests.test_dashboard import DashboardTestCase
from tests.test_report import RunCase
from tests.test_verdicts import passing
from wayline import cli, docs, fetch, gates, tickets, worker
from wayline.plan import PUBLIC_API_HEADING, PUBLIC_API_LINE
from wayline.tickets import machine_acceptance

TINYDOCS = FIXTURES_DIR / "docs" / "tinydocs"
FAKE_SPHINX = HARNESS_ROOT / "tests" / "fake_sphinx"


class FakeFetcher:
    """The fetch seam, answering from a dict of URL to status; a URL it does not know is a refused connection."""

    def __init__(self, statuses):
        self.statuses = dict(statuses)
        self.asked = []

    def fetch(self, url, headers=None, method="GET"):
        self.asked.append((method, url))
        if url not in self.statuses:
            raise fetch.FetchError("%s: connection refused" % url)
        return fetch.Response(url, self.statuses[url])


class DocsCase(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-docs-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.root = self.temp / "tinydocs"
        shutil.copytree(TINYDOCS, self.root)

    def build(self, sphinx=None, fetcher=None, offline=True, python=sys.executable):
        self.sphinx = sphinx or FakeSphinx()
        return docs.build(self.root, self.root, python=python, sphinx=self.sphinx, fetcher=fetcher, offline=offline)

    def fix_faults(self):
        core = self.root / "src" / "tinydocs" / "core.py"
        core.write_text(core.read_text(encoding="utf-8").replace(
            "def undocumented_helper(value):\n",
            "def undocumented_helper(value):\n    \"\"\"Twice `value`.\"\"\"\n"), encoding="utf-8")
        (self.root / "docs" / "examples" / "broken.py").unlink()
        index = self.root / "docs" / "examples" / "index.rst"
        index.write_text(index.read_text(encoding="utf-8").replace(".. literalinclude:: broken.py\n", ""), encoding="utf-8")

    def append(self, relative, text):
        path = self.root / relative
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


class InventoryTest(DocsCase):
    def test_the_public_symbols_are_the_ast_inventory_of_the_package_less_its_private_modules(self):
        symbols = {symbol.name: symbol for symbol in docs.public_symbols(self.root, "src/tinydocs")}
        self.assertEqual(sorted(symbols), ["tinydocs.core.Counter", "tinydocs.core.mean", "tinydocs.core.undocumented_helper"])
        self.assertFalse(symbols["tinydocs.core.undocumented_helper"].documented)
        self.assertTrue(symbols["tinydocs.core.mean"].documented)
        self.assertEqual(symbols["tinydocs.core.undocumented_helper"].where, "src/tinydocs/core.py:20")

    def test_objects_inv_is_read_back_by_name(self):
        path = self.temp / "objects.inv"
        write_objects_inv(path, [("pkg.f", "py:function", "api.html#$"), ("pkg.C", "py:class", "api.html#$")])
        self.assertEqual(docs.read_objects_inv(path), {"pkg.f": "py:function", "pkg.C": "py:class"})


class BuildTest(DocsCase):
    def test_the_fixture_fails_on_its_undocumented_symbol_and_its_broken_example(self):
        record = self.build()
        self.assertFalse(record.passed)
        self.assertEqual([check.id for check in record.checks], list(docs.CHECKS))
        failed = {check.id for check in record.checks if not check.passed}
        self.assertEqual(failed, {"docstrings", "examples", "reference"})
        self.assertIn("tinydocs.core.undocumented_helper (src/tinydocs/core.py:20) has no docstring",
                      record.check("docstrings").failures)
        self.assertEqual(len(record.check("examples").failures), 1)
        self.assertIn("docs/examples/broken.py exited 1", record.check("examples").failures[0])
        self.assertIn("ImportError", record.check("examples").failures[0])
        self.assertEqual(record.check("reference").failures,
                         ["tinydocs.core.undocumented_helper is not in the reference (objects.inv)"])

    def test_with_both_faults_fixed_every_check_passes_and_the_record_is_written(self):
        self.fix_faults()
        record = self.build()
        self.assertTrue(record.passed, record.text())
        self.assertEqual(record.site, self.root / "research" / ".cache" / "docs" / "html" / "index.html")
        self.assertTrue(record.site.is_file())
        written = json.loads((self.root / docs.CHECKS_JSON).read_text(encoding="utf-8"))
        self.assertTrue(written["pass"])
        self.assertEqual([check["check"] for check in written["checks"]], list(docs.CHECKS))
        self.assertEqual(written["site"], "research/.cache/docs/html/index.html")

    def test_the_build_runs_in_the_projects_environment_with_the_package_on_the_path(self):
        self.fix_faults()
        self.build(python="/opt/env/bin/python")
        call = self.sphinx.calls[0]
        self.assertEqual(call["python"], "/opt/env/bin/python")
        self.assertEqual(call["source"], self.root / "docs")
        self.assertEqual(call["out"], self.root / "research" / ".cache" / "docs" / "html.new", "staged, then published")
        self.assertIn(str(self.root / "src"), call["env"]["PYTHONPATH"].split(":"))

    def test_a_warning_fails_the_build_and_is_listed(self):
        self.fix_faults()
        warning = "docs/how-to/index.rst:3: WARNING: undefined label: 'nowhere'"
        record = self.build(sphinx=FakeSphinx(warnings=[warning]))
        self.assertFalse(record.passed)
        self.assertEqual(record.check("build").failures, [warning])

    def test_a_link_to_a_missing_page_or_anchor_fails_the_links_check(self):
        self.fix_faults()
        self.append("docs/explanation/index.rst", "\nSee `the lost page <../lost.html>`_ and `a section <../index.html#no-such-section>`_.\n")
        record = self.build()
        failures = record.check("links").failures
        self.assertEqual(len(failures), 2, failures)
        self.assertIn("explanation/index.html links to ../lost.html, which does not exist", failures)
        self.assertIn("explanation/index.html links to ../index.html#no-such-section, whose anchor is not on that page", failures)

    def test_external_links_are_asked_once_each_and_a_404_fails(self):
        self.fix_faults()
        self.append("docs/explanation/index.rst", "\nSee `live <https://example.org/live>`_, `gone <https://example.org/gone>`_, "
                                                   "and `live again <https://example.org/live>`_.\n")
        fetcher = FakeFetcher({"https://example.org/live": 200, "https://example.org/gone": 404})
        record = self.build(fetcher=fetcher, offline=False)
        self.assertEqual(record.check("links").failures,
                         ["explanation/index.html links to https://example.org/gone, which answered 404"])
        self.assertEqual(sorted(url for _, url in fetcher.asked), ["https://example.org/gone", "https://example.org/live"])

    def test_offline_the_external_links_are_not_asked_and_the_record_says_so(self):
        self.fix_faults()
        self.append("docs/explanation/index.rst", "\nSee `gone <https://example.org/gone>`_.\n")
        fetcher = FakeFetcher({})
        record = self.build(fetcher=fetcher, offline=True)
        self.assertTrue(record.check("links").passed)
        self.assertEqual(fetcher.asked, [])
        self.assertIn("1 external link(s) not checked (--offline)", record.check("links").notes)

    def test_a_theme_other_than_the_recorded_one_fails_the_structure(self):
        self.fix_faults()
        conf = self.root / "docs" / "conf.py"
        conf.write_text(conf.read_text(encoding="utf-8").replace('"alabaster"', '"furo"'), encoding="utf-8")
        record = self.build()
        self.assertEqual(record.check("structure").failures,
                         ["docs/conf.py sets html_theme = 'furo', and harness.json.docs records 'alabaster'; the theme is chosen once per project"])

    def test_no_recorded_theme_fails_the_structure_and_names_docs_init(self):
        harness = json.loads((self.root / "harness.json").read_text(encoding="utf-8"))
        del harness["docs"]["theme"]
        (self.root / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        self.fix_faults()
        record = self.build()
        self.assertTrue(any("wayline docs init --theme" in failure for failure in record.check("structure").failures),
                        record.check("structure").failures)

    def test_a_missing_part_of_the_site_fails_the_structure(self):
        self.fix_faults()
        shutil.rmtree(self.root / "docs" / "explanation")
        (self.root / ".readthedocs.yaml").unlink()
        failures = self.build().check("structure").failures
        self.assertIn("docs/explanation has no index.rst or index.md (the explanation part of the site)", failures)
        self.assertIn(".readthedocs.yaml is missing (the Read the Docs configuration)", failures)

    def test_a_gallery_without_a_figure_and_an_example_the_site_never_shows_fail_the_site_check(self):
        self.fix_faults()
        (self.root / "docs" / "gallery" / "index.rst").write_text("Gallery\n=======\n\nNothing yet.\n", encoding="utf-8")
        (self.root / "docs" / "examples" / "extra.py").write_text("print('extra')\n", encoding="utf-8")
        failures = self.build().check("site").failures
        self.assertIn("the gallery (gallery/index.html) shows no figure", failures)
        self.assertIn("docs/examples/extra.py is run but no page of the site shows it", failures)

    def test_without_sphinx_in_the_environment_the_build_says_how_to_install_it(self):
        self.fix_faults()
        record = docs.build(self.root, self.root, python=sys.executable, offline=True)
        build = record.check("build")
        self.assertFalse(build.passed)
        self.assertIn("wayline docs env", build.failures[0])
        for later in ("reference", "site", "links"):
            self.assertTrue(record.check(later).skipped, later)
            self.assertFalse(record.check(later).passed, later)

    def test_the_printed_report_ends_with_the_failures(self):
        record = self.build()
        text = record.text()
        self.assertIn("docs/examples/broken.py exited 1", text)
        self.assertTrue(text.rstrip().splitlines()[-1].startswith("      - "), text)
        last_pass = max(text.index("  pass  " + check.id) for check in record.checks if check.passed)
        first_fail = min(text.index("  FAIL  " + check.id) for check in record.checks if not check.passed)
        self.assertLess(last_pass, first_fail)


class ReviewFixesTest(DocsCase):
    """What the review of ticket 51 found, each held here."""

    def test_an_unreachable_host_or_a_5xx_is_a_note_and_only_the_servers_4xx_fails(self):
        self.fix_faults()
        self.append("docs/explanation/index.rst", "\nSee `down <https://example.org/down>`_, `busy <https://example.org/busy>`_, "
                                                   "and `gone <https://example.org/gone>`_.\n")
        fetcher = FakeFetcher({"https://example.org/busy": 503, "https://example.org/gone": 410})
        links = self.build(fetcher=fetcher, offline=False).check("links")
        self.assertEqual(links.failures, ["explanation/index.html links to https://example.org/gone, which answered 410"])
        self.assertTrue(any("https://example.org/down could not be reached, not counted" in note for note in links.notes), links.notes)
        self.assertIn("https://example.org/busy answered 503, not counted", links.notes)

    def test_a_protocol_relative_link_is_an_external_link_not_a_crash(self):
        self.fix_faults()
        self.append("docs/explanation/index.rst", "\nSee `the cdn <//cdn.example.org/x>`_.\n")
        fetcher = FakeFetcher({"https://cdn.example.org/x": 200})
        record = self.build(fetcher=fetcher, offline=False)
        self.assertTrue(record.passed, record.text())
        self.assertEqual(fetcher.asked, [("HEAD", "https://cdn.example.org/x")])

    def test_a_build_that_writes_no_front_page_leaves_the_served_site_as_it_was(self):
        self.fix_faults()
        self.build()
        served = self.root / docs.SITE_INDEX
        before = served.read_text(encoding="utf-8")
        record = docs.build(self.root, self.root, python=sys.executable, offline=True)  # no Sphinx in this interpreter
        self.assertFalse(record.check("build").passed)
        self.assertEqual(served.read_text(encoding="utf-8"), before)
        self.assertFalse((self.root / docs.STAGING_DIR).exists())

    def test_a_build_out_of_time_still_writes_its_record_and_says_what_it_did_not_run(self):
        self.fix_faults()
        record = docs.build(self.root, self.root, python=sys.executable, sphinx=FakeSphinx(), offline=True, budget_s=0)
        self.assertEqual(record.check("examples").failures,
                         ["docs/examples/basic.py was not run: the build's time ran out (policy.acceptance_timeout_s)"])
        self.assertIn("the build's time ran out", record.check("build").failures[0])
        self.assertFalse(read_json(self.root / docs.CHECKS_JSON)["pass"])

    def test_the_budget_is_inside_the_acceptance_timeout(self):
        self.assertLess(docs.budget_for(self.root), 600)
        self.assertGreater(docs.budget_for(self.root), 500)

    def test_a_layout_outside_docs_is_refused_by_name(self):
        harness = read_json(self.root / "harness.json")
        harness["docs"]["layout"]["tutorials"] = "guides/tutorials"
        (self.root / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        with self.assertRaises(docs.DocsError) as raised:
            self.build()
        self.assertIn("harness.json.docs.layout.tutorials is 'guides/tutorials'", str(raised.exception))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["docs", "build", "--project", str(self.root), "--root", str(self.root)]), 2)
        self.assertIn("docs/", err.getvalue())

    def test_env_with_a_missing_interpreter_says_so(self):
        harness = read_json(self.root / "harness.json")
        harness["docs"]["python"] = str(self.temp / "no-such-python")
        (self.root / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        with self.assertRaises(docs.DocsError) as raised:
            docs.env(self.root, self.root)
        self.assertIn("no interpreter at", str(raised.exception))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class InitTest(DocsCase):
    def setUp(self):
        super().setUp()
        for path in (self.root / "docs", self.root / ".readthedocs.yaml"):
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        harness = json.loads((self.root / "harness.json").read_text(encoding="utf-8"))
        del harness["docs"]
        (self.root / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def harness_docs(self):
        return json.loads((self.root / "harness.json").read_text(encoding="utf-8"))["docs"]

    def test_init_lays_out_the_four_parts_and_records_the_theme_package_and_layout(self):
        written = docs.init(self.root, theme="furo")
        for path in ("docs/conf.py", "docs/index.rst", "docs/requirements.txt", ".readthedocs.yaml",
                     "docs/tutorials/index.rst", "docs/how-to/index.rst", "docs/reference/index.rst",
                     "docs/explanation/index.rst", "docs/gallery/index.rst", "docs/examples/index.rst",
                     "docs/reference/tinydocs.core.rst", "harness.json"):
            self.assertIn(path, written)
        self.assertEqual(self.harness_docs(), {"theme": "furo", "package": "src/tinydocs", "layout": docs.DEFAULT_LAYOUT})
        self.assertIn('html_theme = "furo"', (self.root / "docs" / "conf.py").read_text(encoding="utf-8"))
        self.assertIn("furo", (self.root / "docs" / "requirements.txt").read_text(encoding="utf-8").split())
        self.assertIn(".. automodule:: tinydocs.core", (self.root / "docs" / "reference" / "tinydocs.core.rst").read_text(encoding="utf-8"))

    def test_a_second_init_writes_nothing_and_adds_a_reference_page_for_a_new_module(self):
        docs.init(self.root, theme="furo")
        self.assertEqual(docs.init(self.root), [])
        (self.root / "src" / "tinydocs" / "stats.py").write_text('"""Spread."""\n\ndef spread(v):\n    """Max minus min."""\n    return max(v) - min(v)\n', encoding="utf-8")
        self.assertEqual(docs.init(self.root), ["docs/reference/tinydocs.stats.rst"])

    def test_the_theme_is_chosen_once(self):
        docs.init(self.root, theme="furo")
        with self.assertRaises(docs.DocsError) as raised:
            docs.init(self.root, theme="alabaster")
        self.assertIn("furo", str(raised.exception))
        self.assertEqual(self.harness_docs()["theme"], "furo")

    def test_a_fresh_skeleton_builds_and_fails_only_where_content_is_owed(self):
        docs.init(self.root, theme="alabaster")
        self.fix_faults_in_code()
        record = self.build()
        failed = {check.id: check.failures for check in record.checks if not check.passed}
        self.assertEqual(set(failed), {"structure", "site"}, record.text())
        self.assertEqual(failed["structure"], ["docs/examples holds no example (a .py file the build runs)"])
        self.assertEqual(failed["site"], ["the gallery (gallery/index.html) shows no figure"])

    def fix_faults_in_code(self):
        core = self.root / "src" / "tinydocs" / "core.py"
        core.write_text(core.read_text(encoding="utf-8").replace(
            "def undocumented_helper(value):\n", "def undocumented_helper(value):\n    \"\"\"Twice.\"\"\"\n"), encoding="utf-8")


class FakePython:
    """`subprocess.run` for `docs.env`: a venv command lays out `bin/python`; a pip probe answers by how the venv was made.

    `ensurepip` False is Debian's Python without python3-venv: the plain venv is left half-made, an
    interpreter with no pip, and only the fallback that sees the interpreter's own pip has one.
    """

    def __init__(self, venv, ensurepip=True):
        self.venv, self.ensurepip, self.commands, self.pip = venv, ensurepip, [], False

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            (self.venv / "bin").mkdir(parents=True, exist_ok=True)
            (self.venv / "bin" / "python").write_text("", encoding="utf-8")
            self.pip = self.ensurepip or "--system-site-packages" in argv
            return _Done(0 if self.pip else 1)
        if argv[1:] == ["-m", "pip", "--version"]:
            return _Done(0 if self.pip else 1)
        return _Done(0)

    def made(self):
        return [command[3:] for command in self.commands if command[1:3] == ["-m", "venv"]]


class EnvTest(DocsCase):
    def setUp(self):
        super().setUp()
        self.venv = self.root / "research" / ".cache" / "docs" / "venv"
        self.install = [str(self.venv / "bin" / "python"), "-m", "pip", "install", "-r", str(self.root / "docs" / "requirements.txt")]

    def test_env_makes_a_venv_under_the_project_cache_and_installs_the_requirements_there(self):
        fake = FakePython(self.venv)
        docs.env(self.root, self.root, run=fake)
        self.assertEqual(fake.made(), [[str(self.venv)]])
        self.assertEqual(fake.commands[-1], self.install)

    def test_a_venv_with_pip_is_kept(self):
        fake = FakePython(self.venv)
        docs.env(self.root, self.root, run=fake)
        again = FakePython(self.venv)
        again.pip = True
        docs.env(self.root, self.root, run=again)
        self.assertEqual(again.made(), [])

    def test_a_python_without_ensurepip_gets_a_venv_on_its_own_pip(self):
        fake = FakePython(self.venv, ensurepip=False)
        docs.env(self.root, self.root, run=fake)
        self.assertEqual(fake.made(), [[str(self.venv)], ["--system-site-packages", "--without-pip", str(self.venv)]])
        self.assertEqual(fake.commands[-1], self.install)

    def test_a_half_made_venv_a_failed_run_left_is_made_again(self):
        (self.venv / "bin").mkdir(parents=True)
        (self.venv / "bin" / "python").write_text("", encoding="utf-8")
        fake = FakePython(self.venv, ensurepip=False)
        docs.env(self.root, self.root, run=fake)
        self.assertEqual(fake.made()[-1], ["--system-site-packages", "--without-pip", str(self.venv)])
        self.assertEqual(fake.commands[-1], self.install)

    def test_a_recorded_python_is_installed_into_and_no_venv_is_made(self):
        harness = json.loads((self.root / "harness.json").read_text(encoding="utf-8"))
        harness["docs"]["python"] = "/opt/env/bin/python"
        (self.root / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        fake = FakePython(self.venv)
        docs.env(self.root, self.root, run=fake)
        self.assertEqual(fake.commands, [["/opt/env/bin/python", "-m", "pip", "install", "-r", str(self.root / "docs" / "requirements.txt")]])


class _Done:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class CommandTest(DocsCase):
    def test_docs_build_exits_1_and_prints_the_failures(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["docs", "build", "--project", str(self.root), "--root", str(self.root),
                             "--python", sys.executable, "--offline"])
        self.assertEqual(code, 1)
        self.assertIn("wayline docs env", out.getvalue())

    def test_docs_with_no_action_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["docs"]), 2)


class RealRunnerTest(DocsCase):
    """`run_sphinx` for real: the probe, the subprocess, and the argv, against `tests/fake_sphinx/sphinx`."""

    def setUp(self):
        super().setUp()
        previous = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = os.pathsep.join([str(FAKE_SPHINX), str(HARNESS_ROOT)] + ([previous] if previous else []))
        self.addCleanup(self._restore, previous)

    @staticmethod
    def _restore(previous):
        if previous is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous

    def test_the_real_runner_builds_through_python_dash_m_sphinx(self):
        self.fix_faults()
        record = docs.build(self.root, self.root, python=sys.executable, offline=True)
        self.assertTrue(record.passed, record.text())
        self.assertTrue((self.root / docs.HTML_DIR / "reference" / "tinydocs.core.html").is_file())

    def test_docs_build_exits_0_when_every_check_passes(self):
        self.fix_faults()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["docs", "build", "--project", str(self.root), "--root", str(self.root),
                             "--python", sys.executable, "--offline"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertTrue(out.getvalue().startswith("wayline docs build: pass"))


class DocsReadTest(ConductorCase):
    """The one Type-B read a done docs ticket earns, through the gate of ticket 32."""

    TICKET = {"id": 3, "title": "Document the package", "kind": "docs", "touches": ["docs/", ".readthedocs.yaml"],
              "acceptance": {"machine": ["test -f docs/index.rst"], "quality": []}}

    def test_a_docs_ticket_earns_the_docs_read_and_no_other_read_at_any_difficulty(self):
        for difficulty in (1, 3, 5):
            asks = gates.ticket_asks(self.TICKET, difficulty, "sonnet", "research/tickets/03-document-the-package.md", commit="abc")
            self.assertEqual([ask.verdict_type for ask in asks], [gates.DOCS_READ], difficulty)
        (ask,) = asks
        self.assertIn("clear and complete against the package's purpose", ask.question)
        for path in ("docs/", ".readthedocs.yaml", "research/INTAKE.md", "README.md", "research/.cache/docs/checks.json"):
            self.assertIn(path, ask.paths)

    def test_quality_criteria_are_asked_beside_the_docs_read(self):
        ticket = dict(self.TICKET, acceptance={"machine": ["true"], "quality": ["The tutorial ends with a working mean."]})
        asks = gates.ticket_asks(ticket, 2, "sonnet", "research/tickets/03-document-the-package.md")
        self.assertEqual([ask.verdict_type for ask in asks], [gates.QUALITY, gates.DOCS_READ])

    def test_the_docs_read_is_taken_by_the_verifier_and_journaled(self):
        (ask,) = gates.ticket_asks(self.TICKET, 1, "sonnet", "research/tickets/03-document-the-package.md")
        with worker.use_fake() as fake:
            fake.script(passing(question_limit="Only whether a reader could use the package from the site."), role="verifier")
            taken = gates.verdict_for(ask, project=self.project)
            calls = list(fake.calls)
        self.assertTrue(taken.passed)
        (event,) = self.events("verdict")
        self.assertEqual((event["payload"]["verdict_type"], event["ticket"]), ("docs_read", 3))
        (call,) = calls
        self.assertEqual(call.request.model, "opus", "a sonnet author's verifier, by policy.verifier")
        self.assertIn("research/.cache/docs/checks.json", call.request.prompt)


class ReportTest(RunCase):
    """REPORT.md's tickets-closed section names the site whenever a code ticket added public API."""

    def add_ticket(self, identifier, title, kind, status, blocked_by, body=""):
        fields = {"id": identifier, "title": title, "kind": kind, "difficulty": 2, "status": status,
                  "blocked_by": blocked_by, "touches": ["docs/"] if kind == "docs" else ["src/toy/"],
                  "role": "documentarian" if kind == "docs" else "coder", "skills": [],
                  "acceptance": {"machine": ["true"], "quality": []}, "origin": "SPEC.md#seams",
                  "proposed_by": "planner", "demo": "A page a person reads."}
        tickets.write_ticket(self.book, fields, "## Demo\n\nA page a person reads.\n" + body)

    def fifth(self):
        self.render(draft=False, offline=True)
        return self.section(5)

    def test_a_run_whose_code_added_no_public_api_says_nothing_of_a_site(self):
        self.assertNotIn("documentation site", self.fifth())

    def test_the_site_is_listed_with_its_docs_ticket_and_the_last_build(self):
        self.add_ticket(12, "Add the metric module", "code", "accepted", [], "\n" + PUBLIC_API_HEADING + "\n\n" + PUBLIC_API_LINE + "\n")
        self.add_ticket(13, "Document the metric module", "docs", "accepted", [12])
        record = self.project / docs.CHECKS_JSON
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"ran_at": "2026-09-23T12:00:00Z", "pass": True, "site": "research/.cache/docs/html/index.html",
                                      "checks": [{"check": check, "pass": True} for check in docs.CHECKS]}), encoding="utf-8")
        fifth = self.fifth()
        self.assertIn("The documentation site, part of done because ticket(s) 12 added public API:", fifth)
        self.assertIn("- Ticket 13, *Document the metric module* (docs): accepted", fifth)
        self.assertIn("- The site `research/.cache/docs/html/index.html`, built 2026-09-23T12:00:00Z: every machine check passed.", fifth)
        self.assertNotIn("Owed", fifth)

    def test_a_docs_ticket_documents_what_it_waits_on_through_a_chain(self):
        api = "\n" + PUBLIC_API_HEADING + "\n\n" + PUBLIC_API_LINE + "\n"
        self.add_ticket(12, "Add the metric module", "code", "accepted", [], api)
        self.add_ticket(13, "Add the plot module on the metric module", "code", "accepted", [12], api)
        self.add_ticket(14, "Document both modules", "docs", "accepted", [13])
        fifth = self.fifth()
        self.assertIn("ticket(s) 12, 13 added public API", fifth)
        self.assertNotIn("Owed", fifth)

    def test_public_api_with_no_closed_docs_ticket_is_the_site_still_owed(self):
        self.add_ticket(12, "Add the metric module", "code", "done", [], "\n" + PUBLIC_API_HEADING + "\n\n" + PUBLIC_API_LINE + "\n")
        self.add_ticket(13, "Document the metric module", "docs", "open", [12])
        fifth = self.fifth()
        self.assertIn("- The site has not been built on `main` (no `research/.cache/docs/checks.json`).", fifth)
        self.assertIn("- Owed: ticket 12 added public API and no closed docs ticket documents it.", fifth)


class SiteServedTest(DashboardTestCase):
    """The outputs index names the site built on main, and `site/` serves its pages inline, in a sandbox."""

    def setUp(self):
        super().setUp()
        html_dir = self.project / docs.HTML_DIR
        (html_dir / "reference").mkdir(parents=True)
        (html_dir / "index.html").write_text('<a href="reference/">reference</a>\n', encoding="utf-8")
        (html_dir / "reference" / "index.html").write_text("<h1>Reference</h1>\n", encoding="utf-8")
        (self.project / docs.CHECKS_JSON).write_text(json.dumps({"ran_at": "2026-09-23T12:00:00Z", "pass": True}), encoding="utf-8")

    def test_the_outputs_index_carries_the_site_with_its_last_checks(self):
        (site,) = self.api("/outputs").json["site"]
        self.assertEqual((site["path"], site["url"], site["built"], site["passed"]),
                         ("research/.cache/docs/html/index.html", "site/index.html", "2026-09-23T12:00:00Z", True))

    def test_pages_are_served_inline_in_a_sandbox_and_a_directory_is_its_index(self):
        page = self.api("/site/reference/")
        self.assertEqual(page.status, 200)
        self.assertEqual(page.text, "<h1>Reference</h1>\n")
        self.assertTrue(page.headers.get("content-type").startswith("text/html"))
        self.assertEqual(page.headers.get("content-security-policy"), "sandbox allow-scripts allow-popups")
        self.assertIsNone(page.headers.get("content-disposition"), "a page is read, not downloaded")

    def test_nothing_outside_the_site_is_served_through_it(self):
        for path in ("/site/../../../harness.json", "/site/%2e%2e/checks.json", "/site/missing.html"):
            self.assertEqual(self.api(path).status, 404, path)

    def test_the_dashboard_never_puts_the_token_in_the_sites_url(self):
        script = (HARNESS_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        body = script[script.index("function siteRow("):script.index("function outputRow(")]
        self.assertNotIn("TOKEN", body.split("\n", 1)[1], "a script in a model-written page can read its own URL")

    def test_no_site_is_an_empty_list(self):
        shutil.rmtree(self.project / docs.HTML_DIR)
        self.assertEqual(self.api("/outputs").json["site"], [])


class AcceptanceTest(unittest.TestCase):
    def test_a_docs_ticket_is_always_accepted_by_the_docs_build(self):
        ticket = {"kind": "docs", "acceptance": {"machine": ["test -f docs/index.rst"]}}
        self.assertEqual(machine_acceptance(ticket), ["test -f docs/index.rst", "wayline docs build"])

    def test_the_worker_is_told_the_build_is_part_of_its_acceptance(self):
        from wayline.worker import _ticket_section
        ticket = {"id": 7, "title": "Document the package", "kind": "docs", "touches": ["docs/"],
                  "acceptance": {"machine": ["test -f docs/tutorials/first.rst"]}}
        section = _ticket_section(ticket, None)
        self.assertIn("    - `test -f docs/tutorials/first.rst`\n    - `wayline docs build`", section)

    def test_the_documentarian_is_the_role_the_librarian_gives_a_docs_ticket(self):
        from wayline import proposals, registry
        entries = [dict(registry.read_sidecar(path / "wayline.json", "role", path.name), kind="role", assignable=True,
                        outcome={"assigned": 0, "passed_first_time": 0})
                   for path in sorted((FIXTURES_DIR.parent / "roles").iterdir()) if (path / "wayline.json").is_file()]
        self.assertEqual(registry.librarian({"kind": "docs"}, {"entries": entries})["role"], "documentarian")
        self.assertEqual(proposals.KIND_ROLE["docs"], "documentarian")

    def test_acceptance_runs_this_harness_s_wayline_whatever_the_path_says(self):
        with unittest.mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            (result,) = gates.run_machine_acceptance(["command -v wayline"], HARNESS_ROOT, 30)
        self.assertEqual(result["tail"].strip(), str(HARNESS_ROOT / "bin" / "wayline"))

    def test_the_build_is_not_added_twice_nor_to_another_kind(self):
        self.assertEqual(machine_acceptance({"kind": "docs", "acceptance": {"machine": ["wayline docs build"]}}),
                         ["wayline docs build"])
        for spelled in ("wayline docs build --offline", "cd . && wayline docs build", "bin/wayline  docs build"):
            self.assertEqual(machine_acceptance({"kind": "docs", "acceptance": {"machine": [spelled]}}), [spelled], spelled)
        self.assertEqual(machine_acceptance({"kind": "docs", "acceptance": {"machine": ["echo nowayline docs build"]}})[-1],
                         "wayline docs build")
        self.assertEqual(machine_acceptance({"kind": "code", "acceptance": {"machine": ["true"]}}), ["true"])


if __name__ == "__main__":
    unittest.main()
