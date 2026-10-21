"""Plan, phase P4 (ticket 34; Implementation Decisions 10, 2, and 5).

The planner is driven through the fake launcher (seam 1) over the project of ticket 33's tests: the
recorded grill's decisions, the toy spec written and confirmed, `toy/` at the project root. The
planner's answer is `fixtures/plan/cut.json`, the toy spec cut into eight tickets and one decision, or
a copy of it broken on purpose. What is asserted is what the owner and the conductor see: the ticket
files, `graph.json`, `plan.json`, the journal's `ticket_created`, `assigned`, `decision_opened`,
`ticket_cancelled`, and `phase` events, the launch lines, the resume messages, and the confirmation
ticket. The plan-time checks are also run on hand-written graphs, good and bad, at the base commit.
"""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase, open_goal, open_objective
from tests.test_specify import DRAFT, GOAL, INPUT, RECORDED, run
from wayline import cli, decider, objectives, plan, project, registry, specify, tickets, worker
from wayline.ledger import Ledger
from wayline.tickets import read_ticket, read_tickets, tickets_dir, write_ticket
from wayline.worker import Envelope

CUT = json.loads((FIXTURES_DIR / "plan" / "cut.json").read_text(encoding="utf-8"))
# The toy spec with C1 answering both objectives the plan tests record: O1, and O2, the goal on `auroc`.
SPEC = copy.deepcopy(DRAFT)
SPEC["claims"][0]["objectives"] = ["O1", "O2"]
CHECKS = FIXTURES_DIR / "skill" / "wayline-plan" / "checks.py"
IDENTITY = ("-c", "user.name=wayline test", "-c", "user.email=test@wayline.invalid")


def cut(**changes):
    value = copy.deepcopy(CUT)
    value.update(changes)
    return value


def planned(value):
    return Envelope(structured_output=value, num_turns=20, duration_ms=120000)


def decided(answer, rationale="The graph implements every experiment of the spec."):
    return Envelope(structured_output={"question": "as asked", "options": ["confirm"], "answer": answer, "confidence": 0.8,
                                       "decided_by": "decider", "rationale": rationale, "reversible": True, "timestamp": None})


def fields(identifier, title="A ticket", **extra):
    """A hand-written work ticket, in the shape the ledger fixture's are."""
    value = {"id": identifier, "title": title, "kind": "code", "difficulty": 2, "status": "open", "blocked_by": [],
             "touches": ["src/"], "role": "coder", "skills": [], "acceptance": {"machine": ["test -f src/%d.py" % identifier], "quality": []},
             "context_pack": ["research/INTAKE.md"], "origin": "research/INTAKE.md#the-intent", "proposed_by": "planner",
             "demo": "src/%d.py exists" % identifier}
    value.update(extra)
    return value


class PlannerRoleTest(unittest.TestCase):
    """`roles/planner/` in its plan protocol: the `## Plan` section alone, the same read-only role."""

    def test_the_plan_protocol_is_its_own_section(self):
        role = worker.read_role(plan.PLANNER)
        text = specify.protocol_for(role.protocol, "plan")
        self.assertIn("## Plan", text)
        self.assertIn("adds_public_api", text)
        self.assertNotIn("## Specify", text)
        self.assertTrue(text.startswith("# Protocol"))

    def test_the_plan_schema_is_shipped(self):
        schema = plan.load_schema(plan.PLAN_SCHEMA)
        self.assertEqual(schema["title"], "plan")
        self.assertNotIn("decision", schema["properties"]["tickets"]["items"]["properties"]["kind"]["enum"])

    def test_a_cut_names_its_kind_and_a_split_its_ticket(self):
        self.assertEqual(plan.Cut("split", of=4).asked, "a split of ticket #4, which failed its escalation: at least two smaller tickets that replace it")
        with self.assertRaises(plan.PlanError):
            plan.Cut("split")
        with self.assertRaises(plan.PlanError):
            plan.Cut("plan", of=4)
        with self.assertRaises(plan.PlanError):
            plan.Cut("recut")

    def test_retry_steps_are_spelled_as_a_ticket_file_holds_them(self):
        self.assertEqual(plan.retry_steps({"host_oom": [{"--batch-size": 16, "NAME": "v"}], "gpu_oom": ["--x=1"]}),
                         {"host_oom": ["--batch-size=16 NAME=v"], "gpu_oom": ["--x=1"]})
        self.assertIsNone(plan.retry_steps(None))


