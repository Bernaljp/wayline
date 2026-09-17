"""The registry of skills and roles, and the librarian (Implementation Decisions 10).

Three things are checked here: the artifacts the harness ships (the five interactive skills, their
sidecars, and their fixture directories), the build that turns both scopes plus the journal into
`research/registry.json`, and the librarian step that assigns a role and skills to a ticket from it.
"""

import json
import os
import shutil
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import cli, registry
from wayline.frontmatter import load_document
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger

# The five interactive skills of Implementation Decisions 10, directory name to ticket-facing id.
INTERACTIVE = {
    "wayline-intake": "intake",
    "wayline-grill": "grill",
    "wayline-plan": "plan",
    "wayline-evolve": "evolve",
    "wayline-paper": "paper",
}

SIDECAR = """{"id": "%s", "capability_summary": "%s", "applicability_tags": {"kinds": %s},
              "cost_hint": "%s", "fixtures": %s}"""


def write_skill(directory, identifier, summary="does one thing", kinds=(), cost="small", fixtures=(), body=None):
    """A skill directory with a `SKILL.md` and a sidecar, as a project or the harness would hold it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        body if body is not None else "---\nname: %s\ndescription: %s\n---\n\n# %s\n" % (directory.name, summary, identifier),
        encoding="utf-8")
    (directory / "wayline.json").write_text(
        SIDECAR % (identifier, summary, json.dumps(list(kinds)), cost, json.dumps(list(fixtures))), encoding="utf-8")
    return directory


def write_fixture(root, identifier, baseline=None):
    """A fixture directory under `<root>/fixtures/<kind>/<slug>/`, optionally with a baseline."""
    directory = Path(root) / "fixtures" / identifier
    directory.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": 1, "id": identifier, "kind": identifier.split("/")[0], "structural": [], "baseline": baseline}
    (directory / "fixture.json").write_text(json.dumps(record), encoding="utf-8")
    return directory


class ShippedSkillsTest(unittest.TestCase):
    """The five interactive skills as the harness ships them, with sidecars and fixture directories."""

    def test_the_five_interactive_skills_exist_with_a_body_and_a_sidecar(self):
        for name, identifier in INTERACTIVE.items():
            with self.subTest(skill=name):
                directory = HARNESS_ROOT / "skills" / name
                frontmatter, body = load_document((directory / "SKILL.md").read_text(encoding="utf-8"))
                self.assertEqual(frontmatter["name"], name, "a skill's frontmatter name is its directory name")
                self.assertTrue(frontmatter["description"].strip())
                self.assertTrue(body.strip())
                sidecar = registry.read_sidecar(directory / "wayline.json", "skill", expect_id=identifier)
                self.assertEqual(sidecar["id"], identifier)
                self.assertTrue(sidecar["capability_summary"].strip())

    def test_every_shipped_sidecar_is_stamped_with_the_hash_of_its_files(self):
        """`stamp_sidecars` is what to run when this fails: the sidecar says what the body was."""
        stale = []
        for parent in ("skills", "roles"):
            for directory in sorted(path for path in (HARNESS_ROOT / parent).iterdir() if path.is_dir()):
                sidecar = directory / "wayline.json"
                if not sidecar.is_file():
                    continue
                declared = json.loads(sidecar.read_text(encoding="utf-8")).get("sha256")
                computed = registry.content_sha256(directory)
                if declared != computed:
                    stale.append("%s: sidecar says %s, files hash to %s" % (directory.name, declared, computed))
        self.assertEqual(stale, [], "run python3 -c 'from wayline.registry import stamp_sidecars; stamp_sidecars()'")

    def test_every_interactive_skill_has_a_fixture_with_structural_checks_only(self):
        for name in INTERACTIVE:
            with self.subTest(skill=name):
                record = json.loads((FIXTURES_DIR / "skill" / name / "fixture.json").read_text(encoding="utf-8"))
                self.assertEqual(record["id"], "skill/" + name)
                self.assertEqual(record["kind"], "skill")
                self.assertNotIn("judged", record, "a skill's judged layer arrives with the ticket that records its session")
                self.assertIsInstance(record["structural"], list)
                self.assertTrue((HARNESS_ROOT / record["subject"]["path"]).is_file())
                self.assertTrue((FIXTURES_DIR / "skill" / name / record["input"]["prompt"]).is_file())

    def test_every_skill_names_its_own_fixture(self):
        for name, identifier in INTERACTIVE.items():
            with self.subTest(skill=name):
                sidecar = registry.read_sidecar(HARNESS_ROOT / "skills" / name / "wayline.json", "skill", identifier)
                self.assertEqual(sidecar["fixtures"], ["skill/" + name])

    def test_the_coder_role_carries_the_registry_fields_and_the_four_a_role_adds(self):
        sidecar = registry.read_sidecar(HARNESS_ROOT / "roles" / "coder" / "wayline.json", "role", "coder")
        for field in registry.SIDECAR_FIELDS + registry.ROLE_FIELDS:
            self.assertIn(field, sidecar)
        self.assertEqual(sidecar["applicability_tags"]["kinds"], ["code", "docs", "harness"])
        self.assertEqual(sidecar["output_schema"], "result")


class SidecarTest(unittest.TestCase):
    """What `read_sidecar` accepts and what it refuses, on files written for the purpose."""

    def setUp(self):
        self.directory = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.path = self.directory / "wayline.json"

    def read(self, value, kind="skill", expect_id="thing"):
        self.path.write_text(json.dumps(value), encoding="utf-8")
        return registry.read_sidecar(self.path, kind, expect_id=expect_id)

    def test_a_short_sidecar_defaults_the_lists_and_the_cost_hint(self):
        sidecar = self.read({"id": "thing", "capability_summary": "does one thing"})
        self.assertEqual(sidecar["scope_kind"], "global")
        self.assertEqual(sidecar["cost_hint"], "medium")
        self.assertEqual(sidecar["fixtures"], [])
        self.assertEqual(sidecar["applicability_tags"], {"kinds": [], "data_types": [], "libraries": [], "venues": []})
        self.assertIsNone(sidecar["sha256"])

    def test_an_unknown_field_is_refused(self):
        with self.assertRaises(registry.RegistryError) as caught:
            self.read({"id": "thing", "capability_summary": "x", "capabilty_summary": "typo"})
        self.assertIn("capabilty_summary", str(caught.exception))

    def test_a_skill_may_not_carry_the_role_fields(self):
        with self.assertRaises(registry.RegistryError) as caught:
            self.read({"id": "thing", "capability_summary": "x", "allowed_tools": ["Read"]})
        self.assertIn("allowed_tools", str(caught.exception))

    def test_a_sidecar_naming_another_artifact_is_refused(self):
        with self.assertRaises(registry.RegistryError) as caught:
            self.read({"id": "other", "capability_summary": "x"})
        self.assertIn("other", str(caught.exception))

    def test_an_empty_capability_summary_is_refused(self):
        with self.assertRaises(registry.RegistryError):
            self.read({"id": "thing", "capability_summary": "  "})

    def test_a_kind_that_is_no_ticket_kind_is_refused(self):
        with self.assertRaises(registry.RegistryError) as caught:
            self.read({"id": "thing", "capability_summary": "x", "applicability_tags": {"kinds": ["refactor"]}})
        self.assertIn("refactor", str(caught.exception))

    def test_a_cost_hint_outside_the_three_is_refused(self):
        with self.assertRaises(registry.RegistryError):
            self.read({"id": "thing", "capability_summary": "x", "cost_hint": "free"})

    def test_a_fixture_id_without_a_kind_is_refused(self):
        with self.assertRaises(registry.RegistryError) as caught:
            self.read({"id": "thing", "capability_summary": "x", "fixtures": ["thing"]})
        self.assertIn("<kind>/<slug>", str(caught.exception))

    def test_a_sha256_that_is_not_a_digest_is_refused(self):
        with self.assertRaises(registry.RegistryError):
            self.read({"id": "thing", "capability_summary": "x", "sha256": "nope"})

    def test_a_missing_file_names_the_file_it_wanted(self):
        with self.assertRaises(registry.RegistryError) as caught:
            registry.read_sidecar(self.directory / "absent" / "wayline.json", "skill")
        self.assertIn("wayline.json", str(caught.exception))

    def test_the_hash_covers_the_files_and_not_the_sidecar(self):
        write_skill(self.directory / "wayline-thing", "thing")
        first = registry.content_sha256(self.directory / "wayline-thing")
        (self.directory / "wayline-thing" / "wayline.json").write_text('{"id": "thing", "capability_summary": "other"}', encoding="utf-8")
        self.assertEqual(registry.content_sha256(self.directory / "wayline-thing"), first)
        (self.directory / "wayline-thing" / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n\nchanged\n", encoding="utf-8")
        self.assertNotEqual(registry.content_sha256(self.directory / "wayline-thing"), first)


class BuildTest(ProjectTestCase):
    """`wayline registry build`: both scopes, the outcomes from the journal, and the written file."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        # The pre-check shells out; the builds here name a binary that is not there, so the note
        # path is what the suite exercises and no test depends on a `claude` being installed.
        previous = os.environ.get("WAYLINE_CLAUDE")
        os.environ["WAYLINE_CLAUDE"] = str(self.temp / "no-such-claude")
        self.addCleanup(lambda: os.environ.pop("WAYLINE_CLAUDE") if previous is None else os.environ.__setitem__("WAYLINE_CLAUDE", previous))

    def build(self, **options):
        return registry.build(self.project, **options)

    def entry(self, registry_value, kind, identifier):
        for entry in registry_value["entries"]:
            if entry["kind"] == kind and entry["id"] == identifier:
                return entry
        raise AssertionError("no %s %r in %s" % (kind, identifier, [e["id"] for e in registry_value["entries"]]))

    def local_skill(self, name, **options):
        return write_skill(self.project / ".claude" / "skills" / name, name.replace("wayline-", ""), **options)

    def test_the_registry_lists_the_five_interactive_skills_with_their_capability_summaries(self):
        built = self.build()
        for name, identifier in INTERACTIVE.items():
            with self.subTest(skill=identifier):
                entry = self.entry(built, "skill", identifier)
                self.assertEqual(entry["scope_kind"], "global")
                self.assertEqual(entry["path"], "skills/" + name)
                self.assertTrue(entry["capability_summary"].strip())
                self.assertTrue(entry["assignable"])

    def test_every_entry_validates_against_the_registry_entry_schema(self):
        schema = load_schema("registry_entry")
        for entry in self.build()["entries"]:
            with self.subTest(entry=entry["id"]):
                check(entry, schema, name=entry["id"])

    def test_the_build_writes_registry_json_through_the_ledger(self):
        built = self.build()
        written = json.loads((self.project / "research" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(written["entries"], built["entries"])
        self.assertEqual(registry.read_registry(self.project)["entries"], built["entries"])

    def test_the_outcome_record_comes_from_the_journal(self):
        built = self.build()
        coder = self.entry(built, "role", "coder")
        self.assertEqual(coder["outcome"]["assigned"], 1)
        self.assertEqual(coder["outcome"]["passed_first_time"], 1)
        self.assertEqual(coder["outcome"]["failed"], 0)
        self.assertEqual(coder["outcome"]["last_used"], "2026-09-11T11:00:02.000Z")

    def test_a_skill_the_journal_never_names_has_an_empty_outcome(self):
        self.assertEqual(self.entry(self.build(), "skill", "intake")["outcome"],
                         {"assigned": 0, "passed_first_time": 0, "failed": 0, "last_used": None})

    def test_a_local_skill_is_registered_under_the_project_scope(self):
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline={"structural": "2/2"})
        entry = self.entry(self.build(), "skill", "sweep")
        self.assertEqual(entry["scope_kind"], "local")
        self.assertEqual(entry["path"], ".claude/skills/wayline-sweep")
        self.assertTrue(entry["assignable"])

    def test_a_local_skill_without_a_fixture_is_not_assignable(self):
        self.local_skill("wayline-sweep", kinds=["experiment"])
        entry = self.entry(self.build(), "skill", "sweep")
        self.assertFalse(entry["assignable"])
        self.assertIn("names no fixture", " ".join(entry["problems"]))

    def test_a_local_skill_whose_fixture_never_ran_is_not_assignable(self):
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline=None)
        entry = self.entry(self.build(), "skill", "sweep")
        self.assertFalse(entry["assignable"])
        self.assertIn("never passed", " ".join(entry["problems"]))

    def test_a_local_skill_whose_fixture_failed_at_its_baseline_is_not_assignable(self):
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline={"structural": "1/3"})
        self.assertFalse(self.entry(self.build(), "skill", "sweep")["assignable"])

    def test_a_local_skill_whose_fixture_is_missing_is_not_assignable(self):
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        entry = self.entry(self.build(), "skill", "sweep")
        self.assertFalse(entry["assignable"])
        self.assertIn("is in none of", " ".join(entry["problems"]))

    def test_a_skill_directory_without_the_prefix_is_registered_but_unreachable(self):
        write_skill(self.project / ".claude" / "skills" / "sweep", "sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline={"structural": "1/1"})
        entry = self.entry(self.build(), "skill", "sweep")
        self.assertFalse(entry["assignable"])
        self.assertIn("/wayline-<skill>", " ".join(entry["problems"]))

    def test_a_broken_sidecar_is_listed_rather_than_raised(self):
        directory = self.project / ".claude" / "skills" / "wayline-broken"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("---\nname: wayline-broken\ndescription: x\n---\n\nbody\n", encoding="utf-8")
        (directory / "wayline.json").write_text("{not json", encoding="utf-8")
        entry = self.entry(self.build(), "skill", "broken")
        self.assertFalse(entry["assignable"])
        self.assertIn("not readable JSON", " ".join(entry["problems"]))

    def test_a_skill_symlinked_in_by_init_is_not_registered_twice(self):
        links = self.project / ".claude" / "skills"
        links.mkdir(parents=True, exist_ok=True)
        (links / "wayline-intake").symlink_to(HARNESS_ROOT / "skills" / "wayline-intake")
        entries = [entry for entry in self.build()["entries"] if entry["id"] == "intake"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["scope_kind"], "global")

    def test_a_relative_symlink_into_the_harness_is_not_a_local_skill_either(self):
        """A relative target is read against the link's directory, not the process's."""
        links = self.project / ".claude" / "skills"
        links.mkdir(parents=True, exist_ok=True)
        target = os.path.relpath(HARNESS_ROOT / "skills" / "wayline-plan", links)
        (links / "wayline-plan").symlink_to(target)
        entries = [entry for entry in self.build()["entries"] if entry["id"] == "plan"]
        self.assertEqual([entry["scope_kind"] for entry in entries], ["global"])

    def test_a_finding_on_a_local_skill_lands_on_the_local_entry(self):
        directory = self.local_skill("wayline-sweep", kinds=["experiment"])
        fake = self.temp / "fake-claude"
        report = {"success": True, "contents": [{
            "file": str(directory / "SKILL.md"), "type": "skill",
            "errors": [{"path": "frontmatter", "message": "the description is empty"}], "warnings": []}]}
        # The same report comes back for both scope roots; only the local entry's directory holds it.
        fake.write_text("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(report), encoding="utf-8")
        fake.chmod(0o755)
        os.environ["WAYLINE_CLAUDE"] = str(fake)
        built = self.build()
        self.assertIn("the description is empty", " ".join(self.entry(built, "skill", "sweep")["problems"]))
        self.assertNotIn("problems", self.entry(built, "skill", "intake"))

    def test_a_local_role_override_keeps_the_harness_role_s_kinds(self):
        agents = self.project / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "coder.md").write_text("---\nname: coder\ndescription: the project's own coder\n---\n\nWrite Fortran.\n", encoding="utf-8")
        entry = self.entry(self.build(), "role", "coder")
        self.assertEqual(entry["scope_kind"], "local")
        self.assertEqual(entry["path"], ".claude/agents/coder.md")
        self.assertEqual(entry["applicability_tags"]["kinds"], ["code", "docs", "harness"])
        self.assertTrue(entry["assignable"])

    def test_a_local_role_the_harness_does_not_have_cannot_be_launched(self):
        agents = self.project / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "scribe.md").write_text("---\nname: scribe\ndescription: judges\n---\n\nJudge.\n", encoding="utf-8")
        entry = self.entry(self.build(), "role", "scribe")
        self.assertFalse(entry["assignable"])
        self.assertIn("tool lists", " ".join(entry["problems"]))

    def test_a_missing_validator_is_one_note_and_not_a_failure(self):
        built = self.build()
        self.assertTrue(any("structural pre-check" in note for note in built["notes"]))
        self.assertTrue(self.entry(built, "skill", "intake")["assignable"])

    def test_the_validator_s_findings_are_notes_on_the_entry_and_never_a_veto(self):
        fake = self.temp / "fake-claude"
        report = {"success": True, "contents": [{
            "file": str(HARNESS_ROOT / "skills" / "wayline-intake" / "SKILL.md"), "type": "skill",
            "errors": [], "warnings": [{"path": "frontmatter", "message": "consider a shorter description"}]}]}
        fake.write_text("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(report), encoding="utf-8")
        fake.chmod(0o755)
        os.environ["WAYLINE_CLAUDE"] = str(fake)
        entry = self.entry(self.build(), "skill", "intake")
        self.assertTrue(entry["assignable"])
        self.assertIn("claude plugin validate", " ".join(entry["problems"]))

    def test_a_stale_sidecar_hash_is_reported_and_does_not_unassign_the_skill(self):
        """An unstamped sidecar says the sidecar was not restamped, not that the skill is broken.

        Anything that changes a skill's files without a restamp lands here: an edited body, a merge
        leaving a `.orig` beside it, an editor's backup file. None of them is a reason for the
        librarian to stop assigning a skill the launch path runs perfectly well.
        """
        directory = self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline={"structural": "1/1"})
        sidecar = json.loads((directory / "wayline.json").read_text(encoding="utf-8"))
        sidecar["sha256"] = "0" * 64
        (directory / "wayline.json").write_text(json.dumps(sidecar), encoding="utf-8")
        entry = self.entry(self.build(), "skill", "sweep")
        self.assertIn("the computed one is registered", " ".join(entry["problems"]))
        self.assertNotEqual(entry["sha256"], "0" * 64)
        self.assertTrue(entry["assignable"])

    def test_a_stray_file_beside_a_harness_skill_does_not_unassign_it(self):
        harness = self.temp / "harness"
        directory = write_skill(harness / "skills" / "wayline-thing", "thing", kinds=["code"])
        sidecar = json.loads((directory / "wayline.json").read_text(encoding="utf-8"))
        sidecar["sha256"] = registry.content_sha256(directory)
        (directory / "wayline.json").write_text(json.dumps(sidecar), encoding="utf-8")
        (directory / "SKILL.md.orig").write_text("a merge left this here\n", encoding="utf-8")
        built = registry.build(self.project, harness_root=harness, pre_check=False, write=False)
        entry = self.entry(built, "skill", "thing")
        self.assertTrue(entry["assignable"])
        self.assertIn("the computed one is registered", " ".join(entry["problems"]))

    def test_a_file_that_is_no_artifact_name_is_a_note_and_not_a_failed_build(self):
        """The registry is rebuilt at every planner launch, so a stray file must not stop it."""
        agents = self.project / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "README.md").write_text("notes on the role overrides\n", encoding="utf-8")
        write_skill(self.project / ".claude" / "skills" / "My_Skill", "sweep")
        built = self.build()
        self.assertEqual([entry["id"] for entry in built["entries"] if entry["id"] in ("README", "My_Skill")], [])
        notes = " ".join(built["notes"])
        self.assertIn("README.md is not a role name", notes)
        self.assertIn("My_Skill is not a skill name", notes)

    def test_an_unreadable_file_inside_a_skill_is_that_skill_s_problem(self):
        directory = self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline={"structural": "1/1"})
        (directory / "data.csv").symlink_to(self.temp / "gone.csv")
        built = self.build()
        entry = self.entry(built, "skill", "sweep")
        self.assertFalse(entry["assignable"])
        self.assertIn("data.csv cannot be read", " ".join(entry["problems"]))
        self.assertTrue(self.entry(built, "skill", "intake")["assignable"], "one broken skill is not the build")

    def test_a_baseline_that_records_no_result_is_not_a_pass(self):
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        for baseline in ({}, {"structural": None, "judged": None}, {"recorded_at": "2026-09-12T10:00:00.000Z"}):
            with self.subTest(baseline=baseline):
                write_fixture(self.project, "skill/sweep", baseline=baseline)
                entry = self.entry(self.build(), "skill", "sweep")
                self.assertFalse(entry["assignable"])
                self.assertIn("has no recorded baseline", " ".join(entry["problems"]))

    def test_a_judged_layer_that_did_not_sweep_is_not_a_pass(self):
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        write_fixture(self.project, "skill/sweep", baseline={"structural": "3/3", "judged": "2/3"})
        self.assertFalse(self.entry(self.build(), "skill", "sweep")["assignable"])

    def test_a_local_skill_whose_fixture_was_recorded_into_the_harness_tree_is_assignable(self):
        """Decision 12's fixture layout is the harness's tree, so the gate looks in both."""
        harness = self.temp / "harness"
        write_fixture(harness, "skill/sweep", baseline={"structural": "3/3"})
        self.local_skill("wayline-sweep", kinds=["experiment"], fixtures=["skill/sweep"])
        built = registry.build(self.project, harness_root=harness, pre_check=False, write=False)
        self.assertTrue(self.entry(built, "skill", "sweep")["assignable"])

    def test_a_local_role_override_is_summarised_by_its_own_description(self):
        agents = self.project / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "coder.md").write_text(
            "---\nname: coder\ndescription: writes Fortran and nothing else\n---\n\nWrite Fortran.\n", encoding="utf-8")
        entry = self.entry(self.build(), "role", "coder")
        self.assertEqual(entry["capability_summary"], "writes Fortran and nothing else")

    def test_a_local_role_override_without_a_readable_description_keeps_the_harness_one(self):
        agents = self.project / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "coder.md").write_text("no frontmatter at all\n", encoding="utf-8")
        entry = self.entry(self.build(), "role", "coder")
        self.assertIn("one code ticket", entry["capability_summary"])

    def test_a_build_without_a_project_reads_the_harness_alone(self):
        built = registry.build(project=None, pre_check=False, write=False)
        self.assertTrue(built["entries"])
        self.assertTrue(all(entry["scope_kind"] == "global" for entry in built["entries"]))


