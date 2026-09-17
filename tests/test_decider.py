"""The decider (ticket 31; Implementation Decisions 10, 4, and 5; BRIEF 6.2).

The decider is driven through the fake launcher (seam 1) over two real projects: the recorded grill
of ticket 30, whose owner said "decide the rest yourself" and left Q8 and Q10 open, and the
decision-branch fixture of ticket 35, whose ticket 2 pauses a branch. What is asserted is what the
owner and the next component see: the records in `research/DECISIONS.md`, the `decision` events
and their model, the ticket files, the launch line's model, effort, schema, and prompt, the decision
log's order, and the report's first section. The one rule under every other assertion: nothing on
the irreversible list is decided by the decider, and a refused answer becomes the owner's.
"""

import io
import json
import shutil
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import drive
from tests.test_decisions import ConductedCase
from wayline import cli, decider, decisions, grill, pacing, project, provenance, tickets, worker
from wayline.decider import Subject, irreversible_class, refusal
from wayline.ledger import Ledger
from wayline.worker import Envelope

RECORDED = FIXTURES_DIR / "skill" / "wayline-grill" / "recorded"
INPUT = FIXTURES_DIR / "skill" / "wayline-grill" / "input"
HOUR = 3600

Q8_ANSWER = "a small multilayer network (scikit-learn MLPClassifier) on the raw features"
Q10_ANSWER = "5-fold cross-validation inside split_a, the same grid for every model"


def decision(answer, rationale="POSITION.md names it as the flexible baseline paper-b used.", confidence=0.7, **extra):
    """The structured output a decider session returns."""
    record = {"question": "as asked", "options": [], "answer": answer, "rationale": rationale, "confidence": confidence,
              "decided_by": "decider", "reversible": True, "timestamp": None}
    record.update(extra)
    return record


def envelope(answer, **extra):
    return Envelope(structured_output=decision(answer, **extra), num_turns=5, duration_ms=30000)


def subject_of(request):
    """The subject line of a decider prompt: `the grill's Q8`, `decision ticket 2`, `parked proposal p1`."""
    for line in request.prompt.split("\n"):
        if line.startswith("- subject: "):
            return line[len("- subject: "):]
    raise AssertionError("no subject line in the decider's prompt")


def answering(table):
    """A `respond` for the fake: the envelope for whichever subject the prompt names."""
    def respond(request, message):
        subject = subject_of(request)
        for key, given in table.items():
            if key in subject:
                return given if isinstance(given, Envelope) else Envelope(structured_output=given, num_turns=5, duration_ms=30000)
        raise AssertionError("nothing scripted for %s" % subject)
    return respond


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


# --- the role and the line -----------------------------------------------------------------------------


