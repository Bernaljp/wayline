"""Provenance tags, the classifier, the linter, the sampled verdicts, and REPORT.md (tickets 40 and 90).

Every model call goes through the fake launcher. The classifier is answered by a responder that
reads the numbered sentences it was actually sent; the verifier by scripted envelopes. No writer
drafts the report: code alone writes it (ticket 90). What is asserted is what the owner and the next component see: the REPORT.md on disk,
the cache, the journal's `report_rendered` and `verdict` events, and the writing tickets filed.
The ledger they run against is `fixtures/projects/ended-run/`, a toy run that ended.
"""

import io
import json
import re
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import cli, provenance, tickets, worker
from wayline.ledger import Ledger
from wayline.provenance import (
    CLAIMS_CACHE, SECTIONS, Claim, ProvenanceError, classify, claim_subject, lint, lint_report,
    prose_sentences, read_claims_cache, render_citations, render_report, restore_tags, sample_claims,
    sample_size, sentence_hash, verify_claims,
)
from wayline.worker import Envelope

ENDED_RUN = FIXTURES_DIR / "projects" / "ended-run"
SAMPLE = (FIXTURES_DIR / "reports" / "sample-report.md").read_text(encoding="utf-8")
POLICY = json.loads((FIXTURES_DIR.parent / "policy.json").read_text(encoding="utf-8"))

NUMBERED = re.compile(r"^\[(\d+)\] (.*)$", re.M)

INTERACTIONS = "{res:t3-a1/results/interactions/summary.json#auroc_mean}"
BASELINE = "{res:t2-a1/results/baseline/summary.json#auroc_mean}"
DEPTH = "{res:t4-a1/results/depth/summary.json#auroc_mean}"
GROUP = "SPEC.md#c1-interaction-terms"



def rule(sentence):
    """How the faked classifier reads a sentence."""
    lowered = sentence.lower()
    if " means " in lowered:
        return "definition"
    if lowered.startswith("next,"):
        return "transition"
    if lowered.startswith("each "):
        return "method_description"
    return "claim"


class Classifier:
    """A responder for the fake launcher: classifies the sentences it was sent, and keeps every batch."""

    def __init__(self):
        self.batches = []

    def __call__(self, request, message):
        found = NUMBERED.findall(request.prompt)
        self.batches.append([text for _, text in found])
        return Envelope(structured_output={"classes": [{"n": int(number), "class": rule(text)} for number, text in found]})


def verdict(passed=True, text="The artifact holds 0.861, not a gain over the baseline.", locator="results/interactions/summary.json#auroc_mean"):
    findings = [] if passed else [{"text": text, "locator": locator, "severity": "blocker"}]
    return Envelope(structured_output={"pass": passed, "findings": findings,
                                       "question_limit": "Whether the cited artifacts support the sentence."})


class RunCase(ProjectTestCase):
    """A writable copy of the ended run."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "ended-run"
        shutil.copytree(ENDED_RUN, self.project)
        self.book = Ledger(self.project)
        self.calls = []

    def events(self, name):
        found, _ = self.book.read_events()
        return [event for event in found if event["event"] == name]

    def render(self, offline=False):
        """Render with the classifier answered; nothing else is scripted, since code alone writes the report."""
        with worker.use_fake() as fake:
            self.classifier = Classifier()
            for _ in range(6):
                fake.script(respond=self.classifier, role="classifier")
            rendered = render_report(self.project, offline=offline)
            self.calls = list(fake.calls)
        return rendered

    def roles_called(self):
        return [call.request.role for call in self.calls]

    def report_events(self):
        """REPORT.md's renders: the account's, in the same pass (ticket 89), carry `report: account`."""
        return [event for event in self.events("report_rendered") if "report" not in event["payload"]]

    def account(self, title):
        """One section of `research/ACCOUNT.md`, which the render wrote beside REPORT.md (ticket 89)."""
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        start = text.index("## %s\n" % title)
        following = re.search(r"^## ", text[start + 3:], re.M)
        return text[start:start + 3 + following.start()] if following else text[start:]

    def text(self):
        return (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")

    def section(self, number):
        """One numbered section of the general report, in decision 17's order (ticket 90)."""
        text = self.text()
        start = text.index("## %d. %s" % (number, SECTIONS[number - 1]))
        following = re.search(r"^## ", text[start + 3:], re.M)
        return text[start:start + 3 + following.start()] if following else text[start:]


