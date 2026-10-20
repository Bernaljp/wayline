"""The numbers check at acceptance (decision 17; ticket 90).

A Type-A function: every number in a finding must match a value at one of its sentence's `res` locators, allowing for
rounding, percents, and the scales 100 and 1000; counts in words and the parameters the spec names are exempt. What
code cannot match goes to a fresh verifier, one per sentence, through the fake launcher; a failure sends the ticket back,
which the conductor's acceptance shows.
"""

import json

from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, hold_the_ladder, patch
from wayline import numbers, worker
from wayline import project as projects
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.worker import Envelope

SUMMARY = {"auroc_mean": 0.8123, "auroc_sd": 0.004, "disagreement": 0.031, "seconds": 1.25, "counts": {"rows": 1200}}


def finding(text, *provenance):
    return {"text": text, "provenance": list(provenance) or ["results/summary.json#auroc_mean"]}


def verdict(passed, text="The artifact holds 0.812, not 0.9."):
    findings = [] if passed else [{"text": text, "locator": "results/summary.json#auroc_mean", "severity": "blocker"}]
    return Envelope(structured_output={"pass": passed, "findings": findings, "question_limit": "Only the numbers of the sentence."})


class NumbersCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "artifacts"
        (self.root / "results").mkdir(parents=True)
        (self.root / "results" / "summary.json").write_text(json.dumps(SUMMARY), encoding="utf-8")
        (self.root / "results" / "table.csv").write_text("split,auroc\nsplit_a,0.79\nsplit_b,0.86\n", encoding="utf-8")
        (self.root / "results" / "log.txt").write_text("epoch 1\nloss: 0.42\nloss: 0.25\n", encoding="utf-8")
        self.read = numbers.reader(self.root)

    def unmatched(self, *findings, exempt=()):
        return [(sentence.text, sentence.unmatched) for sentence in numbers.check(list(findings), self.read, exempt).unmatched]


