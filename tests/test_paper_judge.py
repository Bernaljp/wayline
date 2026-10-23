"""The decider orders the paper under `autonomous` (Implementation Decision 17; ticket 120).

Three seams. The setup's answer, through `wayline intake` into `harness.json`. Code's five checks and the decider's one
session (`wayline.paper_judge`) over a temporary project, every session through the fake launcher. And the conductor at
a run's end, read back from the journal each end kind writes, from the paper order it started, and from the rendered
`research/ACCOUNT.md`.
"""

import io
import json
import sys
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest import mock

from tests import machine
from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_builds import Verifier
from tests.test_drawings import DrawingRunCase
from tests.test_keep_if_better import GoalTicketCase, finding_result, seeds
from tests.test_paper import PaperCase, Writer
from tests.test_report import Classifier
from wayline.conductor import Conductor
from tests.test_paper_figures import FiguresCase
from tests.test_run_end import HOUR, GatesRunCase
from wayline import batches, cli, gates, objectives, outline, paper_judge, run_end, sections, tickets, verification, worker
from wayline import project as projects
from wayline.project import init_project, read_harness
from wayline.worker import Envelope


def intake(*args, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin or "")):
        code = cli.main(["intake", *args])
    return code, out.getvalue(), err.getvalue()


class SetupAnswerTest(ProjectTestCase):
    """Setup question 8: whether the decider judges the paper order, and for which venue."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)

    def answer(self, value):
        spec = {"intent": "Do interaction terms help?", "autonomy": "autonomous", "paper_order": value}
        return intake("--project", str(self.project), "--from", "-", stdin=json.dumps(spec))

    def test_without_an_answer_the_decider_judges_the_order_for_no_venue(self):
        self.assertNotIn("paper_order", read_harness(self.project))
        self.assertEqual(paper_judge.setting(read_harness(self.project)), {"decider": True, "venue": None})

    def test_the_answer_is_recorded_in_harness_json(self):
        code, _, err = self.answer({"decider": True, "venue": "nature-methods"})
        self.assertEqual(code, 0, err)
        self.assertEqual(read_harness(self.project)["paper_order"], {"decider": True, "venue": "nature-methods"})
        code, _, err = self.answer({"decider": False, "venue": None})
        self.assertEqual(code, 0, err)
        self.assertEqual(paper_judge.setting(read_harness(self.project)), {"decider": False, "venue": None})

    def test_a_venue_with_no_guidelines_and_an_answer_of_another_shape_are_refused(self):
        code, _, err = self.answer({"decider": True, "venue": "no-such-venue"})
        self.assertNotEqual(code, 0)
        self.assertIn("no-such-venue", err)
        code, _, err = self.answer("yes")
        self.assertNotEqual(code, 0)
        self.assertIn("paper_order", err)
        self.assertNotIn("paper_order", read_harness(self.project))


# --- code's five checks ------------------------------------------------------------------------------------------------


def kill_verdict(ledger, passed):
    """The kill argument on the general report, as the run-end gates journal it."""
    ledger.append_event("verdict", {"subject_kind": "report", "subject": "research/REPORT.md#kill-0123456789abcdef",
                                    "verdict_type": "kill_argument", "pass": passed, "session_id": "s-kill", "model": "opus",
                                    "findings": [] if passed else [{"text": "The gain is one seed's."}]})


def file_kill_scope_down(project, ledger):
    return gates.file_writing_ticket(project, ledger, title=run_end.KILL_TITLE, touches=[], inputs=[], quality=["narrowed?"],
                                     origin=run_end.KILL_ORIGIN, demo="narrowed", body="## Points\n\n- one seed\n",
                                     sections=["results"])


class ChecksTest(PaperCase):
    """`paper_judge.checks`: code's five checks, each failing with what a person reads, before any model call."""

    def failed(self):
        return {item["check"]: item["said"] for item in paper_judge.checks(self.project)}

    def test_a_project_short_of_a_paper_fails_the_four_checks_that_apply(self):
        found = self.failed()
        self.assertEqual(sorted(found), ["drawn", "gaps", "kill", "objectives"])
        self.assertIn(self.o1, found["objectives"])
        self.assertIn("no kill argument", found["kill"])
        self.assertIn("Fitting", found["gaps"])
        self.assertIn("R1", found["drawn"])

    def test_an_answered_objective_and_a_passed_kill_argument_pass_their_checks(self):
        objectives.change_objective(self.project, self.o1, "answered", "owner", answer="It grows.")
        kill_verdict(self.ledger, passed=True)
        self.assertEqual(sorted(self.failed()), ["drawn", "gaps"])

    def test_a_stopping_rule_naming_other_objectives_waits_only_on_those(self):
        other = self.objective("Does the fit hold at high noise?")
        objectives.change_objective(self.project, self.o1, "answered", "owner", answer="It grows.")
        harness = read_harness(self.project)
        (self.project / "harness.json").write_text(json.dumps(dict(harness, stop_when=[self.o1]), indent=2) + "\n")
        self.assertNotIn("objectives", self.failed(), "%s is open, and the rule does not name it" % other)

    def test_a_failed_kill_argument_passes_once_its_scope_downs_are_done(self):
        kill_verdict(self.ledger, passed=False)
        identifier = file_kill_scope_down(self.project, self.ledger)
        said = self.failed()["kill"]
        self.assertIn("failed", said)
        self.assertIn("ticket %d" % identifier, said)
        fields = {entry["id"]: entry for entry in tickets.read_tickets(self.project)}[identifier]
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        tickets.write_ticket(self.ledger, dict(fields, status="done"), body)
        self.assertNotIn("kill", self.failed())

    def test_a_failed_kill_argument_with_no_scope_down_fails_its_check(self):
        kill_verdict(self.ledger, passed=False)
        self.assertIn("no scope-down", self.failed()["kill"])

    def test_at_a_start_midway_the_inherited_results_objective_must_be_answered(self):
        self.inherited("Old fits", "The old fit holds at 0.2.", "D1#p1")
        self.assertIn("not recorded", self.failed()["inherited"])
        held = self.objective(verification.OBJECTIVE)
        self.assertIn("open", self.failed()["inherited"])
        objectives.change_objective(self.project, held, "answered", "code", answer="every inherited result has a verdict")
        self.assertNotIn("inherited", self.failed())