# --- tags ------------------------------------------------------------------------------------------


class TagsTest(unittest.TestCase):
    def test_tags_render_as_numbered_citations_listed_at_the_end(self):
        rendered = render_citations("A holds.{res:t1-a1/x.json#k} B holds.{ref:paper-a#s1} C holds.{res:t1-a1/x.json#k}\n")
        self.assertIn("A holds.[^1] B holds.[^2] C holds.[^1]", rendered)
        self.assertIn("## Supplementary references", rendered)
        self.assertIn("[^1]: `res:t1-a1/x.json#k`", rendered)
        self.assertIn("[^2]: `ref:paper-a#s1`", rendered)
        self.assertNotIn("{res:", rendered)

    def test_a_document_without_tags_is_left_alone(self):
        self.assertEqual(render_citations("No tags here.\n"), "No tags here.\n")

    def test_the_citations_read_back_as_the_tags_they_were(self):
        self.assertEqual(prose_sentences(restore_tags(render_citations(SAMPLE))), prose_sentences(SAMPLE))

    def test_a_citation_with_no_reference_line_reads_as_untagged(self):
        self.assertEqual(prose_sentences(restore_tags("It holds.[^4]\n"))[0].tags, ())

    def test_prose_is_paragraphs_and_list_items_only(self):
        texts = [sentence.text for sentence in prose_sentences(SAMPLE)]
        self.assertEqual(texts, [
            "Pairwise interaction terms raise the held-out AUROC to 0.861." + INTERACTIONS,
            "The baseline reaches a held-out AUROC of 0.812." + BASELINE,
            "Next, the section turns to the references.",
            "Interaction features were studied on tabular data before this run.{ref:paper-a#sec-2}",
            "AUROC means the area under the receiver operating characteristic curve.",
            "Each model was trained on three seeds.",
            "Doubling the depth leaves the held-out AUROC within one standard deviation of the baseline." + DEPTH,
        ])

    def test_a_sentence_keeps_its_hash_when_a_tag_is_added_and_loses_it_when_a_word_changes(self):
        plain = "The baseline reaches 0.812."
        self.assertEqual(sentence_hash(plain), sentence_hash(plain + BASELINE))
        self.assertEqual(sentence_hash(plain), sentence_hash("The  baseline\nreaches 0.812."))
        self.assertNotEqual(sentence_hash(plain), sentence_hash("The baseline reaches 0.813."))


# --- the classifier --------------------------------------------------------------------------------