class MatchTest(NumbersCase):
    def test_a_number_the_artifact_holds_matches_and_one_it_does_not_is_unmatched(self):
        self.assertEqual(self.unmatched(finding("The AUROC is 0.8123.")), [])
        self.assertEqual(self.unmatched(finding("The AUROC is 0.9.")), [("The AUROC is 0.9.", ["0.9"])])

    def test_rounding_percents_and_the_scales_100_and_1000(self):
        for text, locator in (("The AUROC is 0.81.", "auroc_mean"), ("The AUROC is 81.2 percent.", "auroc_mean"),
                              ("The two sources disagree on 3.1% of the rows.", "disagreement"),
                              ("A step takes 1250 ms.", "seconds"), ("The AUROC is 81.", "auroc_mean")):
            with self.subTest(text=text):
                self.assertEqual(self.unmatched(finding(text, "results/summary.json#%s" % locator)), [])
        self.assertEqual(self.unmatched(finding("The AUROC is 0.82.")), [("The AUROC is 0.82.", ["0.82"])],
                         "0.8123 rounds to 0.81, never to 0.82")

    def test_counts_in_words_identifiers_and_the_specs_parameters_are_exempt(self):
        text = "Over three seeds and split_2, R2 holds at a learning rate of 0.001, with an AUROC of 0.812."
        self.assertEqual(self.unmatched(finding(text), exempt={0.001}), [])
        self.assertEqual(self.unmatched(finding(text)), [(text, ["0.001"])])

    def test_every_locator_of_the_sentence_is_read_and_a_nested_key_or_thousands_separator_resolves(self):
        text = "The baseline reaches 0.812, with a standard deviation of 0.004, over 1,200 rows."
        found = finding(text, "results/summary.json#auroc_mean", "results/summary.json#auroc_sd", "results/summary.json#counts.rows")
        self.assertEqual(self.unmatched(found), [])

    def test_a_csv_column_and_a_text_line_range_resolve(self):
        self.assertEqual(self.unmatched(finding("Split B reaches 0.86.", "results/table.csv#auroc")), [])
        self.assertEqual(self.unmatched(finding("The loss ends at 0.25.", "results/log.txt#L3")), [])
        self.assertEqual(self.unmatched(finding("The loss ends at 0.42.", "results/log.txt#L3")), [("The loss ends at 0.42.", ["0.42"])])

    def test_a_sentence_ending_with_its_own_res_tags_is_matched_against_those(self):
        tagged = ("The AUROC is 0.81.{res:t2-a1/results/summary.json#auroc_mean} "
                  "Split B reaches 0.86.{res:t3-a1/results/table.csv#auroc}")
        self.assertEqual(self.unmatched(finding(tagged, "results/log.txt#L1")), [])

    def test_a_locator_that_resolves_to_nothing_leaves_its_numbers_unmatched(self):
        self.assertEqual(self.unmatched(finding("The AUROC is 0.81.", "results/ghost.json#auroc")), [("The AUROC is 0.81.", ["0.81"])])
        self.assertEqual(self.unmatched(finding("The AUROC is 0.81.", "results/summary.json#nothing")), [("The AUROC is 0.81.", ["0.81"])])

    def test_a_tag_naming_a_run_whose_file_the_manifest_no_longer_holds_is_not_read(self):
        tagged = finding("The AUROC is 0.81.{res:t2-a1/results/summary.json#auroc_mean}")
        runs = {"results/summary.json": "t5-a1"}
        self.assertEqual([sentence.unmatched for sentence in numbers.check([tagged], self.read, runs=runs).unmatched], [["0.81"]])
        self.assertEqual(numbers.check([tagged], self.read, runs=runs, own_run="t2-a1").unmatched, [], "the attempt's own run is read")
        self.assertEqual(numbers.check([tagged], self.read, runs={"results/summary.json": "t2-a1"}).unmatched, [])

    def test_a_sentence_tagged_only_with_a_reference_is_not_read_against_the_runs(self):
        cited = finding("Smith reports 0.80 {ref:smith-2020#p3}. Ours is 0.81.{res:t2-a1/results/summary.json#auroc_mean}")
        self.assertEqual([sentence.text for sentence in numbers.check([cited], self.read).sentences],
                         ["Ours is 0.81.{res:t2-a1/results/summary.json#auroc_mean}"])

    def test_the_verifier_is_shown_the_file_code_read(self):
        sentence = numbers.check([finding("The AUROC is 0.9.")], self.read).sentences[0]
        self.assertEqual(sentence.locators, ["%s#auroc_mean" % (self.root / "results" / "summary.json")])

    def test_a_sentence_without_a_number_is_not_read(self):
        self.assertEqual(numbers.check([finding("Interaction terms lift the AUROC.")], self.read).sentences, [])


class SpecParametersTest(ProjectTestCase):
    def test_the_parameters_the_spec_names_are_read_from_its_methods_and_experiments(self):
        project = self.temp / "project"
        projects.init_project(project, harness_root=self.fake_harness(), git=False)
        Ledger(project).write_json("spec.json", {
            "methods": [{"id": "M1", "text": "Train with a learning rate of 0.001 for 40 epochs."}],
            "experiments": [{"id": "E1", "design": "Five seeds at batch size 64."}],
            "claims": [{"id": "C1", "text": "The AUROC passes 0.9."}]})
        self.assertEqual(numbers.spec_parameters(project), {0.001, 40.0, 64.0})


