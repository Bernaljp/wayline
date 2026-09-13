"""Phase P2's grill and the autonomy switch (ticket 30; Implementation Decisions 10 and 4; BRIEF 6.2).

Each test lays out a project with `init`, drives `wayline grill` and `wayline switch --autonomy` in
process, and reads back what the owner, the decider, and the conductor see: `research/DECISIONS.md`
(through the grill's own reader, every record against the `decision` schema), `research/CONTEXT.md`,
`harness.json`, and the journal.
"""

import io
import json
import shutil
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, patch
from tests.test_intake import structural
from wayline import cli, replay, worker
from wayline.conductor import Conductor
from wayline.grill import GrillError, answer, frontier, read_records, render_decisions, with_answer, with_question
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Heartbeat, Ledger, make_event
from wayline.project import init_project, read_harness, set_autonomy

BASELINE = "Which baseline do the claims compare against?"
SEEDS = "How many seeds does a comparison use?"
TERMS = "Which interaction terms are in scope?"
SPLIT = "Does the held-out split stay split_b?"


def run(*args, stdin=None):
    """`wayline ...` in process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin or "")):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class GrillCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)

    def grill(self, *args, stdin=None):
        return run("grill", *args, "--project", str(self.project), stdin=stdin)

    def ok(self, *args, stdin=None):
        code, out, err = self.grill(*args, stdin=stdin)
        self.assertEqual(code, 0, out + err)
        return out

    def tier(self):
        return json.loads(self.ok("--json"))

    def records(self):
        return {record["id"]: record for record in read_records(self.project)}

    def decisions_md(self):
        return (self.project / "research" / "DECISIONS.md").read_text(encoding="utf-8")

    def context_md(self):
        return (self.project / "research" / "CONTEXT.md").read_text(encoding="utf-8")

    def events(self, name=None):
        events, _ = Ledger(self.project).read_events()
        return [event for event in events if name is None or event["event"] == name]

    def tree(self):
        """The toy intent's first questions: two roots, one that needs both, and a human-only root."""
        self.ok("ask", BASELINE, "--option", "logistic regression on the raw features", "--option", "gradient-boosted trees",
                "--recommend", "logistic regression on the raw features",
                "--evidence", "research/POSITION.md#closest-prior-work: paper-a compares against the linear model")
        self.ok("ask", SEEDS, "--recommend", "three", "--evidence", "policy.json: goal.min_seeds is 3")
        self.ok("ask", TERMS, "--requires", "Q1", "--requires", "Q2", "--recommend", "pairwise terms only")
        self.ok("ask", SPLIT, "--human-only", "--irreversible", "--recommend", "yes")

    def answer(self, identifier, text, *extra):
        return self.ok("answer", identifier, text, "--rationale", "the owner took the recommendation", *extra)


