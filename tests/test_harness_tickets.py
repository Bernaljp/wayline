"""Harness tickets through the conductor, the proof, and the retrospective (ticket 45; Implementation Decisions 12).

A local change and a global change are each carried end to end with the fake launcher: the evolver's list, the
harness ticket, the worker's patch, the fixture run on the old subject and on the change, and what the owner
finds afterwards: the skill on the project's `main` and assignable, or the branch `evolve/<id>` of a stand-in
harness repository, checked, waiting, and tagged once merged. Nothing here reaches a model or the real harness
repository.
"""

import json
import shutil
import subprocess

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_changes import GLOBAL, answer, events_of, record
from tests.test_conductor import done, drive, hold_the_ladder
from tests.test_fixtures import Harness, good
from wayline import changes, fixtures, project, registry, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.tickets import read_tickets
from wayline.worker import Patch

IDENTITY = ["-c", "user.name=wayline test", "-c", "user.email=test@wayline.invalid"]
SKILL = ".claude/skills/wayline-caption-claims"
SKILL_FIXTURE = "skill/wayline-caption-claims"
SUBJECT_ROLE = "captioner"
SCHEMA = {"type": "object", "required": ["word"], "additionalProperties": False, "properties": {"word": {"type": "string"}}}
PLANNER_PROMPT = "prompts/roles/planner.md"
SMALLER = "Cut tickets smaller: no ticket should need more than one attempt.\n"


def fixture_files(identifier, subject, pinned=None):
    """The files of one hand-written fixture, as a worker's patch carries them: one structural check, no judged layer."""
    kind, slug = identifier.split("/")
    base = "fixtures/%s/%s/" % (kind, slug)
    prompt = "# The task\n\nWrite the caption.\n" + ("\n" + pinned if pinned else "") + "\nReturn the structured result.\n"
    value = {
        "schema_version": 1, "id": identifier, "kind": kind, "subject": {"path": subject, "sha256": None, "also": []},
        "origin": {"project": None, "ticket": None, "session_id": None, "journal_ts": None, "change_record": None, "reason": "born from feedback"},
        "launch": {"role": SUBJECT_ROLE, "model": "sonnet", "effort": "low", "permission_mode": "dontAsk", "output_format": "stream-json",
                   "json_schema": "input/schema.json", "allowed_tools": ["Read"], "disallowed_tools": ["WebFetch"],
                   "add_dirs": ["{project}"], "env": {"WAYLINE_PROJECT": "{project}", "WAYLINE_RUN": "{run}"}, "settings": None},
        "input": {"prompt": "input/prompt.md", "agent": "input/agent.json", "context_manifest": None, "input_hash": None},
        "structural": [{"check": "schema_valid"}, {"check": "path_in", "path": "$.word", "values": ["hedged"]}],
        "baseline": None, "quarantine": {"status": "active", "flake_limit": 2, "flakes": [], "stable_runs_to_restore": 3},
    }
    files = {
        base + "fixture.json": json.dumps(value, indent=2) + "\n",
        base + "input/prompt.md": prompt,
        base + "input/agent.json": json.dumps({SUBJECT_ROLE: {"description": "Writes captions.", "prompt": "You write captions.", "permissionMode": "dontAsk"}}),
        base + "input/schema.json": json.dumps(SCHEMA),
    }
    if pinned:
        files[base + "input/subject/" + subject] = pinned
    return files


def skill_files():
    sidecar = {"id": "caption-claims", "scope_kind": "local", "capability_summary": "Holds a figure caption to what its table shows.",
               "applicability_tags": {"kinds": ["figure"], "data_types": [], "libraries": [], "venues": []}, "cost_hint": "small",
               "fixtures": [SKILL_FIXTURE], "sha256": "0" * 64}
    files = {SKILL + "/SKILL.md": "---\nname: wayline-caption-claims\ndescription: Holds a caption to its table.\n---\n\nClaim only what the table shows.\n",
             SKILL + "/wayline.json": json.dumps(sidecar, indent=2) + "\n"}
    files.update(fixture_files(SKILL_FIXTURE, SKILL + "/SKILL.md"))
    return files


