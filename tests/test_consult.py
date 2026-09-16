"""The consultant (Implementation Decisions 9; map ticket 41): one question about one dossier.

Every consultant session runs over the fake launcher. A project starts from `write_l0` and an L1
skim written by hand, the way `wayline absorb --level 1` would leave it, so a question can be
answered, logged, journaled, counted against its ticket, and turned into a promotion.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from wayline import cli, consult, worker
from wayline.dossier import CONSULTANT_QUESTION, LEVEL_1, LEVEL_2, PLANNER_OR_DECIDER, l0_dossier, promote, read_dossier, write_l0
from wayline.fetch import recording_fetcher
from wayline.ledger import Ledger
from wayline.scout import Scout, parse_reference
from wayline.tickets import read_tickets
from wayline.worker import Envelope

RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"
SLUG = "vaswani-2017-attention"
QUESTION = "How many warmup steps does the learning-rate schedule use?"
READ_ONLY_REMOVALS = ("Edit", "Write", "NotebookEdit", "Bash", "Agent", "WebFetch", "WebSearch")


def answer(**fields):
    value = {"answer": "4000 warmup steps.", "locators": ["source/flat.tex:412"], "confidence": 0.9,
             "not_in_source": False, "promote_requested": False}
    value.update(fields)
    return value


class ConsultTestCase(unittest.TestCase):
    """A bare project with L1 dossiers, and the fake launcher selected."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-consult-test-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.project = (self.temp / "project").resolve()
        (self.project / "research").mkdir(parents=True)
        self.ledger = Ledger(self.project)
        self.scout = Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)
        self.seed("arXiv:1706.03762", SLUG)
        self.fake = self.enterContext(worker.use_fake())

    def seed(self, text, slug, level=LEVEL_1):
        dossier = l0_dossier(self.scout.resolve(parse_reference(text)), slug)
        if level >= LEVEL_1:
            dossier.update(level=LEVEL_1, relation_to_intent="The architecture the intent builds on.",
                           deserves_l2_if="The project needs the training recipe.")
        write_l0(self.ledger, dossier)
        return dossier

    def ask(self, question=QUESTION, slug=SLUG, ticket=None, **fields):
        self.fake.script(Envelope(session_id="consult-session", structured_output=answer(**fields)), role="consultant")
        return consult.ask(self.project, slug, question, ticket=ticket)

    def consulted(self):
        events, _ = self.ledger.read_events()
        return [event for event in events if event["event"] == "consulted"]

    def qa_lines(self, slug=SLUG):
        path = self.project / "research" / "refs" / slug / "qa_log.md"
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