# --- the decider's one session -----------------------------------------------------------------------------------------


def judgment(order, reason="Both questions are answered and the outline holds every result.", answers=(), confidence=0.8):
    return Envelope(structured_output={"order": order, "reason": reason, "confidence": confidence, "answers": list(answers)},
                    num_turns=6, duration_ms=40000)


def answer(ref, mark, why=None):
    return {"ref": ref, "mark": mark, "why": why}


class JudgeCase(FiguresCase):
    """`FiguresCase`'s project under `autonomous`, R1's figure too large for a page, a contradiction between two inherited
    claims, and the outline proposing to merge R2 and R3, R3 placed by the owner."""

    def setUp(self):
        super().setUp()
        self.autonomy("autonomous")
        self.drawn("R1", [(number, "keep") for number in range(1, 13)])
        self.claim = self.inherited("Earlier noise study", "Noise inflates the error.", "D1#p1.s1")["id"]
        self.other = self.inherited("Earlier noise study", "Noise inflates the error tenfold.", "D1#p1.s2")["id"]
        self.contradiction(self.claim, self.other, "Earlier noise study")
        self.merges = batches.open_batch(self.project, "outline_proposals", "Merges", [
            {"ref": "R2+R3", "text": "Merge R2 and R3?", "default": "decline"}])["id"]
        outline.place(self.project, "R3", "supplement")

    def setup_answer(self, value):
        harness = read_harness(self.project)
        (self.project / "harness.json").write_text(json.dumps(dict(harness, paper_order=value), indent=2) + "\n")

    def judge(self, *envelopes, end="objectives_closed"):
        with worker.use_fake() as fake:
            for envelope in envelopes:
                fake.script(envelope, role="decider")
            try:
                return paper_judge.judge(self.project, end, fall_back=False)
            finally:
                self.calls = list(fake.calls)

    def journaled(self, name):
        return [event["payload"] for event in self.journal() if event["event"] == name]

    def decided(self):
        return [payload["answer"] for payload in self.journaled("decision") if payload["decided_by"] == "decider"]


