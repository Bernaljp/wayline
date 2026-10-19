"""The rule from code to Methods (Implementation Decision 17; ticket 107).

The check is a Type-A function over a worktree and a result: a temporary project whose `main` holds the
code before the ticket and whose branch holds the ticket's change, both from the start-midway fixture's
`phaselock.py` and `phaselock.m` (ticket 78). Methods passages go in through the ledger. The parsers run
through the tool runner's recordings (`fixtures/methods/recorded/`): tree-sitter-matlab's parse of each
MATLAB file and `inspect.signature` in a project environment, both recorded live; the Sonnet reading of
another language goes through the fake launcher.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, patch
from tests.test_verdicts import GateCase, failing, passing
from wayline import gates, methods, sections, tickets, worker
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.tools import Tools, ToolOutput

ROOT = Path(__file__).resolve().parent.parent
MIDWAY = ROOT / "fixtures" / "midway"
OWN = ROOT / "fixtures" / "methods"
RECORDED = OWN / "recorded"


def _midway():
    spec = importlib.util.spec_from_file_location("midway_build_code", MIDWAY / "build_code.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIDWAY_CODE = _midway()
PY_FIRST, PY_SECOND, MATLAB = MIDWAY_CODE.PY_FIRST, MIDWAY_CODE.PY_SECOND, MIDWAY_CODE.MATLAB
SWEEP = (OWN / "phaselock_sweep.m").read_text(encoding="utf-8")


def git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


class Recorded:
    """The tool runner answering from `fixtures/methods/recorded/`: what each parser printed when it ran live."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        if argv[1].endswith("matlab_parse.py"):
            digest = hashlib.sha256(Path(argv[2]).read_bytes()).hexdigest()[:16]
            where = RECORDED / "matlab_parse" / ("%s.json" % digest)
            if not where.exists():
                return ToolOutput(1, b"", ("nothing recorded for %s (%s)" % (argv[2], digest)).encode())
            return ToolOutput(0, where.read_bytes(), b"")
        if argv[1] == "-c":
            found = {}
            for name in json.loads(argv[3]):
                where = RECORDED / "signatures" / ("%s.json" % name)
                found[name] = json.loads(where.read_text()) if where.exists() else {"error": "ModuleNotFoundError: %s" % name}
            return ToolOutput(0, json.dumps({"signatures": found}).encode(), b"")
        return ToolOutput(127, b"", b"not recorded")


class MethodsCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "lantern"
        self.project.mkdir()
        init_project(self.project)
        self.ledger = Ledger(self.project)
        self.run = Recorded()
        self.tools = Tools(root=self.temp / "tools", record={"tools": {"tree-sitter-matlab": {
            "executable": sys.executable, "version": "1.3.1", "env": {}, "route": "uv"}}})

    def on_main(self, files):
        for name, text in files.items():
            path = self.project / "code" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "code on main")

    def ticket(self, files):
        """The ticket's branch: `files` written under `code/` and committed on top of `main`."""
        git(self.project, "checkout", "-q", "-b", "ticket-1")
        self.on_main(files)

    def methods_passage(self, text, heading="Phase locking"):
        return sections.add_passage(self.ledger, "methods", heading, text, by="owner")

    def check(self, **result):
        base = {"ticket_id": 1, "status": "done", "summary": "changed the order parameter"}
        base.update(result)
        return methods.check(self.ledger, self.project, base, run=self.run, tools=self.tools)

    def assertProblem(self, outcome, *words):
        found = [problem for problem in outcome.problems if all(word in problem for word in words)]
        self.assertTrue(found, "no problem names %s: %s" % (words, outcome.problems))


