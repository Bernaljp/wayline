"""Pacing and the fallback by rung (ticket 62; Implementation Decisions 16, 15, 5, 14, and 2).

A nearly spent window stretches further instead of making hard tickets wait: at `pacing.cheap_at`
every ticket launch runs one rung down the rung ladder. The pure half (`pacing.rung_action`,
`conductor.stepped_down`) is tested on its own; the conductor half is driven with the fake launcher
over the pacing project, its readings journaled as another process's `pacing` event or scripted into
a worker's stream, and a clock the test moves. What is asserted is what the owner and the next
process see: each `LaunchRequest`'s model, effort, and budget, the `rung` on `ticket_launched`, the
`fallback_from` a held Fable rung carries, the replayed view, and the window line `wayline status`
and the dashboard show.
"""

import io
import json
import unittest

from tests.projects import on_fable
from tests.test_conductor import ConductorCase, done, drive, patch, run_verb
from tests.test_fable_hold import HoldCase, journal_ts
from tests.test_pacing import HOUR
from tests.test_verdicts import passing
from wayline import conductor, pacing, project, replay, worker
from wayline.conductor import Conductor
from wayline.project import render_status, status_view

# The shipped ladder, rung by rung: what each rung's launch asks the launcher for.
RUNGS = {1: ("haiku", "medium", 30), 2: ("sonnet", "low", 30), 3: ("sonnet", "high", 30),
         4: ("opus", "low", 90), 5: ("opus", "high", 90), 6: ("fable", "low", 180), 7: ("fable", "high", 180)}


# --- the pure half -------------------------------------------------------------------------------


class RungWindowsTest(unittest.TestCase):
    """Criterion 1: a Fable rung reads Fable's weekly window and the all-models week, every other rung the five-hour and the week."""

    def test_each_family_reads_its_own_two_windows(self):
        self.assertEqual(pacing.windows_for("fable"), ("fable", "seven_day"))
        for family in ("haiku", "sonnet", "opus", None):
            with self.subTest(family=family):
                self.assertEqual(pacing.windows_for(family), ("five_hour", "seven_day"))

    def test_the_five_hour_window_paces_every_rung_but_fable_s(self):
        reading = {"five_hour": 0.85, "seven_day": 0.1, "fable": 0.1}
        self.assertEqual(pacing.rung_action("opus", reading), "cheap_only")
        self.assertEqual(pacing.rung_action("fable", reading), "normal")

    def test_fable_s_weekly_window_paces_a_fable_rung_alone(self):
        reading = {"five_hour": 0.1, "seven_day": 0.1, "fable": 0.85}
        self.assertEqual(pacing.rung_action("fable", reading), "cheap_only")
        self.assertEqual(pacing.rung_action("sonnet", reading), "normal")

    def test_the_all_models_week_paces_both(self):
        reading = {"five_hour": 0.1, "seven_day": 0.85, "fable": 0.1}
        self.assertEqual(pacing.rung_action("fable", reading), "cheap_only")
        self.assertEqual(pacing.rung_action("opus", reading), "cheap_only")
        spent = dict(reading, seven_day=0.95)
        self.assertEqual(pacing.rung_action("fable", spent), "stop")


class SteppedDownTest(ConductorCase):
    """Criterion 2: one rung below, never below rung 2, and never out of Fable."""

    def setUp(self):
        super().setUp()
        self.policy = project.policy_for(self.project)

    def test_every_rung_steps_one_down_to_the_floors_of_decision_16(self):
        for rung, expected in ((7, 6), (6, 6), (5, 4), (4, 3), (3, 2), (2, 2), (1, 1)):
            with self.subTest(rung=rung):
                self.assertEqual(conductor.stepped_down(self.policy, rung), expected)

    def test_rung_6_stays_on_fable_because_only_the_hold_and_the_fallback_leave_it(self):
        self.assertEqual(conductor.rung_family(self.policy, 6), "fable")
        self.assertEqual(conductor.rung_family(self.policy, conductor.stepped_down(self.policy, 6)), "fable")

    def test_a_rung_the_ladder_does_not_have_is_returned_as_it_came(self):
        for rung in (None, 0, 99, "5", True):
            with self.subTest(rung=rung):
                self.assertEqual(conductor.stepped_down(self.policy, rung), rung)

    def test_the_floor_follows_a_policy_whose_ladder_is_all_on_one_model(self):
        """A ladder with no Fable rung steps to rung 2 and stops there, whatever its models."""
        policy = dict(self.policy, tiers=[{"model": "haiku", "effort": "low", "budget": "small"},
                                          {"model": "sonnet", "effort": "low", "budget": "small"},
                                          {"model": "sonnet", "effort": "high", "budget": "small"}])
        self.assertEqual([conductor.stepped_down(policy, rung) for rung in (1, 2, 3)], [1, 2, 2])