def word(value):
    return worker.Envelope(structured_output={"word": value}, num_turns=2)


class ProofTest(Harness):
    """Criterion 7: the runner shows the fixture failing on the old subject and passing on the change."""

    def setUp(self):
        super().setUp()
        self.old = self.temp / "old"
        (self.old / "prompts").mkdir(parents=True)
        (self.old / "prompts" / "greeting.md").write_text("Greet nobody.\n", encoding="utf-8")
        self.directory = self.make_fixture(judged=False)
        self.fake = self.enterContext(worker.use_fake())

    def answer_by_subject(self, times=6):
        for _ in range(times):
            self.fake.script(respond=lambda request, message: good() if "list whom you greeted" in request.prompt else good(word="bye"))

    def test_a_fixture_that_fails_on_the_old_subject_and_passes_on_the_new_proves_the_change(self):
        self.answer_by_subject()
        proof = changes.prove("prompt/greeting", self.old, self.root, self.policy)
        self.assertTrue(proof.proven, proof.problem)
        self.assertIn("structural 3/3", proof.new)
        self.assertIn("structural 0/3", proof.old)
        baseline = self.record_of()["baseline"]
        self.assertEqual((baseline["passed"], baseline["structural"]), (True, "3/3"))
        self.assertEqual(baseline["subject_sha256"], fixtures.subject_sha256(self.record_of(), self.root))
        self.assertFalse((self.directory / "runs").exists(), "both runs happen on a copy")

    def test_a_fixture_that_passes_on_both_proves_nothing(self):
        for _ in range(6):
            self.fake.script(good())
        proof = changes.prove("prompt/greeting", self.old, self.root, self.policy)
        self.assertFalse(proof.proven)
        self.assertIn("does not encode the desired behaviour", proof.problem)
        self.assertIsNone(self.record_of()["baseline"], "a change that is not proven leaves its fixture as the worker left it")

    def test_a_fixture_that_fails_on_the_change_is_said_before_the_old_subject_is_run(self):
        for _ in range(3):
            self.fake.script(good(word="bye"))
        proof = changes.prove("prompt/greeting", self.old, self.root, self.policy)
        self.assertIn("does not pass on the change", proof.problem)
        self.assertEqual(len(self.fake.calls), 3)

    def test_a_subject_the_old_tree_does_not_hold_fails_there(self):
        (self.old / "prompts" / "greeting.md").unlink()
        self.answer_by_subject(3)
        self.assertTrue(changes.prove("prompt/greeting", self.old, self.root, self.policy).proven)

    def test_a_change_without_its_fixture_is_refused(self):
        self.assertIn("ships no fixture", changes.prove("prompt/nothing-here", self.old, self.root, self.policy).problem)


