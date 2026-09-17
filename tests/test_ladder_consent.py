"""The ladder consent (ticket 64; Implementation Decision 16).

`ladder_changes` says whether an autonomous run may change the rung ladder (`tiers` or `difficulty`) on its
own. It is driven exactly as the fallback consent of ticket 55 is driven, and tested the same way: as plain
functions over a temporary project, through `wayline intake`, `wayline switch --ladder`, and the dashboard's
action, read back from `harness.json`, the journal, the replayed view, the decider's prompt, and the ticket a
decision of class `ladder` opens. `tests/test_fallback.py` is the prior art this file mirrors.
"""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.test_actions import STATIC, ActionCase
from tests.test_conductor import ConductorCase
from wayline import cli, decider, decisions, intake, project, replay
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger
from wayline.project import (
    LADDER_CHANGES, LADDER_CLASS, LADDER_CONSENTS, human_only_classes_now, ladder_consent, ladder_is_human_only,
    read_harness, set_ladder_changes,
)
from wayline.schedule import awaits_owner


def run(*arguments):
    """`wayline <verb>` in process, with its output captured: the exit code, stdout, and stderr."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


class LadderConsentTest(ConductorCase):
    """Criteria 1 and 2: `ladder_changes` in `harness.json`, and `wayline switch --ladder` writing it and journaling `control`."""

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
        self.assertNotIn("ladder_changes", harness, "init records no consent: the intake asks it")
        self.assertEqual(ladder_consent(harness), ("ask", False))
        self.assertEqual(ladder_consent(dict(harness, ladder_changes="ask")), ("ask", True))
        self.assertEqual(ladder_consent(dict(harness, ladder_changes="auto")), ("auto", True))

    def test_the_harness_schema_takes_the_two_consents_and_nothing_else(self):
        harness = read_harness(self.project)
        for consent in LADDER_CONSENTS:
            check(dict(harness, ladder_changes=consent), load_schema("harness"))
        for refused in ("wait", "sometimes", ""):
            with self.subTest(consent=refused), self.assertRaises(ValidationError):
                check(dict(harness, ladder_changes=refused), load_schema("harness"))

    def test_switch_ladder_writes_harness_json_first_and_then_journals_control(self):
        written = []
        original = project.control

        def control(*arguments, **options):
            written.append(read_harness(self.project).get("ladder_changes"))
            return original(*arguments, **options)

        with mock.patch.object(project, "control", control):
            code, out, err = self.switch("--ladder", "auto")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(written, ["auto"], "harness.json already said auto when control was journaled")
        self.assertEqual(read_harness(self.project)["ladder_changes"], "auto")
        self.assertEqual(self.controls(), [{"command": "ladder_changes", "args": {"ladder_changes": "auto"}, "by": "cli"}])
        self.assertIn("ask (unset)", out)
        self.assertIn("no conductor is running", out)

    def test_either_consent_is_accepted_at_any_time_with_a_conductor_running(self):
        self.hold_the_conductor()
        for consent in ("auto", "ask", "auto"):
            code, out, err = self.switch("--ladder", consent)
            self.assertEqual(code, 0, out + err)
            self.assertIn("4242", out)
        self.assertEqual([payload["args"] for payload in self.controls()],
                         [{"ladder_changes": "auto"}, {"ladder_changes": "ask"}, {"ladder_changes": "auto"}])
        self.assertEqual(ladder_consent(read_harness(self.project)), ("auto", True))
        self.assertEqual(json.loads((self.project / "harness.json").read_text(encoding="utf-8"))["radius"], "moderate",
                         "the rest of harness.json is kept")

    def test_the_key_lands_beside_the_fallback_consent_and_beside_radius_without_one(self):
        self.assertEqual(self.switch("--ladder", "auto")[0], 0)
        keys = list(read_harness(self.project))
        self.assertEqual(keys.index("ladder_changes"), keys.index("radius") + 1, "no fallback consent: it sits beside radius")
        code, out, err = run("switch", "--fallback", "wait", "--project", str(self.project))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.switch("--ladder", "ask")[0], 0)
        keys = list(read_harness(self.project))
        self.assertEqual(keys.index("ladder_changes"), keys.index("model_fallback") + 1)

    def test_the_same_consent_again_changes_nothing_and_an_explicit_ask_on_a_project_without_the_key_does(self):
        self.assertEqual(self.switch("--ladder", "ask")[0], 0)
        self.assertEqual(len(self.controls()), 1, "unset and ask behave alike, and are still two settings")
        code, out, _ = self.switch("--ladder", "ask")
        self.assertEqual(code, 0)
        self.assertIn("already", out)
        self.assertEqual(len(self.controls()), 1)

    def test_a_consent_the_running_conductor_holds_apart_from_the_file_is_still_journaled(self):
        self.assertEqual(self.switch("--ladder", "ask")[0], 0)
        Ledger(self.project).append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "checkpoints",
                                                          "radius": "moderate", "pid": 4242})
        self.hold_the_conductor()
        self.ledger.append_event("control", {"command": "ladder_changes", "args": {"ladder_changes": "auto"}, "by": "dashboard"})
        code, out, err = self.switch("--ladder", "ask")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("already", out)
        self.assertEqual(replay.replay(self.events()).ladder_changes, "ask")

    def test_switch_refuses_a_consent_it_does_not_know_and_another_flag_beside_it(self):
        self.assertEqual(self.switch("--ladder", "wait")[0], 2, "wait is the fallback consent's, not the ladder's")
        code, _, err = run("switch", str(self.project), "--ladder", "auto")
        self.assertEqual(code, 2)
        self.assertIn("--ladder", err)
        self.assertEqual(self.switch("--ladder", "auto", "--autonomy", "autonomous")[0], 2)
        self.assertEqual(self.switch("--ladder", "auto", "--fallback", "wait")[0], 2)
        self.assertEqual(self.switch("--ladder", "auto", "--stop-at", "0.9")[0], 2)
        self.assertEqual(self.controls(), [])

    def test_the_function_refuses_a_consent_nobody_can_hold(self):
        with self.assertRaises(project.ProjectError) as raised:
            set_ladder_changes(self.project, "wait")
        self.assertIn("one of auto, ask", str(raised.exception))

    def test_the_dashboard_action_calls_the_same_function(self):
        report = set_ladder_changes(self.project, "auto", by="dashboard")
        self.assertEqual((report["from"], report["to"], report["changed"]), (None, "auto", True))
        self.assertEqual(self.controls()[0]["by"], "dashboard")


class LadderReplayTest(unittest.TestCase):
    """Criterion 2 by replay: a `control ladder_changes` holds for the run it arrived in, over `harness.json`."""

    @staticmethod
    def control(consent):
        return {"event": "control", "payload": {"command": "ladder_changes", "args": {"ladder_changes": consent}, "by": "cli"}}

    def test_the_view_takes_each_consent_for_the_open_run_and_forgets_it_when_the_run_ends(self):
        view = replay.replay([self.control("auto")])
        self.assertIsNone(view.ladder_changes, "no run is open: harness.json, which the switch wrote first, says it")
        replay.replay([{"event": "run_started", "payload": {"autonomy": "checkpoints"}}], view)
        for consent in ("auto", "ask", "auto"):
            replay.replay([self.control(consent)], view)
            self.assertEqual(view.ladder_changes, consent)
            self.assertEqual(ladder_consent({"ladder_changes": "ask"}, view), (consent, True))
        replay.replay([self.control("wait")], view)
        self.assertEqual(view.ladder_changes, "auto", "a consent nobody can hold is passed over")
        replay.replay([{"event": "run_ended", "payload": {"reason": "stopped"}}], view)
        self.assertIsNone(view.ladder_changes)
        self.assertEqual(ladder_consent({"ladder_changes": "auto"}, view), ("auto", True))
        self.assertEqual(ladder_consent({}, view), ("ask", False))


class LadderIntakeTest(ConductorCase):
    """Criterion 1: the intake asks the consent beside autonomy and the fallback consent, and never invents one."""

    def intake(self, *arguments, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = intake.intake_command(["--project", str(self.project), *arguments], stdin=stdin)
        return code, out.getvalue(), err.getvalue()

    def autonomy_section(self):
        text = (self.project / "research" / "INTAKE.md").read_text(encoding="utf-8")
        return text.split("## Autonomy", 1)[1].split("\n## ", 1)[0]

    def test_the_consent_lands_beside_the_fallback_consent_in_harness_json_and_in_intake_md(self):
        code, out, err = self.intake("--intent", "a question", "--autonomy", "autonomous",
                                     "--model-fallback", "auto", "--ladder-changes", "auto", "--gpu-hours", "2")
        self.assertEqual(code, 0, out + err)
        harness = read_harness(self.project)
        self.assertEqual(harness["ladder_changes"], "auto")
        keys = list(harness)
        self.assertEqual(keys.index("ladder_changes"), keys.index("model_fallback") + 1)
        self.assertIn("Ladder consent `auto`", self.autonomy_section())
        self.assertIn("ladder auto", out)
        self.assertEqual(self.events("control"), [], "no run is open, so harness.json alone says it")

    def test_an_intake_that_does_not_state_it_writes_no_key_and_keeps_one_stated_before(self):
        self.assertEqual(self.intake("--intent", "a question")[0], 0)
        self.assertNotIn("ladder_changes", read_harness(self.project))
        section = self.autonomy_section()
        self.assertIn("Ladder consent not stated", section)
        self.assertIn("`ask`", section)
        self.assertEqual(self.intake("--intent", "a question", "--ladder-changes", "auto")[0], 0)
        self.assertEqual(self.intake("--intent", "the same question, restated")[0], 0)
        self.assertEqual(read_harness(self.project)["ladder_changes"], "auto")

    def test_the_recommended_answer_is_ask_and_the_skill_asks_it_beside_the_other_two(self):
        skill = (project.HARNESS_ROOT / "skills" / "wayline-intake" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`ladder_changes`", skill)
        self.assertIn("recommended", skill)
        self.assertIn("--ladder-changes", skill)
        code, out, _ = self.intake("--help")
        self.assertEqual(code, 0)
        self.assertIn("`ask` recommended", out, "the verb's own help recommends ask too")
        self.assertIn("--ladder-changes", out)

    def test_a_consent_the_intake_does_not_know_is_refused_and_nothing_is_written(self):
        code, _, err = self.intake("--intent", "a question", "--ladder-changes", "wait")
        self.assertEqual(code, 2, err)
        self.assertNotIn("ladder_changes", read_harness(self.project))
        with self.assertRaises(intake.IntakeError):
            intake.normalize_spec({"intent": "a question", "ladder_changes": "wait"})


class LadderClassTest(ConductorCase):
    """Criterion 3: who answers a decision of class `ladder`, under each autonomy and each consent."""

    def harness_with(self, **keys):
        return dict(read_harness(self.project), **keys)

    def test_the_class_is_human_only_under_ask_and_unset_and_is_not_under_auto(self):
        self.assertTrue(ladder_is_human_only(self.harness_with()))
        self.assertTrue(ladder_is_human_only(self.harness_with(ladder_changes="ask")))
        self.assertFalse(ladder_is_human_only(self.harness_with(ladder_changes="auto")))

    def test_the_classes_the_decider_is_given_carry_ladder_only_while_the_consent_is_not_auto(self):
        for consent, carries in ((None, True), ("ask", True), ("auto", False)):
            harness = self.harness_with() if consent is None else self.harness_with(ladder_changes=consent)
            with self.subTest(consent=consent):
                self.assertEqual(LADDER_CLASS in human_only_classes_now(harness), carries)
                told = decider._classes(dict(harness, human_only=["goal", "data"]))
                self.assertEqual("`ladder`" in told, carries)
                self.assertIn("`goal`", told, "the classes harness.json holds are still told")

    def test_a_decision_of_class_ladder_opens_human_only_under_ask_and_is_the_deciders_under_auto(self):
        opened = decisions.open_decision(self.project, "Raise difficulty 4 to rung 7?", blocking=None,
                                         decision_class=LADDER_CLASS, notify=lambda *arguments: None)
        fields = {ticket["id"]: ticket for ticket in decisions.read_tickets(self.project)}[opened["ticket"]]
        self.assertTrue(fields["human_only"], "the consent is unset, so it behaves as ask")
        self.assertEqual(self.events("decision_opened")[-1]["payload"]["human_only"], True)

        self.assertEqual(set_ladder_changes(self.project, "auto")["to"], "auto")
        under_auto = decisions.open_decision(self.project, "Raise difficulty 5 to rung 7?", blocking=None,
                                             decision_class=LADDER_CLASS, notify=lambda *arguments: None)
        fields = {ticket["id"]: ticket for ticket in decisions.read_tickets(self.project)}[under_auto["ticket"]]
        self.assertFalse(fields["human_only"], "under auto the decider may answer it")

    def test_a_class_the_project_does_not_hold_human_only_leaves_the_ticket_alone(self):
        opened = decisions.open_decision(self.project, "Which colour map?", blocking=None,
                                         decision_class="figures", notify=lambda *arguments: None)
        fields = {ticket["id"]: ticket for ticket in decisions.read_tickets(self.project)}[opened["ticket"]]
        self.assertFalse(fields["human_only"])

    def test_under_interactive_and_checkpoints_the_consent_changes_who_answers_not_at_all(self):
        for autonomy in ("interactive", "checkpoints"):
            for consent in (None, "ask", "auto"):
                entry = {"kind": "decision", "human_only": ladder_is_human_only(
                    self.harness_with() if consent is None else self.harness_with(ladder_changes=consent))}
                with self.subTest(autonomy=autonomy, consent=consent):
                    self.assertTrue(awaits_owner(entry, autonomy=autonomy, decider=True),
                                    "the owner answers every decision ticket there, under either consent")

    def test_under_autonomous_the_consent_decides_who_answers(self):
        for consent, owner in ((None, True), ("ask", True), ("auto", False)):
            entry = {"kind": "decision", "human_only": ladder_is_human_only(
                self.harness_with() if consent is None else self.harness_with(ladder_changes=consent))}
            with self.subTest(consent=consent):
                self.assertEqual(awaits_owner(entry, autonomy="autonomous", decider=True), owner)


class LadderActionTest(ActionCase):
    """Criterion 4 over HTTP: the `ladder_changes` action behind the token, and the control on the page."""

    def test_the_action_writes_harness_json_and_journals_control_by_the_dashboard(self):
        response = self.act("ladder_changes", {"ladder_changes": "auto"})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual((response.json["from"], response.json["to"], response.json["changed"]), (None, "auto", True))
        self.assertEqual(read_harness(self.project)["ladder_changes"], "auto")
        self.assertEqual(self.events("control")[-1]["payload"],
                         {"command": "ladder_changes", "args": {"ladder_changes": "auto"}, "by": "dashboard"})

    def test_without_the_token_or_with_a_wrong_one_it_is_refused_and_a_consent_nobody_holds_is_a_400(self):
        for token in (None, "wrong"):
            with self.subTest(token=token):
                self.assertEqual(self.act("ladder_changes", {"ladder_changes": "auto"}, token=token).status, 403)
        refused = self.act("ladder_changes", {"ladder_changes": "wait"})
        self.assertEqual(refused.status, 400)
        self.assertIn("one of auto, ask", refused.json["error"])
        self.assertEqual(self.act("ladder_changes", {}).status, 400)
        self.assertEqual(self.events("control"), [])
        self.assertNotIn("ladder_changes", read_harness(self.project))

    def test_the_decisions_view_carries_the_consent_the_control_is_drawn_from(self):
        view = self.request("GET", "/api/projects/%s/decisions" % self.project.name)
        self.assertEqual(view.status, 200, view.text)
        keys = ("ladder_changes", "ladder_changes_stated", "ladder_changes_levels")
        self.assertEqual({key: view.json["controls"][key] for key in keys},
                         {"ladder_changes": "ask", "ladder_changes_stated": False, "ladder_changes_levels": ["auto", "ask"]})
        self.assertEqual(self.act("ladder_changes", {"ladder_changes": "auto"}).status, 200)
        view = self.request("GET", "/api/projects/%s/decisions" % self.project.name)
        self.assertEqual({key: view.json["controls"][key] for key in keys[:2]},
                         {"ladder_changes": "auto", "ladder_changes_stated": True})

    def test_the_page_carries_the_ladder_consent_control_beside_the_fallback_one(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        for element in ("ladder-changes-form", "ladder-changes-select", "ladder-changes-set", "ladder-changes-current"):
            with self.subTest(element=element):
                self.assertIn('id="%s"' % element, page)
        self.assertLess(page.index("model-fallback-form"), page.index("ladder-changes-form"), "it sits beside the fallback consent")
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("perform('ladder_changes', { ladder_changes: consent }", script)
        self.assertIn("'ladder-changes-set'", script, "the button is token-guarded with the others")


class LadderLineTest(unittest.TestCase):
    """The one line each consent is shown by, which the switch and the intake both print."""

    def test_each_consent_has_a_line_and_no_other_does(self):
        self.assertEqual(tuple(LADDER_CHANGES), LADDER_CONSENTS)
        for consent, line in LADDER_CHANGES.items():
            with self.subTest(consent=consent):
                self.assertTrue(line.endswith("."), line)


if __name__ == "__main__":
    unittest.main()
