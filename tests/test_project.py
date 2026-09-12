"""`wayline init` and `wayline switch`: the layout, the symlinks, the pointers, idempotence.

Every test runs offline against a temporary `WAYLINE_HOME` and a fake harness checkout, and
asserts on what a user or the next component can observe: the files on disk, the pointers, the
journal events, and the exit codes.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase, tree_hash
from wayline import TAG
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger
from wayline.project import (
    BLOCK_BEGIN, BLOCK_END, GITIGNORE_ENTRIES, HARNESS_JSON, RESEARCH_DIRS, ProjectError,
    default_harness, find_project, init_project, read_active, read_harness, read_projects,
    switch_project,
)
from wayline.tickets import GRAPH


class InitLayoutTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.harness = self.fake_harness()
        self.project = self.temp / "study"
        self.report = init_project(self.project, harness_root=self.harness)

    def test_harness_json_carries_the_pin_and_the_defaults(self):
        harness = read_harness(self.project)
        self.assertEqual(harness["harness_tag"], TAG)
        self.assertEqual(harness["autonomy"], "checkpoints")
        self.assertEqual(harness["radius"], "moderate")
        self.assertEqual(harness["reservations"], {"gpu": [], "cores": 8, "ram_gb": 64, "processes": []})
        self.assertEqual(harness["pacing"], {"stop_at": 0.90, "cheap_at": 0.80})
        self.assertEqual(harness["dashboard"]["port"], 8765)
        self.assertIn("hermes_python", harness["notify"])
        self.assertEqual(harness["policy"], {})

    def test_harness_json_matches_the_policy_defaults_of_decision_14(self):
        policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        harness = read_harness(self.project)
        self.assertEqual(harness["reservations"], policy["reservations"])
        self.assertEqual(harness["pacing"], policy["pacing"])
        self.assertEqual(harness["dashboard"], policy["dashboard"])

    def test_claude_md_carries_the_block_with_the_tag(self):
        text = (self.project / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(BLOCK_BEGIN, text)
        self.assertIn(BLOCK_END, text)
        self.assertIn(TAG, text)
        self.assertIn("research/", text)

    def test_gitignore_carries_the_four_entries(self):
        lines = (self.project / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in GITIGNORE_ENTRIES:
            self.assertIn(entry, lines)

    def test_the_research_tree_exists_with_the_empty_ledger_files(self):
        research = self.project / "research"
        for name in RESEARCH_DIRS:
            self.assertTrue((research / name).is_dir(), name)
        self.assertIn("## The intent", (research / "INTAKE.md").read_text(encoding="utf-8"))
        self.assertEqual((research / "journal.jsonl").read_bytes(), b"")
        self.assertEqual((research / "findings.jsonl").read_bytes(), b"")
        self.assertEqual(json.loads((research / "manifest.json").read_text(encoding="utf-8")), {"entries": []})
        self.assertEqual(json.loads((research / GRAPH).read_text(encoding="utf-8")), {"snapshot": {}, "tickets": []})

    def test_the_manifest_validates_against_its_schema(self):
        check(json.loads((self.project / "research" / "manifest.json").read_text(encoding="utf-8")), load_schema("manifest"))

    def test_the_project_directories_outside_the_ledger_exist(self):
        self.assertTrue((self.project / ".worktrees").is_dir())
        self.assertTrue((self.project / "results").is_dir())

    def test_every_harness_skill_and_workflow_is_symlinked(self):
        for skill in ("wayline-absorb", "wayline-figure"):
            link = self.project / ".claude" / "skills" / skill
            self.assertTrue(link.is_symlink(), skill)
            self.assertEqual(os.readlink(link), str(self.harness / "skills" / skill))
        for workflow in ("absorb.js", "panel.js"):
            link = self.project / ".claude" / "workflows" / workflow
            self.assertTrue(link.is_symlink(), workflow)
            self.assertEqual(os.readlink(link), str(self.harness / "workflows" / workflow))
        self.assertTrue((self.project / ".claude" / "agents").is_dir())

    def test_the_project_is_a_git_repository_on_main_with_one_commit(self):
        head = subprocess.run(["git", "-C", str(self.project), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
        self.assertEqual(head.stdout.strip(), "main")
        log = subprocess.run(["git", "-C", str(self.project), "log", "--oneline"], capture_output=True, text=True)
        self.assertEqual(len(log.stdout.strip().splitlines()), 1)
        status = subprocess.run(["git", "-C", str(self.project), "status", "--porcelain"], capture_output=True, text=True)
        self.assertEqual(status.stdout.strip(), "")

    def test_the_pointers_live_outside_the_harness_and_the_project(self):
        self.assertEqual(read_active(), self.project.resolve())
        entries = read_projects()
        self.assertEqual([entry["path"] for entry in entries], [str(self.project.resolve())])
        self.assertEqual(entries[0]["name"], "study")
        self.assertEqual(entries[0]["harness_tag"], TAG)
        self.assertIn("created", entries[0])
        for path in (self.wayline_home / "projects.json", self.wayline_home / "active"):
            self.assertTrue(path.exists())
            self.assertFalse(path.is_relative_to(self.project))
            self.assertFalse(path.is_relative_to(HARNESS_ROOT))

    def test_the_report_names_what_it_wrote(self):
        self.assertIn(HARNESS_JSON, self.report["changes"])
        self.assertIn("research/journal.jsonl", self.report["changes"])
        self.assertTrue(self.report["created"])
        self.assertIsNone(self.report["displaced"])


class InitIdempotenceTest(ProjectTestCase):
    def test_a_second_init_changes_nothing_in_the_project(self):
        harness = self.fake_harness()
        project = self.temp / "study"
        init_project(project, harness_root=harness)
        before = tree_hash(project)
        head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        report = init_project(project, harness_root=harness)
        self.assertEqual(tree_hash(project), before)
        self.assertEqual(report["changes"], [])
        self.assertFalse(report["created"])
        after = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertEqual(head, after)

    def test_a_second_init_keeps_the_created_timestamp(self):
        harness = self.fake_harness()
        project = self.temp / "study"
        init_project(project, harness_root=harness)
        created = read_projects()[0]["created"]
        init_project(project, harness_root=harness)
        self.assertEqual(read_projects()[0]["created"], created)
        self.assertEqual(len(read_projects()), 1)

    def test_init_leaves_an_existing_repository_and_its_history_alone(self):
        project = self.temp / "existing"
        project.mkdir()
        subprocess.run(["git", "-C", str(project), "init", "-b", "trunk"], capture_output=True)
        (project / "README.md").write_text("mine\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(project), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(project), "commit", "-m", "mine"], capture_output=True)
        head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        init_project(project, harness_root=self.fake_harness())
        self.assertEqual(subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True).stdout, head)
        self.assertEqual(subprocess.run(["git", "-C", str(project), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip(), "trunk")

    def test_init_appends_its_block_to_an_existing_claude_md_and_never_overwrites_it(self):
        project = self.temp / "existing"
        project.mkdir()
        (project / "CLAUDE.md").write_text("# My project\n\nRun the thing.\n", encoding="utf-8")
        init_project(project, harness_root=self.fake_harness())
        text = (project / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# My project"))
        self.assertIn("Run the thing.", text)
        self.assertEqual(text.count(BLOCK_BEGIN), 1)
        before = tree_hash(project)
        init_project(project, harness_root=self.fake_harness())
        self.assertEqual(tree_hash(project), before)

    def test_init_refreshes_the_block_when_the_tag_moved(self):
        harness = self.fake_harness()
        project = self.temp / "study"
        init_project(project, harness_root=harness, harness_tag="v0.0.0")
        (project / HARNESS_JSON).write_text(json.dumps(default_harness("v9.9.9", hermes_python=None)) + "\n", encoding="utf-8")
        init_project(project, harness_root=harness)
        text = (project / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(BLOCK_BEGIN), 1)
        self.assertIn("v9.9.9", text)
        self.assertNotIn("v0.0.0", text)

    def test_init_keeps_an_owner_edited_harness_json(self):
        harness = self.fake_harness()
        project = self.temp / "study"
        init_project(project, harness_root=harness)
        edited = read_harness(project)
        edited["autonomy"] = "autonomous"
        (project / HARNESS_JSON).write_text(json.dumps(edited, indent=2) + "\n", encoding="utf-8")
        init_project(project, harness_root=harness)
        self.assertEqual(read_harness(project)["autonomy"], "autonomous")

    def test_init_keeps_existing_gitignore_entries(self):
        project = self.temp / "existing"
        project.mkdir()
        (project / ".gitignore").write_text("*.pyc\nresults/\n", encoding="utf-8")
        init_project(project, harness_root=self.fake_harness())
        lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("*.pyc", lines)
        self.assertEqual(lines.count("results/"), 1)
        for entry in GITIGNORE_ENTRIES:
            self.assertIn(entry, lines)


class SymlinkRefreshTest(ProjectTestCase):
    def test_a_symlink_pointing_at_another_harness_is_replaced(self):
        old, new = self.fake_harness(name="old"), self.fake_harness(name="new")
        project = self.temp / "study"
        init_project(project, harness_root=old)
        link = project / ".claude" / "skills" / "wayline-absorb"
        self.assertEqual(os.readlink(link), str(old / "skills" / "wayline-absorb"))
        report = init_project(project, harness_root=new)
        self.assertEqual(os.readlink(link), str(new / "skills" / "wayline-absorb"))
        self.assertIn(".claude/skills/wayline-absorb", report["changes"])

    def test_a_dangling_symlink_into_the_harness_is_removed(self):
        harness = self.fake_harness()
        project = self.temp / "study"
        init_project(project, harness_root=harness)
        shutil.rmtree(harness / "skills" / "wayline-figure")
        report = init_project(project, harness_root=harness)
        self.assertFalse((project / ".claude" / "skills" / "wayline-figure").is_symlink())
        self.assertIn("removed .claude/skills/wayline-figure", report["changes"])

    def test_a_local_skill_that_is_not_a_symlink_is_left_alone(self):
        harness = self.fake_harness()
        project = self.temp / "study"
        init_project(project, harness_root=harness)
        local = project / ".claude" / "skills" / "wayline-absorb"
        local.unlink()
        local.mkdir()
        (local / "SKILL.md").write_text("# local override\n", encoding="utf-8")
        report = init_project(project, harness_root=harness)
        self.assertFalse(local.is_symlink())
        self.assertEqual((local / "SKILL.md").read_text(encoding="utf-8"), "# local override\n")
        self.assertTrue(any("left alone" in note for note in report["notes"]))

    def test_a_harness_without_skills_or_workflows_still_lays_out_a_project(self):
        bare = self.temp / "bare"
        (bare / "templates" / "project").mkdir(parents=True)
        shutil.copytree(HARNESS_ROOT / "templates" / "project", bare / "templates" / "project", dirs_exist_ok=True)
        project = self.temp / "study"
        init_project(project, harness_root=bare)
        self.assertTrue((project / ".claude" / "skills").is_dir())
        self.assertEqual(list((project / ".claude" / "skills").iterdir()), [])


class SwitchTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.harness = self.fake_harness()
        self.first = self.temp / "first"
        self.second = self.temp / "second"
        init_project(self.first, harness_root=self.harness)
        init_project(self.second, harness_root=self.harness)

    def test_init_points_the_machine_at_the_project_it_just_laid_out(self):
        self.assertEqual(read_active(), self.second.resolve())

    def test_switch_moves_the_pointer_and_journals_switched_in_both_projects(self):
        moved = switch_project(self.first)
        self.assertTrue(moved["moved"])
        self.assertEqual(read_active(), self.first.resolve())
        for project in (self.first, self.second):
            events, _ = Ledger(project).read_events()
            switched = [event for event in events if event["event"] == "switched"]
            self.assertEqual(len(switched), 1, project)
            self.assertEqual(switched[0]["payload"], {"from": str(self.second.resolve()), "to": str(self.first.resolve())})

    def test_switching_to_the_active_project_journals_nothing(self):
        switch_project(self.second)
        events, _ = Ledger(self.second).read_events()
        self.assertEqual(events, [])

    def test_switch_refuses_a_directory_that_is_not_a_project(self):
        plain = self.temp / "plain"
        plain.mkdir()
        with self.assertRaises(ProjectError):
            switch_project(plain)
        self.assertEqual(read_active(), self.second.resolve())

    def test_switch_registers_a_project_init_did_not_touch_on_this_machine(self):
        (self.wayline_home / "projects.json").write_text("[]\n", encoding="utf-8")
        switch_project(self.first)
        self.assertEqual([entry["path"] for entry in read_projects()], [str(self.first.resolve())])

    def test_init_reports_the_project_it_displaced(self):
        third = self.temp / "third"
        report = init_project(third, harness_root=self.harness)
        self.assertEqual(report["displaced"], str(self.second.resolve()))


class FindProjectTest(ProjectTestCase):
    def test_an_explicit_path_wins_over_the_pointer(self):
        harness = self.fake_harness()
        first, second = self.temp / "first", self.temp / "second"
        init_project(first, harness_root=harness)
        init_project(second, harness_root=harness)
        self.assertEqual(find_project(str(first)), first.resolve())
        self.assertEqual(find_project(None), second.resolve())

    def test_no_active_project_says_what_to_run(self):
        with self.assertRaises(ProjectError) as caught:
            find_project(None)
        self.assertIn("wayline init", str(caught.exception))

    def test_a_directory_without_harness_json_is_not_a_project(self):
        plain = self.temp / "plain"
        plain.mkdir()
        with self.assertRaises(ProjectError):
            find_project(str(plain))


class DefaultHarnessTest(unittest.TestCase):
    def test_the_default_validates_against_the_harness_schema(self):
        check(default_harness(hermes_python=None), load_schema("harness"), name="harness.json")

    def test_an_unknown_policy_shape_still_yields_a_valid_harness_json(self):
        value = default_harness(policy={}, hermes_python=None)
        check(value, load_schema("harness"), name="harness.json")
        self.assertEqual(value["reservations"]["cores"], 8)

    def test_a_bad_tag_is_refused(self):
        with self.assertRaises(ValidationError):
            default_harness("0.0.0", hermes_python=None)


class InitCommandTest(ProjectTestCase):
    def run_cli(self, *args):
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home))
        return subprocess.run([sys.executable, "-m", "wayline", *args], cwd=str(HARNESS_ROOT),
                              capture_output=True, text=True, timeout=120, env=environment)

    def test_init_lays_out_a_project_from_the_command_line(self):
        project = self.temp / "cli-study"
        done = self.run_cli("init", str(project))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(str(project), done.stdout)
        self.assertTrue((project / HARNESS_JSON).is_file())
        self.assertEqual(read_active(), project.resolve())

    def test_a_second_init_says_there_was_nothing_to_do(self):
        project = self.temp / "cli-study"
        self.run_cli("init", str(project))
        done = self.run_cli("init", str(project))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("nothing to do", done.stdout)

    def test_uninstall_units_names_the_ticket_that_installs_them(self):
        done = self.run_cli("init", str(self.temp / "cli-study"), "--uninstall-units")
        self.assertEqual(done.returncode, 2)
        self.assertIn("ticket 14", done.stderr)

    def test_switch_from_the_command_line_moves_the_pointer(self):
        first, second = self.temp / "one", self.temp / "two"
        self.run_cli("init", str(first))
        self.run_cli("init", str(second))
        done = self.run_cli("switch", str(first))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(read_active(), first.resolve())
        self.assertIn(str(first), done.stdout)

    def test_switch_to_a_directory_that_is_not_a_project_exits_1(self):
        plain = self.temp / "plain"
        plain.mkdir()
        done = self.run_cli("switch", str(plain))
        self.assertEqual(done.returncode, 1)
        self.assertIn("not a wayline project", done.stderr)


if __name__ == "__main__":
    unittest.main()