class RequestTest(ConsultTestCase):
    def test_the_session_is_launched_as_decision_9_gives_it(self):
        self.ask()
        request = self.fake.calls[0].request
        self.assertEqual(request.role, "consultant")
        self.assertTrue(request.prompt.startswith(QUESTION + "\n"))
        self.assertEqual([Path(path) for path in request.add_dirs], [self.project / "research" / "refs" / SLUG])
        self.assertEqual(Path(request.cwd), self.project)
        self.assertEqual((request.model, request.effort), ("sonnet", "medium"))
        self.assertEqual(request.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in READ_ONLY_REMOVALS:
            self.assertIn(tool, request.disallowed_tools)
        self.assertEqual(Path(request.schema_path), HARNESS_ROOT / "schemas" / "consultant_answer.json")
        self.assertEqual(request.agent_json["consultant"]["permissionMode"], "dontAsk")

    def test_the_launch_line_carries_the_read_only_flags(self):
        self.ask()
        call = self.fake.calls[0]
        argv = worker.build_argv(call.request, call.run_dir)
        self.assertEqual(argv[argv.index("--agent") + 1], "consultant")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertEqual(argv[argv.index("--add-dir") + 1], str(self.project / "research" / "refs" / SLUG))
        self.assertIn("--json-schema", argv)
        removed = argv[argv.index("--disallowedTools") + 1:]
        for tool in READ_ONLY_REMOVALS:
            self.assertIn(tool, removed)

    def test_a_consult_from_inside_a_worker_does_not_inherit_its_acceptance_contract(self):
        with mock.patch.dict(os.environ, {"TICKET_ACCEPTANCE_FILE": "/tmp/acceptance.json", "TICKET_TOUCHES": "src/"}):
            self.ask(ticket=7)
        env = self.fake.calls[0].request.env
        self.assertEqual(env["TICKET_ACCEPTANCE_FILE"], "")
        self.assertEqual(env["TICKET_TOUCHES"], "")
        self.assertEqual(env["WAYLINE_PROJECT"], str(self.project))
        self.assertTrue(Path(env["WAYLINE_RUN"]).is_relative_to(self.project / "research" / "sessions" / "consult" / SLUG))

    def test_two_consults_get_two_session_directories(self):
        self.ask()
        self.ask()
        self.assertNotEqual(self.fake.calls[0].run_dir, self.fake.calls[1].run_dir)

    def test_the_policy_tier_is_the_consultant_s(self):
        (self.project / "harness.json").write_text(json.dumps({"policy": {"roles": {"consultant": {"model": "opus", "effort": "high"}}}}), encoding="utf-8")
        self.ask()
        request = self.fake.calls[0].request
        self.assertEqual((request.model, request.effort), ("opus", "high"))

    def test_a_slug_without_a_dossier_is_refused_before_a_launch(self):
        with self.assertRaises(consult.ConsultError):
            consult.ask(self.project, "no-such-paper", QUESTION)
        self.assertEqual(self.fake.calls, [])

    def test_an_empty_question_is_refused(self):
        with self.assertRaises(consult.ConsultError):
            consult.ask(self.project, SLUG, "   ")
        self.assertEqual(self.fake.calls, [])


class ExchangeTest(ConsultTestCase):
    def test_an_answer_is_returned_logged_and_journaled(self):
        report = self.ask(ticket=7)
        self.assertEqual(report["answer"], answer())
        self.assertEqual(report["session_id"], "consult-session")
        lines = self.qa_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn(QUESTION, lines[0])
        self.assertIn("4000 warmup steps.", lines[0])
        self.assertIn("source/flat.tex:412", lines[0])
        self.assertIn("worker:7", lines[0])
        consulted = self.consulted()
        self.assertEqual(len(consulted), 1)
        self.assertEqual(consulted[0]["ticket"], 7)
        self.assertEqual(consulted[0]["session_id"], "consult-session")
        self.assertEqual(consulted[0]["payload"], {
            "slug": SLUG, "by": "worker:7", "question_sha256": hashlib.sha256(QUESTION.encode("utf-8")).hexdigest(),
            "promote_requested": False, "session_id": "consult-session",
        })

    def test_every_exchange_is_appended_one_line_each_even_across_line_breaks(self):
        self.ask(question="First question?\nWith a second line.")
        self.ask(answer="An answer\n\nin two paragraphs.")
        lines = self.qa_lines()
        self.assertEqual(len(lines), 2)
        self.assertIn("First question? With a second line.", lines[0])
        self.assertIn("An answer in two paragraphs.", lines[1])
        text = (self.project / "research" / "refs" / SLUG / "qa_log.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("# Questions asked about"), 1)

    def test_a_question_asked_outside_a_ticket_is_by_the_command_line(self):
        self.ask()
        self.assertEqual(self.consulted()[0]["payload"]["by"], "cli")
        self.assertIsNone(self.consulted()[0]["ticket"])

    def test_not_in_source_is_logged_as_such(self):
        self.ask(answer="The files do not say.", locators=[], not_in_source=True, confidence=0.7)
        self.assertIn("not in source", self.qa_lines()[0])

    def test_an_answer_read_in_the_source_without_a_locator_is_refused_and_not_recorded(self):
        with self.assertRaises(consult.ConsultError) as raised:
            self.ask(locators=[])
        self.assertIn("locator", str(raised.exception))
        self.assertEqual(self.consulted(), [])
        self.assertFalse((self.project / "research" / "refs" / SLUG / "qa_log.md").exists())

    def test_a_session_without_a_valid_answer_is_an_error_and_not_recorded(self):
        self.fake.script(Envelope(session_id="s", errors=["no structured output"]), role="consultant")
        with self.assertRaises(consult.ConsultError):
            consult.ask(self.project, SLUG, QUESTION, ticket=7)
        self.assertEqual(self.consulted(), [])

    def test_check_answer_uses_the_schema(self):
        self.assertEqual(consult.check_answer(answer()), [])
        self.assertTrue(consult.check_answer(answer(confidence=2)))
        self.assertTrue(consult.check_answer({"answer": "x"}))
        self.assertTrue(consult.check_answer("not an object"))


class PromotionTest(ConsultTestCase):
    def test_a_requested_promotion_inside_the_budget_promotes(self):
        report = self.ask(ticket=7, answer="The skim does not say.", locators=[], not_in_source=True, promote_requested=True)
        self.assertTrue(report["promotion"]["promoted"])
        self.assertEqual(read_dossier(self.ledger, SLUG)["level"], LEVEL_2)
        events, _ = self.ledger.read_events()
        promoted = [event for event in events if event["event"] == "promoted"]
        self.assertEqual(promoted[0]["payload"]["trigger"], CONSULTANT_QUESTION)
        self.assertEqual(promoted[0]["ticket"], 7)
        self.assertTrue(self.consulted()[0]["payload"]["promote_requested"])

    def test_a_requested_promotion_beyond_the_budget_opens_a_decision_ticket(self):
        for text, slug in (("10.1038/s41586-020-2649-2", "a"), ("10.1101/2020.03.22.002386", "b"), ("arXiv:1912.01703", "c")):
            self.seed(text, slug)
            promote(self.ledger, slug, PLANNER_OR_DECIDER, phase="P1")
        report = self.ask(ticket=7, answer="The skim does not say.", locators=[], not_in_source=True, promote_requested=True)
        self.assertFalse(report["promotion"]["promoted"])
        fields = next(t for t in read_tickets(self.project) if t["id"] == report["promotion"]["decision_ticket"])
        self.assertEqual(fields["kind"], "decision")
        self.assertEqual(fields["proposed_by"], "worker:7")
        self.assertIn("consultant question", fields["origin"])
        self.assertEqual(read_dossier(self.ledger, SLUG)["level"], LEVEL_1)

    def test_no_promotion_unless_requested(self):
        report = self.ask()
        self.assertIsNone(report["promotion"])
        self.assertEqual(read_dossier(self.ledger, SLUG)["level"], LEVEL_1)


class LimitTest(ConsultTestCase):
    def test_the_sixth_question_of_a_ticket_is_refused_before_a_launch(self):
        for _ in range(5):
            self.ask(ticket=7)
        self.assertEqual(consult.questions_asked(self.ledger, 7), 5)
        with self.assertRaises(consult.ConsultRefused) as raised:
            consult.ask(self.project, SLUG, QUESTION, ticket=7)
        self.assertIn("5", str(raised.exception))
        self.assertEqual(len(self.fake.calls), 5)
        self.assertEqual(len(self.consulted()), 5)

    def test_questions_are_counted_per_ticket(self):
        for _ in range(5):
            self.ask(ticket=7)
        self.ask(ticket=8)
        self.ask()
        self.assertEqual(consult.questions_asked(self.ledger, 8), 1)

    def test_the_limit_is_the_policy_s(self):
        (self.project / "harness.json").write_text(json.dumps({"policy": {"consultant": {"max_questions_per_ticket": 1}}}), encoding="utf-8")
        self.ask(ticket=7)
        with self.assertRaises(consult.ConsultRefused):
            consult.ask(self.project, SLUG, QUESTION, ticket=7)


class CommandTest(ConsultTestCase):
    def setUp(self):
        super().setUp()
        (self.project / "harness.json").write_text("{}\n", encoding="utf-8")  # what makes a directory a project

    def run_verb(self, *args, ticket="7"):
        env = {"WAYLINE_PROJECT": str(self.project), "WAYLINE_TICKET": ticket}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["consult", *args])
        return code, out.getvalue(), err.getvalue()

    def script(self, **fields):
        self.fake.script(Envelope(session_id="consult-session", structured_output=answer(**fields)), role="consultant")

    def test_the_verb_is_built(self):
        self.assertIsNotNone(cli.lookup("consult").handler)

    def test_the_verb_answers_and_reads_the_ticket_and_project_from_the_environment(self):
        self.script()
        code, out, err = self.run_verb(SLUG, QUESTION)
        self.assertEqual(code, 0, err)
        self.assertIn("4000 warmup steps.", out)
        self.assertIn("source/flat.tex:412", out)
        self.assertEqual(self.consulted()[0]["ticket"], 7)

    def test_json_prints_the_answer_object(self):
        self.script()
        code, out, _ = self.run_verb(SLUG, QUESTION, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), answer())

    def test_the_sixth_question_exits_1_and_says_why(self):
        for _ in range(5):
            self.script()
            self.assertEqual(self.run_verb(SLUG, QUESTION)[0], 0)
        code, out, err = self.run_verb(SLUG, QUESTION)
        self.assertEqual(code, 1)
        self.assertIn("max_questions_per_ticket", err)
        self.assertEqual(len(self.fake.calls), 5)

    def test_an_unknown_slug_exits_1(self):
        code, _, err = self.run_verb("no-such-paper", QUESTION)
        self.assertEqual(code, 1)
        self.assertIn("no-such-paper", err)

    def test_a_non_numeric_ticket_is_refused(self):
        code, _, err = self.run_verb(SLUG, QUESTION, ticket="seven")
        self.assertEqual(code, 2)
        self.assertIn("WAYLINE_TICKET", err)


class RolesTest(unittest.TestCase):
    def test_the_consultant_is_read_only(self):
        role = worker.read_role("consultant", HARNESS_ROOT)
        self.assertEqual(role.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in READ_ONLY_REMOVALS:
            self.assertIn(tool, role.disallowed_tools)
        self.assertEqual(role.output_schema, "consultant_answer")
        self.assertFalse(role.may_judge)

    def test_the_workers_that_may_consult_have_the_verb_on_their_allowed_tools(self):
        for name in ("coder", "experimenter", "analyst"):
            with self.subTest(role=name):
                self.assertIn("Bash(wayline consult *)", worker.read_role(name, HARNESS_ROOT).allowed_tools)


if __name__ == "__main__":
    unittest.main()
