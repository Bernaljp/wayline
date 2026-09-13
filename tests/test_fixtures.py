"""The fixture runner and recorder (Implementation Decisions 12; ticket 44).

A fixture whose subject is a test prompt, run with the fake launcher as both the subject and the
judge: every structural check, the pass rule, the judge's launch, the caches, `--changed` and the
weekly window, the turn ceiling, the quarantine, the exit codes, and `fixture record` from a
journaled session. Nothing here reaches a model; `docs/verification/m6.md` holds the live runs.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from wayline import cli, fixtures, worker
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger
from wayline.worker import Envelope, LaunchRequest, Patch, RateLimitEvent, Window

ROLE = "greeter"
SUBJECT = "prompts/greeting.md"
SUBJECT_TEXT = "Greet each person named in notes/names.txt, and list whom you greeted.\n"
SCHEMA = {
    "type": "object",
    "required": ["word", "greeted"],
    "additionalProperties": False,
    "properties": {
        "word": {"type": "string"},
        "greeted": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "notes": {"type": ["string", "null"]},
        "checks": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}
GOOD = {"word": "hello", "greeted": ["ada", "grace"], "summary": "Greeted Ada and Grace.", "checks": {"pytest": "pass"}}
POLICY = {"fixtures": {"sample_size": 3, "at_least": 2, "flake_limit": 2, "stable_runs_to_restore": 3,
                       "max_turns_per_suite": 300, "judge": {"model": "haiku", "effort": "low"}}}
RUBRIC = "Question: does `summary` name only the people listed in `greeted`?\n"


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def good(**changes):
    output = json.loads(json.dumps(GOOD))
    output.update(changes)
    return Envelope(structured_output=output, num_turns=2, usage={"input_tokens": 100, "output_tokens": 10})


def verdict(value, session_id=None):
    return Envelope(structured_output={"verdict": value, "reason": "Because the fields say so."}, num_turns=1, session_id=session_id)


class Harness(unittest.TestCase):
    """A scratch tree holding a subject and `fixtures/`, and a scratch `WAYLINE_HOME` for the caches."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-fixtures-test-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.root = self.temp / "harness"
        self.home = self.temp / "home"
        environment = mock.patch.dict(os.environ, {"WAYLINE_HOME": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        write(self.root / SUBJECT, SUBJECT_TEXT)
        self.policy = json.loads(json.dumps(POLICY))
        self.calls, self.printed = [], ""

    def make_fixture(self, slug="greeting", subject=SUBJECT, structural=None, judged=True, strict=False,
                     baseline=None, sample_size=3, at_least=2, show_judge=("$.summary", "$.greeted")):
        directory = self.root / "fixtures" / "prompt" / slug
        text = (self.root / subject).read_text(encoding="utf-8")
        write(directory / "input" / "prompt.md", "# The task\n\n" + text + "\nReturn the structured result.\n")
        write(directory / "input" / "agent.json", json.dumps({ROLE: {"description": "Greets.", "prompt": "You greet people.", "permissionMode": "dontAsk"}}))
        write(directory / "input" / "schema.json", json.dumps(SCHEMA))
        write(directory / "input" / "subject" / subject, text)
        write(directory / "input" / "context" / "notes" / "names.txt", "ada\ngrace\n")
        write(directory / "rubric.md", RUBRIC)
        record = {
            "schema_version": 1, "id": "prompt/" + slug, "kind": "prompt",
            "subject": {"path": subject, "sha256": None, "also": []},
            "origin": {"project": None, "ticket": None, "session_id": None, "journal_ts": None, "change_record": None, "reason": "test"},
            "launch": {"role": ROLE, "model": "sonnet", "effort": "low", "permission_mode": "dontAsk", "output_format": "stream-json",
                       "json_schema": "input/schema.json", "allowed_tools": ["Read"], "disallowed_tools": ["WebFetch"],
                       "add_dirs": ["{project}"], "env": {"WAYLINE_PROJECT": "{project}", "WAYLINE_RUN": "{run}"}, "settings": None},
            "input": {"prompt": "input/prompt.md", "agent": "input/agent.json", "context_manifest": None, "input_hash": None},
            "structural": structural if structural is not None else [{"check": "schema_valid"}, {"check": "path_in", "path": "$.word", "values": ["hello"]}],
            "baseline": baseline,
            "quarantine": {"status": "active", "flake_limit": 2, "flakes": [], "stable_runs_to_restore": 3},
        }
        if judged:
            record["judged"] = {"rubric": "rubric.md", "show_judge": list(show_judge),
                                "judge": {"model": "haiku", "effort": "low", "tools": [], "votes": 1, "must_differ_from_subject_session": True},
                                "sample_size": sample_size, "pass_rule": {"at_least": at_least}, "strict": strict}
        write(directory / "fixture.json", json.dumps(record, indent=2) + "\n")
        return directory

    def record_of(self, slug="greeting"):
        return json.loads((self.root / "fixtures" / "prompt" / slug / "fixture.json").read_text(encoding="utf-8"))

    def update_record(self, slug="greeting", **fields):
        record = self.record_of(slug)
        record.update(fields)
        write(self.root / "fixtures" / "prompt" / slug / "fixture.json", json.dumps(record, indent=2) + "\n")

    def passing_baseline(self, slug="greeting"):
        """Stamp the fixture's current hashes as a baseline that passed 3/3 and 3/3."""
        directory = self.root / "fixtures" / "prompt" / slug
        record = self.record_of(slug)
        self.update_record(slug, baseline={
            "recorded_at": "2026-09-13T00:00:00Z", "structural": "3/3", "judged": "3/3", "passed": True, "unstable": False,
            "subject_sha256": fixtures.subject_sha256(record, self.root), "input_hash": fixtures.input_hash(directory, record)})

    def run_fixtures(self, subject=(), judge=(), **options):
        """Script the fake as subject and judge, run the fixtures, and keep the calls and the printout."""
        options.setdefault("policy", self.policy)
        with worker.use_fake() as fake:
            for entry in subject:
                envelope, patch = entry if isinstance(entry, tuple) else (entry, None)
                fake.script(envelope, patch=patch, role=ROLE)
            for envelope in judge:
                fake.script(envelope, role=fixtures.JUDGE_ROLE)
            out = StringIO()
            try:
                with redirect_stdout(out):
                    return fixtures.run(self.root, **options)
            finally:
                self.calls = list(fake.calls)
                self.printed = out.getvalue()

    def subject_calls(self):
        return [call for call in self.calls if call.request.role == ROLE]

    def judge_calls(self):
        return [call for call in self.calls if call.request.role == fixtures.JUDGE_ROLE]


# --- the structural checks ----------------------------------------------------------------------


class JsonPathTest(unittest.TestCase):
    def test_the_subset(self):
        value = {"a": {"b": 1}, "list": [{"x": 1}, {"x": 2}], "odd key": "k"}
        self.assertEqual(fixtures.jsonpath(value, "$"), [value])
        self.assertEqual(fixtures.jsonpath(value, "$.a.b"), [1])
        self.assertEqual(fixtures.jsonpath(value, "$.list[1].x"), [2])
        self.assertEqual(fixtures.jsonpath(value, "$.list[*].x"), [1, 2])
        self.assertEqual(fixtures.jsonpath(value, "$['odd key']"), ["k"])
        self.assertEqual(fixtures.jsonpath(value, "$.a.*"), [1])
        self.assertEqual(fixtures.jsonpath(value, "$.missing.deeper"), [])
        self.assertEqual(fixtures.jsonpath(value, "$.list[9]"), [])

    def test_a_path_outside_the_subset_is_refused(self):
        for path in ("a.b", "$..x", "$.list[?(@.x)]", "$.list[1:2]"):
            with self.subTest(path=path):
                with self.assertRaises(fixtures.FixtureError):
                    fixtures.jsonpath({}, path)


class StructuralChecksTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-checks-test-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.root = self.temp / "project"
        write(self.root / "out" / "hello.txt", "hello\n")
        self.trace = write(self.temp / "trace.jsonl", "\n".join(json.dumps(line) for line in [
            {"type": "system", "subtype": "init", "session_id": "s"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"},
                                                          {"type": "tool_use", "name": "Skill", "input": {"skill": "wayline-note"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "wayline intake notes.md"}}]}},
        ]) + "\n")
        write(self.temp / "checks.py", "\n".join([
            "def root_has_hello(root):",
            "    return [] if (root / 'out' / 'hello.txt').is_file() else ['no hello']",
            "def greeted_two(root, output):",
            "    return len(output['greeted']) == 2",
            "def always_wrong(root):",
            "    return ['wrong on purpose']",
        ]) + "\n")
        write(self.temp / "broken_checks.py", "raise ValueError('broken at import')\n")

    def check(self, check, output=GOOD, schema=SCHEMA):
        results = fixtures.structural_checks([check], output, self.root, trace=self.trace, fixture_dir=self.temp, schema=schema)
        self.assertEqual(results[0].check["check"], "schema_valid", "schema_valid runs first whether or not it is listed")
        return results[-1].passed

    def test_every_check_passes_and_fails(self):
        cases = [
            ({"check": "path_equals", "path": "$.word", "value": "hello"}, True),
            ({"check": "path_equals", "path": "$.checks.pytest", "value": "pass"}, True),
            ({"check": "path_equals", "path": "$.greeted[0]", "value": "ada"}, True),
            ({"check": "path_equals", "path": "$.word", "value": "bye"}, False),
            ({"check": "path_equals", "path": "$.missing", "value": None}, False),
            ({"check": "path_in", "path": "$.word", "values": ["hi", "hello"]}, True),
            ({"check": "path_in", "path": "$.word", "values": ["hi"]}, False),
            ({"check": "path_matches", "path": "$.greeted[*]", "regex": "^[a-z]+$"}, True),
            ({"check": "path_matches", "path": "$.greeted[*]", "regex": "^a"}, False),
            ({"check": "path_matches", "path": "$.missing", "regex": "."}, False),
            ({"check": "path_contains_all", "path": "$.greeted", "values": ["ada", "grace"]}, True),
            ({"check": "path_contains_all", "path": "$.greeted", "values": ["ada", "alan"]}, False),
            ({"check": "path_contains_all", "path": "$.summary", "values": ["Ada", "Grace"]}, True),
            ({"check": "path_contains_any", "path": "$.greeted", "values": ["alan", "grace"]}, True),
            ({"check": "path_contains_any", "path": "$.greeted", "values": ["alan"]}, False),
            ({"check": "path_count", "path": "$.greeted", "min": 2, "max": 2}, True),
            ({"check": "path_count", "path": "$.greeted", "max": 1}, False),
            ({"check": "path_count", "path": "$.greeted", "min": 3}, False),
            ({"check": "path_count", "path": "$.notes", "max": 0}, True),
            ({"check": "path_absent_or_empty", "path": "$.notes"}, True),
            ({"check": "path_absent_or_empty", "path": "$.greeted"}, False),
            ({"check": "file_exists", "path": "out/hello.txt", "in": "worktree"}, True),
            ({"check": "file_exists", "path": "out/missing.txt"}, False),
            ({"check": "file_exists", "path": "../trace.jsonl"}, False),
            ({"check": "file_absent", "path": "escaped.txt"}, True),
            ({"check": "file_absent", "path": "out/hello.txt"}, False),
            ({"check": "tool_used", "tool": "Skill", "arg": "wayline-note"}, True),
            ({"check": "tool_used", "tool": "Skill", "arg": "wayline-tally"}, False),
            ({"check": "tool_used", "tool": "Bash", "input_matches": "wayline intake"}, True),
            ({"check": "tool_used", "tool": "WebFetch"}, False),
            ({"check": "tool_not_used", "tool": "WebFetch"}, True),
            ({"check": "tool_not_used", "tool": "Skill"}, False),
            ({"check": "python", "file": "checks.py", "fn": "root_has_hello"}, True),
            ({"check": "python", "file": "checks.py", "fn": "greeted_two"}, True),
            ({"check": "python", "file": "checks.py", "fn": "always_wrong"}, False),
            ({"check": "python", "file": "checks.py", "fn": "not_there"}, False),
            ({"check": "python", "file": "broken_checks.py", "fn": "anything"}, False),
            ({"check": "tool_used", "tool": "Bash", "input_matches": "("}, False),
            ({"check": "schema_valid"}, True),
        ]
        for check, expected in cases:
            with self.subTest(check=check):
                self.assertIs(self.check(check), expected)
        kinds = {check["check"] for check, _ in cases}
        self.assertEqual(kinds, set(fixtures.CHECKS), "every check of decision 12 is exercised both ways")

    def test_empty_values_count_as_empty(self):
        for value in (None, [], {}, ""):
            with self.subTest(value=value):
                self.assertTrue(self.check({"check": "path_absent_or_empty", "path": "$.notes"}, output=dict(GOOD, notes=value),
                                           schema=None))

    def test_an_output_the_schema_rejects_fails_schema_valid_and_runs_nothing_else(self):
        results = fixtures.structural_checks([{"check": "path_in", "path": "$.word", "values": ["hello"]}],
                                             {"word": "hello"}, self.root, schema=SCHEMA)
        self.assertEqual([result.passed for result in results], [False, False])
        self.assertIn("greeted", results[0].detail)
        self.assertIn("not run", results[1].detail)

    def test_a_session_without_a_schema_is_schema_valid_when_it_ended_cleanly(self):
        self.assertTrue(fixtures.structural_checks([], None, self.root, schema=None, ended_ok=True)[0].passed)
        self.assertFalse(fixtures.structural_checks([], None, self.root, schema=None, ended_ok=False)[0].passed)
        result = fixtures.structural_checks([{"check": "path_equals", "path": "$.word", "value": "x"}], None, self.root, schema=None)
        self.assertFalse(result[1].passed)


