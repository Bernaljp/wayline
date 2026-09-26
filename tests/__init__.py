"""The suite never reaches the owner's user manager (Implementation Decisions 7).

`WAYLINE_UNITS=none` is set before any test module is imported, and every process a test starts
inherits it, so `init` writes no unit into `~/.config/systemd/user` and `run` starts no dashboard
service. The tests of the units stand `wayline.tick.use_fake_systemd` in for the manager instead.

`WAYLINE_UNPINNED=1` likewise lets `run` start against a harness checkout that is not at the
project's pin (Implementation Decisions 5). The suite runs between tags by construction, and a
shallow clone has no tags at all. The tests of the pin pass their own environment instead.

`WAYLINE_NOTIFY=none` keeps the notifier's channels off, so a conductor that opens a decision
ticket in a test journals its notification and sends nothing to the owner's desktop or phone. The
tests of the notifier pass their own `run` for the channels instead.

`WAYLINE_BACKENDS=none` makes every real backend raise `wayline.BackendTouched` if it is reached:
the `claude` executable (a session, `/usage`, the login check), the network behind the fetch seam,
and nvidia-smi. The suite runs without the subscription, the network, or a GPU (ticket 47), and a
test that would have reached one fails instead. The tests of the real launcher pass their own
environment without it, with a fake executable standing in for `claude`.

`python -m unittest` runs the whole suite in parallel (ticket 47: under a minute): `load_tests`
below forks one child per test class, `WAYLINE_TEST_JOBS` at a time (default the CPU count, at
most 32), and replays each child's outcomes into the runner's result, so the summary, the failure
blocks, `--durations`, and the exit code read as a serial run's do. `WAYLINE_TEST_JOBS=1` runs it
serially; naming a module or a test (`python -m unittest tests.test_changes`) never forks.
"""

import os
import pickle
import sys
import tempfile
import traceback
import unittest

os.environ["WAYLINE_UNITS"] = "none"
os.environ["WAYLINE_UNPINNED"] = "1"
os.environ["WAYLINE_NOTIFY"] = "none"
os.environ["WAYLINE_BACKENDS"] = "none"

JOBS_ENV = "WAYLINE_TEST_JOBS"


def lift_backends(case):
    """Lift `WAYLINE_BACKENDS=none` for one test, for the tests of a real backend that stand in its command."""
    previous = os.environ.pop("WAYLINE_BACKENDS", None)
    if previous is not None:
        case.addCleanup(os.environ.__setitem__, "WAYLINE_BACKENDS", previous)


def load_tests(loader, standard_tests, pattern):
    """Discovery of the package (`python -m unittest`): the package's tests, run by `ParallelSuite`."""
    here = os.path.dirname(os.path.abspath(__file__))
    found = loader.discover(start_dir=here, pattern=pattern or "test*.py", top_level_dir=os.path.dirname(here))
    standard_tests.addTests(found)
    jobs = _jobs()
    return ParallelSuite(standard_tests, jobs) if jobs > 1 else standard_tests


def _jobs():
    text = os.environ.get(JOBS_ENV, "").strip()
    if text:
        try:
            return max(1, int(text))
        except ValueError:
            raise ValueError("%s=%r is not a number of processes" % (JOBS_ENV, text)) from None
    return max(1, min(os.cpu_count() or 1, 32))


def _flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


class _Reported:
    """A test as the parent prints it: the description a child recorded for it."""

    def __init__(self, text, short):
        self.text, self.short = text, short

    def __str__(self):
        return self.text

    def shortDescription(self):
        return self.short

    def id(self):
        return self.text


