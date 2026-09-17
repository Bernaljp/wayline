"""Verdicts on Opus and the verdict principle (ticket 56; Implementation Decisions 11 and 15).

A verdict never comes from the session that wrote the work, and it may come from the author's own model in a
fresh session carrying none of the author's context. While Fable's weekly window is spent, a verdict whose table
verifier is Fable is taken by a fresh Opus session at the table's effort under the fallback consent `auto`, and
waits under `wait`, under `ask`, and on a project that never stated a consent. Nothing taken by fallback is taken
again after the reset.

The gates are driven with the fake launcher over the one-ticket project; the conductor over the hold project of
ticket 54, across a restart that replays the journal it left; claim sampling and the report over the ended run;
the depth spot-check over the absorb fixture; the decider's answer through the grill. What is asserted is what the
next process and the owner see: each call's kind, model, and effort, the journal's `verdict` and `decision`
events, the ticket statuses, `dossier.json`, `DECISIONS.md`, and the report section.
"""

import io
import json
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.test_absorb import SLUG, WORKFLOW, AbsorbTestCase
from tests.test_conductor import drive
from tests.test_fallback import FallbackCase
from tests.test_grill import GrillCase
from tests.test_pacing import HOUR
from tests.test_report import RunCase, verdict
from tests.test_verdicts import GateCase, failing, passing
from wayline import cli, gates, grill, pacing, replay, tickets, worker
from wayline.absorb import take_spot_check
from wayline.conductor import Conductor
from wayline.dossier import absorb_command, read_dossier
from wayline.grill import GrillError
from wayline.ledger import LedgerError, make_event
from wayline.project import policy_for, set_model_fallback
from wayline.provenance import verify_claims
from wayline.worker import Envelope

HELD_HOURS = 10
HARNESS = {"harness_tag": "v0.0.0", "autonomy": "autonomous", "radius": "moderate"}

# Every kind of verdict passes the one gate: (subject_kind, verdict_type, the judging role).
KINDS = (
    ("ticket", gates.QUALITY, "verifier"),
    ("claim", gates.CLAIM_SUPPORT, "verifier"),
    ("figure", gates.QUALITY, "verifier"),  # the figure honesty verdict of ticket 50 asks through this gate
    ("paper", gates.KILL_ARGUMENT, "verifier"),
    ("dossier", gates.DEPTH_SPOT_CHECK, "critic"),
)


def hold(ledger, hours=HELD_HOURS):
    """A hold on Fable's weekly window journaled now, resetting `hours` from now."""
    ledger.append_event("paused", {"resets_at": pacing.iso(time.time() + hours * HOUR), "window": "seven_day",
                                   "utilization": 1.0, "model": "fable"})


# --- the gate ------------------------------------------------------------------------------------------------------


class PrincipleTest(GateCase):
    """Criterion 1: the table may name the author's model, and every verdict is a fresh launch of its own."""

    def same_model(self):
        policy = policy_for(self.project)
        return dict(policy, verifier=dict(policy["verifier"], opus={"model": "opus", "effort": "max"}))

    def test_a_table_naming_the_authors_model_launches_a_fresh_session_on_it(self):
        taken = self.take(passing(), author_model="opus", policy=self.same_model())
        (call,) = self.calls
        self.assertEqual((call.kind, call.session_id), ("launch", None), "a launch, never a resume of the session that wrote the work")
        self.assertEqual((call.request.model, call.request.effort), ("opus", "max"))
        self.assertIn("verdicts", call.run_dir.parts)
        self.assertEqual(list(json.loads(call.request.agent_text())), ["verifier"], "no agent of the author's rides inside it")
        self.assertTrue(taken.passed)
        self.assertEqual(self.payload("verdict")["model"], "claude-opus-5")
        self.assertNotIn("fallback_from", self.payload("verdict"))

    def test_the_one_resume_a_verdict_takes_is_of_its_own_session(self):
        blocker = [{"text": "hello.txt holds two lines.", "locator": "hello.txt#L2", "severity": "blocker"}]
        taken = self.take(passing(findings=blocker), passing(), author_model="opus", policy=self.same_model())
        launch, resume = self.calls
        self.assertEqual((launch.kind, resume.kind), ("launch", "resume"))
        self.assertEqual(resume.session_id, taken.session_id)
        self.assertEqual(resume.run_dir.parent, launch.run_dir)

    def test_the_models_the_rules_name_are_the_launchers_aliases(self):
        self.assertLessEqual({pacing.FABLE, pacing.OPUS, pacing.HAIKU}, set(worker.MODEL_ALIASES))

    def test_the_tier_moves_only_a_verifier_on_fable(self):
        policy = policy_for(self.project)
        self.assertEqual(gates.verdict_tier(policy, "opus"), ("fable", "high", None))
        # `fallback_from` names the rung the verifier came from (decision 16), `fable high` being rung 7.
        self.assertEqual(gates.verdict_tier(policy, "opus", fall_back=True), ("opus", "high", "r7 fable high"))
        self.assertEqual(gates.verdict_tier(policy, "fable", fall_back=True), ("opus", "max", None))
        self.assertEqual(gates.verdict_tier(policy, "sonnet", fall_back=True), ("opus", "high", None))


