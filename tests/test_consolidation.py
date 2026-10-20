"""A consolidation: one read-only writer session the owner asks for (decision 17; ticket 88).

The seams are `wayline consolidate <section>` and `consolidation.consolidate` over a temporary project, with the fake
launcher standing in for the writer's session. What is asserted is what the owner is shown before it runs, what the
session was launched with, and what lands in `research/passages.jsonl`, the journal, and the rendered section.
"""

import io
import json
import os
import re
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.projects import ProjectTestCase
from wayline import consolidation, sections, worker
from wayline import project as projects
from wayline.ledger import Ledger
from wayline.worker import Envelope

FIT = "We fit the phase by least squares {code:code/phase.py#fit}."
ONCE = "The fit runs once per cell {code:code/phase.py#L1-L2}."
FILM = "The cells are filmed at 10 Hz {res:t2-a1/results/film.json#rate}."
MERGED = "We fit the phase by least squares once per cell {code:code/phase.py#fit}{code:code/phase.py#L1-L2}."


def answer(*passages):
    return Envelope(structured_output={"passages": [dict(zip(("heading", "text", "replaces"), passage)) for passage in passages]})


class ConsolidationCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "paper-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)
        (self.project / "code").mkdir()
        (self.project / "code" / "phase.py").write_text("def fit(signal):\n    return signal\n", encoding="utf-8")
        sections.add_passage(self.ledger, "methods", "Fitting", FIT, by="t1-a1")
        sections.add_passage(self.ledger, "methods", "Fitting", ONCE, by="owner")
        sections.add_passage(self.ledger, "methods", "Data", FILM, by="t2-a1")
        patcher = mock.patch.dict(os.environ)  # the owner's own shell, outside any run
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("WAYLINE_RUN", "WAYLINE_TICKET"):
            os.environ.pop(name, None)

    def methods(self):
        return (self.project / "research" / "sections" / "methods.md").read_text(encoding="utf-8")

    def events(self, name):
        return [event for event in self.ledger.read_events()[0] if event["event"] == name]

    def run_verb(self, *args, script=(), classifier=False):
        out, err = io.StringIO(), io.StringIO()
        with worker.use_fake() as fake:
            for envelope in script:
                fake.script(envelope, role="writer")
            if classifier:  # every sentence it is sent is a claim
                for _ in range(len(script)):
                    fake.script(respond=lambda request, message: Envelope(structured_output={"classes": [
                        {"n": int(number), "class": "claim"} for number in re.findall(r"^\[(\d+)\] ", request.prompt, re.M)]}),
                        role="classifier")
            with redirect_stdout(out), redirect_stderr(err):
                code = consolidation.consolidate_command([*args, "--project", str(self.project)])
            self.calls = list(fake.calls)
        return code, out.getvalue(), err.getvalue()


class ConfirmFirstTest(ConsolidationCase):
    def test_without_the_owners_yes_it_shows_the_cost_and_launches_nothing(self):
        code, out, _ = self.run_verb("methods")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("3 current passages", out)
        self.assertRegex(out, r"about [0-9,]+ tokens")
        self.assertIn("--yes", out)
        self.assertEqual(len(sections.read_passages(self.ledger)), 3)

    def test_the_estimate_names_the_writers_model(self):
        estimate = consolidation.estimate(self.project, "methods")
        self.assertEqual(estimate["passages"], 3)
        self.assertTrue(estimate["model"])
        self.assertGreater(estimate["tokens"], 0)


