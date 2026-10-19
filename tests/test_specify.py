"""Specify, phase P3 (ticket 33; Implementation Decisions 10 and 11).

The planner and the verifier are driven through the fake launcher (seam 1) over the project of ticket
30's recorded grill: its `DECISIONS.md` is the fixture decision log, with the position memo, the
dossiers, a goal, and a query pack beside it. The planner's answer is `fixtures/specify/draft.json`,
the toy intent's spec, or a copy of it broken on purpose. What is asserted is what the owner and the
next phase see: `research/SPEC.md` and `research/spec.json`, the launch lines, the resume messages,
the journal's `phase`, `verdict`, and `decision` events, and the confirmation ticket.
"""

import copy
import io
import json
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase, fable_policy, open_goal, open_objective
from wayline import cli, decider, gates, grill, objectives, project, sections, specify, tickets, worker
from wayline.ledger import Ledger
from wayline.worker import Envelope

RECORDED = FIXTURES_DIR / "skill" / "wayline-grill" / "recorded"
INPUT = FIXTURES_DIR / "skill" / "wayline-grill" / "input"
DRAFT = json.loads((FIXTURES_DIR / "specify" / "draft.json").read_text(encoding="utf-8"))
GOAL = {
    "metric": "auroc", "direction": "up", "target": 0.02, "dataset_or_split": None, "held_out_split": "split_b",
    "eval_command": "python3 toy/eval.py {artifact}", "baseline": {"value": None, "source": None},
    "budget": {"gpu_hours": None, "wallclock": 4, "usage_windows": None}, "stop_when": "goal_reached",
}


def draft(**changes):
    value = copy.deepcopy(DRAFT)
    value.update(changes)
    return value


def unlinked():
    """The toy spec with a claim no experiment tests and a metric with no script: two structural failures."""
    value = draft()
    value["claims"].append({"id": "C4", "text": "The products also help calibration.", "experiments": [], "objectives": []})
    value["metrics"][1]["script"] = None
    return value


def planned(value):
    return Envelope(structured_output=value, num_turns=12, duration_ms=90000)


def verdict(passed=True, findings=()):
    return Envelope(structured_output={"pass": passed, "findings": list(findings),
                                       "question_limit": specify.VERDICT_QUESTION}, num_turns=4, duration_ms=20000)