class JudgeTest(JudgeCase):
    def test_one_session_on_opus_max_reads_the_report_the_objectives_and_the_outline(self):
        self.judge(judgment(False, "The kill argument's points narrowed the claims too far for a paper yet."))
        [call] = self.calls
        request = call.request
        self.assertEqual((request.role, request.model, request.effort), ("decider", "opus", "max"))
        self.assertTrue(str(request.schema_path).endswith("paper_judgment.json"))
        for path in ("research/REPORT.md", "research/OBJECTIVES.md", "research/OUTLINE.md"):
            self.assertIn(path, request.prompt)
        self.assertIn("contradiction:%s+%s" % (self.claim, self.other), request.prompt, "the batch is in the same session")
        self.assertIn("R3", request.prompt.split("# The lines the owner placed")[1].split("#")[0])

    def test_declining_writes_why_and_orders_nothing(self):
        outcome = self.judge(judgment(False, "The kill argument's points narrowed the claims too far for a paper yet."))
        self.assertFalse(outcome["ordered"])
        self.assertEqual(self.orders(), [])
        [judged] = self.journaled("paper_judged")
        self.assertEqual((judged["end"], judged["checks"], judged["ordered"]), ("objectives_closed", [], False))
        self.assertIn("narrowed the claims too far", judged["reason"])
        self.assertEqual(self.decided(), ["paper order: not now"])

    def test_ordering_answers_the_batch_and_orders_for_the_setups_venue(self):
        self.setup_answer({"decider": True, "venue": "nature-methods"})
        contradiction = "contradiction:%s+%s" % (self.claim, self.other)
        outcome = self.judge(judgment(True, answers=[
            answer(contradiction, "the first", "The first is the measured one."),
            answer("oversized:R1", "drop"),
            answer("outline:%s#1" % self.merges, "take"),
        ]))
        self.assertTrue(outcome["ordered"])
        [made] = self.orders()
        self.assertEqual((made["action"], made["by"], made["run"], made["venue"]),
                         ("ordered", "decider", "objectives_closed", "nature-methods"))
        batch = batches.read_batch(self.project, made["batch"])
        self.assertEqual(batch["status"], "closed", "every item is answered: the writer waits on nothing")
        by_ref = {item["ref"]: item for item in batch["items"]}
        self.assertTrue(all(item["by"] == "decider" for item in batch["items"]))
        self.assertEqual(by_ref[contradiction]["mark"], "the first")
        self.assertEqual(by_ref["oversized:R1"]["mark"], "split", "split, never dropped")
        self.assertIn("never dropped", by_ref["oversized:R1"]["note"])
        self.assertEqual(by_ref["outline:%s#1" % self.merges]["mark"], "decline", "R3 is a line the owner placed")
        self.assertIn("R3", by_ref["outline:%s#1" % self.merges]["note"])
        self.assertEqual(by_ref["figure:R1"]["mark"], by_ref["figure:R1"]["default"], "an item left unanswered takes code's default")
        [judged] = self.journaled("paper_judged")
        self.assertEqual((judged["ordered"], judged["order"], judged["venue"]), (True, 1, "nature-methods"))
        decided = {payload["answer"]: payload["decided_by"] for payload in self.journaled("decision")}
        self.assertEqual(self.decided()[0], "paper order: order it, as paper order 1 for nature-methods")
        self.assertEqual(decided["paper order 1 (%s): the first" % contradiction], "decider")
        self.assertEqual(decided["paper order 1 (oversized:R1): split"], "conductor", "code overrode the decider's drop")
        self.assertEqual(decided["paper order 1 (outline:%s#1): decline" % self.merges], "conductor")
        self.assertEqual(len(decided), 1 + len(batch["items"]), "the order and each answer of its batch")

    def test_the_owner_reversing_a_paper_decision_makes_the_order_theirs(self):
        from wayline import account
        self.judge(judgment(False, "Too early."))
        self.ledger.append_event("run_ended", {"reason": "objectives_closed"})
        self.assertTrue(paper_judge.considered(self.project, "objectives_closed"), "a new end is judged")
        identifier = "D%d" % len(self.journaled("decision"))
        with self.assertRaisesRegex(account.AccountError, "order the paper yourself"):
            account.review(self.project, identifier, "reverse", answer="order it")
        said = account.review(self.project, identifier, "reverse")
        self.assertIn("the paper order is yours from now on", said)
        self.assertFalse(paper_judge.considered(self.project, "objectives_closed"))

    def test_items_the_decider_left_out_are_code_s_defaults_listed_as_the_conductor_s(self):
        contradiction = "contradiction:%s+%s" % (self.claim, self.other)
        self.judge(judgment(True, answers=[answer(contradiction, "the first")]))
        by_answer = {payload["answer"]: payload["decided_by"] for payload in self.journaled("decision")}
        self.assertEqual(by_answer["paper order 1 (%s): the first" % contradiction], "decider")
        self.assertEqual(by_answer["paper order 1 (oversized:R1): split"], "conductor", "code's default, not the decider's")

    def test_a_usage_window_that_refuses_the_session_journals_nothing_and_raises_for_the_pause(self):
        refused = Envelope(api_error_status=429, is_error=True, exit_code=1, session_id="refused",
                           errors=["You've hit your session limit · resets 3:45pm (UTC)"])
        with self.assertRaises(gates.UsageLimited):
            self.judge(refused)
        self.assertEqual(self.journaled("paper_judged"), [])
        self.assertTrue(paper_judge.considered(self.project, "objectives_closed"), "judged after the pause")

    def test_a_ref_holding_parentheses_is_read_back_from_its_decision(self):
        self.assertEqual(paper_judge.decision_parts("paper order 2 (reference:doi:10.1016/S0140-6736(20)30183-5): drop"),
                         (2, "reference:doi:10.1016/S0140-6736(20)30183-5", "drop"))
        self.assertEqual(paper_judge.decision_parts("paper order: not now"), (None, None, "not now"))
        self.assertIsNone(paper_judge.decision_parts("paper venue: nature-methods"))

    def test_a_session_with_no_usable_judgment_is_resumed_once_then_recorded_as_not_judged(self):
        unknown = judgment(True, answers=[answer("figure:R9", "as planned")])
        outcome = self.judge(unknown, unknown)
        self.assertFalse(outcome["ordered"])
        self.assertEqual(len(self.calls), 2)
        self.assertIn("figure:R9", self.calls[1].message)
        [judged] = self.journaled("paper_judged")
        self.assertIsNone(judged["ordered"])
        self.assertIn("could not judge", judged["reason"])
        self.assertEqual(self.orders(), [])