# --- the pass rule and the judge ------------------------------------------------------------------


class PassRuleTest(Harness):
    def test_structural_n_of_n_and_judged_at_least_2_of_3(self):
        self.make_fixture()
        result = self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass"), verdict("pass"), verdict("fail")], ids=["prompt/greeting"])
        run = result.runs[0]
        self.assertEqual((run.structural, run.judged, run.n), (3, 2, 3))
        self.assertTrue(run.passed)
        self.assertEqual(result.exit_code, 0)
        for text in ("prompt/greeting", "structural 3/3", "judged 2/3", "baseline", "delta", "cost"):
            self.assertIn(text, self.printed)

    def test_one_of_three_judged_fails(self):
        self.make_fixture()
        run = self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass"), verdict("fail"), verdict("fail")], ids=["prompt/greeting"]).runs[0]
        self.assertEqual(run.judged, 1)
        self.assertFalse(run.passed)

    def test_strict_forces_n_of_n(self):
        self.make_fixture(strict=True)
        run = self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass"), verdict("pass"), verdict("fail")], ids=["prompt/greeting"]).runs[0]
        self.assertEqual(run.judged, 2)
        self.assertFalse(run.passed)

    def test_one_structural_miss_fails_the_fixture_and_the_judge_is_never_launched(self):
        self.make_fixture()
        run = self.run_fixtures(subject=[good(), good(word="bye"), good()], ids=["prompt/greeting"]).runs[0]
        self.assertEqual(run.structural, 2)
        self.assertIsNone(run.judged)
        self.assertFalse(run.passed)
        self.assertEqual(len(self.subject_calls()), 3)
        self.assertEqual(self.judge_calls(), [])

    def test_a_fixture_without_a_judged_layer_passes_on_structure_alone(self):
        self.make_fixture(judged=False)
        run = self.run_fixtures(subject=[good()] * 3, ids=["prompt/greeting"]).runs[0]
        self.assertEqual((run.structural, run.judged, run.n), (3, None, 3))
        self.assertTrue(run.passed)

    def test_the_subject_runs_the_pinned_input_in_a_project_holding_the_context_and_never_bare(self):
        self.make_fixture(structural=[{"check": "schema_valid"}, {"check": "file_exists", "path": "out/hello.txt"},
                                      {"check": "file_exists", "path": "notes/names.txt"}], judged=False)
        run = self.run_fixtures(subject=[(good(), Patch({"out/hello.txt": "hello\n"}, commit=False))] * 3, ids=["prompt/greeting"]).runs[0]
        self.assertEqual(run.structural, 3)
        call = self.subject_calls()[0]
        self.assertIn(SUBJECT_TEXT.strip(), call.request.prompt)
        self.assertEqual((call.request.model, call.request.effort, call.request.allowed_tools), ("sonnet", "low", ["Read"]))
        self.assertEqual(call.request.env["WAYLINE_PROJECT"], str(call.request.cwd))
        self.assertEqual(call.request.env["WAYLINE_RUN"], str(call.run_dir))
        for placeholder in ("{harness}", "{project}", "{run}"):
            self.assertNotIn(placeholder, json.dumps(call.request.env) + call.request.prompt)
        command = json.loads((call.run_dir / "env.json").read_text(encoding="utf-8"))["command"]
        self.assertNotIn("--bare", command)


    def test_a_ticket_launch_runs_in_a_git_project_on_the_ticket_branch(self):
        self.make_fixture(judged=False)
        record = self.record_of()
        record["launch"]["env"].update(TICKET_TOUCHES="m0/", WAYLINE_TICKET="1")
        self.update_record(launch=record["launch"])
        self.run_fixtures(subject=[good()] * 3, ids=["prompt/greeting"])
        cwd = self.subject_calls()[0].request.cwd
        branch = subprocess.run(["git", "-C", str(cwd), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "ticket/1")

    def test_a_cache_under_the_claude_directory_is_refused_before_anything_launches(self):
        self.make_fixture()
        under = Path.home() / ".claude" / "wayline-fixture-test-never-written"
        with mock.patch.dict(os.environ, {"WAYLINE_HOME": str(under)}):
            with self.assertRaises(fixtures.FixtureError) as caught:
                self.run_fixtures(subject=[good()] * 3, ids=["prompt/greeting"])
        self.assertIn("Edit(~/.claude/**)", str(caught.exception))
        self.assertEqual(self.calls, [])
        self.assertFalse(under.exists())


class JudgeTest(Harness):
    def test_the_judge_is_a_fresh_haiku_low_session_with_no_tools_shown_only_the_named_fields(self):
        self.make_fixture()
        self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass")] * 3, ids=["prompt/greeting"])
        calls = self.judge_calls()
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call.kind, "launch", "never a resume of the subject's session")
            self.assertIsNone(call.session_id)
            self.assertEqual((call.request.model, call.request.effort), ("haiku", "low"))
            self.assertEqual(call.request.allowed_tools, [])
            for tool in ("Read", "Bash", "Write", "Grep"):
                self.assertIn(tool, call.request.disallowed_tools)
            self.assertEqual(Path(call.request.schema_path).name, "fixture_verdict.json")
            self.assertIn(RUBRIC.strip(), call.request.prompt)
            self.assertIn("Greeted Ada and Grace.", call.request.prompt)
            self.assertIn("$.greeted", call.request.prompt)
            self.assertNotIn("pytest", call.request.prompt, "a field show_judge does not name is not shown")
            self.assertNotIn("hello", call.request.prompt)

    def test_a_judge_that_answers_from_the_subjects_session_is_a_fail(self):
        self.make_fixture()
        subject = [Envelope(structured_output=GOOD, session_id="the-subject")] * 3
        run = self.run_fixtures(subject=subject, judge=[verdict("pass", session_id="the-subject")] * 3, ids=["prompt/greeting"]).runs[0]
        self.assertEqual(run.judged, 0)
        self.assertIn("session", run.samples[0].verdict["reason"])

    def test_a_judge_without_a_usable_answer_is_a_fail_for_that_sample(self):
        self.make_fixture()
        broken = Envelope(subtype="error_max_structured_output_retries", is_error=True)
        run = self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass"), broken, verdict("pass")], ids=["prompt/greeting"]).runs[0]
        self.assertEqual(run.judged, 2)
        self.assertTrue(run.passed)

    def test_votes_take_the_majority_of_independent_calls(self):
        self.make_fixture(sample_size=1, at_least=1)
        record = self.record_of()
        record["judged"]["judge"]["votes"] = 3
        self.update_record(judged=record["judged"])
        run = self.run_fixtures(subject=[good()], judge=[verdict("fail"), verdict("pass"), verdict("pass")], ids=["prompt/greeting"]).runs[0]
        self.assertEqual((run.judged, len(self.judge_calls())), (1, 3))


