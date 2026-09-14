"""Decision tickets end to end (ticket 35; Implementation Decisions 5, 7, and 8; BRIEF 6.6).

`fixtures/projects/decision-branch/` runs with the fake worker: decision ticket 2, `blocking:
subgraph`, holds the beta branch while the alpha branch runs. The owner's answer is given through
each of the four paths, is journaled once as a human decision, is what the tick relaunches the
conductor for, and releases the branch at the relaunched run's first wave. A worker's
`decision_requests` open decision tickets of their own. What is asserted is what the owner and the
next process see: the journal, the ticket files, the launches, and what was said.
"""

import http.client
import importlib.util
import io
import json
import os
import shutil
import subprocess
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import HELLO, WRONG, ConductorCase, done as worker_done, patch as worker_patch
from wayline import cli, decisions, grill, notify, project, schedule, tick, tickets, worker
from wayline.conductor import Conductor
from wayline.dashboard import LOOPBACK, TOKEN_HEADER, make_server
from wayline.frontmatter import dump_document
from wayline.ledger import Ledger
from wayline.project import ProjectError
from wayline.tickets import TicketError

BRANCH = HARNESS_ROOT / "fixtures" / "projects" / "decision-branch"
WAYLINE = HARNESS_ROOT / "bin" / "wayline"
DECISION_FILE = "02-which-form-does-the-beta-report-take.md"
TOKEN = "a-token-for-the-answer-form"
REQUEST = {"question": "Does the alpha note stay one word?", "options": ["one word", "a sentence"], "recommended": "one word",
           "evidence": ["notes/alpha.md holds the line alpha"], "blocking": "subgraph"}