class DeciderRoleTest(unittest.TestCase):
    """`roles/decider/` as the harness ships it: read-only, its own schema and protocol, launched at fable max."""

    def setUp(self):
        self.role = worker.read_role(decider.DECIDER)
        self.policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))

    def test_the_role_returns_a_decision_and_is_assigned_to_no_ticket(self):
        self.assertEqual(self.role.output_schema, "decision")
        self.assertEqual(self.role.kinds, [], "the conductor and the grill launch it; the librarian never assigns it")
        self.assertFalse(self.role.may_judge, "a decision is not a verdict")
        self.assertIn("irreversible", self.role.system_prompt)

    def test_the_role_reads_and_never_writes(self):
        self.assertEqual(self.role.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in ("Edit", "Write", "NotebookEdit", "Bash", "Agent", "WebFetch", "WebSearch", "mcp__*", "Workflow", "Skill"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.role.disallowed_tools)

    def test_the_protocol_comes_from_prompts(self):
        self.assertEqual(self.role.protocol, (HARNESS_ROOT / "prompts" / "roles" / "decider.md").read_text(encoding="utf-8"))
        self.assertIn("answer: null", self.role.protocol)

    def test_the_tier_is_fable_max_and_falls_back_to_opus_max(self):
        self.assertEqual(decider.decider_tier(self.policy), ("fable", "max", None))
        self.assertEqual(decider.decider_tier(self.policy, fall_back=True), ("opus", "max", "fable"))
        self.assertTrue(decider.decides_on_fable(self.policy))
        with self.assertRaises(decider.DeciderError):
            decider.decider_tier({"roles": {"decider": {"model": "gpt", "effort": "max"}}})

    def test_the_decisions_module_now_finds_a_decider(self):
        self.assertTrue(decisions.decider_ready())


class IrreversibleListTest(unittest.TestCase):
    """The code check of decision 4: an answer's class on the irreversible list, read off its words."""

    def test_each_class_on_the_list_is_caught(self):
        for text, expected in (
            ("delete the old results directory and regenerate", "delete or overwrite data"),
            ("overwrite results/run-3 with the new run", "delete or overwrite data"),
            ("rm -rf results/ before the sweep", "delete or overwrite data"),
            ("git push the branch to origin once it passes", "push"),
            ("force-push the rebased branch", "push"),
            ("raise the GPU budget to 40 hours", "budgets"),
            ("exceed the wall-clock budget by two hours for the sweep", "budgets"),
            ("buy more credits for the API", "spending"),
            ("pay for a larger instance", "spending"),
            ("change the goal to 0.74 AUROC on split_b", "goal"),
            ("lower the target to 0.74", "goal"),
            ("regenerate the dataset with interaction 0.6", "data"),
            ("swap the held-out split for the last third", "data"),
            ("upload the data to the shared bucket", "data"),
            ("edit the harness policy.json so every project gets 4 slots", "global harness change"),
            ("upload the figures to the wiki", "network write"),
            ("post the results to the Slack channel", "network write"),
        ):
            with self.subTest(text=text):
                self.assertEqual(irreversible_class(text), expected)

    def test_the_recorded_grills_answers_are_not_caught(self):
        for text in (Q8_ANSWER, Q10_ANSWER, "three seeds", "logistic regression on the raw features", "a table",
                     "keep split_b as the held-out split", "read the data once and cache it", "fetch the arXiv source",
                     "the same grid for every model", "yes", "no tuning: library defaults for every model"):
            with self.subTest(text=text):
                self.assertIsNone(irreversible_class(text))

    def test_a_bare_choice_takes_its_class_from_the_question(self):
        self.assertEqual(irreversible_class("yes", "Do we change the goal to a gain over the baseline?"), "goal")
        self.assertIsNone(irreversible_class("the second option", "Which flexible model is the second baseline?"))
        self.assertIsNone(irreversible_class("5-fold cross-validation inside split_a", "How are settings tuned without touching split_b?"))

    def test_an_answer_that_only_points_at_an_option_is_checked_by_the_options_words(self):
        options = ["keep the results", "delete results/ and regenerate"]
        for pointer in ("option 2", "2", "the second", "the second option", "choice 2", "The second one."):
            with self.subTest(pointer=pointer):
                self.assertEqual(decider.chosen_option(pointer, options), "delete results/ and regenerate")
        self.assertEqual(decider.chosen_option("the first", options), "keep the results")
        self.assertEqual(decider.chosen_option("option 3", options), "option 3", "a pointer past the options is read as words")
        self.assertEqual(decider.chosen_option("keep the results", options), "keep the results")
        subject = Subject(kind="ticket", key="2", question="What happens to the old results?", options=options)
        self.assertIn("irreversible list (delete or overwrite data): delete results/ and regenerate",
                      refusal(subject, decision("the second option")))
        self.assertIsNone(refusal(subject, decision("the first")))

    def test_refusal_reads_the_session_first_and_the_answer_second(self):
        subject = Subject(kind="question", key="Q8", question="Which flexible model is the second baseline?")
        self.assertIsNone(refusal(subject, decision(Q8_ANSWER)))
        self.assertIn("gave no answer", refusal(subject, decision(None, rationale="it is the owner's")))
        self.assertIn("cannot be taken back", refusal(subject, decision("wipe results/", reversible=False)))
        self.assertIn("human-only class", refusal(subject, decision(None, human_only=True)))
        self.assertIn("irreversible list (delete or overwrite data)", refusal(subject, decision("delete results/ first")))
        self.assertIn("irreversible", refusal(Subject(kind="question", key="Q1", question="q", reversible=False), decision("x")))


# --- the recorded grill, decided ---------------------------------------------------------------------


class RecordedGrillCase(ProjectTestCase):
    """The project of ticket 30's recorded grill after the switch: Q8 and Q10 open for the decider, Q7 and Q9 for the owner."""

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
        self.ledger.write_json("GOAL.json", {
            "metric": "auroc", "direction": "up", "target": 0.85, "dataset_or_split": None, "held_out_split": "split_b",
            "eval_command": "python3 toy/eval.py {artifact}", "baseline": {"value": None, "source": None},
            "budget": {"gpu_hours": None, "wallclock": 4, "usage_windows": None}, "stop_when": "goal_reached",
        }, schema="goal")
        self.ledger.write_markdown("kb/query_pack.md", "# Query pack\n\n- paper-a extends paper-b\n")
        project.set_autonomy(self.project, "autonomous")
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def notify(self, event, text, path, ticket):
        self.notified.append((event, ticket, text))

    def records(self):
        return {record["id"]: record for record in grill.read_records(self.project)}

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def decider_calls(self):
        return [call for call in self.fake.calls if call.request.role == decider.DECIDER]

    def decide_rest(self, **table):
        self.fake.script(respond=answering(table), role=decider.DECIDER)
        self.fake.script(respond=answering(table), role=decider.DECIDER)
        return decider.decide_rest(self.project, notify=self.notify)


class DecideRestTest(RecordedGrillCase):
    """Criteria 1, 2, and 4: the frontier is resolved one session at a time, each recorded as the decider's."""

    def test_the_open_frontier_is_settled_by_the_decider_with_rationale_confidence_and_model(self):
        report = self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER, confidence=0.55))
        self.assertEqual([outcome.subject.key for outcome in report["decided"]], ["Q8", "Q10"])
        self.assertEqual((report["refused"], report["failed"], report["stopped"], report["left"]), ([], [], None, []))
        records = self.records()
        for identifier, answer, confidence in (("Q8", Q8_ANSWER, 0.7), ("Q10", Q10_ANSWER, 0.55)):
            with self.subTest(identifier=identifier):
                record = records[identifier]
                self.assertEqual((record["answer"], record["decided_by"], record["confidence"]), (answer, "decider", confidence))
                self.assertTrue(record["rationale"])
                self.assertEqual(record["model"], worker.RESOLVED_MODELS["fable"])
                self.assertNotIn("fallback_from", record)
                self.assertTrue(record["session_id"])
                self.assertTrue(record["timestamp"])
        self.assertEqual({key: records[key]["answer"] for key in ("Q7", "Q9")}, {"Q7": None, "Q9": None}, "the owner's stay open")
        text = (self.project / "research" / "DECISIONS.md").read_text(encoding="utf-8")
        self.assertIn("- decided-by: decider", text)
        self.assertIn("- model: %s" % worker.RESOLVED_MODELS["fable"], text)

    def test_every_decision_is_journaled_with_its_model_and_session(self):
        self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER))
        decided = [event for event in self.events("decision") if event["payload"].get("decided_by") == "decider"]
        self.assertEqual(len(decided), 2)
        for event in decided:
            self.assertIsNone(event["payload"]["ticket"])
            self.assertEqual(event["payload"]["model"], worker.RESOLVED_MODELS["fable"])
            self.assertTrue(event["session_id"])
            self.assertTrue(event["payload"]["rationale"])
        self.assertTrue(decided[0]["payload"]["answer"].startswith("Q8 "))
        self.assertTrue(decided[1]["payload"]["answer"].startswith("Q10 "))
        log = decisions.decision_log(self.events(), grill.read_records(self.project))
        self.assertEqual([entry["decided_by"] for entry in log[:2]], ["decider", "decider"], "the decider's come first")
        self.assertEqual([entry["id"] for entry in log[:2]], ["Q8", "Q10"])
        self.assertTrue(all(entry["decided_by"] == "human" for entry in log[2:]))

    def test_the_launch_is_fable_at_max_effort_with_the_decision_schema_and_the_records_in_its_prompt(self):
        self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER))
        calls = self.decider_calls()
        self.assertEqual([call.kind for call in calls], ["launch", "launch"], "one fresh session per decision, no resume")
        first = calls[0].request
        self.assertEqual((first.model, first.effort, first.role), ("fable", "max", "decider"))
        self.assertEqual(first.schema_path.name, "decision.json")
        self.assertEqual(json.loads(first.agent_text())["decider"]["model"], "fable")
        self.assertEqual(first.cwd, self.project.resolve(), "no worktree: the decider writes nothing")
        self.assertNotIn("TICKET_TOUCHES", first.env, "without a touch set the guard blocks every write")
        self.assertEqual(first.allowed_tools, ["Read", "Glob", "Grep"])
        self.assertTrue(str(first.run_dir).startswith(str(self.project.resolve() / "research" / "sessions" / "decider" / "q8")))
        prompt = first.prompt
        self.assertIn("- subject: the grill's Q8", prompt)
        self.assertIn("- the question: Which flexible model without products is the second baseline?", prompt)
        self.assertIn("- recommended: a small multilayer network", prompt)
        self.assertIn("- rests on Q2, Which of the position memo's directions does the project take?: settled as moderate", prompt)
        for heading in ("## research/DECISIONS.md", "## research/POSITION.md", "## research/GOAL.json",
                        "## the L0 and L1 records (research/refs/<slug>/dossier.json)", "## research/kb/query_pack.md"):
            with self.subTest(heading=heading):
                self.assertIn(heading, prompt)
        self.assertIn("### Q2. Which of the position memo's directions does the project take?", prompt, "DECISIONS.md is inlined")
        self.assertIn("`paper-a` (level 2): Interaction features for tabular classification (2021)", prompt)
        self.assertIn("relation to the intent: The nearest work", prompt)
        self.assertIn('"held_out_split": "split_b"', prompt)
        self.assertIn("paper-a extends paper-b", prompt)
        self.assertIn("The human-only classes of this project are: `goal`, `data`.", prompt)
        self.assertIn("# The line", prompt)
        self.assertIn("# Protocol", prompt)
        self.assertIn("`decision` schema", prompt)
        second = calls[1].request.prompt
        self.assertIn("- subject: the grill's Q10", second)
        self.assertIn("- answer: %s" % Q8_ANSWER, second, "the second session reads what the first settled")

    def test_the_verb_decides_the_rest_and_then_prints_the_owners_tier(self):
        self.fake.script(respond=answering({"Q8": decision(Q8_ANSWER), "Q10": decision(Q10_ANSWER)}), role=decider.DECIDER)
        self.fake.script(respond=answering({"Q8": decision(Q8_ANSWER), "Q10": decision(Q10_ANSWER)}), role=decider.DECIDER)
        with mock.patch.object(decisions, "send_notification", self.notify):
            code, out, err = run("grill", "--decide-rest", "--project", str(self.project))
        self.assertEqual(code, 0, out + err)
        self.assertIn("the grill's Q8  decided: %s (confidence 0.7, on %s)" % (Q8_ANSWER, worker.RESOLVED_MODELS["fable"]), out)
        self.assertIn("the grill's Q10  decided:", out)
        self.assertIn("--revise", out, "how to reverse one is printed")
        self.assertIn("tier 3: ask the owner these 2 questions", out)
        self.assertRegex(out, r"(?m)^\s+1\. Q7\b")
        self.assertRegex(out, r"(?m)^\s+2\. Q9\b")
        self.assertNotIn("the decider resolves these", out, "nothing is left for the decider")

    def test_under_any_other_autonomy_the_verb_refuses_and_names_the_switch(self):
        project.set_autonomy(self.project, "checkpoints")
        code, out, err = run("grill", "--decide-rest", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("wayline switch --autonomy autonomous", err)
        self.assertEqual(self.decider_calls(), [])

    def test_a_question_the_decider_could_not_answer_is_left_open_and_not_tried_again_in_the_call(self):
        bad = Envelope(structured_output=None, errors=["the session returned no structured decision"], num_turns=2)
        self.fake.script(respond=answering({"Q8": bad, "Q10": decision(Q10_ANSWER)}), role=decider.DECIDER)
        self.fake.script(respond=answering({"Q8": bad, "Q10": decision(Q10_ANSWER)}), role=decider.DECIDER)
        self.fake.script(respond=answering({"Q8": bad, "Q10": decision(Q10_ANSWER)}), role=decider.DECIDER)
        report = decider.decide_rest(self.project, notify=self.notify)
        self.assertEqual([outcome.subject.key for outcome in report["failed"]], ["Q8"])
        self.assertIn("could not decide", report["failed"][0].why)
        self.assertEqual([outcome.subject.key for outcome in report["decided"]], ["Q10"])
        self.assertEqual(report["left"], ["Q8"], "still the decider's, for the next call")
        self.assertIsNone(self.records()["Q8"]["answer"])
        self.assertFalse(self.records()["Q8"].get("human_only"))
        self.assertEqual([call.kind for call in self.decider_calls()], ["launch", "resume", "launch"],
                         "resumed once with the reason, then left; the next question is a fresh launch")

    def test_an_unusable_decision_is_resumed_once_with_the_reason(self):
        no_rationale = decision(Q8_ANSWER, rationale="")

        def respond(request, message):
            if message is not None:
                self.assertIn("carries no rationale", message)
                return Envelope(structured_output=decision(Q8_ANSWER), num_turns=1)
            return Envelope(structured_output=no_rationale if "Q8" in subject_of(request) else decision(Q10_ANSWER), num_turns=3)

        self.fake.script(respond=respond, role=decider.DECIDER)
        self.fake.script(respond=respond, role=decider.DECIDER)
        self.fake.script(respond=respond, role=decider.DECIDER)
        report = decider.decide_rest(self.project, notify=self.notify)
        self.assertEqual([outcome.subject.key for outcome in report["decided"]], ["Q8", "Q10"])
        self.assertEqual([call.kind for call in self.decider_calls()], ["launch", "resume", "launch"])


class RefusedAnswerTest(RecordedGrillCase):
    """Criterion 3: a refused answer becomes a human-only decision, in the tree and as a decision ticket."""

    def test_a_scripted_irreversible_answer_is_refused_and_turned_over_to_the_owner(self):
        report = self.decide_rest(Q8=decision("delete the old results and regenerate the data with interaction 0.6"),
                                  Q10=decision(Q10_ANSWER))
        self.assertEqual([outcome.subject.key for outcome in report["refused"]], ["Q8"])
        refused = report["refused"][0]
        self.assertIn("irreversible list (delete or overwrite data)", refused.why)
        record = self.records()["Q8"]
        self.assertIsNone(record["answer"], "nothing was decided")
        self.assertTrue(record["human_only"], "the question is the owner's now")
        self.assertIn("the decider was refused it: its answer falls in a class on the irreversible list (delete or overwrite data): "
                      "delete the old results and regenerate the data with interaction 0.6", record["evidence"][-1])
        self.assertEqual([event["payload"]["answer"][:3] for event in self.events("decision")
                          if event["payload"].get("decided_by") == "decider"], ["Q10"], "no decision for Q8 was journaled")
        # The human-only decision ticket it became.
        opened = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[refused.ticket]
        self.assertEqual((opened["kind"], opened["human_only"], opened["blocking"], opened["proposed_by"], opened["origin"]),
                         ("decision", True, None, "decider", "grill Q8"))
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(opened))[1]
        self.assertIn("Which flexible model without products is the second baseline?", body)
        self.assertIn("the decider was refused it", body)
        self.assertEqual([(event, ticket) for event, ticket, _ in self.notified], [("decision_opened", refused.ticket)])
        self.assertEqual(self.events("decision_opened")[-1]["payload"], {"ticket": refused.ticket, "blocking": None, "human_only": True})
        # The grill asks the owner Q8 now, and lists nothing for the decider.
        view = grill.grill_view(self.project)
        self.assertEqual([record["id"] for record in view["ask"]], ["Q7", "Q8", "Q9"])
        self.assertEqual(view["decider"], [])

    def test_the_sessions_own_refusal_is_a_refusal(self):
        report = self.decide_rest(Q8=decision(None, rationale="a network changes what leaves the machine, so it is the owner's",
                                              reversible=False),
                                  Q10=decision(Q10_ANSWER))
        self.assertEqual([outcome.subject.key for outcome in report["refused"]], ["Q8"])
        self.assertIn("cannot be taken back: a network changes what leaves the machine", report["refused"][0].why)
        self.assertTrue(self.records()["Q8"]["human_only"])
        self.assertEqual(len(self.notified), 1)

    def test_the_owners_answer_on_the_ticket_settles_the_question_in_the_tree(self):
        report = self.decide_rest(Q8=decision("wipe results/ and start over"), Q10=decision(Q10_ANSWER))
        ticket = report["refused"][0].ticket
        project.answer(self.project, ticket, "gradient-boosted trees (scikit-learn HistGradientBoostingClassifier) on the raw features",
                       rationale="trees need no tuning grid")
        view = grill.grill_view(self.project)  # the next `wayline grill` reads the ticket's answer back into the tree
        record = self.records()["Q8"]
        self.assertEqual((record["answer"], record["decided_by"], record["rationale"]),
                         ("gradient-boosted trees (scikit-learn HistGradientBoostingClassifier) on the raw features", "human",
                          "trees need no tuning grid"))
        self.assertNotIn("model", record, "the owner's answer ran on no model")
        self.assertEqual([record["id"] for record in view["ask"]], ["Q7", "Q9"])
        journaled = [event for event in self.events("decision") if event["payload"].get("answer", "").startswith("Q8 ")]
        self.assertEqual(len(journaled), 1)
        self.assertEqual(journaled[0]["payload"]["decided_by"], "human")

    def test_the_owners_answer_in_the_grill_answers_the_ticket_too(self):
        report = self.decide_rest(Q8=decision("wipe results/ and start over"), Q10=decision(Q10_ANSWER))
        ticket = report["refused"][0].ticket
        grill.answer(self.project, "Q8", "both", "the owner wants trees and a network")
        answered = [event for event in self.events("decision") if event["ticket"] == ticket]
        self.assertEqual(len(answered), 1)
        self.assertEqual((answered[0]["payload"]["answer"], answered[0]["payload"]["decided_by"], answered[0]["payload"]["rationale"]),
                         ("both", "human", "the owner wants trees and a network"))
        opened = {item["id"]: item for item in tickets.read_tickets(self.project)}[ticket]
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(opened))[1]
        self.assertEqual(tickets.answer_section(body), "both", "the ticket carries the same answer, for the conductor to close")
        self.assertEqual(self.records()["Q8"]["answer"], "both")
        grill.grill_view(self.project)  # reading the tree again neither re-answers nor re-journals anything
        self.assertEqual(len([event for event in self.events("decision") if event["ticket"] == ticket]), 1)
        self.assertEqual(len([event for event in self.events("decision") if event["payload"].get("answer", "").startswith("Q8 ")]), 1)

    def test_a_human_only_or_irreversible_question_is_never_launched(self):
        report = self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER))
        subjects = [subject_of(call.request) for call in self.decider_calls()]
        self.assertEqual(subjects, ["the grill's Q8", "the grill's Q10"])
        self.assertEqual(report["left"], [])
        with self.assertRaises(grill.GrillError):
            grill.answer(self.project, "Q7", "x", "y", decided_by="decider", model="fable")


