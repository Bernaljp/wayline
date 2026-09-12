"""The worker launcher seam (Implementation Decisions 3; Testing Decisions seam 1).

`launch` and `resume` over a `LaunchRequest`, the `claude_cli` backend against a recording
stand-in for the `claude` executable (never the network), stream parsing on the recorded streams
under `tests/streams/`, the re-validation of `structured_output`, the `fake` backend's scripting,
the hidden smoke verb, and the scan that finds the executable in one place only.
"""

import ast
import dataclasses
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.spec_table import spec_seam_fields
from tests.test_cli import run_cli
from wayline import cli, worker
from wayline.worker import Envelope, LaunchRequest, Patch

STREAMS = HARNESS_ROOT / "tests" / "streams"
SCHEMA = STREAMS / "schema.json"

# A stand-in for the `claude` executable: it replays a stream and records what it received.
# It is driven by FAKE_CLAUDE_* variables, which the launcher passes through untouched. It exits
# 143 on SIGTERM after flushing, as the real one does.
STAND_IN = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, signal, sys, time

    def term(signum, frame):
        try:
            sys.stdout.flush()
        finally:
            os._exit(143)

    signal.signal(signal.SIGTERM, term)
    stream = os.environ.get("FAKE_CLAUDE_STREAM")
    lines = open(stream).read().splitlines() if stream else []
    head = int(os.environ.get("FAKE_CLAUDE_HEAD", len(lines)))
    for line in lines[:head]:
        sys.stdout.write(line + "\\n")
    sys.stdout.flush()
    record = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "stdin": os.readlink("/proc/self/fd/0") if os.path.exists("/proc/self/fd/0") else None,
        "env": {key: value for key, value in os.environ.items()
                if key.startswith(("TICKET_", "WAYLINE_", "CLAUDE_CODE_RETRY_WATCHDOG"))},
    }
    with open(os.environ["FAKE_CLAUDE_RECORD"], "w") as handle:
        json.dump(record, handle)
    sys.stderr.write("stand-in stderr line\\n")
    time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
    for line in lines[head:]:
        sys.stdout.write(line + "\\n")
    sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