class DevelopedMethodsTest(MethodsCase):
    def test_an_untagged_developed_method_sends_the_ticket_back_naming_it(self):
        self.on_main({"README.md": "the lantern moths\n"})
        self.ticket({"phaselock.py": PY_SECOND})
        outcome = self.check()
        self.assertProblem(outcome, "order_parameter", "code/phaselock.py")
        self.assertProblem(outcome, "colony_synchrony")
        self.assertFalse(outcome.passed)

    def test_a_code_tag_naming_the_method_or_its_lines_in_a_current_passage_passes_it(self):
        self.on_main({"phaselock.py": PY_FIRST})
        self.methods_passage("The order parameter is the modulus of the mean phase vector across moths, the phase taken "
                             "from the analytic signal {code:code/phaselock.py#order_parameter}.")
        self.ticket({"phaselock.py": PY_SECOND})
        outcome = self.check(passages=[{"section": "methods", "heading": "Phase locking", "replaces": None,
                                        "text": "Colony synchrony is the order parameter over 512 samples {code:code/phaselock.py#L10-L12}."}],
                             parameters=[{"method": "order_parameter", "name": "window", "reason": "A 512-sample window spans two wingbeats."}])
        self.assertEqual([problem for problem in outcome.problems if "developed method" in problem], [])

    def test_a_replaced_passage_no_longer_names_a_method(self):
        self.on_main({"README.md": "the lantern moths\n"})
        tagged = self.methods_passage("The order parameter averages the phase vector {code:code/phaselock.py#order_parameter}.")
        self.ticket({"phaselock.py": PY_FIRST})
        outcome = self.check(passages=[{"section": "methods", "heading": "Phase locking", "replaces": tagged["id"],
                                        "text": "The order parameter averages the phase vector over moths."}])
        self.assertProblem(outcome, "order_parameter", "no `code` tag")

    def test_plumbing_is_excluded_by_code(self):
        self.on_main({"README.md": "the lantern moths\n"})
        self.ticket({"io_helpers.py": "def load_traces(path):\n    return open(path).read()\n\n\ndef _clean(x):\n    return x\n",
                     "tests/test_phase.py": "def check_order():\n    return 1\n"})
        outcome = self.check()
        self.assertEqual(outcome.problems, [])

    def test_a_change_outside_code_is_not_checked(self):
        self.on_main({"README.md": "the lantern moths\n"})
        git(self.project, "checkout", "-q", "-b", "ticket-1")
        (self.project / "notes.md").write_text("notes\n")
        git(self.project, "add", "notes.md")
        git(self.project, "commit", "-q", "-m", "notes")
        self.assertIsNone(self.check())


class NotMethodsTest(MethodsCase):
    def test_a_method_listed_in_not_methods_passes_and_goes_to_the_verdict(self):
        self.on_main({"phaselock.py": PY_FIRST})
        self.methods_passage("The order parameter averages the phase vector {code:code/phaselock.py#order_parameter}.")
        self.ticket({"phaselock.py": PY_SECOND})
        why = "It only fixes the window the figures use; the method is order_parameter."
        outcome = self.check(not_methods=[{"name": "colony_synchrony", "why": why}],
                             parameters=[{"method": "order_parameter", "name": "window", "reason": "Two wingbeats fit in 512 samples."}])
        self.assertEqual(outcome.problems, [])
        self.assertEqual(outcome.not_methods, [{"name": "colony_synchrony", "why": why}])
        self.assertEqual(outcome.code_rule()["not_methods"], [{"name": "colony_synchrony", "why": why}])


class UsedMethodsTest(MethodsCase):
    def setUp(self):
        super().setUp()
        self.on_main({"README.md": "the lantern moths\n"})
        self.ticket({"phaselock.py": PY_FIRST})

    def test_a_used_method_no_methods_passage_names_sends_the_ticket_back(self):
        self.methods_passage("The order parameter averages the phase vector over moths {code:code/phaselock.py#order_parameter}.")
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": "Two wingbeats at 2000 Hz."}])
        self.assertProblem(outcome, "scipy.signal.hilbert", "Hilbert transform", "not named in a Methods passage")

    def test_an_alias_in_a_methods_passage_names_it(self):
        self.methods_passage("The phase is taken from the analytic signal {code:code/phaselock.py#order_parameter}.")
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": "Two wingbeats at 2000 Hz."}])
        self.assertEqual([problem for problem in outcome.problems if "used method" in problem], [])