# --- the caches -----------------------------------------------------------------------------------


class CacheTest(Harness):
    def first_run(self):
        self.make_fixture()
        return self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass")] * 3, ids=["prompt/greeting"])

    def test_an_unchanged_fixture_costs_nothing_the_second_time(self):
        self.first_run()
        self.assertEqual((len(self.subject_calls()), len(self.judge_calls())), (3, 3), "one subject run per sample index")
        run = self.run_fixtures(ids=["prompt/greeting"]).runs[0]
        self.assertEqual(self.calls, [])
        self.assertEqual((run.structural, run.judged), (3, 3))
        self.assertTrue(all(sample.cached for sample in run.samples))
        self.assertEqual(run.cost["turns"], 0)

    def test_a_changed_rubric_reruns_only_the_judge(self):
        self.first_run()
        write(self.root / "fixtures" / "prompt" / "greeting" / "rubric.md", "Question: is the word a greeting?\n")
        self.run_fixtures(judge=[verdict("pass")] * 3, ids=["prompt/greeting"])
        self.assertEqual((len(self.subject_calls()), len(self.judge_calls())), (0, 3))

    def test_a_changed_subject_reruns_the_subject_with_the_new_text(self):
        self.first_run()
        write(self.root / SUBJECT, "Greet only Ada.\n")
        self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass")] * 3, ids=["prompt/greeting"])
        self.assertEqual(len(self.subject_calls()), 3)
        prompt = self.subject_calls()[0].request.prompt
        self.assertIn("Greet only Ada.", prompt)
        self.assertNotIn(SUBJECT_TEXT.strip(), prompt)

    def test_a_changed_model_reruns_the_subject(self):
        self.first_run()
        record = self.record_of()
        record["launch"]["model"] = "opus"
        self.update_record(launch=record["launch"])
        self.run_fixtures(subject=[good()] * 3, ids=["prompt/greeting"])
        self.assertEqual(len(self.subject_calls()), 3)

    def test_no_cache_launches_again(self):
        self.first_run()
        self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass")] * 3, ids=["prompt/greeting"], use_cache=False)
        self.assertEqual((len(self.subject_calls()), len(self.judge_calls())), (3, 3))