class AskTheTierTest(GrillCase):
    """Criterion 1: the whole frontier per tier, numbered, each with a recommended answer."""

    def test_the_first_tier_is_the_whole_frontier_numbered_with_a_recommendation_each(self):
        self.tree()
        out = self.ok()
        self.assertIn("tier 1", out)
        self.assertRegex(out, r"(?m)^\s+1\. Q1\b")
        self.assertRegex(out, r"(?m)^\s+2\. Q2\b")
        self.assertRegex(out, r"(?m)^\s+3\. Q4\b")
        self.assertNotRegex(out, r"(?m)^\s+\d+\. Q3\b", "Q3 waits on Q1 and Q2")
        self.assertEqual(out.count("recommended:"), 3)
        self.assertIn("human-only", out)
        records = self.records()
        self.assertEqual({key: records[key]["tier"] for key in records}, {"Q1": 1, "Q2": 1, "Q3": None, "Q4": 1})

    def test_asking_again_before_anything_is_answered_is_the_same_tier_and_writes_nothing(self):
        self.tree()
        first = self.ok()
        written = self.decisions_md()
        self.assertEqual(self.ok(), first)
        self.assertEqual(self.decisions_md(), written)

    def test_the_next_tier_asks_what_its_answers_opened_and_what_is_still_open(self):
        self.tree()
        self.ok()
        self.answer("Q1", "logistic regression on the raw features")
        self.answer("Q2", "three")
        view = self.tier()
        self.assertEqual(view["tier"], 2)
        self.assertEqual([record["id"] for record in view["ask"]], ["Q3", "Q4"])
        records = self.records()
        self.assertEqual((records["Q3"]["tier"], records["Q4"]["tier"]), (2, 1), "a question keeps the tier it was first asked in")

    def test_a_question_whose_prerequisite_is_open_cannot_be_answered(self):
        self.tree()
        self.ok()
        code, out, err = self.grill("answer", "Q3", "pairwise terms only", "--rationale", "why not")
        self.assertEqual(code, 2, out + err)
        self.assertIn("Q1", err)
        self.assertIsNone(self.records()["Q3"]["answer"])
        self.assertEqual(self.events("decision"), [])

    def test_the_grill_ends_when_every_question_is_settled(self):
        self.tree()
        self.ok()
        for identifier, text in (("Q1", "logistic regression"), ("Q2", "three"), ("Q4", "yes")):
            self.answer(identifier, text)
        self.ok()
        self.answer("Q3", "pairwise terms only")
        out = self.ok()
        self.assertIn("every question is settled", out)
        view = self.tier()
        self.assertEqual((view["ask"], view["waiting"], view["settled"], view["total"]), ([], [], 4, 4))

    def test_an_empty_tree_says_how_to_start_one(self):
        out = self.ok()
        self.assertIn("wayline grill ask", out)
        self.assertFalse((self.project / "research" / "DECISIONS.md").exists())

    def test_the_tier_names_the_position_memo_it_rests_on_or_its_absence(self):
        self.tree()
        self.assertIn("no position memo", self.ok())
        Ledger(self.project).write_markdown("POSITION.md", "# Position\n")
        self.assertIn("research/POSITION.md", self.ok())


