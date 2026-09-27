"""Opus 5.5 in the roles and the verifier table (ticket 65; Implementation Decisions 11, 14, 15, and 16).

The shipped policy runs the planner, the writer, and the evolver on `opus xhigh`, the decider on `opus max`, and
reads work written on Opus in a fresh `opus max` session, so no role and no verdict draws on Fable's weekly
window. What is asserted is what the owner sees while that window is spent: each launch's model, effort, and
context cap as the fake launcher received it, no `FableHeld`, and a journal with no `fallback_from` in it.
"""

import io
import json
import time
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.test_changes import EvolveCase, answer, record
from tests.test_conductor import drive
from tests.test_decider import Q8_ANSWER, Q10_ANSWER, RecordedGrillCase, decision
from tests.test_fallback import FallbackCase
from tests.test_pacing import HOUR
from tests.test_plan import PlanCase, cut
from tests.test_plan import planned as planned_graph
from tests.test_report import GOOD_PROSE, Classifier, RunCase, prose, verdict
from tests.test_specify import SpecifyCase, draft
from tests.test_specify import planned as planned_spec
from tests.test_verdict_fallback import KINDS
from tests.test_verdicts import GateCase, passing
from wayline import changes, cli, decider, pacing, plan, worker
from wayline.project import set_model_fallback

OPUS_CAP = 200000
CONSENTS = ("auto", "wait", "ask", None)  # None: a project that never stated one, which waits as under ask


def spend_fable(ledger, consent="wait"):
    """Fable's weekly window read at 100%, and the hold the conductor journals at that reading, under `consent`."""
    ledger.append_event("pacing", {"five_hour": 0.1, "seven_day": 0.5, "fable": 1.0, "action": "normal", "fable_action": "stop"})
    ledger.append_event("paused", {"resets_at": pacing.iso(time.time() + 10 * HOUR), "window": "seven_day",
                                   "utilization": 1.0, "model": "fable"})
    if consent is not None:
        set_model_fallback(ledger.project, consent)


def fallbacks(events):
    """Every journaled event that says a launch, a verdict, or a decision fell back from Fable."""
    return [event for event in events if "fallback_from" in (event.get("payload") or {})]


class VerdictOnOpusTest(GateCase):
    """Criterion 3: work written on Opus is judged by a fresh `opus max` session at every reading of Fable's window."""

    def readings(self):
        """Fable's window unread, read low, and read spent under each consent: `(label, lay down)`."""
        yield "unread", lambda: None
        yield "read at 40%", lambda: self.ledger.append_event("pacing", {"five_hour": 0.1, "seven_day": 0.2, "fable": 0.4,
                                                                         "action": "normal", "fable_action": "normal"})
        for consent in CONSENTS:
            yield "spent under %s" % (consent or "no consent"), lambda consent=consent: spend_fable(self.ledger, consent)

    def test_every_kind_of_verdict_on_opus_work_is_a_fresh_opus_max_session_that_never_falls_back(self):
        for label, lay_down in self.readings():
            lay_down()
            for subject_kind, verdict_type, role in KINDS:
                with self.subTest(reading=label, kind=subject_kind):
                    taken = self.take(passing(), subject_kind=subject_kind, verdict_type=verdict_type, role=role, author_model="opus")
                    (call,) = self.calls
                    self.assertEqual((call.kind, call.session_id), ("launch", None), "a fresh session, never the author's")
                    self.assertEqual((call.request.role, call.request.model, call.request.effort), (role, "opus", "max"))
                    self.assertIn("verdicts", call.run_dir.parts)
                    self.assertEqual(list(json.loads(call.request.agent_text())), [role], "no agent of the author's rides inside it")
                    self.assertIsNone(taken.fallback_from)
        verdicts = self.events("verdict")
        self.assertEqual(len(verdicts), 6 * len(KINDS))
        self.assertEqual(fallbacks(verdicts), [])
        self.assertEqual({event["payload"]["model"] for event in verdicts}, {worker.RESOLVED_MODELS["opus"]})

    def test_work_written_on_fable_is_still_judged_at_opus_max(self):
        for label, lay_down in self.readings():
            lay_down()
            with self.subTest(reading=label):
                taken = self.take(passing(), author_model="fable")
                (call,) = self.calls
                self.assertEqual((call.kind, call.request.model, call.request.effort, taken.fallback_from), ("launch", "opus", "max", None))
        self.assertEqual(fallbacks(self.events("verdict")), [])


class ConductorVerdictOnOpusTest(FallbackCase):
    """Criterion 3 in the conductor: an Opus ticket done while Fable is held under `wait` is read and accepted at once."""

    def test_a_done_opus_tickets_verdict_is_taken_at_opus_max_and_does_not_wait(self):
        self.add(1, difficulty=3)  # rung 5, opus high
        self.hold_journaled(10)
        self.consent("wait")
        driven = self.conductor()
        self.script(1)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        (call,) = self.verifier_calls()
        self.assertEqual((call.kind, call.request.model, call.request.effort), ("launch", "opus", "max"))
        self.assertEqual(self.statuses(), {1: "accepted"})
        self.assertNotIn("wait for a verdict on Fable", driven.out.getvalue())
        self.assertEqual(fallbacks(self.events()), [])


