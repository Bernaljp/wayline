"""The project the M0 demo runs on, checked here with the fake worker (ticket 06).

`docs/verification/m0.md` records what a real `claude -p` did with this same project, once, as
Testing Decisions ask. What the suite can hold is everything that does not need a model: that the
fixture is well formed, that `init` leaves its two skills alone, that the prompt the launcher
would be handed carries both `/wayline-<skill>` lines and the ticket's own instructions, that each
skill's passphrase is written in exactly one place, and that the whole path still ends with the
files on `main` and a journal that says how they got there.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import conductor, project, tickets, worker

M0_LIVE = FIXTURES_DIR / "projects" / "m0-live"
TICKET_FILE = "01-probe-the-guards-the-skills-and-the-subagent.md"

# Each skill's SKILL.md is the only place its passphrase is written, which is what makes a
# passphrase evidence that the skill's body reached the worker rather than a guess.
PASSPHRASES = {"wayline-m0-note": "plumbline-4f2a", "wayline-m0-tally": "sextant-9c7b"}


class FixtureShapeTest(unittest.TestCase):
    """The fixture as it is checked in, before `init` has touched it."""

    def test_the_ticket_parses_and_names_its_two_skills(self):
        [ticket] = tickets.read_tickets(M0_LIVE)
        self.assertEqual(ticket["id"], 1)
        self.assertEqual(ticket["skills"], ["m0-note", "m0-tally"])
        self.assertEqual(ticket["touches"], ["m0/"])
        self.assertEqual(ticket["role"], "coder")

    def test_the_ticket_file_is_named_after_its_title(self):
        """The conductor rewrites the ticket by title; a name that disagrees would leave two files."""
        [ticket] = tickets.read_tickets(M0_LIVE)
        self.assertEqual(tickets.filename(ticket), TICKET_FILE)

    def test_each_skill_line_has_a_skill_behind_it(self):
        [ticket] = tickets.read_tickets(M0_LIVE)
        for skill in ticket["skills"]:
            with self.subTest(skill=skill):
                self.assertTrue((M0_LIVE / ".claude" / "skills" / ("wayline-" + skill) / "SKILL.md").is_file())

    def test_a_passphrase_is_written_in_one_place_and_nowhere_else(self):
        for skill, passphrase in PASSPHRASES.items():
            carrying = [path.relative_to(M0_LIVE).as_posix()
                        for path in sorted(M0_LIVE.rglob("*"))
                        if path.is_file() and passphrase in path.read_text(encoding="utf-8")]
            with self.subTest(skill=skill):
                self.assertEqual(carrying, [".claude/skills/%s/SKILL.md" % skill, "fake-worker.json"])

    def test_the_acceptance_commands_are_shell_built_ins(self):
        """The fixture runs on a machine with no Python project, no test framework, and no network."""
        [ticket] = tickets.read_tickets(M0_LIVE)
        for command in ticket["acceptance"]["machine"]:
            with self.subTest(command=command):
                self.assertRegex(command, r"^(test|grep) ")


class PromptTest(ProjectTestCase):
    """What the launcher would be handed: both skill lines, the ticket's own instructions, the pack."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "m0-live"
        shutil.copytree(M0_LIVE, self.project)
        project.init_project(self.project)
        [self.ticket] = tickets.read_tickets(self.project)
        self.prompt = worker.assemble_prompt(
            self.ticket, worker.read_role("coder", HARNESS_ROOT, self.project),
            roots=(self.project,), budget={"max_turns": 40, "max_minutes": 20})

    def test_the_prompt_opens_with_one_skill_line_per_skill(self):
        self.assertEqual(self.prompt.text.split("\n")[:2], ["/wayline-m0-note", "/wayline-m0-tally"])

    def test_the_context_pack_carries_the_five_steps_the_ticket_asks_for(self):
        self.assertIn("## research/tickets/%s#what-to-do" % TICKET_FILE, self.prompt.text)
        for step in ("m0/hello.txt", "escaped.txt", "Agent tool exactly once", "wayline accept"):
            with self.subTest(step=step):
                self.assertIn(step, self.prompt.text)

    def test_each_skill_reaches_the_worker_by_the_route_the_live_run_measured(self):
        """The first line expands; the rest are inlined (`docs/verification/m0.md`).

        So the first skill's passphrase must not be in the prompt at all, or its coming back would
        prove nothing, and the second's must be, because nothing else would carry it.
        """
        self.assertNotIn(PASSPHRASES["wayline-m0-note"], self.prompt.text)
        self.assertIn(PASSPHRASES["wayline-m0-tally"], self.prompt.text)
        self.assertIn("## /wayline-m0-tally", self.prompt.text)

    def test_the_pack_read_every_entry_it_was_given(self):
        self.assertEqual(self.prompt.problems, [])
        self.assertEqual(self.prompt.dropped, [])

    def test_init_leaves_the_project_s_own_skills_where_they_are(self):
        for skill in PASSPHRASES:
            directory = self.project / ".claude" / "skills" / skill
            with self.subTest(skill=skill):
                self.assertTrue(directory.is_dir())
                self.assertFalse(directory.is_symlink())

    def test_the_worktree_the_worker_starts_in_carries_the_skills(self):
        """A worktree is checked out from `main`, so a skill reaches the worker only if it is committed.

        The project's own two skills are committed as files; the harness's are the symlinks `init`
        laid down, which resolve from a worktree because they name the harness by absolute path.
        """
        tracked = subprocess.run(["git", "-C", str(self.project), "ls-files", "-s", ".claude/skills"],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(tracked.returncode, 0, tracked.stderr)
        rows = [line.split("\t", 1) for line in tracked.stdout.splitlines()]
        files = sorted(path for mode, path in rows if not mode.startswith("120000"))
        links = sorted(path for mode, path in rows if mode.startswith("120000"))
        self.assertEqual(files, [".claude/skills/%s/SKILL.md" % skill for skill in sorted(PASSPHRASES)])
        self.assertTrue(links, "init links the harness skills in, and a worktree carries only what is committed")
        for link in links:
            with self.subTest(link=link):
                self.assertEqual(Path(os.readlink(self.project / link)).parent, HARNESS_ROOT / "skills")


class ShellRunTest(ProjectTestCase):
    """The whole path from the shell with the fake worker: the same two commands the record used."""

    def test_the_fixture_runs_end_to_end(self):
        target = self.temp / "m0-live"
        shutil.copytree(M0_LIVE, target)
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home))
        laid_out = subprocess.run([sys.executable, "-m", "wayline", "init", str(target)],
                                  cwd=HARNESS_ROOT, capture_output=True, text=True, env=environment, timeout=120)
        self.assertEqual(laid_out.returncode, 0, laid_out.stderr)

        environment.update(WAYLINE_LAUNCHER="fake", WAYLINE_FAKE_SCRIPT=str(target / "fake-worker.json"))
        ran = subprocess.run([sys.executable, "-m", "wayline", "run"],
                             cwd=HARNESS_ROOT, capture_output=True, text=True, env=environment, timeout=300)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("1 ticket(s) done", ran.stdout)
        self.assertIn("frontier_empty", ran.stdout)

        self.assertEqual((target / "m0" / "hello.txt").read_text(encoding="utf-8"), "hello\n")
        self.assertTrue((target / "m0" / "report.md").read_text(encoding="utf-8").strip())
        self.assertEqual(
            sorted((target / "m0" / "skills-seen.txt").read_text(encoding="utf-8").split("\n")[:2]),
            ["m0-note: plumbline-4f2a", "m0-tally: sextant-9c7b"])
        self.assertFalse((target / "escaped.txt").exists())
        self.assertEqual(list((target / conductor.WORKTREES).iterdir()), [])

        events = [json.loads(line)["event"]
                  for line in (target / "research" / "journal.jsonl").read_text(encoding="utf-8").split("\n") if line]
        self.assertEqual(events[0], "run_started")
        self.assertEqual(events[-1], "run_ended")
        self.assertIn("ticket_done", events)

        # The refusal the worker was given reaches the owner as a finding, not as a touch-set
        # complaint: `touched_outside_declared` would have blocked the ticket for the planner.
        findings = [json.loads(line) for line
                    in (target / "research" / "findings.jsonl").read_text(encoding="utf-8").split("\n") if line]
        self.assertIn("touch_set_guard", findings[0]["text"])
        self.assertEqual(tickets.read_tickets(target)[0]["status"], "done")

    def test_the_worker_can_reach_wayline_accept(self):
        """The contract tells the worker to run it, and the stop guard blocks until it has."""
        environment = worker.session_env(self.temp / "m0-live", 1, 1, ["m0/"])
        found = shutil.which("wayline", path=environment["PATH"])
        self.assertIsNotNone(found, "the launch environment's PATH does not reach the wayline command")
        self.assertEqual(Path(found).resolve(), (HARNESS_ROOT / "bin" / "wayline").resolve())


if __name__ == "__main__":
    unittest.main()