class AnswerTest(GrillCase):
    """Criterion 1 and 3: every answer is a whole decision record in DECISIONS.md, valid, and journaled."""

    def setUp(self):
        super().setUp()
        self.tree()
        self.ok()

    def test_an_answer_lands_in_decisions_md_as_a_whole_record_and_in_the_journal(self):
        self.ok("answer", "Q1", "logistic regression on the raw features",
                "--rationale", "it isolates the one change the intent is about", "--confidence", "0.9")
        record = self.records()["Q1"]
        self.assertEqual(record["answer"], "logistic regression on the raw features")
        self.assertEqual(record["rationale"], "it isolates the one change the intent is about")
        self.assertEqual((record["decided_by"], record["confidence"], record["tier"]), ("human", 0.9, 1))
        [event] = self.events("decision")
        self.assertEqual(event["ts"], record["timestamp"])
        self.assertIsNone(event["ticket"])
        payload = event["payload"]
        self.assertEqual((payload["decided_by"], payload["confidence"], payload["rationale"]),
                         ("human", 0.9, "it isolates the one change the intent is about"))
        self.assertIn("Q1", payload["answer"])
        self.assertIn("logistic regression on the raw features", payload["answer"])
        text = self.decisions_md()
        for line in ("### Q1. " + BASELINE, "- answer: logistic regression on the raw features",
                     "- rationale: it isolates the one change the intent is about", "- decided-by: human",
                     "- confidence: 0.9", "- timestamp: " + record["timestamp"]):
            self.assertIn(line, text)
        self.assertLess(text.index("## Settled"), text.index("### Q1."))
        self.assertLess(text.index("### Q1."), text.index("## Open"))

    def test_every_entry_validates_against_the_decision_schema(self):
        self.answer("Q1", "logistic regression")
        self.answer("Q2", "three", "--confidence", "0.6")
        schema = load_schema("decision")
        records = read_records(self.project)
        self.assertEqual(len(records), 4)
        for record in records:
            with self.subTest(record=record["id"]):
                self.assertEqual(validate(record, schema), [])
                for key in ("question", "options", "answer", "rationale", "confidence", "decided_by", "reversible", "timestamp"):
                    self.assertIn(key, record)
        self.assertEqual(self.records()["Q4"]["reversible"], False)
        self.assertTrue(self.records()["Q4"]["human_only"])

    def test_an_unstated_confidence_is_recorded_as_not_stated(self):
        self.answer("Q2", "three")
        self.assertIsNone(self.records()["Q2"]["confidence"])
        self.assertIn("- confidence: not stated", self.decisions_md())

    def test_an_answer_without_a_rationale_is_refused(self):
        code, _, err = self.grill("answer", "Q1", "logistic regression", "--rationale", "  ")
        self.assertEqual(code, 2)
        self.assertIn("rationale", err)
        code, _, _ = self.grill("answer", "Q1", "logistic regression")
        self.assertEqual(code, 2)
        self.assertIsNone(self.records()["Q1"]["answer"])

    def test_a_confidence_outside_zero_to_one_is_refused(self):
        code, _, err = self.grill("answer", "Q1", "logistic regression", "--rationale", "r", "--confidence", "90")
        self.assertEqual(code, 2)
        self.assertIn("confidence", err)
        self.assertEqual(self.events("decision"), [])

    def test_an_unknown_question_is_refused(self):
        code, _, err = self.grill("answer", "Q9", "yes", "--rationale", "r")
        self.assertEqual(code, 2)
        self.assertIn("Q9", err)

    def test_a_settled_question_changes_only_by_a_revision_that_supersedes_it(self):
        self.answer("Q1", "logistic regression")
        code, _, err = self.grill("answer", "Q1", "gradient-boosted trees", "--rationale", "the owner changed their mind")
        self.assertEqual(code, 2)
        self.assertIn("--revise", err)
        self.ok("answer", "Q1", "gradient-boosted trees", "--rationale", "the owner changed their mind", "--revise")
        records = self.records()
        self.assertEqual(records["Q1"]["answer"], "logistic regression", "the superseded record stays as it was")
        self.assertEqual((records["Q5"]["question"], records["Q5"]["answer"], records["Q5"]["supersedes"]),
                         (BASELINE, "gradient-boosted trees", "Q1"))
        self.assertIn("- superseded-by: Q5", self.decisions_md())
        self.assertEqual(len(self.events("decision")), 2)

    def test_the_decider_answers_through_the_same_function(self):
        record = answer(self.project, "Q2", "three", rationale="policy.json says three seeds", confidence=0.7, decided_by="decider")
        self.assertEqual(record["decided_by"], "decider")
        self.assertEqual(self.events("decision")[0]["payload"]["decided_by"], "decider")
        self.assertIn("- decided-by: decider", self.decisions_md())

    def test_an_answer_the_journal_missed_is_journaled_by_the_next_grill(self):
        with mock.patch.object(Ledger, "append_event", side_effect=OSError("no space left on device")):
            code, _, err = self.grill("answer", "Q1", "logistic regression", "--rationale", "the recommendation")
        self.assertEqual(code, 1, err)
        self.assertEqual(self.records()["Q1"]["answer"], "logistic regression", "DECISIONS.md was written before the journal failed")
        self.assertEqual(self.events("decision"), [])
        self.ok()
        [event] = self.events("decision")
        self.assertTrue(event["payload"]["answer"].startswith("Q1 " + BASELINE))
        self.ok()
        self.assertEqual(len(self.events("decision")), 1, "an answer is journaled once")

    def test_a_comment_opener_in_a_question_cannot_hide_its_record(self):
        self.ok("ask", "Keep the <!-- marker in the output?", "--recommend", "no")
        self.assertIn("### Q5. Keep the <\\!-- marker in the output?", self.decisions_md())
        self.assertEqual(self.records()["Q5"]["question"], "Keep the <!-- marker in the output?")

    def test_the_decider_never_answers_a_human_only_question(self):
        with self.assertRaises(GrillError) as caught:
            answer(self.project, "Q4", "no", rationale="more margin", decided_by="decider")
        self.assertIn("human-only", str(caught.exception))
        self.assertIsNone(self.records()["Q4"]["answer"])
        self.assertEqual(self.events("decision"), [])


