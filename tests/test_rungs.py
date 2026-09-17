"""The rung ladder (ticket 60; Implementation Decisions 16, 14, and 2).

A ticket's difficulty names a rung of `policy.tiers`, and the launch takes the rung's model, effort,
and budget, under the cap: nothing a ticket runs on is above `high`. What is asserted is what the fake
launcher was asked for, what `ticket_launched` and `verdict` carry, what `wayline status` and the
dashboard label a launch, and what `refuse_to_start` says to a project whose override is in the old shape.
"""

import io
import json
import re
import unittest

from tests import machine
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, patch
from wayline import conductor, gates, plan, project, tickets, worker
from wayline.ledger import Ledger, make_event

# Difficulty 1 to 5 on the shipped ladder: the rung, its model and effort, and its budget's turns and minutes.
EXPECTED = {
    1: (2, "sonnet", "low", 40, 30),
    2: (3, "sonnet", "high", 40, 30),
    3: (5, "opus", "high", 100, 90),
    4: (6, "fable", "low", 200, 180),
    5: (7, "fable", "high", 200, 180),
}


def passing_verdict():
    """The envelope a verifier returns when the subject answers the question."""
    return worker.Envelope(structured_output={"pass": True, "findings": [], "question_limit": "Only the ticket."}, num_turns=4, duration_ms=9000)


class LaunchRequestTest(ConductorCase):
    """Each difficulty's launch, as the fake launcher saw it, and the verdict it earned."""

    def set_difficulty(self, difficulty):
        path = next(tickets.tickets_dir(self.project).glob("01-*.md"))
        text = path.read_text(encoding="utf-8")
        changed = re.sub(r"^difficulty: \d+$", "difficulty: %d" % difficulty, text, count=1, flags=re.MULTILINE)
        if changed != text:
            path.write_text(changed, encoding="utf-8")
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "difficulty %d" % difficulty)

    def launch_at(self, difficulty):
        """The whole path at `difficulty`: the worker scripted by ticket, a passing verdict by role for the read a hard ticket earns."""
        self.set_difficulty(difficulty)
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch(), ticket=1)
            fake.script(passing_verdict(), role=gates.VERIFIER)
            self.conductor = conductor.Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            drive(self.conductor)
            self.calls = list(fake.calls)

    def check_launch(self, difficulty):
        rung, model, effort, turns, minutes = EXPECTED[difficulty]
        self.launch_at(difficulty)
        request = self.calls[0].request
        self.assertEqual(request.role, "coder")
        self.assertEqual((request.model, request.effort, request.max_minutes), (model, effort, minutes))
        self.assertEqual(request.agent_json[request.role]["maxTurns"], turns)
        self.assertEqual(request.agent_json[request.role]["model"], model)
        launched = self.payload("ticket_launched")
        self.assertEqual((launched["difficulty"], launched["rung"], launched["model"], launched["effort"]),
                         (difficulty, rung, model, effort))
        self.assertIn("(coder, r%d %s %s, attempt 1)" % (rung, model, effort), self.conductor.out.getvalue())
        for call in self.calls:
            if call.request.role == "coder":
                self.assertIn(call.request.effort, ("low", "medium", "high"), "the cap: ticket work never runs above high")
        if difficulty >= 3:
            # The read a difficulty 3 to 5 ticket earns (decision 11) stays keyed to the level; its verdict carries the rung.
            self.assertEqual(self.calls[1].request.role, gates.VERIFIER)
            self.assertEqual(self.payload("verdict")["rung"], rung)
            self.assertEqual(self.ticket()["status"], "accepted")
        else:
            self.assertEqual([call.request.role for call in self.calls], ["coder"])
            self.assertEqual(self.ticket()["status"], "done")

    def test_difficulty_1_launches_on_rung_2(self):
        self.check_launch(1)

    def test_difficulty_2_launches_on_rung_3(self):
        self.check_launch(2)

    def test_difficulty_3_launches_on_rung_5_and_its_verdict_carries_the_rung(self):
        self.check_launch(3)

    def test_difficulty_4_launches_on_fable_low(self):
        self.check_launch(4)

    def test_difficulty_5_launches_on_fable_high_not_max(self):
        self.check_launch(5)
        verifier = self.calls[1].request
        self.assertEqual((verifier.model, verifier.effort), ("opus", "max"), "the verifier table's effort, which the cap does not bind")

    def test_an_old_shape_override_refuses_the_run_naming_upgrade(self):
        harness_path = self.project / project.HARNESS_JSON
        harness = json.loads(harness_path.read_text(encoding="utf-8"))
        harness["policy"] = {"difficulty": {"4": {"model": "fable", "effort": "xhigh", "budget": "large"}}}
        harness_path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "override")
        problems = conductor.refuse_to_start(self.project)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("wayline upgrade", problems[0])
        self.assertIn("level 4", problems[0])

    def test_a_valid_override_does_not_refuse_the_run(self):
        harness_path = self.project / project.HARNESS_JSON
        harness = json.loads(harness_path.read_text(encoding="utf-8"))
        harness["policy"] = {"difficulty": {"4": 7}}
        harness_path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "override")
        self.assertEqual(conductor.refuse_to_start(self.project), [])
        self.assertEqual(conductor.tier_for(project.policy_for(self.project), 4).label, "r7 fable high")