class BranchCase(ProjectTestCase):
    """A laid-out copy of the decision-branch fixture, with the notifier recorded rather than sent."""

    git = True

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "decision-branch").resolve()
        shutil.copytree(BRANCH, self.project)
        project.init_project(self.project, git=self.git, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)
        self.notified = []
        self.out = io.StringIO()

    def notify(self, event, text, path, ticket):
        self.notified.append((event, ticket, text))

    def events(self, name=None):
        found, _ = self.ledger.read_events()
        return [event for event in found if name is None or event["event"] == name]

    def statuses(self):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def ticket(self, identifier):
        return {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[identifier]

    def ticket_path(self, identifier):
        return tickets.tickets_dir(self.project) / tickets.filename(self.ticket(identifier))

    def body(self, identifier):
        return tickets.read_ticket(self.ticket_path(identifier))[1]

    def write_answer(self, identifier, text):
        """What a person does in an editor: the answer under an `## Answer` heading at the end of the file."""
        path = self.ticket_path(identifier)
        path.write_text(path.read_text(encoding="utf-8") + "\n## Answer\n\n%s\n" % text, encoding="utf-8")


class ConductedCase(BranchCase):
    """The fixture with the fake worker it ships with, run by a conductor whose notifier is recorded."""

    def setUp(self):
        super().setUp()
        self.fake = self.enterContext(worker.use_fake())

    def script(self, requests_of_ticket_one=None):
        """The fixture's fake worker script; ticket 1's result also asks these decisions when they are given."""
        entries = json.loads((BRANCH / "fake-worker.json").read_text(encoding="utf-8"))
        for entry in entries:
            if entry["ticket"] == "1" and requests_of_ticket_one:
                entry["envelope"]["structured_output"]["decision_requests"] = requests_of_ticket_one
            self.fake.script(entry["envelope"], patch=entry["patch"], ticket=entry["ticket"])

    def conductor(self):
        driven = Conductor(self.project, out=self.out)
        driven.notify = self.notify
        return driven

    def conduct(self):
        """One run to its end, its sessions settled between waves: the tickets each wave launched, and the waves."""
        driven = self.conductor()
        waves = driven.run(wait=lambda seconds: driven.settle())
        return [sorted(wave.launched) for wave in waves if wave.launched], waves

    def tick(self):
        """One tick with no conductor alive, recording the relaunch it asks for rather than starting a unit."""
        self.relaunched = []

        def relaunch(path):
            self.relaunched.append(Path(path).resolve())
            return "recorded"

        machine = tick.Machine(conductor=lambda path: None, credentials=self.temp / "no-credentials.json", environ={},
                               notify=self.notify, relaunch=relaunch, render=lambda path: None,
                               poll_jobs=lambda path: [], checks=lambda path: [])
        return tick.tick(project=self.project, machine=machine, out=io.StringIO())


# --- the subgraph waits, the other branch runs, and every answer path releases it ---------------------------


class AnswerPathsTest(ConductedCase):
    """Criteria 1, 2, and 5: one branch waits on the decision, the other runs, and each answer path releases the first."""

    def setUp(self):
        super().setUp()
        self.script()
        self.launched, self.waves = self.conduct()
        self.said = self.out.getvalue()

    def released(self, answer="one line", rationale=None):
        """The tick relaunches for the answer, and the relaunched run closes ticket 2 and runs the branch it held."""
        result = self.tick()
        self.assertTrue(result.relaunched, result.why)
        self.assertEqual(self.relaunched, [self.project])
        self.assertIn("a decision ticket was answered since the conductor last ran", result.why)
        decided = [event["payload"] for event in self.events("decision")]
        self.assertEqual(decided, [{"ticket": 2, "answer": answer, "decided_by": "human", "rationale": rationale, "confidence": None}])
        launched, _ = self.conduct()
        self.assertEqual(launched, [[3], [5]])
        self.assertEqual(set(self.statuses().values()), {"done"})
        self.assertEqual(len(self.events("decision")), 1, "closing the ticket journals no second decision")
        where = {(event["event"], event["ticket"]): index for index, event in enumerate(self.events())}
        self.assertLess(where[("decision", 2)], where[("ticket_launched", 3)])
        self.assertEqual((self.project / "reports" / "beta.md").read_text(encoding="utf-8"), "beta\nbeta extended\n")

    def test_the_decision_holds_its_subgraph_while_the_other_branch_runs_to_the_end_of_the_run(self):
        self.assertEqual(self.launched, [[1], [4]])
        self.assertEqual(self.statuses(), {1: "done", 2: "open", 3: "open", 4: "done", 5: "open"})
        self.assertEqual((self.waves[-1].ended, self.waves[-1].reason), (True, "frontier_empty"))
        self.assertIn("ticket 3 waits on the open decision ticket 2, which pauses its subgraph", self.said)
        self.assertIn("ticket 5 waits on the open decision ticket 2, which pauses its subgraph", self.said)
        self.assertIn("decision ticket 2 waits for the owner's answer: under autonomy checkpoints the owner answers every decision ticket",
                      self.said)
        self.assertEqual(self.events("decision"), [])

    def test_no_session_is_launched_for_the_decision_ticket_under_checkpoints(self):
        self.assertEqual([event["payload"]["ticket"] for event in self.events("ticket_launched")], [1, 4])

    def test_without_an_answer_the_tick_does_not_relaunch(self):
        result = self.tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_wayline_answer_from_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["answer", "2", "one line", "--project", str(self.project)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(tickets.answer_section(self.body(2)), "one line")
        self.released()

    def test_an_answer_written_into_the_ticket_file_is_journaled_by_the_tick(self):
        self.write_answer(2, "one line")
        self.assertEqual(self.events("decision"), [], "nothing is journaled until the tick or a wave reads the file")
        self.released()

    def test_the_dashboard_s_answer_form(self):
        server = make_server(LOOPBACK, 0, token=TOKEN, memo_ttl=0.0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address[:2], timeout=30)
        try:
            connection.request("POST", "/api/projects/%s/actions/answer" % self.project.name,
                               body=json.dumps({"ticket": 2, "answer": "one line", "rationale": "a glance is what the intake asks for"}),
                               headers={TOKEN_HEADER: TOKEN, "Content-Type": "application/json"})
            response = connection.getresponse()
            reply = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(5)
        self.assertEqual(response.status, 200, reply)
        self.released(rationale="a glance is what the intake asks for")

    def test_a_session_running_the_verb_in_the_project(self):
        """An interactive session answers for the owner as the project's CLAUDE.md block says: the verb, run in the project."""
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home))
        done = subprocess.run([str(WAYLINE), "answer", "2", "one line", "--rationale", "the owner said so in the session", "--project", "."],
                              cwd=self.project, env=environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("ticket 2 answered", done.stdout)
        self.released(rationale="the owner said so in the session")

    def test_the_project_s_claude_md_tells_a_session_how_to_answer(self):
        block = (self.project / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn('wayline answer <id> "<answer>" --rationale "<their reasons>" --project .', block)


class AnswerWhileRunningTest(ConductedCase):
    """Criterion 2's file path while a conductor runs: the wave, not the tick, is the first to read the edit."""

    def test_an_answer_written_mid_run_is_journaled_as_the_owner_s_and_applied_at_the_next_wave(self):
        self.script()
        driven = self.conductor()
        self.assertEqual(driven.wave().launched, [1])
        self.write_answer(2, "a table")
        driven.settle()
        second = driven.wave()
        driven.settle()
        self.assertEqual(sorted(second.launched), [3, 4])
        self.assertEqual(self.ticket(2)["status"], "done")
        self.assertEqual([event["payload"] for event in self.events("decision")],
                         [{"ticket": 2, "answer": "a table", "decided_by": "human", "rationale": None, "confidence": None}])
        self.assertIn("ticket 2: the answer written in its file is journaled as the owner's", self.out.getvalue())


class NoDeciderTest(ConductedCase):
    """Found by the review: under `autonomous` a decision ticket was launched on the decider role, which ticket 31 has not installed."""

    def test_under_autonomous_without_a_decider_the_decision_ticket_waits_for_the_owner_and_is_not_failed(self):
        project.set_autonomy(self.project, "autonomous")
        self.script()
        with mock.patch.object(decisions, "decider_ready", return_value=False):
            launched, _ = self.conduct()
            awaits = decisions.decisions_view(self.project)["open"][0]["awaits"]
        self.assertEqual(launched, [[1], [4]])
        self.assertEqual((self.ticket(2)["status"], awaits), ("open", "owner"))
        self.assertIn("decision ticket 2 waits for the owner's answer: no decider role is installed to answer it (ticket 31)",
                      self.out.getvalue())

    def test_a_harness_without_the_role_has_no_decider(self):
        self.assertFalse(decisions.decider_ready(harness_root=self.temp / "no-harness", project=self.project))


class BackgroundNotifyTest(ConductedCase):
    """Found by the review: the notifier ran inside the wave, so a slow channel held every other outcome and launch."""

    def test_a_slow_channel_holds_no_wave_and_settle_waits_for_it(self):
        release, sent = threading.Event(), []

        def slow(event, text, project=None, ticket=None, run=None):
            release.wait(60)
            sent.append((event, ticket))

        self.script(requests_of_ticket_one=[REQUEST])
        driven = Conductor(self.project, out=self.out)
        with mock.patch.object(notify, "notify", slow):
            self.assertEqual(driven.wave().launched, [1])
            driven.settle()
            carried = driven.wave()
            self.assertEqual(carried.done, [1])
            self.assertTrue(driven.notifying and driven.notifying[-1].is_alive(), "the wave returned while the channel still ran")
            self.assertEqual(sent, [])
            release.set()
            driven.settle()
        self.assertEqual(sent, [("decision_opened", 6)])


class ResumedRequestTest(ConductorCase):
    """Found by the review: the decision requests of a session resumed after a failed acceptance were never opened."""

    def test_what_a_session_resumed_after_a_failed_acceptance_asks_is_opened(self):
        self.conduct((worker_done(), worker_patch(WRONG)),
                     (worker_done(decision_requests=[REQUEST]), worker_patch(HELLO, message="ticket 1: fix hello.txt")))
        self.conductor.settle()
        opened = [event["payload"] for event in self.events("decision_opened")]
        self.assertEqual(len(opened), 1)
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[opened[0]["ticket"]]
        self.assertEqual((fields["kind"], fields["origin"]), ("decision", decisions.requested_origin(1, 1, REQUEST["question"])))
        self.assertEqual(self.ticket()["status"], "done")


# --- a worker's decision requests ---------------------------------------------------------------------------


class RequestedDecisionTest(ConductedCase):
    """Criterion 1: each of a worker's `decision_requests` opens a decision ticket that pauses what waits on the worker's ticket."""

    def setUp(self):
        super().setUp()
        self.script(requests_of_ticket_one=[REQUEST])
        self.launched, self.waves = self.conduct()

    def test_the_request_opens_a_decision_ticket_that_carries_the_question(self):
        fields = self.ticket(6)
        self.assertEqual((fields["kind"], fields["status"], fields["blocking"], fields["human_only"], fields["proposed_by"]),
                         ("decision", "open", "subgraph", False, "worker:1"))
        self.assertEqual(fields["origin"], decisions.requested_origin(1, 1, REQUEST["question"]))
        self.assertRegex(fields["origin"], r"\Aticket 1 attempt 1: decision request [0-9a-f]{12}\Z")
        self.assertEqual(fields["context_pack"], ["research/tickets/01-write-the-alpha-note.md"])
        record = decisions.decision_record(self.body(6))
        self.assertEqual({key: record[key] for key in ("ticket", "question", "options", "recommended", "evidence", "blocking", "human_only")},
                         dict(REQUEST, ticket=6, human_only=False))
        self.assertIsNone(record["answer"])

    def test_it_pauses_the_tickets_that_wait_on_the_ticket_that_asked(self):
        self.assertEqual(self.ticket(4)["blocked_by"], [1, 6])
        self.assertEqual(self.launched, [[1]])
        self.assertEqual(self.statuses(), {1: "done", 2: "open", 3: "open", 4: "open", 5: "open", 6: "open"})
        said = self.out.getvalue()
        self.assertIn("ticket 1 asked a decision: decision ticket 6, pausing ticket(s) 4", said)
        self.assertIn("ticket 4 waits on the open decision ticket 6, which pauses its subgraph", said)

    def test_its_creation_journals_decision_opened_and_notifies_the_owner(self):
        self.assertEqual([event["payload"] for event in self.events("ticket_created")],
                         [{"ticket": 6, "kind": "decision", "proposed_by": "worker:1", "origin": decisions.requested_origin(1, 1, REQUEST["question"]),
                           "blocked_by": []}])
        self.assertEqual([event["payload"] for event in self.events("decision_opened")],
                         [{"ticket": 6, "blocking": "subgraph", "human_only": False}])
        self.assertEqual([(event, ticket) for event, ticket, _ in self.notified], [("decision_opened", 6)])
        text = self.notified[0][2]
        self.assertIn("decision ticket 6 asks: Does the alpha note stay one word?", text)
        self.assertIn("It pauses ticket 4.", text)
        self.assertIn('wayline answer 6 "<answer>"', text)

    def test_the_ticket_that_asked_still_says_what_it_asked(self):
        self.assertIn("Asked Does the alpha note stay one word?", self.body(1))

    def test_the_same_result_carried_again_opens_nothing_twice(self):
        reports = decisions.open_requested(self.project, 1, 1, [REQUEST], notify=self.notify)
        self.assertEqual(reports, [{"ticket": 6, "opened": False, "paused": [4]}])
        self.assertEqual(len(self.events("decision_opened")), 1)
        self.assertEqual(len(self.notified), 1)
        self.assertEqual(self.ticket(4)["blocked_by"], [1, 6])

    def test_answering_it_releases_the_ticket_it_paused(self):
        project.answer(self.project, 6, "one word")
        launched, _ = self.conduct()
        self.assertEqual(launched, [[4]])
        self.assertEqual((self.ticket(6)["status"], self.ticket(4)["status"]), ("done", "done"))


# --- opening a decision ticket --------------------------------------------------------------------------------


class OpenDecisionTest(BranchCase):
    """`open_decision`, the one way the planner, the conductor, and anything else open a decision ticket."""

    git = False

    def open(self, question="Which split is held out?", **fields):
        return decisions.open_decision(self.project, question, notify=self.notify, **fields)

    def test_it_carries_the_question_pauses_what_it_names_journals_and_notifies(self):
        report = self.open(options=["the last fifth", "a random fifth"], recommended="the last fifth",
                           evidence=["the generator writes the split in order"], pauses=[4], proposed_by="planner", origin="SPEC.md#splits")
        self.assertEqual(report, {"ticket": 6, "opened": True, "paused": [4]})
        self.assertEqual(self.ticket(4)["blocked_by"], [1, 6])
        graph, _ = tickets.refresh_graph(self.project, write=False)
        self.assertNotIn(4, [entry["id"] for entry in tickets.frontier(graph)])
        self.assertEqual([event["event"] for event in self.events()][-2:], ["ticket_created", "decision_opened"])
        self.assertEqual(self.events("decision_opened")[-1]["payload"], {"ticket": 6, "blocking": "subgraph", "human_only": False})
        self.assertEqual([(event, ticket) for event, ticket, _ in self.notified], [("decision_opened", 6)])
        record = decisions.decision_record(self.body(6))
        self.assertEqual((record["options"], record["recommended"], record["evidence"]),
                         (["the last fifth", "a random fifth"], "the last fifth", ["the generator writes the split in order"]))
        self.assertIn("- blocking: `subgraph`, so ticket 4 and whatever waits on it wait for the answer", self.body(6))

    def test_a_running_or_closed_ticket_is_not_paused(self):
        for identifier, status in ((1, "done"), (4, "running")):
            path = self.ticket_path(identifier)
            fields, body = tickets.read_ticket(path)
            tickets.write_ticket(self.ledger, dict(fields, status=status), body)
        report = self.open(pauses=[1, 4])
        self.assertEqual(report["paused"], [])
        self.assertEqual((self.ticket(1)["blocked_by"], self.ticket(4)["blocked_by"]), ([], [1]))

    def test_blocking_all_pauses_every_other_ticket(self):
        self.open(blocking="all", human_only=True)
        graph, _ = tickets.refresh_graph(self.project, write=False)
        self.assertEqual([entry["id"] for entry in tickets.frontier(graph)], [2, 6])
        self.assertIn("(human only) asks: Which split is held out? It pauses every other ticket.", self.notified[0][2])

    def test_what_it_refuses_writes_nothing(self):
        refusals = ((dict(question="  "), "needs a question"), (dict(blocking="some"), "subgraph, all, or null"),
                    (dict(pauses=[99]), "no ticket 99"), (dict(pauses=[3], blocked_by=[5]), "cycle"))
        for fields, message in refusals:
            with self.subTest(fields=fields):
                with self.assertRaises(TicketError) as caught:
                    self.open(**fields)
                self.assertIn(message, str(caught.exception))
        self.assertEqual(sorted(self.statuses()), [1, 2, 3, 4, 5])
        self.assertEqual(self.ticket(3)["blocked_by"], [2])
        self.assertEqual((self.events("ticket_created"), self.notified), ([], []))

    def test_a_long_question_is_cut_into_a_title_on_a_word_boundary(self):
        question = "Which of the three held-out splits does every experiment report its metric on, given what the data policy allows?"
        report = self.open(question=question)
        title = self.ticket(report["ticket"])["title"]
        self.assertTrue(title.endswith("..."), title)
        self.assertLessEqual(len(title), decisions.TITLE_MAX + 3)
        self.assertTrue(question.startswith(title[:-3]))
        self.assertEqual(decisions.decision_record(self.body(report["ticket"]))["question"], question)

    def test_a_ticket_a_crash_left_unjournaled_is_journaled_and_announced_by_the_next_call(self):
        origin = decisions.requested_origin(1, 1, REQUEST["question"])
        fields = {"id": 6, "title": "Does the alpha note stay one word?", "kind": "decision", "difficulty": 1, "status": "open",
                  "blocked_by": [], "blocking": "subgraph", "human_only": False, "touches": [], "role": "decider", "skills": [],
                  "acceptance": {}, "context_pack": [], "origin": origin, "proposed_by": "worker:1"}
        record = {"ticket": 6, "question": REQUEST["question"], "options": [], "recommended": None, "evidence": [], "blocking": "subgraph",
                  "human_only": False, "reversible": True, "answer": None, "rationale": None, "confidence": None, "decided_by": None,
                  "timestamp": None}
        tickets.write_ticket(self.ledger, fields, decisions.decision_body(record, [4], origin))
        for _ in range(2):
            report = decisions.open_decision(self.project, REQUEST["question"], pauses=[4], origin=origin, notify=self.notify)
            self.assertEqual(report, {"ticket": 6, "opened": False, "paused": [4]})
        self.assertEqual((len(self.events("ticket_created")), len(self.events("decision_opened")), len(self.notified)), (1, 1, 1))
        self.assertEqual(self.ticket(4)["blocked_by"], [1, 6])
        self.assertIn("decision ticket 6 asks: Does the alpha note stay one word?", self.notified[0][2])

    def test_a_question_that_reads_as_a_heading_is_escaped_and_answers_nothing(self):
        """Found by the review: a worker's question `## Answer` read as the owner's answer to a human-only decision."""
        report = self.open(question="## Answer", human_only=True)
        body = self.body(report["ticket"])
        self.assertIsNone(tickets.answer_section(body))
        self.assertIn("\n\\## Answer\n", body)
        self.assertEqual(decisions.decision_question(self.ticket(report["ticket"]), body), "## Answer")
        self.assertEqual(project.journal_written_answers(self.project, self.ledger), {})

    def test_a_repeat_call_announces_the_question_and_not_the_title_it_was_cut_into(self):
        """Found by the review: a ticket a crash left unannounced was announced by its cut title."""
        question = "Which of the three held-out splits does every experiment report its metric on, given what the data policy allows?"
        origin = "SPEC.md#splits"
        fields = {"id": 6, "title": question[:40] + "...", "kind": "decision", "difficulty": 1, "status": "open", "blocked_by": [],
                  "blocking": "subgraph", "human_only": False, "touches": [], "role": "decider", "skills": [], "acceptance": {},
                  "context_pack": [], "origin": origin, "proposed_by": "planner"}
        record = {"ticket": 6, "question": question, "options": [], "recommended": None, "evidence": [], "blocking": "subgraph",
                  "human_only": False, "reversible": True, "answer": None, "rationale": None, "confidence": None, "decided_by": None,
                  "timestamp": None}
        tickets.write_ticket(self.ledger, fields, decisions.decision_body(record, [], origin))
        self.assertFalse(decisions.open_decision(self.project, question, origin=origin, notify=self.notify)["opened"])
        self.assertIn("asks: %s No ticket waits on it yet." % question, self.notified[0][2])


class DecisionRecordTest(unittest.TestCase):
    """How a decision ticket's body is read back, with and without its machine copy."""

    def test_the_fixture_s_decision_ticket_reads_back(self):
        _, body = tickets.read_ticket(BRANCH / "research" / "tickets" / DECISION_FILE)
        record = decisions.decision_record(body)
        self.assertEqual((record["ticket"], record["options"], record["recommended"], record["blocking"]),
                         (2, ["one line", "a table"], "one line", "subgraph"))
        self.assertEqual(len(record["evidence"]), 2)

    def test_a_body_without_a_record_falls_back_to_its_decision_section_then_to_the_title(self):
        body = "\n## Decision\n\nPromote `alpha` to level 2 (a full read)?\n\nTrigger: a consultant question.\n"
        self.assertIsNone(decisions.decision_record(body))
        self.assertEqual(decisions.decision_question({"title": "T"}, body), "Promote `alpha` to level 2 (a full read)?")
        self.assertEqual(decisions.decision_question({"title": "Sign in again"}, "\n## Demo\n\nnothing\n"), "Sign in again")

    def test_a_record_that_is_not_a_valid_decision_is_reported_and_the_question_still_read(self):
        body = "\n## Decision\n\nWhich form?\n\n<!-- wayline:decision {\"ticket\": 2} -->\n"
        with self.assertRaises(ProjectError):
            decisions.decision_record(body)
        self.assertEqual(decisions.decision_question({"title": "T"}, body), "Which form?")

    def test_the_fixture_is_what_its_make_script_writes(self):
        spec = importlib.util.spec_from_file_location("decision_branch_make", BRANCH / "make.py")
        made = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(made)
        for fields, body in made.TICKETS:
            with self.subTest(ticket=fields["id"]):
                path = BRANCH / "research" / "tickets" / tickets.filename(fields)
                self.assertEqual(path.read_text(encoding="utf-8"), dump_document(fields, body),
                                 "run python3 fixtures/projects/decision-branch/make.py")
        self.assertEqual((BRANCH / "fake-worker.json").read_text(encoding="utf-8"), json.dumps(made.fake_worker(), indent=2) + "\n")


# --- the view -----------------------------------------------------------------------------------------------


class DecisionsViewTest(BranchCase):
    """Criterion 3's view: the open decision tickets with their options and evidence, the log, and the controls' settings."""

    git = False

    def test_an_open_decision_ticket_with_its_question_options_evidence_and_what_it_pauses(self):
        view = decisions.decisions_view(self.project)
        self.assertEqual([entry["id"] for entry in view["open"]], [2])
        entry = view["open"][0]
        self.assertEqual({key: entry[key] for key in ("question", "options", "recommended", "blocking", "human_only", "pauses", "awaits",
                                                      "answered", "written", "proposed_by")},
                         {"question": "Which form does the beta report take?", "options": ["one line", "a table"], "recommended": "one line",
                          "blocking": "subgraph", "human_only": False, "pauses": [3, 5], "awaits": "owner", "answered": None,
                          "written": None, "proposed_by": "planner"})
        self.assertEqual(len(entry["evidence"]), 2)
        self.assertEqual(view["log"], [])
        self.assertEqual(view["controls"], {"autonomy": "checkpoints", "autonomy_levels": ["interactive", "checkpoints", "autonomous"],
                                            "stop_at": 0.9, "cheap_at": 0.8, "model_fallback": "ask", "model_fallback_stated": False,
                                            "model_fallback_levels": ["auto", "ask", "wait"], "paused_by_owner": False, "active": True})
        self.assertEqual(view["problems"], [])

    def test_under_autonomous_the_decider_takes_it_and_a_human_only_one_stays_the_owner_s(self):
        project.set_autonomy(self.project, "autonomous")
        decisions.open_decision(self.project, "May the data leave the machine?", human_only=True, notify=self.notify)
        with mock.patch.object(decisions, "decider_ready", return_value=True):
            view = decisions.decisions_view(self.project)
            self.assertEqual({entry["id"]: entry["awaits"] for entry in view["open"]}, {2: "decider", 6: "owner"})
            self.assertEqual({entry["id"]: entry["awaits"] for entry in project.status_view(self.project, refresh=False)["decisions"]},
                             {2: "decider", 6: "owner"}, "the overview says who answers each as the decisions view does")
        with mock.patch.object(decisions, "decider_ready", return_value=False):
            self.assertEqual({entry["id"]: entry["awaits"] for entry in decisions.decisions_view(self.project)["open"]},
                             {2: "owner", 6: "owner"}, "with no decider role to launch, the owner answers every decision ticket")

    def test_the_overview_says_the_owner_answers_every_decision_ticket_under_checkpoints(self):
        """Found live: the overview's table said "the decider" for a ticket the decisions view said the owner answers."""
        self.assertEqual([(entry["id"], entry["awaits"]) for entry in project.status_view(self.project, refresh=False)["decisions"]],
                         [(2, "owner")])

    def test_an_answer_not_yet_closed_and_one_written_in_the_file_are_both_shown(self):
        project.answer(self.project, 2, "one line")
        decisions.open_decision(self.project, "May the data leave the machine?", notify=self.notify)
        self.write_answer(6, "no")
        entries = {entry["id"]: entry for entry in decisions.decisions_view(self.project)["open"]}
        self.assertEqual(entries[2]["answered"], {"answer": "one line", "decided_by": "human"})
        self.assertEqual((entries[6]["answered"], entries[6]["written"]), (None, "no"))

    def test_the_log_puts_the_decider_s_decisions_first_and_marks_what_was_superseded(self):
        grill.ask(self.project, "Which metric does the goal use?", options=["auroc", "accuracy"], recommended="auroc")
        grill.answer(self.project, "Q1", "auroc", "the goal names it")
        project.answer(self.project, 2, "one line")
        decisions.open_decision(self.project, "Which seed range?", notify=self.notify)
        self.ledger.append_event("decision", {"ticket": 6, "answer": "0 to 4", "decided_by": "decider", "rationale": "five seeds",
                                              "confidence": 0.7}, ticket=6)
        self.ledger.append_event("ticket_rerun", {"ticket": 2, "by": "cli"}, ticket=2)
        self.ledger.append_event("decision", {"ticket": 2, "answer": "a table", "decided_by": "human", "rationale": None,
                                              "confidence": None}, ticket=2)
        log = decisions.decisions_view(self.project)["log"]
        self.assertEqual([(entry["decided_by"], entry["ticket"], entry["id"], entry["answer"], entry["superseded"]) for entry in log],
                         [("decider", 6, None, "0 to 4", False),
                          ("human", None, "Q1", "auroc", False),
                          ("human", 2, None, "one line", True),
                          ("human", 2, None, "a table", False)])
        self.assertEqual((log[0]["question"], log[1]["question"], log[2]["question"]),
                         ("Which seed range?", "Which metric does the goal use?", "Which form does the beta report take?"))

    def test_a_broken_record_is_a_problem_and_the_rest_of_the_view_is_still_served(self):
        path = self.ticket_path(2)
        text = path.read_text(encoding="utf-8")
        start = text.index("<!-- wayline:decision ")
        end = text.index("-->", start) + 3
        path.write_text(text[:start] + '<!-- wayline:decision {"ticket": 2} -->' + text[end:], encoding="utf-8")
        view = decisions.decisions_view(self.project)
        self.assertEqual(len(view["problems"]), 1)
        self.assertIn("ticket 2:", view["problems"][0])
        self.assertEqual((view["open"][0]["question"], view["open"][0]["options"]), ("Which form does the beta report take?", []))

    def test_while_a_conductor_runs_its_autonomy_decides_who_answers_not_a_hand_edit_of_harness_json(self):
        """Found by the review: the view named the decider for a ticket the running conductor leaves to the owner."""
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": os.getpid()})
        path = self.project / "harness.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"checkpoints"', '"autonomous"'), encoding="utf-8")
        with mock.patch.object(decisions, "decider_ready", return_value=True):
            heartbeat = self.ledger.heartbeat().acquire()
            try:
                self.assertEqual(decisions.decisions_view(self.project)["open"][0]["awaits"], "owner")
            finally:
                heartbeat.release()
            self.assertEqual(decisions.decisions_view(self.project)["open"][0]["awaits"], "decider")


# --- the answer, the pacing thresholds, and the ticket controls --------------------------------------------------


class AnswerTest(BranchCase):
    """`project.answer`: what every answer path but the file calls."""

    git = False

    def test_the_owner_s_reasons_and_certainty_are_journaled_and_the_file_keeps_the_answer_alone(self):
        event = project.answer(self.project, 2, "one line", rationale="  a glance  ", confidence=0.8)
        self.assertEqual(event["payload"], {"ticket": 2, "answer": "one line", "decided_by": "human", "rationale": "a glance", "confidence": 0.8})
        self.assertEqual(tickets.answer_section(self.body(2)), "one line")

    def test_a_confidence_outside_zero_to_one_and_an_id_that_is_not_a_number_are_refused(self):
        for identifier, confidence in ((2, 1.5), (2, True), ("2", None), (True, None)):
            with self.subTest(identifier=identifier, confidence=confidence):
                with self.assertRaises(ProjectError):
                    project.answer(self.project, identifier, "one line", confidence=confidence)
        self.assertEqual(self.events("decision"), [])

    def test_two_answers_given_at_once_are_never_both_taken(self):
        barrier, outcomes = threading.Barrier(2), []

        def give(text):
            barrier.wait()
            try:
                project.answer(self.project, 2, text)
                outcomes.append("taken")
            except ProjectError:
                outcomes.append("refused")

        threads = [threading.Thread(target=give, args=(text,)) for text in ("one line", "a table")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(sorted(outcomes), ["refused", "taken"])
        self.assertEqual(len(self.events("decision")), 1)

    def test_the_verb_takes_a_rationale_and_a_confidence(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["answer", "2", "one line", "--rationale", "a glance", "--confidence", "0.6", "--project", str(self.project)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual({key: self.events("decision")[0]["payload"][key] for key in ("rationale", "confidence")},
                         {"rationale": "a glance", "confidence": 0.6})

    def test_an_answer_being_given_is_not_journaled_a_second_time_from_the_file(self):
        """Found by the review: a wave that read the file between `answer`'s two writes journaled a second decision."""
        readers = []
        written = project.write_ticket

        def write_then_read(ledger, fields, body=""):
            path = written(ledger, fields, body)
            reader = threading.Thread(target=project.journal_written_answers, args=(self.project, Ledger(self.project)))
            reader.start()
            readers.append(reader)
            reader.join(0.3)
            return path

        with mock.patch.object(project, "write_ticket", write_then_read):
            project.answer(self.project, 2, "one line", rationale="a glance")
        for reader in readers:
            reader.join(30)
        self.assertEqual(len(readers), 1)
        self.assertEqual([event["payload"]["rationale"] for event in self.events("decision")], ["a glance"])


class PacingTest(BranchCase):
    """`project.set_pacing`, which `wayline switch --stop-at/--cheap-at` and the dashboard's pacing action call."""

    git = False

    def harness(self):
        return project.read_harness(self.project)

    def test_the_thresholds_are_written_to_harness_json_then_journaled_as_control_pacing(self):
        report = project.set_pacing(self.project, stop_at=0.95, cheap_at=0.85, by="dashboard")
        self.assertEqual((report["from"], report["to"], report["changed"], report["conductor"]),
                         ({"stop_at": 0.9, "cheap_at": 0.8}, {"stop_at": 0.95, "cheap_at": 0.85}, True, None))
        self.assertEqual(self.harness()["pacing"], {"stop_at": 0.95, "cheap_at": 0.85})
        self.assertEqual(self.events("control")[-1]["payload"],
                         {"command": "pacing", "args": {"stop_at": 0.95, "cheap_at": 0.85}, "by": "dashboard"})
        self.assertEqual(decisions.decisions_view(self.project)["controls"]["stop_at"], 0.95)

    def test_one_threshold_alone_keeps_the_other(self):
        self.assertEqual(project.set_pacing(self.project, stop_at=0.95)["to"], {"stop_at": 0.95, "cheap_at": 0.8})

    def test_the_thresholds_the_project_holds_already_change_nothing(self):
        self.assertFalse(project.set_pacing(self.project, stop_at=0.9, cheap_at=0.8)["changed"])
        self.assertEqual(self.events("control"), [])

    def test_what_it_refuses_writes_nothing(self):
        for fields, message in ((dict(cheap_at=0.95), "above stop_at"), (dict(stop_at=1.5), "fraction"), (dict(stop_at=True), "fraction"),
                                (dict(), "give stop_at")):
            with self.subTest(fields=fields):
                with self.assertRaises(ProjectError) as caught:
                    project.set_pacing(self.project, **fields)
                self.assertIn(message, str(caught.exception))
        self.assertEqual((self.harness()["pacing"], self.events("control")), ({"stop_at": 0.9, "cheap_at": 0.8}, []))

    def test_the_switch_verb_sets_them_and_refuses_them_beside_a_project_to_switch_to(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["switch", "--stop-at", "0.95", "--project", str(self.project)])
            refused = cli.main(["switch", str(self.project), "--cheap-at", "0.5"])
        self.assertEqual((code, refused), (0, 2), err.getvalue())
        self.assertIn("pacing thresholds from stop_at 0.9, cheap_at 0.8 to stop_at 0.95, cheap_at 0.8", out.getvalue())
        self.assertIn("give --stop-at and --cheap-at on their own", err.getvalue())

    def test_the_policy_s_thresholds_are_the_layer_under_harness_json(self):
        """Found by the review: with the thresholds only in the policy, a real change was reported as none and nothing written."""
        path = self.project / "harness.json"
        harness = json.loads(path.read_text(encoding="utf-8"))
        harness.pop("pacing")
        harness["policy"] = {"pacing": {"stop_at": 0.8, "cheap_at": 0.7}}
        path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(decisions.decisions_view(self.project)["controls"]["stop_at"], 0.8)
        report = project.set_pacing(self.project, stop_at=0.9)
        self.assertEqual((report["from"], report["to"], report["changed"]),
                         ({"stop_at": 0.8, "cheap_at": 0.7}, {"stop_at": 0.9, "cheap_at": 0.7}, True))
        self.assertEqual(self.harness()["pacing"], {"stop_at": 0.9, "cheap_at": 0.7})


class SteerTicketTest(BranchCase):
    """`project.steer_ticket`, which `wayline cancel`, `wayline rerun`, and their dashboard actions call."""

    git = False

    def test_cancel_and_rerun_journal_the_control_for_a_ticket_the_project_has(self):
        for command in ("cancel", "rerun"):
            event = project.steer_ticket(self.project, command, 3, by="dashboard")
            self.assertEqual((event["payload"], event["ticket"]), ({"command": command, "args": {"ticket": 3}, "by": "dashboard"}, 3))

    def test_an_unknown_ticket_an_id_that_is_not_a_number_and_another_command_are_refused(self):
        for command, identifier, message in (("cancel", 99, "has no ticket 99"), ("rerun", "3", "whole number"), ("stop", 3, "cancel or rerun")):
            with self.subTest(command=command, identifier=identifier):
                with self.assertRaises(ProjectError) as caught:
                    project.steer_ticket(self.project, command, identifier)
                self.assertIn(message, str(caught.exception))
        self.assertEqual(self.events("control"), [])


# --- who takes a decision ticket, and the notifier the suite keeps quiet --------------------------------------------


class AwaitsOwnerTest(unittest.TestCase):
    """Under `interactive` and `checkpoints` the owner answers every decision ticket; under `autonomous`, only the human-only ones."""

    def graph(self):
        base = {"kind": "decision", "status": "open", "difficulty": 1, "blocked_by": [], "blocking": "subgraph", "touches": [],
                "resources": None, "role": "decider", "skills": [], "attempt": 0}
        return {"snapshot": {}, "tickets": [dict(base, id=1, human_only=True), dict(base, id=2, human_only=False),
                                            dict(base, id=3, kind="code", role="coder", blocking=None, human_only=False)]}

    def test_who_waits_for_the_owner_under_each_autonomy(self):
        entries = self.graph()["tickets"]
        for autonomy, expected in (("interactive", [True, True, False]), ("checkpoints", [True, True, False]),
                                   ("autonomous", [True, False, False]), (None, [True, False, False])):
            with self.subTest(autonomy=autonomy):
                self.assertEqual([schedule.awaits_owner(entry, autonomy) for entry in entries], expected)

    def test_no_decision_ticket_is_picked_under_checkpoints(self):
        self.assertEqual([entry["id"] for entry in schedule.pick(self.graph(), slots=3, autonomy="checkpoints")], [3])
        self.assertEqual(sorted(entry["id"] for entry in schedule.pick(self.graph(), slots=3, autonomy="autonomous")), [2, 3])

    def test_held_back_says_why_each_decision_ticket_waits(self):
        self.assertEqual(schedule.held_back(self.graph(), "checkpoints"), [
            "  decision ticket 1 waits for the owner's answer: it is human-only, and no session answers it",
            "  decision ticket 2 waits for the owner's answer: under autonomy checkpoints the owner answers every decision ticket",
        ])

    def test_without_a_decider_every_decision_ticket_waits_for_the_owner(self):
        entries = self.graph()["tickets"]
        self.assertEqual([schedule.awaits_owner(entry, "autonomous", decider=False) for entry in entries], [True, True, False])
        self.assertEqual([entry["id"] for entry in schedule.pick(self.graph(), slots=3, autonomy="autonomous", decider=False)], [3])
        self.assertEqual(schedule.held_back(self.graph(), "autonomous", decider=False)[1],
                         "  decision ticket 2 waits for the owner's answer: no decider role is installed to answer it (ticket 31)")


class NotifyOffTest(ProjectTestCase):
    """`WAYLINE_NOTIFY=none`, which the suite sets: both `notified` lines are journaled and no channel runs."""

    def test_no_channel_runs_and_the_claim_and_the_outcome_are_still_journaled(self):
        target = self.temp / "study"
        project.init_project(target, git=False, hermes_python="/usr/bin/false", owner_email=None)
        self.assertEqual(os.environ.get(notify.NOTIFY_ENV), "none")
        outcome = notify.notify("decision_opened", "ticket 1 asks", project=target, ticket=1)
        self.assertEqual((outcome["channel"], outcome["ok"], outcome["journaled"]), ("none", False, True))
        events, _ = Ledger(target).read_events()
        self.assertEqual([event["payload"] for event in events if event["event"] == "notified"],
                         [{"event": "decision_opened", "channel": None, "ok": None, "exit_code": None},
                          {"event": "decision_opened", "channel": "none", "ok": False, "exit_code": None}])

    def test_a_channel_a_test_passes_in_still_runs(self):
        ran = []
        outcome = notify.notify("paused", "text", run=lambda argv, timeout: ran.append(argv) or subprocess.CompletedProcess(argv, 0))
        self.assertEqual((len(ran), outcome["channel"], outcome["ok"]), (1, "notify-send", True))