class GateFallbackTest(GateCase):
    """Criterion 3 at the gate: a verifier on Fable is Opus at the table's effort under `auto`, and waits otherwise."""

    def held(self, consent, hours=HELD_HOURS):
        hold(self.ledger, hours)
        if consent is not None:
            set_model_fallback(self.project, consent)

    def take_kind(self, subject_kind, verdict_type, role, **options):
        return self.take(passing(), subject_kind=subject_kind, verdict_type=verdict_type, role=role, **options)

    def test_under_auto_every_kind_of_verdict_on_fable_is_a_fresh_opus_session_at_the_tables_effort(self):
        self.held("auto")
        for subject_kind, verdict_type, role in KINDS:
            with self.subTest(kind=subject_kind, verdict=verdict_type):
                taken = self.take_kind(subject_kind, verdict_type, role, author_model="opus")
                (call,) = self.calls
                self.assertEqual((call.kind, call.request.role, call.request.model, call.request.effort), ("launch", role, "opus", "high"))
                self.assertEqual({agent["model"] for agent in json.loads(call.request.agent_text()).values()}, {"opus"})
                payload = self.payload("verdict")
                self.assertEqual((taken.fallback_from, payload["fallback_from"], payload["model"]),
                         ("r7 fable high", "r7 fable high", "claude-opus-5"))

    def waits_under(self, consent, named):
        self.held(consent)
        for subject_kind, verdict_type, role in KINDS:
            with self.subTest(kind=subject_kind, verdict=verdict_type):
                with self.assertRaises(gates.FableHeld) as caught:
                    self.take_kind(subject_kind, verdict_type, role, author_model="opus")
                self.assertEqual(self.calls, [], "no session is spent on a verdict that waits")
                self.assertIn("under the fallback consent %s it waits for the reset" % named, str(caught.exception))
        self.assertEqual(self.events("verdict"), [])

    def test_under_wait_every_kind_of_verdict_on_fable_waits_and_no_session_is_spent(self):
        self.waits_under("wait", "wait")

    def test_under_ask_it_waits(self):
        self.waits_under("ask", "ask")

    def test_a_project_that_never_stated_a_consent_waits_as_under_ask(self):
        self.waits_under(None, "ask (unset)")

    def test_a_verifier_on_another_model_is_the_tables_under_every_consent(self):
        for consent in ("wait", "auto"):
            self.held(consent)
            for author, tier in (("fable", ("opus", "max")), ("sonnet", ("opus", "high"))):
                with self.subTest(consent=consent, author=author):
                    taken = self.take(passing(), author_model=author)
                    self.assertEqual((self.calls[0].request.model, self.calls[0].request.effort), tier)
                    self.assertIsNone(taken.fallback_from)

    def test_a_hold_whose_reset_has_passed_takes_the_verdict_on_fable(self):
        self.held("wait", hours=-1)
        taken = self.take(passing(), author_model="opus")
        self.assertEqual((self.calls[0].request.model, self.calls[0].request.effort, taken.fallback_from), ("fable", "high", None))

    def test_a_caller_that_decided_is_not_overruled_by_the_journal(self):
        self.held("wait")
        self.assertEqual(self.take(passing(), author_model="opus", fall_back=True).fallback_from, "r7 fable high")
        self.assertEqual(self.calls[0].request.model, "opus")
        set_model_fallback(self.project, "auto")
        self.assertIsNone(self.take(passing(), author_model="opus", fall_back=False).fallback_from)
        self.assertEqual(self.calls[0].request.model, "fable")

    def test_a_depth_spot_check_never_goes_to_haiku(self):
        policy = policy_for(self.project)
        policy = dict(policy, verifier=dict(policy["verifier"], opus={"model": "haiku", "effort": "low"}))
        with self.assertRaises(gates.GateError) as caught:
            self.take_kind("dossier", gates.DEPTH_SPOT_CHECK, "critic", author_model="opus", policy=policy)
        self.assertIn("never goes to Haiku", str(caught.exception))
        self.assertEqual(self.calls, [])


