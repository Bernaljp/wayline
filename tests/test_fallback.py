"""Fall back to Opus under the fallback consent (ticket 55; Implementation Decision 15).

The consent is driven through `wayline switch --fallback` and `wayline intake` on a laid-out project
and read back from `harness.json` and the journal. The conductor is driven with the fake launcher
over the one-ticket project grown by tickets on Fable (difficulty 4 and 5) and Opus (difficulty 3),
with the hold on Fable's weekly window journaled or begun by a scripted refusal, and a clock the
test moves. What is asserted is what the owner and the next process see: each `LaunchRequest` the
launcher received (its model, effort, budget, context cap, and agent models), the journal, the
replayed view, the ticket statuses, and the hold line `wayline status` prints.
"""

import io
import json
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.test_conductor import ConductorCase, done, drive, patch
from tests.test_fable_hold import HoldCase, journal_ts, refused, rejected_on_fable
from tests.test_pacing import HOUR
from tests.test_report import RunCase, verdict
from tests.test_verdicts import passing
from wayline import cli, dashboard, intake, pacing, project, replay, tickets, worker
from wayline.conductor import Conductor
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger
from wayline.project import fallback_consent, read_harness, render_status, set_model_fallback, status_view
from wayline.provenance import verify_claims
from wayline.worker import Envelope, LaunchRequest

RESETS = "2026-09-16T02:00:00Z"