class FallbackTest(RecordedGrillCase):
    """Decision 15: while Fable's weekly window is spent the decider falls back as the consent says, and each decision records its model."""

    def hold(self):
        self.ledger.append_event("paused", {"resets_at": pacing.iso(time.time() + 10 * HOUR), "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"})

    def test_under_consent_auto_the_decider_runs_on_opus_at_max_and_the_record_says_so(self):
        self.hold()
        project.set_model_fallback(self.project, "auto")
        self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER))
        request = self.decider_calls()[0].request
        self.assertEqual((request.model, request.effort), ("opus", "max"))
        self.assertEqual(json.loads(request.agent_text())["decider"]["model"], "opus")
        record = self.records()["Q8"]
        self.assertEqual((record["model"], record["fallback_from"]), (worker.RESOLVED_MODELS["opus"], "fable"))
        event = [event for event in self.events("decision") if event["payload"].get("decided_by") == "decider"][0]
        self.assertEqual((event["payload"]["model"], event["payload"]["fallback_from"]), (worker.RESOLVED_MODELS["opus"], "fable"))
        self.assertIn("in place of fable, whose weekly window was spent", (self.project / "research" / "DECISIONS.md").read_text(encoding="utf-8"))

    def test_under_consent_wait_nothing_is_launched_and_the_call_says_why(self):
        self.hold()
        project.set_model_fallback(self.project, "wait")
        report = self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER))
        self.assertEqual(self.decider_calls(), [])
        self.assertIn("Fable's weekly window is held", report["stopped"])
        self.assertEqual(report["left"], ["Q8", "Q10"])