class KillArgumentFallbackTest(GateCase):
    """Both threads of the kill argument fall back together, or wait together."""

    def run_gate(self, *scripted):
        self.calls = []
        with worker.use_fake() as fake:
            for entry in scripted:
                if isinstance(entry, Envelope):
                    fake.script(entry)
                else:
                    fake.script(respond=entry)
            try:
                return gates.kill_argument(["research/REPORT.md"], project=self.project, author_model="opus")
            finally:
                self.calls = list(fake.calls)

    def memo(self):
        return failing(text="The headline claim rests on one seed.", locator="research/REPORT.md#L12", severity="major")

    def test_under_auto_both_threads_run_on_opus_at_high_and_the_adjudication_carries_fallback_from(self):
        hold(self.ledger)
        set_model_fallback(self.project, "auto")
        taken = self.run_gate(self.memo(), passing())
        self.assertEqual([(call.kind, call.request.model, call.request.effort) for call in self.calls], [("launch", "opus", "high")] * 2)
        (payload,) = [event["payload"] for event in self.events("verdict")]
        self.assertEqual((payload["verdict_type"], payload["fallback_from"], taken.fallback_from),
                         (gates.KILL_ARGUMENT, "r7 fable high", "r7 fable high"))

    def test_under_wait_neither_thread_is_spent(self):
        hold(self.ledger)
        set_model_fallback(self.project, "wait")
        with self.assertRaises(gates.FableHeld):
            self.run_gate(self.memo(), passing())
        self.assertEqual((self.calls, self.events("verdict")), ([], []))

    def test_a_hold_that_begins_while_the_memo_is_written_does_not_split_the_threads(self):
        def memo(request, message):
            hold(self.ledger)
            set_model_fallback(self.project, "auto")
            return self.memo()

        self.run_gate(memo, passing())
        self.assertEqual([call.request.model for call in self.calls], ["fable", "fable"])


# --- the conductor ---------------------------------------------------------------------------------------------------