class LocalChangeTest(ProjectTestCase):
    """Criteria 3, 4, and 8: a local change through the conductor, applied at once and used from the next wave."""

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "study").resolve()
        project.init_project(self.project, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)
        self.fake = self.enterContext(worker.use_fake())
        hold_the_ladder(self)
        changes.file_feedback(self.project, "captions overclaim", source="dashboard")

    def conductor(self):
        driven = Conductor(self.project, out=open("/dev/null", "w"))
        self.addCleanup(driven.out.close)
        driven.plan_pre_check = False
        return driven

    def script_the_change(self, files=None):
        self.fake.script(answer(record()), role=changes.EVOLVER)
        self.fake.script(done(1, outputs_written=[SKILL + "/SKILL.md"]), patch=Patch(files=files or skill_files(), message="ticket 1: the caption skill"),
                         role="coder")

    def git(self, *args):
        done_process = subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True)
        self.assertEqual(done_process.returncode, 0, done_process.stderr)
        return done_process.stdout.strip()

    def test_feedback_filed_during_a_run_becomes_a_skill_the_librarian_assigns(self):
        self.script_the_change()
        for _ in range(3):
            self.fake.script(word("hedged"), role=SUBJECT_ROLE)
        driven = self.conductor()
        results = drive(driven)
        self.assertEqual([identifier for result in results for identifier in result.done], [1])
        names = [event["event"] for event in self.ledger.read_events()[0]]
        self.assertLess(names.index("change_record"), names.index("ticket_launched"), "the evolver ran in the wave that launched its ticket")
        self.assertIn("integrated", names)
        kept = changes.read_changes(self.project)[0]
        self.assertEqual(kept["status"], "applied")
        self.assertIn("structural 3/3", kept["proof"]["new"])
        self.assertTrue((self.project / SKILL / "SKILL.md").is_file(), "the skill is on the project's main")
        baseline = json.loads((self.project / "fixtures" / SKILL_FIXTURE / "fixture.json").read_text(encoding="utf-8"))["baseline"]
        self.assertTrue(baseline["passed"])
        self.assertEqual(self.git("status", "--porcelain", "--", "fixtures", ".claude"), "", "the baseline is committed with the change")

        index = registry.build(self.project, pre_check=False)
        entry = {found["id"]: found for found in index["entries"] if found["scope_kind"] == "local"}["caption-claims"]
        self.assertTrue(entry["assignable"], entry["problems"])
        assignment = registry.assign({"id": 9, "kind": "figure"}, index, ledger=self.ledger)
        self.assertIn("caption-claims", assignment["skills"])
        self.assertIn("caption-claims", events_of(self.ledger, "assigned")[-1]["payload"]["skills"], "the journal shows the librarian assigning it")

    def test_a_skill_whose_fixture_never_passed_is_not_assignable(self):
        files = skill_files()
        directory = self.project / SKILL
        for path, text in files.items():
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        entry = {found["id"]: found for found in registry.build(self.project, pre_check=False)["entries"]
                 if found["scope_kind"] == "local"}["caption-claims"]
        self.assertTrue(directory.is_dir())
        self.assertFalse(entry["assignable"])
        self.assertTrue(any("has no recorded baseline" in problem for problem in entry["problems"]), entry["problems"])

    def test_a_fixture_that_passes_on_the_old_subject_fails_the_ticket(self):
        self.script_the_change()
        driven = self.conductor()
        driven.prover = lambda fixture, old, new, policy: changes.Proof(fixture, old="structural 3/3", new="structural 3/3",
                                                                       problem="the fixture passes on the subject as it was")
        drive(driven)
        failed = events_of(self.ledger, "ticket_failed")
        self.assertIn("passes on the subject as it was", failed[0]["payload"]["reason"])
        self.assertNotIn("integrated", [event["event"] for event in self.ledger.read_events()[0]])
        self.assertEqual(changes.read_changes(self.project)[0]["status"], "open")

    def test_a_proof_stopped_for_cost_is_carried_again(self):
        self.script_the_change()
        driven = self.conductor()
        answers = [changes.Proof(SKILL_FIXTURE, waits=True), changes.Proof(SKILL_FIXTURE, old="structural 0/3", new="structural 3/3")]
        driven.prover = lambda fixture, old, new, policy: answers.pop(0)
        results = drive(driven)
        self.assertEqual(answers, [], "the proof that waited was run again by a later wave")
        self.assertEqual([len(result.done) for result in results if result.done], [1], "and the ticket closed once")
        self.assertEqual(events_of(self.ledger, "ticket_failed"), [], "a stop for cost is not a failure")
        self.assertEqual(read_tickets(self.project)[0]["status"], "done")

    def test_the_conductor_rereads_harness_json_every_wave(self):
        driven = self.conductor()
        driven.evolver = lambda fall_back: self.fail("no feedback is pending in this test")
        changes.mark_read(self.ledger, {"001-captions-overclaim": {"records": [], "dismissed": "test"}})
        driven.wave()
        before = driven.policy["max_parallel_workers"]
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["policy"] = {"max_parallel_workers": before + 3}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        driven.wave()
        self.assertEqual(driven.policy["max_parallel_workers"], before + 3)
        harness["policy"] = {"tiers": []}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        driven.wave()
        self.assertEqual(driven.policy["max_parallel_workers"], before + 3, "a policy the schema refuses leaves the last good one standing")

    def test_a_policy_handed_in_is_never_reread(self):
        policy = project.policy_for(self.project)
        driven = Conductor(self.project, policy=policy, out=open("/dev/null", "w"))
        self.addCleanup(driven.out.close)
        driven._reread_policy()
        self.assertIs(driven.policy, policy)

    def test_a_list_refused_twice_is_said_and_not_launched_again(self):
        bad = record(target="/etc/passwd")
        self.fake.script(answer(bad), role=changes.EVOLVER)
        self.fake.script(answer(bad), role=changes.EVOLVER)
        driven = self.conductor()
        driven.wave()
        driven.wave()
        self.assertEqual(len([call for call in self.fake.calls if call.request.role == changes.EVOLVER]), 2, "one launch and its one return")
        self.assertIn("refused", changes.read_state(self.ledger)["read"]["001-captions-overclaim"]["dismissed"])