class ParametersTest(MethodsCase):
    def setUp(self):
        super().setUp()
        self.on_main({"phaselock.py": PY_FIRST})
        self.methods_passage("The phase is taken from the analytic signal {code:code/phaselock.py#order_parameter}; colony "
                             "synchrony is its value over the colony {code:code/phaselock.py#colony_synchrony}.")

    def test_an_unexplained_non_default_sends_the_ticket_back(self):
        self.ticket({"phaselock.py": PY_SECOND})
        outcome = self.check()
        self.assertProblem(outcome, "order_parameter", "`window` to 512", "default is 256", "code/phaselock.py:13")
        self.assertFalse(outcome.passed)

    def test_a_reason_passes_and_code_fills_its_value_and_default(self):
        self.ticket({"phaselock.py": PY_SECOND})
        reason = "A 512-sample window spans two full wingbeats at 2000 frames per second."
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": reason}])
        self.assertEqual(outcome.problems, [])
        self.assertEqual(outcome.parameters, [{"method": "order_parameter", "name": "window", "reason": reason,
                                               "value": "512", "default": "256", "path": "code/phaselock.py", "line": 13}])

    def test_a_value_the_parsers_cannot_see_is_kept_as_the_worker_gave_it(self):
        self.ticket({"phaselock.py": PY_SECOND})
        entries = [{"method": "order_parameter", "name": "window", "reason": "Two wingbeats."},
                   {"method": "band-pass filter", "name": "band", "value": "20-60 Hz", "reason": "The wingbeat band of the moths."}]
        outcome = self.check(parameters=entries)
        self.assertEqual(outcome.parameters[1], entries[1])

    def test_one_reason_covers_a_methods_own_default_and_a_call_that_sets_it_with_a_row_for_each_value(self):
        git(self.project, "rm", "-q", "code/phaselock.py")
        git(self.project, "commit", "-q", "-m", "no code yet")
        self.ticket({"phaselock.py": PY_SECOND})
        reason = "The default spans one wingbeat; colony synchrony takes two."
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": reason}])
        self.assertEqual(outcome.problems, [])
        self.assertEqual([(entry["value"], entry["default"], entry["reason"]) for entry in outcome.parameters],
                         [("256", None, reason), ("512", "256", reason)])

    def test_a_new_methods_own_numeric_default_needs_a_reason(self):
        self.ticket({"phaselock.py": PY_FIRST.replace("window=256", "window=128")})
        outcome = self.check()
        self.assertProblem(outcome, "order_parameter", "gives `window` the default 128")

    def test_an_unseeded_random_state_needs_a_reason(self):
        jitter = PY_SECOND + "\n\ndef jittered(traces):\n    rng = np.random.default_rng()\n    return traces + rng.normal(size=traces.shape)\n"
        self.methods_passage("Jitter is added before the order parameter {code:code/phaselock.py#jittered}.")
        self.ticket({"phaselock.py": jitter})
        reason = "Two wingbeats at 2000 Hz."
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": reason}])
        self.assertProblem(outcome, "numpy.random.default_rng", "random state no seed fixes", "`seed`")
        seeded = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": reason},
                                        {"method": "numpy.random.default_rng", "name": "seed",
                                         "reason": "Each sweep draws fresh jitter, and the result is averaged over 50 sweeps."}])
        self.assertEqual(seeded.problems, [])
        self.assertEqual((seeded.parameters[1]["value"], seeded.parameters[1]["default"]), (methods.UNSET, methods.UNSEEDED))

    def test_a_global_random_draw_with_no_seed_needs_a_reason(self):
        noisy = PY_SECOND + "\n\ndef noisy(traces):\n    return traces + np.random.randn(*traces.shape)\n"
        self.methods_passage("Noise is added {code:code/phaselock.py#noisy}.")
        self.ticket({"phaselock.py": noisy})
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": "Two wingbeats."}])
        self.assertProblem(outcome, "numpy.random.randn", "random state no seed fixes")

    def test_default_solver_tolerances_left_unset_need_a_reason(self):
        ode = PY_SECOND + ("\n\nfrom scipy.integrate import solve_ivp\n\n\ndef drift(rate):\n"
                           "    return solve_ivp(lambda t, y: -rate * y, (0, 10), [1.0])\n")
        self.methods_passage("The drift is integrated numerically {code:code/phaselock.py#drift}.")
        self.ticket({"phaselock.py": ode})
        outcome = self.check(parameters=[{"method": "order_parameter", "name": "window", "reason": "Two wingbeats."}])
        self.assertProblem(outcome, "scipy.integrate.solve_ivp", "leaves `rtol` at its default (1e-3)")
        self.assertProblem(outcome, "scipy.integrate.solve_ivp", "leaves `atol` at its default (1e-6)")