""")


def make_request(run_dir, **overrides):
    fields = dict(
        role="coder", model="sonnet", effort="low", prompt="/wayline-smoke\nDo the ticket.",
        agent_json={"coder": {"description": "a coder", "prompt": "You code.", "model": "sonnet", "effort": "low", "maxTurns": 40, "permissionMode": "dontAsk"}},
        allowed_tools=["Read", "Bash(git status*)"], disallowed_tools=["WebFetch", "WebSearch"],
        settings_path=None, add_dirs=["/harness", "/project"], cwd=str(run_dir),
        env={"TICKET_TOUCHES": "src:tests", "TICKET_ACCEPTANCE_FILE": str(run_dir / "acceptance.json"),
             "WAYLINE_PROJECT": "/project", "WAYLINE_TICKET": "3", "WAYLINE_RUN": str(run_dir)},
        schema_path=str(SCHEMA), max_minutes=30,
    )
    fields.update(overrides)
    return LaunchRequest(**fields)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True, text=True, check=True).stdout


class InterfaceTest(unittest.TestCase):
    def test_launch_request_and_envelope_carry_the_fields_of_decision_3(self):
        request_fields, envelope_fields = spec_seam_fields(SPEC_PATH)
        self.assertEqual([field.name for field in dataclasses.fields(LaunchRequest)], request_fields)
        names = [field.name for field in dataclasses.fields(Envelope)]
        self.assertEqual(names[:len(envelope_fields)], envelope_fields)
        self.assertEqual(names[len(envelope_fields):], ["errors", "result_text"])

    def test_run_dir_is_the_wayline_run_variable(self):
        request = make_request(Path("/tmp/x/research/sessions/3/1"))
        self.assertEqual(request.run_dir, Path("/tmp/x/research/sessions/3/1"))
        with self.assertRaises(worker.LaunchError):
            make_request(Path("/tmp/x"), env={}).run_dir

    def test_session_dir_and_env_follow_the_launch_line(self):
        run = worker.session_dir("/proj", 3, 2)
        self.assertEqual(run, Path("/proj/research/sessions/3/2"))
        env = worker.session_env("/proj", 3, 2, ["src/", "tests/test_x.py"])
        self.assertEqual(env, {
            "TICKET_TOUCHES": "src/:tests/test_x.py",
            "TICKET_ACCEPTANCE_FILE": "/proj/research/sessions/3/2/acceptance.json",
            "WAYLINE_PROJECT": "/proj", "WAYLINE_TICKET": "3", "WAYLINE_RUN": "/proj/research/sessions/3/2",
        })
        self.assertEqual(worker.session_env("/proj", 3, 2, "src/")["TICKET_TOUCHES"], "src/")

    def test_backend_names(self):
        with mock.patch.dict(os.environ, {"WAYLINE_LAUNCHER": "claude_cli"}):
            self.assertEqual(worker.backend().name, "claude_cli")
        with mock.patch.dict(os.environ, {"WAYLINE_LAUNCHER": "fake"}):
            self.assertEqual(worker.backend().name, "fake")
        with mock.patch.dict(os.environ, {"WAYLINE_LAUNCHER": "sdk"}):
            with self.assertRaises(worker.LaunchError):
                worker.backend()
        with mock.patch.dict(os.environ):
            os.environ.pop("WAYLINE_LAUNCHER", None)
            self.assertEqual(worker.backend().name, "claude_cli")

    def test_aliases_agree_with_the_policy_schema(self):
        schema = json.loads((HARNESS_ROOT / "schemas" / "policy.json").read_text(encoding="utf-8"))
        text = json.dumps(schema)
        self.assertIn(json.dumps(list(worker.MODEL_ALIASES)), text)
        self.assertIn(json.dumps(list(worker.EFFORTS)), text)

    def test_an_envelope_built_by_hand_is_normalized(self):
        envelope = Envelope(rate_limit_events=[{"status": "allowed", "five_hour": {"utilization": 0.2, "resets_at": 5}}], errors=None, stream_path="/x/stream.jsonl")
        self.assertEqual(envelope.last_windows(), (0.2, None))
        self.assertEqual(envelope.errors, [])
        self.assertEqual(envelope.stream_path, Path("/x/stream.jsonl"))
        self.assertEqual(json.loads(json.dumps(envelope.as_dict()))["rate_limit_events"][0]["five_hour"]["resets_at"], 5)
        for bad in [dict(structured_output=["a"]), dict(errors="three tries"), dict(permission_denials="x"), dict(usage=[]),
                    dict(rate_limit_events=[{"status": "rejected", "resetsAt": 1}]), dict(rate_limit_events=[{"five_hour": {"utilisation": 1}}])]:
            with self.subTest(bad=bad):
                with self.assertRaises(worker.LaunchError):
                    Envelope(**bad)
        with self.assertRaises(worker.LaunchError):
            Envelope.from_dict({"structured_output": {}, "typo_field": 1})


class ArgvTest(unittest.TestCase):
    def test_launch_argv_is_the_launch_line_of_decision_3(self):
        run = Path("/proj/research/sessions/3/1")
        request = make_request(run)
        argv = worker.build_argv(request, run)
        self.assertEqual(argv, [
            "claude", "-p", "/wayline-smoke\nDo the ticket.",
            "--agents", json.dumps(request.agent_json), "--agent", "coder",
            "--model", "sonnet", "--effort", "low",
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--allowedTools", "Read", "Bash(git status*)",
            "--disallowedTools", "WebFetch", "WebSearch",
            "--settings", "/proj/research/sessions/3/1/settings.json",
            "--add-dir", "/harness", "--add-dir", "/project",
            "--output-format", "stream-json", "--verbose",
            "--json-schema", SCHEMA.read_text(encoding="utf-8"),
            "--fallback-model", "sonnet",
        ])

    def test_resume_argv_repasses_every_flag_and_adds_resume(self):
        run = Path("/proj/research/sessions/3/1")
        request = make_request(run)
        launch = worker.build_argv(request, run)
        resume = worker.build_argv(request, run / "resume-1", session_id="83508b6e", message="you ran out of time")
        self.assertEqual(resume[:5], ["claude", "-p", "you ran out of time", "--resume", "83508b6e"])
        expected_tail = [arg if arg != "/proj/research/sessions/3/1/settings.json" else "/proj/research/sessions/3/1/resume-1/settings.json" for arg in launch[3:]]
        self.assertEqual(resume[5:], expected_tail)
        for flag in ["--agents", "--settings", "--permission-mode", "--permission-prompts", "--allowedTools",
                     "--disallowedTools", "--add-dir", "--fallback-model", "--output-format", "--json-schema"]:
            self.assertIn(flag, resume)
        with self.assertRaises(worker.LaunchError):
            worker.build_argv(request, run, session_id="83508b6e", message="  ")

    def test_empty_tool_lists_and_no_schema_drop_their_flags(self):
        run = Path("/r")
        request = make_request(run, allowed_tools=[], disallowed_tools=[], schema_path=None)
        argv = worker.build_argv(request, run)
        for flag in ["--allowedTools", "--disallowedTools", "--json-schema"]:
            self.assertNotIn(flag, argv)

    def test_a_string_agent_json_is_passed_verbatim(self):
        run = Path("/r")
        text = '{"coder": {"description": "d", "prompt": "p"}}'
        argv = worker.build_argv(make_request(run, agent_json=text), run)
        self.assertEqual(argv[argv.index("--agents") + 1], text)

    def test_the_spelled_line_names_the_session_files_by_absolute_path(self):
        run = Path("/proj/research/sessions/3/1")
        spelled = worker.spelled_argv(worker.build_argv(make_request(run), run), run)
        self.assertEqual(spelled[:3], ["claude", "-p", "$(cat /proj/research/sessions/3/1/prompt.md)"])
        self.assertEqual(spelled[spelled.index("--agents") + 1], "$(cat /proj/research/sessions/3/1/agent.json)")
        self.assertEqual(spelled[spelled.index("--json-schema") + 1], "$(cat /proj/research/sessions/3/1/schema.json)")
        self.assertEqual(len(spelled), len(worker.build_argv(make_request(run), run)))

    def test_the_request_is_checked_before_anything_starts(self):
        run = Path("/r")
        agent = {"coder": {"description": "d", "prompt": "p"}}
        for bad in [dict(prompt=""), dict(role="verifier"), dict(model=""), dict(model="sonet"), dict(effort="ultracode"),
                    dict(agent_json="not json"), dict(agent_json={"coder": {**agent["coder"], "tools": ["Bash"]}}),
                    dict(agent_json={"coder": {**agent["coder"], "skills": ["x"]}}), dict(allowed_tools="Read"),
                    dict(add_dirs="/harness"), dict(max_minutes=True), dict(max_minutes=0), dict(env=[])]:
            with self.subTest(bad=bad):
                with self.assertRaises(worker.LaunchError):
                    worker.build_argv(make_request(run, **bad), run)

    def test_a_schema_outside_the_validator_subset_is_refused_before_a_session_is_spent(self):
        with tempfile.TemporaryDirectory() as temp:
            schema = Path(temp) / "schema.json"
            schema.write_text('{"type": "object", "properties": {"x": {"type": "string", "minLength": 1}}}', encoding="utf-8")
            with self.assertRaises(worker.LaunchError) as caught:
                worker.build_argv(make_request(Path("/r"), schema_path=str(schema)), Path("/r"))
            self.assertIn("minLength", str(caught.exception))
            schema.write_text("{not json", encoding="utf-8")
            with self.assertRaises(worker.LaunchError):
                worker.build_argv(make_request(Path("/r"), schema_path=str(schema)), Path("/r"))


class StreamParsingTest(unittest.TestCase):
    def stream(self, name):
        return STREAMS / name

    def test_success_stream_of_note_01_launch_2(self):
        parsed = worker.parse_stream(self.stream("note01-launch2-success.jsonl"))
        self.assertEqual(parsed.session_id, "83508b6e-7d57-40cc-9243-83174fde6613")
        self.assertEqual(parsed.model, "claude-sonnet-5")
        self.assertEqual(parsed.result["subtype"], "success")
        self.assertEqual(len(parsed.rate_limit_events), 2)
        first, last = parsed.rate_limit_events
        self.assertEqual((first.status, first.resets_at, first.rate_limit_type), ("allowed", 1789153800, "five_hour"))
        self.assertEqual((first.five_hour.utilization, first.five_hour.resets_at), (0.14, 1789153800))
        self.assertEqual((first.seven_day.utilization, first.seven_day.resets_at), (0.21, 1789524000))
        self.assertEqual(last.five_hour.utilization, 0.15)
        self.assertEqual(parsed.torn_lines, 0)

    def test_envelope_of_a_valid_result(self):
        envelope = worker.read_envelope(self.stream("note01-launch2-success.jsonl"), SCHEMA, exit_code=0)
        self.assertEqual(envelope.session_id, "83508b6e-7d57-40cc-9243-83174fde6613")
        self.assertEqual(envelope.model, "claude-sonnet-5")
        self.assertEqual(envelope.structured_output["skill_token"], "UNKNOWN")
        self.assertTrue(envelope.valid)
        self.assertFalse(envelope.is_error)
        self.assertEqual(envelope.subtype, "success")
        self.assertEqual((envelope.num_turns, envelope.duration_ms, envelope.duration_api_ms), (3, 5569, 6510))
        self.assertEqual(envelope.usage["output_tokens"], 196)
        self.assertIn("claude-sonnet-5", envelope.model_usage)
        self.assertEqual(envelope.permission_denials, [])
        self.assertIsNone(envelope.api_error_status)
        self.assertEqual(envelope.exit_code, 0)
        self.assertEqual(envelope.stream_path, self.stream("note01-launch2-success.jsonl"))
        self.assertEqual(envelope.errors, [])
        self.assertTrue(envelope.result_text.startswith("{"))
        self.assertEqual(envelope.last_windows(), (0.15, 0.21))

    def test_success_without_structured_output_is_invalid(self):
        envelope = worker.read_envelope(self.stream("note01-launch1-success-without-structured-output.jsonl"), SCHEMA, exit_code=0)
        self.assertEqual(envelope.subtype, "success")
        self.assertIsNone(envelope.structured_output)
        self.assertFalse(envelope.valid)
        self.assertTrue(envelope.is_error)
        self.assertEqual(len(envelope.errors), 1)
        self.assertIn("structured_output", envelope.errors[0])
        self.assertEqual(envelope.session_id, "66c03632-0d1d-43d9-ade2-ef09678eed88")

    def test_max_structured_output_retries_is_invalid(self):
        envelope = worker.read_envelope(self.stream("synth-max-structured-output-retries.jsonl"), SCHEMA, exit_code=1)
        self.assertEqual(envelope.subtype, "error_max_structured_output_retries")
        self.assertIsNone(envelope.structured_output)
        self.assertTrue(envelope.is_error)
        self.assertIn("error_max_structured_output_retries", " ".join(envelope.errors))
        self.assertIn("report is a required property", " ".join(envelope.errors))
        self.assertEqual(envelope.num_turns, 6)

    def test_the_resume_stream_of_note_01_launch_3(self):
        envelope = worker.read_envelope(self.stream("note01-launch3-resume.jsonl"), SCHEMA, exit_code=0)
        self.assertTrue(envelope.valid)
        self.assertEqual(envelope.structured_output["skill_token"], "SKILL-TOKEN-7F3A")
        self.assertEqual(envelope.last_windows(), (0.16, 0.22))

    def test_a_plain_session_without_schema_keeps_the_result_text(self):
        envelope = worker.read_envelope(self.stream("note02-launch2-plain.jsonl"), None, exit_code=0)
        self.assertIsNone(envelope.structured_output)
        self.assertFalse(envelope.is_error)
        self.assertEqual(envelope.errors, [])
        self.assertEqual(envelope.result_text, "ok")
        self.assertEqual(envelope.last_windows(), (0.14, 0.21))

    def test_missing_unified_windows_degrades_to_status(self):
        parsed = worker.parse_stream(self.stream("synth-no-unified-windows.jsonl"))
        (event,) = parsed.rate_limit_events
        self.assertEqual(event.status, "allowed_warning")
        self.assertEqual(event.resets_at, 1789153800)
        self.assertIsNone(event.five_hour)
        self.assertIsNone(event.seven_day)
        envelope = worker.read_envelope(self.stream("synth-no-unified-windows.jsonl"), SCHEMA, exit_code=0)
        self.assertEqual(envelope.last_windows(), (None, None))
        self.assertTrue(envelope.valid)
        self.assertIn("unknown", worker.describe_windows(envelope)[1])

    def test_a_rejected_window_is_an_error_with_the_api_status(self):
        envelope = worker.read_envelope(self.stream("synth-rejected-429.jsonl"), SCHEMA, exit_code=1)
        self.assertTrue(envelope.is_error)
        self.assertEqual(envelope.api_error_status, 429)
        self.assertEqual(envelope.rate_limit_events[-1].status, "rejected")
        self.assertEqual(envelope.last_windows(), (1.0, 0.61))
        self.assertIn("session limit", " ".join(envelope.errors))

    def test_a_killed_stream_has_a_session_and_no_result(self):
        envelope = worker.read_envelope(self.stream("synth-killed.jsonl"), SCHEMA, exit_code=143)
        self.assertEqual(envelope.session_id, "0a0a0a0a-0000-4000-8000-000000000071")
        self.assertEqual(envelope.model, "claude-opus-5")
        self.assertIsNone(envelope.subtype)
        self.assertIsNone(envelope.structured_output)
        self.assertTrue(envelope.is_error)
        self.assertEqual(envelope.exit_code, 143)
        self.assertIn("no result", " ".join(envelope.errors))
        self.assertEqual(envelope.last_windows(), (0.31, 0.40))

    def test_a_torn_tail_is_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stream.jsonl"
            lines = (STREAMS / "synth-killed.jsonl").read_text(encoding="utf-8").splitlines()[:2]
            path.write_text("\n".join(lines) + '\n{"type":"result","subtype":"success","is_error":false,"duration_ms":41', encoding="utf-8")
            with self.assertLogs("wayline.worker", "WARNING"):
                parsed = worker.parse_stream(path)
            self.assertEqual(parsed.torn_lines, 1)
            self.assertIsNone(parsed.result)
            self.assertEqual(parsed.session_id, "0a0a0a0a-0000-4000-8000-000000000071")
            self.assertEqual(len(parsed.rate_limit_events), 1)

    def test_a_missing_stream_is_an_empty_parse(self):
        parsed = worker.parse_stream(Path("/nonexistent/stream.jsonl"))
        self.assertIsNone(parsed.session_id)
        self.assertIsNone(parsed.result)
        envelope = worker.read_envelope(Path("/nonexistent/stream.jsonl"), SCHEMA, exit_code=1)
        self.assertTrue(envelope.is_error)

    def test_structured_output_is_revalidated_in_code(self):
        envelope = worker.read_envelope(self.stream("synth-invalid-structured-output.jsonl"), SCHEMA, exit_code=0)
        self.assertEqual(envelope.subtype, "success")
        self.assertIsNone(envelope.structured_output)
        self.assertTrue(envelope.is_error)
        joined = " ".join(envelope.errors)
        self.assertIn("skill_token", joined)
        self.assertIn("extra", joined)
        self.assertEqual(envelope.permission_denials[0]["tool_name"], "Write")

    def test_a_structured_output_that_is_not_an_object_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stream.jsonl"
            lines = (STREAMS / "synth-invalid-structured-output.jsonl").read_text(encoding="utf-8").splitlines()
            result = json.loads(lines[1])
            for candidate in [["not", "an", "object"], "just a string", 3]:
                result["structured_output"] = candidate
                path.write_text(lines[0] + "\n" + json.dumps(result) + "\n", encoding="utf-8")
                envelope = worker.read_envelope(path, SCHEMA, exit_code=0)
                self.assertFalse(envelope.valid, candidate)
                self.assertIn("not an object", " ".join(envelope.errors))

    def test_a_schema_outside_the_subset_is_a_launcher_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            schema = Path(temp) / "schema.json"
            schema.write_text('{"type": "object", "minProperties": 1}', encoding="utf-8")
            with self.assertRaises(worker.LaunchError):
                worker.read_envelope(self.stream("note01-launch2-success.jsonl"), schema, exit_code=0)

    def test_envelope_as_dict_is_json(self):
        envelope = worker.read_envelope(self.stream("note01-launch2-success.jsonl"), SCHEMA, exit_code=0)
        text = json.dumps(envelope.as_dict())
        loaded = json.loads(text)
        self.assertEqual(loaded["session_id"], envelope.session_id)
        self.assertEqual(loaded["rate_limit_events"][0]["five_hour"]["utilization"], 0.14)
        self.assertEqual(loaded["stream_path"], str(envelope.stream_path))
        self.assertEqual(Envelope.from_dict(loaded).last_windows(), envelope.last_windows())


class StandInMixin:
    """A temporary directory with the stand-in executable on WAYLINE_CLAUDE and a run directory."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stand_in = self.root / "claude-stand-in"
        self.stand_in.write_text(STAND_IN, encoding="utf-8")
        self.stand_in.chmod(self.stand_in.stat().st_mode | stat.S_IXUSR)
        self.record = self.root / "record.json"
        self.run = self.root / "project" / "research" / "sessions" / "3" / "1"
        self.cwd = self.root / "worktree"
        self.cwd.mkdir()
        patched = mock.patch.dict(os.environ, {
            "WAYLINE_CLAUDE": str(self.stand_in),
            "FAKE_CLAUDE_RECORD": str(self.record),
            "FAKE_CLAUDE_STREAM": str(STREAMS / "note01-launch2-success.jsonl"),
            "CLAUDE_CODE_RETRY_WATCHDOG": "1",
        })
        patched.start()
        self.addCleanup(patched.stop)
        for key in ["WAYLINE_LAUNCHER", "WAYLINE_FAKE_SCRIPT", "FAKE_CLAUDE_SLEEP", "FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_HEAD"]:
            os.environ.pop(key, None)

    def request(self, **overrides):
        return make_request(self.run, **{"cwd": str(self.cwd), **overrides})

    def recorded(self):
        return json.loads(self.record.read_text(encoding="utf-8"))


