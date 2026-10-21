"""The setup conversation fixture, `fixtures/skill/wayline/` (decision 12's fixtures; ticket 109).

The fixture pins the setup conversation in its new order: the owner's opening and replies under `input/`, and the
checks a recording of it has to pass. Recording it is a live session, run on demand as its note says; the suite holds
its checks to a recording written here by hand in the shape a recorded session leaves (`result-<n>.json` and
`trace-<n>.jsonl` per turn, the project's `research/journal.jsonl` and `harness.json`): one that asks the ten setup
questions in order passes every structural check, and each way of breaking the order is caught.
"""

import json
import shutil
import unittest

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_intake import structural
from wayline.fixtures import load_fixture

FIXTURE = FIXTURES_DIR / "skill" / "wayline"
TITLES = ("the documents", "the objectives", "the concerns", "the missing material", "the stopping rule and budgets", "the software",
          "the code repository", "the paper order", "the front matter", "the important unresolved references")


def said(*numbers):
    """A closing message asking the setup questions `numbers`, each headed as the setup reference heads it."""
    return "\n\n".join("Setup %d/10: %s\n\nRecommended: as I said." % (number, TITLES[number - 1]) for number in numbers)


# The turns of a good setup: (the commands the turn ran, what it said at its end).
GOOD = [
    (["wayline intake --from - --project .", "wayline absorb --project .", "wayline document add owner/draft.docx --kind inherited --project .",
      "wayline position --project ."], said(1)),
    (["wayline mark B1 1 right --project ."], said(2)),
    (["wayline grill answer Q1 open --rationale \"the owner's reason\" --project ."], said(3)),
    (["wayline grill answer Q4 \"take it\" --rationale \"as proposed\" --project ."], said(4)),
    (["wayline grill answer Q7 \"as recommended\" --project .", "wayline grill --decide-rest --project ."], said(5)),
    (["wayline switch --stop-when objectives --project .", "wayline switch --budget wallclock_hours=48 --project .",
      "wayline specify --project .", "wayline plan --cut-only --project .", "wayline tools needs --project ."], said(6)),
    (["wayline tools install octave --yes --project ."], said(7)),
    (["wayline intake --from - --project ."], said(8)),
    ([], said(9)),
    (["wayline reference --project ."], said(10)),
    (["wayline reference smith-2019 \"leave it\" --project .", "wayline plan --project ."], "Setup is done: the graph is confirmed."),
]


