"""The suite runs offline and in under a minute (ticket 47, M6 criterion 8).

`WAYLINE_BACKENDS=none`, which `tests/__init__.py` sets, makes the `claude` executable and the
network raise if reached, and reads the machine as one with no GPU; `load_tests` there runs the
suite in forked children and folds their outcomes into one result.
"""

import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests
from wayline import BACKENDS_ENV, BackendTouched, figure_checks, resources, tools, worker
from wayline.fetch import Fetcher, UrllibBackend


class FlagTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-offline-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        patched = mock.patch.dict(os.environ)
        patched.start()
        self.addCleanup(patched.stop)
        os.environ.pop("WAYLINE_CLAUDE", None)

    def test_the_suite_sets_it(self):
        self.assertEqual(os.environ.get(BACKENDS_ENV), "none")

    def test_the_claude_executable_raises_for_a_session_the_usage_and_the_login(self):
        with mock.patch("wayline.worker.subprocess") as spawned:
            for call in (lambda cli: cli._executable(), lambda cli: cli.usage(), lambda cli: cli.auth_status()):
                with self.assertRaises(BackendTouched) as raised:
                    call(worker.ClaudeCli())
                self.assertIn("claude executable", str(raised.exception))
        self.assertFalse(spawned.mock_calls, "nothing was started")

    def test_a_stand_in_named_by_wayline_claude_is_not_the_subscription(self):
        stand_in = self.temp / "claude"
        stand_in.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stand_in.chmod(0o755)
        os.environ["WAYLINE_CLAUDE"] = str(stand_in)
        self.assertEqual(worker.ClaudeCli()._executable(), str(stand_in))

    def test_the_free_pre_check_is_a_note_as_on_a_machine_without_the_cli(self):
        findings, note = worker.validate_plugin(self.temp)
        self.assertEqual(findings, {})
        self.assertIn("did not run", note)

    def test_the_network_raises_before_a_socket_is_opened(self):
        with mock.patch("urllib.request.OpenerDirector.open") as opened:
            with self.assertRaises(BackendTouched) as raised:
                Fetcher(UrllibBackend()).fetch("https://api.crossref.org/works/10.1/x")
        self.assertIn("api.crossref.org", str(raised.exception))
        self.assertFalse(opened.called)

    def test_the_tools_install_raises_before_it_downloads(self):
        with self.assertRaises(BackendTouched):
            tools.install(root=self.temp)
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_the_gpu_probe_reads_a_machine_with_no_gpu_without_running_nvidia_smi(self):
        with mock.patch("wayline.resources.subprocess.run") as ran:
            self.assertEqual(resources.read_gpus(), [])
            self.assertEqual(resources.read_gpu_processes(), [])
            self.assertIsNone(tools.driver_cuda())
        self.assertFalse(ran.called)

    def test_ruff_through_uvx_runs_from_the_cache_and_never_asks_the_index(self):
        """`uvx ruff` asks the package index on every run; the figure checks' `generator_clean` ran it in the suite."""
        which = {"uvx": "/bin/uvx"}.get
        self.assertEqual(figure_checks.Tools(which=which).argv("ruff"), ["/bin/uvx", "--offline", "ruff"])
        with mock.patch.dict(os.environ):
            os.environ.pop(BACKENDS_ENV, None)
            self.assertEqual(figure_checks.Tools(which=which).argv("ruff"), ["/bin/uvx", "ruff"])

    def test_lifting_it_holds_for_one_test_only(self):
        case = unittest.TestCase()
        tests.lift_backends(case)
        self.assertNotIn(BACKENDS_ENV, os.environ)
        case.doCleanups()
        self.assertEqual(os.environ.get(BACKENDS_ENV), "none")


def samples(parent):
    """Two classes for the runner to fork, built here so that the loader does not collect them."""

    class Sample(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.pid = os.getpid()

        def test_a_pass(self):
            self.assertEqual(os.getpid(), self.pid, "setUpClass ran in this test's own process")

        def test_b_fail(self):
            """A failure the parent prints."""
            self.assertEqual(1, 2)

        def test_c_error(self):
            raise KeyError("boom")

        @unittest.skip("not here")
        def test_d_skip(self):
            pass

        def test_e_subtests(self):
            for value in (1, 2):
                with self.subTest(value=value):
                    self.assertEqual(value, 1)

    class Other(unittest.TestCase):
        def test_parent_is_not_this_process(self):
            self.assertNotEqual(os.getpid(), parent)

    return Sample, Other


class ParallelSuiteTest(unittest.TestCase):
    def setUp(self):
        self.Sample, self.Other = samples(os.getpid())

    def run_parallel(self, *cases, jobs=2):
        loader = unittest.TestLoader()
        suite = unittest.TestSuite(loader.loadTestsFromTestCase(case) for case in cases)
        stream = io.StringIO()
        result = unittest.TextTestResult(unittest.runner._WritelnDecorator(stream), descriptions=True, verbosity=1)
        tests.ParallelSuite(suite, jobs)(result)
        result.printErrors()
        return result, stream.getvalue()

    def test_each_outcome_reaches_the_parent_s_result(self):
        result, printed = self.run_parallel(self.Sample, self.Other)
        self.assertEqual(result.testsRun, 6)
        self.assertEqual(len(result.failures), 2, "the failing test and the failing subtest")
        self.assertEqual(len(result.errors), 1)
        self.assertEqual([reason for _, reason in result.skipped], ["not here"])
        self.assertFalse(result.wasSuccessful())
        self.assertIn("AssertionError: 1 != 2", printed)
        self.assertIn("KeyError: 'boom'", printed)
        self.assertIn("A failure the parent prints.", printed)
        self.assertIn("(value=2)", printed)

    def test_a_suite_that_passes_is_successful(self):
        result, _ = self.run_parallel(self.Other, jobs=4)
        self.assertEqual((result.testsRun, result.wasSuccessful()), (1, True))

    def test_a_child_that_dies_is_an_error_naming_its_class(self):
        with mock.patch.object(self.Other, "test_parent_is_not_this_process", lambda case: os._exit(3)):
            result, printed = self.run_parallel(self.Other)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Other", printed)

    def test_one_job_is_the_plain_serial_suite(self):
        loader = unittest.TestLoader()
        with mock.patch.dict(os.environ, {tests.JOBS_ENV: "1"}):
            suite = tests.load_tests(loader, unittest.TestSuite(), "test_offline.py")
        self.assertNotIsInstance(suite, tests.ParallelSuite)
        self.assertTrue(suite.countTestCases())


if __name__ == "__main__":
    unittest.main()
