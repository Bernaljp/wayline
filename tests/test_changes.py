"""Feedback, change records, and harness tickets (ticket 45; Implementation Decisions 12 and 16).

The evolver is driven through the fake launcher (seam 1). What is asserted is what the owner and the
conductor see: the files under `research/feedback/` and `research/changes/`, the journal's `feedback`,
`change_record`, `ticket_created`, and `decision_opened` events, the harness ticket files, and
`REPORT.md`'s proposals. The conductor's path for a local and a global change is in
`tests/test_harness_tickets.py`.
"""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase, fable_policy, open_objective
from tests.test_specify import run
from wayline import changes, gates, project, provenance, tickets, worker
from wayline.ledger import Ledger
from wayline.tickets import read_ticket, read_tickets, tickets_dir
from wayline.worker import Envelope


def events_of(ledger, name):
    return [event for event in ledger.read_events()[0] if event["event"] == name]


class IntakeTest(ProjectTestCase):
    """Criterion 1: the three ways feedback arrives, each journaled as `feedback` with its source."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        project.init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)

    def test_feedback_from_the_command_line_is_a_file_and_an_event(self):
        item = changes.file_feedback(self.project, "The tickets are too big: ticket 4 took three attempts.", source="cli")
        self.assertEqual(item["id"], "001-the-tickets-are-too-big")
        self.assertEqual(item["source"], "cli")
        text = (self.project / "research" / "feedback" / "001-the-tickets-are-too-big.md").read_text(encoding="utf-8")
        self.assertIn("three attempts", text)
        self.assertEqual([event["payload"] for event in events_of(self.ledger, "feedback")],
                         [{"id": "001-the-tickets-are-too-big", "source": "cli"}])

    def test_the_verb_files_it(self):
        code, out, err = run("feedback", "captions overclaim", "--project", str(self.project))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("001-captions-overclaim", out)
        self.assertEqual(events_of(self.ledger, "feedback")[0]["payload"]["source"], "cli")
        code, _, err = run("feedback", "   ", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("no text", err)

    def test_a_second_item_takes_the_next_number_and_the_same_words_a_new_file(self):
        changes.file_feedback(self.project, "captions overclaim", source="dashboard")
        item = changes.file_feedback(self.project, "captions overclaim", source="dashboard")
        self.assertEqual(item["id"], "002-captions-overclaim")
        self.assertEqual([event["payload"]["source"] for event in events_of(self.ledger, "feedback")], ["dashboard", "dashboard"])

    def test_a_file_dropped_in_the_directory_is_journaled_once(self):
        dropped = self.project / "research" / "feedback" / "Notes from Monday.md"
        dropped.write_text("The figure captions claim more than the table shows.\n", encoding="utf-8")
        (self.project / "research" / "feedback" / ".hidden").write_text("not feedback\n", encoding="utf-8")
        taken = changes.take_dropped(self.project)
        self.assertEqual([item["id"] for item in taken], ["Notes from Monday"])
        self.assertEqual(changes.take_dropped(self.project), [], "journaled once")
        self.assertEqual([event["payload"] for event in events_of(self.ledger, "feedback")],
                         [{"id": "Notes from Monday", "source": "file"}])

    def test_what_is_pending_is_what_no_evolver_session_has_read(self):
        changes.file_feedback(self.project, "captions overclaim", source="cli")
        (self.project / "research" / "feedback" / "big.txt").write_text("tickets too big\n", encoding="utf-8")
        pending = changes.pending_feedback(self.project)
        self.assertEqual([(item["id"], item["source"]) for item in pending], [("001-captions-overclaim", "cli"), ("big", "file")])
        self.assertEqual(pending[1]["text"], "tickets too big\n")
        changes.mark_read(self.ledger, {"big": {"records": [], "dismissed": "nothing to change"}}, session_id="s-1")
        self.assertEqual([item["id"] for item in changes.pending_feedback(self.project)], ["001-captions-overclaim"])

    def test_empty_feedback_is_refused(self):
        with self.assertRaises(changes.ChangeError):
            changes.file_feedback(self.project, " \n", source="cli")
        with self.assertRaises(changes.ChangeError):
            changes.file_feedback(self.project, "text", source="email")


def record(**changes_made):
    """One record as the evolver returns it: a local skill that holds captions to the table."""
    value = {
        "feedback": "001-captions-overclaim", "title": "Hold figure captions to the table",
        "observed": {"text": "The caption of figure 2 says the method wins everywhere; the table shows two ties.",
                     "journal_events": ["research/journal.jsonl#L1"]},
        "desired": "A caption claims only what the table it draws from shows.",
        "mechanism": "skill", "scope_kind": "local", "risk": "low", "target": ".claude/skills/wayline-caption-claims/", "keys": [],
        "fixture": "skill/wayline-caption-claims", "difficulty": 2,
        "acceptance": ["test -f .claude/skills/wayline-caption-claims/SKILL.md"],
        "notes": "Record the fixture from the writer's session of ticket 7; the rubric asks whether every claim is in the table.",
    }
    value.update(changes_made)
    return value


def answer(*records, dismissed=(), recommendations=()):
    return Envelope(structured_output={"records": list(records), "dismissed": list(dismissed), "recommendations": list(recommendations)},
                    session_id="evolver-1", num_turns=12, duration_ms=60000)


LADDER = dict(title="Send difficulty 2 to opus low", mechanism="policy", scope_kind="local", risk="low", target="harness.json",
              keys=["difficulty"], fixture="role/coder-small-change", acceptance=["grep -q difficulty harness.json"])
GLOBAL = dict(title="Tell the planner to cut smaller tickets", mechanism="prompt", scope_kind="global", risk="medium",
              target="prompts/roles/planner.md", fixture="role/planner-small-tickets", acceptance=["grep -qi smaller prompts/roles/planner.md"])


class EvolveCase(ProjectTestCase):
    """A project with one item of feedback filed, the real harness's evolver role, and the fake launcher."""

    autonomy = "checkpoints"

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "study").resolve()
        project.init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        open_objective(self.project)
        project.set_autonomy(self.project, self.autonomy)
        self.ledger = Ledger(self.project)
        changes.file_feedback(self.project, "captions overclaim", source="dashboard")
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def notify(self, event, text, path, ticket):
        self.notified.append((event, ticket, text))

    def evolve(self, *envelopes, **options):
        for envelope in envelopes:
            self.fake.script(envelope, role=changes.EVOLVER)
        return changes.evolve(self.project, notify=self.notify, pre_check=False, fall_back=False, **options)

    def tickets(self):
        return {found["id"]: found for found in read_tickets(self.project)}

    def body(self, identifier):
        return read_ticket(tickets_dir(self.project) / tickets.filename(self.tickets()[identifier]))[1]