class _Recorder(unittest.TestResult):
    """A child's result: every outcome in order, as text a pipe can carry back to the parent."""

    def __init__(self):
        super().__init__()
        self.events = []

    def _key(self, test):
        return (str(test), test.shortDescription() if hasattr(test, "shortDescription") else None)

    def _note(self, kind, test, detail=None):
        self.events.append((kind, self._key(test), detail))

    def startTest(self, test):
        super().startTest(test)
        self._note("start", test)

    def stopTest(self, test):
        super().stopTest(test)
        self._note("stop", test)

    def addSuccess(self, test):
        self._note("success", test)

    def addError(self, test, err):
        self._note("errors", test, self._exc_info_to_string(err, test))

    def addFailure(self, test, err):
        self._note("failures", test, self._exc_info_to_string(err, test))

    def addSubTest(self, test, subtest, err):
        if err is not None:
            kind = "failures" if issubclass(err[0], test.failureException) else "errors"
            self._note(kind, subtest, self._exc_info_to_string(err, subtest))

    def addSkip(self, test, reason):
        self._note("skip", test, reason)

    def addExpectedFailure(self, test, err):
        self._note("expected", test, self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        self._note("unexpected", test)

    def addDuration(self, test, elapsed):
        self._note("duration", test, elapsed)


class ParallelSuite(unittest.TestSuite):
    """The suite, one forked child per test class, `jobs` children at a time.

    A class is the unit because `setUpClass` and `tearDownClass` must run once around its tests in one
    process; the package has no module fixtures. The classes with the most tests start first, so a long
    class is not the last one left running. Each child writes its outcomes to a file and exits; the parent
    replays them into the runner's result as the child ends, so the dots arrive a class at a time.
    """

    def __init__(self, tests, jobs):
        super().__init__()
        self.inner, self.jobs = tests, jobs

    def countTestCases(self):
        return self.inner.countTestCases()

    def run(self, result, debug=False):
        units = {}
        for test in _flatten(self.inner):
            units.setdefault((type(test).__module__, type(test).__qualname__), []).append(test)
        queue = sorted(units.values(), key=len, reverse=True)
        running, started = {}, 0
        with tempfile.TemporaryDirectory(prefix="wayline-tests-") as scratch:
            try:
                while queue or running:
                    while queue and len(running) < self.jobs and not result.shouldStop:
                        tests, started = queue.pop(0), started + 1
                        path = os.path.join(scratch, "%d.pickle" % started)
                        running[self._fork(tests, path)] = (tests, path)
                    if not running:
                        break
                    pid, status = os.wait()
                    if pid not in running:
                        continue
                    tests, path = running.pop(pid)
                    self._replay(result, tests, path, status)
            finally:
                for pid in running:
                    try:
                        os.kill(pid, 9)
                        os.waitpid(pid, 0)
                    except OSError:
                        pass
        return result

    def _fork(self, tests, path):
        pid = os.fork()
        if pid:
            return pid
        code = 0
        try:
            recorder = _Recorder()
            unittest.TestSuite(tests).run(recorder)
            with open(path, "wb") as handle:
                pickle.dump(recorder.events, handle)
        except BaseException:
            traceback.print_exc()
            code = 70
        finally:
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.flush()
                except Exception:
                    pass
            os._exit(code)

    def _replay(self, result, tests, path, status):
        try:
            with open(path, "rb") as handle:
                events = pickle.load(handle)
        except (OSError, EOFError, pickle.UnpicklingError):
            events = None
        if events is None:  # the child died before it could say how its class went
            holder = _Reported("%s (a child process that ended with status %d)" % (type(tests[0]).__qualname__, status), None)
            result.startTest(holder)
            _report(result, "errors", holder, "the forked child running %s.%s left no outcomes; it ended with wait status %d\n"
                    % (type(tests[0]).__module__, type(tests[0]).__qualname__, status))
            result.stopTest(holder)
            return
        holders = {}
        for kind, key, detail in events:
            holder = holders.setdefault(key, _Reported(*key))
            if kind == "start":
                result.startTest(holder)
            elif kind == "stop":
                result.stopTest(holder)
            elif kind == "success":
                result.addSuccess(holder)
            elif kind == "skip":
                result.addSkip(holder, detail)
            elif kind == "unexpected":
                result.addUnexpectedSuccess(holder)
            elif kind == "duration":
                if hasattr(result, "addDuration"):
                    result.addDuration(holder, detail)
            elif kind == "expected":
                result.expectedFailures.append((holder, detail))
            else:
                _report(result, kind, holder, detail)


def _report(result, kind, holder, text):
    """Append a failure or an error the child already formatted, and print its mark as the runner would."""
    getattr(result, kind).append((holder, text))
    stream = getattr(result, "stream", None)
    if stream is None:
        return
    if getattr(result, "showAll", False):
        stream.writeln("FAIL" if kind == "failures" else "ERROR")
    elif getattr(result, "dots", False):
        stream.write("F" if kind == "failures" else "E")
        stream.flush()
    if getattr(result, "failfast", False):
        result.stop()