class GlobalChangeTest(ProjectTestCase):
    """Criteria 3, 5, and 8: a global change works on `evolve/<id>` in the harness repository and waits for the owner."""

    def setUp(self):
        super().setUp()
        self.harness = self.temp / "harness"
        for name in ("roles", "prompts", "hooks", "schemas", "skills", "templates", "figures", "workflows"):
            shutil.copytree(HARNESS_ROOT / name, self.harness / name)
        shutil.copy(HARNESS_ROOT / "policy.json", self.harness / "policy.json")
        (self.harness / "wayline").mkdir()
        (self.harness / "wayline" / "__init__.py").write_text('__version__ = "0.1.0"\nTAG = "v" + __version__\n', encoding="utf-8")
        (self.harness / "CHANGELOG.md").write_text("# Changelog\n\n## v0.1.0 (2026-09-01)\n\nThe first tag.\n", encoding="utf-8")
        self.hgit("init", "-q", "-b", "main")
        self.hgit("add", "-A")
        self.hgit("commit", "-q", "-m", "release v0.1.0")
        self.hgit("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.project = (self.temp / "study").resolve()
        project.init_project(self.project, harness_root=self.harness, harness_tag="v0.1.0", hermes_python=None, owner_email=None)
        project.set_autonomy(self.project, "checkpoints")
        self.ledger = Ledger(self.project)
        self.fake = self.enterContext(worker.use_fake())
        hold_the_ladder(self)
        changes.file_feedback(self.project, "tickets too big", source="dashboard")
        self.planner_prompt = (self.harness / PLANNER_PROMPT).read_text(encoding="utf-8")

    def hgit(self, *args, cwd=None):
        done_process = subprocess.run(["git", "-C", str(cwd or self.harness), *IDENTITY, *args], capture_output=True, text=True)
        self.assertEqual(done_process.returncode, 0, done_process.stderr)
        return done_process.stdout.strip()

    def conductor(self, exit_codes=(0, 0)):
        driven = Conductor(self.project, harness_root=self.harness, out=open("/dev/null", "w"))
        self.addCleanup(driven.out.close)
        driven.plan_pre_check = False
        self.checked = []
        codes = list(exit_codes)

        def run(argv, cwd):
            self.checked.append((argv[1:4], str(cwd)))
            return codes.pop(0), "ran %s\nOK" % " ".join(argv[1:3])

        driven.global_checks = run
        return driven

    def script_the_change(self):
        changed = self.planner_prompt + "\n" + SMALLER
        files = {PLANNER_PROMPT: changed}
        files.update(fixture_files("role/planner-small-tickets", PLANNER_PROMPT, pinned=changed))
        self.fake.script(answer(record(feedback="001-tickets-too-big", **GLOBAL)), role=changes.EVOLVER)
        self.fake.script(done(1, outputs_written=[PLANNER_PROMPT]), patch=Patch(files=files, message="ticket 1: smaller tickets"), role="coder")
        for _ in range(6):
            self.fake.script(respond=lambda request, message: word("hedged" if SMALLER.strip() in request.prompt else "bold"), role=SUBJECT_ROLE)

    def test_it_is_checked_on_its_branch_and_waits_for_the_owner_who_merges_and_tags(self):
        self.script_the_change()
        driven = self.conductor()
        results = drive(driven)
        self.assertEqual([identifier for result in results for identifier in result.done], [1])
        kept = changes.read_changes(self.project)[0]
        branch = "evolve/" + kept["id"]
        self.assertEqual((kept["status"], kept["branch"]), ("awaiting_owner", branch))
        self.assertEqual([item["name"] for item in kept["checks"]], ["tests", "fixtures"])
        self.assertEqual([argv for argv, _ in self.checked], [["-m", "unittest"], ["-m", "wayline", "fixture"]])
        self.assertTrue(all(cwd == kept["worktree"] for _, cwd in self.checked), "both ran in the branch's worktree")
        self.assertIn("structural 0/3", kept["proof"]["old"])
        names = [event["event"] for event in self.ledger.read_events()[0]]
        self.assertIn("ticket_done", names)
        self.assertNotIn("integrated", names, "nothing is integrated into the project")
        self.assertEqual(self.hgit("show", "main:" + PLANNER_PROMPT), self.planner_prompt.strip(), "the harness main is untouched")
        self.assertIn(SMALLER.strip(), self.hgit("show", branch + ":" + PLANNER_PROMPT))
        self.assertIn(kept["id"], self.hgit("show", branch + ":CHANGELOG.md"))
        self.assertIn("waits for the owner", (self.project / "research" / "tickets" / "01-tell-the-planner-to-cut-smaller-tickets.md").read_text(encoding="utf-8"))
        self.assertTrue(any(kept["id"] in line and "waits for the owner's merge" in line for line in changes.proposal_lines(self.project)))

        self.assertEqual(changes.settle_global(self.project, self.harness)["tagged"], [])
        self.hgit("merge", "-q", "--no-ff", "-m", "Merge " + branch, branch)
        settled = changes.settle_global(self.project, self.harness)
        self.assertEqual(settled["tagged"], ["%s: v0.2.0" % kept["id"]])
        self.assertEqual(changes.read_changes(self.project)[0]["status"], "applied")
        self.assertEqual(events_of(self.ledger, "tagged")[-1]["payload"], {"tag": "v0.2.0"})
        self.assertIn("v0.2.0", self.hgit("tag", "--points-at", "main"))
        self.assertNotIn(branch, self.hgit("branch", "--list", branch))

    def test_a_failing_suite_fails_the_ticket_and_leaves_the_branch(self):
        self.script_the_change()
        driven = self.conductor(exit_codes=(0, 1))
        drive(driven)
        failed = events_of(self.ledger, "ticket_failed")
        self.assertIn("fixtures failed (exit 1)", failed[0]["payload"]["reason"])
        kept = changes.read_changes(self.project)[0]
        self.assertEqual(kept["status"], "open")
        self.assertEqual([item["exit_code"] for item in kept["checks"]], [0, 1])


class RetrospectiveTest(ProjectTestCase):
    """Criterion 1: after every `run_ended`, a retrospective over the journal, filed for the evolver when it earns one."""

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "study").resolve()
        project.init_project(self.project, git=False, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)
        self.fake = self.enterContext(worker.use_fake())

    def a_bad_run(self, ticket=4):
        for attempt in (1, 2):
            self.ledger.append_event("ticket_launched", {"ticket": ticket, "attempt": attempt, "role": "coder", "skills": []}, ticket=ticket)
            self.ledger.append_event("ticket_result", {"ticket": ticket, "attempt": attempt, "turns": 30, "status": "done"}, ticket=ticket)
        self.ledger.append_event("ticket_failed", {"ticket": ticket, "attempt": 1, "reason": "the acceptance failed", "next": "tier_up"}, ticket=ticket)
        self.ledger.append_event("stall", {"waves": 3, "action": "replan"})
        self.ledger.append_event("ticket_done", {"ticket": ticket}, ticket=ticket)
        self.ledger.append_event("run_ended", {"reason": "frontier_empty"})

    def test_it_reads_failures_escalations_stalls_rework_and_turns(self):
        self.a_bad_run()
        retro = changes.retrospective(self.project, pre_check=False)
        self.assertEqual(len(retro["failures"]), 1)
        self.assertIn("escalated to `tier_up`", retro["escalations"][0])
        self.assertEqual(len(retro["stalls"]), 1)
        self.assertIn("ticket 4 took 2 attempts", retro["rework"])
        self.assertEqual(retro["turns"], {4: 60})
        self.assertTrue(changes.notable(retro))
        text = changes.render_retrospective(retro)
        for heading in ("## Failures", "## Escalations", "## Stalls", "## Rework", "## Turns per closed ticket",
                        "## Skills below the registry's median first-time pass rate"):
            self.assertIn(heading, text)

    def test_skills_below_the_median_first_time_pass_rate_are_named(self):
        def entry(identifier, assigned, passed):
            return {"id": identifier, "kind": "skill", "scope_kind": "global",
                    "outcome": {"assigned": assigned, "passed_first_time": passed, "failed": assigned - passed, "last_used": None}}

        index = {"entries": [entry("sweep", 4, 4), entry("plots", 4, 3), entry("captions", 4, 1), entry("untried", 0, 0)]}
        retro = changes.retrospective(self.project, index=index)
        self.assertEqual(len(retro["poor_skills"]), 1)
        self.assertIn("`captions` passed first time on 25%", retro["poor_skills"][0])

    def test_it_is_filed_once_as_feedback_the_evolver_reads(self):
        self.a_bad_run()
        item = changes.file_retrospective(self.project, pre_check=False)
        self.assertTrue(item["id"].startswith("retro-"))
        self.assertEqual(events_of(self.ledger, "feedback")[-1]["payload"], {"id": item["id"], "source": "retrospective"})
        self.assertEqual([found["id"] for found in changes.pending_feedback(self.project)], [item["id"]])
        self.assertIsNone(changes.file_retrospective(self.project, pre_check=False), "nothing happened since the last one")

    def test_a_quiet_run_and_a_run_of_harness_tickets_earn_none(self):
        self.ledger.append_event("ticket_launched", {"ticket": 1, "attempt": 1}, ticket=1)
        self.ledger.append_event("ticket_done", {"ticket": 1}, ticket=1)
        self.ledger.append_event("run_ended", {"reason": "frontier_empty"})
        self.assertIsNone(changes.file_retrospective(self.project, pre_check=False), "nothing went badly")
        changes.file_feedback(self.project, "captions overclaim", source="cli")
        self.fake.script(answer(record()), role=changes.EVOLVER)
        changes.evolve(self.project, pre_check=False, fall_back=False)
        ticket = read_tickets(self.project)[0]["id"]
        self.a_bad_run(ticket)
        self.assertIsNone(changes.file_retrospective(self.project, pre_check=False), "or the loop would feed itself")

    def test_after_a_run_the_retrospective_is_filed_and_the_evolver_reads_it(self):
        self.a_bad_run()
        said = []
        self.fake.script(respond=lambda request, message: answer(dismissed=[
            {"feedback": changes.pending_feedback(self.project)[0]["id"], "reason": "One bad ticket is not a pattern."}]), role=changes.EVOLVER)
        report = changes.after_run(self.project, "frontier_empty", say=said.append, pre_check=False)
        self.assertTrue(report["launched"])
        self.assertIn("# Retrospective", self.fake.calls[0].request.prompt)
        self.assertEqual(changes.pending_feedback(self.project), [])

    def test_a_run_the_owner_stopped_launches_no_session(self):
        self.a_bad_run()
        self.assertIsNone(changes.after_run(self.project, "stopped", say=lambda text: None, pre_check=False))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(len(changes.pending_feedback(self.project)), 1, "the retrospective waits for the next wayline evolve")

    def test_nothing_after_a_run_fails_the_run(self):
        self.a_bad_run()
        said = []
        self.assertIsNone(changes.after_run(self.project, "frontier_empty", say=said.append, pre_check=False), "the fake has no answer scripted")
        self.assertTrue(any(line.startswith("evolve ") for line in said), said)