class JournalTest(unittest.TestCase):
    """`ticket_launched` and `verdict` carry `rung` (decision 2)."""

    def test_a_launch_and_a_verdict_carry_the_rung(self):
        launched = make_event("ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "model": "opus", "effort": "high",
                                                  "skills": [], "worktree": ".worktrees/1", "pid": 1, "context_chars": 1,
                                                  "prompt_sha256": "0" * 64, "difficulty": 3, "rung": 5}, ticket=1)
        self.assertEqual(launched["payload"]["rung"], 5)
        verdict = gates.Verdict(subject_kind="ticket", subject="research/tickets/01-x.md", verdict_type="diff", passed=True,
                                question_limit="the diff", session_id="s", model="claude-fable-5-1", ticket=1, rung=5)
        self.assertEqual(verdict.payload["rung"], 5)
        self.assertEqual(make_event("verdict", verdict.payload, ticket=1)["payload"]["rung"], 5)

    def test_a_verdict_off_a_ticket_carries_no_rung(self):
        verdict = gates.Verdict(subject_kind="claim", subject="c-0001", verdict_type="claim", passed=True, question_limit="the claim")
        self.assertNotIn("rung", verdict.payload)

    def test_the_asks_of_a_ticket_carry_the_rung_of_the_attempt_that_wrote_it(self):
        ticket = {"id": 4, "acceptance": {"quality": ["It reads well."]}}
        asks = gates.ticket_asks(ticket, 4, "fable", "research/tickets/04-x.md", rung=6)
        self.assertEqual([(ask.verdict_type, ask.rung, ask.author_model) for ask in asks], [("quality", 6, "fable"), ("result", 6, "fable")])
        self.assertEqual([ask.rung for ask in gates.ticket_asks(ticket, 4, "fable", "research/tickets/04-x.md")], [None, None])

    def test_the_verifier_table_is_keyed_by_the_authors_family(self):
        policy = json.loads((conductor.HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(gates.verifier_tier(policy, "claude-sonnet-5"), ("opus", "high"))
        self.assertEqual(gates.verifier_tier(policy, "claude-fable-5-1"), ("opus", "max"), "the verifier's effort is not capped")
        with self.assertRaises(gates.GateError):
            gates.verifier_tier(policy, "gpt-5")


class LabelTest(unittest.TestCase):
    """`r<index> <model> <effort>`, and a journal without `rung` still renders."""

    def test_the_label(self):
        self.assertEqual(project.rung_label(5, "opus", "high"), "r5 opus high")
        self.assertEqual(project.rung_label(None, "opus", "high"), "opus high")
        self.assertEqual(project.rung_label(6, "claude-fable-5-1", "low"), "r6 claude-fable-5-1 low")
        self.assertEqual(conductor.Tier(model="opus", effort="high").label, "opus high")

    def test_the_planners_rubric_names_each_levels_rung(self):
        policy = json.loads((conductor.HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        text = plan.rubric_text(policy)
        self.assertIn("Rung 2, sonnet at low, a small budget.", text)
        self.assertIn("Rung 7, fable at high, a large budget.", text)
        self.assertIn("policy.tiers", text)


class StatusLabelTest(ProjectTestCase):
    """`wayline status` labels each launched ticket from `ticket_launched`, with or without `rung`."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.ledger = Ledger(self.project)

    def running(self):
        view = project.status_view(self.project)
        self.assertEqual(len(view["running"]), 1)
        return view, view["running"][0]

    def test_a_journal_without_rung_labels_the_launch_by_model_and_effort(self):
        view, entry = self.running()
        self.assertEqual(entry["launch"], "opus high")
        line = next(line for line in project.render_status(view).splitlines() if line.startswith("  #%-3d" % entry["id"]))
        self.assertTrue(line.endswith("attempt 1  opus high"), line)
        self.assertIsNone(next(line for line in view["frontier"] if line["id"] == 5)["launch"], "never launched")

    def test_a_launch_with_rung_is_labeled_r_index_model_effort(self):
        _, entry = self.running()
        self.ledger.append_event("ticket_launched", {
            "ticket": entry["id"], "attempt": entry["attempt"] + 1, "role": entry["role"], "model": "opus", "effort": "high", "skills": [],
            "worktree": ".worktrees/%d" % entry["id"], "pid": 4242, "context_chars": 100, "prompt_sha256": "b" * 64,
            "difficulty": 3, "rung": 5}, ticket=entry["id"])
        view, entry = self.running()
        self.assertEqual(entry["launch"], "r5 opus high")
        self.assertIn("r5 opus high", project.render_status(view))


class LauncherModelTest(unittest.TestCase):
    """A rung's model reaches the launcher as an alias or a full version name (decision 3)."""

    def request(self, model):
        return worker.LaunchRequest(role="coder", model=model, effort="high", prompt="x",
                                    agent_json={"coder": {"description": "d", "prompt": "p", "model": model, "effort": "high"}})

    def test_a_full_version_name_is_accepted_and_an_unknown_one_refused(self):
        self.request("claude-opus-4-8").check()
        self.request("opus").check()
        with self.assertRaises(worker.LaunchError):
            self.request("gpt-5").check()

    def test_a_full_fable_name_falls_back_to_opus_like_the_alias(self):
        moved, changed = worker.fall_back(self.request("claude-fable-5-1"))
        self.assertTrue(changed)
        self.assertEqual((moved.model, moved.agent_json["coder"]["model"]), ("opus", "opus"))
        self.assertTrue(worker.launches_on(self.request("claude-fable-5-1"), "fable"))
        self.assertFalse(worker.launches_on(self.request("claude-opus-4-8"), "fable"))


if __name__ == "__main__":
    unittest.main()