class AskTest(GrillCase):
    """The design tree is built question by question, and nothing in it is taken on trust."""

    def test_a_prerequisite_must_already_be_in_the_tree(self):
        code, _, err = self.grill("ask", TERMS, "--requires", "Q7")
        self.assertEqual(code, 2)
        self.assertIn("Q7", err)
        self.assertFalse((self.project / "research" / "DECISIONS.md").exists())

    def test_the_same_question_twice_is_refused_with_the_record_that_asks_it(self):
        self.ok("ask", BASELINE)
        code, _, err = self.grill("ask", "which baseline do the claims  compare against?")
        self.assertEqual(code, 2)
        self.assertIn("Q1", err)

    def test_an_id_is_the_one_given_or_the_next_free_one(self):
        self.assertIn("Q7", self.ok("ask", BASELINE, "--id", "Q7"))
        self.assertIn("Q8", self.ok("ask", SEEDS))
        code, _, err = self.grill("ask", TERMS, "--id", "Q8")
        self.assertEqual(code, 2)
        self.assertIn("Q8", err)
        code, _, _ = self.grill("ask", TERMS, "--id", "question-3")
        self.assertEqual(code, 2)

    def test_a_hand_broken_record_is_reported_not_trusted(self):
        self.tree()
        path = self.project / "research" / "DECISIONS.md"
        path.write_text(self.decisions_md().replace('"reversible":true', '"reversible":"maybe"', 1), encoding="utf-8")
        code, _, err = self.grill()
        self.assertEqual(code, 1)
        self.assertIn("DECISIONS.md", err)
        self.assertIn("reversible", err)

    def test_a_decisions_md_wayline_did_not_write_is_left_alone(self):
        path = self.project / "research" / "DECISIONS.md"
        path.write_text("# My decisions\n\nWe use split_b.\n", encoding="utf-8")
        code, _, err = self.grill("ask", BASELINE)
        self.assertEqual(code, 1)
        self.assertIn("DECISIONS.md", err)
        self.assertEqual(path.read_text(encoding="utf-8"), "# My decisions\n\nWe use split_b.\n")


class TermTest(GrillCase):
    """Criterion 1: each settled term lands in CONTEXT.md, in the glossary's own format."""

    def test_a_term_lands_in_context_md_in_the_glossary_format(self):
        out = self.ok("term", "Held-out split", "The rows of split_b, which no ticket trains or tunes on.",
                      "--avoid", "test set, validation set")
        self.assertIn("Held-out split", out)
        self.assertIn("## Language\n\n**Held-out split**:\nThe rows of split_b, which no ticket trains or tunes on.\n"
                      "_Avoid_: test set, validation set\n", self.context_md())

    def test_a_term_settled_again_replaces_its_definition_and_keeps_everything_else(self):
        written = ("# Context\n\nThe owner's words.\n\n## Language\n\n**Seed**:\nOne random initialization.\n\n"
                   "**Interaction term**:\nA product of two features.\n_Avoid_: cross feature\n\n## Flagged ambiguities\n\n"
                   "- \"run\" meant a job once.\n")
        Ledger(self.project).write_markdown("CONTEXT.md", written)
        self.ok("term", "interaction term", "A product of two raw features, added as a column.")
        self.ok("term", "Held-out split", "The rows of split_b.")
        text = self.context_md()
        self.assertIn("**interaction term**:\nA product of two raw features, added as a column.\n\n", text)
        self.assertNotIn("A product of two features.", text)
        self.assertNotIn("cross feature", text)
        self.assertIn("# Context\n\nThe owner's words.\n\n## Language\n\n**Seed**:\nOne random initialization.\n\n", text)
        self.assertLess(text.index("**Held-out split**"), text.index("## Flagged ambiguities"))
        self.assertTrue(text.endswith("## Flagged ambiguities\n\n- \"run\" meant a job once.\n"))

    def test_an_entry_written_on_one_line_is_replaced_and_every_other_line_is_kept(self):
        written = ("# Context\n\n## Language\n\n**Seed**: One random init.\n\n\n**Split**:\nThe rows.\n\n"
                   "# Appendix\n\nA paragraph\nwrapped over two lines.\n")
        Ledger(self.project).write_markdown("CONTEXT.md", written)
        self.assertIn("replaced", self.ok("term", "Seed", "A generator seed."))
        text = self.context_md()
        self.assertEqual(text.count("**Seed**"), 1)
        self.assertIn("## Language\n\n**Seed**:\nA generator seed.\n\n\n**Split**:\nThe rows.\n", text, "the blank lines between entries are kept")
        self.ok("term", "Held-out split", "The rows of split_b.")
        self.assertTrue(self.context_md().endswith(
            "**Split**:\nThe rows.\n\n**Held-out split**:\nThe rows of split_b.\n\n# Appendix\n\nA paragraph\nwrapped over two lines.\n"))

    def test_a_term_with_a_definition_of_several_paragraphs_is_refused(self):
        code, _, err = self.grill("term", "Seed", "One.\n\nTwo.")
        self.assertEqual(code, 2)
        self.assertIn("definition", err)