class SelectionTest(Harness):
    def setUp(self):
        super().setUp()
        write(self.root / "prompts" / "farewell.md", "Say goodbye.\n")
        self.make_fixture("greeting")
        self.make_fixture("farewell", subject="prompts/farewell.md")

    def test_changed_runs_only_the_fixtures_whose_subject_changed(self):
        self.run_fixtures(subject=[good()] * 6, judge=[verdict("pass")] * 6, suite=True)
        write(self.root / SUBJECT, "Greet only Ada.\n")
        result = self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass")] * 3, changed=True)
        self.assertEqual([run.id for run in result.runs], ["prompt/greeting"])
        self.assertEqual(self.run_fixtures(changed=True).runs, [])

    def test_the_full_suite_runs_at_most_once_per_weekly_window(self):
        limited = Envelope(structured_output=GOOD, num_turns=1, rate_limit_events=[
            RateLimitEvent("allowed", seven_day=Window(0.5, 1_000_000))])
        first = self.run_fixtures(subject=[limited] * 6, judge=[verdict("pass")] * 6, suite=True, now=999_000)
        self.assertEqual(len(first.runs), 2)
        again = self.run_fixtures(suite=True, now=999_500)
        self.assertEqual((again.runs, again.exit_code), ([], 2))
        self.assertIn("weekly window", self.printed)
        self.assertEqual(len(self.run_fixtures(suite=True, force=True, now=999_500).runs), 2)
        self.assertEqual(len(self.run_fixtures(suite=True, now=1_000_001).runs), 2)

    def test_without_a_reading_the_weekly_window_is_seven_days(self):
        self.run_fixtures(subject=[good()] * 6, judge=[verdict("pass")] * 6, suite=True, now=0)
        self.assertEqual(self.run_fixtures(suite=True, now=7 * 86400 - 1).exit_code, 2)
        self.assertEqual(len(self.run_fixtures(suite=True, now=7 * 86400).runs), 2)

    def test_the_turn_ceiling_skips_the_judged_samples_and_still_runs_the_free_layer(self):
        self.policy["fixtures"]["max_turns_per_suite"] = 6
        result = self.run_fixtures(subject=[good()] * 6, ids=["prompt/greeting", "prompt/farewell"])
        greeting, farewell = result.runs
        self.assertEqual(result.exit_code, 2)
        self.assertEqual((greeting.structural, greeting.judged, greeting.partial), (3, None, True))
        self.assertEqual((farewell.structural, farewell.judged, farewell.partial), (3, None, True))
        self.assertEqual(len(self.subject_calls()), 6, "the subject sessions behind the free layer go on after the ceiling")
        self.assertEqual(self.judge_calls(), [])
        self.assertIn("ceiling", self.printed)
        self.assertIsNone(self.record_of("greeting").get("last_run"), "a partial run is no outcome to measure a flake by")

    def test_a_structural_failure_after_the_ceiling_is_still_a_regression(self):
        self.policy["fixtures"]["max_turns_per_suite"] = 1
        self.passing_baseline("farewell")
        result = self.run_fixtures(subject=[good(word="bye")] * 3, ids=["prompt/farewell"])
        run = result.runs[0]
        self.assertEqual((run.structural, run.partial, run.regression), (0, False, True))
        self.assertEqual(result.exit_code, 1)

    def test_a_refused_subject_session_stops_the_suite_and_is_not_cached(self):
        refused = Envelope(rate_limit_events=[RateLimitEvent("rejected")])
        first = self.run_fixtures(subject=[refused], ids=["prompt/greeting", "prompt/farewell"])
        self.assertEqual((first.exit_code, [run.partial for run in first.runs], len(self.subject_calls())), (2, [True, True], 1))
        self.assertIn("refused", self.printed)
        second = self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass")] * 3, ids=["prompt/greeting"])
        self.assertEqual((second.exit_code, second.runs[0].structural, len(self.subject_calls())), (0, 3, 3))

    def test_a_judge_without_a_usable_verdict_is_asked_again_next_time(self):
        broken = Envelope(subtype="error_max_structured_output_retries", is_error=True)
        self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass"), broken, verdict("pass")], ids=["prompt/greeting"])
        run = self.run_fixtures(judge=[verdict("pass")], ids=["prompt/greeting"]).runs[0]
        self.assertEqual((len(self.subject_calls()), len(self.judge_calls()), run.judged), (0, 1, 3))