class SetupFixtureTest(ProjectTestCase):
    def record(self, turns=GOOD, events=None, autonomy="autonomous"):
        """A recording of `turns` under `self.temp/recorded`, with a journal ending setup at the last turn."""
        root = self.temp / "recorded"
        shutil.rmtree(root, ignore_errors=True)
        (root / "research").mkdir(parents=True)
        for number, (commands, closing) in enumerate(turns, 1):
            lines = [{"type": "system", "subtype": "init", "session_id": "setup", "model": "claude-opus-5"}]
            for index, command in enumerate(commands):
                identifier = "toolu_%d_%d" % (number, index)
                lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": identifier, "name": "Bash",
                                                                            "input": {"command": command}}]}})
                lines.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": identifier, "content": "ok"}]}})
            (root / ("trace-%d.jsonl" % number)).write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
            (root / ("result-%d.json" % number)).write_text(json.dumps({"session_id": "setup", "result": closing}), encoding="utf-8")
        if events is None:
            events = [{"ts": "2026-10-21T10:00:00.000Z", "event": "control", "payload": {"command": "stop_when"}},
                      {"ts": "2026-10-21T11:00:00.000Z", "event": "phase", "payload": {"from": "P4", "to": "P5"}}]
        (root / "research" / "journal.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        (root / "harness.json").write_text(json.dumps({"autonomy": autonomy}), encoding="utf-8")
        return root

    def failures(self, root):
        record = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        return [problem for check in record["structural"] for problem in structural(check, root, FIXTURE)]

    def test_the_fixture_is_a_skill_fixture_of_the_wayline_skill_with_replies_in_setup_order(self):
        record = load_fixture(FIXTURE)
        self.assertEqual((record["id"], record["kind"]), ("skill/wayline", "skill"))
        self.assertEqual(record["subject"]["path"], "skills/wayline/SKILL.md")
        self.assertIn("skills/wayline/setup.md", record["subject"]["also"])
        self.assertTrue((FIXTURE / record["input"]["prompt"]).read_text(encoding="utf-8").startswith("/wayline\n"))
        self.assertEqual(len(record["input"]["replies"]), 10, "one reply per setup question")
        for reply in record["input"]["replies"]:
            self.assertTrue((FIXTURE / reply).is_file(), reply)
        self.assertIn("on demand", record["note"])
        checks = {check.get("fn") for check in record["structural"] if check["check"] == "python"}
        self.assertTrue({"asks_the_ten_questions_in_order", "confirms_the_plan_after_the_last_question",
                         "nothing_is_asked_after_setup"} <= checks, checks)

    def test_a_setup_that_asks_the_ten_questions_in_order_passes_every_check(self):
        self.assertEqual(self.failures(self.record()), [])

    def test_a_question_asked_out_of_order_is_caught(self):
        turns = list(GOOD)
        turns[6], turns[7] = (turns[6][0], said(8)), (turns[7][0], said(7))
        problems = self.failures(self.record(turns))
        self.assertTrue(any("Setup 7/10" in problem and "after" in problem for problem in problems), problems)

    def test_a_question_never_asked_is_caught(self):
        turns = [turn for turn in GOOD if "Setup 9/10" not in turn[1]]
        problems = self.failures(self.record(turns))
        self.assertTrue(any("Setup 9/10" in problem and "never" in problem for problem in problems), problems)

    def test_a_plan_confirmed_before_the_last_question_is_caught(self):
        turns = list(GOOD)
        turns[5] = ([command.replace("plan --cut-only", "plan") for command in GOOD[5][0]], GOOD[5][1])
        problems = self.failures(self.record(turns))
        self.assertTrue(any("confirm" in problem for problem in problems), problems)

    def test_a_re_cut_after_the_code_repository_answer_passes_as_setup_says_to_make_it(self):
        turns = list(GOOD)
        turns[7] = (["wayline intake --from - --project .", 'wayline plan revise "code tickets write under code/" --project .',
                     "wayline plan --cut-only --project ."], GOOD[7][1])
        self.assertEqual(self.failures(self.record(turns)), [])

    def test_a_re_cut_or_a_split_is_no_confirmation(self):
        turns = list(GOOD)
        turns[7] = (GOOD[7][0] + ["wayline plan --replan --project .", "wayline plan --split 4 --project ."], GOOD[7][1])
        self.assertEqual(self.failures(self.record(turns)), [])

    def test_the_owners_confirmation_through_its_ticket_before_the_last_question_is_caught(self):
        turns = list(GOOD)
        turns[7] = (GOOD[7][0] + ['wayline answer 12 "confirm" --project .'], GOOD[7][1])
        problems = self.failures(self.record(turns))
        self.assertTrue(any("answer 12" in problem for problem in problems), problems)

    def test_a_graph_cut_before_the_stopping_rule_was_asked_is_caught(self):
        turns = list(GOOD)
        turns[0] = (GOOD[0][0] + ["wayline plan --cut-only --project ."], GOOD[0][1])
        problems = self.failures(self.record(turns))
        self.assertTrue(any("--cut-only" in problem for problem in problems), problems)

    def test_a_human_only_decision_opened_after_setup_under_autonomous_is_caught(self):
        events = [{"ts": "2026-10-21T10:00:00.000Z", "event": "control", "payload": {"command": "stop_when"}},
                  {"ts": "2026-10-21T11:00:00.000Z", "event": "phase", "payload": {"from": "P4", "to": "P5"}},
                  {"ts": "2026-10-21T12:00:00.000Z", "event": "decision_opened", "ticket": 9, "payload": {"human_only": True}}]
        problems = self.failures(self.record(events=events))
        self.assertTrue(any("after setup" in problem for problem in problems), problems)
        self.assertEqual(self.failures(self.record(events=events, autonomy="checkpoints")), [], "only autonomous asks nothing after setup")

    def test_a_session_that_writes_around_the_verbs_is_caught(self):
        turns = list(GOOD)
        turns[1] = (GOOD[1][0] + ["echo x >> research/OBJECTIVES.md"], GOOD[1][1])
        self.assertTrue(self.failures(self.record(turns)))


if __name__ == "__main__":
    unittest.main()