# --- the conductor at a run's end ----------------------------------------------------------------------------------------


class EndCase(GatesRunCase):
    """`GatesRunCase`'s run end under `autonomous`: no plotting interpreter, so R1 stays undrawn and code's checks hold."""

    def setUp(self):
        super().setUp()
        self.set_harness(autonomy="autonomous")

    def conduct(self, *decider_envelopes, **options):
        original = worker.use_fake

        @contextmanager
        def scripted():
            with original() as fake:
                for envelope in decider_envelopes:
                    fake.script(envelope, role="decider")
                yield fake
        with mock.patch.object(worker, "use_fake", scripted):
            return super().conduct(**options)

    def judged(self):
        return [event["payload"] for event in self.events("paper_judged")]

    def deciders(self):
        return [call for call in self.calls if call.request.role == "decider"]


class EndKindsTest(EndCase):
    def test_at_objectives_closed_code_s_checks_hold_the_order_and_no_session_launches(self):
        self.close_the_objective(other=False)
        self.conduct(judgment(True))
        self.assertEqual(self.ended(), ["objectives_closed"])
        [judged] = self.judged()
        self.assertEqual((judged["end"], judged["ordered"]), ("objectives_closed", None))
        self.assertIn("drawn", [item["check"] for item in judged["checks"]])
        self.assertIn("R1", judged["reason"])
        self.assertEqual(self.deciders(), [], "no model call")
        self.assertLess(max(self.index("verdict")), self.index("paper_judged")[0], "after the run-end gates")
        self.assertLess(self.index("paper_judged")[0], self.index("run_ended")[0])
        self.assertEqual([event for event, _, _ in self.recorder.sent], ["run_ended"], "one end notice")

    def test_at_frontier_empty_the_order_is_judged_too(self):
        self.conduct()
        self.assertEqual(self.ended(), ["frontier_empty"])
        self.assertEqual([payload["end"] for payload in self.judged()], ["frontier_empty"])

    def test_after_budget_spent_a_strict_stall_a_stop_or_a_switch_nothing_is_judged(self):
        self.set_harness(budgets={"wallclock_hours": 1})
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "autonomous",
                                                 "radius": "moderate", "pid": 1})
        self.conduct(clock=lambda: time.time() + 2 * HOUR)
        self.assertEqual(self.ended(), ["budget_spent"])
        self.set_harness(budgets={"wallclock_hours": None})
        self.ledger.append_event("stall", {"waves": 3, "action": "stop"})
        self.conduct()
        self.assertEqual(self.ended(), ["budget_spent", "stall_strict"])
        for args, reason in (({"drain": False}, "stopped"), ({"drain": True, "switch_to": "/elsewhere"}, "switched")):
            projects.control(self.project, "stop", args)
            self.conduct()
        self.assertEqual(self.ended(), ["budget_spent", "stall_strict", "stopped", "switched"])
        self.assertEqual(self.judged(), [])

    def test_the_setup_s_no_leaves_the_order_to_the_owner(self):
        self.set_harness(paper_order={"decider": False, "venue": None})
        self.conduct()
        self.assertEqual(self.ended(), ["frontier_empty"])
        self.assertEqual(self.judged(), [])

    def test_a_replayed_wave_never_judges_the_same_end_again(self):
        self.ledger.append_event("paper_judged", {"end": "frontier_empty", "checks": [], "ordered": False,
                                                  "reason": "judged before the conductor died"})
        self.conduct(judgment(True))
        self.assertEqual(self.ended(), ["frontier_empty"])
        self.assertEqual(len(self.judged()), 1)
        self.assertEqual(self.deciders(), [])
        self.conduct()  # a later run's end is a new end, judged once more
        self.assertEqual(len(self.judged()), 2)

    def test_a_run_started_afresh_after_a_conductor_that_died_judges_its_own_end(self):
        self.ledger.append_event("paper_judged", {"end": "frontier_empty", "checks": [], "ordered": False,
                                                  "reason": "judged before the conductor died, with no run_ended"})
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "autonomous",
                                                 "radius": "moderate", "pid": 1})
        self.conduct()
        self.assertEqual(len(self.judged()), 2)