# --- regressions, flakes, quarantine ----------------------------------------------------------------


class ExitCodeTest(Harness):
    def test_a_fixture_passing_at_its_baseline_and_failing_now_exits_1(self):
        self.make_fixture()
        self.passing_baseline()
        result = self.run_fixtures(subject=[good(word="bye")] * 3, ids=["prompt/greeting"])
        self.assertTrue(result.runs[0].regression)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("REGRESSION", self.printed)

    def test_a_failing_fixture_with_no_passing_baseline_is_no_regression(self):
        self.make_fixture()
        result = self.run_fixtures(subject=[good(word="bye")] * 3, ids=["prompt/greeting"])
        self.assertFalse(result.runs[0].regression)
        self.assertEqual(result.exit_code, 0)

    def test_the_command_returns_the_exit_code(self):
        self.make_fixture()
        self.passing_baseline()
        with worker.use_fake() as fake:
            for _ in range(3):
                fake.script(good(word="bye"), role=ROLE)
            with redirect_stdout(StringIO()):
                code = cli.main(["fixture", "run", "prompt/greeting", "--root", str(self.root)])
        self.assertEqual(code, 1)

    def test_a_regression_stays_selected_by_changed_until_it_is_fixed(self):
        self.make_fixture()
        self.passing_baseline()
        write(self.root / SUBJECT, "Greet only Ada.\n")
        self.assertEqual(self.run_fixtures(subject=[good(word="bye")] * 3, changed=True).exit_code, 1)
        again = self.run_fixtures(changed=True)
        self.assertEqual(([run.id for run in again.runs], again.exit_code, self.calls), (["prompt/greeting"], 1, []))

    def test_a_subject_that_no_longer_renders_is_a_regression_when_the_baseline_passed(self):
        self.make_fixture()
        self.passing_baseline()
        (self.root / SUBJECT).unlink()
        result = self.run_fixtures(ids=["prompt/greeting"])
        self.assertTrue(result.runs[0].gating)
        self.assertEqual((result.exit_code, self.calls), (1, []))
        self.assertIn("REGRESSION, cannot run", self.printed)

    def test_a_fixture_json_that_no_longer_validates_is_a_regression_when_the_baseline_passed(self):
        self.make_fixture()
        self.passing_baseline()
        self.update_record(structural=[{"check": "path_looks_right", "path": "$.word"}])
        self.assertEqual(self.run_fixtures(ids=["prompt/greeting"]).exit_code, 1)

    def test_a_launch_failure_is_named_and_the_suite_goes_on(self):
        write(self.root / "prompts" / "farewell.md", "Say goodbye.\n")
        self.make_fixture("farewell", subject="prompts/farewell.md", judged=False)
        self.make_fixture("greeting", judged=False)
        self.passing_baseline("greeting")
        result = self.run_fixtures(subject=[good()] * 3, ids=["prompt/farewell", "prompt/greeting"])  # enough for the first only
        farewell, greeting = result.runs
        self.assertEqual(farewell.structural, 3)
        self.assertIn("launch failed", greeting.skipped)
        self.assertEqual((greeting.gating, result.exit_code), (True, 1))

    def test_a_subject_nothing_carries_into_the_run_is_refused(self):
        self.make_fixture()
        write(self.root / "docs" / "style.md", "Be brief.\n")
        self.update_record(subject={"path": "docs/style.md", "sha256": None, "also": []})
        run = self.run_fixtures(ids=["prompt/greeting"]).runs[0]
        self.assertIn("nothing carries", run.skipped)
        self.assertEqual(self.calls, [])

    def test_a_skill_subject_is_delivered_into_the_runs_project_and_a_change_to_it_is_a_new_run(self):
        skill = "skills/wayline-greet/SKILL.md"
        write(self.root / skill, "---\nname: wayline-greet\ndescription: Greets.\n---\n\nSay hello.\n")
        directory = self.make_fixture(judged=False, structural=[{"check": "schema_valid"}])
        write(directory / "input" / "context" / ".claude" / "skills" / "wayline-greet" / "SKILL.md", "a stale copy\n")
        self.update_record(subject={"path": skill, "sha256": None, "also": []})
        self.run_fixtures(subject=[good()] * 3, ids=["prompt/greeting"])
        delivered = Path(self.subject_calls()[0].request.cwd) / ".claude" / "skills" / "wayline-greet" / "SKILL.md"
        self.assertIn("Say hello.", delivered.read_text(encoding="utf-8"))
        write(self.root / skill, "---\nname: wayline-greet\ndescription: Greets.\n---\n\nSay goodbye.\n")
        self.run_fixtures(subject=[good()] * 3, ids=["prompt/greeting"])
        self.assertEqual(len(self.subject_calls()), 3, "the changed skill is a new cache key")
        delivered = Path(self.subject_calls()[0].request.cwd) / ".claude" / "skills" / "wayline-greet" / "SKILL.md"
        self.assertIn("Say goodbye.", delivered.read_text(encoding="utf-8"))

    def test_a_fixture_that_cannot_launch_is_skipped_and_named(self):
        self.make_fixture()
        self.update_record(input={"prompt": "input/prompt.md", "agent": None, "context_manifest": None, "input_hash": None})
        result = self.run_fixtures(ids=["prompt/greeting"])
        self.assertTrue(result.runs[0].skipped)
        self.assertEqual((result.exit_code, self.calls), (0, []))
        self.assertIn("skipped", self.printed)