class ClassifierTest(RunCase):
    TEXTS = ["Sentence %d holds." % number for number in range(5)]

    def classify(self, texts, scripted=3, **options):
        with worker.use_fake() as fake:
            self.classifier = Classifier()
            for _ in range(scripted):
                fake.script(respond=self.classifier, role="classifier")
            classes = classify(self.project, texts, **options)
            self.calls = list(fake.calls)
        return classes

    def test_sentences_are_classified_in_haiku_batches_through_the_launcher(self):
        classes = self.classify(self.TEXTS, batch_size=2)
        self.assertEqual(self.classifier.batches, [self.TEXTS[0:2], self.TEXTS[2:4], self.TEXTS[4:5]])
        for call in self.calls:
            self.assertEqual((call.request.role, call.request.model, call.request.effort), ("classifier", "haiku", "low"))
            self.assertEqual(call.request.schema_path.name, "claim_classes.json")
            self.assertEqual(call.request.allowed_tools, [])
        self.assertEqual(len(classes), 5)
        cached = json.loads((self.project / "research" / CLAIMS_CACHE).read_text(encoding="utf-8"))
        self.assertEqual(cached["classes"], {sentence_hash(text): "claim" for text in self.TEXTS})

    def test_a_rebuild_classifies_only_the_sentences_that_changed(self):
        self.classify(self.TEXTS)
        self.classify(self.TEXTS, scripted=0)
        self.assertEqual(self.calls, [], "an unchanged document launches nothing")
        changed = list(self.TEXTS)
        changed[2] = "Sentence 2 holds no longer."
        self.classify(changed)
        self.assertEqual(self.classifier.batches, [["Sentence 2 holds no longer."]])
        self.classify([self.TEXTS[0] + BASELINE], scripted=0)
        self.assertEqual(self.calls, [], "a tag says where a claim comes from, not what kind of sentence it is")

    def test_the_session_sees_the_sentence_without_its_tags(self):
        self.classify(["The baseline reaches 0.812." + BASELINE])
        self.assertEqual(self.classifier.batches, [["The baseline reaches 0.812."]])

    def test_an_answer_missing_a_sentence_is_resumed_once_and_then_refused(self):
        short = Envelope(structured_output={"classes": [{"n": 1, "class": "claim"}]})
        with worker.use_fake() as fake:
            fake.script(short, role="classifier")
            fake.script(short, role="classifier")
            with self.assertRaises(ProvenanceError) as raised:
                classify(self.project, self.TEXTS[:2])
            kinds = [call.kind for call in fake.calls]
        self.assertEqual(kinds, ["launch", "resume"])
        self.assertIn("no class for sentence(s) 2", str(raised.exception))
        self.assertEqual(read_claims_cache(self.project), {})

    def test_a_batch_that_fails_keeps_the_batches_before_it(self):
        with worker.use_fake() as fake:
            fake.script(respond=Classifier(), role="classifier")
            fake.script(Envelope(structured_output={"classes": []}), role="classifier")
            fake.script(Envelope(structured_output={"classes": []}), role="classifier")
            with self.assertRaises(ProvenanceError):
                classify(self.project, self.TEXTS[:2], batch_size=1)
        self.assertEqual(read_claims_cache(self.project), {sentence_hash(self.TEXTS[0]): "claim"})

    def test_offline_launches_nothing(self):
        self.assertEqual(self.classify(self.TEXTS, scripted=0, offline=True), {})
        self.assertEqual(self.calls, [])


# --- the linter ------------------------------------------------------------------------------------