class BatchTest(GrillCase):
    """`--from`: what a session with the owner present settles in one go, all of it or none."""

    def test_a_batch_adds_questions_answers_and_terms_then_asks_the_next_tier(self):
        self.tree()
        self.ok()
        batch = {"answers": [{"id": "Q1", "answer": "logistic regression", "rationale": "the recommendation", "confidence": 0.8},
                             {"id": "Q2", "answer": "three", "rationale": "the recommendation"}],
                 "terms": [{"term": "Seed", "definition": "One random initialization of a model.", "avoid": "run"}],
                 "questions": [{"question": "Which feature scaling do both models share?", "requires": ["Q1"], "recommended": "standardize"}]}
        out = self.ok("--from", "-", stdin=json.dumps(batch))
        self.assertIn("tier 2", out)
        records = self.records()
        self.assertEqual((records["Q1"]["confidence"], records["Q2"]["answer"]), (0.8, "three"))
        self.assertEqual((records["Q5"]["requires"], records["Q5"]["tier"]), (["Q1"], 2))
        self.assertIn("**Seed**:\nOne random initialization of a model.\n_Avoid_: run\n", self.context_md())
        self.assertEqual(len(self.events("decision")), 2)

    def test_a_batch_with_one_bad_entry_writes_nothing(self):
        self.tree()
        written = self.decisions_md()
        batch = {"answers": [{"id": "Q1", "answer": "logistic regression", "rationale": "r"},
                             {"id": "Q3", "answer": "pairwise", "rationale": "r"}],
                 "terms": [{"term": "Seed", "definition": "One random initialization."}]}
        code, _, err = self.grill("--from", "-", stdin=json.dumps(batch))
        self.assertEqual(code, 2)
        self.assertIn("Q3", err)
        self.assertEqual(self.decisions_md(), written)
        self.assertFalse((self.project / "research" / "CONTEXT.md").exists())
        self.assertEqual(self.events("decision"), [])

    def test_a_batch_value_of_the_wrong_type_is_refused_rather_than_crashing(self):
        self.tree()
        for batch in ({"terms": [{"term": "Seed", "definition": "One random initialization.", "avoid": 5}]},
                      {"terms": [{"term": "Seed", "definition": "One random initialization.", "avoid": True}]},
                      {"answers": [{"id": ["Q1"], "answer": "logistic regression", "rationale": "r"}]},
                      {"answers": [{"id": "Q1", "answer": "logistic regression", "rationale": "r", "revise": "yes"}]},
                      {"questions": [{"question": "Which metric?", "requires": "Q1"}]}):
            with self.subTest(batch=batch):
                code, out, err = self.grill("--from", "-", stdin=json.dumps(batch))
                self.assertEqual(code, 2, out + err)
                self.assertNotIn("Traceback", err)
        self.assertEqual(self.events("decision"), [])

    def test_a_batch_field_the_grill_does_not_know_is_refused(self):
        code, _, err = self.grill("--from", "-", stdin=json.dumps({"answers": [], "notes": "x"}))
        self.assertEqual(code, 2)
        self.assertIn("notes", err)