class ConductorVerdictFallbackTest(FallbackCase):
    """Criterion 3 in the conductor, and criterion 6's replay: verdicts queued under `wait` and taken under `auto`."""

    def verdicts(self):
        return [item["payload"] for item in self.events("verdict")]

    def test_under_auto_a_done_tickets_verdict_on_fable_is_taken_by_a_fresh_opus_session_and_accepts_it(self):
        self.add(1, difficulty=3)  # written on Opus, so its diff read goes to the Fable verifier the table gives
        self.hold_journaled(HELD_HOURS)
        self.consent("auto")
        driven = self.conductor()
        self.script(1)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        (call,) = self.verifier_calls()
        self.assertEqual((call.kind, call.request.model, call.request.effort), ("launch", "opus", "high"))
        self.assertIn("verdicts", call.run_dir.parts)
        (payload,) = self.verdicts()
        self.assertEqual((payload["verdict_type"], payload["model"], payload["fallback_from"]),
                         ("diff", "claude-opus-5", "r7 fable high"))
        self.assertEqual(self.statuses(), {1: "accepted"})
        self.assertIn("falling back from r7 fable high", driven.out.getvalue())
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / "01-write-the-hello-file.md")
        self.assertIn("in place of r7 fable high, whose weekly window was spent", body)

    def test_under_wait_it_waits_a_difficulty_5_blocker_holds_its_dependent_and_auto_takes_it_once(self):
        self.add(1, difficulty=5)
        self.add(2, difficulty=1, blocked_by=[1])
        self.hold_journaled(HELD_HOURS)
        self.consent("auto")
        driven = self.conductor()
        self.script(1)
        self.script(2)
        self.assertEqual(driven.wave().launched, [1], "on Opus, by fallback")
        self.consent("wait")
        driven.settle()
        carried = driven.wave()
        self.assertEqual((carried.done, carried.launched, carried.accepted), ([1], [], []))
        self.assertEqual(self.verifier_calls(), [], "written on Opus, its result read goes to Fable, which waits under wait")
        self.assertEqual(self.statuses(), {1: "done", 2: "open"}, "a difficulty-5 blocker counts only when accepted")
        self.assertIn("wait for a verdict on Fable", driven.out.getvalue())
        self.assertEqual(driven.wave().launched, [])

        self.fake.script(passing(), role="verifier")
        self.consent("auto")
        judged = driven.wave()
        self.assertEqual((judged.accepted, judged.launched), ([1], []), "the wave picks before it drains its verdicts")
        (call,) = self.verifier_calls()
        self.assertEqual((call.kind, call.request.model, call.request.effort), ("launch", "opus", "high"))
        self.assertEqual(self.verdicts()[0]["fallback_from"], "r7 fable high")
        self.assertEqual(driven.wave().launched, [2], "accepted, the difficulty-5 blocker lets its dependent start")
        driven.settle()
        drive(driven)
        self.assertEqual(self.statuses(), {1: "accepted", 2: "done"})

        self.now[0] += (HELD_HOURS + 1) * HOUR
        again = Conductor(self.project, out=io.StringIO())
        again.clock = lambda: self.now[0]
        self.addCleanup(again.settle, 30)
        drive(again)
        self.assertEqual(len(self.verifier_calls()), 1, "a verdict taken by fallback is not taken again after the reset")
        self.assertEqual(replay.replay(self.events()).passed(1), {gates.RESULT})

    def test_a_hold_the_gate_meets_after_the_wave_decided_keeps_the_verdict_queued(self):
        self.add(1, difficulty=3)
        driven = self.conductor()
        self.script(1)
        self.fake.script(passing(), role="verifier")
        taken = gates.verdict_for
        met = []

        def gate(ask, **context):
            if not met:
                met.append(ask.verdict_type)
                raise gates.FableHeld("held since the wave read the consent")
            return taken(ask, **context)

        with mock.patch.object(gates, "verdict_for", side_effect=gate):
            drive(driven)
        self.assertEqual(met, ["diff"])
        self.assertIn("its diff verdict waits for Fable's weekly window", driven.out.getvalue())
        self.assertNotIn("could not be taken", driven.out.getvalue())
        self.assertEqual((self.verifier_calls(), self.statuses()), ([], {1: "done"}), "still queued, not dropped")
        self.assertEqual(driven.wave().accepted, [1], "the next wave takes it")
        self.assertEqual(len(self.verifier_calls()), 1)

    def test_a_restart_takes_under_auto_the_verdict_a_conductor_held_under_wait(self):
        self.add(1, difficulty=3)
        self.hold_journaled(HELD_HOURS)
        self.consent("wait")
        first = self.conductor()
        self.script(1)
        self.assertEqual(first.wave().launched, [1])
        first.settle()
        first.wave()
        self.assertEqual((self.statuses(), self.verifier_calls()), ({1: "done"}, []))
        # That conductor is gone with the queue it held in memory; the owner consents to fall back.
        self.consent("auto")
        self.fake.script(passing(), role="verifier")
        again = Conductor(self.project, out=io.StringIO())
        again.clock = lambda: self.now[0]
        self.addCleanup(again.settle, 30)
        drive(again)
        self.assertIn("was never taken; queued again", again.out.getvalue())
        (call,) = self.verifier_calls()
        self.assertEqual((call.kind, call.request.model, call.request.effort), ("launch", "opus", "high"))
        self.assertEqual((self.statuses(), self.verdicts()[0]["fallback_from"]), ({1: "accepted"}, "r7 fable high"))