class ClaudeCliTest(StandInMixin, unittest.TestCase):
    def test_launch_runs_the_launch_line_and_writes_the_session_directory(self):
        request = self.request()
        started = []
        envelope = worker.launch(request, on_start=started.append)
        record = self.recorded()
        self.assertEqual(record["argv"], worker.build_argv(request, self.run)[1:])
        self.assertEqual(record["cwd"], str(self.cwd))
        self.assertEqual(record["stdin"], "/dev/null")
        seen = {key: value for key, value in record["env"].items() if key in request.env}
        self.assertEqual(seen, request.env)  # TICKET_* and WAYLINE_* exported
        self.assertNotIn("CLAUDE_CODE_RETRY_WATCHDOG", record["env"])  # the watchdog unset although the parent has it
        for name in ["prompt.md", "agent.json", "settings.json", "env.json", "stream.jsonl", "stderr.txt", "result.json", "schema.json", "pid"]:
            self.assertTrue((self.run / name).exists(), name)
        self.assertEqual(sorted(path.name for path in self.run.iterdir() if path.name.endswith(".tmp")), [])
        self.assertEqual((self.run / "prompt.md").read_text(encoding="utf-8"), request.prompt + "\n")
        self.assertEqual(json.loads((self.run / "agent.json").read_text(encoding="utf-8")), request.agent_json)
        self.assertEqual(json.loads((self.run / "settings.json").read_text(encoding="utf-8")), {})
        self.assertEqual((self.run / "stderr.txt").read_text(encoding="utf-8"), "stand-in stderr line\n")
        self.assertEqual(json.loads((self.run / "result.json").read_text(encoding="utf-8"))["subtype"], "success")
        self.assertEqual((self.run / "schema.json").read_text(encoding="utf-8"), SCHEMA.read_text(encoding="utf-8"))
        recorded_env = json.loads((self.run / "env.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded_env["env"], request.env)
        self.assertEqual(recorded_env["command"][:3], ["claude", "-p", "$(cat %s)" % (self.run / "prompt.md")])
        self.assertIn("$(cat %s)" % (self.run / "agent.json"), recorded_env["command"])
        self.assertIn("$(cat %s)" % (self.run / "schema.json"), recorded_env["command"])
        self.assertEqual(recorded_env["stdin"], "/dev/null")
        self.assertEqual(recorded_env["executable"], str(self.stand_in))
        self.assertRegex(recorded_env["started_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].pid, int((self.run / "pid").read_text(encoding="utf-8")))
        self.assertEqual(started[0].stream_path, self.run / "stream.jsonl")
        self.assertTrue(envelope.valid)
        self.assertEqual(envelope.exit_code, 0)
        self.assertEqual(envelope.stream_path, self.run / "stream.jsonl")
        self.assertEqual(envelope.session_id, "83508b6e-7d57-40cc-9243-83174fde6613")
        self.assertEqual(envelope.last_windows(), (0.15, 0.21))

    def test_settings_path_is_copied_into_the_session(self):
        source = self.root / "worker-settings.json"
        source.write_text('{"permissions": {"deny": ["Bash(git push *)"]}}', encoding="utf-8")
        worker.launch(self.request(settings_path=str(source)))
        self.assertEqual(json.loads((self.run / "settings.json").read_text(encoding="utf-8")), {"permissions": {"deny": ["Bash(git push *)"]}})
        self.assertIn(str(self.run / "settings.json"), self.recorded()["argv"])

    def test_resume_passes_resume_and_writes_beside_the_launch(self):
        request = self.request()
        worker.launch(request)
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "note01-launch3-resume.jsonl")
        envelope = worker.resume(request, "83508b6e-7d57-40cc-9243-83174fde6613", "your result was rejected; retry")
        argv = self.recorded()["argv"]
        self.assertEqual(argv[:4], ["-p", "your result was rejected; retry", "--resume", "83508b6e-7d57-40cc-9243-83174fde6613"])
        self.assertIn(str(self.run / "resume-1" / "settings.json"), argv)
        for name in ["prompt.md", "agent.json", "settings.json", "env.json", "stream.jsonl", "stderr.txt", "result.json", "pid"]:
            self.assertTrue((self.run / "resume-1" / name).exists(), name)
        self.assertEqual((self.run / "resume-1" / "prompt.md").read_text(encoding="utf-8"), "your result was rejected; retry\n")
        self.assertTrue((self.run / "stream.jsonl").exists())  # the launch stream survives
        self.assertEqual(envelope.structured_output["skill_token"], "SKILL-TOKEN-7F3A")
        self.assertEqual(envelope.stream_path, self.run / "resume-1" / "stream.jsonl")
        worker.resume(request, "83508b6e-7d57-40cc-9243-83174fde6613", "again")
        self.assertTrue((self.run / "resume-2" / "stream.jsonl").exists())

    def test_a_timeout_sends_sigterm_and_keeps_the_session_id(self):
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "synth-killed.jsonl")
        os.environ["FAKE_CLAUDE_HEAD"] = "2"
        os.environ["FAKE_CLAUDE_SLEEP"] = "30"
        envelope = worker.launch(self.request(max_minutes=0.01))
        self.assertEqual(envelope.exit_code, 143)
        self.assertTrue(envelope.is_error)
        self.assertIsNone(envelope.subtype)
        self.assertEqual(envelope.session_id, "0a0a0a0a-0000-4000-8000-000000000071")
        self.assertIn("timeout", " ".join(envelope.errors))
        self.assertFalse((self.run / "result.json").exists())

    def test_a_relaunch_into_a_used_directory_removes_the_stale_result(self):
        worker.launch(self.request())
        self.assertTrue((self.run / "result.json").exists())
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "synth-killed.jsonl")
        envelope = worker.launch(self.request(prompt="second attempt"))
        self.assertFalse(envelope.valid)
        self.assertFalse((self.run / "result.json").exists())
        self.assertEqual((self.run / "prompt.md").read_text(encoding="utf-8"), "second attempt\n")

    def test_a_failed_start_is_an_error_envelope_with_the_exit_code(self):
        os.environ["FAKE_CLAUDE_STREAM"] = ""
        os.environ["FAKE_CLAUDE_EXIT"] = "1"
        envelope = worker.launch(self.request())
        self.assertEqual(envelope.exit_code, 1)
        self.assertTrue(envelope.is_error)
        self.assertIsNone(envelope.session_id)
        self.assertIsNone(envelope.subtype)
        self.assertEqual((self.run / "stderr.txt").read_text(encoding="utf-8"), "stand-in stderr line\n")

    def test_a_missing_executable_is_refused_before_anything_is_written(self):
        os.environ["WAYLINE_CLAUDE"] = str(self.root / "no-such-claude")
        with self.assertRaises(worker.LaunchError):
            worker.launch(self.request())
        self.assertFalse(self.run.exists())

    def test_a_relative_executable_override_works_from_another_cwd(self):
        os.environ["WAYLINE_CLAUDE"] = os.path.relpath(self.stand_in)
        envelope = worker.launch(self.request())
        self.assertTrue(envelope.valid)
        self.assertEqual(json.loads((self.run / "env.json").read_text(encoding="utf-8"))["executable"], str(self.stand_in))

    def test_missing_settings_or_schema_files_are_refused_before_anything_is_written(self):
        with self.assertRaises(worker.LaunchError):
            worker.launch(self.request(settings_path=str(self.root / "absent-settings.json")))
        with self.assertRaises(worker.LaunchError):
            worker.launch(self.request(schema_path=str(self.root / "absent-schema.json")))
        with self.assertRaises(worker.LaunchError):
            worker.launch(self.request(cwd=str(self.root / "absent-cwd")))
        self.assertFalse(self.run.exists())

    def test_a_failing_on_start_does_not_leave_the_worker_running(self):
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "synth-killed.jsonl")
        os.environ["FAKE_CLAUDE_HEAD"] = "2"
        os.environ["FAKE_CLAUDE_SLEEP"] = "30"
        pids = []

        def explode(started):
            pids.append(started.pid)
            raise RuntimeError("the journal is gone")

        with self.assertRaises(RuntimeError):
            worker.launch(self.request(), on_start=explode)
        self.assertEqual(len(pids), 1)
        self.assertFalse(worker.pid_alive(pids[0]))

    def test_pid_alive_asks_the_kernel(self):
        self.assertTrue(worker.pid_alive(os.getpid()))
        probe = subprocess.Popen([sys.executable, "-c", "pass"])
        probe.wait()
        self.assertFalse(worker.pid_alive(probe.pid))

    def test_envelope_from_a_stream_another_process_wrote(self):
        request = self.request()
        worker.launch(request)
        envelope = worker.read_envelope(self.run / "stream.jsonl", request.schema_path, exit_code=None)
        self.assertTrue(envelope.valid)
        self.assertIsNone(envelope.exit_code)


class FakeBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "research" / "sessions" / "3" / "1"
        self.repo = self.make_repo("worktree")

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "seed")
        return repo

    def request(self, **overrides):
        return make_request(self.run, **{"cwd": str(self.repo), **overrides})

    def test_scripted_envelopes_return_in_order_and_then_run_out(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "one"}))
            fake.script(Envelope(structured_output={"skill_token": "B", "report": "two"}, num_turns=7))
            first = worker.launch(self.request())
            second = worker.launch(self.request())
            self.assertEqual(first.structured_output["report"], "one")
            self.assertEqual(second.structured_output["report"], "two")
            self.assertEqual(second.num_turns, 7)
            self.assertTrue(first.valid and second.valid)
            self.assertFalse(first.is_error)
            self.assertEqual(first.subtype, "success")
            self.assertEqual(first.exit_code, 0)
            self.assertTrue(first.session_id and first.session_id != second.session_id)
            self.assertEqual(first.model, "claude-sonnet-5")
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(fake.calls[0].kind, "launch")
            self.assertEqual(fake.calls[0].request.role, "coder")
            with self.assertRaises(worker.LaunchError):
                worker.launch(self.request())

    def test_selected_by_the_environment_variable(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}))
            self.assertEqual(os.environ["WAYLINE_LAUNCHER"], "fake")
            self.assertEqual(worker.backend(), fake)
            self.assertTrue(worker.launch(self.request()).valid)

    def test_the_fake_writes_the_session_files_and_a_stream_the_parser_reads(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(
                structured_output={"skill_token": "A", "report": "r"},
                rate_limit_events=[worker.RateLimitEvent("allowed", 1789153800, "five_hour", worker.Window(0.5, 1789153800), worker.Window(0.7, 1789524000))],
            ))
            request = self.request()
            seen = []
            envelope = worker.launch(request, on_start=lambda started: seen.append(worker.parse_stream(started.stream_path).session_id))
            for name in ["prompt.md", "agent.json", "settings.json", "env.json", "stream.jsonl", "stderr.txt", "result.json", "pid"]:
                self.assertTrue((self.run / name).exists(), name)
            self.assertEqual((self.run / "prompt.md").read_text(encoding="utf-8"), request.prompt + "\n")
            self.assertEqual(envelope.stream_path, self.run / "stream.jsonl")
            self.assertEqual(seen, [envelope.session_id])  # the init line is visible while the fake worker runs
            again = worker.read_envelope(self.run / "stream.jsonl", request.schema_path, exit_code=0)
            self.assertEqual(again.session_id, envelope.session_id)
            self.assertEqual(again.structured_output, envelope.structured_output)
            self.assertEqual(again.last_windows(), (0.5, 0.7))
            self.assertEqual(envelope.last_windows(), (0.5, 0.7))

    def test_a_scripted_invalid_output_is_reported_invalid(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": 7}))
            fake.script(Envelope(subtype="success"))
            fake.script(Envelope(subtype="error_max_structured_output_retries", errors=["three tries"]))
            fake.script(Envelope(api_error_status=429, is_error=True, subtype="error_during_execution",
                                 rate_limit_events=[worker.RateLimitEvent("rejected", 1789153800, "five_hour", worker.Window(1.0, 1789153800), None)]))
            bad_shape = worker.launch(self.request())
            self.assertIsNone(bad_shape.structured_output)
            self.assertTrue(bad_shape.is_error)
            self.assertIn("report", " ".join(bad_shape.errors))
            missing = worker.launch(self.request())
            self.assertTrue(missing.is_error and missing.subtype == "success" and not missing.valid)
            retries = worker.launch(self.request())
            self.assertIn("three tries", retries.errors)
            self.assertFalse(retries.valid)
            rejected = worker.launch(self.request())
            self.assertEqual(rejected.api_error_status, 429)
            self.assertEqual(rejected.rate_limit_events[0].status, "rejected")
            self.assertEqual(rejected.exit_code, 1)

    def test_a_dead_worker_carries_the_scripted_errors_like_a_timeout(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(errors=["timeout: no result within 30 minute(s); SIGTERM sent"]), died=True)
            envelope = worker.launch(self.request())
            self.assertEqual(envelope.exit_code, 143)
            self.assertIsNone(envelope.subtype)
            self.assertTrue(envelope.session_id)
            self.assertEqual(envelope.errors[0], "timeout: no result within 30 minute(s); SIGTERM sent")
            self.assertIn("no result", envelope.errors[1])
            self.assertFalse((self.run / "result.json").exists())

    def test_a_patch_is_written_and_committed_before_returning(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}),
                        patch=Patch({"src/answer.py": "ANSWER = 42\n", "README.md": "hello\nworld\n"}, message="ticket 3: the answer"))
            worker.launch(self.request())
            self.assertEqual((self.repo / "src" / "answer.py").read_text(encoding="utf-8"), "ANSWER = 42\n")
            self.assertEqual(git(self.repo, "status", "--porcelain"), "")
            self.assertEqual(git(self.repo, "log", "-1", "--format=%s").strip(), "ticket 3: the answer")
            self.assertEqual(git(self.repo, "rev-list", "--count", "HEAD").strip(), "2")

    def test_a_patch_stages_only_its_own_files_and_skips_an_empty_commit(self):
        (self.repo / "stray.txt").write_text("left behind\n", encoding="utf-8")
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}), patch=Patch({"a.txt": "hello\n"}, message="first"))
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}), patch=Patch({"a.txt": "hello\n"}, message="same again"))
            worker.launch(self.request())
            self.assertIn("stray.txt", git(self.repo, "status", "--porcelain"))
            self.assertNotIn("stray.txt", git(self.repo, "show", "--stat", "--format=", "HEAD"))
            worker.launch(self.request())
            self.assertEqual(git(self.repo, "log", "-1", "--format=%s").strip(), "first")
            self.assertEqual(git(self.repo, "rev-list", "--count", "HEAD").strip(), "2")

    def test_an_uncommitted_patch_leaves_the_worktree_dirty(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}),
                        patch=Patch({"notes.txt": "draft\n"}, commit=False))
            worker.launch(self.request())
            self.assertIn("notes.txt", git(self.repo, "status", "--porcelain"))

    def test_resume_is_scripted_the_same_way(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(subtype="success"))
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "fixed"}))
            request = self.request()
            first = worker.launch(request)
            second = worker.resume(request, first.session_id, "your result was rejected")
            self.assertEqual(second.session_id, first.session_id)
            self.assertTrue(second.valid)
            self.assertEqual(fake.calls[1].kind, "resume")
            self.assertEqual(fake.calls[1].message, "your result was rejected")
            self.assertTrue((self.run / "resume-1" / "stream.jsonl").exists())
            self.assertEqual(second.stream_path, self.run / "resume-1" / "stream.jsonl")

    def test_a_refused_call_does_not_consume_a_scripted_envelope(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "one"}))
            with self.assertRaises(worker.LaunchError):
                worker.resume(self.request(), "sid", "")
            with self.assertRaises(worker.LaunchError):
                worker.launch(self.request(schema_path=str(self.root / "absent.json")))
            with self.assertRaises(worker.LaunchError):
                worker.launch(self.request(cwd=str(self.root / "absent")))
            self.assertEqual(fake.calls, [])
            self.assertEqual(worker.launch(self.request()).structured_output["report"], "one")

    def test_entries_can_be_keyed_by_ticket_and_role(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "for four"}), ticket=4)
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "for three"}), ticket="3")
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "verifier"}), role="verifier")
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "anyone"}))
            three = worker.launch(self.request())
            self.assertEqual(three.structured_output["report"], "for three")
            five = self.request(env={**self.request().env, "WAYLINE_TICKET": "5"})
            self.assertEqual(worker.launch(five).structured_output["report"], "anyone")  # the unkeyed entry, not ticket 4's
            with self.assertRaises(worker.LaunchError):
                worker.launch(five)  # only ticket 4's and the verifier's entries are left
            verifier = self.request(role="verifier", agent_json={"verifier": {"description": "v", "prompt": "p"}})
            self.assertEqual(worker.launch(verifier).structured_output["report"], "verifier")
            self.assertEqual(worker.launch(self.request(env={**self.request().env, "WAYLINE_TICKET": "4"})).structured_output["report"], "for four")

    def test_parallel_launches_keep_their_own_envelopes_and_patches(self):
        other = self.make_repo("worktree-4")
        run4 = self.root / "research" / "sessions" / "4" / "1"
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "three"}), patch=Patch({"who.txt": "three\n"}, commit=False), ticket=3)
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "four"}), patch=Patch({"who.txt": "four\n"}, commit=False), ticket=4)
            requests = {
                "3": self.request(),
                "4": make_request(run4, cwd=str(other), env={"WAYLINE_TICKET": "4", "WAYLINE_RUN": str(run4)}),
            }
            results = {}
            threads = [threading.Thread(target=lambda key: results.__setitem__(key, worker.launch(requests[key])), args=(key,)) for key in ("4", "3")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(results["3"].structured_output["report"], "three")
            self.assertEqual(results["4"].structured_output["report"], "four")
            self.assertEqual((self.repo / "who.txt").read_text(encoding="utf-8"), "three\n")
            self.assertEqual((other / "who.txt").read_text(encoding="utf-8"), "four\n")

    def test_pid_alive_simulation(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}), alive=True)
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}))
            started = []
            worker.launch(self.request(), on_start=started.append)
            worker.launch(self.request(), on_start=started.append)
            self.assertNotEqual(started[0].pid, started[1].pid)
            self.assertTrue(worker.pid_alive(started[0].pid))
            self.assertFalse(worker.pid_alive(started[1].pid))
            fake.alive[started[0].pid] = False
            self.assertFalse(worker.pid_alive(started[0].pid))
            self.assertEqual(int((self.run / "pid").read_text(encoding="utf-8")), started[1].pid)

    def test_a_delay_is_honored(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}), delay=0.05)
            with mock.patch("wayline.worker.time.sleep") as sleep:
                worker.launch(self.request())
            sleep.assert_called_once_with(0.05)

    def test_a_script_file_drives_demos(self):
        script = self.root / "fake.json"
        script.write_text(json.dumps([
            {"envelope": {"structured_output": {"skill_token": "A", "report": "from file"}, "num_turns": 2},
             "patch": {"files": {"out.txt": "made\n"}, "message": "fake: out"}, "alive": False, "delay": 0, "ticket": 3},
            {"envelope": {"subtype": "success"}},
        ]), encoding="utf-8")
        with mock.patch.dict(os.environ, {"WAYLINE_LAUNCHER": "fake", "WAYLINE_FAKE_SCRIPT": str(script)}):
            worker.FAKE.reset()
            first = worker.launch(self.request())
            self.assertEqual(first.structured_output["report"], "from file")
            self.assertEqual(first.num_turns, 2)
            self.assertEqual((self.repo / "out.txt").read_text(encoding="utf-8"), "made\n")
            second = worker.launch(self.request())
            self.assertFalse(second.valid)
            with self.assertRaises(worker.LaunchError):
                worker.launch(self.request())
        worker.FAKE.reset()
        with worker.use_fake() as fake:
            fake.load(script)
            self.assertEqual(len(fake.queue), 2)

    def test_an_exported_script_file_does_not_leak_into_a_scripted_block(self):
        script = self.root / "fake.json"
        script.write_text(json.dumps([{"envelope": {"structured_output": {"skill_token": "A", "report": "leak"}}}]), encoding="utf-8")
        with mock.patch.dict(os.environ, {"WAYLINE_FAKE_SCRIPT": str(script)}):
            with worker.use_fake() as fake:
                self.assertNotIn("WAYLINE_FAKE_SCRIPT", os.environ)
                fake.script(Envelope(structured_output={"skill_token": "A", "report": "scripted"}))
                self.assertEqual(worker.launch(self.request()).structured_output["report"], "scripted")
                with self.assertRaises(worker.LaunchError):
                    worker.launch(self.request())
            self.assertEqual(os.environ["WAYLINE_FAKE_SCRIPT"], str(script))

    def test_a_malformed_script_file_fails_every_call_with_its_own_error(self):
        script = self.root / "fake.json"
        script.write_text('{"not": "a list"}', encoding="utf-8")
        with mock.patch.dict(os.environ, {"WAYLINE_LAUNCHER": "fake", "WAYLINE_FAKE_SCRIPT": str(script)}):
            worker.FAKE.reset()
            for _ in range(2):
                with self.assertRaises(worker.LaunchError) as caught:
                    worker.launch(self.request())
                self.assertIn("JSON list", str(caught.exception))
        worker.FAKE.reset()

    def test_a_malformed_script_is_refused(self):
        with worker.use_fake() as fake:
            with self.assertRaises(worker.LaunchError):
                fake.script({"structured_output": {}, "typo_field": 1})
            with self.assertRaises(worker.LaunchError):
                fake.script(Envelope(), patch={"paths": {}})
            with self.assertRaises(worker.LaunchError):
                fake.script(Envelope(), alive="yes")
            with self.assertRaises(worker.LaunchError):
                fake.script(Envelope(), delay="soon")
            with self.assertRaises(worker.LaunchError):
                fake.script(Envelope(), patch=Patch({"../escape.txt": "x"}))
                worker.launch(self.request())
            self.assertFalse((self.root / "escape.txt").exists())

    def test_the_fake_never_starts_a_process(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"skill_token": "A", "report": "r"}))
            with mock.patch("wayline.worker.subprocess.Popen") as popen:
                worker.launch(self.request())
            popen.assert_not_called()