class LintTest(RunCase):
    def lint(self, text, offline=False):
        with worker.use_fake() as fake:
            for _ in range(2):
                fake.script(respond=Classifier(), role="classifier")
            classes = classify(self.project, [sentence.text for sentence in prose_sentences(text)], offline=offline)
        return lint(self.project, text, classes)

    def problems(self, result):
        return [(problem["problem"], problem["sentence"]) for problem in result.problems]

    def test_the_sample_report_passes(self):
        result = self.lint(SAMPLE)
        self.assertEqual(result.problems, [])
        self.assertTrue(result.passed)
        self.assertEqual((result.claims, result.tagged), (4, 4))

    def test_a_claim_without_a_tag_fails_with_the_sentence(self):
        result = self.lint(SAMPLE.replace("0.861." + INTERACTIONS, "0.861."))
        self.assertFalse(result.passed)
        self.assertEqual(self.problems(result), [("untagged_claim", "Pairwise interaction terms raise the held-out AUROC to 0.861.")])
        self.assertEqual((result.claims, result.tagged), (4, 3))

    def test_a_negative_result_is_a_claim_and_needs_a_tag(self):
        result = self.lint(SAMPLE.replace("baseline." + DEPTH, "baseline."))
        self.assertEqual(self.problems(result), [
            ("untagged_claim", "Doubling the depth leaves the held-out AUROC within one standard deviation of the baseline.")])

    def test_a_tag_inside_a_sentence_does_not_end_it(self):
        result = self.lint(SAMPLE.replace("Pairwise interaction terms raise the held-out AUROC to 0.861." + INTERACTIONS,
                                          "Pairwise interaction terms" + INTERACTIONS + " raise the held-out AUROC to 0.861."))
        self.assertEqual([problem["problem"] for problem in result.problems], ["untagged_claim"])
        self.assertIn("inside it", result.problems[0]["detail"])

    def test_a_res_tag_to_an_artifact_the_manifest_does_not_hold_does_not_resolve(self):
        result = self.lint(SAMPLE.replace("results/interactions/summary.json", "results/interactions/missing.json"))
        self.assertEqual([problem["problem"] for problem in result.problems], ["unresolved_res"])
        self.assertIn("results/interactions/missing.json is not in manifest.json", result.problems[0]["detail"])

    def test_a_res_tag_naming_the_wrong_run_does_not_resolve(self):
        result = self.lint(SAMPLE.replace("t3-a1/results/interactions", "t9-a1/results/interactions"))
        self.assertEqual([problem["problem"] for problem in result.problems], ["unresolved_res"])
        self.assertIn("from run t3-a1, not from run t9-a1", result.problems[0]["detail"])

    def test_a_ref_tag_resolves_only_to_a_verified_reference_with_a_node(self):
        for slug, detail in (("paper-z", "holds no dossier.json"), ("paper-d", "existence: verified")):
            with self.subTest(slug=slug):
                result = self.lint(SAMPLE.replace("{ref:paper-a#", "{ref:%s#" % slug))
                self.assertEqual([problem["problem"] for problem in result.problems], ["unresolved_ref"])
                self.assertIn(detail, result.problems[0]["detail"])
        (self.project / "research" / "kb" / "nodes" / "paper-a.json").unlink()
        result = self.lint(SAMPLE)
        self.assertEqual([problem["problem"] for problem in result.problems], ["unresolved_ref"])
        self.assertIn("no node paper-a", result.problems[0]["detail"])

    def test_a_finding_whose_artifact_was_never_manifested_does_not_resolve(self):
        record = {"id": "f-0009", "ticket": 2, "text": "The unmanifested run scores 0.9.",
                  "provenance": ["results/nowhere.json#auroc"], "negative": False, "ts": "2026-09-12T03:00:00.000Z"}
        text = provenance.finding_line(record, provenance.read_manifest(self.project))
        result = self.lint(text)
        self.assertEqual([problem["problem"] for problem in result.problems], ["unresolved_res"])
        self.assertIn("results/nowhere.json is not in manifest.json", result.problems[0]["detail"])

    def test_a_malformed_tag_fails(self):
        result = self.lint(SAMPLE.replace(DEPTH, "{res:results/depth/summary.json#auroc_mean}"))
        self.assertEqual([problem["problem"] for problem in result.problems], ["malformed_tag"])

    def test_definitions_transitions_and_method_descriptions_need_no_tag(self):
        result = self.lint(SAMPLE)
        self.assertNotIn("AUROC means", json.dumps(result.problems))
        self.assertNotIn("Each model", json.dumps(result.problems))

    def test_records_tables_and_code_are_not_linted(self):
        result = self.lint(SAMPLE.replace("<!-- /wayline:records -->", "The model is perfect.\n<!-- /wayline:records -->", 1))
        self.assertTrue(result.passed)

    def test_an_untagged_sentence_nobody_classified_fails(self):
        result = self.lint(SAMPLE, offline=True)
        self.assertEqual(sorted(problem["problem"] for problem in result.problems), ["unclassified"] * 3)
        self.assertFalse(result.passed)


# --- the sampling rule -----------------------------------------------------------------------------


def claims(count, hardest=()):
    return [Claim("Claim %d holds." % number, ("res:t%d-a1/results/x.json#k" % (3 if number in hardest else 1),),
                  "%064x" % number, (3 if number in hardest else 1,)) for number in range(count)]


class SamplingTest(unittest.TestCase):
    DIFFICULTIES = {1: 2, 3: 5}

    def test_ten_percent_of_the_tagged_claims(self):
        self.assertEqual(sample_size(150, POLICY), 15)
        self.assertEqual(len(sample_claims(claims(150), POLICY, self.DIFFICULTIES)), 15)

    def test_at_least_ten(self):
        self.assertEqual(len(sample_claims(claims(30), POLICY, self.DIFFICULTIES)), 10)

    def test_fewer_than_ten_claims_are_all_read(self):
        self.assertEqual(sample_claims(claims(4), POLICY, self.DIFFICULTIES), claims(4))

    def test_every_difficulty_5_claim_is_added_on_top(self):
        every = claims(50, hardest={7, 21, 44})
        chosen = sample_claims(every, POLICY, self.DIFFICULTIES)
        self.assertEqual(len(chosen), 13)
        for number in (7, 21, 44):
            self.assertIn(every[number], chosen)

    def test_the_policy_can_leave_difficulty_5_claims_to_the_draw(self):
        policy = dict(POLICY, provenance=dict(POLICY["provenance"], all_difficulty_5=False))
        self.assertEqual(len(sample_claims(claims(50, hardest={7, 21, 44}), policy, self.DIFFICULTIES)), 10)

    def test_the_same_claims_draw_the_same_sample_in_document_order(self):
        every = claims(150)
        first = sample_claims(every, POLICY, self.DIFFICULTIES)
        self.assertEqual(first, sample_claims(every, POLICY, self.DIFFICULTIES))
        self.assertEqual(first, sorted(first, key=every.index))
        self.assertNotEqual(first, sample_claims(every, POLICY, self.DIFFICULTIES, seed="another"))