class ChecksTest(ProjectTestCase):
    """Criterion 3 on hand-written graphs: each check named, the base commit run in a checkout of main."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        project.init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)

    def write(self, *values, bodies=None):
        for value in values:
            write_ticket(self.ledger, value, (bodies or {}).get(value["id"], "## Demo\n\n%s\n" % value["demo"]))

    def test_a_good_graph_passes(self):
        self.write(fields(1), fields(2, kind="docs", blocked_by=[1], touches=["docs/"]),
                   fields(3, kind="experiment", role="experimenter", blocked_by=[1], touches=["results/e1/"]),
                   bodies={1: "## Demo\n\nsrc/1.py exists\n\n## Public API\n\n%s\n" % plan.PUBLIC_API_LINE})
        self.assertEqual(plan.check_graph(self.project), [])

    def test_a_cycle_and_an_unknown_blocker(self):
        self.write(fields(1, blocked_by=[2]), fields(2, blocked_by=[1]))
        failures = plan.check_graph(self.project, base=False)
        self.assertTrue(any(failure.startswith("the graph is not a DAG") for failure in failures), failures)
        self.write(fields(3, blocked_by=[9]))
        self.assertEqual(plan.check_graph(self.project, base=False), ["ticket 3 is blocked by 9, which does not exist"],
                         "a file the harness refuses is named, not raised")
        graph = [fields(1), fields(3, blocked_by=[9])]
        self.assertIn("ticket 3 waits on ticket 9, which the graph does not hold",
                      plan.check_tickets([(graph[1], "")], graph, self.project, base=False))

    def test_every_field_is_present(self):
        self.write(fields(1, demo="", acceptance={"machine": [], "quality": []}, touches=[], context_pack=[], role=plan.UNASSIGNED))
        failures = plan.check_graph(self.project, base=False)
        for text in ("ticket 1 has no demo", "ticket 1 has no machine criterion in acceptance.machine", "ticket 1 has no touch set",
                     "ticket 1 has no context pack",
                     "ticket 1 has no role: no assignable role covers a code ticket, and the harness needs one before it can run"):
            self.assertIn(text, failures)

    def test_a_title_that_gives_no_file_name_is_named(self):
        broken = fields(1, title="実験")
        failures = plan.check_tickets([(broken, "")], [broken], self.project, base=False)
        self.assertTrue(any(failure.startswith("ticket 1: its title gives no file name") for failure in failures), failures)

    def test_a_touch_set_is_paths_under_the_project(self):
        self.write(fields(1, touches=["/etc/", "../other/", "research/tickets/", "./", "src/", "results/e1/"]))
        failures = plan.check_graph(self.project, base=False)
        self.assertIn("ticket 1: the touch set entry `/etc/` is not a path under the project", failures)
        self.assertIn("ticket 1: the touch set entry `../other/` leaves the project", failures)
        self.assertIn("ticket 1: the touch set entry `research/tickets/` is under research/, which the ledger alone writes", failures)
        self.assertIn("ticket 1: the touch set entry `./` names the whole project", failures)
        self.assertEqual([failure for failure in failures if "`src/`" in failure or "`results/e1/`" in failure], [])

    def test_a_code_ticket_that_adds_public_api_is_followed_by_a_docs_ticket(self):
        body = "## Demo\n\nsrc/1.py exists\n\n## Public API\n\n%s\n" % plan.PUBLIC_API_LINE
        self.write(fields(1), bodies={1: body})
        self.assertIn("ticket 1 adds public API and no docs ticket waits on it", plan.check_graph(self.project, base=False))
        self.write(fields(2, kind="docs", blocked_by=[1], touches=["docs/"]))
        self.assertEqual(plan.check_graph(self.project, base=False), [])
        self.write(fields(2, kind="docs", status="parked", blocked_by=[1], touches=["docs/"]))
        self.assertIn("ticket 1 adds public API and no docs ticket waits on it", plan.check_graph(self.project, base=False),
                      "a parked docs ticket documents nothing")
        self.assertTrue(plan.adds_public_api(body))
        self.assertFalse(plan.adds_public_api("## Demo\n\nnothing\n"))

    def test_a_criterion_that_passes_at_the_base_is_a_failure(self):
        self.write(fields(1, acceptance={"machine": ["test -f research/INTAKE.md", "test -f src/1.py"], "quality": []}))
        [failure] = plan.check_graph(self.project)
        self.assertIn("ticket 1: the machine criterion `test -f research/INTAKE.md` passes at the base commit", failure)
        self.assertIn("the project directory, which lies in no repository", failure)
        self.assertEqual(plan.check_graph(self.project, base=False), [], "base False skips the run")

    def test_a_done_ticket_is_not_run_at_the_base(self):
        self.write(fields(1, status="done", acceptance={"machine": ["test -f research/INTAKE.md"], "quality": []}))
        self.assertEqual(plan.check_graph(self.project), [])

    def test_a_decision_ticket_is_exempt(self):
        self.write({"id": 1, "title": "Which split?", "kind": "decision", "difficulty": 1, "status": "open", "blocked_by": [],
                    "blocking": "subgraph", "human_only": False, "touches": [], "role": "decider", "skills": [], "acceptance": {},
                    "context_pack": [], "origin": None, "proposed_by": "planner", "demo": "The owner answers."})
        self.assertEqual(plan.check_graph(self.project), [])


class BaseCommitTest(ProjectTestCase):
    """The base commit is `main` of the project's repository, checked out apart from the working tree."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        project.init_project(self.project, harness_root=self.fake_harness(), git=True, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.project), *IDENTITY, *args], capture_output=True, text=True, check=True)

    def test_an_uncommitted_file_does_not_make_a_criterion_pass(self):
        (self.project / "notes").mkdir()
        (self.project / "notes" / "alpha.md").write_text("alpha\n", encoding="utf-8")
        write_ticket(self.ledger, fields(1, touches=["notes/"], acceptance={"machine": ["test -f notes/alpha.md"], "quality": []}))
        self.assertEqual(plan.check_graph(self.project), [], "the file is in the working tree, not at the base commit")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "alpha")
        [failure] = plan.check_graph(self.project)
        self.assertIn("passes at the base commit (main at", failure)
        self.assertFalse(list((self.project.parent).glob("wayline-plan-base-*")), "the checkout is removed afterward")
        self.assertNotIn("base", self.git("worktree", "list").stdout)

    def test_the_checkout_is_of_the_project_itself(self):
        with plan.base_checkout(self.project) as (where, described):
            self.assertNotEqual(where, self.project.resolve())
            self.assertTrue((where / "research" / "INTAKE.md").is_file())
            self.assertTrue(described.startswith("main at "))
        self.assertFalse(where.exists())

    def test_a_project_inside_a_larger_repository_is_checked_at_its_prefix(self):
        repo = self.temp / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
        nested = repo / "study"
        project.init_project(nested, harness_root=self.fake_harness(name="harness-2"), git=False, hermes_python=None, owner_email=None)
        (nested / "notes").mkdir()
        (nested / "notes" / "committed.md").write_text("x\n", encoding="utf-8")
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-q", "-m", "the study", cwd=repo)
        (nested / "notes" / "uncommitted.md").write_text("y\n", encoding="utf-8")
        write_ticket(Ledger(nested), fields(1, touches=["notes/"], acceptance={"machine": ["test -f notes/uncommitted.md", "test -f notes/committed.md"], "quality": []}))
        [failure] = plan.check_graph(nested)
        self.assertIn("`test -f notes/committed.md` passes at the base commit (main at", failure)
        self.assertIn(", under study)", failure)

    def test_a_repository_without_a_commit_is_refused_rather_than_checked_in_place(self):
        bare = self.temp / "fresh"
        bare.mkdir()
        subprocess.run(["git", "-C", str(bare), "init", "-q", "-b", "main"], check=True)
        with self.assertRaises(plan.PlanError) as caught:
            with plan.base_checkout(bare):
                pass
        self.assertIn("has no commit to be the base", str(caught.exception))


class PlanCase(ProjectTestCase):
    """The recorded grill's project with the toy spec written and confirmed, `toy/` at the root, the fake launcher in place."""

    autonomy = "checkpoints"
    git = False

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "toy").resolve()
        project.init_project(self.project, harness_root=HARNESS_ROOT, git=self.git, hermes_python=None, owner_email=None)
        research = self.project / "research"
        for name in ("DECISIONS.md", "CONTEXT.md", "journal.jsonl"):
            shutil.copy(RECORDED / "research" / name, research / name)
        shutil.copy(INPUT / "research" / "POSITION.md", research / "POSITION.md")
        shutil.copytree(INPUT / "research" / "refs", research / "refs", dirs_exist_ok=True)
        shutil.copytree(INPUT / "context" / "toy", self.project / "toy")
        self.ledger = Ledger(self.project)
        self.ledger.write_json("GOAL.json", GOAL)  # an old project's goal file, which nothing reads (ticket 87)
        self.ledger.write_markdown("kb/query_pack.md", "# Query pack\n\n- paper-a extends paper-b\n")
        self.confirm_spec()
        open_objective(self.project)
        open_goal(self.project)  # O2, a goal on `auroc`, which the cut's E1 ticket names as its `goal`
        project.set_autonomy(self.project, self.autonomy)
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def confirm_spec(self):
        """The spec as ticket 33 leaves it: written, judged, confirmed in an interactive session, the phase at P4."""
        self.ledger.write_json("spec.json", SPEC, schema="spec")
        self.ledger.write_markdown("SPEC.md", specify.render_spec(SPEC))
        self.ledger.append_event("verdict", {"subject_kind": "spec", "subject": "research/SPEC.md at %s" % specify.spec_sha(self.project),
                                             "verdict_type": "spec_coverage", "pass": True, "session_id": "verifier-1",
                                             "model": "claude-opus-5", "findings": []})
        project.set_autonomy(self.project, "interactive")
        specify.confirm(self.project, "confirm")

    def notify(self, event, text, path, ticket):
        self.notified.append((event, ticket, text))

    def script(self, *planner):
        for envelope in planner:
            self.fake.script(envelope, role=plan.PLANNER)

    def plan(self, **options):
        return plan.plan(self.project, notify=self.notify, pre_check=False, **options)

    def calls(self, role):
        return [call for call in self.fake.calls if call.request.role == role]

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def phases(self):
        return [(event["payload"]["from"], event["payload"]["to"]) for event in self.events("phase")]

    def ticket(self, identifier):
        return {found["id"]: found for found in read_tickets(self.project)}[identifier]

    def body(self, identifier):
        return read_ticket(tickets_dir(self.project) / tickets.filename(self.ticket(identifier)))[1]

    def statuses(self):
        return {found["id"]: found["status"] for found in read_tickets(self.project)}

    def confirmation(self):
        return [found for found in read_tickets(self.project) if found["title"] == plan.TITLE]

    def set_status(self, identifier, status):
        found = self.ticket(identifier)
        write_ticket(self.ledger, dict(found, status=status), self.body(identifier))

    def second_message(self):
        return self.calls(plan.PLANNER)[1].message

    def harness_ticket(self):
        """The harness ticket the evolve loop files for a local change record (ticket 45), next to the graph; its id."""
        identifier = tickets.next_id(self.project)
        write_ticket(self.ledger, fields(identifier, "Tell the planner to cut smaller tickets", kind="harness", role="coder",
                                         touches=[".claude/agents/planner.md", "fixtures/role/planner-cuts-small/"],
                                         acceptance={"machine": ["test -f fixtures/role/planner-cuts-small/fixture.json"], "quality": []},
                                         context_pack=["research/changes/001-tell-the-planner-to-cut-smaller-tickets.json"],
                                         origin="change 001-tell-the-planner-to-cut-smaller-tickets", proposed_by="evolve"),
                     "## Demo\n\nThe planner cuts smaller tickets.\n")
        return identifier