class SmokeVerbTest(StandInMixin, unittest.TestCase):
    def test_launch_is_hidden_from_the_overview_but_registered(self):
        self.assertIn("launch", [verb.name for verb in cli.VERBS])
        self.assertNotRegex(cli.overview(), r"(?m)^\s+launch\b")
        done = run_cli("--help")
        self.assertNotRegex(done.stdout, r"(?m)^\s+launch\b")

    def test_smoke_prints_the_envelope_and_the_windows(self):
        smoke_dir = self.root / "smoke"
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "synth-smoke.jsonl")
        done = run_cli("launch", "--smoke", "--dir", str(smoke_dir))
        self.assertEqual(done.returncode, 0, done.stderr)
        argv = self.recorded()["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--effort") + 1], "low")
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        self.assertEqual(len(schema["properties"]), 2)
        self.assertIn('"session_id": "83508b6e-7d57-40cc-9243-83174fde6613"', done.stdout)
        self.assertIn("five_hour", done.stdout)
        self.assertIn("15%", done.stdout)
        self.assertIn("seven_day", done.stdout)
        self.assertIn("21%", done.stdout)
        self.assertIn(str(smoke_dir), done.stdout)
        for name in ["prompt.md", "agent.json", "settings.json", "env.json", "stream.jsonl", "stderr.txt", "result.json"]:
            self.assertTrue((smoke_dir / name).exists(), name)

    def test_a_relative_dir_is_resolved_before_the_child_changes_directory(self):
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "synth-smoke.jsonl")
        relative = os.path.relpath(self.root / "smoke", HARNESS_ROOT)
        done = run_cli("launch", "--smoke", "--dir", relative)
        self.assertEqual(done.returncode, 0, done.stderr)
        argv = self.recorded()["argv"]
        self.assertEqual(argv[argv.index("--settings") + 1], str(self.root / "smoke" / "settings.json"))
        self.assertEqual(self.recorded()["cwd"], str(self.root / "smoke"))

    def test_smoke_reports_an_invalid_result_with_exit_1(self):
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "note01-launch1-success-without-structured-output.jsonl")
        done = run_cli("launch", "--smoke", "--dir", str(self.root / "smoke"))
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("structured_output", done.stdout + done.stderr)

    def test_smoke_reports_a_launcher_error_without_a_traceback(self):
        os.environ["WAYLINE_CLAUDE"] = str(self.root / "no-such-claude")
        done = run_cli("launch", "--smoke", "--dir", str(self.root / "smoke"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("WAYLINE_CLAUDE", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_launch_without_smoke_or_with_a_bad_alias_is_a_usage_error(self):
        done = run_cli("launch")
        self.assertEqual(done.returncode, 2)
        self.assertIn("--smoke", done.stderr)
        done = run_cli("launch", "--smoke", "--model", "sonet")
        self.assertEqual(done.returncode, 2)


class SeamTest(unittest.TestCase):
    """Nothing in the harness starts `claude` except the `claude_cli` backend (M0 criterion 10)."""

    EXECUTABLE = "claude"
    # The bare word, or a path ending in it, inside a string: "claude", "claude -p", "/usr/bin/claude", "cd x && claude -p".
    NAMES_IT = re.compile(r"(^|[/\s'\"=])claude($|[\s'\"])")

    def modules(self):
        for path in sorted((HARNESS_ROOT / "wayline").rglob("*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    @staticmethod
    def docstrings(tree):
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    found.add(id(first.value))
        return found

    def test_the_executable_is_named_only_inside_the_claude_cli_backend(self):
        hits = []
        for path, tree in self.modules():
            owners = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for inner in ast.walk(node):
                        owners[id(inner)] = node.name
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and (node.value == self.EXECUTABLE or node.value.startswith(self.EXECUTABLE + " ")):
                    hits.append((path.relative_to(HARNESS_ROOT).as_posix(), owners.get(id(node))))
        self.assertTrue(hits, "the backend must name the executable somewhere")
        self.assertEqual(set(hits), {("wayline/worker.py", "ClaudeCli")})

    def test_no_module_but_the_backend_reaches_the_executable(self):
        """Path-qualified, env-indirected, shell-string, and re-exported spellings are caught too."""
        for path, tree in self.modules():
            if path.name == "worker.py":
                continue
            skip = self.docstrings(tree)
            for node in ast.walk(tree):
                where = "%s:%d" % (path.relative_to(HARNESS_ROOT).as_posix(), getattr(node, "lineno", 0))
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                    self.assertIsNone(self.NAMES_IT.search(node.value), "%s names the executable: %r" % (where, node.value))
                    self.assertNotIn("WAYLINE_CLAUDE", node.value, where)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, ("ClaudeCli", "CLAUDE_CLI"), where)
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ("ClaudeCli", "CLAUDE_CLI"), where)

    def test_the_scan_recognizes_the_spellings_it_guards_against(self):
        for spelling in ["claude", "claude -p x", "/home/me/.local/bin/claude", "cd x && claude -p x", "env claude", 'x="claude"']:
            self.assertIsNotNone(self.NAMES_IT.search(spelling), spelling)
        for benign in [".claude/skills", "~/.claude/settings.json", "Claude Code", "claude_cli", "claudeAiOauth"]:
            self.assertIsNone(self.NAMES_IT.search(benign), benign)

    def test_the_backend_class_is_named_after_the_spec(self):
        self.assertEqual(worker.ClaudeCli.name, "claude_cli")
        self.assertEqual(worker.FakeLauncher.name, "fake")


if __name__ == "__main__":
    unittest.main()