class NotCheckedTest(MethodsCase):
    """`hilbert(..., axis=1)` sets a library parameter: its default comes from the project's environment, or is not checked."""

    def setUp(self):
        super().setUp()
        self.on_main({"README.md": "the lantern moths\n"})
        self.methods_passage("The phase is taken from the analytic signal {code:code/phaselock.py#order_parameter}.")
        self.ticket({"phaselock.py": PY_FIRST})
        self.reason = {"method": "order_parameter", "name": "window", "reason": "Two wingbeats at 2000 Hz."}

    def test_without_the_projects_environment_a_default_is_not_checked_and_does_not_fail(self):
        outcome = self.check(parameters=[self.reason])
        self.assertEqual(outcome.problems, [])
        self.assertTrue(any("not installed" in note for note in outcome.notes), outcome.notes)
        self.assertTrue(any("`axis`" in note and methods.NOT_CHECKED in note for note in outcome.notes), outcome.notes)
        self.assertFalse([call for call in self.run.calls if call[1] == "-c"], "no environment, so no probe ran")
        given = self.check(parameters=[self.reason, {"method": "scipy.signal.hilbert", "name": "axis", "reason": "Time runs along rows."}])
        self.assertEqual(given.parameters[1]["default"], methods.NOT_CHECKED)

    def test_in_the_projects_environment_the_signature_gives_the_default(self):
        python = self.project / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("")
        outcome = self.check(parameters=[self.reason])
        self.assertProblem(outcome, "scipy.signal.hilbert", "`axis` to 1", "default is -1")
        probe = [call for call in self.run.calls if call[1] == "-c"]
        self.assertEqual(probe[0][0], str(python))
        self.assertEqual(json.loads(probe[0][3]), ["scipy.signal.hilbert"])