class SwitchAutonomyTest(GrillCase):
    """Criterion 2, and criterion 4's switch mid-grill, on the journal and harness.json."""

    def switch(self, *args):
        return run("switch", *args, "--project", str(self.project))

    def controls(self):
        return [event["payload"] for event in self.events("control")]

    def hold_the_conductor(self):
        heartbeat = Ledger(self.project).heartbeat().acquire()
        self.addCleanup(heartbeat.release)
        heartbeat.write(pid=4242, started_at="2026-09-13T10:00:00.000Z", last_wave_at=None, harness_tag="v0.0.0")

    def test_the_switch_mid_grill_journals_control_updates_harness_json_and_hands_the_rest_to_the_decider(self):
        self.tree()
        self.ok()
        self.answer("Q1", "logistic regression")
        before = self.decisions_md()
        code, out, err = self.switch("--autonomy", "autonomous")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.controls(), [{"command": "autonomy", "args": {"autonomy": "autonomous"}, "by": "cli"}])
        self.assertEqual(read_harness(self.project)["autonomy"], "autonomous")
        self.assertIn("decider", out)
        self.assertEqual(self.decisions_md(), before, "the switch answers nothing")
        view = self.tier()
        self.assertEqual(view["autonomy"], "autonomous")
        self.assertEqual([record["id"] for record in view["ask"]], ["Q4"], "only a human-only question is still the owner's")
        self.assertEqual([record["id"] for record in view["decider"]], ["Q2"])
        self.assertIn("decider", self.ok())

    def test_a_running_conductor_is_raised_at_its_next_wave(self):
        Ledger(self.project).append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "checkpoints",
                                                          "radius": "moderate", "pid": 4242})
        self.hold_the_conductor()
        code, out, err = self.switch("--autonomy", "autonomous")
        self.assertEqual(code, 0, out + err)
        self.assertIn("4242", out)
        self.assertEqual(replay.replay(self.events()).autonomy, "autonomous")
        self.assertEqual(read_harness(self.project)["autonomy"], "autonomous", "the next run starts where this one was raised to")

    def test_lowering_is_refused_while_a_conductor_is_alive(self):
        self.assertEqual(self.switch("--autonomy", "autonomous")[0], 0)
        self.hold_the_conductor()
        harness = (self.project / "harness.json").read_bytes()
        code, out, err = self.switch("--autonomy", "checkpoints")
        self.assertEqual(code, 1, out + err)
        self.assertIn("wayline stop", err)
        self.assertIn("4242", err)
        self.assertEqual((self.project / "harness.json").read_bytes(), harness)
        self.assertEqual(len(self.controls()), 1)

    def test_lowering_with_no_conductor_alive_edits_harness_json(self):
        self.assertEqual(self.switch("--autonomy", "autonomous")[0], 0)
        code, out, err = self.switch("--autonomy", "interactive")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(read_harness(self.project)["autonomy"], "interactive")
        self.assertEqual([payload["args"] for payload in self.controls()], [{"autonomy": "autonomous"}, {"autonomy": "interactive"}])
        self.assertEqual(json.loads((self.project / "harness.json").read_text(encoding="utf-8"))["radius"], "moderate",
                         "the rest of harness.json is kept")

    def test_an_irreversible_question_stays_the_owners_under_autonomous(self):
        self.ok("ask", "Delete the raw data once the features are built?", "--irreversible", "--recommend", "no")
        self.ok("ask", SEEDS, "--recommend", "three")
        self.assertEqual(self.switch("--autonomy", "autonomous")[0], 0)
        view = self.tier()
        self.assertEqual([record["id"] for record in view["ask"]], ["Q1"])
        self.assertEqual([record["id"] for record in view["decider"]], ["Q2"])
        with self.assertRaises(GrillError) as caught:
            answer(self.project, "Q1", "yes", rationale="it saves disk", decided_by="decider")
        self.assertIn("irreversible", str(caught.exception))
        self.assertEqual(self.events("decision"), [])

    def edit_harness(self, autonomy):
        path = self.project / "harness.json"
        harness = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(dict(harness, autonomy=autonomy), indent=2) + "\n", encoding="utf-8")

    def start_run(self, autonomy):
        Ledger(self.project).append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": autonomy,
                                                          "radius": "moderate", "pid": 4242})
        self.hold_the_conductor()

    def test_a_hand_edited_harness_json_cannot_pass_a_lowering_off_as_a_raise(self):
        self.edit_harness("autonomous")
        self.start_run("autonomous")
        self.edit_harness("interactive")
        code, out, err = self.switch("--autonomy", "checkpoints")
        self.assertEqual(code, 1, out + err)
        self.assertIn("wayline stop", err)
        self.assertEqual(self.controls(), [])
        self.assertEqual(replay.replay(self.events()).autonomy, "autonomous")

    def test_a_run_the_file_already_names_the_new_autonomy_for_is_still_raised(self):
        self.edit_harness("autonomous")
        self.start_run("checkpoints")
        code, out, err = self.switch("--autonomy", "autonomous")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("already", out)
        self.assertIn("raised from checkpoints to autonomous", out)
        self.assertEqual(len(self.controls()), 1)
        self.assertEqual(replay.replay(self.events()).autonomy, "autonomous")

    def test_the_same_autonomy_again_changes_nothing(self):
        code, out, _ = self.switch("--autonomy", "checkpoints")
        self.assertEqual(code, 0)
        self.assertIn("already", out)
        self.assertEqual(self.controls(), [])

    def test_switch_takes_a_project_path_or_an_autonomy_but_not_both(self):
        code, _, err = run("switch", str(self.project), "--autonomy", "autonomous")
        self.assertEqual(code, 2)
        self.assertIn("--autonomy", err)
        code, _, _ = run("switch")
        self.assertEqual(code, 2)
        code, _, _ = self.switch("--autonomy", "manual")
        self.assertEqual(code, 2)

    def test_the_dashboard_raises_through_the_same_function(self):
        report = set_autonomy(self.project, "autonomous", by="dashboard")
        self.assertEqual((report["from"], report["to"], report["changed"]), ("checkpoints", "autonomous", True))
        self.assertEqual(self.controls()[0]["by"], "dashboard")