def run(*arguments):
    """`wayline <verb>` in process, with its output captured: the exit code, stdout, and stderr."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


class ConsentTest(ConductorCase):
    """Criteria 1 and 2: `model_fallback` in `harness.json`, and `wayline switch --fallback` writing it and journaling `control`."""

    def switch(self, *arguments):
        return run("switch", *arguments, "--project", str(self.project))

    def controls(self):
        return [item["payload"] for item in self.events("control")]

    def hold_the_conductor(self):
        heartbeat = Ledger(self.project).heartbeat().acquire()
        self.addCleanup(heartbeat.release)
        heartbeat.write(pid=4242, started_at="2026-09-13T10:00:00.000Z", last_wave_at=None, harness_tag="v0.0.0")

    def test_a_project_without_the_key_behaves_as_ask_and_stays_distinguishable_from_an_explicit_ask(self):
        harness = read_harness(self.project)
        self.assertNotIn("model_fallback", harness, "init records no consent: the intake asks it")
        self.assertEqual(fallback_consent(harness), ("ask", False))
        self.assertEqual(fallback_consent(dict(harness, model_fallback="ask")), ("ask", True))
        self.assertEqual(fallback_consent(dict(harness, model_fallback="auto")), ("auto", True))

    def test_the_harness_schema_takes_the_three_consents_and_nothing_else(self):
        harness = read_harness(self.project)
        for consent in ("auto", "ask", "wait"):
            check(dict(harness, model_fallback=consent), load_schema("harness"))
        with self.assertRaises(ValidationError):
            check(dict(harness, model_fallback="sometimes"), load_schema("harness"))

    def test_switch_fallback_writes_harness_json_first_and_then_journals_control(self):
        written = []
        original = project.control

        def control(*arguments, **options):
            written.append(read_harness(self.project).get("model_fallback"))
            return original(*arguments, **options)

        with mock.patch.object(project, "control", control):
            code, out, err = self.switch("--fallback", "auto")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(written, ["auto"], "harness.json already said auto when control was journaled")
        self.assertEqual(read_harness(self.project)["model_fallback"], "auto")
        self.assertEqual(self.controls(), [{"command": "model_fallback", "args": {"model_fallback": "auto"}, "by": "cli"}])
        self.assertIn("ask (unset)", out)
        self.assertIn("no conductor is running", out)

    def test_any_consent_is_accepted_at_any_time_with_a_conductor_running(self):
        self.hold_the_conductor()
        for consent in ("wait", "auto", "ask"):
            code, out, err = self.switch("--fallback", consent)
            self.assertEqual(code, 0, out + err)
            self.assertIn("4242", out)
        self.assertEqual([payload["args"] for payload in self.controls()],
                         [{"model_fallback": "wait"}, {"model_fallback": "auto"}, {"model_fallback": "ask"}])
        self.assertEqual(fallback_consent(read_harness(self.project)), ("ask", True), "an explicit ask is written, not left unset")
        self.assertEqual(json.loads((self.project / "harness.json").read_text(encoding="utf-8"))["radius"], "moderate",
                         "the rest of harness.json is kept")

    def test_the_same_consent_again_changes_nothing_and_an_explicit_ask_on_a_project_without_the_key_does(self):
        self.assertEqual(self.switch("--fallback", "ask")[0], 0)
        self.assertEqual(len(self.controls()), 1, "unset and ask behave alike, and are still two settings")
        code, out, _ = self.switch("--fallback", "ask")
        self.assertEqual(code, 0)
        self.assertIn("already", out)
        self.assertEqual(len(self.controls()), 1)

    def test_a_consent_the_running_conductor_holds_apart_from_the_file_is_still_journaled(self):
        self.assertEqual(self.switch("--fallback", "wait")[0], 0)
        Ledger(self.project).append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "checkpoints",
                                                          "radius": "moderate", "pid": 4242})
        self.hold_the_conductor()
        self.ledger.append_event("control", {"command": "model_fallback", "args": {"model_fallback": "auto"}, "by": "dashboard"})
        code, out, err = self.switch("--fallback", "wait")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("already", out)
        self.assertEqual(replay.replay(self.events()).model_fallback, "wait")

    def test_switch_refuses_a_consent_it_does_not_know_and_a_project_path_beside_the_flag(self):
        self.assertEqual(self.switch("--fallback", "sometimes")[0], 2)
        code, _, err = run("switch", str(self.project), "--fallback", "auto")
        self.assertEqual(code, 2)
        self.assertIn("--fallback", err)
        code, _, err = self.switch("--fallback", "auto", "--autonomy", "autonomous")
        self.assertEqual(code, 2)
        self.assertEqual(self.controls(), [])

    def test_the_dashboard_action_calls_the_same_function(self):
        report = set_model_fallback(self.project, "wait", by="dashboard")
        self.assertEqual((report["from"], report["to"], report["changed"]), (None, "wait", True))
        self.assertEqual(self.controls()[0]["by"], "dashboard")


class ConsentReplayTest(unittest.TestCase):
    """Criterion 2 by replay: a `control model_fallback` holds for the run it arrived in, over `harness.json`."""

    @staticmethod
    def control(consent):
        return {"event": "control", "payload": {"command": "model_fallback", "args": {"model_fallback": consent}, "by": "cli"}}

    def test_the_view_takes_each_consent_for_the_open_run_and_forgets_it_when_the_run_ends(self):
        view = replay.replay([self.control("auto")])
        self.assertIsNone(view.model_fallback, "no run is open: harness.json, which the switch wrote first, says it")
        replay.replay([{"event": "run_started", "payload": {"autonomy": "checkpoints"}}], view)
        for consent in ("auto", "wait", "ask"):
            replay.replay([self.control(consent)], view)
            self.assertEqual(view.model_fallback, consent)
            self.assertEqual(fallback_consent({"model_fallback": "wait"}, view), (consent, True))
        replay.replay([self.control("sometimes")], view)
        self.assertEqual(view.model_fallback, "ask", "a consent nobody can hold is passed over")
        replay.replay([{"event": "run_ended", "payload": {"reason": "stopped"}}], view)
        self.assertIsNone(view.model_fallback)
        self.assertEqual(fallback_consent({"model_fallback": "wait"}, view), ("wait", True))
        self.assertEqual(fallback_consent({}, view), ("ask", False))
        replay.replay([{"event": "run_started", "payload": {"autonomy": "checkpoints"}}, self.control("auto")], view)
        replay.replay([{"event": "run_started", "payload": {"autonomy": "checkpoints"}}], view)
        self.assertIsNone(view.model_fallback, "a new run starts from harness.json")


class IntakeConsentTest(ConductorCase):
    """Criterion 1: the intake records the consent beside autonomy and budgets, and never invents one."""

    def intake(self, *arguments, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = intake.intake_command(["--project", str(self.project), *arguments], stdin=stdin)
        return code, out.getvalue(), err.getvalue()

    def autonomy_section(self):
        text = (self.project / "research" / "INTAKE.md").read_text(encoding="utf-8")
        return text.split("## Autonomy", 1)[1].split("\n## ", 1)[0]

    def test_the_consent_lands_beside_autonomy_in_harness_json_and_in_intake_md(self):
        code, out, err = self.intake("--intent", "a question", "--autonomy", "autonomous", "--model-fallback", "auto", "--gpu-hours", "2")
        self.assertEqual(code, 0, out + err)
        harness = read_harness(self.project)
        self.assertEqual(harness["model_fallback"], "auto")
        keys = list(harness)
        self.assertEqual(keys.index("model_fallback"), keys.index("radius") + 1)
        self.assertIn("`auto`", self.autonomy_section())
        self.assertIn("fallback auto", out)
        self.assertEqual(self.events("control"), [], "no run is open, so harness.json alone says it")

    def test_an_intake_that_does_not_state_it_writes_no_key_and_keeps_one_stated_before(self):
        self.assertEqual(self.intake("--intent", "a question")[0], 0)
        self.assertNotIn("model_fallback", read_harness(self.project))
        self.assertIn("not stated", self.autonomy_section())
        self.assertIn("`ask`", self.autonomy_section())
        self.assertEqual(self.intake("--intent", "a question", "--model-fallback", "wait")[0], 0)
        self.assertEqual(self.intake("--intent", "the same question, restated")[0], 0)
        self.assertEqual(read_harness(self.project)["model_fallback"], "wait")

    def start_run(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": 4242})
        heartbeat = Ledger(self.project).heartbeat().acquire()
        self.addCleanup(heartbeat.release)
        heartbeat.write(pid=4242, started_at="2026-09-13T10:00:00.000Z", last_wave_at=None, harness_tag="v0.0.0")
        return heartbeat

    def test_an_intake_during_a_run_that_heard_another_consent_journals_it_for_that_run(self):
        self.start_run()
        set_model_fallback(self.project, "wait")
        code, out, err = self.intake("--intent", "a question", "--model-fallback", "auto")
        self.assertEqual(code, 0, out + err)
        self.assertEqual([item["payload"]["args"] for item in self.events("control")], [{"model_fallback": "wait"}, {"model_fallback": "auto"}])
        self.assertEqual(replay.replay(self.events()).model_fallback, "auto")

    def test_a_consent_a_run_heard_does_not_outlive_the_run(self):
        heartbeat = self.start_run()
        set_model_fallback(self.project, "auto")
        self.ledger.append_event("paused", {"resets_at": pacing.iso(time.time() + 10 * HOUR), "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"})
        self.assertTrue(project.fable_falls_back(self.project))
        self.ledger.append_event("run_ended", {"reason": "stopped"})
        heartbeat.release()
        self.assertEqual(self.intake("--intent", "a question", "--model-fallback", "wait")[0], 0)
        self.assertEqual(fallback_consent(read_harness(self.project), replay.replay(self.events())), ("wait", True))
        self.assertFalse(project.fable_falls_back(self.project), "the report's writer waits as the owner said")
        self.assertEqual(status_view(self.project)["hold"]["consent"], "wait")
        self.assertFalse(set_model_fallback(self.project, "wait")["changed"])

    def test_a_spec_carries_it_and_a_consent_nobody_can_hold_is_refused(self):
        code, _, err = self.intake("--from", "-", stdin=io.StringIO(json.dumps({"intent": "a question", "model_fallback": "ask"})))
        self.assertEqual(code, 0, err)
        self.assertEqual(fallback_consent(read_harness(self.project)), ("ask", True))
        code, _, err = self.intake("--from", "-", stdin=io.StringIO(json.dumps({"intent": "a question", "model_fallback": "sometimes"})))
        self.assertEqual(code, 2)
        self.assertIn("model_fallback", err)


class FallBackTest(unittest.TestCase):
    """Criterion 3 on the request: `worker.fall_back` moves the model and every agent on Fable to Opus, and nothing else."""

    def request(self, model, agents):
        return LaunchRequest(role="coder", model=model, effort="xhigh", prompt="the prompt", agent_json=agents, max_minutes=180)

    def test_the_launch_and_every_agent_it_defines_on_fable_move_to_opus(self):
        agents = {"coder": {"model": "fable", "effort": "xhigh", "maxTurns": 200},
                  "reader": {"model": "sonnet", "effort": "medium"}, "judge": {"model": "fable", "effort": "high"}}
        original = self.request("fable", agents)
        moved, changed = worker.fall_back(original)
        self.assertTrue(changed)
        self.assertEqual((moved.model, moved.effort, moved.max_minutes, moved.prompt), ("opus", "xhigh", 180, "the prompt"))
        self.assertEqual({name: agent["model"] for name, agent in moved.agent_json.items()},
                         {"coder": "opus", "reader": "sonnet", "judge": "opus"})
        self.assertEqual(moved.agent_json["coder"]["maxTurns"], 200)
        self.assertEqual((original.model, original.agent_json["coder"]["model"]), ("fable", "fable"), "the request it was given is left as it was")
        self.assertFalse(worker.launches_on(moved, "fable"))

    def test_agents_given_as_text_come_back_as_text_and_a_launch_with_nothing_on_fable_is_unchanged(self):
        moved, changed = worker.fall_back(self.request("sonnet", json.dumps({"coder": {"model": "fable", "effort": "low"}})))
        self.assertTrue(changed)
        self.assertEqual((moved.model, json.loads(moved.agent_json)["coder"]["model"]), ("sonnet", "opus"))
        untouched = self.request("opus", {"coder": {"model": "opus", "effort": "high"}})
        self.assertEqual(worker.fall_back(untouched), (untouched, False))


class FallbackCase(HoldCase):
    """The hold project with the consent set as the owner sets it, and the calls the launcher received read by ticket."""

    def consent(self, value):
        set_model_fallback(self.project, value)

    def calls(self, identifier):
        return [call for call in self.fake.calls if call.request.env.get("WAYLINE_TICKET") == str(identifier)]

    def launches(self, identifier):
        return [item["payload"] for item in self.events("ticket_launched") if item["payload"]["ticket"] == identifier]

    def packed(self, identifier, characters):
        """Ticket `identifier` carries one context pack entry of `characters` characters."""
        (self.project / "notes.md").write_text("x" * characters, encoding="utf-8")
        fields = {item["id"]: item for item in tickets.read_tickets(self.project)}[identifier]
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))
        tickets.write_ticket(self.ledger, dict(fields, context_pack=["notes.md"]), body)


class FallbackLaunchTest(FallbackCase):
    """Criterion 3: under `auto` a held Fable launch runs on Opus at its own effort and budget, under Opus's cap."""

    def test_under_auto_held_fable_tickets_launch_on_opus_at_their_own_effort_and_budget_under_the_opus_cap(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=5)
        self.add(3, difficulty=3)
        self.packed(1, 400)
        self.packed(2, 400)
        self.hold_journaled(10)
        self.consent("auto")
        driven = self.conductor(workers=3)
        driven.policy = dict(driven.policy, context_pack={"max_chars": {"sonnet": 100, "opus": 150, "fable": 1000}})
        for identifier in (1, 2, 3):
            self.script(identifier)
        self.assertEqual(sorted(driven.wave().launched), [1, 2, 3])

        for identifier, effort, came_from in ((1, "low", "r6 fable low"), (2, "high", "r7 fable high")):  # rungs 6 and 7 fall back to opus at the same effort (decision 16)
            with self.subTest(ticket=identifier):
                (call,) = self.calls(identifier)
                request = call.request
                self.assertEqual((call.kind, request.model, request.effort, request.max_minutes), ("launch", "opus", effort, 180))
                agents = json.loads(request.agent_text())
                self.assertEqual({agent["model"] for agent in agents.values()}, {"opus"})
                self.assertEqual({(agent["effort"], agent["maxTurns"]) for agent in agents.values()}, {(effort, 200)})
                self.assertIn("cut here at the context cap; 250 character(s) are missing", request.prompt)
                (launched,) = self.launches(identifier)
                self.assertEqual((launched["model"], launched["effort"], launched["fallback_from"], launched["context_chars"]),
                                 ("opus", effort, came_from, 150), "fallback_from names the Fable rung it came from")
        (opus,) = self.calls(3)
        self.assertEqual((opus.request.model, opus.request.effort), ("opus", "high"))
        self.assertNotIn("fallback_from", self.launches(3)[0], "a launch that was on Opus all along did not fall back")
        self.assertIn("falling back from r6 fable low", driven.out.getvalue())

        for _ in range(6):
            self.fake.script(passing(), role="verifier")
        driven.settle()
        carried = driven.wave()
        self.assertEqual((sorted(carried.done), sorted(carried.accepted)), ([1, 2, 3], [1, 2, 3]),
                         "every verdict here runs on Fable, and under auto a fresh Opus session takes it (ticket 56)")
        self.assertEqual({(call.kind, call.request.model, call.request.effort) for call in self.verifier_calls()}, {("launch", "opus", "high")})
        self.assertEqual({item["payload"].get("fallback_from") for item in self.events("verdict")}, {"r7 fable high"},
                         "a verdict names the Fable rung its verifier came from (decision 16)")
        self.assertEqual({item["difficulty"] for item in tickets.read_tickets(self.project) if item["id"] in (1, 2)}, {4, 5},
                         "the difficulty is the ticket's, whatever model it ran on")

    def waits_under(self, consent):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        self.hold_journaled(10)
        if consent is not None:
            self.consent(consent)
        driven = self.conductor()
        self.script(2)
        self.assertEqual(driven.wave().launched, [2])
        driven.settle()
        driven.wave()
        self.assertEqual((self.calls(1), self.launches(1)), ([], []))
        self.assertEqual(self.statuses()[1], "open")

    def test_under_wait_a_held_fable_ticket_waits_while_the_rest_launch(self):
        self.waits_under("wait")

    def test_under_ask_it_waits_and_so_it_does_on_a_project_that_never_recorded_a_consent(self):
        self.waits_under("ask")

    def test_a_project_without_the_key_waits_as_under_ask(self):
        self.waits_under(None)

    def test_a_control_model_fallback_mid_run_is_applied_at_the_next_wave(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=4)
        self.hold_journaled(10)
        self.consent("wait")
        driven = self.conductor()
        self.script(1)
        self.script(2)
        self.assertEqual(driven.wave().launched, [])
        set_model_fallback(self.project, "auto", by="dashboard")
        self.assertEqual(driven.wave().launched, [1])
        self.assertEqual(self.launches(1)[0]["fallback_from"], "r6 fable low")
        set_model_fallback(self.project, "wait")
        driven.settle()
        carried = driven.wave()
        self.assertEqual((carried.done, carried.launched), ([1], []), "back to wait: ticket 2 waits")
        set_model_fallback(self.project, "auto")
        self.assertEqual(driven.wave().launched, [2])
        self.assertEqual([call.request.model for call in self.fake.calls], ["opus", "opus"])
        self.assertIn("fallback consent is now auto", driven.out.getvalue())
        self.assertEqual(fallback_consent(read_harness(self.project), replay.replay(self.events())), ("auto", True))