# --- the conductor -------------------------------------------------------------------------------


class StepDownCase(HoldCase):
    """The pacing project with a reading another process journaled, so the first launch of a wave is already paced."""

    def journal_reading(self, five_hour=0.1, seven_day=0.1, fable=0.1, ago=60):
        """A `pacing` event as the tick's `/usage` writes one, read `ago` seconds before now."""
        self.ledger.append_event("pacing", {"five_hour": five_hour, "seven_day": seven_day, "fable": fable,
                                            "action": "normal", "fable_action": "normal"},
                                 ts=journal_ts(self.now[0] - ago))

    def launches(self):
        """Every `ticket_launched`, by ticket: the rung it ran on, its model, and its effort."""
        return {item["payload"]["ticket"]: (item["payload"]["rung"], item["payload"]["model"], item["payload"]["effort"])
                for item in self.events("ticket_launched")}

    def request_for(self, identifier):
        """The `LaunchRequest` the launcher was given for ticket `identifier`'s worker."""
        for call in self.fake.calls:
            if call.request.env.get("WAYLINE_TICKET") == str(identifier) and call.request.role == "coder":
                return call.request
        self.fail("the launcher was never called for ticket %d" % identifier)

    def assert_ran_on(self, identifier, rung):
        """The launcher's call and the journal agree that this ticket ran on `rung` of the shipped ladder."""
        model, effort, minutes = RUNGS[rung]
        request = self.request_for(identifier)
        self.assertEqual((request.model, request.effort, request.max_minutes), (model, effort, minutes))
        self.assertEqual(request.agent_json[request.role]["model"], model)
        self.assertEqual(self.launches()[identifier], (rung, model, effort))


class LaunchRungTest(StepDownCase):
    """Criterion 2: at `cheap_at` each launch runs one rung down, on the windows its own rung reads."""

    def test_the_five_hour_window_steps_every_launch_but_a_fable_one_down_one_rung(self):
        self.add(1, difficulty=3)
        self.add(2, difficulty=2)
        self.add(3, difficulty=5)
        self.journal_reading(five_hour=0.85)
        driven = self.conductor(workers=3)
        for identifier in (1, 2, 3):
            self.script(identifier)
        drive(driven)
        self.assert_ran_on(1, 4)  # difficulty 3 is rung 5, opus high: one rung down is opus low
        self.assert_ran_on(2, 2)  # difficulty 2 is rung 3, sonnet high: one rung down is sonnet low
        self.assert_ran_on(3, 7)  # a Fable rung reads Fable's window and the week, and neither is at cheap_at
        self.assertEqual(self.payload("pacing")["action"], "cheap_only")
        self.assertEqual(self.payload("pacing")["fable_action"], "normal")

    def test_fable_s_weekly_window_steps_a_fable_launch_from_rung_7_to_rung_6_and_no_other(self):
        self.add(1, difficulty=5)
        self.add(2, difficulty=3)
        self.journal_reading(fable=0.85)
        driven = self.conductor(workers=2)
        self.script(1)
        self.script(2)
        drive(driven)
        self.assert_ran_on(1, 6)
        self.assert_ran_on(2, 5)
        self.assertEqual((self.payload("pacing")["action"], self.payload("pacing")["fable_action"]), ("normal", "cheap_only"))
        self.assertIsNone(replay.replay(self.events()).hold, "under stop_at there is no hold: the launch stepped down instead")

    def test_rung_6_stays_on_fable_and_rung_2_is_the_floor(self):
        self.add(1, difficulty=4)  # rung 6, fable low: pacing never steps a launch out of Fable
        self.add(2, difficulty=1)  # rung 2, sonnet low: the floor
        self.journal_reading(seven_day=0.85)  # the week every model draws on steps both families
        driven = self.conductor(workers=2)
        self.script(1)
        self.script(2)
        drive(driven)
        self.assert_ran_on(1, 6)
        self.assert_ran_on(2, 2)
        self.assertEqual(self.payload("pacing")["fable_action"], "cheap_only")

    def test_the_budget_follows_the_rung_the_launch_ran_on(self):
        """A step from rung 6 to rung 5 would be a step out of Fable; a step from 5 to 4 keeps the medium budget."""
        self.add(1, difficulty=3)
        self.journal_reading(five_hour=0.85)
        driven = self.conductor()
        self.script(1)
        drive(driven)
        request = self.request_for(1)
        self.assertEqual((request.max_minutes, request.agent_json[request.role]["maxTurns"]), (90, 100))
        self.assertIn("stepping down one rung from r5 opus high", driven.out.getvalue())

    def test_a_reading_under_cheap_at_steps_nothing(self):
        self.add(1, difficulty=3)
        self.journal_reading(five_hour=0.79)
        driven = self.conductor()
        self.script(1)
        drive(driven)
        self.assert_ran_on(1, 5)
        self.assertEqual(self.payload("pacing")["action"], "normal")