class SpentWindowCase:
    """Fable's weekly window spent under `wait`, the strictest consent, before the role launches."""

    def launched(self):
        return self.fake.calls

    def assertLaunchedOnOpus(self, role, effort):
        calls = [call for call in self.launched() if call.request.role == role]
        self.assertTrue(calls, "no %s launched" % role)
        self.assertEqual({(call.request.model, call.request.effort) for call in calls}, {("opus", effort)})
        self.assertEqual({agent["model"] for call in calls for agent in json.loads(call.request.agent_text()).values()}, {"opus"})

    def assertNoFallback(self):
        self.assertEqual(fallbacks(self.events()), [])


class PlannerTest(SpentWindowCase, SpecifyCase):
    """Criteria 4 and 6: `wayline specify` drafts on `opus xhigh` with Fable spent, its records cut at Opus's cap."""

    def test_the_planner_drafts_the_spec_without_a_hold_or_a_fallback_under_the_opus_cap(self):
        spend_fable(self.ledger)
        self.script(planned_spec(draft()))
        with mock.patch.object(decider, "records_text", wraps=decider.records_text) as records:
            self.specify()
        self.assertLaunchedOnOpus(plan.PLANNER, "xhigh")
        self.assertEqual({call.args[1] for call in records.call_args_list}, {OPUS_CAP})
        self.assertLaunchedOnOpus("verifier", "max")
        self.assertNoFallback()


class PlanTest(SpentWindowCase, PlanCase):
    """Criteria 4 and 6: `wayline plan` cuts the graph on `opus xhigh` with Fable spent, its records cut at Opus's cap."""

    def test_the_planner_cuts_the_graph_without_a_hold_or_a_fallback_under_the_opus_cap(self):
        spend_fable(self.ledger)
        self.script(planned_graph(cut()))
        with mock.patch.object(plan, "_records", wraps=plan._records) as records:
            report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertLaunchedOnOpus(plan.PLANNER, "xhigh")
        self.assertEqual({call.args[1] for call in records.call_args_list}, {OPUS_CAP})
        self.assertNoFallback()


class DeciderTest(SpentWindowCase, RecordedGrillCase):
    """Criteria 4 and 6: the decider answers on `opus max` with Fable spent, its records cut at Opus's cap."""

    def test_the_decider_answers_without_a_hold_or_a_fallback_under_the_opus_cap(self):
        spend_fable(self.ledger)
        with mock.patch.object(decider, "records_text", wraps=decider.records_text) as records:
            report = self.decide_rest(Q8=decision(Q8_ANSWER), Q10=decision(Q10_ANSWER))
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(report["left"], [])
        self.assertLaunchedOnOpus(decider.DECIDER, "max")
        self.assertEqual({call.args[1] for call in records.call_args_list}, {OPUS_CAP})
        self.assertEqual({record["model"] for record in self.records().values() if record.get("decided_by") == "decider"},
                         {worker.RESOLVED_MODELS["opus"]})
        self.assertNoFallback()


class ReportVerifyTest(SpentWindowCase, RunCase):
    """Criterion 4: `wayline report --verify` drafts on `opus xhigh` and samples its claims with Fable spent."""

    def launched(self):
        return self.calls

    def test_the_writer_and_the_sampled_verdicts_launch_without_a_hold_or_a_fallback(self):
        spend_fable(self.book)
        spent = len(self.book.read_events()[0])  # the ended run's own journal already lists what fell back that night
        out = io.StringIO()
        with worker.use_fake() as fake:
            for _ in range(3):
                fake.script(respond=Classifier(), role="classifier")
            fake.script(prose(GOOD_PROSE), role="writer")
            for _ in range(7):
                fake.script(respond=lambda request, message: verdict(), role="verifier")
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = cli.main(["report", "--project", str(self.project), "--verify"])
            self.calls = list(fake.calls)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("7 of 7 tagged claims sampled: 7 passed", out.getvalue())
        self.assertNotIn("in place of Fable", out.getvalue())
        self.assertLaunchedOnOpus("writer", "xhigh")
        verifiers = [call for call in self.calls if call.request.role == "verifier"]
        self.assertEqual(len(verifiers), 7)
        self.assertEqual({call.request.model for call in verifiers}, {"opus"})
        read_at = {}
        for call in verifiers:
            for marker in ("`f-0001`", "`f-0002`", "Interaction terms carry"):
                if marker in call.request.prompt:
                    read_at[marker] = (call.request.model, call.request.effort)
        self.assertEqual(read_at, {"`f-0001`": ("opus", "high"), "`f-0002`": ("opus", "max"), "Interaction terms carry": ("opus", "max")},
                         "Sonnet's finding at opus high; Opus's finding and the writer's prose keep opus max")
        self.assertEqual(fallbacks(self.book.read_events()[0][spent:]), [])


class EvolveTest(SpentWindowCase, EvolveCase):
    """Criterion 4: `wayline evolve` runs the evolver on `opus xhigh` with Fable spent."""

    def test_the_evolver_launches_without_a_hold_or_a_fallback(self):
        spend_fable(self.ledger)
        self.fake.script(answer(record()), role=changes.EVOLVER)
        report = changes.evolve(self.project, notify=self.notify, pre_check=False)  # the hold read from the journal
        self.assertEqual(len(report["records"]), 1, report)
        self.assertLaunchedOnOpus(changes.EVOLVER, "xhigh")
        self.assertNoFallback()

    def events(self, name=None):
        found, _ = self.ledger.read_events()
        return [event for event in found if name is None or event["event"] == name]