FINDING = {"text": "E2 compares the network with the with-products model, so it does not test C2's claim about recovery.",
           "locator": "research/SPEC.md#E2", "severity": "blocker"}


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class PlannerRoleTest(unittest.TestCase):
    """`roles/planner/`: read-only, launched by code, its specify protocol cut from its protocol file."""

    def setUp(self):
        self.role = worker.read_role(specify.PLANNER)
        self.policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))

    def test_the_role_returns_a_spec_and_writes_nothing(self):
        self.assertEqual(self.role.output_schema, "spec")
        self.assertEqual(self.role.kinds, [])
        self.assertFalse(self.role.may_judge)
        self.assertEqual(self.role.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in ("Edit", "Write", "NotebookEdit", "Bash", "Agent", "WebFetch", "Workflow", "Skill"):
            self.assertIn(tool, self.role.disallowed_tools)

    def test_the_specify_protocol_is_its_own_section(self):
        cut = specify.protocol_for(self.role.protocol, "specify")
        self.assertIn("## Specify", cut)
        self.assertIn("confirmed_by", cut)
        self.assertTrue(cut.startswith("# Protocol"))
        self.assertEqual(specify.protocol_for("# Protocol\n\nno sections\n", "specify"), "# Protocol\n\nno sections\n")
        self.assertEqual(specify.protocol_for("## Plan\n\nplan\n\n## Specify\n\nspec\n", "specify"), "## Specify\n\nspec\n")

    def test_the_protocols_and_the_role_name_objectives(self):
        """Ticket 81: the specify protocol ties claims to open objectives, the plan protocol tickets, and the role reads OBJECTIVES.md."""
        specify_cut = specify.protocol_for(self.role.protocol, "specify")
        plan_cut = specify.protocol_for(self.role.protocol, "plan")
        for text in ("`research/OBJECTIVES.md`", "`objectives`", "summary", "every open objective has a claim"):
            self.assertIn(text, specify_cut)
        for text in ("`research/OBJECTIVES.md`", "`objectives`", "`goal`"):
            self.assertIn(text, plan_cut)
        self.assertNotIn("GOAL.json", specify_cut + plan_cut)
        self.assertNotIn("goal_metric", plan_cut)
        agent = (HARNESS_ROOT / "roles" / "planner" / "agent.md").read_text(encoding="utf-8")
        self.assertIn("`OBJECTIVES.md`", agent)
        self.assertNotIn("GOAL.json", agent)

    def test_the_tier_is_opus_xhigh_and_a_planner_on_fable_falls_back_to_opus_xhigh(self):
        for fall_back in (False, True):
            self.assertEqual(specify.planner_tier(self.policy, fall_back=fall_back), ("opus", "xhigh", None))
        planner_on_fable = fable_policy(self.policy, "planner")
        self.assertEqual(specify.planner_tier(planner_on_fable), ("fable", "xhigh", None))
        self.assertEqual(specify.planner_tier(planner_on_fable, fall_back=True), ("opus", "xhigh", "fable"))
        with self.assertRaises(specify.SpecifyError):
            specify.planner_tier({"roles": {}})


class TypeAChecksTest(unittest.TestCase):
    """Criterion 2: the structural checks, each failure named."""

    def test_the_toy_spec_passes(self):
        self.assertEqual(specify.check_draft(draft()), [])

    def test_a_claim_without_an_experiment_and_an_experiment_without_a_claim(self):
        value = draft()
        value["claims"][0]["experiments"] = []
        value["experiments"][1]["claims"] = []
        failures = specify.check_draft(value)
        self.assertIn("claim C1 names no experiment", failures)
        self.assertIn("experiment E2 names no claim", failures)
        self.assertIn("claim C2 names the experiment E2, which does not name C2 among its claims", failures)
        self.assertIn("experiment E1 names the claim C1, whose experiments do not list E1", failures)

    def test_a_metric_without_a_script_and_an_anti_claim_without_an_experiment(self):
        value = draft()
        value["metrics"][0]["script"] = "  "
        value["anti_claims"][0]["confirmed_by"] = None
        value["anti_claims"][1]["confirmed_by"] = "E9"
        failures = specify.check_draft(value)
        self.assertIn("metric auroc names no script", failures)
        self.assertIn("anti-claim A1 names no experiment that would confirm it", failures)
        self.assertIn("anti-claim A2 names the experiment E9, which the spec does not define", failures)

    def test_every_section_is_present_and_not_empty(self):
        value = draft(out_of_scope=[], seams=[], methods=[],
                      budgets={"gpu_hours": None, "wallclock_hours": None, "usage_windows": None, "notes": None})
        failures = specify.check_draft(value)
        for heading in ("Out of scope", "Seams", "Methods"):
            self.assertIn("section %s is empty" % heading, failures)
        self.assertTrue(any(failure.startswith("section Budgets is empty") for failure in failures))
        missing = draft()
        del missing["risks"]
        self.assertTrue(specify.check_draft(missing)[0].startswith("the spec is not valid"), "a missing section is a schema failure")

    def test_references_resolve_and_ids_are_unique(self):
        value = draft()
        value["experiments"][0]["baselines"] = ["B7"]
        value["experiments"][0]["data"] = ["D7"]
        value["experiments"][0]["metrics"] = ["accuracy"]
        value["claims"][0]["experiments"] = ["E1", "E8"]
        value["baselines"].append(dict(value["baselines"][0]))
        value["success_criteria"][0]["experiments"] = ["E6"]
        failures = specify.check_draft(value)
        for text in ("experiment E1 names the baseline B7, which the spec does not define",
                     "experiment E1 names the data D7, which the spec does not define",
                     "experiment E1 names the metric accuracy, which the spec does not define",
                     "claim C1 names the experiment E8, which the spec does not define",
                     "the baseline id B1 is used more than once",
                     "success criterion 1 names the experiment E6, which the spec does not define"):
            self.assertIn(text, failures)


def objective(identifier, status="open", metric=None, direction="up"):
    """One record of `research/objectives.json`; a goal when `metric` is given."""
    measure = None
    if metric is not None:
        measure = {"metric": metric, "direction": direction, "target": None, "held_out_split": "split_b",
                   "eval_command": "python3 toy/eval.py {artifact}", "baseline": {"value": None, "source": None},
                   "dataset_or_split": None, "min_seeds": None}
    return {"id": identifier, "text": "Question %s?" % identifier, "measure": measure, "status": status,
            "answer": None if status == "open" else "set aside", "evidence": [], "reframed_as": None}


class ObjectivesCheckTest(unittest.TestCase):
    """Ticket 81: claims name open objectives, every open objective has a claim, every goal's metric is a metric."""

    def test_a_spec_whose_claims_answer_every_open_objective_passes(self):
        self.assertEqual(specify.check_draft(draft(), objectives=[objective("O1", metric="auroc")]), [])

    def test_an_open_objective_no_claim_answers_is_named(self):
        failures = specify.check_draft(draft(), objectives=[objective("O1"), objective("O2")])
        self.assertEqual(failures, ["the open objective O2 is answered by no claim: name it in the objectives of the claim "
                                    "that answers it"])

    def test_a_closed_objective_needs_no_claim(self):
        self.assertEqual(specify.check_draft(draft(), objectives=[objective("O1"), objective("O2", status="parked")]), [])

    def test_a_goal_whose_metric_is_not_among_the_metrics_is_named(self):
        failures = specify.check_draft(draft(), objectives=[objective("O1", metric="brier")])
        self.assertEqual(failures, ["the goal O1's metric brier is not among the spec's metrics"])

    def test_a_claim_naming_a_closed_or_unknown_objective_is_refused(self):
        value = draft()
        value["claims"][1]["objectives"] = ["O2"]
        value["claims"][2]["objectives"] = ["O9"]
        failures = specify.check_draft(value, objectives=[objective("O1"), objective("O2", status="answered")])
        self.assertIn("claim C2 names the objective O2, which is answered; a claim names only open objectives", failures)
        self.assertIn("claim C3 names the objective O9, which the project does not hold", failures)

    def test_the_schema_asks_for_the_summary_and_every_claims_objectives(self):
        self.assertTrue(DRAFT["summary"].strip())
        self.assertEqual([claim["objectives"] for claim in DRAFT["claims"]], [["O1"], [], []], "a claim may serve none")
        missing = draft()
        del missing["summary"]
        self.assertTrue(specify.check_draft(missing)[0].startswith("the spec is not valid"))
        unnamed = draft()
        del unnamed["claims"][0]["objectives"]
        self.assertTrue(specify.check_draft(unnamed)[0].startswith("the spec is not valid"))
        malformed = draft()
        malformed["claims"][0]["objectives"] = ["objective one"]
        self.assertTrue(specify.check_draft(malformed)[0].startswith("the spec is not valid"))


class RenderTest(unittest.TestCase):
    """Criterion 1's rendering: SPEC.md has the sections of decision 10, in order."""

    def test_every_section_in_order_with_the_ids(self):
        text = specify.render_spec(draft())
        headings = [line[3:] for line in text.split("\n") if line.startswith("## ")]
        self.assertEqual(headings, [heading for _, heading in specify.SECTIONS])
        self.assertTrue(text.startswith("# Spec: Do pairwise interaction terms improve"))
        self.assertIn("- **C1.** Adding all 28 pairwise products", text)
        self.assertIn("(experiments: E1)", text)
        self.assertIn("(confirmed by: E3)", text)
        self.assertIn("### E2 (claims: C2)", text)
        self.assertIn("- **auroc**: area under the ROC curve of the model's scores on split_b (script: `python3 toy/eval.py {artifact}`)", text)
        self.assertIn("- wall clock: 4 hours", text)

    def test_the_summary_leads_and_each_claim_names_its_objectives(self):
        text = specify.render_spec(draft())
        self.assertEqual([line[3:] for line in text.split("\n") if line.startswith("## ")][:2], ["Summary", "Question"])
        self.assertIn("## Summary\n\nThis project asks whether explicit pairwise interaction terms", text)
        self.assertIn("(experiments: E1; objectives: O1)", text)
        self.assertIn("(experiments: E2)\n", text, "a claim no objective asked for names none")

    def test_text_is_kept_to_one_line(self):
        value = draft()
        value["claims"][0]["text"] = "two\n\n## Not a heading"
        self.assertIn("- **C1.** two ## Not a heading (experiments: E1; objectives: O1)", specify.render_spec(value))


class SpecifyCase(ProjectTestCase):
    """The recorded grill's project with a goal and a query pack, the fake launcher in place."""

    autonomy = "checkpoints"

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        project.init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        research = self.project / "research"
        for name in ("DECISIONS.md", "CONTEXT.md", "journal.jsonl"):
            shutil.copy(RECORDED / "research" / name, research / name)
        shutil.copy(INPUT / "research" / "POSITION.md", research / "POSITION.md")
        shutil.copytree(INPUT / "research" / "refs", research / "refs", dirs_exist_ok=True)
        self.ledger = Ledger(self.project)
        self.ledger.write_json("GOAL.json", GOAL)  # an old project's goal file, which nothing reads (ticket 87)
        self.ledger.write_markdown("kb/query_pack.md", "# Query pack\n\n- paper-a extends paper-b\n")
        open_objective(self.project)
        project.set_autonomy(self.project, self.autonomy)
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def notify(self, event, text, path, ticket):
        self.notified.append((event, ticket, text))

    def script(self, *planner, verdicts=(verdict(),)):
        for envelope in planner:
            self.fake.script(envelope, role=specify.PLANNER)
        for envelope in verdicts:
            self.fake.script(envelope, role=gates.VERIFIER)

    def specify(self):
        return specify.specify(self.project, notify=self.notify)

    def calls(self, role):
        return [call for call in self.fake.calls if call.request.role == role]

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def phases(self):
        return [(event["payload"]["from"], event["payload"]["to"]) for event in self.events("phase")]

    def spec_md(self):
        return (self.project / "research" / "SPEC.md").read_text(encoding="utf-8")

    def confirmation(self):
        found = [ticket for ticket in tickets.read_tickets(self.project) if ticket["title"] == specify.TITLE]
        return found


class DraftTest(SpecifyCase):
    """Criteria 1 and 3: the launch, the rendered spec, and the one verdict."""

    def test_the_planner_is_launched_with_the_records_and_the_spec_is_rendered(self):
        self.script(planned(draft()))
        report = self.specify()
        self.assertIsNone(report["stopped"], report)
        [call] = self.calls(specify.PLANNER)
        request = call.request
        self.assertEqual((call.kind, request.model, request.effort), ("launch", "opus", "xhigh"))
        self.assertEqual(request.schema_path.name, "spec.json")
        self.assertEqual(request.allowed_tools, ["Read", "Glob", "Grep"])
        self.assertEqual(request.cwd, self.project.resolve())
        for text in ("## research/DECISIONS.md", "What does the goal become", "## research/POSITION.md", "The hostile reviewer",
                     "## research/OBJECTIVES.md", "## research/kb/query_pack.md",
                     "paper-a extends paper-b", "paper-b", "## Specify", "# The spec", "confirmed_by"):
            self.assertIn(text, request.prompt)
        self.assertNotIn("## Plan", request.prompt)
        self.assertIn("- Q7: How is the objection that the synthetic set plants the interaction met?", request.prompt,
                      "the grill's open questions are named")
        self.assertEqual(json.loads((self.project / "research" / "spec.json").read_text(encoding="utf-8")), DRAFT)
        self.assertEqual(self.spec_md(), specify.render_spec(DRAFT))
        self.assertEqual(specify.check_spec(self.project), [])
        self.assertEqual(self.phases(), [(None, "P3")])

    def test_the_verifier_judges_the_spec_on_opus_max_and_the_verdict_is_journaled(self):
        self.script(planned(draft()))
        self.specify()
        [call] = self.calls(gates.VERIFIER)
        self.assertEqual((call.request.model, call.request.effort), ("opus", "max"), "an opus author gets opus max")
        for path in specify.VERDICT_PATHS:
            self.assertIn("- `%s`" % path, call.request.prompt)
        self.assertNotIn("[wayline: this path is not there", call.request.prompt)
        self.assertIn(specify.VERDICT_QUESTION, call.request.prompt)
        [event] = self.events("verdict")
        sha = specify.spec_sha(self.project)
        self.assertEqual((event["payload"]["subject_kind"], event["payload"]["subject"], event["payload"]["verdict_type"],
                          event["payload"]["pass"]), ("spec", "research/SPEC.md at %s" % sha, "spec_coverage", True))

    def test_a_failing_structural_check_returns_the_draft_once_with_the_failures(self):
        self.script(planned(unlinked()), planned(draft()))
        report = self.specify()
        self.assertIsNone(report["stopped"])
        first, second = self.calls(specify.PLANNER)
        self.assertEqual((first.kind, second.kind), ("launch", "resume"))
        self.assertIn("- claim C4 names no experiment", second.message)
        self.assertIn("- metric auroc_gain names no script", second.message)
        self.assertEqual(specify.check_spec(self.project), [])
        sessions = self.project / "research" / "sessions" / "specify" / "1"
        self.assertEqual(sorted(path.name for path in sessions.glob("draft-*.json")), ["draft-1.json", "draft-2.json"])

    def test_a_second_structural_failure_writes_nothing_and_asks_nothing(self):
        self.script(planned(unlinked()), planned(unlinked()), verdicts=())
        report = self.specify()
        self.assertIn("failed its structural checks twice", report["stopped"])
        self.assertIn("claim C4 names no experiment", report["failures"])
        self.assertEqual(len(self.calls(specify.PLANNER)), 2, "returned once, not twice")
        self.assertEqual(self.calls(gates.VERIFIER), [])
        self.assertFalse((self.project / "research" / "SPEC.md").exists())
        self.assertEqual(self.confirmation(), [])
        self.assertEqual(report["state"]["state"], "none")
        code, out, _ = run("specify", "--project", str(self.project))
        self.assertEqual(code, 1, "and the verb says it stopped")

    def test_an_unreadable_draft_is_resumed_once(self):
        self.script(Envelope(structured_output=None, errors=["no structured output"]), planned(draft()))
        self.assertIsNone(self.specify()["stopped"])
        self.assertIn("could not be read", self.calls(specify.PLANNER)[1].message)

    def test_a_failing_verdict_returns_the_draft_once_with_the_findings(self):
        revised = draft()
        revised["claims"][1]["text"] = "A small network on the raw features does not match the with-products model."
        self.script(planned(draft()), planned(revised), verdicts=(verdict(False, [FINDING]), verdict()))
        report = self.specify()
        self.assertIsNone(report["stopped"], report)
        resume = self.calls(specify.PLANNER)[1]
        self.assertEqual(resume.kind, "resume")
        self.assertIn("[blocker] E2 compares the network", resume.message)
        self.assertIn("(research/SPEC.md#E2)", resume.message)
        self.assertEqual(json.loads((self.project / "research" / "spec.json").read_text(encoding="utf-8")), revised)
        self.assertEqual([event["payload"]["pass"] for event in self.events("verdict")], [False, True])
        self.assertEqual(report["state"]["state"], "pending")

    def test_a_second_failing_verdict_leaves_the_spec_unverified_and_the_next_run_redrafts_with_the_findings(self):
        self.script(planned(draft()), planned(draft()), verdicts=(verdict(False, [FINDING]), verdict(False, [FINDING])))
        report = self.specify()
        self.assertEqual(report["stopped"], "the verifier failed the spec twice; it stands unconfirmed")
        self.assertEqual(report["state"]["state"], "unverified")
        self.assertEqual(self.confirmation(), [], "an unverified spec is not put to the owner")
        self.script(planned(draft()))
        report = self.specify()
        self.assertIsNone(report["stopped"])
        launch = self.calls(specify.PLANNER)[2]
        self.assertEqual(launch.kind, "launch", "a fresh session")
        self.assertIn("# What to change", launch.request.prompt)
        self.assertIn("E2 compares the network", launch.request.prompt)

    def test_no_open_objective_no_spec_and_the_question_to_ask_is_named(self):
        objectives.change_objective(self.project, "O1", "parked", by="owner", answer="later")
        report = self.specify()
        self.assertIn("no objective is open", report["stopped"])
        self.assertIn('"what should the project answer first?"', report["stopped"])
        self.assertIn("wayline objective add", report["stopped"])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.phases(), [], "a refused draft moves no phase")
        code, out, _ = run("specify", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("what should the project answer first?", out)

    def test_an_objectives_json_that_cannot_be_read_stops_the_draft_without_a_traceback(self):
        self.ledger.write_json("objectives.json", {"objectives": 3})
        report = self.specify()
        self.assertIn("research/objectives.json cannot be read", report["stopped"])
        self.assertEqual(self.fake.calls, [])
        code, out, err = run("specify", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_check_spec_names_an_objectives_json_it_cannot_read(self):
        self.script(planned(draft()))
        self.specify()
        self.ledger.write_json("objectives.json", {"objectives": 3})
        self.assertTrue(specify.check_spec(self.project)[0].startswith("research/objectives.json cannot be read"))

    def test_a_confirmed_spec_is_not_held_to_objectives_that_changed_after_it(self):
        """What changes after the confirmation is an amendment's (ticket 92) and the tickets' own check, not a dead end."""
        self.script(planned(draft()))
        self.specify()
        objectives.add_objective(self.project, "A question asked after the confirmation")
        self.assertEqual(specify.check_spec(self.project, against_objectives=False), [])
        self.assertIn("the open objective O2 is answered by no claim: name it in the objectives of the claim that answers it",
                      specify.check_spec(self.project))

    def test_one_open_objective_is_enough_and_no_goal_json_is_needed(self):
        """The objective may be the question to answer first, not the project's end; it need carry no measure."""
        (self.project / "research" / "GOAL.json").unlink()
        self.script(planned(draft()))
        report = self.specify()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["state"]["state"], "pending")

    def test_the_prompt_names_the_open_objectives_and_the_goals_measure(self):
        open_goal(self.project)
        objectives.add_objective(self.project, "A question set aside")
        objectives.change_objective(self.project, "O3", "parked", by="owner", answer="later")
        value = draft()
        value["claims"][0]["objectives"] = ["O1", "O2"]
        self.script(planned(value))
        report = self.specify()
        self.assertIsNone(report["stopped"], report)
        prompt = self.calls(specify.PLANNER)[0].request.prompt
        section = prompt.split("# The objectives", 1)[1].split("\n# ", 1)[0]
        self.assertIn("- O1: Does the method answer the project's question? (an objective: no measure)", section)
        self.assertIn("- O2: Do the products raise the held-out AUROC? (a goal: `auroc` up", section)
        self.assertNotIn("O3", section, "a parked objective is not the spec's to answer")
        self.assertIn("`objectives`", section)
        self.assertIn("`summary`", section)
        self.assertEqual([claim["objectives"] for claim in json.loads(
            (self.project / "research" / "spec.json").read_text(encoding="utf-8"))["claims"]], [["O1", "O2"], [], []])
        self.assertIn("## Summary", self.spec_md())

    def test_a_draft_that_leaves_an_open_objective_unanswered_goes_back_with_its_name(self):
        open_goal(self.project, metric="brier")
        self.script(planned(draft()), planned(draft()))
        report = self.specify()
        self.assertIn("failed its structural checks twice", report["stopped"])
        message = self.calls(specify.PLANNER)[1].message
        self.assertIn("- the open objective O2 is answered by no claim", message)
        self.assertIn("- the goal O2's metric brier is not among the spec's metrics", message)

    def test_the_verifier_reads_the_objectives_not_the_goal_json(self):
        self.assertIn("research/OBJECTIVES.md", specify.VERDICT_PATHS)
        self.assertNotIn("research/GOAL.json", specify.VERDICT_PATHS)
        self.assertIn("OBJECTIVES.md", specify.VERDICT_SCOPE)

    def test_a_hand_edit_of_spec_md_fails_the_check(self):
        self.script(planned(draft()))
        self.specify()
        path = self.project / "research" / "SPEC.md"
        path.write_text(path.read_text(encoding="utf-8").replace("## Seams", "## Interfaces"), encoding="utf-8")
        self.assertEqual(specify.check_spec(self.project), ["research/SPEC.md lacks the section(s) Seams"])
        path.write_text(specify.render_spec(DRAFT).replace("real datasets", "real data"), encoding="utf-8")
        self.assertIn("edited by hand", specify.check_spec(self.project)[0])


class CheckpointsTest(SpecifyCase):
    """Criterion 4 under checkpoints: a blocking-all ticket, and the phase advances on its answer."""

    def test_a_blocking_all_confirmation_is_opened_and_the_phase_advances_on_its_answer(self):
        self.script(planned(draft()))
        report = self.specify()
        [ticket] = self.confirmation()
        self.assertEqual((ticket["kind"], ticket["blocking"], ticket["human_only"], ticket["status"]),
                         ("decision", "all", False, "open"))
        self.assertEqual(ticket["origin"], "specify: confirm research/SPEC.md at %s" % specify.spec_sha(self.project))
        self.assertEqual(report["state"]["state"], "pending")
        self.assertEqual([(event, identifier) for event, identifier, _ in self.notified], [("decision_opened", ticket["id"])])
        self.assertEqual(self.phases(), [(None, "P3")])
        again = self.specify()
        self.assertEqual((again["did"], again["state"]["state"]), ([], "pending"), "waiting is idempotent")
        self.assertEqual(len(self.confirmation()), 1)
        project.answer(self.project, ticket["id"], "confirm", rationale="reads right")
        report = self.specify()
        self.assertEqual(report["state"]["state"], "confirmed")
        self.assertIn("the spec is confirmed; the phase moved to P4", report["did"])
        self.assertEqual(self.phases(), [(None, "P3"), ("P3", "P4")])
        self.specify()
        self.assertEqual(self.phases(), [(None, "P3"), ("P3", "P4")], "advanced once")
        self.assertEqual(len(self.calls(specify.PLANNER)), 1)

    def test_an_answer_written_in_the_ticket_file_counts(self):
        self.script(planned(draft()))
        self.specify()
        [ticket] = self.confirmation()
        path = tickets.tickets_dir(self.project) / tickets.filename(ticket)
        path.write_text(path.read_text(encoding="utf-8") + "\n## Answer\n\nyes, go ahead\n", encoding="utf-8")
        self.assertEqual(specify.spec_state(self.project)["state"], "confirmed")
        self.specify()
        self.assertEqual(self.phases()[-1], ("P3", "P4"))

    def test_a_revise_answer_redrafts_with_the_change_and_asks_again(self):
        self.script(planned(draft()), planned(draft(title="Pairwise products on the synthetic set")), verdicts=(verdict(), verdict()))
        self.specify()
        [first] = self.confirmation()
        code, out, err = run("answer", str(first["id"]), "revise: add a sweep of interaction 0.3", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        report = self.specify()
        self.assertIn("# What to change", self.calls(specify.PLANNER)[1].request.prompt)
        self.assertIn("The owner asked: add a sweep of interaction 0.3", self.calls(specify.PLANNER)[1].request.prompt)
        self.assertEqual(report["state"]["state"], "pending")
        self.assertEqual(len(self.confirmation()), 2, "the new spec is asked about anew")
        self.assertEqual(self.phases(), [(None, "P3")])

    def test_the_verb_prints_the_state_and_what_to_do(self):
        self.script(planned(draft()))
        code, out, err = run("specify", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("drafting the spec: the planner on opus at xhigh", out)
        self.assertIn('opened decision ticket', out)
        self.assertIn("the spec: pending at %s" % specify.spec_sha(self.project), out)
        self.assertIn("wayline answer", out)
        code, out, err = run("specify", "confirm", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("the spec: confirmed", out)
        self.assertIn("next: wayline plan", out)
        self.assertEqual(self.phases()[-1], ("P3", "P4"))
        code, _, err = run("specify", "confirm", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("nothing to confirm", err)


class AutonomousTest(SpecifyCase):
    """Criterion 4 under autonomous: the decider answers the confirmation."""

    autonomy = "autonomous"

    def settle_the_grill(self):
        """The recorded grill leaves Q8 and Q10 to the decider, which specify hands it before drafting."""
        for answer in ("a small network", "5-fold cross-validation inside split_a"):
            self.fake.script(Envelope(structured_output={
                "question": "as asked", "options": [], "answer": answer, "confidence": 0.7, "decided_by": "decider",
                "rationale": "The owner's earlier answers point there.", "reversible": True, "timestamp": None}), role=decider.DECIDER)

    def test_the_decider_takes_the_grills_open_questions_before_the_planner_drafts(self):
        self.settle_the_grill()
        self.script(planned(draft()))
        report = self.specify()  # nothing scripted for the confirmation: it stays pending
        roles = [call.request.role for call in self.fake.calls]
        self.assertEqual(roles[:3], [decider.DECIDER, decider.DECIDER, specify.PLANNER])
        self.assertIn("- subject: the grill's Q8", self.calls(decider.DECIDER)[0].request.prompt)
        self.assertTrue(any(line.startswith("the decider on the grill's Q8") for line in report["did"]), report["did"])
        prompt = self.calls(specify.PLANNER)[0].request.prompt
        left = prompt.split("# The questions the grill left open", 1)[1].split("\n# ", 1)[0]
        self.assertIn("- Q7:", left, "the owner's questions stay open")
        self.assertNotIn("- Q8:", left)
        self.assertNotIn("- Q10:", left)
        self.assertEqual([record["id"] for record in grill.decider_share(grill.read_records(self.project))], [])

    def test_a_human_only_question_is_left_to_the_owner_not_taken_by_the_spec(self):
        self.settle_the_grill()
        self.script(planned(draft()))
        self.specify()
        prompt = self.calls(specify.PLANNER)[0].request.prompt
        left = prompt.split("# The questions the grill left open", 1)[1].split("\n# ", 1)[0]
        [q7] = [line for line in left.split("\n") if line.startswith("- Q7:")]
        self.assertIn("the owner's: human-only or irreversible", q7)
        self.assertNotIn("recommended:", q7)
        self.assertIn("conditional on the owner's answer", left)

    def test_the_decider_confirms_the_spec_and_the_phase_advances(self):
        self.settle_the_grill()
        self.script(planned(draft()))
        self.fake.script(Envelope(structured_output={
            "question": "as asked", "options": ["confirm"], "answer": "confirm", "confidence": 0.8, "decided_by": "decider",
            "rationale": "Every claim traces to a settled decision and the verifier passed it.", "reversible": True,
            "timestamp": None}), role=decider.DECIDER)
        report = self.specify()
        self.assertIsNone(report["stopped"])
        call = self.calls(decider.DECIDER)[-1]
        self.assertIn("- subject: decision ticket", call.request.prompt)
        self.assertIn("Confirm the spec", call.request.prompt)
        self.assertEqual((report["state"]["state"], report["state"]["decided_by"]), ("confirmed", "decider"))
        decision = [event for event in self.events("decision") if event["payload"].get("decided_by") == "decider"][-1]
        self.assertEqual(decision["payload"]["answer"], "confirm")
        self.assertEqual(self.phases(), [(None, "P3"), ("P3", "P4")])

    def test_a_decider_that_cannot_decide_leaves_it_for_the_owner(self):
        self.settle_the_grill()
        self.script(planned(draft()))
        report = self.specify()  # nothing scripted for the decider: its launch fails
        self.assertEqual(report["state"]["state"], "pending")
        self.assertTrue(any("not decided" in line for line in report["did"]), report["did"])
        self.assertEqual(self.phases(), [(None, "P3")])


class InteractiveTest(SpecifyCase):
    """Criterion 4 under interactive: the owner is asked in the session, and no ticket is opened."""

    autonomy = "interactive"

    def test_the_owner_confirms_in_the_session(self):
        self.script(planned(draft()))
        code, out, err = run("specify", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("Ask the owner to read research/SPEC.md", out)
        self.assertIn("wayline specify confirm", out)
        self.assertEqual(self.confirmation(), [])
        self.assertEqual(specify.spec_state(self.project)["state"], "unasked")
        code, out, err = run("specify", "confirm", "--rationale", "matches the grill", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        [decision] = self.events("decision")[-1:]
        sha = specify.spec_sha(self.project)
        self.assertEqual((decision["payload"]["ticket"], decision["payload"]["answer"], decision["payload"]["decided_by"],
                          decision["payload"]["rationale"]), (None, "spec %s: confirm" % sha, "human", "matches the grill"))
        self.assertEqual(self.phases(), [(None, "P3"), ("P3", "P4")])

    def test_the_gap_passages_reach_the_introduction_once_the_spec_is_confirmed(self):
        """Ticket 86: the specify session writes the Introduction's passages on the gap, which code writes at the confirmation."""
        gap = [{"heading": "The gap", "text": "No work compares the products on a set whose labels do not depend on them.{ref:paper-a#relation_to_intent}"}]
        self.script(planned(draft(gap=gap)))
        self.specify()
        self.assertEqual(sections.read_passages(self.project), [], "a draft not yet confirmed writes no passage")
        code, _, err = run("specify", "confirm", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        [seeded] = sections.read_passages(self.project)
        self.assertEqual((seeded["section"], seeded["heading"], seeded["by"]), ("introduction", "The gap", "step:specify"))
        self.assertIn("No work compares the products", (self.project / "research" / "sections" / "introduction.md").read_text(encoding="utf-8"))
        specify.advance(self.project)
        self.assertEqual(len(sections.read_passages(self.project)), 1, "a second read of the confirmation seeds nothing")

    def test_the_owner_asks_for_a_change_in_the_session(self):
        self.script(planned(draft()), planned(draft(title="Products on the synthetic set")), verdicts=(verdict(), verdict()))
        self.specify()
        code, out, err = run("specify", "revise", "state the null control as its own claim", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("the spec: revise", out)
        self.specify()
        self.assertIn("state the null control as its own claim", self.calls(specify.PLANNER)[1].request.prompt)
        self.assertEqual(specify.spec_state(self.project)["state"], "unasked")


class ReviewFindingsTest(SpecifyCase):
    """What the review of ticket 33 found: no stuck revise, no lost verdict, no phase moving back."""

    def test_an_unchanged_redraft_is_refused_and_the_owner_can_still_confirm_that_version(self):
        self.script(planned(draft()), planned(draft()))
        self.specify()
        [ticket] = self.confirmation()
        project.answer(self.project, ticket["id"], "revise: add a sweep")
        report = self.specify()
        self.assertIn("returned the spec unchanged", report["stopped"])
        self.assertEqual(len(self.calls(gates.VERIFIER)), 1, "no verdict is spent on an unchanged draft")
        self.assertEqual(report["state"]["state"], "revise")
        state = specify.confirm(self.project, "confirm")
        self.assertEqual(state["state"], "confirmed", "the last answer wins")
        self.assertEqual(self.phases()[-1], ("P3", "P4"))

    def test_the_deciders_placeholder_revise_carries_its_rationale(self):
        self.script(planned(draft()))
        self.specify()
        [ticket] = self.confirmation()
        project.answer(self.project, ticket["id"], specify.REVISE, rationale="E2 does not test C2")
        state = specify.spec_state(self.project)
        self.assertEqual(state["feedback"], "(the reason given: E2 does not test C2)")

    def test_a_spec_whose_verdict_was_never_taken_is_judged_not_redrafted(self):
        self.script(planned(draft()), verdicts=(Envelope(structured_output=None, is_error=True, errors=["killed"]),))
        report = self.specify()
        self.assertIsNotNone(report["stopped"])
        self.assertEqual(report["state"]["state"], "unverified")
        self.script(verdicts=(verdict(),))
        report = self.specify()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(len(self.calls(specify.PLANNER)), 1, "the planner was not launched again")
        self.assertTrue(report["did"][0].startswith("the verifier passed research/SPEC.md"))
        self.assertEqual(report["state"]["state"], "pending")

    def test_the_phase_never_moves_back(self):
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})
        self.script(planned(draft()))
        self.specify()
        self.assertEqual(self.phases(), [("P4", "P5")])


class ConfirmationWordsTest(unittest.TestCase):
    def test_which_answers_confirm(self):
        for text in ("confirm", "Confirm the spec", "yes, go ahead", "OK", "approved.", "lgtm", "I confirm", "Looks good"):
            self.assertTrue(specify.confirms(text), text)
        for text in ("revise: add a claim", "no", "not yet, confirm E2 first", "", None, "ok, but drop C3",
                     "yes after removing E2"):
            self.assertFalse(specify.confirms(text), text)
        self.assertEqual(specify.what_to_change("revise: add a claim"), "add a claim")
        self.assertEqual(specify.what_to_change("drop E3"), "drop E3")


if __name__ == "__main__":
    unittest.main()