# --- the conductor: decision tickets, and parked proposals at the end of the wave ---------------------------


class ConductorDecidesTest(ConductedCase):
    """Criterion 2: under `autonomous` the conductor launches the decider each wave for open decision tickets not human-only."""

    def setUp(self):
        super().setUp()
        project.set_autonomy(self.project, "autonomous")

    def decider_calls(self):
        return [call for call in self.fake.calls if call.request.role == decider.DECIDER]

    def test_the_decider_answers_ticket_two_in_the_first_wave_and_the_branch_it_paused_launches_at_once(self):
        self.script()
        self.fake.script(envelope("one line", rationale="INTAKE.md asks for a report read at a glance"), role=decider.DECIDER)
        launched, waves = self.conduct()
        self.assertEqual(launched, [[1, 3], [4, 5]], "ticket 3 no longer waits for the owner's morning")
        self.assertEqual(waves[0].decided, [2])
        self.assertEqual(self.statuses(), {1: "done", 2: "done", 3: "done", 4: "done", 5: "done"})
        decided = [event for event in self.events("decision") if event["payload"].get("decided_by") == "decider"]
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["ticket"], 2)
        self.assertEqual(decided[0]["payload"], {"ticket": 2, "answer": "one line", "decided_by": "decider",
                                                 "rationale": "INTAKE.md asks for a report read at a glance", "confidence": 0.7,
                                                 "model": worker.RESOLVED_MODELS["fable"]})
        self.assertTrue(decided[0]["session_id"])
        self.assertEqual(tickets.answer_section(self.body(2)), "one line")
        self.assertIn("ticket 2: decision ticket 2  decided: one line", self.out.getvalue())
        # The decision is appended to DECISIONS.md as well, as a settled record of the ticket's question (criterion 4).
        records = grill.read_records(self.project)
        self.assertEqual([(record.get("ticket"), record["answer"], record["decided_by"]) for record in records],
                         [(2, "one line", "decider")])
        self.assertEqual(records[0]["model"], worker.RESOLVED_MODELS["fable"])
        self.assertTrue(records[0]["session_id"])
        text = (self.project / "research" / "DECISIONS.md").read_text(encoding="utf-8")
        self.assertIn("### Ticket 2. Which form does the beta report take?", text)
        self.assertIn("- decided-by: decider", text)

    def test_the_launch_is_the_decider_at_fable_max_on_the_project_with_no_worktree(self):
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        self.conduct()
        calls = self.decider_calls()
        self.assertEqual(len(calls), 1)
        request = calls[0].request
        self.assertEqual((request.model, request.effort, request.schema_path.name), ("fable", "max", "decision.json"))
        self.assertEqual(request.cwd, self.project)
        self.assertFalse((self.project / ".worktrees" / "2").exists())
        self.assertEqual(self.events("ticket_launched")[0]["payload"]["ticket"], 1, "no ticket_launched for a decision ticket")
        self.assertNotIn(2, [event["payload"]["ticket"] for event in self.events("ticket_launched")])
        prompt = request.prompt
        self.assertIn("- subject: decision ticket 2", prompt)
        self.assertIn("- the question: Which form does the beta report take?", prompt)
        self.assertIn("- options: one line | a table", prompt)
        self.assertIn("- evidence: asked by: research/INTAKE.md#the-intent", prompt)
        self.assertIn("[wayline: there is no DECISIONS.md; nothing is settled yet]", prompt)

    def test_the_decision_log_and_the_report_list_the_deciders_decision_first(self):
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        self.conduct()
        log = decisions.decisions_view(self.project)["log"]
        self.assertEqual(log[0]["decided_by"], "decider")
        self.assertEqual((log[0]["ticket"], log[0]["answer"], log[0]["question"]), (2, "one line", "Which form does the beta report take?"))
        provenance.render_report(self.project, offline=True, draft=False)
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        first = text.split("## 1. Decisions by the decider", 1)[1].split("## 2.", 1)[0]
        self.assertIn("Ticket 2, *Which form does the beta report take?*: **one line** (confidence 0.7", first)
        self.assertIn("rationale: POSITION.md names it", first)

    def test_status_lists_the_deciders_decision_before_the_owners(self):
        self.script()
        Ledger(self.project).append_event("decision", {"ticket": None, "answer": "the goal stays", "decided_by": "human",
                                                       "rationale": None, "confidence": None})
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        self.conduct()
        view = project.status_view(self.project)
        self.assertEqual([entry["decided_by"] for entry in view["decided"]], ["decider", "human"])
        text = project.render_status(view)
        made = text.split("decisions made (2)\n", 1)[1].split("\n\n", 1)[0].split("\n")
        self.assertIn("decider", made[0])
        self.assertIn("ticket 2: one line  (confidence 0.7)", made[0])
        self.assertIn("rationale: POSITION.md names it", made[1])
        self.assertIn("human", made[2])
        self.assertIn("the goal stays", made[2])

    def test_a_refused_answer_turns_the_ticket_human_only_and_the_run_waits_for_the_owner(self):
        self.script()
        self.fake.script(envelope("a table, after deleting the old reports directory"), role=decider.DECIDER)
        launched, waves = self.conduct()
        self.assertEqual(launched, [[1], [4]], "the branch stays paused for the owner")
        self.assertEqual(waves[0].decided, [])
        ticket = self.ticket(2)
        self.assertEqual((ticket["status"], ticket["human_only"]), ("open", True))
        body = self.body(2)
        self.assertIn("- human-only: yes, only the owner answers it", body)
        self.assertIn("## Refused by the decider", body)
        self.assertIn("irreversible list (delete or overwrite data)", body)
        self.assertTrue(decisions.decision_record(body)["human_only"], "the record the dashboard reads says so too")
        self.assertIsNone(tickets.answer_section(body))
        self.assertEqual([event for event in self.events("decision") if event["payload"].get("decided_by") == "decider"], [])
        opened = self.events("decision_opened")
        self.assertEqual(opened[-1]["payload"], {"ticket": 2, "blocking": "subgraph", "human_only": True})
        self.assertIn(("decision_opened", 2), [(event, ticket) for event, ticket, _ in self.notified])
        self.assertIn("is now human only: the decider was refused it", self.notified[-1][2])
        self.assertIn("decision ticket 2 waits for the owner's answer: it is human-only", self.out.getvalue())
        self.assertEqual(decisions.decisions_view(self.project)["open"][0]["awaits"], "owner")
        self.assertEqual(len(self.decider_calls()), 1, "not launched again on the next wave")

    def test_a_ticket_nobody_could_decide_is_handed_to_a_person_rather_than_tried_every_wave(self):
        self.script()
        bad = Envelope(structured_output=None, errors=["no structured decision"], num_turns=1)
        self.fake.script(bad, role=decider.DECIDER)
        launched, _ = self.conduct()
        self.assertEqual(launched, [[1], [4]])
        self.assertEqual(self.ticket(2)["status"], "needs_human")
        needs = self.events("ticket_needs_human")
        self.assertEqual(needs[-1]["payload"]["ticket"], 2)
        self.assertIn("the decider could not answer it", needs[-1]["payload"]["question"])
        self.assertEqual(len(self.decider_calls()), 1)
        project.answer(self.project, 2, "one line")  # the owner can still answer it
        self.assertEqual(self.events("decision")[-1]["payload"]["decided_by"], "human")

    def test_under_checkpoints_the_decider_is_not_launched(self):
        project.set_autonomy(self.project, "checkpoints")
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        launched, _ = self.conduct()
        self.assertEqual(launched, [[1], [4]])
        self.assertEqual(self.decider_calls(), [])

    def test_while_fable_is_held_the_decider_waits_under_wait_and_falls_back_under_auto(self):
        """The decider is model work on Fable: the hold keeps it as it keeps a verdict, and the run stays open for the reset."""
        self.ledger.append_event("paused", {"resets_at": pacing.iso(time.time() + 10 * HOUR), "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"})
        project.set_model_fallback(self.project, "wait")
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        driven = self.conductor()
        waves = drive(driven, waves=4)
        self.assertEqual([sorted(wave.launched) for wave in waves if wave.launched], [[1], [4]])
        self.assertFalse(waves[-1].ended, "ticket 2 is still the decider's, so the run waits for the reset rather than ending")
        self.assertEqual(self.decider_calls(), [])
        self.assertEqual(self.ticket(2)["status"], "open")
        # The consent changes to `auto` mid-run: the next wave falls back, on Opus at max, and the decision says so.
        project.set_model_fallback(self.project, "auto")
        waves = drive(driven)
        self.assertEqual([sorted(wave.launched) for wave in waves if wave.launched], [[3], [5]])
        self.assertTrue(waves[-1].ended)
        request = self.decider_calls()[0].request
        self.assertEqual((request.model, request.effort), ("opus", "max"))
        self.assertEqual(json.loads(request.agent_text())["decider"]["model"], "opus")
        decided = [event for event in self.events("decision") if event["payload"].get("decided_by") == "decider"][0]
        self.assertEqual((decided["payload"]["model"], decided["payload"]["fallback_from"]), (worker.RESOLVED_MODELS["opus"], "fable"))
        self.assertIn("in place of fable", self.out.getvalue())