# --- claim sampling, the depth spot-check, the report --------------------------------------------------------------


class ClaimFallbackTest(RunCase):
    """Claim sampling while Fable is spent: Opus under `auto`, a wait under `wait`, and nothing read again after the reset."""

    def setUp(self):
        super().setUp()
        self.render()

    def verify(self, scripted=7):
        with worker.use_fake() as fake:
            for _ in range(scripted):
                fake.script(respond=lambda request, message: verdict(), role="verifier")
            outcome = verify_claims(self.project)
            self.calls = list(fake.calls)
        return outcome

    def tiers(self):
        """`{marker: (model, effort)}` for Sonnet's finding, Opus's finding, and the Fable writer's prose."""
        found = {}
        for call in self.calls:
            for marker in ("`f-0001`", "`f-0002`", "Interaction terms carry"):
                if marker in call.request.prompt:
                    found[marker] = (call.request.model, call.request.effort)
        return found

    def claim_verdicts(self):
        return [event["payload"] for event in self.events("verdict") if event["payload"]["subject_kind"] == "claim"]

    def test_under_auto_a_claim_whose_verifier_is_fable_is_judged_on_opus_at_high(self):
        hold(self.book)
        set_model_fallback(self.project, "auto")
        outcome = self.verify()
        self.assertEqual((len(outcome["passed"]), outcome["waiting"], len(outcome["fell_back"])), (7, [], 2))
        self.assertEqual(self.tiers(), {"`f-0001`": ("opus", "high"), "`f-0002`": ("opus", "high"), "Interaction terms carry": ("opus", "max")})
        fell_back = [payload for payload in self.claim_verdicts() if payload.get("fallback_from")]
        self.assertEqual(len(fell_back), 2, "the claims of the two findings written on Opus, tickets 2 and 4")
        self.assertEqual({(payload["model"], payload["fallback_from"]) for payload in fell_back}, {("claude-opus-5", "r7 fable high")})

    def test_under_wait_those_claims_wait_the_rest_are_judged_and_a_pass_after_the_reset_takes_only_them(self):
        hold(self.book)
        set_model_fallback(self.project, "wait")
        first = self.verify()
        self.assertEqual((len(first["passed"]), len(first["waiting"])), (5, 2))
        self.assertNotIn("fable", [call.request.model for call in self.calls])
        self.assertFalse({payload["subject"] for payload in self.claim_verdicts()} & set(first["waiting"]))
        self.book.append_event("unpaused", {"model": "fable"})
        second = self.verify()
        self.assertEqual((second["already_verdicted"], sorted(second["passed"]), second["waiting"]), (5, sorted(first["waiting"]), []))
        self.assertEqual({call.request.model for call in self.calls}, {"fable"})

    def test_report_verify_lists_the_claims_it_judged_by_fallback_in_the_report_it_leaves(self):
        hold(self.book)
        set_model_fallback(self.project, "auto")
        renders = len(self.events("report_rendered"))
        out = io.StringIO()
        with worker.use_fake() as fake:
            for _ in range(7):
                fake.script(respond=lambda request, message: verdict(), role="verifier")
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = cli.main(["report", "--project", str(self.project), "--verify"])
            roles = {call.request.role for call in fake.calls}
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("2 judged on Opus in place of Fable", out.getvalue())
        self.assertEqual(self.section(6).count("- Verdict `claim_support` on the claim"), 2)
        self.assertEqual(len(self.events("report_rendered")), renders + 2, "rendered once more after the sampling")
        self.assertEqual(roles, {"verifier"}, "the second render launches nothing")

    def test_a_claim_judged_by_fallback_is_not_judged_again_after_the_reset(self):
        hold(self.book)
        set_model_fallback(self.project, "auto")
        self.verify()
        self.book.append_event("unpaused", {"model": "fable"})
        again = self.verify(scripted=0)
        self.assertEqual((again["already_verdicted"], self.calls), (7, []))