class FallbackSessionTest(FallbackCase):
    """Criterion 5: a held Fable session is started again as a fresh Opus session in the same attempt, never resumed on Opus."""

    def refused_then_carried(self, envelope, consent="auto"):
        self.add(1, difficulty=4)
        self.consent(consent)
        driven = self.conductor()
        resets = int(self.now[0]) + 3 * HOUR
        self.script(1, rejected_on_fable(resets), envelope=envelope)
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        driven.settle()
        driven.wave()
        return driven

    def test_under_auto_a_session_refused_before_its_first_turn_is_relaunched_on_opus_at_once(self):
        driven = self.refused_then_carried(refused())
        self.assertEqual([(call.kind, call.request.model) for call in self.calls(1)], [("launch", "fable"), ("launch", "opus")])
        first, again = self.launches(1)
        self.assertEqual((first["attempt"], again["attempt"]), (1, 1), "the same attempt")
        self.assertNotIn("fallback_from", first)
        self.assertEqual((again["model"], again["effort"], again["fallback_from"]), ("opus", "low", "r6 fable low"))
        self.assertLess(self.index("paused", model="fable"), self.index("ticket_launched", fallback_from="r6 fable low"))
        self.assertNotIn("partial work", self.calls(1)[1].request.prompt, "a refused session left nothing behind")
        self.assertNotIn("relaunching it", driven.out.getvalue(), "the fallback is said once, by the line that launches it")
        self.assertEqual(driven.out.getvalue().count("never started work; it is launched again on opus low"), 1)
        drive(driven)
        self.assertEqual(self.statuses(), {1: "done"})

    def test_under_auto_a_session_stopped_mid_work_continues_as_a_fresh_opus_session_in_the_same_attempt_and_worktree(self):
        driven = self.refused_then_carried(refused(answered=True, num_turns=12))
        stopped, fresh = self.calls(1)
        self.assertEqual([(call.kind, call.request.model) for call in (stopped, fresh)], [("launch", "fable"), ("launch", "opus")],
                         "a Fable transcript is never resumed on Opus")
        self.assertEqual(fresh.request.cwd, stopped.request.cwd)
        self.assertIn("partial work", fresh.request.prompt)
        relaunch = self.payload("ticket_resumed")
        self.assertEqual((relaunch["reason"], relaunch["session_id"], relaunch["attempt"]), ("worker_died", None, 1))
        self.assertEqual((self.launches(1)[-1]["attempt"], self.launches(1)[-1]["fallback_from"]), (1, "r6 fable low"))
        kept = self.project / "research" / "sessions" / "1" / "1" / "stopped-1" / "stream.jsonl"
        self.assertTrue(kept.is_file(), "the stopped session's stream is kept beside the fresh one")
        latest = replay.replay(self.events()).tickets[1].latest
        self.assertEqual((latest.number, latest.model, latest.fallback_from), (1, "opus", "r6 fable low"))
        drive(driven)
        self.assertEqual(self.statuses(), {1: "done"})

    def test_under_auto_a_gate_resume_stopped_at_the_limit_hands_the_message_it_was_answering_to_the_fresh_session(self):
        self.add(1, difficulty=4)
        self.consent("auto")
        driven = self.conductor()
        self.fake.script(done(), ticket=1)  # no hello.txt, so the acceptance fails and its resume runs on Fable
        self.script(1, rejected_on_fable(int(self.now[0]) + 3 * HOUR), envelope=refused(answered=True, num_turns=12))
        self.script(1)
        drive(driven)
        self.assertEqual([(call.kind, call.request.model) for call in self.calls(1)],
                         [("launch", "fable"), ("resume", "fable"), ("launch", "opus")])
        fresh = self.calls(1)[2].request.prompt
        self.assertIn("stopped before it returned its result", fresh)
        self.assertIn("The machine acceptance failed in your worktree", fresh, "the gate's message goes with the work")
        attempt = replay.replay(self.events()).tickets[1].attempts[1]
        self.assertEqual((attempt.stage, attempt.fallback_from), ("acceptance_failed", "r6 fable low"), "its one resume stays spent")
        self.assertEqual(self.statuses(), {1: "done"})

    def test_under_auto_a_session_that_returned_and_is_owed_its_acceptance_resume_is_told_it_returned(self):
        self.add(1, difficulty=4)
        self.consent("auto")
        driven = self.conductor()
        self.fake.script(done(), ticket=1)  # no hello.txt, so the acceptance fails
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        driven.settle()
        self.hold_journaled(10)  # the tick's /usage reading, journaled while the session ran
        drive(driven)
        self.assertEqual([(call.kind, call.request.model) for call in self.calls(1)], [("launch", "fable"), ("launch", "opus")],
                         "the acceptance resume is neither taken on Fable nor resumed on Opus")
        fresh = self.calls(1)[1].request.prompt
        self.assertIn("returned its result", fresh)
        self.assertNotIn("stopped before it returned", fresh)
        self.assertIn("The machine acceptance failed in your worktree", fresh)
        resumed = self.payload("ticket_resumed")
        self.assertEqual((resumed["reason"], resumed["session_id"]), ("acceptance_failed", None))
        attempt = replay.replay(self.events()).tickets[1].attempts[1]
        self.assertEqual((attempt.stage, attempt.spent, attempt.fallback_from),
                         ("acceptance_failed", {"acceptance_failed"}, "r6 fable low"))
        self.assertEqual(self.statuses(), {1: "done"})

    def test_a_restart_relaunches_a_fallen_back_session_that_never_started_with_its_notes(self):
        self.add(1, difficulty=4)
        self.consent("auto")
        first = self.conductor()
        self.script(1, rejected_on_fable(int(self.now[0]) + 3 * HOUR), envelope=refused(answered=True, num_turns=12))
        self.fake.script(done(), ticket=1, died=True)
        self.assertEqual(first.wave().launched, [1])
        first.settle()
        first.wave()  # carries the stopped session and starts the fresh one on Opus
        first.settle()  # whose worker dies, and so does its conductor, before either says who the session was
        (self.project / "research" / "sessions" / "1" / "1" / "stream.jsonl").unlink()
        self.script(1)
        again = Conductor(self.project, out=io.StringIO())
        again.clock = lambda: self.now[0]
        self.addCleanup(again.settle, 30)
        again.wave()
        calls = self.calls(1)
        self.assertEqual([(call.kind, call.request.model) for call in calls], [("launch", "fable"), ("launch", "opus"), ("launch", "opus")])
        self.assertIn("stopped before it returned its result", calls[2].request.prompt, "the relaunch still says whose work is there")
        self.assertEqual([item["attempt"] for item in self.launches(1)], [1, 1, 1])
        drive(again)
        self.assertEqual(self.statuses(), {1: "done"})

    def test_under_wait_a_session_stopped_mid_work_waits_for_the_reset(self):
        driven = self.refused_then_carried(refused(answered=True, num_turns=12), consent="wait")
        driven.wave()
        self.assertEqual([call.kind for call in self.calls(1)], ["launch"])
        self.assertEqual([item for item in self.launches(1) if "fallback_from" in item], [])

    def test_a_consent_changed_to_auto_starts_the_session_that_waited_under_wait_on_opus(self):
        driven = self.refused_then_carried(refused(answered=True, num_turns=12), consent="wait")
        set_model_fallback(self.project, "auto")
        driven.wave()
        self.assertEqual([(call.kind, call.request.model) for call in self.calls(1)], [("launch", "fable"), ("launch", "opus")])

    def test_a_fallback_attempt_counts_toward_the_escalation_like_any_attempt(self):
        """Its one resume is spent on Opus, where its session runs, and its failure names the tier up; ticket 38 reads `fallback_from` off the attempt."""
        self.add(1, difficulty=4)
        self.hold_journaled(10)
        self.consent("auto")
        driven = self.conductor()
        self.fake.script(Envelope(num_turns=2), ticket=1)
        self.fake.script(Envelope(num_turns=2), ticket=1)
        drive(driven)
        self.assertEqual([(call.kind, call.request.model) for call in self.calls(1)], [("launch", "opus"), ("resume", "opus")])
        failed = [item["payload"] for item in self.events() if item["event"] == "ticket_failed"][0]
        self.assertEqual((failed["attempt"], failed["next"]), (1, "tier_up"),
                         "rung 6 to rung 7 stays inside Fable, so the tier up comes first (ticket 61)")
        view = replay.replay(self.events())
        attempt = view.tickets[1].attempts[1]
        self.assertEqual((attempt.fallback_from, attempt.spent), ("r6 fable low", {"invalid_result"}))
        self.assertEqual(view.failures, {}, "a failure on a launch that fell back never counts toward difficulty_raised")
        self.assertNotIn("difficulty_raised", [item["event"] for item in self.events()])
        self.assertEqual(self.statuses(), {1: "needs_human"}, "the tier-up attempt had nothing scripted")

    def test_a_restart_resumes_an_attempt_that_fell_back_on_opus_whatever_the_consent_says_now(self):
        self.add(1, difficulty=4)
        self.hold_journaled(10)
        self.consent("auto")
        first = self.conductor()
        self.fake.script(done(), patch=patch(), ticket=1, died=True)
        self.assertEqual(first.wave().launched, [1])
        first.settle()  # the worker died, and so did its conductor, before either was carried
        self.consent("wait")
        self.script(1)
        again = Conductor(self.project, out=io.StringIO())
        again.clock = lambda: self.now[0]
        self.addCleanup(again.settle, 30)
        again.wave()
        self.assertEqual([(call.kind, call.request.model) for call in self.calls(1)], [("launch", "opus"), ("resume", "opus")],
                         "an Opus transcript is resumed on Opus: it is not Fable work")
        drive(again)
        self.assertEqual(self.statuses(), {1: "done"})