class OutcomeTest(unittest.TestCase):
    """The outcome record, from launch and close pairs in the journal."""

    @staticmethod
    def events(*rows):
        return [{"ts": ts, "event": event, "ticket": payload.get("ticket"), "session_id": None, "job": None, "payload": payload}
                for ts, event, payload in rows]

    def test_a_first_attempt_that_closes_counts_as_a_first_time_pass(self):
        records = registry.outcomes(self.events(
            ("2026-09-12T10:00:00Z", "ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "skills": ["sweep"]}),
            ("2026-09-12T10:30:00Z", "ticket_done", {"ticket": 1}),
        ))
        self.assertEqual(records[("role", "coder")], {"assigned": 1, "passed_first_time": 1, "failed": 0, "last_used": "2026-09-12T10:00:00Z"})
        self.assertEqual(records[("skill", "sweep")]["passed_first_time"], 1)

    def test_a_second_attempt_that_closes_is_not_a_first_time_pass(self):
        records = registry.outcomes(self.events(
            ("2026-09-12T10:00:00Z", "ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "skills": []}),
            ("2026-09-12T10:20:00Z", "ticket_failed", {"ticket": 1, "attempt": 1, "reason": "no", "next": "resume"}),
            ("2026-09-12T10:30:00Z", "ticket_launched", {"ticket": 1, "attempt": 2, "role": "coder", "skills": []}),
            ("2026-09-12T11:00:00Z", "ticket_done", {"ticket": 1}),
        ))
        self.assertEqual(records[("role", "coder")],
                         {"assigned": 2, "passed_first_time": 0, "failed": 1, "last_used": "2026-09-12T10:30:00Z"})

    def test_the_ladder_counts_one_failure_per_launch_and_a_resumed_close_is_no_first_time_pass(self):
        records = registry.outcomes(self.events(
            ("2026-09-12T10:00:00Z", "ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "skills": []}),
            ("2026-09-12T10:20:00Z", "ticket_failed", {"ticket": 1, "attempt": 1, "reason": "no", "next": "resume"}),
            ("2026-09-12T10:25:00Z", "ticket_failed", {"ticket": 1, "attempt": 1, "reason": "still no", "next": "tier_up"}),
            ("2026-09-12T10:30:00Z", "ticket_launched", {"ticket": 2, "attempt": 1, "role": "coder", "skills": []}),
            ("2026-09-12T10:40:00Z", "ticket_failed", {"ticket": 2, "attempt": 1, "reason": "no", "next": "resume"}),
            ("2026-09-12T11:00:00Z", "ticket_done", {"ticket": 2}),
        ))
        self.assertEqual(records[("role", "coder")],
                         {"assigned": 2, "passed_first_time": 0, "failed": 2, "last_used": "2026-09-12T10:30:00Z"})

    def test_a_relaunch_in_the_same_attempt_does_not_count_its_failure_twice(self):
        records = registry.outcomes(self.events(
            ("2026-09-12T10:00:00Z", "ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "skills": []}),
            ("2026-09-12T10:20:00Z", "ticket_failed", {"ticket": 1, "attempt": 1, "reason": "no", "next": "resume"}),
            ("2026-09-12T10:25:00Z", "ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "skills": []}),
            ("2026-09-12T10:30:00Z", "ticket_failed", {"ticket": 1, "attempt": 1, "reason": "no", "next": "tier_up"}),
        ))
        self.assertEqual(records[("role", "coder")]["failed"], 1)

    def test_a_close_is_attributed_to_what_the_latest_launch_named(self):
        records = registry.outcomes(self.events(
            ("2026-09-12T10:00:00Z", "ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "skills": ["first"]}),
            ("2026-09-12T10:10:00Z", "ticket_launched", {"ticket": 2, "attempt": 1, "role": "analyst", "skills": ["second"]}),
            ("2026-09-12T10:20:00Z", "ticket_done", {"ticket": 2}),
        ))
        self.assertEqual(records[("skill", "second")]["passed_first_time"], 1)
        self.assertEqual(records[("skill", "first")]["passed_first_time"], 0)

    def test_a_close_without_a_launch_is_ignored(self):
        self.assertEqual(registry.outcomes(self.events(("2026-09-12T10:00:00Z", "ticket_done", {"ticket": 7}))), {})

    def test_the_ledger_fixture_journal_reads_as_its_events_say(self):
        events, _ = Ledger(FIXTURES_DIR / "ledger").read_events()
        records = registry.outcomes(events)
        self.assertEqual(records[("role", "reader")], {"assigned": 2, "passed_first_time": 0, "failed": 2, "last_used": "2026-09-11T13:31:00.000Z"})
        self.assertEqual(records[("skill", "absorb")]["failed"], 2)
        self.assertEqual(records[("skill", "python-package")]["passed_first_time"], 1)


def entry(identifier, kind="skill", kinds=(), cost="small", outcome=None, assignable=True, tags=None, scope="global"):
    """One registry entry, spelled out, for the librarian tests."""
    applicability = {"kinds": list(kinds), "data_types": [], "libraries": [], "venues": []}
    applicability.update(tags or {})
    return {
        "id": identifier, "kind": kind, "scope_kind": scope, "path": "skills/" + identifier,
        "sha256": "0" * 64, "capability_summary": identifier, "applicability_tags": applicability,
        "cost_hint": cost, "fixtures": [], "assignable": assignable,
        "outcome": outcome or {"assigned": 0, "passed_first_time": 0, "failed": 0, "last_used": None},
    }


class LibrarianTest(unittest.TestCase):
    """The planner's step: one ticket and the registry in, a role and skills out."""

    @staticmethod
    def ticket(kind="code", identifier=3):
        return {"id": identifier, "kind": kind}

    def test_the_role_is_the_one_whose_kinds_cover_the_ticket(self):
        index = {"entries": [entry("coder", kind="role", kinds=["code", "docs"]),
                             entry("reader", kind="role", kinds=["dossier"])]}
        self.assertEqual(registry.librarian(self.ticket("code"), index)["role"], "coder")
        self.assertEqual(registry.librarian(self.ticket("dossier"), index)["role"], "reader")

    def test_a_kind_no_role_covers_is_a_note_and_not_a_guess(self):
        index = {"entries": [entry("coder", kind="role", kinds=["code"])]}
        assignment = registry.librarian(self.ticket("figure"), index)
        self.assertIsNone(assignment["role"])
        self.assertIn("no assignable role covers a figure ticket", " ".join(assignment["notes"]))

    def test_an_entry_that_is_not_assignable_is_never_assigned(self):
        index = {"entries": [entry("coder", kind="role", kinds=["code"], assignable=False),
                             entry("sweep", kinds=["code"], assignable=False)]}
        assignment = registry.librarian(self.ticket("code"), index)
        self.assertIsNone(assignment["role"])
        self.assertEqual(assignment["skills"], [])

    def test_skills_are_the_ones_whose_kinds_match(self):
        index = {"entries": [entry("sweep", kinds=["experiment"]), entry("notes", kinds=["code", "docs"])]}
        self.assertEqual(registry.librarian(self.ticket("code"), index)["skills"], ["notes"])
        self.assertEqual(registry.librarian(self.ticket("experiment"), index)["skills"], ["sweep"])

    def test_a_phase_skill_with_no_kinds_is_never_assigned_to_a_ticket(self):
        index = {"entries": [entry("intake"), entry("plan")]}
        self.assertEqual(registry.librarian(self.ticket("code"), index)["skills"], [])

    def test_a_skill_that_names_a_library_wants_the_ticket_to_use_it(self):
        index = {"entries": [entry("torch-sweep", kinds=["experiment"], tags={"libraries": ["torch"]}),
                             entry("any-sweep", kinds=["experiment"])]}
        self.assertEqual(registry.librarian(self.ticket("experiment"), index)["skills"], ["any-sweep"])
        matched = registry.librarian(self.ticket("experiment"), index, tags={"libraries": ["torch"]})
        self.assertEqual(matched["skills"], ["torch-sweep", "any-sweep"], "a tag match sorts first")

    def test_a_record_of_first_time_passes_beats_no_record_which_beats_failures(self):
        good = {"assigned": 4, "passed_first_time": 3, "failed": 1, "last_used": "2026-09-12T10:00:00Z"}
        bad = {"assigned": 4, "passed_first_time": 0, "failed": 4, "last_used": "2026-09-12T10:00:00Z"}
        index = {"entries": [entry("untried", kinds=["code"]),
                             entry("failing", kinds=["code"], outcome=bad),
                             entry("proven", kinds=["code"], outcome=good)]}
        self.assertEqual(registry.librarian(self.ticket("code"), index)["skills"], ["proven", "untried", "failing"])

    def test_the_cheaper_skill_comes_first_when_the_records_agree(self):
        index = {"entries": [entry("large-one", kinds=["code"], cost="large"),
                             entry("small-one", kinds=["code"], cost="small")]}
        self.assertEqual(registry.librarian(self.ticket("code"), index)["skills"], ["small-one", "large-one"])

    def test_an_empty_registry_assigns_nothing_and_says_so(self):
        assignment = registry.librarian(self.ticket("code"), {"entries": []})
        self.assertIsNone(assignment["role"])
        self.assertEqual(assignment["skills"], [])
        self.assertTrue(assignment["notes"])


class AssignTest(ProjectTestCase):
    """`assign` journals what the librarian returned, which is what the next build's outcomes read."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()

    def test_the_assignment_is_journaled_as_assigned(self):
        ledger = Ledger(self.project)
        index = {"entries": [entry("coder", kind="role", kinds=["code"]), entry("notes", kinds=["code"])]}
        before, _ = ledger.read_events()
        assignment = registry.assign({"id": 12, "kind": "code"}, index, ledger=ledger)
        after, _ = ledger.read_events()
        self.assertEqual(assignment, {"role": "coder", "skills": ["notes"], "notes": []})
        written = after[len(before):]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["event"], "assigned")
        self.assertEqual(written[0]["ticket"], 12)
        self.assertEqual(written[0]["payload"], {"ticket": 12, "role": "coder", "skills": ["notes"]})
        check(written[0], load_schema("journal_event"), name="assigned")

    def test_an_assignment_without_a_ledger_journals_nothing(self):
        ledger = Ledger(self.project)
        before, _ = ledger.read_events()
        registry.assign({"id": 12, "kind": "code"}, {"entries": []})
        after, _ = ledger.read_events()
        self.assertEqual(len(after), len(before))

    def test_a_role_the_librarian_could_not_find_is_journaled_as_null(self):
        ledger = Ledger(self.project)
        registry.assign({"id": 13, "kind": "figure"}, {"entries": []}, ledger=ledger)
        events, _ = ledger.read_events()
        self.assertEqual(events[-1]["payload"], {"ticket": 13, "role": None, "skills": []})


class VerbTest(ProjectTestCase):
    """`wayline registry build` from the command line."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        previous = os.environ.get("WAYLINE_CLAUDE")
        os.environ["WAYLINE_CLAUDE"] = str(self.temp / "no-such-claude")
        self.addCleanup(lambda: os.environ.pop("WAYLINE_CLAUDE") if previous is None else os.environ.__setitem__("WAYLINE_CLAUDE", previous))

    def test_the_verb_is_wired(self):
        self.assertIsNotNone(cli.lookup("registry").handler)

    def test_build_prints_the_entries_and_writes_the_file(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["registry", "build", "--project", str(self.project)])
        self.assertEqual(code, 0)
        for identifier in INTERACTIVE.values():
            self.assertIn(identifier, out.getvalue())
        self.assertTrue((self.project / "research" / "registry.json").is_file())

    def test_build_json_prints_the_registry(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["registry", "build", "--project", str(self.project), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["entries"], registry.read_registry(self.project)["entries"])

    def test_an_unknown_action_is_a_usage_error(self):
        from contextlib import redirect_stderr
        from io import StringIO
        with redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["registry", "rebuild"]), 2)


class SymlinkRefresherTest(ProjectTestCase):
    """The one refresher `init` uses and `upgrade` will: relink what is there, drop what is not."""

    def setUp(self):
        super().setUp()
        from wayline.project import init_project
        self.harness = self.fake_harness()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=self.harness, git=False, hermes_python=None, owner_email=None)

    def refresh(self):
        from wayline.project import refresh_symlinks
        return refresh_symlinks(self.project, self.harness)

    def test_a_second_refresh_changes_nothing(self):
        self.assertEqual(self.refresh(), ([], []))

    def test_a_skill_added_to_the_harness_is_linked_in(self):
        write_skill(self.harness / "skills" / "wayline-new", "new")
        changes, _ = self.refresh()
        self.assertIn(".claude/skills/wayline-new", changes)
        self.assertTrue((self.project / ".claude" / "skills" / "wayline-new").is_symlink())

    def test_a_link_to_a_skill_the_harness_no_longer_has_is_removed(self):
        shutil.rmtree(self.harness / "skills" / "wayline-absorb")
        changes, _ = self.refresh()
        self.assertIn("removed .claude/skills/wayline-absorb", changes)
        self.assertFalse((self.project / ".claude" / "skills" / "wayline-absorb").exists())

    def test_a_link_into_another_harness_checkout_is_replaced(self):
        link = self.project / ".claude" / "skills" / "wayline-absorb"
        link.unlink()
        link.symlink_to(self.temp / "elsewhere" / "wayline-absorb")
        changes, _ = self.refresh()
        self.assertIn(".claude/skills/wayline-absorb", changes)
        self.assertEqual(os.readlink(link), str(self.harness / "skills" / "wayline-absorb"))

    def test_a_local_skill_of_the_project_is_left_alone(self):
        local = write_skill(self.project / ".claude" / "skills" / "wayline-absorb-local", "absorb-local")
        self.refresh()
        self.assertTrue((local / "SKILL.md").is_file())
        self.assertFalse(local.is_symlink())

    def test_a_real_directory_where_a_harness_skill_belongs_is_reported_not_replaced(self):
        link = self.project / ".claude" / "skills" / "wayline-absorb"
        link.unlink()
        write_skill(link, "absorb")
        changes, notes = self.refresh()
        self.assertEqual(changes, [])
        self.assertIn("wayline-absorb is not a symlink", " ".join(notes))


class RegistryVocabularyTest(unittest.TestCase):
    """The registry's own words come from the spec and the schemas, not from a second copy."""

    def test_the_ticket_kinds_come_from_the_ticket_schema(self):
        self.assertEqual(registry.ticket_kinds(), tuple(load_schema("ticket")["$defs"]["kind"]["enum"]))

    def test_the_entry_schema_and_the_module_agree_on_the_enumerations(self):
        schema = load_schema("registry_entry")
        self.assertEqual(tuple(schema["properties"]["cost_hint"]["enum"]), registry.COST_HINTS)
        self.assertEqual(tuple(schema["properties"]["scope_kind"]["enum"]), registry.SCOPE_KINDS)
        self.assertEqual(tuple(schema["properties"]["applicability_tags"]["required"]), registry.TAG_DIMENSIONS)

    def test_an_entry_missing_a_required_field_is_refused_by_the_schema(self):
        broken = entry("thing")
        del broken["sha256"]
        with self.assertRaises(ValidationError):
            check(broken, load_schema("registry_entry"), name="thing")


if __name__ == "__main__":
    unittest.main()