class SpotCheckFallbackTest(AbsorbTestCase):
    """Criterion 2 under the hold: a critic whose table verifier is Fable runs on Opus under `auto` and waits under `wait`."""

    def absorbed_under(self, consent):
        self.fake.script(respond=self.play_workflow(), role="absorb")
        self.absorb(fanout=WORKFLOW)
        (self.project / "harness.json").write_text(json.dumps(HARNESS), encoding="utf-8")
        set_model_fallback(self.project, consent)
        hold(self.ledger)

    def test_under_auto_the_critic_runs_on_opus_at_high_and_the_record_says_so(self):
        self.absorbed_under("auto")
        self.fake.script(Envelope(structured_output={"pass": True, "findings": [], "question_limit": "the listed items and flaws"}), role="critic")
        taken = take_spot_check(self.project, SLUG)
        critic = self.fake.calls[-1]
        self.assertEqual((critic.kind, critic.request.role, critic.request.model, critic.request.effort), ("launch", "critic", "opus", "high"))
        record = read_dossier(self.ledger, SLUG)["l2"]["spot_check"]
        self.assertEqual((record["status"], record["model"], record["fallback_from"]), ("passed", "claude-opus-5", "r7 fable high"))
        self.assertEqual(taken.payload["fallback_from"], "r7 fable high")
        self.assertIn("Taken on claude-opus-5 in place of r7 fable high", (self.refs / "dossier.md").read_text(encoding="utf-8"))

    def test_the_verb_prints_the_read_and_the_spot_check_that_waits_and_exits_0(self):
        (self.project / "harness.json").write_text(json.dumps(HARNESS), encoding="utf-8")
        set_model_fallback(self.project, "wait")
        hold(self.ledger)
        self.fake.script(respond=self.play_workflow(), role="absorb")
        config = self.temp / "claude-config"
        self.projects_dir = config / "projects"
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(config)}), redirect_stdout(out):
            code = absorb_command(["--level", "2", SLUG, "--project", str(self.project), "--spot-check"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("coverage   pass", out.getvalue())
        self.assertIn("spot-check queued for the critic: the depth_spot_check verdict", out.getvalue())
        self.assertIn("waits for the reset", out.getvalue())
        self.assertEqual([call.request.role for call in self.fake.calls], ["absorb"])

    def test_under_wait_it_stays_queued_and_no_session_is_spent(self):
        self.absorbed_under("wait")
        spent = len(self.fake.calls)
        with self.assertRaises(gates.FableHeld):
            take_spot_check(self.project, SLUG)
        self.assertEqual(len(self.fake.calls), spent)
        self.assertEqual(read_dossier(self.ledger, SLUG)["l2"]["spot_check"]["status"], "queued")


class ReportSectionTest(RunCase):
    """Criterion 5: the section after the tickets closed, rendered from the ended run's journal."""

    def test_every_verdict_and_decision_taken_by_fallback_is_listed_after_the_tickets_closed(self):
        self.render()
        text = self.text()
        self.assertLess(text.index("## 5. Tickets closed: done and accepted"), text.index("## 6. Judged on Opus while Fable was spent"))
        sixth = self.section(6)
        self.assertIn("- Verdict `diff` on the ticket `research/tickets/02` (ticket 2): passed on claude-opus-5 in place of fable", sixth)
        self.assertIn("- Decision by the decider on ticket 8, *Which held-out split does the goal read?*: **split_b** on claude-opus-5 "
                      "in place of fable", sixth)
        self.assertIn("None of them is taken again on Fable after the reset.", sixth)
        self.assertNotIn("research/tickets/01", sixth, "a verdict on the table's own model is not listed")
        self.assertNotIn("20000 rows", sixth, "an answer no model gave is not listed")

    def test_a_run_that_judged_nothing_by_fallback_says_so(self):
        journal = self.project / "research" / "journal.jsonl"
        kept = [line for line in journal.read_text(encoding="utf-8").splitlines(keepends=True) if '"fallback_from"' not in line]
        journal.write_text("".join(kept), encoding="utf-8")
        self.render()
        self.assertIn("Nothing was judged by fallback", self.section(6))


# --- the decision ----------------------------------------------------------------------------------------------------


class DecisionModelTest(GrillCase):
    """Criterion 4: `decision` carries `model` and `fallback_from`, so the decider's answers record the model they ran on."""

    QUESTION = "How many seeds does a comparison use?"

    def test_the_deciders_answer_journals_the_model_it_ran_on_and_its_fallback(self):
        grill.ask(self.project, self.QUESTION)
        record = grill.answer(self.project, "Q1", "three", "policy.json says three", confidence=0.7, decided_by="decider",
                              model="claude-opus-5", fallback_from="fable")
        self.assertEqual((record["model"], record["fallback_from"]), ("claude-opus-5", "fable"))
        (payload,) = [event["payload"] for event in self.events("decision")]
        self.assertEqual((payload["decided_by"], payload["model"], payload["fallback_from"]), ("decider", "claude-opus-5", "fable"))
        self.assertIn("- model: claude-opus-5 in place of fable, whose weekly window was spent", self.decisions_md())
        self.assertEqual(grill.read_records(self.project)[0]["fallback_from"], "fable", "DECISIONS.md reads back what it wrote")

    def test_an_answer_no_model_gave_carries_neither_and_a_revision_does_not_inherit_them(self):
        grill.ask(self.project, self.QUESTION)
        grill.answer(self.project, "Q1", "three", "policy.json says three", decided_by="decider", model="claude-opus-5", fallback_from="fable")
        revised = grill.answer(self.project, "Q1", "five", "the owner wants five", revise=True)
        self.assertEqual([key for key in ("model", "fallback_from") if key in revised], [])
        owner = [event["payload"] for event in self.events("decision")][-1]
        self.assertEqual((owner["decided_by"], "model" in owner, "fallback_from" in owner), ("human", False, False))

    def test_a_fallback_naming_no_model_or_another_model_and_a_model_on_the_owners_answer_are_refused(self):
        grill.ask(self.project, self.QUESTION)
        for decided_by, model, fallback_from in (("decider", None, "fable"), ("decider", "claude-opus-5", "opus"),
                                                 ("human", "claude-opus-5", None), ("human", "claude-opus-5", "fable")):
            with self.subTest(decided_by=decided_by, model=model, fallback_from=fallback_from):
                with self.assertRaises(GrillError):
                    grill.answer(self.project, "Q1", "three", "why", decided_by=decided_by, model=model, fallback_from=fallback_from)
        self.assertEqual(self.events("decision"), [])

    def test_the_journal_takes_fallback_from_as_fable_on_a_decision_and_as_a_rung_on_a_verdict(self):
        """A decision names the model it fell back from; a launch and a verdict name the rung (ticket 62, decision 16)."""
        decision = {"ticket": 8, "answer": "split_b", "decided_by": "decider", "model": "claude-opus-5"}
        make_event("decision", dict(decision, fallback_from="fable"))
        with self.assertRaises(LedgerError):
            make_event("decision", dict(decision, fallback_from="opus"))
        verdict_payload = {"subject_kind": "ticket", "subject": "t", "verdict_type": "diff", "pass": True, "model": "claude-opus-5"}
        for came_from in ("fable", "r7 fable high", "r6 fable low"):
            with self.subTest(fallback_from=came_from):
                make_event("verdict", dict(verdict_payload, fallback_from=came_from))