class HoldLineTest(HoldCase):
    """Criterion 6: the hold line of `wayline status` and the dashboard overview, rendered from laid-down journals."""

    def lay_down(self):
        """Ticket 1 on Fable open, ticket 2 done on Opus with its verdict on Fable, ticket 3 on Fable stopped at the limit,
        and ticket 5 on Fable owed its acceptance resume."""
        self.add(1, difficulty=4)
        self.add(2, difficulty=3)
        self.add(3, difficulty=4)
        self.add(5, difficulty=4)
        for identifier, status in ((2, "done"), (3, "running"), (5, "running")):
            fields = {item["id"]: item for item in tickets.read_tickets(self.project)}[identifier]
            _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))
            tickets.write_ticket(self.ledger, dict(fields, status=status), body)
        now = self.now[0]
        append = self.ledger.append_event
        append("paused", {"resets_at": pacing.iso(now - 30 * HOUR), "window": "seven_day", "utilization": 1.0, "model": "fable"},
               ts=journal_ts(now - 40 * HOUR))
        append("ticket_launched", {"ticket": 9, "attempt": 1, "role": "coder", "model": "opus", "effort": "xhigh", "fallback_from": "fable"},
               ticket=9, ts=journal_ts(now - 39 * HOUR))
        append("unpaused", {"model": "fable"}, ts=journal_ts(now - 30 * HOUR))
        append("ticket_launched", {"ticket": 2, "attempt": 1, "role": "coder", "model": "opus", "effort": "high"},
               ticket=2, ts=journal_ts(now - 20 * HOUR))
        append("ticket_done", {"ticket": 2}, ticket=2, ts=journal_ts(now - 19 * HOUR))
        append("ticket_launched", {"ticket": 3, "attempt": 1, "role": "coder", "model": "fable", "effort": "xhigh"},
               ticket=3, ts=journal_ts(now - 3 * HOUR))
        append("paused", {"resets_at": RESETS, "window": "seven_day", "utilization": 1.0, "model": "fable"}, ts=journal_ts(now - 2 * HOUR))
        append("ticket_result", {"ticket": 3, "attempt": 1, "session_id": "s-3", "status": None, "turns": 12, "valid": False},
               ticket=3, ts=journal_ts(now - 2 * HOUR))
        append("ticket_launched", {"ticket": 5, "attempt": 1, "role": "coder", "model": "fable", "effort": "xhigh"},
               ticket=5, ts=journal_ts(now - 2 * HOUR))
        append("ticket_result", {"ticket": 5, "attempt": 1, "session_id": "s-5", "status": "done", "turns": 20, "valid": True},
               ticket=5, ts=journal_ts(now - 2 * HOUR))
        append("acceptance", {"ticket": 5, "attempt": 1, "where": "worktree", "pass": False, "results": []},
               ticket=5, ts=journal_ts(now - 2 * HOUR))
        for _ in range(2):  # launched, refused before its first turn by the all-models week, and launched again
            append("ticket_launched", {"ticket": 7, "attempt": 1, "role": "coder", "model": "opus", "effort": "max", "fallback_from": "fable"},
                   ticket=7, ts=journal_ts(now - HOUR))

    def hold_line(self):
        lines = [line for line in render_status(status_view(self.project)).splitlines() if line.startswith("fable")]
        return lines[0] if lines else None

    def test_the_hold_line_names_the_reset_the_consent_what_waits_and_what_fell_back_since_the_hold_began(self):
        self.lay_down()
        self.assertEqual(self.hold_line(), "fable    held until %s   consent ask (unset)   waiting 4   fallen back 1" % RESETS)
        set_model_fallback(self.project, "wait")
        self.assertEqual(self.hold_line(), "fable    held until %s   consent wait   waiting 4   fallen back 1" % RESETS)
        set_model_fallback(self.project, "auto")
        self.assertEqual(self.hold_line(), "fable    held until %s   consent auto   waiting 0   fallen back 1" % RESETS,
                         "under auto nothing waits: ticket 2's verdict on Fable is taken on Opus too")
        self.assertEqual(dashboard.overview_view(self.project)["hold"]["line"], self.hold_line())

    def test_no_hold_line_while_no_hold_stands(self):
        self.lay_down()
        self.ledger.append_event("unpaused", {"model": "fable"})
        self.assertIsNone(self.hold_line())
        self.assertIsNone(status_view(self.project)["hold"])
        self.assertIsNone(dashboard.overview_view(self.project)["hold"])