class MatlabTest(MethodsCase):
    """The MATLAB parser: tree-sitter-matlab's recorded parse, the documented-defaults table, and backward slices."""

    def setUp(self):
        super().setUp()
        self.on_main({"README.md": "the lantern moths\n"})

    def problems(self, outcome, *words):
        return [problem for problem in outcome.problems if all(word in problem for word in words)]

    def test_the_parse_runs_through_the_tool_runner_in_the_tools_venv(self):
        self.ticket({"phaselock.m": MATLAB})
        self.check()
        parse = [call for call in self.run.calls if call[1].endswith("matlab_parse.py")]
        self.assertEqual(parse, [[sys.executable, str(methods.MATLAB_PARSER), str(self.project / "code" / "phaselock.m")]])

    def test_an_untagged_matlab_method_its_used_method_and_its_own_default_send_the_ticket_back(self):
        self.ticket({"phaselock.m": MATLAB})
        outcome = self.check()
        self.assertProblem(outcome, "`phaselock`", "code/phaselock.m:1", "no `code` tag")
        self.assertProblem(outcome, "`hilbert`", "Hilbert transform", "not named")
        self.assertProblem(outcome, "`phaselock` (code/phaselock.m:3) gives `window` the default 512")
        self.assertFalse(self.problems(outcome, "traces"), "indexing a variable is not a call")

    def test_a_tagged_and_explained_matlab_file_passes(self):
        self.methods_passage("The phase is taken from the analytic signal of each moth's trace {code:code/phaselock.m#phaselock}.")
        self.ticket({"phaselock.m": MATLAB})
        outcome = self.check(parameters=[{"method": "phaselock", "name": "window", "reason": "Two wingbeats at 2000 Hz."}])
        self.assertEqual(outcome.problems, [])
        self.assertEqual(outcome.parameters[0]["value"], "512")

    def test_a_parameter_given_as_a_variable_is_traced_back_to_its_value(self):
        self.methods_passage("Spectra are estimated by Welch's method and the drift integrated numerically "
                             "{code:code/phaselock_sweep.m#phaselock_sweep}.")
        self.ticket({"phaselock_sweep.m": SWEEP})
        outcome = self.check()
        self.assertProblem(outcome, "`pwelch` (code/phaselock_sweep.m:8)", "`window` to hamming(seglen)")
        self.assertProblem(outcome, "`pwelch` (code/phaselock_sweep.m:8)", "`fs` to 2000", "default is 2*pi")
        self.assertFalse(self.problems(outcome, "noverlap"), "an empty [] keeps the documented default")
        self.assertProblem(outcome, "`phaselock_sweep`", "gives `fs` the default 2000")

    def test_an_unseeded_draw_and_default_solver_tolerances_need_reasons(self):
        self.methods_passage("Spectra are estimated by Welch's method and the drift integrated numerically "
                             "{code:code/phaselock_sweep.m#phaselock_sweep}.")
        self.ticket({"phaselock_sweep.m": SWEEP})
        outcome = self.check()
        self.assertProblem(outcome, "`randn` (code/phaselock_sweep.m:6)", "random state no seed fixes")
        self.assertProblem(outcome, "`ode45` (code/phaselock_sweep.m:9)", "leaves `RelTol` at its default (1e-3)")
        self.assertProblem(outcome, "`ode45` (code/phaselock_sweep.m:9)", "leaves `AbsTol` at its default (1e-6)")

    def test_the_parse_fills_the_code_dossiers_methods_for_a_matlab_repository(self):
        from wayline import code_dossier
        dest = self.temp / "inherited"
        MIDWAY_CODE.build(dest)
        (dest / "phaselock.py").unlink()
        git(dest, "commit", "-q", "-am", "only the MATLAB port")
        sha = git(dest, "rev-parse", "HEAD")
        dossier = code_dossier.code_dossier("varga-2022-phaselock", str(dest), sha, dest, run=self.run, tools=self.tools)
        self.assertEqual(dossier["language"], "matlab")
        self.assertIsNone(dossier["inventory"]["note"])
        self.assertEqual([(module["path"], [function["name"] for function in module["functions"]])
                          for module in dossier["inventory"]["modules"]], [("phaselock.m", ["phaselock"])])
        self.assertIn({"kind": "developed", "name": "phaselock", "path": "phaselock.m", "line": 1}, dossier["methods"])
        self.assertIn({"kind": "used", "name": "hilbert", "path": "phaselock.m", "line": 4, "method": "Hilbert transform"},
                      dossier["methods"])