class QuarantineTest(Harness):
    def setUp(self):
        super().setUp()
        self.make_fixture()
        self.passing_baseline()

    def outcome(self, passing):
        """One complete run whose judged layer passes or fails, fresh from the launcher."""
        return self.run_fixtures(subject=[good()] * 3, judge=[verdict("pass" if passing else "fail")] * 3,
                        ids=["prompt/greeting"], use_cache=False)

    def files(self):
        return {str(path.relative_to(self.root)) for path in self.root.rglob("*")}

    def test_the_second_flake_quarantines_and_stable_runs_restore_and_nothing_is_deleted(self):
        before = self.files()
        self.assertEqual(self.outcome(True).exit_code, 0)
        second = self.outcome(False)
        self.assertEqual(second.exit_code, 1, "the first flake still gates")
        self.assertTrue(second.runs[0].flake)
        quarantine = self.record_of()["quarantine"]
        self.assertEqual((quarantine["status"], len(quarantine["flakes"]), quarantine["flakes"][0]["layer"]), ("active", 1, "judged"))

        self.outcome(True)
        self.assertEqual(self.record_of()["quarantine"]["status"], "quarantined")
        fourth = self.outcome(False)
        self.assertTrue(fourth.runs[0].regression)
        self.assertTrue(fourth.runs[0].quarantined)
        self.assertEqual(fourth.exit_code, 0, "a quarantined fixture keeps reporting and no longer gates")
        self.assertIn("quarantined", self.printed)

        self.outcome(False)
        self.outcome(False)
        self.assertEqual(self.record_of()["quarantine"]["status"], "quarantined")
        seventh = self.outcome(False)
        quarantine = self.record_of()["quarantine"]
        self.assertEqual(quarantine["status"], "active", "three identical outcomes in a row restore it")
        self.assertEqual(len(quarantine["flakes"]), 3, "flakes are appended and never pruned")
        self.assertEqual(seventh.exit_code, 1, "restored, it gates again")
        self.assertLessEqual(before, self.files())

    def test_a_rewrite_restores_a_quarantined_fixture_and_resets_its_baseline(self):
        self.outcome(True)
        self.outcome(False)
        self.outcome(True)
        self.assertEqual(self.record_of()["quarantine"]["status"], "quarantined")
        record = self.record_of()
        record["structural"].append({"check": "path_count", "path": "$.greeted", "min": 1})
        self.update_record(structural=record["structural"])
        self.outcome(False)
        record = self.record_of()
        self.assertEqual(record["quarantine"]["status"], "active")
        self.assertIsNotNone(record["quarantine"]["restored_at"])
        self.assertFalse(record["baseline"]["passed"])

    def test_a_different_outcome_after_a_subject_change_is_no_flake(self):
        self.outcome(True)
        write(self.root / SUBJECT, "Greet only Ada.\n")
        result = self.outcome(False)
        self.assertFalse(result.runs[0].flake)
        self.assertEqual(self.record_of()["quarantine"]["flakes"], [])
        self.assertEqual(result.exit_code, 1)