class RestartTest(StepDownCase):
    """Criterion 2, read back: the rung a launch ran on is the journal's, and a restart resumes there."""

    def test_a_restart_resumes_on_the_rung_the_journal_names_after_the_reading_has_lapsed(self):
        self.add(1, difficulty=3)
        self.journal_reading(five_hour=0.85)
        first = self.conductor()
        self.fake.script(done(), patch=patch(), ticket=1, died=True)
        self.assertEqual(first.wave().launched, [1])
        first.settle()  # the worker died, and so did its conductor, before either was carried
        self.assert_ran_on(1, 4)
        view = replay.replay(self.events())
        self.assertEqual(view.tickets[1].latest.rung, 4)
        self.assertEqual(replay.replay(self.events()), view, "replaying twice yields the same view")

        self.now[0] += 6 * HOUR  # the five-hour window the reading named has reset: the next wave paces normally
        self.script(1)
        again = Conductor(self.project, out=io.StringIO())
        again.clock = lambda: self.now[0]
        self.addCleanup(again.settle, 30)
        again.wave()
        resumed = [call for call in self.fake.calls if call.kind == "resume"]
        self.assertEqual([(call.request.model, call.request.effort) for call in resumed], [("opus", "low")],
                         "the session is resumed on the rung it ran on, not on the rung its level names")
        self.assertEqual(again.action, "normal")


class TierUpExemptTest(StepDownCase):
    """Criterion 3: an attempt that is itself a tier up runs on its escalated rung, whatever the windows read."""

    def failed_attempt(self, identifier=1):
        """A journal in which ticket `identifier`'s first attempt failed and the ladder sent it up a tier."""
        self.ledger.append_event("ticket_launched", {
            "ticket": identifier, "attempt": 1, "role": "coder", "model": "sonnet", "effort": "high", "skills": [],
            "worktree": str(self.project / ".worktrees" / str(identifier)), "pid": 4000, "context_chars": 10,
            "prompt_sha256": "0" * 64, "difficulty": 2, "rung": 3}, ticket=identifier)
        self.ledger.append_event("ticket_failed", {"ticket": identifier, "attempt": 1,
                                                   "reason": "the acceptance failed", "next": "tier_up"}, ticket=identifier)

    def test_a_tier_up_attempt_is_not_stepped_back_down(self):
        self.add(1, difficulty=2)
        self.failed_attempt()
        self.journal_reading(five_hour=0.85)
        driven = self.conductor()
        self.script(1)
        drive(driven)
        self.assertEqual(self.launches()[1][0], 4, "the tier up went one rung up, to rung 4, and pacing left it there")
        self.assert_ran_on(1, 4)
        self.assertIn("cheap_only", driven.out.getvalue())

    def test_the_view_the_journal_rebuilds_is_the_same_read_twice(self):
        self.add(1, difficulty=2)
        self.failed_attempt()
        self.journal_reading(five_hour=0.85)
        driven = self.conductor()
        self.script(1)
        drive(driven)
        events = self.events()
        self.assertEqual(replay.replay(events), replay.replay(events))
        view = replay.replay(events)
        self.assertEqual(view.pacing["fable_action"], "normal")
        self.assertEqual(view.pacing["action"], "cheap_only")