class ReadingTest(MethodsCase):
    """Another language gets one Sonnet reading at acceptance, through the fake launcher; grep checks each item."""

    JULIA = ("using DSP\n\nfunction order_parameter(traces; window=256)\n"
             "    phases = angle.(hilbert(traces[:, 1:window]))\n"
             "    return abs(mean(exp.(im .* phases)))\nend\n")

    def answer(self):
        return {"files": [{"path": "code/phaselock.jl",
                           "developed": [{"name": "order_parameter", "line": 3, "end_line": 6},
                                         {"name": "colony_synchrony", "line": 8}],
                           "used": [{"call": "hilbert", "method": "Hilbert transform", "line": 4, "aliases": ["analytic signal"]}],
                           "parameters": [{"method": "order_parameter", "name": "window", "value": "256", "default": None,
                                           "line": 3, "what": "own default"}]}]}

    def read(self, **result):
        self.on_main({"README.md": "the lantern moths\n"})
        self.ticket({"phaselock.jl": self.JULIA})
        with worker.use_fake() as fake:
            fake.script(worker.Envelope(structured_output=self.answer(), session_id="read-1", num_turns=1,
                                        usage={"input_tokens": 900, "output_tokens": 120}))
            outcome = self.check(**result)
            self.calls = list(fake.calls)
        return outcome

    def test_the_reading_names_the_methods_and_grep_drops_what_the_file_does_not_hold(self):
        outcome = self.read()
        self.assertEqual(len(self.calls), 1)
        request = self.calls[0].request
        self.assertEqual((request.role, request.model), (methods.READER, "sonnet"))
        self.assertIn("    3  function order_parameter(traces; window=256)", request.prompt)
        self.assertProblem(outcome, "`order_parameter` (code/phaselock.jl:3)", "no `code` tag")
        self.assertProblem(outcome, "`hilbert`", "not named")
        self.assertProblem(outcome, "gives `window` the default 256")
        self.assertFalse([problem for problem in outcome.problems if "colony_synchrony" in problem])
        self.assertTrue(any("grep did not find" in note and "colony_synchrony" in note for note in outcome.notes), outcome.notes)

    def test_the_readings_cost_rides_on_the_acceptance_result(self):
        outcome = self.read()
        accepted = outcome.acceptance_result()
        self.assertEqual(accepted["exit_code"], 1)
        self.assertEqual(accepted["reading"]["session_id"], "read-1")
        self.assertEqual(accepted["reading"]["usage"], {"input_tokens": 900, "output_tokens": 120})
        self.assertEqual(accepted["reading"]["lines"], 6)

    def test_a_reading_that_cannot_be_taken_leaves_the_files_not_checked(self):
        self.on_main({"README.md": "the lantern moths\n"})
        self.ticket({"phaselock.jl": self.JULIA})
        with worker.use_fake() as fake:
            fake.script(worker.Envelope(structured_output=None, session_id="read-1", errors=["no structured output"]))
            fake.script(worker.Envelope(structured_output=None, session_id="read-1", errors=["no structured output"]))
            outcome = self.check()
        self.assertEqual(outcome.problems, [])
        self.assertTrue(any("could not be taken" in note and methods.NOT_CHECKED in note for note in outcome.notes), outcome.notes)

    def test_a_tagged_and_explained_file_passes_the_reading(self):
        self.methods_passage("The phase is taken from the analytic signal {code:code/phaselock.jl#order_parameter}.")
        outcome = self.read(parameters=[{"method": "order_parameter", "name": "window", "reason": "Two wingbeats at 2000 Hz."}])
        self.assertEqual(outcome.problems, [])


class SchemaTest(MethodsCase):
    def test_the_result_schema_carries_parameters_and_not_methods(self):
        result = {"ticket_id": 1, "status": "done", "summary": "s",
                  "parameters": [{"method": "order_parameter", "name": "window", "reason": "Two wingbeats."}],
                  "not_methods": [{"name": "colony_synchrony", "why": "It only fixes the window."}]}
        self.assertEqual(validate(result, load_schema("result")), [])
        result["parameters"][0].pop("reason")
        self.assertTrue(validate(result, load_schema("result")))


