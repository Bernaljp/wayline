"""`research_version` and the big-upgrade refusal (Implementation Decision 17, ticket 72).

A project made on a release that kept `research/` another way is refused, never migrated: `upgrade`
to a release of another `research_version` changes nothing and journals nothing, every writing verb
refuses it with the same message, and the dashboard lists it read-only.
"""

import json
import os
from unittest import mock

from tests.test_actions import ActionCase
from tests.test_versions import UpgradeCase
from wayline import RESEARCH_VERSION, TAG, cli, evolve
from wayline.ledger import Ledger
from wayline.project import init_project, old_project_problem, read_harness, research_version


def make_old(project):
    """Hand-make a project of `research_version` 1: the key removed, as a v1.0.x `init` wrote it."""
    path = project / "harness.json"
    harness = json.loads(path.read_text(encoding="utf-8"))
    harness.pop("research_version", None)
    path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
    return harness


def snapshot(project):
    """Every file under the project with its bytes, `.git` left out."""
    files = {}
    for root, dirs, names in os.walk(project):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = os.path.join(root, name)
            if not os.path.islink(path):
                with open(path, "rb") as handle:
                    files[os.path.relpath(path, project)] = handle.read()
    return files


class ResearchVersionTest(UpgradeCase):
    def test_init_writes_the_release_s_research_version_and_absent_reads_as_one(self):
        self.assertEqual(RESEARCH_VERSION, 2)
        fresh = self.temp / "fresh"
        init_project(fresh, harness_root=self.harness, harness_tag="v0.1.0", hermes_python=None, owner_email=None)
        self.assertEqual(read_harness(fresh)["research_version"], 2)
        self.assertIsNone(old_project_problem(fresh))
        make_old(fresh)
        self.assertEqual(research_version(read_harness(fresh)), 1)

    def test_a_small_upgrade_is_still_applied_both_ways(self):
        self.assertEqual(self.upgrade()["direction"], "upgrade")
        self.assertEqual(self.upgrade(to="v0.1.0")["direction"], "rollback")
        self.assertEqual(self.pin(), "v0.1.0")

    def test_a_big_upgrade_refuses_changes_nothing_and_journals_nothing(self):
        make_old(self.project)
        self.hgit("commit", "-qam", "an old project", cwd=self.project)
        before, journal = snapshot(self.project), Ledger(self.project).read_events()[0]
        with self.assertRaises(evolve.EvolveError) as raised:
            self.upgrade()
        message = str(raised.exception)
        self.assertIn("v0.1.0", message)
        self.assertIn("wayline upgrade --to v0.1.0", message)
        self.assertIn("new project", message)
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(Ledger(self.project).read_events()[0], journal)
        self.assertIn("v0.1.0", self.head_tags())

    def test_writing_verbs_refuse_an_old_project_with_the_same_message_and_status_still_reads(self):
        make_old(self.project)
        before = snapshot(self.project)
        messages = set()
        for verb in ("run", "tick", "pause", "answer", "objective", "mark", "reference"):
            with self.subTest(verb=verb):
                code, _, err = self.quietly(cli.main, [verb, "--project", str(self.project)])
                self.assertEqual(code, 1)
                self.assertIn("wayline upgrade --to v0.1.0", err)
                messages.add(err.split(": ", 1)[1])
        self.assertEqual(len(messages), 1, messages)
        self.assertEqual(snapshot(self.project), before)
        code, _, err = self.quietly(cli.main, ["status", "--project", str(self.project)])
        self.assertNotIn("wayline upgrade --to", err)

    def test_every_verb_is_either_refused_on_an_old_project_or_known_not_to_write_to_one(self):
        # A verb added later has to be put on one side: a verb that writes to a project and is missing from
        # `cli.WRITING_VERBS` would write into a project of another `research_version` unrefused.
        not_writing = {
            "init", "status", "serve", "upgrade",  # lay out a new project, read, list read-only, or take the way back
            "accept", "consult", "scout", "job", "launch",  # run inside a worktree the conductor launched, which `run` refuses
            "figures", "guidelines", "registry", "tools",  # write only to the harness or ~/.wayline/
        }
        verbs = {verb.name for verb in cli.VERBS}
        self.assertEqual(verbs - cli.WRITING_VERBS - not_writing, set(), "verbs on neither side")
        self.assertEqual(cli.WRITING_VERBS & not_writing, set())
        self.assertEqual(cli.WRITING_VERBS - verbs, set(), "refused names that are not verbs")


class OldProjectDashboardTest(ActionCase):
    def test_the_dashboard_lists_an_old_project_read_only_and_refuses_its_actions(self):
        make_old(self.project)
        listed = {entry["path"]: entry for entry in self.request("GET", "/api/projects").json["projects"]}
        entry = listed[str(self.project)]
        self.assertTrue(entry["read_only"])
        self.assertEqual(entry["research_version"], 1)
        self.assertIn("harness_tag", entry)
        refused = self.act("pause")
        self.assertEqual(refused.status, 400)
        self.assertIn("wayline upgrade --to", refused.json["error"])
        self.assertEqual([event for event in Ledger(self.project).read_events()[0] if event["event"] == "paused"], [])
        self.assertEqual(self.request("GET", "/api/projects/%s/outputs" % self.project.name).status, 200)

    def test_a_current_project_is_not_read_only(self):
        listed = self.request("GET", "/api/projects").json["projects"]
        self.assertFalse(any(entry["read_only"] for entry in listed))