class NotOnTheLadderTest(StepDownCase):
    """Criterion 3: a verdict is not on the rung ladder and is not stepped down."""

    def test_a_verdict_runs_at_the_verifier_table_s_tier_while_a_fable_launch_steps_down(self):
        self.add(1, difficulty=5)
        self.journal_reading(fable=0.85)
        driven = self.conductor()
        self.script(1)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        self.assert_ran_on(1, 6)
        (verifier,) = self.verifier_calls()
        self.assertEqual((verifier.request.model, verifier.request.effort), ("opus", "max"),
                         "the verifier table's own tier, which no window steps down")
        self.assertEqual(self.payload("verdict")["rung"], 6, "the verdict names the rung the attempt it judged ran on")


class HeldRungFallsBackTest(StepDownCase):
    """Criterion 4: while the hold stands, a Fable rung falls back to the Opus rung at the same effort and budget."""

    def setUp(self):
        super().setUp()
        on_fable(self.project, "verifier.opus")  # work written on Opus is read on Fable, which the hold holds

    def fall_back(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["model_fallback"] = "auto"
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def test_rung_7_falls_back_to_opus_high_and_rung_6_to_opus_low_naming_the_rung_they_came_from(self):
        self.add(1, difficulty=5)
        self.add(2, difficulty=4)
        self.fall_back()
        self.hold_journaled(hours=4)
        driven = self.conductor(workers=2)
        self.script(1)
        self.script(2)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        launched = {item["payload"]["ticket"]: item["payload"] for item in self.events("ticket_launched")}
        self.assertEqual((launched[1]["model"], launched[1]["effort"], launched[1]["fallback_from"]),
                         ("opus", "high", "r7 fable high"))
        self.assertEqual((launched[2]["model"], launched[2]["effort"], launched[2]["fallback_from"]),
                         ("opus", "low", "r6 fable low"))
        self.assertEqual((launched[1]["rung"], launched[2]["rung"]), (7, 6), "the rung is the ticket's; only the model moved")
        self.assertEqual((self.request_for(1).max_minutes, self.request_for(2).max_minutes), (180, 180))
        events = self.events()
        self.assertEqual(replay.replay(events), replay.replay(events))

    def test_a_held_fable_rung_falls_back_at_its_own_effort_rather_than_stepping_down(self):
        """The hold and the step are two answers to two readings: a hold says `stop` for the rung, and the consent moves it.

        A window the hold stands on reads at or above `stop_at`, which is past `cheap_at`, so the rung
        is never stepped: the fallback keeps the effort and budget the ticket's own rung gives it.
        """
        self.add(1, difficulty=5)
        self.fall_back()
        self.hold_journaled(hours=4)
        # The all-models week at `cheap_at` steps every launch off Fable; Fable's own window is the hold's, still spent.
        self.journal_reading(seven_day=0.85, fable=None)
        driven = self.conductor()
        self.script(1)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        self.assertEqual(driven.fable_action, "stop", "the hold's own reading of Fable's window is spent")
        launched = self.payload("ticket_launched")
        self.assertEqual((launched["model"], launched["effort"], launched["rung"], launched["fallback_from"]),
                         ("opus", "high", 7, "r7 fable high"))

    def test_the_hold_line_still_counts_a_launch_that_fell_back(self):
        self.add(1, difficulty=5)
        self.fall_back()
        self.hold_journaled(hours=4)
        driven = self.conductor()
        self.script(1)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        hold = status_view(self.project, refresh=False)["hold"]
        self.assertEqual((hold["consent"], hold["fallen_back"]), ("auto", 2), "the launch and its verdict, both on Opus")


class WindowLineTest(StepDownCase):
    """Criterion 5: the window line of `wayline status` and the dashboard overview says a launch is stepping down."""

    def window_line(self):
        printed = [line for line in render_status(status_view(self.project, refresh=False)).splitlines() if line.startswith("window ")]
        self.assertTrue(printed, "no window line in the status")
        return printed[0]

    def test_the_line_says_one_rung_while_the_windows_every_model_draws_on_are_at_cheap_at(self):
        self.journal_reading(five_hour=0.85)
        self.conductor().wave()
        self.assertIn("stepping down one rung", self.window_line())
        self.assertEqual(status_view(self.project, refresh=False)["window"]["stepping_down"], "stepping down one rung")

    def test_the_line_names_the_rung_a_fable_launch_steps_to_while_fable_s_window_alone_is_at_cheap_at(self):
        self.journal_reading(fable=0.85)
        self.conductor().wave()
        self.assertIn("stepping down to r6 fable low", self.window_line())
        self.assertEqual(status_view(self.project, refresh=False)["window"]["fable_action"], "cheap_only")

    def test_no_window_at_cheap_at_says_nothing(self):
        self.journal_reading(five_hour=0.4, fable=0.4)
        self.conductor().wave()
        self.assertNotIn("stepping down", self.window_line())
        self.assertIsNone(status_view(self.project, refresh=False)["window"]["stepping_down"])

    def test_the_line_is_rendered_from_a_journal_written_before_the_rung_ladder(self):
        """An old `pacing` event carries no `fable_action`, and its window line says only what it knew."""
        self.ledger.append_event("pacing", {"five_hour": 0.85, "seven_day": 0.1, "fable": 0.1, "action": "cheap_only"})
        self.assertIn("stepping down one rung", self.window_line())
        self.ledger.append_event("pacing", {"five_hour": 0.1, "seven_day": 0.1, "fable": 0.95, "action": "normal"})
        self.assertNotIn("stepping down", self.window_line())


class SimulatedStepDownTest(StepDownCase):
    """Criterion 6: `--simulate-limit cheap:<seconds>` forces a reading past `cheap_at` and under `stop_at`."""

    def test_the_value_is_parsed_into_seconds_a_model_and_whether_it_steps_down(self):
        self.assertEqual(conductor.parse_simulated_limit("3600"), (3600.0, None, False))
        self.assertEqual(conductor.parse_simulated_limit("fable:60"), (60.0, "fable", False))
        self.assertEqual(conductor.parse_simulated_limit("cheap:60"), (60.0, None, True))
        self.assertEqual(conductor.parse_simulated_limit("cheap:fable:60"), (60.0, "fable", True))
        for value in ("cheap:opus:60", "cheap:", "cheap:-5", "cheap"):
            with self.subTest(value=value):
                self.assertIsNone(conductor.parse_simulated_limit(value))

    def test_a_forced_reading_steps_every_launch_down_and_lapses_with_its_seconds(self):
        self.add(1, difficulty=3)
        self.add(2, difficulty=3)
        driven = self.conductor()
        driven.simulate_step_down(HOUR)
        self.script(1)
        self.script(2)
        driven.wave()
        driven.settle()
        self.assert_ran_on(1, 4)
        self.assertEqual(self.payload("pacing")["action"], "cheap_only")
        self.now[0] += HOUR + 1  # the forced reading resets, and the next wave launches at the ticket's own rung
        drive(driven)
        self.assert_ran_on(2, 5)
        self.assertEqual(self.payload("pacing")["action"], "normal")

    def test_a_forced_reading_on_fable_s_window_alone_steps_only_a_fable_launch(self):
        self.add(1, difficulty=5)
        self.add(2, difficulty=3)
        driven = self.conductor(workers=2)
        driven.simulate_step_down(HOUR, model="fable")
        self.script(1)
        self.script(2)
        self.fake.script(passing(), role="verifier")
        drive(driven)
        self.assert_ran_on(1, 6)
        self.assert_ran_on(2, 5)
        self.assertEqual((self.payload("pacing")["action"], self.payload("pacing")["fable_action"]), ("normal", "cheap_only"))

    def test_the_verb_runs_under_it_and_says_the_window_line(self):
        """What "43 - M5 overnight demo" forces live: launches one rung down, and the line that says so."""
        self.add(1, difficulty=3)
        with worker.use_fake() as fake:
            self.fake = fake
            self.script(1)
            code, out, err = run_verb(["--simulate-limit", "cheap:3600", "--max-waves", "2", "--project", str(self.project)])
            self.assertEqual(code, 0, out + err)
            self.assertIn("one rung down", out)
            self.assert_ran_on(1, 4)
        self.assertIn("stepping down one rung", render_status(status_view(self.project, refresh=False)))

    def test_a_cheap_value_the_parser_refuses_names_the_spellings(self):
        code, _, err = run_verb(["--simulate-limit", "cheap:soon", "--project", str(self.project)])
        self.assertEqual(code, 2)
        self.assertIn("cheap:", err)
        self.assertIn("fable:<seconds>", err)


if __name__ == "__main__":
    unittest.main()
