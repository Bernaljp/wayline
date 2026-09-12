"""`wayline accept`: the Type-A gates run in a worktree and the file the stop guard looks for.

The contract of Implementation Decisions 4: the conductor exports `WAYLINE_PROJECT`,
`WAYLINE_TICKET` and `TICKET_ACCEPTANCE_FILE`; the worker runs `wayline accept` inside its
worktree; the file lands with `ran_at`, `where`, `results` and `pass` whether the commands
passed or failed, so the stop guard unblocks either way.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.paths import HARNESS_ROOT
from wayline import cli
from wayline.frontmatter import dump_document
from wayline.gates import GateError, acceptance_file_record, read_ticket, run_machine_acceptance

SAMPLE_TICKET = {
    "id": 7,
    "title": "Add the tokenizer",
    "kind": "code",
    "difficulty": 2,
    "status": "running",
    "blocked_by": [],
    "touches": ["src/tokenizer.py", "tests/"],
    "role": "coder",
    "acceptance": {"machine": ["python3 -c \"print('ok')\"", "test -f made-by-the-worker.txt"]},
    "proposed_by": "planner",
}


def write_project(root, ticket=None, extra_tickets=()):
    """A project skeleton with one ticket under research/tickets/."""
    tickets = root / "research" / "tickets"
    tickets.mkdir(parents=True, exist_ok=True)
    (tickets / "07-add-the-tokenizer.md").write_text(
        dump_document(dict(ticket or SAMPLE_TICKET), "\nThe body is not read by accept.\n"),
        encoding="utf-8",
    )
    for name, frontmatter in extra_tickets:
        (tickets / name).write_text(dump_document(dict(frontmatter), "\n"), encoding="utf-8")
    return root


class ReadTicketTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = write_project(Path(self.temporary.name).resolve())
        self.addCleanup(self.temporary.cleanup)

    def test_the_ticket_is_found_by_its_id_not_its_file_name(self):
        ticket = read_ticket(self.project, 7)
        self.assertEqual(ticket["title"], "Add the tokenizer")

    def test_a_string_id_is_accepted(self):
        self.assertEqual(read_ticket(self.project, "7")["id"], 7)

    def test_an_unknown_id_is_an_error_naming_the_directory(self):
        with self.assertRaises(GateError) as caught:
            read_ticket(self.project, 99)
        self.assertIn("tickets", str(caught.exception))

    def test_a_ticket_the_schema_refuses_is_an_error(self):
        broken = dict(SAMPLE_TICKET, id=8, difficulty=9)
        write_project(self.project, extra_tickets=[("08-broken.md", broken)])
        with self.assertRaises(ValueError):
            read_ticket(self.project, 8)

    def test_a_project_without_tickets_is_an_error(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(GateError) as caught:
                read_ticket(empty, 7)
        self.assertIn("wayline project", str(caught.exception))


class RunMachineAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.worktree = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def test_a_command_runs_in_the_worktree(self):
        (self.worktree / "marker.txt").write_text("here\n", encoding="utf-8")
        results = run_machine_acceptance(["cat marker.txt"], self.worktree, 60)
        self.assertEqual(results[0]["exit_code"], 0)
        self.assertIn("here", results[0]["tail"])

    def test_a_failing_command_keeps_its_output(self):
        results = run_machine_acceptance(["echo boom >&2; exit 3"], self.worktree, 60)
        self.assertEqual(results[0]["exit_code"], 3)
        self.assertIn("boom", results[0]["tail"])

    def test_a_hanging_command_is_killed_and_reports_124(self):
        results = run_machine_acceptance(["sleep 30"], self.worktree, 1)
        self.assertEqual(results[0]["exit_code"], 124)
        self.assertIn("killed", results[0]["tail"])
        self.assertLess(results[0]["seconds"], 20)

    def test_the_record_passes_only_when_every_command_passed(self):
        passing = acceptance_file_record(run_machine_acceptance(["true", "true"], self.worktree, 60), "worktree")
        self.assertTrue(passing["pass"])
        self.assertEqual(passing["where"], "worktree")
        self.assertRegex(passing["ran_at"], r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z$")
        mixed = acceptance_file_record(run_machine_acceptance(["true", "false"], self.worktree, 60), "worktree")
        self.assertFalse(mixed["pass"])

    def test_no_machine_acceptance_passes_vacuously(self):
        record = acceptance_file_record(run_machine_acceptance([], self.worktree, 60), "worktree")
        self.assertTrue(record["pass"])
        self.assertEqual(record["results"], [])


class AcceptVerbTest(unittest.TestCase):
    """The verb end to end: a sample ticket, a scratch worktree, one passing and one failing command."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.project = write_project(self.root / "project")
        self.worktree = self.root / "worktree"
        self.worktree.mkdir()
        self.acceptance = self.root / "sessions" / "7" / "1" / "acceptance.json"
        self.addCleanup(self.temporary.cleanup)

    def run_accept(self, extra=(), env=None):
        environment = dict(os.environ)
        environment.update(
            {
                "WAYLINE_PROJECT": str(self.project),
                "WAYLINE_TICKET": "7",
                "TICKET_ACCEPTANCE_FILE": str(self.acceptance),
                "PYTHONPATH": str(HARNESS_ROOT),
            }
        )
        for key, value in (env or {}).items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        return subprocess.run(
            [sys.executable, "-m", "wayline", "accept", *extra],
            cwd=str(self.worktree),
            capture_output=True,
            text=True,
            timeout=120,
            env=environment,
        )

    def test_a_failing_criterion_exits_1_and_still_writes_the_file(self):
        done = self.run_accept()
        self.assertEqual(done.returncode, 1, done.stderr)
        record = json.loads(self.acceptance.read_text(encoding="utf-8"))
        self.assertFalse(record["pass"])
        self.assertEqual(record["where"], "worktree")
        self.assertEqual([result["cmd"] for result in record["results"]], SAMPLE_TICKET["acceptance"]["machine"])
        self.assertEqual(record["results"][0]["exit_code"], 0)
        self.assertNotEqual(record["results"][1]["exit_code"], 0)
        self.assertIn("FAIL", done.stdout)
        self.assertIn("Add the tokenizer", done.stdout)

    def test_the_same_ticket_passes_once_the_worker_has_done_the_work(self):
        (self.worktree / "made-by-the-worker.txt").write_text("done\n", encoding="utf-8")
        done = self.run_accept()
        self.assertEqual(done.returncode, 0, done.stderr)
        record = json.loads(self.acceptance.read_text(encoding="utf-8"))
        self.assertTrue(record["pass"])
        self.assertTrue(all(result["exit_code"] == 0 for result in record["results"]))
        self.assertIn(str(self.acceptance), done.stdout)

    def test_the_commands_run_in_the_worktree_not_the_project(self):
        (self.project / "made-by-the-worker.txt").write_text("wrong place\n", encoding="utf-8")
        self.assertEqual(self.run_accept().returncode, 1)

    def test_where_defaults_to_worktree_and_is_overridable(self):
        (self.worktree / "made-by-the-worker.txt").write_text("done\n", encoding="utf-8")
        self.run_accept(["--where", "main"])
        self.assertEqual(json.loads(self.acceptance.read_text(encoding="utf-8"))["where"], "main")

    def test_an_unknown_where_exits_2(self):
        done = self.run_accept(["--where", "elsewhere"])
        self.assertEqual(done.returncode, 2)
        self.assertIn("worktree, rebased, main", done.stderr)

    def test_a_missing_environment_variable_exits_2_and_names_it(self):
        for name in ("WAYLINE_PROJECT", "WAYLINE_TICKET", "TICKET_ACCEPTANCE_FILE"):
            with self.subTest(variable=name):
                done = self.run_accept(env={name: None})
                self.assertEqual(done.returncode, 2)
                self.assertIn(name, done.stderr)
                self.assertEqual(done.stdout, "")

    def test_an_unwritable_acceptance_file_exits_2_rather_than_crashing(self):
        blocked = self.root / "not-a-directory"
        blocked.write_text("", encoding="utf-8")
        done = self.run_accept(env={"TICKET_ACCEPTANCE_FILE": str(blocked / "acceptance.json")})
        self.assertEqual(done.returncode, 2)
        self.assertIn("cannot be written", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_ticket_the_schema_refuses_exits_2_rather_than_crashing(self):
        write_project(self.project, extra_tickets=[("09-broken.md", dict(SAMPLE_TICKET, id=9, role="Coder"))])
        done = self.run_accept(env={"WAYLINE_TICKET": "9"})
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("Traceback", done.stderr)

    def test_the_verb_is_built(self):
        self.assertIsNotNone(cli.lookup("accept").handler)


if __name__ == "__main__":
    unittest.main()