# --- REPORT.md -------------------------------------------------------------------------------------


class ReportTest(RunCase):
    def setUp(self):
        super().setUp()
        self.rendered = self.render()

    def test_the_sections_are_the_general_reports_in_decision_17s_order(self):
        headings = re.findall(r"^## (\d+)\. (.*)$", self.text(), re.M)
        self.assertEqual([title for _, title in headings], list(SECTIONS))

    def test_what_wayline_did_is_in_the_account_and_no_longer_in_the_report(self):
        text = self.text()
        for gone in ("Decisions by the decider", "Open decision tickets", "Tickets closed", "Judged on Opus", "Papers by level",
                     "Not pursued", "Proposed global harness changes", "Resources spent", "The run's events"):
            self.assertNotIn(gone, text)
        self.assertIn("[ACCOUNT.md](ACCOUNT.md)", text.split("## 1.")[0])

    def test_decider_decisions_are_in_the_account_with_rationale_link_and_confidence(self):
        decided = self.account("Decided for you")
        self.assertIn("ticket 8, *Which held-out split does the goal read?*: **split_b** (by the decider, confidence 0.8", decided)
        self.assertIn("(tickets/08-which-held-out-split-does-the-goal-read.md)", decided)
        self.assertNotIn("20000 rows", decided, "a human's decision is not the decider's")

    def test_a_decider_decision_of_the_grill_is_listed_without_a_ticket(self):
        self.book.append_event("decision", {"ticket": None, "answer": "Q2 How many seeds does a comparison use? Answer: three",
                                            "decided_by": "decider", "rationale": "policy.json says three", "confidence": 0.7})
        self.render()
        decided = self.account("Decided for you")
        self.assertIn("Q2, *How many seeds does a comparison use?*: **three** (by the decider, confidence 0.7", decided)
        self.assertNotIn("ticket None", decided)

    def test_open_decision_tickets_and_needs_human_are_in_the_account(self):
        waiting = self.account("Waiting on you")
        self.assertIn("Decision ticket 6 (human only): Which label source wins where the two disagree?", waiting)
        self.assertNotIn("Decision ticket 11", waiting, "under autonomous the decider takes it")
        self.assertIn("Ticket 7, *Convert the second reference's PDF*, needs a person: Install the converter venv", waiting)
        self.assertNotIn("Decision ticket 8", waiting)
        self.assertNotIn("at the ladder's top rung", waiting, "no ticket here ended on the top rung")

    def test_the_goal_shows_its_kept_values_and_the_discarded_change(self):
        goal = self.section(4)
        self.assertIn("### O1.", goal)
        self.assertIn("Status: answered.", goal)
        self.assertIn("Goal: `auroc`, direction up, target 0.85", goal)
        self.assertIn("Kept values: 0.812 from run `t2-a1` (ticket 2); 0.861 from run `t3-a1` (ticket 3).", goal)
        self.assertIn("ticket 4: mean 0.815 against the best 0.861, standard deviation 0.011, seeds 3", goal)

    def test_findings_render_under_their_results_with_citations_that_resolve(self):
        beyond = self.section(5)
        self.assertIn("### R2. Do interaction terms raise the held-out AUROC? (supported)", beyond)
        self.assertRegex(beyond, r"`f-0003` Pairwise interaction terms raise the held-out AUROC to 0\.861\.\[\^\d+\]\[\^\d+\] That is")
        self.assertIn("`res:t3-a1/results/interactions/summary.json#auroc_mean`", self.text())
        self.assertNotIn("{res:", self.text(), "tags render as citations in the file")

    def test_each_tickets_outcome_with_its_verdict_and_model_is_in_the_accounts_run(self):
        runs = self.account("Runs")
        self.assertIn("| 1 | analysis | accepted | quality passed | sonnet | 14 | 10.0 |", runs)
        self.assertIn("| 3 | experiment | accepted | result passed | fable | 41 | 25.0 |", runs)
        self.assertIn("| 4 | experiment | done | none | opus | 19 | 10.0 |", runs)

    def test_a_negative_result_stays_in_place_marked_and_the_table_flags_it(self):
        self.assertRegex(self.section(5), r"`f-0004` \(negative\) Doubling the model depth .*baseline\.\[\^\d+\]\[\^\d+\]")
        self.assertIn("| R3 Does depth alone do it? | none | **negative** | 1 current, 1 negative |", self.section(3))

    def test_papers_by_level_and_the_promotions_not_read_in_full_are_the_accounts_library(self):
        library = self.account("Library")
        self.assertIn("- Level 2 (2): `paper-a`, `paper-b`", library)
        self.assertIn("- Level 0 (1): `paper-d` (unresolved)", library)
        self.assertIn("`paper-b`: promoted to level 2 on `consultant_question`", library)
        self.assertIn("`paper-c`: a promotion beyond the phase's reading budget waits on decision ticket 11", library)
        self.assertNotIn("`paper-a`: promoted", library, "paper-a was absorbed at level 2")

    def test_parked_proposals_are_listed_as_not_pursued_in_the_account(self):
        ninth = self.account("Not pursued")
        self.assertIn("Proposal `p-0002` from ticket 3 (analysis): parked, reason `cap`", ninth)
        self.assertIn("Proposal `p-0003` from ticket 4 (experiment): parked, reason `radius`", ninth)
        self.assertIn("Ticket 9, *Probe the calibration of the interaction model* (analysis): parked", ninth)
        self.assertNotIn("p-0001", ninth)

    def test_the_resources_spent_are_the_accounts_run(self):
        runs = self.account("Runs")
        self.assertIn("Paused at 2026-09-11 22:21Z on the `five_hour` window at 0.92", runs)
        self.assertIn("Held the launches on Fable at 2026-09-11 20:03Z", runs)
        self.assertIn("Peak utilization: fable 1, five_hour 0.92, seven_day 0.51.", runs)
        self.assertIn("GPU 2.25 hours", runs)

    def test_report_rendered_is_journaled_with_the_digest_and_the_counts(self):
        payload = self.report_events()[-1]["payload"]
        self.assertEqual(payload, {"sha256": provenance.sha256_of(self.rendered.path), "claims": 5, "tagged": 5, "linter_pass": True})
        self.assertTrue(self.rendered.lint.passed)

    def test_no_writer_drafts_any_of_it(self):
        self.assertEqual(self.roles_called(), ["classifier"])

    def test_one_classifier_batch_covered_every_finding_sentence(self):
        self.assertEqual(len(self.classifier.batches), 1)
        self.assertEqual(len(self.classifier.batches[0]), 5)

    def test_the_report_on_disk_passes_the_linter(self):
        result = lint_report(self.project)
        self.assertTrue(result.passed, result.problems)
        self.assertEqual((result.claims, result.tagged), (5, 5))

    def test_a_rebuild_with_nothing_changed_launches_nothing(self):
        again = self.render(offline=True)
        self.assertEqual(self.calls, [])
        self.assertTrue(again.lint.passed)
        self.assertEqual(again.lint.claims, 5)

    def test_a_new_finding_classifies_only_its_sentence(self):
        record = {"id": "f-0005", "ticket": 2, "text": "The seed-3 baseline scores 0.812.", "heading": "Do interaction terms raise the held-out AUROC?",
                  "provenance": ["results/baseline/seed-3/summary.json#auroc"], "negative": False, "ts": "2026-09-12T03:00:00.000Z"}
        self.book.append_record("findings.jsonl", record)
        self.render()
        self.assertEqual(self.roles_called(), ["classifier"])
        self.assertEqual(self.classifier.batches, [["`f-0005` The seed-3 baseline scores 0.812."]])