class EvolverTest(EvolveCase):
    """Criteria 2 and 3: the evolver's records become change records, and code files one harness ticket per record."""

    def test_the_role_is_read_only_and_runs_at_opus_xhigh(self):
        role = worker.read_role(changes.EVOLVER)
        self.assertEqual(role.output_schema, "change_list")
        self.assertEqual(role.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in ("Edit", "Write", "Bash", "Agent"):
            self.assertIn(tool, role.disallowed_tools)
        policy = project.policy_for(self.project, HARNESS_ROOT)
        for fall_back in (False, True):
            self.assertEqual(changes.evolver_tier(policy, fall_back=fall_back), ("opus", "xhigh", None))
        evolver_on_fable = fable_policy(policy, "evolver")
        self.assertEqual(changes.evolver_tier(evolver_on_fable), ("fable", "xhigh", None))
        self.assertEqual(changes.evolver_tier(evolver_on_fable, fall_back=True), ("opus", "xhigh", "fable"))

    def test_feedback_becomes_a_change_record_and_a_harness_ticket(self):
        report = self.evolve(answer(record()))
        self.assertEqual(report["records"], ["001-hold-figure-captions-to-the-table"])
        kept = json.loads((self.project / "research" / "changes" / "001-hold-figure-captions-to-the-table.json").read_text(encoding="utf-8"))
        self.assertEqual((kept["status"], kept["ticket"], kept["feedback"], kept["risk"]), ("open", 1, "001-captions-overclaim", "low"))
        self.assertEqual([event["payload"] for event in events_of(self.ledger, "change_record")],
                         [{"id": kept["id"], "scope_kind": "local", "mechanism": "skill", "fixture": "skill/wayline-caption-claims"}])
        ticket = self.tickets()[1]
        self.assertEqual((ticket["kind"], ticket["role"], ticket["proposed_by"], ticket["origin"]),
                         ("harness", "coder", "evolve", "change 001-hold-figure-captions-to-the-table"))
        self.assertEqual(ticket["touches"], [".claude/skills/wayline-caption-claims/", "fixtures/skill/wayline-caption-claims/"])
        self.assertIn("research/changes/%s.json" % kept["id"], ticket["context_pack"])
        self.assertEqual(changes.change_of(ticket), kept["id"])
        body = self.body(1)
        self.assertIn("fails on the subject as it is", body)
        self.assertIn("two ties", body)
        self.assertEqual([event["payload"]["kind"] for event in events_of(self.ledger, "ticket_created")], ["harness"])
        self.assertEqual([event["payload"]["role"] for event in events_of(self.ledger, "assigned")], ["coder"])
        self.assertEqual(changes.pending_feedback(self.project), [], "the item is read")

    def test_the_prompt_carries_the_feedback_the_numbered_journal_and_the_open_records(self):
        self.evolve(answer(record()))
        changes.file_feedback(self.project, "tickets too big", source="cli")
        self.evolve(answer(dismissed=[{"feedback": "002-tickets-too-big", "reason": "One run is not a pattern."}]))
        first, second = [call.request.prompt for call in self.fake.calls]
        self.assertIn("## 001-captions-overclaim (dashboard)", first)
        self.assertIn("L1 ", first)
        self.assertNotIn("001-captions-overclaim (dashboard)", second, "an item is shown to one session")
        self.assertIn("001-hold-figure-captions-to-the-table", second, "the open record is named, so it is not proposed again")
        self.assertEqual(changes.read_state(self.ledger)["read"]["002-tickets-too-big"]["dismissed"], "One run is not a pattern.")

    def test_the_verb_files_its_text_and_runs_the_loop(self):
        self.fake.script(respond=lambda request, message: answer(record(), dismissed=[
            {"feedback": "002-tickets-too-big", "reason": "One run is not a pattern."}]), role=changes.EVOLVER)
        with mock.patch.object(changes.registry, "plugin_validate", return_value=({}, None)):  # the free pre-check reaches the real CLI
            code, out, err = run("evolve", "tickets too big", "--project", str(self.project))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([event["payload"] for event in events_of(self.ledger, "feedback")],
                         [{"id": "001-captions-overclaim", "source": "dashboard"}, {"id": "002-tickets-too-big", "source": "cli"}])
        self.assertIn("evolved  2 item(s) into 1 change record(s)", out)
        self.assertIn("harness ticket(s) 1 filed", out)
        self.assertIn("dismissed 002-tickets-too-big: One run is not a pattern.", out)
        code, out, _ = run("evolve", "--project", str(self.project))
        self.assertEqual(code, 0)
        self.assertIn("no feedback is pending", out)
        code, _, err = run("evolve", "--tag", "next", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("vMAJOR.MINOR.PATCH", err)

    def test_nothing_pending_launches_nothing(self):
        self.evolve(answer(record()))
        report = self.evolve()
        self.assertEqual((report["launched"], report["records"]), (False, []))
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_list_that_fails_the_checks_goes_back_once_with_every_failure(self):
        bad = record(feedback="009-nobody-filed-this", target="/etc/passwd",
                     observed={"text": "x", "journal_events": ["research/journal.jsonl#L9999"]})
        report = self.evolve(answer(bad), answer(record()))
        self.assertEqual(len(report["records"]), 1)
        message = self.fake.calls[1].message
        self.assertIn("009-nobody-filed-this", message)
        self.assertIn("/etc/passwd", message)
        self.assertIn("L9999", message)
        self.assertIn("001-captions-overclaim is answered by no record", message)
        changes.file_feedback(self.project, "again", source="cli")
        with self.assertRaises(changes.ChangeError):
            self.evolve(answer(bad), answer(bad))
        self.assertEqual(len(read_tickets(self.project)), 1, "a list refused twice files nothing")

    def test_the_target_follows_the_mechanism_and_the_scope(self):
        policy = project.policy_for(self.project, HARNESS_ROOT)

        def problem(**changes_made):
            return changes.target_problem(record(**changes_made), self.project, HARNESS_ROOT, policy)

        self.assertIsNone(problem())
        self.assertIsNone(problem(mechanism="role", target=".claude/agents/writer.md"))
        self.assertIsNone(problem(**LADDER))
        self.assertIsNone(problem(**GLOBAL))
        self.assertIn("wayline-", problem(target=".claude/skills/caption-claims/"))
        self.assertIn("no role", problem(mechanism="role", target=".claude/agents/nobody.md"))
        self.assertIn("global", problem(mechanism="hook", target=".claude/hooks/guard.sh"))
        self.assertIn("harness.json", problem(mechanism="policy", target=".claude/agents/writer.md", keys=["pacing"]))
        self.assertIn("names no policy key", problem(mechanism="policy", target="harness.json", keys=[]))
        self.assertIn("no policy key `ladder`", problem(mechanism="policy", target="harness.json", keys=["ladder"]))
        self.assertIn("leaves", problem(**dict(GLOBAL, target="../elsewhere/agent.md")))
        self.assertIn("research/", problem(**dict(GLOBAL, target="research/journal.jsonl")))
        self.assertIn("holds no", problem(**dict(GLOBAL, target="nowhere/agent.md")))


class ReviewFixesTest(EvolveCase):
    """What the code review of ticket 45 found: a session is never spent twice on one item, whatever goes wrong around it."""

    def test_a_list_that_cannot_be_filed_marks_its_items_read_and_writes_nothing(self):
        with mock.patch.object(changes.registry, "librarian", return_value={"role": None, "skills": [], "notes": ["no role"]}):
            with self.assertRaises(changes.ChangeError):
                self.evolve(answer(record()))
        self.assertEqual(changes.read_changes(self.project), [], "the role is checked before anything is written")
        self.assertEqual(read_tickets(self.project), [])
        self.assertIn("could not be filed", changes.read_state(self.ledger)["read"]["001-captions-overclaim"]["dismissed"])
        self.assertEqual(changes.pending_feedback(self.project), [], "a wave does not launch the evolver over it again")

    def test_a_failure_part_way_names_what_was_written(self):
        with mock.patch.object(changes.decisions, "open_decision", side_effect=changes.TicketError("the graph would hold a cycle")):
            with self.assertRaises(changes.TicketError):
                self.evolve(answer(record(**LADDER)))
        made = changes.read_state(self.ledger)["read"]["001-captions-overclaim"]
        self.assertEqual(made["records"], ["001-send-difficulty-2-to-opus-low"])
        self.assertIn("written before the failure: 001-send-difficulty-2-to-opus-low", made["dismissed"])

    def test_an_item_another_live_process_is_evolving_is_not_pending(self):
        state = changes.read_state(self.ledger)
        state["claimed"]["001-captions-overclaim"] = {"pid": os.getppid(), "ts": "2026-09-20T10:00:00Z"}
        self.ledger.write_json(changes.EVOLVE_JSON, state)
        self.assertEqual(changes.pending_feedback(self.project), [])
        self.assertEqual(self.evolve()["launched"], False, "the second process finds nothing to do")
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        state["claimed"]["001-captions-overclaim"]["pid"] = gone.pid
        self.ledger.write_json(changes.EVOLVE_JSON, state)
        self.assertEqual([item["id"] for item in changes.pending_feedback(self.project)], ["001-captions-overclaim"],
                         "a claim whose process is gone holds nothing")

    def test_a_session_claims_its_items_and_leaves_no_claim_behind(self):
        seen = []

        def respond(request, message):
            seen.append(dict(changes.read_state(self.ledger)["claimed"]))
            return answer(record())

        self.fake.script(respond=respond, role=changes.EVOLVER)
        self.evolve()
        self.assertEqual([sorted(claims) for claims in seen], [["001-captions-overclaim"]])
        self.assertEqual(seen[0]["001-captions-overclaim"]["pid"], os.getpid())
        self.assertEqual(changes.read_state(self.ledger)["claimed"], {})

    def test_a_launch_that_fails_releases_the_claim_and_leaves_the_items_pending(self):
        with self.assertRaises(worker.LaunchError):
            self.evolve()  # nothing is scripted, so the fake launcher refuses the call
        self.assertEqual(changes.read_state(self.ledger)["claimed"], {})
        self.assertEqual([item["id"] for item in changes.pending_feedback(self.project)], ["001-captions-overclaim"])

    def test_a_global_ticket_names_its_branch_in_its_origin_and_earns_no_verdict(self):
        self.evolve(answer(record(difficulty=5, **GLOBAL)))
        kept = changes.read_changes(self.project)[0]
        ticket = self.tickets()[kept["ticket"]]
        self.assertEqual(ticket["origin"], "change %s: evolve/%s" % (kept["id"], kept["id"]))
        self.assertEqual(changes.change_of(ticket), kept["id"])
        self.assertTrue(tickets.works_in_the_harness(ticket))
        self.assertEqual(gates.owed_asks(ticket, 5, "fable", None, ()), ([], []), "neither the conductor's restart nor the tick owes it one")
        local = dict(ticket, origin="change %s" % kept["id"])
        self.assertFalse(tickets.works_in_the_harness(local))
        self.assertTrue(gates.owed_asks(local, 5, "fable", "0123abc", ())[0], "a local change at difficulty 5 earns its verdicts like any ticket")


class LadderTest(EvolveCase):
    """Criterion 6: a change to the rung ladder is always high risk, and the ladder consent says who may approve it."""

    def ladder(self):
        self.evolve(answer(record(**LADDER)))
        kept = changes.read_changes(self.project)[0]
        return kept, self.tickets()

    def test_it_is_high_risk_whatever_the_evolver_said(self):
        self.assertTrue(changes.is_ladder_change(record(**LADDER)))
        self.assertTrue(changes.is_ladder_change(record(**dict(LADDER, keys=["pacing", "tiers"]))))
        self.assertFalse(changes.is_ladder_change(record(**dict(LADDER, keys=["pacing"]))))
        self.assertFalse(changes.is_ladder_change(record(keys=["tiers"])), "only a policy change has keys that count")
        kept, _ = self.ladder()
        self.assertEqual(kept["risk"], "high")

    def test_without_the_key_it_is_a_human_only_decision_of_class_ladder(self):
        kept, found = self.ladder()
        decision = found[kept["decision"]]
        self.assertEqual((decision["kind"], decision["human_only"], decision["origin"]),
                         ("decision", True, "change %s: ladder" % kept["id"]))
        self.assertEqual(found[kept["ticket"]]["blocked_by"], [kept["decision"]], "the harness ticket waits for the answer")
        self.assertEqual(events_of(self.ledger, "decision_opened")[0]["payload"]["human_only"], True)
        self.assertTrue(any("rung ladder" in text for _, _, text in self.notified))

    def test_a_refusal_parks_the_harness_ticket_and_an_approval_leaves_it(self):
        kept, _ = self.ladder()
        self.assertEqual(changes.ladder_answered(self.project, self.tickets()[kept["decision"]], "approve"), [])
        self.assertEqual(self.tickets()[kept["ticket"]]["status"], "open")
        self.assertEqual(changes.ladder_answered(self.project, self.tickets()[kept["decision"]], "decline: keep sonnet"), [kept["ticket"]])
        self.assertEqual(self.tickets()[kept["ticket"]]["status"], "parked")
        self.assertEqual(changes.read_changes(self.project)[0]["status"], "declined")
        self.assertEqual(changes.ladder_answered(self.project, self.tickets()[kept["ticket"]], "decline"), [], "any other ticket is left alone")


class AutonomousLadderTest(EvolveCase):
    autonomy = "autonomous"

    def test_under_ask_it_is_human_only_and_under_auto_the_decider_may_take_it(self):
        project.set_ladder_changes(self.project, "ask")
        self.evolve(answer(record(**LADDER)))
        first = changes.read_changes(self.project)[0]
        self.assertTrue(self.tickets()[first["decision"]]["human_only"])
        project.set_ladder_changes(self.project, "auto")
        changes.file_feedback(self.project, "ladder again", source="cli")
        self.evolve(answer(record(**dict(LADDER, feedback="002-ladder-again", title="Send difficulty 1 to haiku"))))
        second = changes.read_changes(self.project)[1]
        self.assertFalse(self.tickets()[second["decision"]]["human_only"], "the decider may approve it under auto")
        self.assertEqual(second["risk"], "high")

    def test_a_global_change_is_a_proposal_in_the_account_and_nothing_is_applied(self):
        report = self.evolve(answer(record(**GLOBAL)))
        kept = changes.read_changes(self.project)[0]
        self.assertEqual((kept["status"], kept["ticket"], kept["branch"]), ("proposed", None, None))
        self.assertEqual(report["proposed"], [kept["id"]])
        self.assertEqual(read_tickets(self.project), [], "no harness ticket is filed")
        self.assertEqual(events_of(self.ledger, "change_record")[0]["payload"]["scope_kind"], "global")
        lines = changes.proposal_lines(self.project)
        self.assertTrue(any("Tell the planner to cut smaller tickets" in line and "prompts/roles/planner.md" in line for line in lines))
        self.assertTrue(any("wayline evolve --apply %s" % kept["id"] in line for line in lines))
        provenance.render_report(self.project, offline=True, draft=False)
        told = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8").split("## Waiting on you", 1)[1]
        self.assertIn("Global change `%s`, *Tell the planner to cut smaller tickets*" % kept["id"], told)
        self.assertIn("proposed, not applied; `wayline evolve --apply %s` applies it" % kept["id"], told)
        self.assertNotIn("promote", told, "one wording for applying a global change (decision 17)")
        self.assertEqual(len(self.fake.calls), 1, "the report launched nothing, and no harness ticket ran")

    def test_the_owner_applies_a_proposal_by_hand(self):
        self.evolve(answer(record(difficulty=4, **GLOBAL)))
        kept = changes.read_changes(self.project)[0]
        applied = changes.apply_proposal(self.project, kept["id"], pre_check=False)
        self.assertEqual((applied["status"], applied["branch"]), ("open", "evolve/%s" % kept["id"]))
        ticket = self.tickets()[applied["ticket"]]
        self.assertEqual((ticket["kind"], ticket["difficulty"], ticket["acceptance"]["machine"]),
                         ("harness", 4, ["grep -qi smaller prompts/roles/planner.md"]), "filed as the evolver graded and gated it")
        with self.assertRaises(changes.ChangeError):
            changes.apply_proposal(self.project, kept["id"], pre_check=False)


class GlobalTicketTest(EvolveCase):
    def test_a_global_change_under_checkpoints_is_a_ticket_on_its_own_branch(self):
        self.evolve(answer(record(**GLOBAL)))
        kept = changes.read_changes(self.project)[0]
        self.assertEqual((kept["status"], kept["branch"]), ("open", "evolve/%s" % kept["id"]))
        ticket = self.tickets()[kept["ticket"]]
        self.assertEqual(ticket["touches"], ["prompts/roles/planner.md", "fixtures/role/planner-small-tickets/"])
        self.assertIn("evolve/%s" % kept["id"], self.body(kept["ticket"]))


if __name__ == "__main__":
    unittest.main()