class WriterFallbackTest(RunCase):
    """Criterion 3 outside the conductor: the report's writer on Fable falls back to Opus at its own effort, and its prose is judged as Opus's."""

    def hold(self, hours):
        Ledger(self.project).append_event("paused", {"resets_at": pacing.iso(time.time() + hours * HOUR), "window": "seven_day",
                                                     "utilization": 1.0, "model": "fable"})

    def writer(self):
        (call,) = [call for call in self.calls if call.request.role == "writer"]
        return call.request

    def cached(self):
        return json.loads((self.project / "research" / ".cache" / "report_prose.json").read_text(encoding="utf-8"))

    def test_under_auto_the_writer_drafts_on_opus_at_xhigh_and_its_prose_goes_to_the_verifier_opus_gets(self):
        self.hold(10)
        set_model_fallback(self.project, "auto")
        self.render()
        request = self.writer()
        self.assertEqual((request.model, request.effort), ("opus", "xhigh"))
        self.assertEqual({agent["model"] for agent in json.loads(request.agent_text()).values()}, {"opus"})
        self.assertEqual(self.cached()["fallback_from"], "fable")
        with worker.use_fake() as fake:
            for _ in range(7):
                fake.script(respond=lambda request, message: verdict(), role="verifier")
            verify_claims(self.project)
            judged = [(call.request.model, call.request.effort) for call in fake.calls if "Interaction terms carry" in call.request.prompt]
        self.assertEqual(judged, [("opus", "high")],
                         "Opus's prose goes to the Fable verifier the table gives it, a fresh Opus session while the hold stands")

    def test_under_wait_the_writer_stays_on_fable(self):
        self.hold(10)
        set_model_fallback(self.project, "wait")
        self.render()
        self.assertEqual(self.writer().model, "fable")
        self.assertIsNone(self.cached()["fallback_from"])

    def test_a_hold_whose_reset_has_passed_falls_nothing_back(self):
        self.hold(-1)
        set_model_fallback(self.project, "auto")
        self.render()
        self.assertEqual(self.writer().model, "fable")



if __name__ == "__main__":
    unittest.main()