MALFORMED = {"id": "f-0005", "ticket": 4, "text": "Depth alone does not reach the goal.{res:results/depth.json#x}", "heading": "Does depth alone do it?",
             "provenance": ["results/depth/summary.json#auroc_mean"], "negative": True, "ts": "2026-09-12T03:00:00.000Z"}


class LinterFailureTest(RunCase):
    def test_a_refused_tag_is_named_in_the_banner_without_becoming_a_citation_there(self):
        self.book.append_record("findings.jsonl", MALFORMED)
        rendered = self.render()
        self.assertEqual([problem["problem"] for problem in rendered.lint.problems], ["malformed_tag"])
        banner = self.text().split("## 1.")[0]
        self.assertIn("The provenance linter FAILED", banner)
        self.assertIn("`malformed_tag` `f-0005` (negative) Depth alone does not reach the goal. (tag `res:results/depth.json#x`:", banner)
        self.assertNotIn("[^", banner)
        self.assertEqual(self.report_events()[-1]["payload"]["linter_pass"], False)

    def test_an_offline_first_render_launches_nothing_and_classifies_nothing(self):
        rendered = self.render(offline=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(rendered.lint.claims, 0, "nothing was classified")
        self.assertTrue(rendered.lint.passed, "every finding ends with its provenance tags")


REFUSED = Envelope(subtype="success", rate_limit_events=[
    {"status": "rejected", "resets_at": 1789524000, "rate_limit_type": "seven_day_overage_included"}])


class UsageLimitTest(RunCase):
    def test_a_classifier_refused_by_the_usage_limit_leaves_the_sentences_unclassified(self):
        with worker.use_fake() as fake:
            fake.script(REFUSED, role="classifier")
            rendered = render_report(self.project)
            self.calls = list(fake.calls)
        self.assertEqual([call.kind for call in self.calls if call.request.role == "classifier"], ["launch"])
        self.assertIn("classifier", " ".join(rendered.notes))
        self.assertEqual(rendered.lint.claims, 0)
        self.assertIn("seven_day_overage_included", self.text().split("## 1.")[0])


# --- the verifier's sample -------------------------------------------------------------------------


class VerifyTest(RunCase):
    def setUp(self):
        super().setUp()
        self.render()

    def verify(self, respond=None, scripted=5):
        with worker.use_fake() as fake:
            for _ in range(scripted):
                fake.script(respond=respond or (lambda request, message: verdict()), role="verifier")
            outcome = verify_claims(self.project)
            self.calls = list(fake.calls)
        return outcome

    def test_every_sampled_claim_gets_a_verdict_from_its_authors_table_verifier(self):
        outcome = self.verify()
        self.assertEqual((outcome["claims"], outcome["sampled"], len(outcome["passed"])), (5, 5, 5))
        verdicts = self.events("verdict")
        claims_verdicted = [event["payload"] for event in verdicts if event["payload"]["subject_kind"] == "claim"]
        self.assertEqual(len(claims_verdicted), 5)
        self.assertEqual({payload["verdict_type"] for payload in claims_verdicted}, {"claim_support"})
        by_sentence = {}
        for call in self.calls:
            for marker in ("`f-0001`", "`f-0002`"):
                if marker in call.request.prompt:
                    by_sentence[marker] = (call.request.model, call.request.effort)
        self.assertEqual(by_sentence, {"`f-0001`": ("opus", "high"), "`f-0002`": ("opus", "max")},
                         "sonnet's finding goes to opus high, opus's finding to opus max")

    def test_the_verifier_is_given_the_sentence_and_the_artifacts_at_their_locators(self):
        self.verify()
        prompt = next(call.request.prompt for call in self.calls if "`f-0002`" in call.request.prompt)
        self.assertIn("results/baseline/summary.json#auroc_mean", prompt)
        self.assertIn("results/baseline/summary.json#auroc_sd", prompt)
        self.assertNotIn("this path is not there", prompt)

    def test_a_failing_claim_is_journaled_and_filed_as_a_writing_ticket(self):
        def respond(request, message):
            return verdict(passed="`f-0002`" not in request.prompt)

        outcome = self.verify(respond)
        self.assertEqual(len(outcome["failed"]), 1)
        failed = [event["payload"] for event in self.events("verdict") if event["payload"]["pass"] is False]
        self.assertEqual([payload["subject"] for payload in failed], outcome["failed"])
        filed = [fields for fields in tickets.read_tickets(self.project) if fields["kind"] == "writing"]
        self.assertEqual([fields["id"] for fields in filed], outcome["tickets"])
        self.assertEqual(filed[0]["origin"], outcome["failed"][0])
        self.assertEqual(filed[0]["proposed_by"], "verifier")
        self.assertEqual(filed[0]["touches"], [], "REPORT.md is rendered by code; the correction travels in the result")
        _, body = tickets.read_ticket(next(tickets.tickets_dir(self.project).glob("%02d-*.md" % filed[0]["id"])))
        self.assertIn("never a report tag", body, "the M5 run's scope-down findings cited `res:` tags and were refused")
        self.assertIn("The sentence is a finding as its ticket recorded it", body)
        created = self.events("ticket_created")[-1]["payload"]
        self.assertEqual((created["ticket"], created["kind"]), (filed[0]["id"], "writing"))

    def test_a_second_pass_reads_no_claim_twice_and_files_no_second_ticket(self):
        self.verify(lambda request, message: verdict(passed="`f-0002`" not in request.prompt))
        outcome = self.verify(scripted=0)
        self.assertEqual(self.calls, [])
        self.assertEqual(outcome["already_verdicted"], 5)
        self.assertEqual(len([fields for fields in tickets.read_tickets(self.project) if fields["kind"] == "writing"]), 1)

    def test_the_subject_is_the_sentence_with_its_tags(self):
        claim = Claim("It holds.", ("res:t1-a1/x.json#k",), sentence_hash("It holds."), (1,))
        retagged = Claim("It holds.", ("res:t2-a1/x.json#k",), sentence_hash("It holds."), (2,))
        self.assertTrue(claim_subject(claim).startswith("research/REPORT.md#claim-"))
        self.assertNotEqual(claim_subject(claim), claim_subject(retagged))


# --- the verb --------------------------------------------------------------------------------------


class ReportCommandTest(RunCase):
    def run_verb(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with worker.use_fake() as fake:
            for _ in range(6):
                fake.script(respond=Classifier(), role="classifier")
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["report", "--project", str(self.project), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_a_failing_linter_exits_1_and_prints_the_offending_sentences(self):
        self.book.append_record("findings.jsonl", MALFORMED)
        code, out, _ = self.run_verb()
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("malformed_tag", out)
        self.assertIn("Depth alone does not reach the goal.", out)

    def test_a_passing_linter_exits_0(self):
        code, out, _ = self.run_verb("--json")
        self.assertEqual(code, 0)
        outcome = json.loads(out)
        self.assertTrue(outcome["linter_pass"])
        self.assertEqual((outcome["claims"], outcome["tagged"]), (5, 5))

    def test_verify_is_not_run_on_a_report_that_fails_the_linter(self):
        self.book.append_record("findings.jsonl", MALFORMED)
        code, out, _ = self.run_verb("--verify")
        self.assertEqual(code, 1)
        self.assertIn("verifier  not run", out)


class RolesTest(unittest.TestCase):
    def test_the_classifier_reads_nothing_but_its_prompt(self):
        role = worker.read_role("classifier")
        self.assertEqual(role.allowed_tools, [])
        self.assertEqual(role.output_schema, "claim_classes")
        for tool in ("Read", "Bash", "Write", "Skill", "mcp__*"):
            self.assertIn(tool, role.disallowed_tools)
        self.assertFalse(role.may_judge)

    def test_the_writer_is_assigned_writing_tickets_and_judges_nothing(self):
        role = worker.read_role("writer")
        self.assertEqual(role.kinds, ["writing"])
        self.assertFalse(role.may_judge)
        self.assertIn("C8", role.system_prompt)



class TopRungItemTest(RunCase):
    """Decision 16: a ticket the escalation chain left with nowhere to climb says so among the `needs_human` items."""

    def test_the_needs_human_item_names_the_top_rung(self):
        self.book.append_event("ticket_needs_human",
                               {"ticket": 7, "question": "it failed on rung 7, the rung ladder's top rung: no",
                                "reason": "top_rung"}, ticket=7)
        self.render()
        waiting = self.account("Waiting on you")
        self.assertIn("Ticket 7, *Convert the second reference's PDF*, needs a person (at the ladder's top rung):", waiting)


if __name__ == "__main__":
    unittest.main()