class OrderedRunCase(DrawingRunCase):
    """`DrawingRunCase`'s run end under `autonomous`: R1 drawn at the rest point, the gates passing, then the decider."""

    def setUp(self):
        super().setUp()
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["autonomy"] = "autonomous"
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        for section, heading, text in (("introduction", "Why products", "Feature products are a common baseline."),
                                       ("discussion", "Limits", "One split was read."),
                                       ("methods", "Data", "The synthetic set has two splits.")):
            sections.add_passage(self.ledger, section, heading, text, by="t3-a1")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "autonomous")

    def run_to_the_end(self, *decider, writer=True, waves=30):
        notices = []
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            for _ in range(4):
                fake.script(respond=Classifier(), role="classifier")
            for _ in range(12):
                fake.script(respond=Verifier(), role="verifier")
            if writer:
                fake.script(respond=Writer(self.project), role="writer")
            for envelope in decider:
                fake.script(envelope, role="decider")
            driven = Conductor(self.project, out=io.StringIO())
            driven.readings = machine.recorded
            driven.drawing_python = sys.executable
            driven.notify = lambda event, text, project=None, ticket=None: notices.append((event, text))
            self.addCleanup(driven.settle, 30)
            last = None
            for _ in range(waves):
                last = driven.wave()
                driven.settle()
                if last.ended:
                    break
            self.calls = list(fake.calls)
        self.driven, self.notices = driven, notices
        return last

    def judged(self):
        return [event["payload"] for event in self.events("paper_judged")]

    def index(self, predicate):
        return next(number for number, event in enumerate(self.events()) if predicate(event))

    def account(self):
        return (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")


class OrderedRunTest(OrderedRunCase):
    def test_the_decider_orders_the_paper_which_is_composed_titled_and_the_run_ends_as_judged(self):
        last = self.run_to_the_end(judgment(True, "The one objective-free result stands and the kill argument passed."),
                                   decision_envelope("title-2", rationale="The second title names the measured gain."))
        self.assertTrue(last.ended, self.driven.out.getvalue())
        self.assertEqual(last.reason, "frontier_empty")
        [judged] = self.judged()
        self.assertEqual((judged["end"], judged["ordered"], judged["order"]), ("frontier_empty", True, 1))
        actions = [(payload["action"], payload["by"]) for payload in (event["payload"] for event in self.events("paper_order"))]
        self.assertEqual(actions[0], ("ordered", "decider"))
        self.assertIn(("passed", "decider"), actions)
        drawn = self.index(lambda event: event["event"] == "drawing" and event["payload"]["outcome"] == "accepted")
        kill = self.index(lambda event: event["event"] == "verdict" and event["payload"]["verdict_type"] == "kill_argument")
        ordered = self.index(lambda event: event["event"] == "paper_judged")
        ended = self.index(lambda event: event["event"] == "run_ended")
        self.assertLess(drawn, kill)
        self.assertLess(kill, ordered, "the decider judges after the drawings and the run-end gates")
        self.assertLess(ordered, ended)
        self.assertEqual([payload["reason"] for payload in (event["payload"] for event in self.events("run_ended"))],
                         ["frontier_empty"], "one end, once the paper is made")
        title = (self.project / "research" / "paper" / "title.md").read_text(encoding="utf-8").strip()
        self.assertEqual(title, "How noise bends a polynomial fit", "the decider's pick of the writer's three titles")
        deciders = [call for call in self.calls if call.request.role == "decider"]
        self.assertEqual(len(deciders), 2, "the judgment, then the pick among the titles")
        self.assertIn("title-2: How noise bends a polynomial fit", deciders[1].request.prompt)
        decided = self.account().split("## Decided for you", 1)[1].split("\n## ", 1)[0]
        self.assertIn("the paper order: **order it, as paper order 1** (by the decider", decided)
        self.assertIn("paper order 1, `title`: **title-2, \"How noise bends a polynomial fit\"**", decided)
        [made] = [event["payload"] for event in self.events("paper_order") if event["payload"]["action"] == "ordered"]
        batch = batches.read_batch(self.project, made["batch"])
        self.assertEqual(batch["status"], "closed")
        for item in batch["items"]:
            self.assertEqual(item["by"], "decider")
            self.assertIn("paper order 1, `%s`: **%s**" % (item["ref"], item["mark"]), decided)
        record = json.loads((self.project / "research" / "paper" / "paper.json").read_text(encoding="utf-8"))
        self.assertEqual({answer["by"] for answer in record["answers"]}, {"decider"} if record["answers"] else set())
        rationale = [event["payload"]["rationale"] for event in self.events("decision")][0]
        self.assertEqual(rationale, "The one objective-free result stands and the kill argument passed.")
        self.assertEqual([event for event, _ in self.notices].count("run_ended"), 1, "one end notice")

    def test_the_decider_declining_ends_the_run_with_its_reason_and_no_paper(self):
        last = self.run_to_the_end(judgment(False, "One result is too little for a paper."), writer=False)
        self.assertEqual(last.reason, "frontier_empty")
        [judged] = self.judged()
        self.assertEqual((judged["ordered"], judged["reason"]), (False, "One result is too little for a paper."))
        self.assertEqual(self.events("paper_order"), [])
        self.assertIn("the paper order: **not now** (by the decider", self.account())


def decision_envelope(answer, rationale="It reads best.", confidence=0.7):
    return Envelope(structured_output={"question": "as asked", "options": [], "answer": answer, "rationale": rationale,
                                       "confidence": confidence, "decided_by": "decider", "reversible": True, "timestamp": None},
                    num_turns=3, duration_ms=10000)


class GoalEndTest(GoalTicketCase):
    def test_at_goal_reached_the_order_is_judged(self):
        self.set_harness(autonomy="autonomous")
        self.set_goal(target=0.9)
        results = self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)), waves=8)
        self.assertEqual(results[-1].reason, "goal_reached")
        judged = [event["payload"] for event in self.events("paper_judged")]
        self.assertEqual([payload["end"] for payload in judged], ["goal_reached"])
        self.assertIsNone(judged[0]["ordered"], "code's checks held it: nothing was drawn")