# --- recording ------------------------------------------------------------------------------------


class RecordTest(Harness):
    def setUp(self):
        super().setUp()
        write(self.root / "roles" / ROLE / "agent.md", "---\nname: greeter\ndescription: Greets.\n---\n\nYou greet people.\n")
        self.project = self.temp / "project"
        write(self.project / "harness.json", "{}\n")
        write(self.project / "notes" / "names.txt", "ada\ngrace\n")
        write(self.project / "research" / "tickets" / "01-greet.md",
              "---\nid: 1\ntitle: Greet\ncontext_pack: [notes/names.txt]\n---\n\n## Demo\n\nGreetings.\n")
        self.schema = write(self.temp / "schema.json", json.dumps(SCHEMA))

    def journaled_session(self, session_id="sess-1", output=GOOD):
        """One session launched the way the conductor launches a ticket, and journaled the same way."""
        request = LaunchRequest(
            role=ROLE, model="sonnet", effort="low", prompt="# The task\n\n" + SUBJECT_TEXT,
            agent_json={ROLE: {"description": "Greets.", "prompt": "You greet people.", "maxTurns": 10, "permissionMode": "dontAsk"}},
            allowed_tools=["Read"], disallowed_tools=["WebFetch"], add_dirs=[str(HARNESS_ROOT), str(self.project)],
            cwd=str(self.project), env=worker.session_env(self.project, 1, 1, ["notes/"]), schema_path=str(self.schema))
        with worker.use_fake() as fake:
            fake.script(Envelope(session_id=session_id, structured_output=output, num_turns=4))
            worker.launch(request)
        Ledger(self.project).append_event("ticket_session", {"ticket": 1, "attempt": 1, "session_id": session_id, "model": "claude-sonnet-5"},
                                          ticket=1, session_id=session_id)

    def record(self, runs=0, subject=(), **options):
        options.setdefault("root", self.root)
        options.setdefault("policy", self.policy)
        with worker.use_fake() as fake:
            for envelope in subject:
                fake.script(envelope, role=ROLE)
            out = StringIO()
            try:
                with redirect_stdout(out):
                    return fixtures.record(self.project, "sess-1", options.pop("kind", "role"), options.pop("slug", "greeter-smoke"),
                                           runs=runs, **options)
            finally:
                self.calls = list(fake.calls)
                self.printed = out.getvalue()

    def test_the_input_pack_and_the_envelope_are_copied_from_the_journaled_session(self):
        self.journaled_session()
        directory = self.record()
        run = self.project / "research" / "sessions" / "1" / "1"
        self.assertEqual(directory, self.root / "fixtures" / "role" / "greeter-smoke")
        self.assertEqual((directory / "input" / "prompt.md").read_text(), (run / "prompt.md").read_text())
        self.assertEqual(json.loads((directory / "input" / "agent.json").read_text()), json.loads((run / "agent.json").read_text()))
        self.assertTrue((directory / "input" / "schema.json").is_file())
        self.assertTrue((directory / "recorded" / "result-sess-1.json").is_file())
        init = json.loads((directory / "recorded" / "trace-sess-1.jsonl").read_text().splitlines()[0])
        self.assertEqual(init, {"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-sonnet-5"},
                         "the host's tools, servers, and paths stay out of the recording")
        self.assertEqual((directory / "input" / "context" / "notes" / "names.txt").read_text(), "ada\ngrace\n")
        self.assertTrue((directory / "input" / "context" / "research" / "tickets" / "01-greet.md").is_file())

        record = json.loads((directory / "fixture.json").read_text())
        self.assertEqual(validate(record, load_schema("fixture")), [])
        self.assertEqual(record["subject"]["path"], "roles/greeter/agent.md")
        self.assertEqual(record["subject"]["sha256"], fixtures.subject_sha256(record, self.root))
        self.assertEqual(record["input"]["input_hash"], fixtures.input_hash(directory, record))
        self.assertEqual((record["origin"]["session_id"], record["origin"]["ticket"]), ("sess-1", 1))
        self.assertIsNotNone(record["origin"]["journal_ts"])
        launch = record["launch"]
        self.assertEqual((launch["role"], launch["model"], launch["effort"], launch["max_turns"]), (ROLE, "sonnet", "low", 10))
        self.assertEqual((launch["allowed_tools"], launch["disallowed_tools"]), (["Read"], ["WebFetch"]))
        self.assertEqual(launch["env"]["WAYLINE_RUN"], "{run}")
        self.assertEqual(launch["env"]["WAYLINE_PROJECT"], "{project}")
        self.assertNotIn("PATH", launch["env"])
        self.assertEqual(launch["add_dirs"], ["{harness}", "{project}"])
        self.assertIsNone(record["baseline"])

    def test_it_proposes_one_path_equals_per_scalar_and_one_path_count_per_array(self):
        self.journaled_session()
        structural = json.loads((self.record() / "fixture.json").read_text())["structural"]
        self.assertEqual(structural[0], {"check": "schema_valid"})
        for proposal in ({"check": "path_equals", "path": "$.word", "value": "hello"},
                         {"check": "path_equals", "path": "$.summary", "value": "Greeted Ada and Grace."},
                         {"check": "path_equals", "path": "$.checks.pytest", "value": "pass"},
                         {"check": "path_count", "path": "$.greeted", "min": 2, "max": 2}):
            self.assertIn(proposal, structural)
        self.assertEqual(len(structural), 5)

    def test_the_recorded_fixture_runs_and_launches_the_current_role_prompt(self):
        self.journaled_session()
        self.record()
        write(self.root / "roles" / ROLE / "agent.md", "---\nname: greeter\ndescription: Greets.\n---\n\nYou greet people warmly.\n")
        run = self.run_fixtures(subject=[good()] * 3, ids=["role/greeter-smoke"]).runs[0]
        self.assertEqual(run.structural, 3)
        agents = self.subject_calls()[0].request.agent_json
        agents = json.loads(agents) if isinstance(agents, str) else agents
        self.assertEqual(agents[ROLE]["prompt"], "You greet people warmly.")

    def test_the_baseline_is_n_runs_and_an_unstable_one_is_flagged(self):
        self.journaled_session()
        record = json.loads((self.record(runs=3, subject=[good()] * 3) / "fixture.json").read_text())
        self.assertEqual((len(self.subject_calls()), record["baseline"]["structural"]), (3, "3/3"))
        self.assertEqual((record["baseline"]["passed"], record["baseline"]["unstable"]), (True, False))

    def test_an_unstable_baseline_is_flagged(self):
        self.journaled_session()
        broken = Envelope(structured_output={"word": "hello"}, num_turns=1)
        record = json.loads((self.record(runs=3, subject=[good(), broken, good()]) / "fixture.json").read_text())
        self.assertEqual((record["baseline"]["structural"], record["baseline"]["unstable"]), ("2/3", True))
        self.assertIn("unstable", self.printed)

    def test_the_fixture_id_is_linked_into_the_change_record_and_the_skill_sidecar(self):
        self.journaled_session()
        change = write(self.temp / "change.json", json.dumps({"id": "c-1", "fixture": None}))
        record = json.loads((self.record(change_record=change) / "fixture.json").read_text())
        self.assertEqual(json.loads(change.read_text())["fixture"], "role/greeter-smoke")
        self.assertEqual(record["origin"]["change_record"], str(change))

        write(self.root / "skills" / "wayline-greet" / "SKILL.md", "---\nname: wayline-greet\ndescription: Greets.\n---\n\n" + SUBJECT_TEXT)
        write(self.root / "skills" / "wayline-greet" / "wayline.json", json.dumps({"id": "greet", "fixtures": []}))
        self.record(kind="skill", slug="greet-smoke", subject_path="skills/wayline-greet/SKILL.md")
        self.assertEqual(json.loads((self.root / "skills" / "wayline-greet" / "wayline.json").read_text())["fixtures"], ["skill/greet-smoke"])

    def test_a_session_the_journal_does_not_name_is_refused(self):
        self.journaled_session()
        with self.assertRaises(fixtures.FixtureError) as caught:
            with worker.use_fake():
                fixtures.record(self.project, "nobody", "role", "x", root=self.root, runs=0, policy=self.policy)
        self.assertIn("journal", str(caught.exception))

    def test_a_record_that_fails_leaves_nothing_behind_and_can_be_retried(self):
        self.journaled_session()
        with self.assertRaises(OSError):
            self.record(rubric=self.temp / "no-such-rubric.md")
        parent = self.root / "fixtures" / "role"
        self.assertEqual(sorted(path.name for path in parent.iterdir()) if parent.is_dir() else [], [])
        self.assertTrue((self.record() / "fixture.json").is_file())

    def test_a_subject_nothing_would_carry_is_refused_before_anything_is_written(self):
        self.journaled_session()
        write(self.root / "docs" / "style.md", "Be brief.\n")
        with self.assertRaises(fixtures.FixtureError) as caught:
            self.record(kind="prompt", slug="style", subject_path="docs/style.md")
        self.assertIn("nothing would carry", str(caught.exception))
        self.assertFalse((self.root / "fixtures" / "prompt").exists())

    def test_an_existing_fixture_is_never_overwritten(self):
        self.journaled_session()
        self.record()
        with self.assertRaises(fixtures.FixtureError):
            self.record()


# --- what ships -----------------------------------------------------------------------------------


class ShippedTest(unittest.TestCase):
    def test_every_shipped_fixture_validates(self):
        found = fixtures.discover(HARNESS_ROOT)
        self.assertTrue(found)
        for directory in found:
            with self.subTest(fixture=str(directory.relative_to(FIXTURES_DIR))):
                record = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))
                self.assertEqual(validate(record, load_schema("fixture")), [])
                self.assertEqual(record["id"], "%s/%s" % (directory.parent.name, directory.name))

    def test_the_judge_role_has_no_tools_and_may_judge(self):
        role = worker.read_role(fixtures.JUDGE_ROLE)
        self.assertEqual(role.allowed_tools, [])
        self.assertTrue(role.may_judge)
        self.assertEqual(role.output_schema, "fixture_verdict")

    def test_the_verb_is_built(self):
        self.assertIsNotNone(cli.lookup("fixture").handler)


if __name__ == "__main__":
    unittest.main()