class ParkedProposalsTest(ConductedCase):
    """Criterion 2's other half: at the end of the wave the decider reconsiders parked proposals, once each."""

    def setUp(self):
        super().setUp()
        project.set_autonomy(self.project, "autonomous")
        parked = self.project / "research" / "proposals"
        parked.mkdir()
        (parked / "p1.json").write_text(json.dumps({"id": "p1", "title": "Sweep the interaction strength", "kind": "experiment",
                                                    "reason": "radius", "proposed_by": "worker:1"}), encoding="utf-8")
        (parked / "p2.json").write_text(json.dumps({"id": "p2", "title": "Add a null control", "reason": "cap"}), encoding="utf-8")
        (parked / "notes.txt").write_text("not a proposal\n", encoding="utf-8")

    def decider_calls(self):
        return [call for call in self.fake.calls if call.request.role == decider.DECIDER]

    def test_each_parked_proposal_is_reconsidered_once_and_the_answer_is_journaled(self):
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        self.fake.script(respond=answering({"p1": decision("admit", rationale="it probes the claim's failure, inside a moderate radius"),
                                            "p2": decision("keep parked", rationale="the cap stands")}), role=decider.DECIDER)
        self.fake.script(respond=answering({"p1": decision("admit", rationale="it probes the claim's failure, inside a moderate radius"),
                                            "p2": decision("keep parked", rationale="the cap stands")}), role=decider.DECIDER)
        launched, waves = self.conduct()
        self.assertEqual(launched, [[1, 3], [4, 5]])
        self.assertEqual(waves[0].reconsidered, ["p1", "p2"])
        self.assertEqual([wave.reconsidered for wave in waves[1:]], [[] for _ in waves[1:]], "asked once, not every wave")
        answers = [event["payload"] for event in self.events("decision") if event["payload"].get("ticket") is None]
        self.assertEqual([entry["answer"] for entry in answers], ["proposal p1: admit", "proposal p2: keep parked"])
        self.assertEqual(answers[0]["rationale"], "it probes the claim's failure, inside a moderate radius")
        self.assertEqual(answers[0]["model"], worker.RESOLVED_MODELS["fable"])
        self.assertEqual(decider.reconsidered(self.project, self.events()), {"p1", "p2"})
        prompt = [call for call in self.fake.calls if "parked proposal p1" in call.request.prompt][0].request.prompt
        self.assertIn('- the question: Is the parked proposal p1, "Sweep the interaction strength", admitted to the run?', prompt)
        self.assertIn("- options: admit | keep parked", prompt)
        self.assertIn("- evidence: parked because: radius", prompt)
        self.assertEqual(len(self.decider_calls()), 3, "ticket 2 and the two proposals")

    def test_a_refused_admission_becomes_a_human_only_decision_ticket_and_is_not_asked_again(self):
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        self.fake.script(respond=answering({"p1": decision("admit, and push the branch to origin"), "p2": decision("keep parked")}),
                         role=decider.DECIDER)
        self.fake.script(respond=answering({"p1": decision("admit, and push the branch to origin"), "p2": decision("keep parked")}),
                         role=decider.DECIDER)
        launched, waves = self.conduct()
        answers = {event["payload"]["answer"]: event["payload"] for event in self.events("decision") if event["payload"].get("ticket") is None}
        self.assertEqual(list(answers), ["proposal p2: keep parked"], "nothing was decided about p1")
        opened = [ticket for ticket in tickets.read_tickets(self.project) if ticket.get("origin") == "proposal p1"]
        self.assertEqual(len(opened), 1)
        self.assertEqual((opened[0]["kind"], opened[0]["human_only"], opened[0]["blocking"], opened[0]["proposed_by"], opened[0]["status"]),
                         ("decision", True, None, "decider", "open"))
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(opened[0]))[1]
        self.assertIn('Is the parked proposal p1, "Sweep the interaction strength", admitted to the run?', body)
        self.assertIn("irreversible list (push)", body)
        self.assertIn(("decision_opened", opened[0]["id"]), [(event, ticket) for event, ticket, _ in self.notified])
        self.assertEqual(decider.reconsidered(self.project, self.events()), {"p1", "p2"})
        self.assertEqual(waves[0].reconsidered, ["p1", "p2"], "both were put to the decider this wave")
        self.assertEqual([wave.reconsidered for wave in waves[1:]], [[] for _ in waves[1:]])
        self.assertEqual(len(self.decider_calls()), 3, "p1 is the owner's now and is not put to a session again")
        self.assertTrue(launched, "the run went on")

    def test_the_report_names_a_proposal_decision_as_a_parked_proposal(self):
        self.script()
        self.fake.script(envelope("one line"), role=decider.DECIDER)
        self.fake.script(respond=answering({"p1": decision("admit"), "p2": decision("keep parked")}), role=decider.DECIDER)
        self.fake.script(respond=answering({"p1": decision("admit"), "p2": decision("keep parked")}), role=decider.DECIDER)
        self.conduct()
        provenance.render_report(self.project, offline=True, draft=False)
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        first = text.split("## 1. Decisions by the decider", 1)[1].split("## 2.", 1)[0]
        self.assertIn("- A parked proposal: **proposal p1: admit**", first)
        self.assertNotIn("The grill: **proposal", first)


class NoParkedProposalsTest(unittest.TestCase):
    def test_a_project_without_the_directory_has_none(self):
        self.assertEqual(decisions.parked_proposals(FIXTURES_DIR / "projects" / "decision-branch"), [])
