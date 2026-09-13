"""Tags, pins, upgrade, rollback, and promotion (Implementation Decisions 12 and 5, ticket 46).

Every test stands a temporary git repository in for the harness: two annotated tags, `v0.1.0` and
`v0.2.0`, the second adding a skill, and a project laid out by `init` that pins the first. The real
harness is never checked out, tagged, or branched; only its `CHANGELOG.md` and tags are read, by the
test that holds them to one entry per tag.
"""

import io
import json
import os
import re
import shutil
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import TAG, conductor, evolve, fixtures, registry
from wayline.ledger import Ledger
from wayline.project import init_project, read_harness

IDENTITY = ["-c", "user.name=wayline test", "-c", "user.email=test@wayline.invalid"]

CHANGELOG_V1 = """# Changelog

One entry per tag. `wayline upgrade` prints the entries between two tags.

## v0.1.0 (2026-09-01)

The first tag: the absorb skill.
"""

V2_ENTRY = """## v0.2.0 (2026-09-05)

The figure skill.

"""


def write_skill(directory, identifier, scope_kind="global", fixtures_ids=(), body=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(body or "---\nname: %s\ndescription: %s\n---\n\nDo the %s thing.\n" % (directory.name, identifier, identifier),
                                        encoding="utf-8")
    sidecar = {"id": identifier, "scope_kind": scope_kind, "capability_summary": "Does the %s thing." % identifier,
               "applicability_tags": {"kinds": [], "data_types": [], "libraries": [], "venues": []},
               "cost_hint": "small", "fixtures": list(fixtures_ids)}
    (directory / "wayline.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return directory


class HarnessRepositoryCase(ProjectTestCase):
    """A harness repository with the tags `v0.1.0` and `v0.2.0`, checked out at `v0.1.0`, and a project pinned there."""

    def setUp(self):
        super().setUp()
        self.harness = self.fake_harness(skills=("wayline-absorb",), workflows=("absorb.js",))
        (self.harness / "wayline").mkdir()
        (self.harness / "wayline" / "__init__.py").write_text('__version__ = "0.1.0"\nTAG = "v" + __version__\n', encoding="utf-8")
        shutil.copytree(HARNESS_ROOT / "roles" / "coder", self.harness / "roles" / "coder")
        (self.harness / ".gitignore").write_text("fixtures/*/*/runs/\n", encoding="utf-8")
        (self.harness / "CHANGELOG.md").write_text(CHANGELOG_V1, encoding="utf-8")
        self.hgit("init", "-q", "-b", "main")
        self.commit_and_tag("v0.1.0")

        (self.harness / "skills" / "wayline-figure").mkdir()
        (self.harness / "skills" / "wayline-figure" / "SKILL.md").write_text("# wayline-figure\n", encoding="utf-8")
        text = (self.harness / "CHANGELOG.md").read_text(encoding="utf-8")
        (self.harness / "CHANGELOG.md").write_text(text.replace("## v0.1.0", V2_ENTRY + "## v0.1.0"), encoding="utf-8")
        (self.harness / "wayline" / "__init__.py").write_text('__version__ = "0.2.0"\nTAG = "v" + __version__\n', encoding="utf-8")
        self.commit_and_tag("v0.2.0")
        self.hgit("checkout", "-q", "--detach", "v0.1.0")

        self.project = self.temp / "project"
        init_project(self.project, harness_root=self.harness, harness_tag="v0.1.0", hermes_python=None, owner_email=None)

    # --- the stand-in harness ---

    def hgit(self, *args, cwd=None):
        done = subprocess.run(["git", "-C", str(cwd or self.harness), *IDENTITY, *args], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def commit_and_tag(self, tag):
        self.hgit("add", "-A")
        self.hgit("commit", "-q", "-m", "release " + tag)
        self.hgit("tag", "-a", tag, "-m", tag)

    def head_tags(self):
        return self.hgit("tag", "--points-at", "HEAD").split()

    def pin(self):
        return read_harness(self.project)["harness_tag"]

    def events(self, name):
        return [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == name]

    def quietly(self, function, *args, **options):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = function(*args, **options)
        return result, out.getvalue(), err.getvalue()


# --- the pin -------------------------------------------------------------------------------------


class PinTest(HarnessRepositoryCase):
    """`run` refuses a harness checkout that is not at the project's pin, and prints the command that fixes it."""

    def problem(self, **options):
        return evolve.pin_problem(self.project, harness_root=self.harness, environ={}, **options)

    def test_a_checkout_at_the_pin_has_nothing_against_it(self):
        self.assertIsNone(self.problem())

    def test_a_checkout_at_another_tag_is_refused_with_the_upgrade_command(self):
        self.hgit("checkout", "-q", "--detach", "v0.2.0")
        problem = self.problem()
        self.assertIn("v0.2.0", problem)
        self.assertIn("wayline upgrade --to v0.1.0 --project %s" % self.project, problem)
        self.assertIn("wayline upgrade --to v0.2.0 --project %s" % self.project, problem, "moving the project to the checkout fixes it too")

    def test_a_checkout_on_no_tag_is_refused(self):
        self.hgit("checkout", "-q", "main")
        (self.harness / "README.md").write_text("untagged\n", encoding="utf-8")
        self.hgit("add", "-A")
        self.hgit("commit", "-q", "-m", "untagged")
        problem = self.problem()
        self.assertIn("no tag", problem)
        self.assertIn("wayline upgrade --to v0.1.0", problem)

    def test_a_pin_the_repository_has_no_tag_for_says_so(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["harness_tag"] = "v9.9.9"
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        problem = self.problem()
        self.assertIn("v9.9.9", problem)
        self.assertIn("no such tag", problem)
        self.assertIn("wayline upgrade --project", problem)

    def test_a_second_tag_on_the_same_commit_still_matches_the_pin(self):
        self.hgit("tag", "-a", "v0.1.1", "-m", "v0.1.1")
        self.assertIsNone(self.problem())

    def test_the_development_override_skips_the_check(self):
        self.hgit("checkout", "-q", "--detach", "v0.2.0")
        self.assertIsNone(evolve.pin_problem(self.project, harness_root=self.harness, environ={evolve.UNPINNED_ENV: "1"}))

    def test_refuse_to_start_carries_the_pin_problem(self):
        self.hgit("checkout", "-q", "--detach", "v0.2.0")
        with mock.patch.dict(os.environ):
            os.environ.pop(evolve.UNPINNED_ENV, None)
            problems = conductor.refuse_to_start(self.project, harness_root=self.harness)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("wayline upgrade --to v0.1.0", problems[0])

    def test_the_run_verb_exits_2_and_prints_the_fix(self):
        self.hgit("checkout", "-q", "--detach", "v0.2.0")
        with mock.patch.dict(os.environ), mock.patch.object(conductor, "HARNESS_ROOT", self.harness):
            os.environ.pop(evolve.UNPINNED_ENV, None)
            code, _, err = self.quietly(conductor.run_command, ["--project", str(self.project)])
        self.assertEqual(code, 2)
        self.assertIn("wayline upgrade --to v0.1.0", err)
        self.assertEqual(self.events("run_started"), [])


# --- tags and the changelog ------------------------------------------------------------------------


class ChangelogTest(unittest.TestCase):
    TEXT = CHANGELOG_V1.replace("## v0.1.0", "## Unreleased\n\nNot yet.\n\n## v0.3.0 (2026-09-09)\n\nThird.\n\n" + V2_ENTRY + "## v0.1.0")

    def test_tags_parse_as_three_numbers_and_nothing_else(self):
        self.assertEqual(evolve.parse_tag("v1.20.3"), (1, 20, 3))
        for bad in ("1.2.3", "v1.2", "v1.2.3-rc1", "v01.2.3x", "release"):
            with self.subTest(tag=bad):
                self.assertIsNone(evolve.parse_tag(bad))

    def test_the_next_minor_tag(self):
        self.assertEqual(evolve.next_tag("v0.2.7"), "v0.3.0")
        self.assertEqual(evolve.next_tag(None), "v0.1.0")

    def test_the_entries_are_keyed_by_tag_in_file_order(self):
        entries = evolve.changelog_entries(self.TEXT)
        self.assertEqual(list(entries), ["v0.3.0", "v0.2.0", "v0.1.0"])
        self.assertTrue(entries["v0.2.0"].startswith("## v0.2.0 (2026-09-05)"))
        self.assertIn("The figure skill.", entries["v0.2.0"])
        self.assertNotIn("v0.1.0", entries["v0.2.0"])

    def test_the_entries_between_two_tags_leave_the_older_out(self):
        self.assertEqual([tag for tag, _ in evolve.entries_between(self.TEXT, "v0.1.0", "v0.3.0")], ["v0.3.0", "v0.2.0"])
        self.assertEqual([tag for tag, _ in evolve.entries_between(self.TEXT, "v0.3.0", "v0.1.0")], ["v0.3.0", "v0.2.0"],
                         "a rollback lists the same entries: the ones it leaves behind")
        self.assertEqual(evolve.entries_between(self.TEXT, "v0.2.0", "v0.2.0"), [])


class HarnessChangelogTest(unittest.TestCase):
    """The harness's own `CHANGELOG.md` carries one entry per tag, and every tag is `vMAJOR.MINOR.PATCH`."""

    @classmethod
    def setUpClass(cls):
        cls.text = (HARNESS_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_every_version_heading_is_a_tag_and_none_repeats(self):
        headings = re.findall(r"^## (\S+)", self.text, flags=re.MULTILINE)
        versions = [heading for heading in headings if heading != "Unreleased"]
        self.assertTrue(versions)
        for heading in versions:
            with self.subTest(heading=heading):
                self.assertIsNotNone(evolve.parse_tag(heading))
        self.assertEqual(len(versions), len(set(versions)))

    def test_the_package_version_has_an_entry(self):
        self.assertIn(TAG, evolve.changelog_entries(self.text))

    def test_every_tag_of_the_repository_has_an_entry(self):
        """A clone without tags (a shallow CI checkout) has nothing to hold, and passes."""
        done = subprocess.run(["git", "-C", str(HARNESS_ROOT), "tag", "--list", "v*"], capture_output=True, text=True)
        tags = done.stdout.split() if done.returncode == 0 else []
        entries = evolve.changelog_entries(self.text)
        for tag in tags:
            with self.subTest(tag=tag):
                self.assertIsNotNone(evolve.parse_tag(tag))
                self.assertIn(tag, entries)


# --- upgrade and rollback ---------------------------------------------------------------------------


class UpgradeTest(HarnessRepositoryCase):
    def upgrade(self, to=None):
        return evolve.upgrade(self.project, to=to, harness_root=self.harness)

    def test_upgrade_moves_the_checkout_the_pin_the_links_and_journals_pinned(self):
        report = self.upgrade()
        self.assertEqual((report["previous"], report["tag"], report["direction"]), ("v0.1.0", "v0.2.0", "upgrade"))
        self.assertIn("v0.2.0", self.head_tags())
        self.assertEqual(self.pin(), "v0.2.0")
        link = self.project / ".claude" / "skills" / "wayline-figure"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(self.harness / "skills" / "wayline-figure"))
        self.assertIn("v0.2.0", (self.project / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual(self.events("pinned"), [{"tag": "v0.2.0", "previous": "v0.1.0"}])
        self.assertEqual([tag for tag, _ in report["entries"]], ["v0.2.0"])
        self.assertIsNone(evolve.pin_problem(self.project, harness_root=self.harness, environ={}))

    def test_upgrade_commits_what_it_changed_so_the_next_run_is_not_refused(self):
        self.upgrade()
        self.assertEqual(conductor.dirty_outside_research(self.project), [])
        self.assertIn("v0.2.0", subprocess.run(["git", "-C", str(self.project), "log", "-1", "--format=%s"],
                                               capture_output=True, text=True).stdout)

    def test_rollback_is_upgrade_to_the_older_tag(self):
        self.upgrade()
        report = self.upgrade(to="v0.1.0")
        self.assertEqual((report["previous"], report["tag"], report["direction"]), ("v0.2.0", "v0.1.0", "rollback"))
        self.assertIn("v0.1.0", self.head_tags())
        self.assertEqual(self.pin(), "v0.1.0")
        self.assertFalse((self.project / ".claude" / "skills" / "wayline-figure").exists())
        self.assertFalse((self.project / ".claude" / "skills" / "wayline-figure").is_symlink())
        self.assertEqual(self.events("pinned")[-1], {"tag": "v0.1.0", "previous": "v0.2.0"})
        self.assertEqual([tag for tag, _ in report["entries"]], ["v0.2.0"], "the changelog read at the newer tag, not the checkout")
        self.assertEqual(conductor.dirty_outside_research(self.project), [])

    def test_upgrade_to_the_pin_puts_the_checkout_back_and_journals_nothing(self):
        self.hgit("checkout", "-q", "--detach", "v0.2.0")
        report = self.upgrade(to="v0.1.0")
        self.assertEqual(report["direction"], "unchanged")
        self.assertIn("v0.1.0", self.head_tags())
        self.assertEqual(self.events("pinned"), [])

    def test_an_unknown_tag_changes_nothing(self):
        for bad in ("v7.0.0", "latest"):
            with self.subTest(tag=bad), self.assertRaises(evolve.EvolveError):
                self.upgrade(to=bad)
        self.assertIn("v0.1.0", self.head_tags())
        self.assertEqual(self.pin(), "v0.1.0")

    def test_a_harness_checkout_with_tracked_changes_is_not_moved(self):
        (self.harness / "policy.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError) as raised:
            self.upgrade()
        self.assertIn("policy.json", str(raised.exception))
        self.assertEqual(self.pin(), "v0.1.0")

    def test_a_running_conductor_is_not_upgraded_under(self):
        with mock.patch.object(evolve, "conductor_holder", return_value={"pid": 4242}), self.assertRaises(evolve.EvolveError) as raised:
            self.upgrade()
        self.assertIn("4242", str(raised.exception))
        self.assertIn("v0.1.0", self.head_tags())

    def test_a_conductor_on_another_project_holds_the_shared_checkout(self):
        other = self.temp / "other"
        init_project(other, harness_root=self.harness, harness_tag="v0.1.0", hermes_python=None, owner_email=None)
        holding = lambda path: {"pid": 77} if Path(path).resolve() == other.resolve() else None
        with mock.patch.object(evolve, "conductor_holder", side_effect=holding), self.assertRaises(evolve.EvolveError) as raised:
            self.upgrade()
        self.assertIn(str(other), str(raised.exception))
        self.assertIn("v0.1.0", self.head_tags())
        self.assertEqual(self.pin(), "v0.1.0")

    def test_an_uncommitted_edit_to_harness_json_is_not_swept_into_the_pin_commit(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["autonomy"] = "interactive"
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError) as raised:
            self.upgrade()
        self.assertIn("harness.json", str(raised.exception))
        self.assertIn("v0.1.0", self.head_tags())

    def test_an_unfinished_local_skill_stays_out_of_the_pin_commit(self):
        skill = write_skill(self.project / ".claude" / "skills" / "wayline-mine", "mine", scope_kind="local")
        self.hgit("add", "-A", cwd=self.project)
        self.hgit("commit", "-q", "-m", "a local skill", cwd=self.project)
        (skill / "SKILL.md").write_text("half written\n", encoding="utf-8")
        self.upgrade()
        committed = self.hgit("show", "--name-only", "--format=", "HEAD", cwd=self.project).split()
        self.assertIn(".claude/skills/wayline-figure", committed)
        self.assertFalse([path for path in committed if "wayline-mine" in path], committed)
        self.assertIn("wayline-mine", self.hgit("status", "--porcelain", cwd=self.project))

    def test_another_project_left_on_the_old_pin_is_named(self):
        other = self.temp / "other"
        init_project(other, harness_root=self.harness, harness_tag="v0.1.0", hermes_python=None, owner_email=None)
        report = self.upgrade()
        self.assertTrue(any(str(other) in note for note in report["notes"]), report["notes"])

    def test_the_verb_prints_the_changelog_between_the_tags(self):
        with mock.patch.object(evolve, "HARNESS_ROOT", self.harness):
            code, out, _ = self.quietly(evolve.upgrade_command, ["--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertIn("v0.1.0 -> v0.2.0", out)
        self.assertIn("The figure skill.", out)
        with mock.patch.object(evolve, "HARNESS_ROOT", self.harness):
            code, _, err = self.quietly(evolve.upgrade_command, ["--to", "v5.0.0", "--project", str(self.project)])
        self.assertEqual(code, 1)
        self.assertIn("v5.0.0", err)


# --- promotion ------------------------------------------------------------------------------------


class Checks:
    """The command runner `promote` runs the tests and the fixture suite through; records what it was asked."""

    def __init__(self, codes=None):
        self.codes = dict(codes or {})
        self.calls = []

    def __call__(self, argv, cwd):
        self.calls.append((list(argv), Path(cwd)))
        name = "fixtures" if "fixture" in argv else "tests"
        return self.codes.get(name, 0), "output of %s\n" % name


class PromoteCase(HarnessRepositoryCase):
    SKILL = "wayline-local-thing"

    def setUp(self):
        super().setUp()
        self.checks = Checks()

    def promote(self, kind, name, **options):
        options.setdefault("run", self.checks)
        return evolve.promote(kind, name, self.project, harness_root=self.harness, **options)

    def show(self, revision, path):
        return self.hgit("show", "%s:%s" % (revision, path))

    def branch_exists(self, name):
        return subprocess.run(["git", "-C", str(self.harness), "rev-parse", "--verify", "--quiet", "refs/heads/" + name],
                              capture_output=True).returncode == 0

    def merge(self, branch):
        """What the owner does on GitHub or by hand: merge the promotion branch into `main`."""
        self.hgit("checkout", "-q", "main")
        self.hgit("merge", "-q", "--no-ff", "-m", "Merge " + branch, branch)

    def local_skill(self):
        directory = write_skill(self.project / ".claude" / "skills" / self.SKILL, "local-thing", scope_kind="local",
                                fixtures_ids=["skill/local-thing"])
        fixture = self.project / "fixtures" / "skill" / "local-thing"
        (fixture / "input" / "subject" / ".claude" / "skills" / self.SKILL).mkdir(parents=True)
        shutil.copy(directory / "SKILL.md", fixture / "input" / "subject" / ".claude" / "skills" / self.SKILL / "SKILL.md")
        (fixture / "input" / "prompt.md").write_text("Use this:\n\n" + (directory / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
        (fixture / "runs").mkdir()
        (fixture / "runs" / "sample.json").write_text("{}\n", encoding="utf-8")
        record = json.loads((HARNESS_ROOT / "fixtures" / "skill" / "wayline-plan" / "fixture.json").read_text(encoding="utf-8"))
        record["id"] = "skill/local-thing"
        record["subject"] = {"path": ".claude/skills/%s/SKILL.md" % self.SKILL, "sha256": None, "also": [".claude/skills/%s/wayline.json" % self.SKILL]}
        record["subject"]["sha256"] = fixtures.subject_sha256(record, self.project)
        record["baseline"] = {"recorded_at": "2026-09-10T00:00:00Z", "subject_sha256": record["subject"]["sha256"],
                              "structural": "3/3", "judged": None}
        (fixture / "fixture.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return directory


class PromoteSkillTest(PromoteCase):
    def test_a_local_skill_and_its_fixture_land_on_the_promotion_branch(self):
        self.local_skill()
        before = self.hgit("rev-parse", "main")
        report = self.promote("skill", self.SKILL)
        branch = "promote/" + self.SKILL
        self.assertEqual((report["state"], report["branch"]), ("branched", branch))
        self.assertEqual(self.hgit("rev-parse", "main"), before, "main is the owner's to move")
        self.assertIn("v0.1.0", self.head_tags(), "the owner's checkout is not touched")
        self.assertEqual(self.hgit("status", "--porcelain"), "")

        self.assertIn("Do the local-thing thing.", self.show(branch, "skills/%s/SKILL.md" % self.SKILL))
        sidecar = json.loads(self.show(branch, "skills/%s/wayline.json" % self.SKILL))
        self.assertEqual(sidecar["scope_kind"], "global")
        worktree = Path(report["worktree"])
        self.assertEqual(sidecar["sha256"], registry.content_sha256(worktree / "skills" / self.SKILL))

        record = json.loads(self.show(branch, "fixtures/skill/local-thing/fixture.json"))
        self.assertEqual(record["subject"]["path"], "skills/%s/SKILL.md" % self.SKILL)
        self.assertEqual(record["subject"]["also"], ["skills/%s/wayline.json" % self.SKILL])
        self.assertEqual(record["subject"]["sha256"], fixtures.subject_sha256(record, worktree))
        self.assertEqual(record["baseline"]["subject_sha256"], record["subject"]["sha256"])
        self.assertIn("Do the local-thing thing.", self.show(branch, "fixtures/skill/local-thing/input/subject/skills/%s/SKILL.md" % self.SKILL))
        files = self.hgit("ls-tree", "-r", "--name-only", branch).split()
        self.assertFalse([path for path in files if "/runs/" in path or "input/subject/.claude" in path], files)

        changelog = self.show(branch, "CHANGELOG.md")
        self.assertRegex(changelog, r"## Unreleased\n\n- Promoted the local skill `%s`" % self.SKILL)
        self.assertLess(changelog.index("## Unreleased"), changelog.index("## v0.2.0"))

    def test_the_tests_and_the_full_fixture_suite_run_in_the_promotion_worktree(self):
        self.local_skill()
        report = self.promote("skill", self.SKILL)
        worktree = Path(report["worktree"])
        self.assertEqual([cwd for _, cwd in self.checks.calls], [worktree, worktree])
        tests, suite = [argv for argv, _ in self.checks.calls]
        self.assertEqual(tests[1:], ["-m", "unittest"])
        self.assertEqual(suite[-5:], ["fixture", "run", "--suite", "--root", str(worktree)])
        self.assertEqual([(check["name"], check["exit_code"]) for check in report["checks"]], [("tests", 0), ("fixtures", 0)])

    def test_a_failing_check_is_reported_and_the_branch_is_kept_for_the_owner(self):
        self.local_skill()
        self.checks = Checks({"fixtures": 1})
        report = self.promote("skill", self.SKILL)
        self.assertEqual(report["checks"][1]["exit_code"], 1)
        self.assertFalse(report["passed"])
        self.assertTrue(self.branch_exists("promote/" + self.SKILL))

    def test_before_the_merge_a_second_promote_waits_and_changes_nothing(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        tip = self.hgit("rev-parse", "promote/" + self.SKILL)
        report = self.promote("skill", self.SKILL)
        self.assertEqual(report["state"], "waiting")
        self.assertEqual(self.hgit("rev-parse", "promote/" + self.SKILL), tip)
        self.assertEqual(len(self.checks.calls), 2, "the checks ran once, for the branch")

    def test_after_the_merge_promote_tags_main_and_journals_tagged(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        self.merge("promote/" + self.SKILL)
        report = self.promote("skill", self.SKILL)
        self.assertEqual((report["state"], report["tag"]), ("tagged", "v0.3.0"))
        self.assertEqual(self.hgit("rev-parse", "v0.3.0^{commit}"), self.hgit("rev-parse", "main"))
        self.assertEqual(self.hgit("cat-file", "-t", "v0.3.0"), "tag")
        changelog = self.show("v0.3.0", "CHANGELOG.md")
        self.assertRegex(changelog, r"## v0\.3\.0 \(\d{4}-\d{2}-\d{2}\)\n\n- Promoted the local skill")
        self.assertNotIn("## Unreleased", changelog)
        self.assertIn('__version__ = "0.3.0"', self.show("v0.3.0", "wayline/__init__.py"))
        self.assertEqual(self.events("tagged"), [{"tag": "v0.3.0"}])
        self.assertFalse(self.branch_exists("promote/" + self.SKILL), "a merged and tagged promotion branch is done with")
        self.assertFalse(Path(report["worktree"]).exists())
        self.assertEqual(self.hgit("status", "--porcelain"), "")
        self.assertIn("wayline upgrade --to v0.3.0", "\n".join(report["next"]))

    def test_a_squash_merge_counts_as_merged_and_is_tagged(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        self.hgit("checkout", "-q", "main")
        self.hgit("merge", "-q", "--squash", "promote/" + self.SKILL)
        self.hgit("commit", "-q", "-m", "Promote the local skill (squashed)")
        report = self.promote("skill", self.SKILL)
        self.assertEqual((report["state"], report["tag"]), ("tagged", "v0.3.0"))
        self.assertEqual(self.events("tagged"), [{"tag": "v0.3.0"}])
        self.assertFalse(self.branch_exists("promote/" + self.SKILL))

    def test_the_waiting_message_says_the_local_main_must_hold_the_branch(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        report = self.promote("skill", self.SKILL)
        self.assertEqual(report["state"], "waiting")
        self.assertIn("pull", "\n".join(report["next"]))

    def test_the_tag_is_made_in_a_worktree_of_its_own_when_main_is_checked_out_nowhere(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        self.merge("promote/" + self.SKILL)
        self.hgit("checkout", "-q", "--detach", "v0.1.0")
        report = self.promote("skill", self.SKILL, tag="v1.0.0")
        self.assertEqual(report["tag"], "v1.0.0")
        self.assertEqual(self.hgit("rev-parse", "v1.0.0^{commit}"), self.hgit("rev-parse", "main"))
        self.assertIn("v0.1.0", self.head_tags())
        self.assertEqual(len([line for line in self.hgit("worktree", "list").splitlines() if line.strip()]), 1)

    def test_a_tag_not_past_the_latest_is_refused(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        self.merge("promote/" + self.SKILL)
        for bad in ("v0.2.0", "v0.1.9", "0.3.0"):
            with self.subTest(tag=bad), self.assertRaises(evolve.EvolveError):
                self.promote("skill", self.SKILL, tag=bad)
        self.assertEqual(self.events("tagged"), [])

    def test_a_skill_the_harness_already_holds_as_is_has_nothing_to_promote(self):
        self.local_skill()
        self.promote("skill", self.SKILL)
        self.merge("promote/" + self.SKILL)
        self.promote("skill", self.SKILL)
        with self.assertRaises(evolve.EvolveError) as raised:
            self.promote("skill", self.SKILL)
        self.assertIn("nothing to promote", str(raised.exception))
        self.assertFalse(self.branch_exists("promote/" + self.SKILL))

    def test_the_name_may_leave_the_prefix_off(self):
        self.local_skill()
        self.assertEqual(self.promote("skill", "local-thing")["branch"], "promote/" + self.SKILL)

    def test_a_skill_the_project_does_not_have_or_that_is_a_harness_link_is_refused(self):
        for name in ("wayline-nowhere", "wayline-absorb"):
            with self.subTest(name=name), self.assertRaises(evolve.EvolveError):
                self.promote("skill", name)
        self.assertFalse(self.branch_exists("promote/wayline-nowhere"))

    def test_the_verb_says_what_it_did_and_what_comes_next(self):
        self.local_skill()
        with mock.patch.object(evolve, "HARNESS_ROOT", self.harness), mock.patch.object(evolve, "run_check", self.checks):
            code, out, _ = self.quietly(evolve.promote_command, ["skill", self.SKILL, "--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertIn("promote/" + self.SKILL, out)
        self.assertIn("merge", out)
        with mock.patch.object(evolve, "HARNESS_ROOT", self.harness):
            code, _, err = self.quietly(evolve.promote_command, ["hook", "x", "--project", str(self.project)])
        self.assertEqual(code, 2)


class PromoteRoleAndPolicyTest(PromoteCase):
    def test_a_local_role_override_replaces_the_harness_prompt_and_restamps_the_sidecar(self):
        (self.project / ".claude" / "agents" / "coder.md").write_text("---\nname: coder\ndescription: a better coder\n---\n\nBe better.\n", encoding="utf-8")
        report = self.promote("role", "coder")
        branch = report["branch"]
        self.assertEqual(branch, "promote/coder")
        self.assertIn("Be better.", self.show(branch, "roles/coder/agent.md"))
        sidecar = json.loads(self.show(branch, "roles/coder/wayline.json"))
        self.assertEqual(sidecar["sha256"], registry.content_sha256(Path(report["worktree"]) / "roles" / "coder"))
        self.assertEqual(sidecar["allowed_tools"], json.loads((self.harness / "roles" / "coder" / "wayline.json").read_text(encoding="utf-8"))["allowed_tools"])

    def test_a_role_the_harness_has_no_sidecar_for_is_refused(self):
        (self.project / ".claude" / "agents" / "stranger.md").write_text("Be strange.\n", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError) as raised:
            self.promote("role", "stranger")
        self.assertIn("wayline.json", str(raised.exception))

    def set_override(self, policy):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["policy"] = policy
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def test_a_policy_override_is_merged_into_policy_json_touching_only_its_key(self):
        self.set_override({"pacing": {"stop_at": 0.95}, "poll_seconds": 5})
        report = self.promote("policy", "pacing")
        before = (self.harness / "policy.json").read_text(encoding="utf-8")
        after = self.show(report["branch"], "policy.json") + "\n"
        self.assertEqual(json.loads(after)["pacing"], {"stop_at": 0.95, "cheap_at": 0.8})
        self.assertEqual(json.loads(after)["poll_seconds"], json.loads(before)["poll_seconds"], "only the named key moves")
        changed = [(old, new) for old, new in zip(before.splitlines(), after.splitlines()) if old != new]
        self.assertEqual(len(changed), 1, changed)
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))

    def test_a_policy_key_the_project_does_not_override_is_refused(self):
        with self.assertRaises(evolve.EvolveError) as raised:
            self.promote("policy", "pacing")
        self.assertIn("pacing", str(raised.exception))

    def test_a_policy_value_the_schema_refuses_is_not_promoted(self):
        self.set_override({"pacing": {"stop_at": 7}})
        with self.assertRaises(evolve.EvolveError):
            self.promote("policy", "pacing")
        self.assertFalse(self.branch_exists("promote/pacing"))


# --- the recommendation ---------------------------------------------------------------------------


class RecommendationTest(unittest.TestCase):
    def entry(self, identifier, scope_kind="local", assigned=3, passed=3, failed=0, kind="skill"):
        return {"id": identifier, "kind": kind, "scope_kind": scope_kind, "assignable": True,
                "outcome": {"assigned": assigned, "passed_first_time": passed, "failed": failed, "last_used": None}}

    def test_a_local_skill_good_over_several_tickets_is_recommended_and_nothing_else(self):
        entries = [
            self.entry("steady"),
            self.entry("once", assigned=1, passed=1),
            self.entry("flaky", assigned=4, passed=3, failed=1),
            self.entry("slow", assigned=4, passed=2),
            self.entry("harness", scope_kind="global"),
            self.entry("coder", kind="role"),
        ]
        candidates = evolve.promotion_candidates({"entries": entries})
        self.assertEqual([candidate["id"] for candidate in candidates], ["steady"])
        self.assertEqual(candidates[0]["command"], "wayline promote skill wayline-steady")

    def test_the_lines_say_the_decision_is_the_owners(self):
        lines = evolve.render_recommendations(evolve.promotion_candidates({"entries": [self.entry("steady")]}))
        self.assertIn("wayline promote skill wayline-steady", "\n".join(lines))
        self.assertIn("owner", "\n".join(lines))
        self.assertEqual(evolve.render_recommendations([]), [])


if __name__ == "__main__":
    unittest.main()