class VerifierTest(NumbersCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)

    def judge(self, *scripted):
        check = numbers.check([finding("The AUROC is 0.9."), finding("Split B reaches 0.95.", "results/table.csv#auroc")], self.read)
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope, role="verifier")
            outcome = numbers.judge(self.project, check, ticket=7, author_model="sonnet", fall_back=False)
            calls = list(fake.calls)
        return outcome, calls

    def test_each_unmatched_sentence_goes_to_a_fresh_verifier_and_a_pass_passes(self):
        outcome, calls = self.judge(verdict(True), verdict(True))
        self.assertEqual(len(calls), 2)
        self.assertEqual([call.kind for call in calls], ["launch", "launch"], "each verdict is a fresh launch, never a resume")
        self.assertIn("The AUROC is 0.9.", calls[0].request.prompt)
        self.assertIn("results/summary.json#auroc_mean", calls[0].request.prompt)
        result = numbers.acceptance_result(outcome)
        self.assertEqual(result["exit_code"], 0, result["tail"])
        verdicts = [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "verdict"]
        self.assertEqual([payload["verdict_type"] for payload in verdicts], ["numbers_match", "numbers_match"])

    def test_a_sentence_passed_at_an_earlier_acceptance_is_not_judged_again(self):
        self.judge(verdict(True), verdict(True))
        outcome, calls = self.judge()
        self.assertEqual(calls, [])
        self.assertEqual(numbers.acceptance_result(outcome)["exit_code"], 0)

    def test_a_verdict_the_gate_refuses_fails_the_check_and_a_closed_window_lists_it(self):
        from unittest import mock
        from wayline import gates
        check = numbers.check([finding("The AUROC is 0.9.")], self.read)
        for raised, code in ((gates.GateError("policy.verifier has no row for sonnet"), 1),
                             (gates.UsageLimited("refused until noon", None), 0)):
            with self.subTest(raised=type(raised).__name__), mock.patch.object(gates, "verdict", side_effect=raised):
                result = numbers.acceptance_result(numbers.judge(self.project, check, ticket=7, author_model="sonnet"))
                self.assertEqual(result["exit_code"], code, result["tail"])
                self.assertIn(str(raised), result["tail"])

    def test_a_failing_verdict_fails_the_check_with_the_sentence_and_why(self):
        outcome, _ = self.judge(verdict(False), verdict(True))
        result = numbers.acceptance_result(outcome)
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("The AUROC is 0.9.", result["tail"])
        self.assertIn("The artifact holds 0.812, not 0.9.", result["tail"])
        self.assertNotIn("Split B reaches 0.95.", result["tail"].split("matched by the verifier")[0])


class AcceptanceTest(ConductorCase):
    """At acceptance in the worktree: a number no locator holds and the verifier does not support sends the ticket back."""

    def setUp(self):
        super().setUp()
        hold_the_ladder(self)
        self.conductor = Conductor(self.project, out=__import__("io").StringIO())

    def run_ticket(self, text, verdicts=()):
        files = {"hello.txt": "hello\nauroc: 0.8123\n"}
        result = done(findings=[{"text": text, "provenance": "hello.txt#auroc"}])
        with worker.use_fake() as fake:
            fake.script(result, patch=patch(files))
            for envelope in verdicts:
                fake.script(envelope, role="verifier")
            drive(self.conductor, waves=2)
        return [event["payload"] for event in self.events("acceptance") if event["payload"]["where"] == "worktree"]

    def test_a_matching_number_passes_with_no_verifier(self):
        accepted = self.run_ticket("The AUROC is 0.81.")
        self.assertTrue(accepted[0]["pass"], accepted)
        self.assertIn(numbers.NUMBERS_CHECK, [entry["cmd"] for entry in accepted[0]["results"]])
        self.assertEqual([event for event in self.events("verdict") if event["payload"]["verdict_type"] == "numbers_match"], [])

    def test_under_cheap_only_no_verifier_launches_and_the_sentence_is_listed(self):
        from types import SimpleNamespace
        from wayline import schedule
        (self.project / "hello.txt").write_text("auroc: 0.8123\n", encoding="utf-8")
        attempt = SimpleNamespace(id=1, number=1, worktree=self.project, tier=SimpleNamespace(model="sonnet"),
                                  result={"findings": [{"text": "The AUROC is 0.9.", "provenance": "hello.txt#auroc"}]})
        self.conductor.action = schedule.CHEAP_ONLY
        with worker.use_fake() as fake:
            (result,) = self.conductor._numbers_check(attempt)
            self.assertEqual(fake.calls, [], "a verdict waits under cheap_only like every other")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("listed, not failed", result["tail"])

    def test_a_number_the_verifier_does_not_support_sends_the_ticket_back(self):
        accepted = self.run_ticket("The AUROC is 0.9.", verdicts=[verdict(False)])
        self.assertFalse(accepted[0]["pass"])
        check = next(entry for entry in accepted[0]["results"] if entry["cmd"] == numbers.NUMBERS_CHECK)
        self.assertEqual(check["exit_code"], 1)
        self.assertIn("The AUROC is 0.9.", check["tail"])
        self.assertNotIn("finding", [event["event"] for event in self.events()], "a ticket sent back files no finding")