class VerdictTest(GateCase):
    """The verifier's verdict is given the reasons and the `not_methods` to judge, and its schema carries the judgment."""

    RULE = {"parameters": [{"method": "order_parameter", "name": "window", "reason": "Two wingbeats fit in 512 samples.",
                            "value": "512", "default": "256", "path": "code/phaselock.py", "line": 13}],
            "not_methods": [{"name": "colony_synchrony", "why": "It only fixes the window the figures use."}]}

    def ticket(self, quality=()):
        return {"id": 4, "title": "Use a 512-sample window", "acceptance": {"machine": ["true"], "quality": list(quality)}}

    def asks(self, difficulty, quality=(), rule=RULE):
        return gates.ticket_asks(self.ticket(quality), difficulty, "sonnet", "research/tickets/04-window.md", commit="abc123",
                                 code_rule=rule)

    def test_the_independent_read_carries_the_reasons_and_the_not_methods(self):
        asks = self.asks(3)
        self.assertEqual([ask.verdict_type for ask in asks], [gates.DIFF])
        for text in ("`order_parameter`", "`window` = 512", "default 256", "code/phaselock.py:13", "Two wingbeats fit in 512 samples.",
                     "colony_synchrony", "It only fixes the window the figures use.", "`code_rule`"):
            self.assertIn(text, asks[0].question)

    def test_a_ticket_that_earns_no_read_earns_one_for_its_reasons(self):
        self.assertEqual(self.asks(2, rule=None), [])
        asks = self.asks(2)
        self.assertEqual([ask.verdict_type for ask in asks], [gates.DIFF])
        self.assertIn("`code_rule`", asks[0].question)

    def test_with_quality_criteria_and_no_read_the_quality_verdict_carries_them(self):
        asks = self.asks(1, ["The window matches the figures."])
        self.assertEqual([ask.verdict_type for ask in asks], [gates.QUALITY])
        self.assertIn("Two wingbeats fit in 512 samples.", asks[0].question)

    def test_a_reason_judged_not_to_hold_fails_the_verdict(self):
        judged = {"parameters": [{"method": "order_parameter", "name": "window", "holds": False,
                                  "why": "Two wingbeats is not why 512 differs from the 256 the Methods states."}],
                  "not_methods": [{"name": "colony_synchrony", "holds": True, "why": "It is a wrapper."}]}
        taken = self.take(passing(code_rule=judged),
                          failing(text="The window's reason does not hold.", locator="code/phaselock.py#L13", code_rule=judged))
        self.assertFalse(taken.passed)
        self.assertEqual(taken.code_rule, judged)
        self.assertEqual(len(self.calls), 2, "a pass carrying a reason that does not hold is sent back once")
        self.assertIn("does not hold", self.calls[1].message)


class AtAcceptanceTest(ConductorCase):
    """The conductor runs the rule at the worktree's acceptance, sends the worker back with the list, and the verdict judges."""

    REASON = "A 256-sample window spans one wingbeat at 2000 frames per second."

    def setUp(self):
        super().setUp()
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, touches=["code/phaselock.py"], outputs=["code/phaselock.py"],
                                               acceptance={"machine": ["test -f code/phaselock.py"], "quality": []}), body)

    def run_ticket(self):
        first = done(outputs_written=["code/phaselock.py"])
        resumed = done(outputs_written=["code/phaselock.py"], passages=[{
            "section": "methods", "heading": "Phase locking", "replaces": None,
            "text": "The phase of each trace is taken from its analytic signal {code:code/phaselock.py#order_parameter}."}],
            parameters=[{"method": "order_parameter", "name": "window", "reason": self.REASON}])
        verdict = passing(code_rule={"parameters": [{"method": "order_parameter", "name": "window", "holds": True,
                                                     "why": "One wingbeat is what the order parameter averages over."}],
                                     "not_methods": []})
        self.conduct((first, patch({"code/phaselock.py": PY_FIRST}, message="ticket 1: the order parameter")),
                     (resumed, None), (verdict, None))

    def test_an_untagged_method_sends_the_worker_back_with_its_name(self):
        self.run_ticket()
        acceptance = self.events("acceptance")
        self.assertEqual([(event["payload"]["where"], event["payload"]["pass"]) for event in acceptance][:2],
                         [("worktree", False), ("worktree", True)])
        checked = [result for result in acceptance[0]["payload"]["results"] if result["cmd"] == methods.CHECK]
        self.assertIn("`order_parameter`", checked[0]["tail"])
        self.assertIn("order_parameter", self.calls[1].message)
        self.assertIn("no `code` tag", self.calls[1].message)
        self.assertEqual(self.payload("ticket_resumed")["reason"], "acceptance_failed")

    def test_the_filled_reasons_reach_the_ticket_file_and_the_verdict(self):
        self.run_ticket()
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / "01-write-the-hello-file.md")
        self.assertIn("Parameters:", body)
        self.assertIn("- `order_parameter` `window` = 256 at `code/phaselock.py:6`: %s" % self.REASON, body)
        kept = json.loads((worker.session_dir(self.project, 1, 1) / methods.CODE_RULE_FILE).read_text())
        self.assertEqual(kept["parameters"][0]["value"], "256")
        verdict_prompt = self.calls[2].request.prompt
        self.assertIn(self.REASON, verdict_prompt)
        self.assertIn("`code_rule`", verdict_prompt)
        self.assertEqual(self.ticket()["status"], "accepted")