class ConsolidateTest(ConsolidationCase):
    def setUp(self):
        super().setUp()
        self.code, self.out, self.err = self.run_verb("methods", "--yes", script=[
            answer(("Fitting", MERGED, ["P1", "P2"]), ("Data", FILM.replace("10 Hz", "ten hertz"), ["P3"]))])

    def test_it_runs_one_read_only_writer_session(self):
        self.assertEqual(self.code, 0, self.err)
        [call] = self.calls
        self.assertEqual(call.request.role, "writer")
        for tool in ("Edit", "Write", "Bash"):
            self.assertIn(tool, call.request.disallowed_tools)
        self.assertIn("P1", call.request.prompt)
        self.assertIn(FIT, call.request.prompt)

    def test_the_fewer_passages_replace_the_current_ones_by_consolidation(self):
        written = [item for item in sections.read_passages(self.ledger) if item["by"] == "consolidation"]
        self.assertEqual([(item["replaces"], bool(item.get("withdrawn"))) for item in written],
                         [("P1", False), ("P2", True), ("P3", False)])
        methods = self.methods()
        self.assertIn("once per cell {code:code/phase.py#fit}", methods)
        self.assertNotIn(FIT, methods)
        self.assertNotIn(ONCE, methods)
        self.assertIn("ten hertz", methods)
        self.assertEqual(sections.current_ids(self.ledger, "methods"), {written[0]["id"], written[2]["id"]})

    def test_it_is_journaled(self):
        [event] = self.events("consolidated")
        self.assertEqual((event["payload"]["section"], event["payload"]["replaced"]), ("methods", ["P1", "P2", "P3"]))
        self.assertEqual(len(event["payload"]["written"]), 2)
        self.assertEqual([item["payload"]["by"] for item in self.events("passage")][-3:], ["consolidation"] * 3)

    def test_the_owners_passage_it_replaced_is_not_changed_without_asking(self):
        self.assertFalse(any(item["payload"].get("replaces_owner") for item in self.events("passage")))


class RefusedTest(ConsolidationCase):
    def assertNothingWritten(self):
        self.assertEqual([item["by"] for item in sections.read_passages(self.ledger)], ["t1-a1", "owner", "t2-a1"])
        self.assertEqual(self.events("consolidated"), [])

    def test_it_refuses_inside_an_automated_run(self):
        with mock.patch.dict(os.environ, {"WAYLINE_RUN": str(self.temp / "session")}):
            code, _, err = self.run_verb("methods", "--yes", script=[answer(("Fitting", MERGED, ["P1", "P2", "P3"]))])
        self.assertEqual(code, 2)
        self.assertIn("automated run", err)
        self.assertEqual(self.calls, [])
        self.assertNothingWritten()

    def test_it_refuses_results(self):
        code, _, err = self.run_verb("results", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("Results", err)

    def test_a_section_with_fewer_than_two_passages_has_nothing_to_consolidate(self):
        code, _, err = self.run_verb("discussion", "--yes")
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, [])

    def test_an_answer_that_drops_a_tag_is_sent_back_once_and_then_refused(self):
        dropped = answer(("Fitting", "We fit the phase by least squares once per cell {code:code/phase.py#fit}.", ["P1", "P2"]),
                         ("Data", FILM, ["P3"]))
        code, _, err = self.run_verb("methods", "--yes", script=[dropped, dropped])
        self.assertEqual(code, 1)
        self.assertEqual([call.kind for call in self.calls], ["launch", "resume"])
        self.assertIn("code:code/phase.py#L1-L2", self.calls[1].message)
        self.assertIn("code:code/phase.py#L1-L2", err)
        self.assertNothingWritten()

    def test_an_answer_that_is_not_fewer_or_misses_a_passage_is_refused(self):
        same = answer(("Fitting", FIT, ["P1"]), ("Fitting", ONCE, ["P2"]), ("Data", FILM, ["P3"]))
        missing = answer(("Fitting", MERGED, ["P1", "P2"]))
        for bad, said in ((same, "fewer"), (missing, "P3")):
            with self.subTest(said=said):
                code, _, err = self.run_verb("methods", "--yes", script=[bad, bad])
                self.assertEqual(code, 1)
                self.assertIn(said, err)
                self.assertNothingWritten()

    def test_a_tag_that_failed_before_the_consolidation_is_carried_not_held_against_it(self):
        merged = answer(("Fitting", MERGED, ["P1", "P2"]), ("Data", FILM, ["P3"]))  # FILM's run is in no manifest
        code, _, err = self.run_verb("methods", "--yes", script=[merged])
        self.assertEqual(code, 0, err)

    def test_an_untagged_claim_of_its_own_fails_the_linter(self):
        merged = answer(("Fitting", MERGED, ["P1", "P2"]), ("Data", FILM + " It always converges.", ["P3"]))
        code, _, err = self.run_verb("methods", "--yes", script=[merged, merged], classifier=True)
        self.assertEqual(code, 1)
        self.assertIn("untagged_claim", err)
        self.assertIn("It always converges.", err)
        self.assertNothingWritten()