class CutTest(PlanCase):
    """Criteria 1, 2, and 4: the launch, the written graph, the librarian's assignments, the decision tickets."""

    def test_the_planner_is_launched_with_the_spec_the_pack_the_registry_and_the_journal(self):
        self.script(planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        [call] = self.calls(plan.PLANNER)
        request = call.request
        self.assertEqual((call.kind, request.model, request.effort), ("launch", "opus", "xhigh"))
        self.assertEqual(request.schema_path.name, "plan.json")
        self.assertEqual(request.allowed_tools, ["Read", "Glob", "Grep"])
        self.assertEqual(request.cwd, self.project)
        for text in ("- the cut: the first cut", "## research/SPEC.md", "# Spec: Do pairwise interaction terms", "### E1 (claims: C1)",
                     "## research/OBJECTIVES.md", "## research/kb/query_pack.md", "paper-a extends paper-b",
                     "# The registry", "`coder` for code, harness tickets", "`documentarian` for docs tickets", "`experimenter` for experiment tickets",
                     "no role covers `figure`, `review` tickets", "`lit` tickets run on the `surveyor` role, not shipped yet", "# The difficulty rubric", "- 3: a new code path",
                     "# What the journal says", "# The paths you may open", "## Plan", "# The plan", "adds_public_api"):
            self.assertIn(text, request.prompt)
        self.assertNotIn("## Specify", request.prompt)
        self.assertNotIn("## research/GOAL.json", request.prompt, "the goals are the objectives' measures (ticket 87)")
        self.assertNotIn("# The graph as it stands", request.prompt, "a first cut has no graph to show")
        self.assertTrue((self.project / "research" / "registry.json").is_file(), "the registry is rebuilt at the launch")

    def test_the_tickets_are_written_and_the_graph_regenerated(self):
        self.script(planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["cut"], "plan")
        self.assertEqual(report["written"]["tickets"], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(report["written"]["decisions"], [9])
        one = self.ticket(1)
        self.assertEqual((one["kind"], one["difficulty"], one["status"], one["role"], one["skills"], one["proposed_by"]),
                         ("code", 2, "open", "coder", [], "planner"))
        self.assertEqual(one["touches"], ["toy/features.py"])
        self.assertEqual(one["acceptance"], {"machine": ["test -f toy/features.py", "python3 -m py_compile toy/features.py"], "quality": []})
        self.assertEqual(one["context_pack"], ["research/SPEC.md#methods", "toy/make_synthetic.py"])
        self.assertEqual(one["origin"], "research/SPEC.md#methods")
        self.assertIn("## Demo", self.body(1))
        self.assertIn("## Notes\n\nKeep the column order stable", self.body(1))
        self.assertIn("## Public API", self.body(1))
        self.assertNotIn("## Public API", self.body(3))
        four = self.ticket(4)
        self.assertEqual((four["kind"], four["role"], four["blocked_by"]), ("experiment", "experimenter", [1, 3]))
        self.assertEqual(four["resources"], {"gpu": 0, "cpu": 4, "ram_gb": 8, "wallclock_minutes": 30})
        self.assertEqual((four["objectives"], four["goal"]), (["O2"], "O2"))
        self.assertEqual(four["retry"], {"host_oom": ["--rows=10000"], "gpu_oom": []}, "a ladder step in the file's spelling")
        self.assertEqual((self.ticket(2)["role"], self.ticket(7)["role"], self.ticket(8)["role"]), ("documentarian", "analyst", "writer"))
        self.assertEqual(self.ticket(6)["blocked_by"], [1, 3, 9], "the decision ticket pauses the network experiment")
        names = sorted(path.name for path in tickets_dir(self.project).glob("*.md"))
        self.assertEqual(names[:2], [tickets.filename(one), "02-document-the-product-features.md"])
        self.assertTrue(names[0].startswith("01-add-the-pairwise-product-features"), names[0])
        graph = tickets.read_graph(self.project)
        self.assertEqual([entry["id"] for entry in graph["tickets"]], list(range(1, 11)))
        self.assertEqual(plan.check_graph(self.project), [], "the written graph passes the checks it was cut under")
        record = plan.read_plan(self.project)
        self.assertEqual((record["cut"], record["tickets"], record["decisions"], record["superseded"], record["sent_back"]),
                         ("plan", [1, 2, 3, 4, 5, 6, 7, 8], [9], [], None))
        self.assertEqual(record["plan"], CUT)
        self.assertEqual(record["sha"], report["written"]["sha"])

    def test_the_assignments_and_the_creations_are_journaled(self):
        self.script(planned(cut()))
        self.plan()
        assigned = {event["ticket"]: event["payload"] for event in self.events("assigned")}
        self.assertEqual(sorted(assigned), [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(assigned[1], {"ticket": 1, "role": "coder", "skills": []})
        self.assertEqual(assigned[4]["role"], "experimenter")
        created = {event["ticket"]: event["payload"] for event in self.events("ticket_created")}
        self.assertEqual(sorted(created), list(range(1, 11)))
        self.assertEqual(created[4], {"ticket": 4, "kind": "experiment", "proposed_by": "planner", "origin": "research/SPEC.md#e1-claims-c1",
                                      "blocked_by": [1, 3]})
        self.assertEqual(created[9]["kind"], "decision")

    def test_a_decision_ticket_carries_the_question_the_options_the_evidence_and_what_it_pauses(self):
        self.script(planned(cut()))
        self.plan()
        nine = self.ticket(9)
        self.assertEqual((nine["kind"], nine["blocking"], nine["human_only"], nine["role"], nine["proposed_by"]),
                         ("decision", "subgraph", False, "decider", "planner"))
        self.assertTrue(nine["origin"].endswith(": research/SPEC.md#risks"))
        from wayline.decisions import decision_record
        record = decision_record(self.body(9))
        self.assertEqual(record["question"], "Which grid does the small network's cross-validation search?")
        self.assertEqual(record["options"], ["hidden sizes 8, 16, 32 with one learning rate", "hidden sizes 8 to 64 and three learning rates"])
        self.assertEqual(record["recommended"], "hidden sizes 8, 16, 32 with one learning rate")
        self.assertEqual(record["evidence"], ["research/SPEC.md#risks: the grid overrunning the 4-hour budget is the first risk"])
        self.assertIn("ticket 6 and whatever waits on it wait for the answer", self.body(9))
        self.assertEqual([identifier for event, identifier, _ in self.notified if event == "decision_opened"], [9, 10])
        self.assertEqual(sorted(tickets.paused_by(tickets.read_graph(self.project), [9])), [6, 7, 8])

    def test_a_decision_that_blocks_everything_and_is_human_only(self):
        whole = cut()
        whole["decisions"][0].update(blocking="all", human_only=True, pauses=[])
        self.script(planned(whole))
        self.assertIsNone(self.plan()["stopped"])
        nine = self.ticket(9)
        self.assertEqual((nine["blocking"], nine["human_only"]), ("all", True))
        self.assertEqual(self.ticket(6)["blocked_by"], [1, 3])
        self.assertIn("blocking: `all`, so no other ticket launches until it is answered", self.body(9))
        self.assertIn("human-only: yes", self.body(9))

    def test_a_failing_check_returns_the_plan_once_with_every_failure(self):
        looped = cut()
        looped["tickets"][0]["blocked_by"] = ["T2"]
        looped["tickets"][2]["touches"] = ["research/kb/"]
        looped["tickets"][3]["acceptance"]["machine"] = ["test -f toy/eval.py"]
        looped["tickets"][4]["context_pack"] = []
        self.script(planned(looped), planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        first, second = self.calls(plan.PLANNER)
        self.assertEqual((first.kind, second.kind), ("launch", "resume"))
        self.assertIn("- the graph is not a DAG", second.message)
        self.assertIn("- T3 (ticket 3): the touch set entry `research/kb/` is under research/, which the ledger alone writes", second.message)
        self.assertIn("- T4 (ticket 4): the machine criterion `test -f toy/eval.py` passes at the base commit", second.message)
        self.assertIn("- T5 (ticket 5) has no context pack", second.message)
        sessions = self.project / "research" / "sessions" / "plan" / "1"
        self.assertEqual(sorted(path.name for path in sessions.glob("plan-*.json")), ["plan-1.json", "plan-2.json"])
        self.assertEqual(len(read_tickets(self.project)), 10)

    def test_a_second_failure_writes_nothing(self):
        broken = cut()
        broken["tickets"][0]["touches"] = ["research/"]
        self.script(planned(broken), planned(broken))
        report = self.plan()
        self.assertIn("failed its checks twice", report["stopped"])
        self.assertTrue(any("is under research/" in failure for failure in report["failures"]), report["failures"])
        self.assertEqual(len(self.calls(plan.PLANNER)), 2, "returned once, not twice")
        self.assertEqual(read_tickets(self.project), [])
        self.assertIsNone(plan.read_plan(self.project))
        self.assertEqual(self.confirmation(), [])
        self.assertEqual(report["state"]["state"], "none")
        code, out, _ = run("plan", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 1, "and the verb says it stopped")

    def test_an_unreadable_plan_is_resumed_once(self):
        self.script(Envelope(structured_output=None, errors=["no structured output"]), planned(cut()))
        self.assertIsNone(self.plan()["stopped"])
        self.assertIn("could not be read", self.second_message())

    def test_references_that_do_not_resolve_and_a_kind_no_role_covers_come_back_together(self):
        broken = cut()
        broken["tickets"][0]["kind"] = "figure"
        broken["tickets"][2]["blocked_by"] = ["#42", "T9"]
        broken["decisions"][0]["pauses"] = []
        self.script(planned(broken), planned(cut()))
        self.assertIsNone(self.plan()["stopped"])
        message = self.second_message()
        self.assertIn("T3 (ticket 3) waits on #42, which the project does not hold", message)
        self.assertIn("T3 (ticket 3) waits on T9, which is no key of this plan", message)
        self.assertIn("decision 1 (ticket 9) pauses no ticket", message)
        self.assertIn("T1 (ticket 1) has no role: no assignable role covers a figure ticket", message)

    def test_a_title_with_no_file_name_and_an_empty_plan_are_returned(self):
        unnamed = cut()
        unnamed["tickets"][1]["title"] = "実験"
        self.script(planned(unnamed), planned(cut()))
        self.assertIsNone(self.plan()["stopped"])
        self.assertIn("T2 (ticket 2): its title gives no file name", self.second_message())
        shutil.rmtree(tickets_dir(self.project))
        tickets_dir(self.project).mkdir()
        (self.project / "research" / "plan.json").unlink()
        self.fake.reset()
        self.script(planned(cut(tickets=[], decisions=[])), planned(cut()))
        self.assertIsNone(self.plan()["stopped"])
        self.assertIn("a plan cuts at least one ticket; the plan holds none", self.second_message())

    def test_a_code_ticket_that_adds_public_api_needs_a_docs_ticket(self):
        undocumented = cut()
        undocumented["tickets"] = [item for item in undocumented["tickets"] if item["key"] != "T2"]
        self.script(planned(undocumented), planned(cut()))
        self.plan()
        self.assertIn("T1 (ticket 1) adds public API and no docs ticket waits on it", self.second_message())

    def test_a_first_plan_takes_back_the_open_tickets_it_finds(self):
        """A crash between the ticket writes and plan.json, or a hand-written ticket: never a second graph beside the first."""
        write_ticket(self.ledger, fields(1, "Left behind"), "## Demo\n\nleft\n")
        self.script(planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertIn("- #1 [open, re-cut] code", self.calls(plan.PLANNER)[0].request.prompt)
        self.assertEqual(report["written"]["superseded"], [1])
        self.assertEqual(report["written"]["tickets"], list(range(2, 10)))
        self.assertEqual(self.statuses()[1], "parked")
        self.assertIn("Superseded by the planner's first cut of the graph", self.body(1))

    def test_two_cuts_of_one_graph_cannot_both_land(self):
        self.script(planned(cut()))
        self.plan()
        index = registry.read_registry(self.project)
        with self.assertRaises(plan.PlanError) as caught:
            plan.write_plan(self.project, self.ledger, cut(), index, plan.Cut("plan"))
        self.assertIn("a graph was cut since this session started", str(caught.exception))
        self.assertEqual(len(read_tickets(self.project)), 10, "nothing was written")
        self.set_status(4, "running")
        with self.assertRaises(plan.PlanError) as caught:
            plan.write_plan(self.project, self.ledger, cut(), index, plan.Cut("replan"), expected=[1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertIn("the graph changed since the planner was launched", str(caught.exception))
        self.assertEqual(self.statuses()[1], "open", "nothing was parked")

    def test_the_spec_must_be_confirmed_first(self):
        (self.project / "research" / "spec.json").unlink()  # no spec, no confirmation to read
        report = self.plan()
        self.assertIn("run wayline specify first", report["stopped"])
        self.assertEqual(self.fake.calls, [])

    def test_a_hand_edited_spec_is_not_cut(self):
        path = self.project / "research" / "SPEC.md"
        path.write_text(path.read_text(encoding="utf-8").replace("real datasets", "real data"), encoding="utf-8")
        report = self.plan()
        self.assertIn("fails its checks", report["stopped"])
        self.assertEqual(self.fake.calls, [])


class ObjectivesTest(PlanCase):
    """Ticket 81: the tickets name the open objectives they serve, and `goal` the one whose measure they report."""

    def test_the_tickets_carry_their_objectives_and_the_goal_names_an_objective_with_a_measure(self):
        self.script(planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        four = self.ticket(4)
        self.assertEqual((four["objectives"], four["goal"]), (["O2"], "O2"))
        self.assertNotIn("goal_metric", four)
        self.assertEqual(self.ticket(5)["objectives"], ["O1"])
        self.assertEqual(self.ticket(1)["objectives"], [], "a ticket no objective asked for serves none")
        self.assertNotIn("goal", self.ticket(1))
        records = objectives.read_objectives(self.project)
        measure = objectives.ticket_goal(four, records)
        self.assertEqual((measure["metric"], measure["direction"]), ("auroc", "up"), "the metric and direction come from the goal")
        self.assertIsNone(objectives.ticket_goal(self.ticket(1), records))

    def test_objectives_changed_after_the_confirmation_leave_the_spec_cuttable(self):
        """An objective opened or parked after the spec was confirmed is no dead end: the tickets are held to what is open."""
        objectives.add_objective(self.project, "A question asked after the confirmation")
        objectives.change_objective(self.project, "O1", "parked", by="owner", answer="later")
        value = cut()
        value["tickets"][4]["objectives"] = []  # T5 named O1, which is parked now
        self.script(planned(value))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(self.ticket(4)["goal"], "O2")

    def test_the_planner_reads_the_objectives(self):
        self.script(planned(cut()))
        self.plan()
        prompt = self.calls(plan.PLANNER)[0].request.prompt
        self.assertIn("## research/OBJECTIVES.md", prompt)
        self.assertIn("## O2 Do the products raise the held-out AUROC?", prompt)

    def test_a_ticket_naming_a_closed_or_unknown_objective_or_a_goal_with_no_measure_is_returned(self):
        objectives.add_objective(self.project, "A question set aside")
        objectives.change_objective(self.project, "O3", "parked", by="owner", answer="later")
        broken = cut()
        broken["tickets"][3]["goal"] = "O1"
        broken["tickets"][1]["objectives"] = ["O3"]
        broken["tickets"][2]["objectives"] = ["O9"]
        broken["tickets"][0]["goal"] = "O3"
        self.script(planned(broken), planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        message = self.second_message()
        self.assertIn("T4 (ticket 4)'s goal O1 has no measure, so it is an objective and not a goal: name it among "
                      "`objectives` and leave `goal` null", message)
        self.assertIn("T2 (ticket 2) names the objective O3, which is parked; a ticket names only open objectives", message)
        self.assertIn("T3 (ticket 3) names the objective O9, which the project does not hold", message)
        self.assertIn("T1 (ticket 1)'s goal O3 is parked; a ticket's goal is an open objective", message)
        self.assertEqual(self.ticket(4)["goal"], "O2", "the second plan is the one written")

    def test_the_schemas_hold_objectives_and_goal_in_place_of_goal_metric(self):
        ticket_schema, plan_schema = (json.loads((HARNESS_ROOT / "schemas" / name).read_text(encoding="utf-8"))
                                      for name in ("ticket.json", "plan.json"))
        item = plan_schema["properties"]["tickets"]["items"]
        self.assertIn("objectives", item["required"], "the planner states them, empty for a ticket that serves none")
        for properties in (ticket_schema["properties"], item["properties"]):
            self.assertIn("objectives", properties)
            self.assertIn("goal", properties)
            self.assertNotIn("goal_metric", properties)
        wrong = cut()
        wrong["tickets"][3]["goal_metric"] = {"reports": "auroc", "expected_direction": "up"}
        self.script(planned(wrong), planned(cut()))
        self.assertIsNone(self.plan()["stopped"])
        self.assertIn("could not be read", self.second_message())


class SectionsTest(PlanCase):
    """Ticket 86: every ticket declares the sections its kind adds to, and a writing ticket's touch set is empty."""

    def test_the_tickets_declare_their_sections_by_kind(self):
        self.script(planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        declared = {identifier: self.ticket(identifier).get("sections") for identifier in range(1, 9)}
        self.assertEqual(declared, {1: ["methods"], 2: None, 3: ["methods"], 4: ["methods"], 5: ["methods"], 6: ["methods"],
                                    7: ["methods", "results"], 8: ["discussion"]})
        self.assertEqual(self.ticket(8)["touches"], [], "a writing ticket writes only its passages")

    def test_a_writing_ticket_with_a_touch_set_or_no_sections_and_a_kind_declaring_another_section_are_returned(self):
        broken = cut()
        broken["tickets"][7]["touches"] = ["paper/discussion.md"]
        broken["tickets"][7].pop("sections")
        broken["tickets"][0]["sections"] = ["results"]
        self.script(planned(broken), planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        message = self.second_message()
        self.assertIn("T8 (ticket 8) is a writing ticket, whose touch set is empty: code writes the sections from its passages", message)
        self.assertIn("T8 (ticket 8) is a writing ticket and declares no section", message)
        self.assertIn("T1 (ticket 1) declares results; a code ticket declares methods", message)

    def test_the_schemas_hold_sections(self):
        for name in ("ticket.json", "plan.json"):
            schema = json.loads((HARNESS_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            properties = schema["properties"] if name == "ticket.json" else schema["properties"]["tickets"]["items"]["properties"]
            self.assertEqual(properties["sections"]["items"]["enum"], ["introduction", "results", "discussion", "methods", "references"])

    def test_the_planner_is_told_no_writing_ticket_follows_an_analysis(self):
        protocol = (HARNESS_ROOT / "prompts" / "roles" / "planner.md").read_text(encoding="utf-8")
        self.assertIn("No `writing` ticket follows an analysis", protocol)


class CheckpointsTest(PlanCase):
    """Criterion 5 under checkpoints: a blocking-all ticket gates the graph; a revise parks it at once."""

    def test_a_blocking_all_confirmation_gates_the_graph_and_the_phase_advances_on_its_answer(self):
        self.script(planned(cut()))
        report = self.plan()
        [ticket] = self.confirmation()
        self.assertEqual((ticket["id"], ticket["kind"], ticket["blocking"], ticket["human_only"], ticket["status"]),
                         (10, "decision", "all", False, "open"))
        self.assertEqual(ticket["origin"], "plan: confirm research/graph.json at %s" % plan.read_plan(self.project)["sha"])
        self.assertEqual(report["written"]["gate"], 10, "opened in the same locked section as the tickets")
        self.assertEqual(report["state"]["state"], "pending")
        self.assertEqual([entry["id"] for entry in tickets.frontier(tickets.read_graph(self.project))], [9, 10],
                         "the frontier holds only the decision tickets while the confirmation is open")
        self.assertEqual(self.phases(), [(None, "P4")])
        again = self.plan()
        self.assertEqual((again["did"], again["cut"], again["state"]["state"]), ([], None, "pending"), "waiting is idempotent")
        self.assertEqual(len(self.confirmation()), 1)
        project.answer(self.project, 10, "confirm", rationale="reads right")
        report = self.plan()
        self.assertEqual(report["state"]["state"], "confirmed")
        self.assertIn("the graph is confirmed; the phase moved to P5", report["did"])
        self.assertEqual(self.phases(), [(None, "P4"), ("P4", "P5")])
        self.assertEqual(self.statuses()[1], "open", "a confirmation parks nothing")
        report = self.plan()
        self.assertEqual((report["did"], report["state"]["state"]), ([], "confirmed"))
        self.assertEqual(self.phases(), [(None, "P4"), ("P4", "P5")], "advanced once")
        self.assertEqual(len(self.calls(plan.PLANNER)), 1)

    def test_a_revise_answer_parks_the_graph_at_once_and_the_next_plan_cuts_it_again(self):
        self.script(planned(cut()))
        self.plan()
        code, _, err = run("answer", "10", "revise: split the network experiment by seed", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        statuses = self.statuses()
        self.assertEqual([identifier for identifier in range(1, 9) if statuses[identifier] == "parked"], list(range(1, 9)))
        self.assertEqual(statuses[9], "open", "the planner's decision ticket stays until the re-cut")
        self.assertIn("## Superseded\n\nSent back: the answer to decision ticket 10", self.body(3))
        self.assertEqual(sorted(event["ticket"] for event in self.events("ticket_cancelled")), list(range(1, 9)))
        self.assertEqual({event["payload"]["by"] for event in self.events("ticket_cancelled")}, {"planner"})
        self.assertEqual(plan.read_plan(self.project)["sent_back"], {"ticket": 10, "answer": "revise: split the network experiment by seed",
                                                                       "parked": list(range(1, 9))})
        self.assertEqual([entry["id"] for entry in tickets.frontier(tickets.read_graph(self.project)) if entry["kind"] != "decision"], [],
                         "nothing of the graph can launch, even once the answered ticket is closed")
        state = plan.plan_state(self.project)
        self.assertEqual((state["state"], state["feedback"]), ("revise", "split the network experiment by seed"))
        recut = cut()
        recut["tickets"][5]["title"] = "Run E2 on seeds 0 to 4"
        self.script(planned(recut))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["cut"], "revise")
        prompt = self.calls(plan.PLANNER)[1].request.prompt
        self.assertIn("# What to change", prompt)
        self.assertIn("The owner asked: split the network experiment by seed", prompt)
        self.assertIn("- #3 [parked, re-cut] code", prompt)
        self.assertIn("- #9 [open, re-cut] decision", prompt, "a decision that paused only re-cut tickets goes with them")
        self.assertIn("- #10 [open, kept] decision", prompt)
        self.assertEqual(report["written"]["tickets"], list(range(11, 19)))
        self.assertEqual(report["written"]["superseded"], list(range(1, 10)))
        self.assertEqual(self.statuses()[9], "parked")
        self.assertEqual(self.ticket(16)["title"], "Run E2 on seeds 0 to 4")
        self.assertEqual(len(self.confirmation()), 2, "the new graph is asked about anew")
        self.assertEqual(report["state"]["state"], "pending")
        self.assertIsNone(plan.read_plan(self.project)["sent_back"])

    def test_a_revise_leaves_the_evolve_loops_harness_ticket_to_its_change_record(self):
        self.script(planned(cut()))
        self.plan()
        harness = self.harness_ticket()
        code, _, err = run("answer", "10", "revise: split the network experiment by seed", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.statuses()[harness], "open", "the change record owns its harness ticket; no cut of the graph parks it")
        self.assertNotIn(harness, plan.read_plan(self.project)["sent_back"]["parked"])
        self.script(planned(cut()))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertIn("- #%d [open, kept] harness" % harness, self.calls(plan.PLANNER)[1].request.prompt)
        self.assertNotIn(harness, report["written"]["superseded"])
        self.assertEqual(self.statuses()[harness], "open")

    def test_a_sent_back_graph_is_not_confirmed_by_a_later_answer(self):
        self.script(planned(cut()))
        self.plan()
        project.answer(self.project, 10, "revise: fewer seeds")
        code, _, err = run("plan", "confirm", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("was sent back", err)
        self.assertEqual(plan.plan_state(self.project)["state"], "revise")
        path = tickets_dir(self.project) / tickets.filename(self.ticket(10))
        path.write_text(path.read_text(encoding="utf-8").replace("## Answer\n\nrevise: fewer seeds", "## Answer\n\nconfirm"), encoding="utf-8")
        project.journal_written_answers(self.project, self.ledger)
        self.assertEqual(plan.plan_state(self.project)["state"], "revise", "the parked tickets do not come back by a word")
        self.assertFalse(plan.advance(self.project))
        self.assertEqual(self.phases(), [(None, "P4")])

    def test_an_answer_written_in_the_ticket_file_counts(self):
        self.script(planned(cut()))
        self.plan()
        path = tickets_dir(self.project) / tickets.filename(self.ticket(10))
        path.write_text(path.read_text(encoding="utf-8") + "\n## Answer\n\nyes, go ahead\n", encoding="utf-8")
        self.assertEqual(plan.plan_state(self.project)["state"], "confirmed")
        self.plan()
        self.assertEqual(self.phases()[-1], ("P4", "P5"))

    def test_an_answer_written_in_the_file_that_sends_it_back_parks_the_graph_too(self):
        self.script(planned(cut()))
        self.plan()
        path = tickets_dir(self.project) / tickets.filename(self.ticket(10))
        path.write_text(path.read_text(encoding="utf-8") + "\n## Answer\n\nrevise: fewer seeds\n", encoding="utf-8")
        project.journal_written_answers(self.project, self.ledger)
        self.assertEqual(self.statuses()[1], "parked")

    def test_the_verb_prints_the_graph_and_what_to_do(self):
        self.script(planned(cut()))
        code, out, err = run("plan", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 0, err)
        self.assertIn("cutting the graph (plan): the planner on opus at xhigh", out)
        self.assertIn("plan: wrote 8 ticket(s) and 1 decision ticket(s) on opus", out)
        self.assertIn("opened decision ticket 10, \"Confirm the graph\", blocking all", out)
        self.assertIn("  1  code       d2  coder        Add the pairwise product features to the toy package", out)
        self.assertIn("(waits on 1, 3, 9)", out)
        self.assertIn("the planner notes: No role covers a figure ticket", out)
        self.assertIn("the graph: pending at %s" % plan.read_plan(self.project)["sha"], out)
        self.assertIn("wayline answer 10", out)
        code, out, err = run("plan", "--json", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["state"]["state"], "pending")
        code, out, err = run("answer", "10", "confirm", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        code, out, err = run("plan", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 0, err)
        self.assertIn("the graph: confirmed", out)
        self.assertIn("next: wayline run", out)
        self.assertIn("phase: P5", out)


class AutonomousTest(PlanCase):
    """Criterion 5 under autonomous: the decider answers the confirmation, and a refusal to confirm parks the graph."""

    autonomy = "autonomous"

    def test_the_decider_confirms_the_graph_and_the_phase_advances(self):
        self.script(planned(cut()))
        self.fake.script(decided("confirm"), role=decider.DECIDER)
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        [call] = self.calls(decider.DECIDER)
        self.assertIn("- subject: decision ticket 10", call.request.prompt)
        self.assertIn("Confirm the graph", call.request.prompt)
        self.assertEqual((report["state"]["state"], report["state"]["decided_by"]), ("confirmed", "decider"))
        self.assertEqual(self.phases(), [(None, "P4"), ("P4", "P5")])
        self.assertEqual(self.statuses()[1], "open")

    def test_a_decider_that_sends_the_graph_back_parks_it(self):
        self.script(planned(cut()))
        self.fake.script(decided("revise: the analysis ticket should wait on the null control alone", "E2 is not needed for C3."), role=decider.DECIDER)
        report = self.plan()
        self.assertEqual(report["state"]["state"], "revise")
        self.assertIn("(the reason given: E2 is not needed for C3.)", report["state"]["feedback"])
        self.assertEqual(report["state"]["decided_by"], "decider")
        self.assertEqual(self.statuses()[7], "parked")
        self.assertEqual(self.phases(), [(None, "P4")])

    def test_setup_cuts_the_graph_and_leaves_its_confirmation_until_its_last_question_is_answered(self):
        """Ticket 109: the confirmation ends setup, so setup cuts first, asks what the planned work needs, then confirms."""
        self.script(planned(cut()))
        report = self.plan(cut_only=True)
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["state"]["state"], "pending")
        self.assertEqual(self.calls(decider.DECIDER), [], "the decider is not launched on the confirmation yet")
        self.assertEqual(self.phases(), [(None, "P4")], "setup has not ended")
        self.fake.script(decided("confirm"), role=decider.DECIDER)
        report = self.plan()
        self.assertEqual((report["state"]["state"], report["state"]["decided_by"]), ("confirmed", "decider"))
        self.assertEqual(self.phases(), [(None, "P4"), ("P4", "P5")])
        self.assertEqual(len(self.calls(plan.PLANNER)), 1, "the graph is cut once")

    def test_a_decider_that_cannot_decide_leaves_it_for_the_owner(self):
        self.script(planned(cut()))
        report = self.plan()  # nothing scripted for the decider: its launch fails
        self.assertEqual(report["state"]["state"], "pending")
        self.assertTrue(any("not decided" in line for line in report["did"]), report["did"])


class InteractiveTest(PlanCase):
    """Criterion 5 under interactive: no ticket; the owner's word is recorded by the verb."""

    autonomy = "interactive"

    def test_the_owner_confirms_in_the_session(self):
        self.script(planned(cut()))
        code, out, err = run("plan", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 0, err)
        self.assertIn("Read the graph back to the owner", out)
        self.assertEqual(self.confirmation(), [])
        self.assertEqual(plan.plan_state(self.project)["state"], "unasked")
        code, out, err = run("plan", "confirm", "--rationale", "eight tickets, three experiments", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        [decision] = self.events("decision")[-1:]
        sha = plan.read_plan(self.project)["sha"]
        self.assertEqual((decision["payload"]["ticket"], decision["payload"]["answer"], decision["payload"]["decided_by"],
                          decision["payload"]["rationale"]), (None, "graph %s: confirm" % sha, "human", "eight tickets, three experiments"))
        self.assertEqual(self.phases(), [(None, "P4"), ("P4", "P5")])
        code, _, err = run("plan", "confirm", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("nothing to confirm", err)

    def test_the_owner_asks_for_a_change_in_the_session(self):
        self.script(planned(cut()))
        self.plan()
        code, out, err = run("plan", "revise", "one experiment ticket per seed", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("the graph: revise", out)
        self.assertEqual(self.statuses()[4], "parked")
        self.assertIn("Sent back by the owner (wayline plan revise", self.body(4))
        self.script(planned(cut()))
        report = self.plan()
        self.assertEqual(report["cut"], "revise")
        self.assertIn("one experiment ticket per seed", self.calls(plan.PLANNER)[1].request.prompt)
        self.assertEqual(plan.plan_state(self.project)["state"], "unasked")


class ReplanTest(PlanCase):
    """Criterion 6: `--replan` re-cuts the open tickets from the journal's failures; the kept ones are referenced as #<id>."""

    def setUp(self):
        super().setUp()
        self.script(planned(cut()))
        self.plan()
        project.answer(self.project, 10, "confirm")
        self.plan()
        self.set_status(1, "done")
        self.ledger.append_event("ticket_done", {"ticket": 1}, ticket=1)
        self.set_status(3, "failed")
        self.ledger.append_event("ticket_failed", {"ticket": 3, "attempt": 1, "reason": "py_compile failed on toy/paired_gain.py",
                                                   "next": "tier_up"}, ticket=3)
        self.ledger.append_event("stall", {"waves": 2, "action": "replan"})
        self.fake.reset()

    @staticmethod
    def recut():
        return {
            "tickets": [
                {"key": "T1", "title": "Run E1 with the products only", "kind": "experiment", "difficulty": 3, "blocked_by": ["#1", "#3"],
                 "touches": ["experiments/e1/", "results/e1/"], "resources": {"gpu": 0, "cpu": 4, "ram_gb": 8, "wallclock_minutes": 30},
                 "acceptance": {"machine": ["test -f results/e1/summary.json"], "quality": []}, "objectives": ["O2"], "goal": "O2",
                 "context_pack": ["research/SPEC.md#e1-claims-c1"], "origin": "research/SPEC.md#e1-claims-c1",
                 "demo": "`results/e1/summary.json` holds ten paired differences."},
                {"key": "T2", "title": "File the findings of E1", "kind": "analysis", "difficulty": 2, "blocked_by": ["T1"], "touches": ["analysis/"],
                 "acceptance": {"machine": ["test -f analysis/criteria.md"], "quality": []}, "objectives": [], "context_pack": ["results/e1/summary.json"],
                 "origin": "research/SPEC.md#success-criteria", "demo": "`analysis/criteria.md` says whether C1 held."},
            ],
            "decisions": [],
            "notes": ["E2 and E3 are dropped until the metric script is repaired."],
        }

    def test_the_open_tickets_are_re_cut_and_the_kept_ones_referenced(self):
        self.script(planned(self.recut()))
        report = plan.replan(self.project, notify=self.notify, pre_check=False)
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["cut"], "replan")
        prompt = self.calls(plan.PLANNER)[0].request.prompt
        self.assertIn("- the cut: a re-cut after a stall", prompt)
        self.assertIn("ticket 3 failed (attempt 1, next: tier_up): py_compile failed on toy/paired_gain.py", prompt)
        self.assertIn("the run stalled after 2 settling wave(s) without progress (action: replan)", prompt)
        self.assertIn("decision on ticket 10 by the owner: confirm", prompt)
        self.assertIn("- #1 [done, kept] code", prompt)
        self.assertIn("- #1 [done, kept] code d2 \"Add the pairwise product features to the toy package\"; touches `toy/features.py`; "
                      "acceptance `test -f toy/features.py`; `python3 -m py_compile toy/features.py`; adds public API", prompt)
        self.assertIn("- #3 [failed, kept] code", prompt)
        self.assertIn("- #2 [open, re-cut] docs", prompt)
        self.assertIn("- #9 [open, re-cut] decision", prompt)
        self.assertEqual(report["written"]["superseded"], [2, 4, 5, 6, 7, 8, 9])
        self.assertEqual(report["written"]["tickets"], [11, 12])
        statuses = self.statuses()
        self.assertEqual([statuses[identifier] for identifier in (1, 2, 3, 4, 8, 9, 11, 12)],
                         ["done", "parked", "failed", "parked", "parked", "parked", "open", "open"])
        self.assertIn("Re-cut by the planner after a stall; its replacements are tickets 11, 12.", self.body(4))
        self.assertEqual(sorted(event["ticket"] for event in self.events("ticket_cancelled")), [2, 4, 5, 6, 7, 8, 9])
        self.assertEqual(self.ticket(11)["blocked_by"], [1, 3])
        self.assertEqual(self.ticket(12)["blocked_by"], [11])
        record = plan.read_plan(self.project)
        self.assertEqual((record["cut"], record["tickets"], record["superseded"]), ("replan", [11, 12], [2, 4, 5, 6, 7, 8, 9]))
        self.assertEqual(len(self.confirmation()), 2, "a re-cut graph is confirmed anew under checkpoints")
        self.assertEqual(self.confirmation()[-1]["blocking"], "all")
        self.assertEqual(report["state"]["state"], "pending")
        self.assertEqual(self.phases()[-1], ("P4", "P5"), "the phase does not move back")

    def test_a_stall_replan_keeps_the_evolve_loops_harness_ticket(self):
        harness = self.harness_ticket()
        self.script(planned(self.recut()))
        report = plan.replan(self.project, notify=self.notify, pre_check=False)
        self.assertIsNone(report["stopped"], report)
        self.assertIn("- #%d [open, kept] harness" % harness, self.calls(plan.PLANNER)[0].request.prompt)
        self.assertEqual(report["written"]["superseded"], [2, 4, 5, 6, 7, 8, 9])
        self.assertEqual(self.statuses()[harness], "open")

    def test_a_stall_replan_keeps_a_ticket_the_owner_asked_for(self):
        """Ticket 109: a drafted ticket is the owner's request, which no re-cut takes back."""
        from wayline import drafts
        drafted = drafts.add_drafted(self.project, {
            "title": "Export the summary as CSV", "kind": "code", "difficulty": 2, "blocked_by": [], "touches": ["toy/export.py"],
            "acceptance": {"machine": ["test -f toy/export.py"]}, "objectives": [], "context_pack": ["research/SPEC.md"],
            "origin": "the owner, in the conversation", "demo": "toy/export.py writes summary.csv"})["ticket"]
        self.script(planned(self.recut()))
        report = plan.replan(self.project, notify=self.notify, pre_check=False)
        self.assertIsNone(report["stopped"], report)
        self.assertNotIn(drafted, report["written"]["superseded"])
        self.assertEqual(self.statuses()[drafted], "open")
        self.assertIn("- #%d [open, kept] code" % drafted, self.calls(plan.PLANNER)[0].request.prompt)

    def test_the_planner_is_never_asked_to_split_a_change_record_s_harness_ticket(self):
        harness = self.harness_ticket()
        self.set_status(harness, "failed")
        report = plan.split(self.project, harness, notify=self.notify, pre_check=False)
        self.assertIn("change record", report["stopped"] or "")
        self.assertEqual(self.calls(plan.PLANNER), [], "refused before a session is launched")

    def test_a_kept_code_ticket_that_adds_public_api_still_needs_its_docs_ticket(self):
        self.set_status(1, "failed")  # kept by the re-cut, with its docs ticket 2 taken back
        self.script(planned(self.recut()), planned(self.recut()))
        report = plan.replan(self.project, notify=self.notify, pre_check=False)
        self.assertIn("failed its checks twice", report["stopped"])
        self.assertIn("ticket 1 adds public API and no docs ticket waits on it", self.second_message())

    def test_a_new_ticket_may_not_wait_on_one_being_re_cut(self):
        wrong = self.recut()
        wrong["tickets"][0]["blocked_by"] = ["#2"]
        self.script(planned(wrong), planned(self.recut()))
        report = plan.replan(self.project, notify=self.notify, pre_check=False)
        self.assertIsNone(report["stopped"], report)
        self.assertIn("T1 (ticket 11) waits on #2, which this plan re-cuts; name its replacement's key instead", self.second_message())

    def test_the_verb_flag(self):
        self.script(planned(self.recut()))
        code, out, err = run("plan", "--replan", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 0, err)
        self.assertIn("replan: wrote 2 ticket(s), parked 2, 4, 5, 6, 7, 8, 9", out)


class SplitTest(PlanCase):
    """Criterion 6: `--split <id>` replaces one ticket with smaller ones that inherit its blockers and dependents."""

    def setUp(self):
        super().setUp()
        self.script(planned(cut()))
        self.plan()
        project.answer(self.project, 10, "confirm")
        self.plan()
        self.set_status(4, "failed")
        self.ledger.append_event("ticket_failed", {"ticket": 4, "attempt": 2, "reason": "the ten seeds did not finish in the budget",
                                                   "next": "split"}, ticket=4)
        self.fake.reset()

    @staticmethod
    def pieces(second_blocked_by=("T1",), difficulty=3, count=2):
        items = [
            {"key": "T1", "title": "Run E1 on seeds 0 to 4", "kind": "experiment", "difficulty": difficulty, "blocked_by": [],
             "touches": ["experiments/e1/first/", "results/e1/first/"], "acceptance": {"machine": ["test -f results/e1/first/summary.json"], "quality": []},
             "objectives": ["O2"], "goal": "O2",
             "context_pack": ["research/SPEC.md#e1-claims-c1"], "origin": "research/SPEC.md#e1-claims-c1",
             "demo": "`results/e1/first/summary.json` holds five paired differences."},
            {"key": "T2", "title": "Run E1 on seeds 5 to 9", "kind": "experiment", "difficulty": 2, "blocked_by": list(second_blocked_by),
             "touches": ["experiments/e1/second/", "results/e1/second/"], "acceptance": {"machine": ["test -f results/e1/second/summary.json"], "quality": []},
             "objectives": ["O2"], "goal": "O2",
             "context_pack": ["research/SPEC.md#e1-claims-c1"], "origin": "research/SPEC.md#e1-claims-c1",
             "demo": "`results/e1/second/summary.json` holds five paired differences."},
        ]
        return {"tickets": items[:count], "decisions": [], "notes": []}

    def test_the_pieces_inherit_the_blockers_and_the_dependents(self):
        self.script(planned(self.pieces()))
        report = plan.split(self.project, 4, notify=self.notify, pre_check=False)
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["cut"], "split")
        prompt = self.calls(plan.PLANNER)[0].request.prompt
        self.assertIn("- the cut: a split of ticket #4", prompt)
        self.assertIn("## The ticket to split, #4, whole", prompt)
        self.assertIn("ticket 4 failed (attempt 2, next: split): the ten seeds did not finish in the budget", prompt)
        self.assertNotIn("ticket 10", prompt.split("# What the journal says")[1].split("# The graph")[0], "the digest is the split ticket's")
        self.assertEqual(report["written"]["tickets"], [11, 12])
        self.assertEqual(self.ticket(11)["blocked_by"], [1, 3], "the blockers of ticket 4")
        self.assertEqual(self.ticket(12)["blocked_by"], [1, 3, 11])
        self.assertEqual(self.ticket(7)["blocked_by"], [5, 6, 11, 12], "the dependent waits on both pieces instead of ticket 4")
        self.assertEqual(report["written"]["repointed"], [7])
        self.assertEqual(self.statuses()[4], "parked")
        self.assertIn("## Superseded\n\nSplit by the planner into tickets 11, 12.", self.body(4))
        self.assertIn("Cut from ticket 4 by the planner's split.", self.body(11))
        self.assertEqual([event["ticket"] for event in self.events("ticket_cancelled")], [4])
        self.assertEqual(len(self.confirmation()), 1, "a split inherits the graph's confirmation")
        self.assertIsNone(report["written"]["gate"])
        self.assertEqual(plan.read_plan(self.project)["tickets"], list(range(1, 9)), "plan.json is the plan's, not the split's")
        self.assertEqual(report["state"]["state"], "confirmed")
        self.assertEqual(plan.check_graph(self.project), [])

    def test_a_split_cuts_at_least_two_no_harder_pieces_that_do_not_wait_on_the_ticket(self):
        wrong = self.pieces(second_blocked_by=("#4",), difficulty=4)
        self.script(planned(wrong), planned(self.pieces(count=1)))
        report = plan.split(self.project, 4, notify=self.notify, pre_check=False)
        self.assertIn("failed its checks twice", report["stopped"])
        launch, resume = self.calls(plan.PLANNER)
        self.assertEqual((launch.kind, resume.kind), ("launch", "resume"))
        self.assertIn("T1 is difficulty 4, harder than ticket 4 (difficulty 3) it is cut from", resume.message)
        self.assertIn("T2 (ticket 12) waits on #4, the ticket this split replaces", resume.message)
        self.assertIn("a split cuts at least two tickets; the plan holds 1", report["failures"])
        self.assertEqual(self.statuses()[4], "failed", "nothing was written")

    def test_a_closed_or_decision_ticket_is_not_split(self):
        self.set_status(1, "done")
        self.assertIn("is done, so it is not split", plan.split(self.project, 1, pre_check=False)["stopped"])
        self.assertIn("answered rather than split", plan.split(self.project, 9, pre_check=False)["stopped"])
        self.assertIn("has no ticket 77", plan.split(self.project, 77, pre_check=False)["stopped"])
        self.assertEqual(self.fake.calls, [])

    def test_the_verb_flag(self):
        self.script(planned(self.pieces()))
        code, out, err = run("plan", "--split", "4", "--project", str(self.project), "--no-pre-check")
        self.assertEqual(code, 0, err)
        self.assertIn("split: wrote 2 ticket(s), parked 4", out)
        self.assertIn("re-pointed at the pieces: 7", out)


class VerbTest(unittest.TestCase):
    def setUp(self):
        # A home of its own, so no active project of the machine's (an old one is refused, decision 17) stands behind the verb.
        home = tempfile.mkdtemp(prefix="wayline-test-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        patched = mock.patch.dict(os.environ, {"WAYLINE_HOME": home})
        patched.start()
        self.addCleanup(patched.stop)

    def test_the_verb_is_wired_and_its_flags_are_exclusive(self):
        self.assertIsNotNone(cli.lookup("plan").handler)
        code, out, _ = run("plan", "--help")
        self.assertEqual(code, 0)
        self.assertIn("--replan", out)
        self.assertIn("--split", out)
        code, _, err = run("plan", "--replan", "--split", "3")
        self.assertEqual(code, 2)
        self.assertIn("give one", err)
        code, _, _ = run("plan", "--frobnicate")
        self.assertEqual(code, 2)


class FixtureChecksTest(PlanCase):
    """The `python` checks of the wayline-plan fixture pass on a graph the verb cut, and the fixture record is whole."""

    def checks(self):
        spec = importlib.util.spec_from_file_location("plan_checks", CHECKS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_every_check_passes_on_a_cut_graph(self):
        self.script(planned(cut()))
        self.plan()
        module = self.checks()
        for name in module.CHECKS:
            with self.subTest(check=name):
                self.assertEqual(getattr(module, name)(self.project), [])

    def test_the_fixture_names_every_check(self):
        record = json.loads((CHECKS.parent / "fixture.json").read_text(encoding="utf-8"))
        named = [check["fn"] for check in record["structural"] if check.get("check") == "python"]
        self.assertEqual(sorted(named), sorted(self.checks().CHECKS))
        self.assertEqual(record["launch"]["model"], "fable")

    def test_the_recorded_run_passes_every_check(self):
        """The live run under `recorded/`, checked in a copy: a criterion run there must not write into the harness checkout."""
        recorded = CHECKS.parent / "recorded"
        if not (recorded / "research" / "graph.json").is_file():
            self.skipTest("no live run is recorded under %s yet" % recorded)
        copied = self.temp / "recorded"
        shutil.copytree(recorded, copied)
        module = self.checks()
        for name in module.CHECKS:
            with self.subTest(check=name):
                self.assertEqual(getattr(module, name)(copied), [])


if __name__ == "__main__":
    unittest.main()