class StartingConductorTest(ConductorCase):
    """A lowering journaled while a conductor starts is the autonomy the run announces, not the one it first read."""

    def test_a_lowering_written_between_the_conductors_read_and_its_heartbeat_holds(self):
        set_autonomy(self.project, "autonomous")
        original = Heartbeat.acquire

        def acquire(heartbeat, *args, **kwargs):
            set_autonomy(self.project, "checkpoints")  # no conductor holds the project yet, so a lowering is allowed
            return original(heartbeat, *args, **kwargs)

        with mock.patch.object(Heartbeat, "acquire", acquire), worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            conductor = Conductor(self.project, out=io.StringIO())
            conductor.run(wait=lambda seconds: conductor.settle())
        self.assertEqual(self.payload("run_started")["autonomy"], "checkpoints")
        self.assertEqual(replay.replay(self.events()).autonomy, "checkpoints")


def journal_answer(root, record):
    """The `decision` event `wayline grill answer` appends for a record, appended to a copied recording."""
    event = make_event("decision", {"ticket": None, "answer": "%s %s Answer: %s" % (record["id"], record["question"], record["answer"]),
                                    "decided_by": record["decided_by"], "rationale": record["rationale"],
                                    "confidence": record["confidence"]}, ts=record["timestamp"])
    with open(root / "research" / "journal.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


class RecordedGrillFixtureTest(ProjectTestCase):
    """Criterion 4: the grill recorded over the toy intent passes every structural check its fixture declares."""

    FIXTURE = FIXTURES_DIR / "skill" / "wayline-grill"

    def checks(self):
        return json.loads((self.FIXTURE / "fixture.json").read_text(encoding="utf-8"))["structural"]

    def failures(self, root):
        return [problem for check in self.checks() for problem in structural(check, root, self.FIXTURE)]

    def broken(self):
        root = self.temp / "broken"
        shutil.copytree(self.FIXTURE / "recorded", root)
        return root

    def test_the_recording_passes_every_structural_check(self):
        kinds = {check["check"] for check in self.checks()}
        self.assertTrue({"file_exists", "python", "tool_used", "tool_not_used"} <= kinds, kinds)
        for check in self.checks():
            with self.subTest(check=check):
                self.assertEqual(structural(check, self.FIXTURE / "recorded", self.FIXTURE), [])

    def test_the_checks_catch_a_session_that_answers_for_the_owner_after_the_switch(self):
        root = self.broken()
        records = read_records(root)
        for identifier in [record["id"] for record in frontier(records) if not record["human_only"]]:
            records, record = with_answer(records, identifier, "what the session liked", "the session chose", ts="2099-01-01T00:00:00.000Z")
            journal_answer(root, record)
        (root / "research" / "DECISIONS.md").write_text(render_decisions(records), encoding="utf-8")
        failures = self.failures(root)
        self.assertTrue(any("after the switch" in problem for problem in failures), failures)

    def test_the_owners_answer_to_a_human_only_question_after_the_switch_passes(self):
        root = self.broken()
        records, record = with_answer(read_records(root), "Q7", "the null control and the anti-claim", "the owner took the recommendation",
                                      ts="2099-01-01T00:00:00.000Z")
        journal_answer(root, record)
        (root / "research" / "DECISIONS.md").write_text(render_decisions(records), encoding="utf-8")
        self.assertEqual(self.failures(root), [])

    def test_the_checks_catch_an_answer_no_earlier_tier_put_to_the_owner(self):
        root = self.broken()
        line = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_test", "name": "Bash",
                                                              "input": {"command": 'wayline grill answer Q2 "moderate" --rationale "the session chose"'}}]}}
        with open(root / "trace-1.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        failures = self.failures(root)
        self.assertTrue(any("answered Q2, which no earlier turn asked" in problem for problem in failures), failures)

    def test_the_checks_catch_a_tier_question_left_out_of_the_message(self):
        root = self.broken()
        path = root / "result-2.json"
        envelope = json.loads(path.read_text(encoding="utf-8"))
        asked = "Which flexible model without products is the second baseline?"
        self.assertIn(asked, envelope["result"])
        envelope["result"] = envelope["result"].replace(asked, "What else did I look up?")
        path.write_text(json.dumps(envelope), encoding="utf-8")
        failures = self.failures(root)
        self.assertTrue(any("turn 2 printed Q8" in problem for problem in failures), failures)

    def test_the_checks_catch_a_record_written_around_the_verb(self):
        root = self.broken()
        records, _ = with_answer(read_records(root), "Q8", "a small network", "the session chose", ts="2099-01-01T00:00:00.000Z")
        (root / "research" / "DECISIONS.md").write_text(render_decisions(records), encoding="utf-8")
        failures = self.failures(root)
        self.assertTrue(any("Q8 is settled in DECISIONS.md with no decision in the journal" in problem for problem in failures), failures)

    def test_a_prerequisite_missing_from_the_file_is_reported_not_raised(self):
        root = self.broken()
        path = root / "research" / "DECISIONS.md"
        path.write_text(path.read_text(encoding="utf-8").replace('"requires":[]', '"requires":["Q12"]', 1), encoding="utf-8")
        failures = self.failures(root)
        self.assertTrue(any("Q12" in problem for problem in failures), failures)

    def test_the_checks_catch_a_tier_asked_without_its_recommendations(self):
        root = self.broken()
        path = root / "result-1.json"
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["result"] = envelope["result"].replace("Recommended:", "Maybe:")
        path.write_text(json.dumps(envelope), encoding="utf-8")
        failures = self.failures(root)
        self.assertTrue(any("Recommended:" in problem for problem in failures), failures)

    def test_the_checks_catch_a_fact_put_to_the_owner(self):
        root = self.broken()
        records, _ = with_question(read_records(root), "Is scikit-learn installed on this machine?", recommended="yes")
        (root / "research" / "DECISIONS.md").write_text(render_decisions(records), encoding="utf-8")
        failures = self.failures(root)
        self.assertTrue(any("asks a fact" in problem for problem in failures), failures)
