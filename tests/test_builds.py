"""Builds at the order (Implementation Decision 17; ticket 117).

The seams: `builds.take` over a temporary project holding an open paper order, the fake launcher scripting the writer,
both threads of the kill argument, the independent read, the classifier, and the claim verdicts; the conductor at an
order under `autonomous`, read back from the journal it wrote; the journal replayed (`replay`, the account, the tick);
the owner's choice through `wayline paper builds`; and the files code renders from a fixture ledger (`research/paper/`'s
supplement, its responses, and a compilation's checks). What is asserted is what the owner and the next component see.
"""

import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests import machine
from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.spec_table import spec_policy_keys
from tests.test_compilations import CompilationCase
from tests.test_drawings import DrawingRunCase
from tests.test_paper import PaperCase, Writer, asked
from tests.test_paper_figures import PlannedFigureCase
from wayline import account, batches, builds, cli, compilations, objectives, paper, paper_figures, replay, sections, tick, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.worker import Envelope

MEMO = "What is the single strongest case for rejecting this work?"
ADJUDICATION = "Does the rejection memo hold, point by point, against the artifacts?"
CLAIM = "Do the cited artifacts, at their locators, support this sentence"
TAGGED = "The error rises to 0.12 with the noise {res:t2-a1/results/summary.json#rmse}."


def answered(passed, text="The Results claim more than the findings carry.", locator="research/paper/results.md:3"):
    return Envelope(session_id="v-%s" % ("pass" if passed else "fail"), model="claude-opus-5-5",
                    structured_output={"pass": passed, "findings": [] if passed else [{"text": text, "locator": locator, "severity": "major"}],
                                       "question_limit": "the paper as built"})


class Verifier:
    """The fake verifier: the kill argument fails on the builds in `kill`, the read on those in `read`, and a claim verdict
    on a sentence holding a word of `claims`; everything else passes. Keeps every prompt."""

    def __init__(self, kill=(), read=(), claims=()):
        self.kill, self.read, self.claims, self.prompts = set(kill), set(read), list(claims), []

    def __call__(self, request, message):
        prompt = request.prompt
        self.prompts.append(prompt)
        found = re.search(r"research/paper#v\d+-b(\d+)", prompt)
        build = int(found.group(1)) if found else 0
        if CLAIM in prompt:
            return answered(not any(word in prompt for word in self.claims), "The summary holds 0.12 on one seed only.",
                            "results/summary.json#rmse")
        if MEMO in prompt or ADJUDICATION in prompt:
            return answered(build not in self.kill, "The noise claim overreaches.")
        return answered(build not in self.read, "The Methods omit the noise model.")


def classify_all(texts):
    from wayline import provenance
    classes = provenance.read_claims_cache(Ledger(classify_all.project))
    classes.update({provenance.sentence_hash(text): provenance.CLAIM for text in texts})
    Ledger(classify_all.project).write_json(provenance.CLAIMS_CACHE, {"schema_version": 1, "classes": classes})
    return classes


class BuildCase(PaperCase):
    """`PaperCase`'s project with the general report's last kill argument failed, and a paper order open."""

    def setUp(self):
        super().setUp()
        self.ledger.append_event("verdict", {"subject_kind": "report", "subject": "research/REPORT.md#kill-0123", "verdict_type": "kill_argument",
                                             "pass": False, "session_id": "s-report", "model": "opus",
                                             "findings": [{"text": "The report's noise claim overreaches.", "locator": "REPORT.md:3",
                                                           "severity": "major"}]})
        self.writers = []

    def open(self):
        payload = paper.open_order(self.project)
        if payload is None:
            paper.order(self.project, start=None)
            payload = paper.open_order(self.project)
        if payload.get("batch") and batches.read_batch(self.project, payload["batch"])["status"] == "open":
            batches.take_defaults(self.project, payload["batch"])
        return payload

    def take(self, verifier, change=None, scripted=12):
        """One build: the writer when a composition is owed, then the gates; returns `builds.take`'s outcome."""
        payload = self.open()
        writer = Writer(self.project, change)
        self.writers.append(writer)
        classify_all.project = self.project
        with worker.use_fake() as fake:
            fake.script(respond=writer, role="writer")
            fake.script(respond=writer, role="writer")
            for _ in range(scripted):
                fake.script(respond=verifier, role="verifier")
            try:
                return builds.take(self.project, payload, classifier=classify_all)
            finally:
                self.calls = list(fake.calls)

    def actions(self):
        return [(item["action"], item.get("build")) for item in self.orders()]


class PassingBuildTest(BuildCase):
    def setUp(self):
        super().setUp()
        self.verifier = Verifier()
        self.outcome = self.take(self.verifier)

    def test_the_build_runs_the_kill_argument_then_the_read_then_the_sampled_verdicts_and_passes(self):
        self.assertEqual(self.outcome["outcome"], "passed")
        self.assertEqual(self.actions(), [("ordered", None), ("composed", 1), ("passed", 1)])
        self.assertIsNone(paper.open_order(self.project), "a build that passed closes the order")
        verdicts = [(event["payload"]["subject_kind"], event["payload"]["verdict_type"]) for event in self.journal()
                    if event["event"] == "verdict" and event["payload"]["subject"].startswith("research/paper#")]
        self.assertEqual(verdicts, [("paper", "kill_argument"), ("paper", "paper_read")], "the memo is no verdict; the read is the one")
        roles = [call.request.role for call in self.calls]
        self.assertEqual(roles, ["writer", "verifier", "verifier", "verifier"])
        self.assertIn(MEMO, self.verifier.prompts[0])
        self.assertIn(ADJUDICATION, self.verifier.prompts[1])
        self.assertIn(builds.READ_QUESTION, self.verifier.prompts[2])
        for prompt in self.verifier.prompts:
            self.assertIn("research/paper/results.md", prompt)

    def test_the_kill_argument_is_told_the_general_reports_last_verdict(self):
        for prompt in self.verifier.prompts[:2]:
            self.assertIn("# What you are told", prompt)
            self.assertIn("The general report's last verdict", prompt)
            self.assertIn("research/REPORT.md#kill-0123", prompt)
            self.assertIn("The report's noise claim overreaches.", prompt)
        self.assertNotIn("# What you are told", self.verifier.prompts[2], "the read is told nothing beside its paths")

    def test_paper_md_and_paper_json_list_each_gate(self):
        report = self.read("PAPER.md")
        self.assertNotIn("not yet gated", report)
        for words in ("## Builds and their gates", "### Build 1: passed", "- the kill argument: passed (verifier session v-pass",
                      "- the independent read: passed", "- the sampled verdicts on claims never sampled: passed",
                      "The paper passed at build 1."):
            self.assertIn(words, report)
        record = json.loads(self.read("paper.json"))
        self.assertTrue(record["gated"])
        self.assertEqual(record["outcome"], "passed")
        self.assertEqual([entry["gate"] for entry in record["builds"][0]["gates"]], ["kill_argument", "paper_read", "sampled_verdicts"])

    def test_no_gate_files_a_ticket(self):
        self.assertEqual(tickets.read_tickets(self.project), [])


class FailThenPassTest(BuildCase):
    def setUp(self):
        super().setUp()
        self.verifier = Verifier(kill={1}, read={1})
        self.first = self.take(self.verifier)
        self.second = self.take(self.verifier)

    def test_a_failed_build_sends_its_points_to_a_fresh_writer_session_with_no_ticket(self):
        self.assertEqual(self.first["outcome"], "next")
        self.assertEqual(self.first["points"], ["The noise claim overreaches. (research/paper/results.md:3)",
                                                "The Methods omit the noise model. (research/paper/results.md:3)"])
        self.assertEqual(self.second["outcome"], "passed")
        self.assertEqual(self.actions(), [("ordered", None), ("composed", 1), ("gated", 1), ("composed", 2), ("passed", 2)])
        gated = self.orders()[2]
        self.assertEqual(gated["points"], self.first["points"])
        [writer] = [call for call in self.calls if call.request.role == "writer"]
        self.assertIsNone(writer.session_id, "a fresh session, never a resume of the last build's writer")
        prompt = self.writers[1].prompts[0]
        self.assertIn("This is build 2 of this order", prompt)
        self.assertIn("The noise claim overreaches.", prompt)
        self.assertIn("research/paper/", prompt)
        self.assertEqual(asked(prompt), list(paper.WRITTEN), "every part is written again")
        self.assertEqual(tickets.read_tickets(self.project), [], "no ticket carries the points")

    def test_the_build_keeps_its_version_and_paper_md_lists_both_builds(self):
        record = json.loads(self.read("paper.json"))
        self.assertEqual(record["version"], 1)
        self.assertFalse((self.project / "research" / "paper" / "earlier").exists(), "a build freezes nothing")
        self.assertEqual([(entry["build"], entry["passed"]) for entry in record["builds"]], [(1, False), (2, True)])
        report = self.read("PAPER.md")
        self.assertIn("### Build 1: failed", report)
        self.assertIn("  - standing: The noise claim overreaches. (research/paper/results.md:3)", report)
        self.assertIn("### Build 2: passed", report)


class NotPassedTest(BuildCase):
    def setUp(self):
        super().setUp()
        self.verifier = Verifier(kill={1, 2, 3, 4, 5, 6})
        self.outcomes = [self.take(self.verifier) for _ in range(3)]

    def test_three_failed_builds_mark_the_paper_not_passed_and_close_the_order(self):
        self.assertEqual([item["outcome"] for item in self.outcomes], ["next", "next", "not_passed"])
        self.assertEqual(self.actions()[-1], ("not_passed", 3))
        self.assertIsNone(paper.open_order(self.project))
        record = json.loads(self.read("paper.json"))
        self.assertEqual(record["outcome"], "not_passed")
        report = self.read("PAPER.md")
        self.assertIn("The paper is **not passed**", report)
        self.assertIn("three more builds, keep it as it is, or the points as objectives", report)

    def test_the_account_waits_on_the_owners_choice(self):
        [line] = builds.waiting_lines(self.project)
        self.assertIn("is not passed", line)
        self.assertIn("Choose three more builds, keep it as it is, or the points as objectives", line)

    def verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(paper, "_start_conductor", lambda project: "started"):
            code = cli.main(["paper", "builds", *args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def test_three_more_builds_reopen_the_order_from_the_points_standing(self):
        code, out, err = self.verb("more")
        self.assertEqual(code, 0, err)
        self.assertIn("reopened", out)
        self.assertEqual(paper.open_order(self.project)["order"], 1)
        self.assertEqual(builds.waiting_lines(self.project), [])
        outcomes = [self.take(self.verifier) for _ in range(3)]
        self.assertEqual([item["build"] for item in outcomes], [4, 5, 6])
        self.assertIn("The noise claim overreaches.", self.writers[3].prompts[0], "build 4 is given the points standing")
        self.assertEqual(outcomes[-1]["outcome"], "not_passed")

    def test_the_points_as_objectives_are_the_owners_open_objectives(self):
        before = len(objectives.read_objectives(self.project))
        code, out, _ = self.verb("objectives")
        self.assertEqual(code, 0)
        added = objectives.read_objectives(self.project)[before:]
        self.assertEqual([item["text"] for item in added], ["The noise claim overreaches. (research/paper/results.md:3)"])
        self.assertEqual(self.orders()[-1]["choice"], "objectives")
        self.assertIsNone(paper.open_order(self.project))
        self.assertEqual(builds.waiting_lines(self.project), [])

    def test_keeping_it_closes_the_choice_and_a_second_choice_is_refused(self):
        self.assertEqual(self.verb("keep")[0], 0)
        self.assertEqual(builds.waiting_lines(self.project), [])
        code, _, err = self.verb("more")
        self.assertEqual(code, 2)
        self.assertIn("no paper waits on a choice", err)


class SampledTest(BuildCase):
    def tagged(self, found, number):
        found["results"] = found["results"] + "\n\n" + TAGGED
        return found

    def test_the_sampled_verdicts_take_only_claims_never_sampled_and_a_failing_claim_is_a_point(self):
        verifier = Verifier(claims=("0.12",))
        first = self.take(verifier, change=self.tagged)
        self.assertEqual(first["outcome"], "next")
        self.assertIn('the claim "The error rises to 0.12 with the noise." is not supported: The summary holds 0.12 on one seed only. (results/summary.json#rmse)',
                      " ".join(first["points"]))
        claims = [prompt for prompt in verifier.prompts if CLAIM in prompt]
        self.assertEqual(len(claims), 1)
        second = self.take(Verifier(), change=self.tagged)
        self.assertEqual(second["outcome"], "passed", "the same claim, sampled once, is not drawn again")
        self.assertEqual(tickets.read_tickets(self.project), [])


class InheritedCase(BuildCase):
    """An inherited result verified and narrowed, another unverifiable, and their record in `research/verifications.json`."""

    def setUp(self):
        super().setUp()
        self.claim = self.inherited("Earlier noise study", "Noise inflates the error tenfold. {doc:D1#p1.s1}", "D1#p1.s1")["id"]
        self.narrowed = self.finding("Earlier noise study", text="Noise inflates the error threefold.", replaces=self.claim,
                                     evidence="narrows")["id"]
        self.gone = sections.add_passage(self.ledger, "results", "Old SINDy cases", "SINDy recovers the cubic. {doc:D1#p2.s1}",
                                         by="document:D1", doc="D1#p2.s1", standing="unverifiable", reason="the data are gone")["id"]
        self.ledger.write_json("verifications.json", {"results": [
            {"heading": "Earlier noise study", "claims": [self.claim], "standing": "verified", "reason": None, "contradictions": [],
             "verdicts": [{"ticket": 5, "route": "reproduced", "commit": None, "substitute": "the 2019 sample",
                           "claims": [{"claim": self.claim, "evidence": "narrows", "by": self.narrowed}]}]},
            {"heading": "Old SINDy cases", "claims": [self.gone], "standing": "unverifiable", "reason": "the data are gone",
             "verdicts": [], "contradictions": []}], "material": [], "reads": []}, schema="verification")

    def routes(self, found, number):
        found["methods"] = (found["methods"] or "") + "\n\nThe inherited results were reproduced from the original code."
        return found


class InheritedTableTest(InheritedCase):
    def test_the_supplement_carries_codes_table_of_every_inherited_result(self):
        self.take(Verifier(), change=self.routes)
        supplement = self.read("supplement.md")
        self.assertIn(builds.TABLE_MARK, supplement)
        self.assertIn("**Supplementary Table S1.** The inherited results", supplement)
        self.assertIn("| Inherited result | Verdict | Route | Narrowed wording | Reasons |", supplement)
        self.assertIn("| Earlier noise study | verified: %s narrows | reproduced | %s: Noise inflates the error threefold. | "
                      "on substitute data: the 2019 sample |" % (self.claim, self.narrowed), supplement)
        self.assertIn("| Old SINDy cases | unverifiable | none | none | the data are gone |", supplement)

    def test_the_writer_is_told_the_table_and_writes_one_methods_paragraph_naming_the_routes(self):
        self.take(Verifier(), change=lambda found, number: self.routes(found, number) if number > 1 else found)
        prompt = self.writers[0].prompts[0]
        self.assertIn("Supplementary Table S1 is code's", prompt)
        self.assertIn("Add one Methods paragraph naming the routes the verifications took, each by its name: reproduced.", prompt)
        self.assertIn("it does not name reproduced", self.writers[0].prompts[1], "a Methods with no routes goes back once")
        self.assertIn("reproduced", self.read("methods.md"))

    def test_an_unverifiable_claim_left_out_is_in_no_part_and_listed(self):
        def carries(found, number):
            found = self.routes(found, number)
            if number == 1:
                found["results"] += "\n\nSINDy recovers the cubic {doc:D1#p2.s1}."
            return found
        self.take(Verifier(), change=carries)
        self.assertIn("results carries %s, an unverifiable claim the order left out" % self.gone, self.writers[0].prompts[1])
        for part in ("results", "supplement", "discussion"):
            self.assertNotIn("{doc:D1#p2.s1}", self.read("%s.md" % part))
        self.assertIn("- %s, an unverifiable claim: unverifiable (the data are gone), and the order left it out" % self.gone,
                      self.read("PAPER.md"))

    def test_an_unverifiable_claim_the_batch_kept_says_it_is_not_verified_and_why(self):
        payload = paper.order(self.project, start=None)
        batch = batches.read_batch(self.project, payload["batch"])
        item = next(entry["id"] for entry in batch["items"] if entry["ref"] == "unverifiable:%s" % self.gone)
        batches.mark(self.project, payload["batch"], item, "keep, not verified")

        def kept(found, number):
            found = self.routes(found, number)
            found["results"] += ("\n\nSINDy recovers the cubic {doc:D1#p2.s1}." if number == 1 else
                                 "\n\nSINDy recovered the cubic, not verified here because the data are gone {doc:D1#p2.s1}.")
            return found
        self.take(Verifier(), change=kept)
        self.assertIn("the sentence carrying %s ({doc:D1#p2.s1}) does not say it is not verified" % self.gone, self.writers[0].prompts[1])
        self.assertIn("keep %s, stated as not verified, with why: the data are gone" % self.gone, self.writers[0].prompts[0])
        self.assertIn("not verified here because the data are gone {doc:D1#p2.s1}", self.read("results.md"))


class ConcernsTest(BuildCase):
    def setUp(self):
        super().setUp()
        self.concerns({"said": "The noise model is never stated.", "place": "order"},
                      {"said": "Run the fit on real data.", "place": "objectives", "status": "answered",
                       "answer": "The fit was run on the 2019 field data.", "objectives": ["O1"]},
                      {"said": "Cite the older fits.", "place": None, "status": "declined", "reason": "they fit another model"})
        self.ledger.write_json("documents.json", {"documents": [{"id": "D2", "kind": "critique", "title": "Referee report 1"},
                                                               {"id": "D3", "kind": "critique", "title": "Referee report 2"}]})

    def answers(self, found, number):
        found["concerns"] = [{"id": "K1", "answer": "The Methods state the Gaussian noise model."}]
        return found

    def test_the_concerns_for_the_order_reach_the_writer_and_its_answers_the_record(self):
        self.take(Verifier(), change=self.answers)
        prompt = self.writers[0].prompts[0]
        self.assertIn("## The concerns kept for the order", prompt)
        self.assertIn("- K1: The noise model is never stated.", prompt)
        self.assertNotIn("Run the fit on real data.", prompt.split("## The concerns kept for the order")[1])
        self.assertEqual(json.loads(self.read("paper.json"))["concerns"], [{"id": "K1", "answer": "The Methods state the Gaussian noise model."}])

    def test_one_response_per_critique_lays_out_each_point_verbatim_with_its_answer(self):
        self.take(Verifier(), change=self.answers)
        folder = self.project / "research" / "paper" / "response"
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["D2.md", "D3.md"])
        response = (folder / "D2.md").read_text(encoding="utf-8")
        for words in ("# Response to D2, Referee report 1", "It is never sent.",
                      "## Point 1 (K1, D2#p1)", "> The noise model is never stated.", "**Answer.** The Methods state the Gaussian noise model.",
                      "## Point 2 (K2, D2#p2)", "> Run the fit on real data.", "**Answer.** The fit was run on the 2019 field data.",
                      "## Point 3 (K3, D2#p3)", "> Cite the older fits.", "**Answer.** Declined: they fit another model"):
            self.assertIn(words, response)
        self.assertIn("No point of this critique became a concern.", (folder / "D3.md").read_text(encoding="utf-8"))

    def test_a_concern_the_writer_names_that_is_not_kept_for_the_order_goes_back(self):
        def wrong(found, number):
            found["concerns"] = [{"id": "K2" if number == 1 else "K1", "answer": "Answered."}]
            return found
        self.take(Verifier(), change=wrong)
        self.assertIn("concerns: K2 is no concern kept for the order (K1)", self.writers[0].prompts[1])

    def test_the_compilations_checks_carry_each_concern_for_the_order(self):
        record = {"concerns": [{"id": "K1", "answer": "The Methods state it."}]}
        [check] = builds.concern_checks(self.project, record)
        self.assertEqual((check["check"], check["level"]), ("concern", "ok"))
        self.assertIn("K1, kept for the paper order", check["message"])
        [check] = builds.concern_checks(self.project, {"concerns": []})
        self.assertEqual(check["level"], "fail")
        self.assertIn("the paper does not say how it answers it", check["message"])


class ConcernsAtTheFigureTest(PlannedFigureCase):
    def test_the_concerns_for_the_order_reach_the_figure_finish(self):
        self.concerns({"said": "Show the spread, not only the mean.", "place": "order"})
        plan = paper_figures.build(self.project)
        request = paper_figures.request_for(self.project, plan, self.figure(plan, "F1"))
        self.assertEqual(request["change_requests"], [{"id": "K1", "text": "Show the spread, not only the mean.", "from": "paper"}])
        from tests.test_paper_figures import passing_checks, verdict
        from wayline import figure_role
        with worker.use_fake() as fake:
            fake.script(respond=self.finisher(), role="figure-designer")
            fake.script(verdict(), role="verifier")
            result, reason = figure_role.make(self.project, request, checks=passing_checks, autonomy="checkpoints")
        self.assertEqual(result["status"], "verified", reason)
        self.assertIn("- `K1`: Show the spread, not only the mean.", self.prompts[0])


class CompilationConcernsTest(CompilationCase):
    """A compilation of the composed fixture paper, with one concern kept for the order."""

    def test_a_compilation_checks_each_concern_for_the_order_against_the_writers_answers(self):
        self.book.write_json("concerns.json", {"concerns": [{
            "id": "K1", "sources": [{"critique": "D2", "locator": "D2#p1", "text": "The noise model is never stated."}],
            "targets": [], "place": "order", "objectives": [], "status": "open", "answer": None, "reason": None, "proposed": None,
            "returned": None, "sorted_by": "owner"}], "split": []}, schema="concern")
        self.retry()
        made = compilations.compile_paper(self.project, None, tools=self.tools, run=self.run)
        [check] = [item for item in made["checks"] if item["check"] == "concern"]
        self.assertEqual(check["level"], "fail")
        self.assertIn("K1, kept for the paper order (The noise model is never stated.): the paper does not say how it answers it",
                      check["message"])
        record = paper.read_record(self.project)
        record["concerns"] = [{"id": "K1", "answer": "The Methods state the Gaussian noise model."}]
        self.book.write_json("paper/paper.json", record, schema="paper")
        made = compilations.compile_paper(self.project, None, tools=self.tools, run=self.run)
        [check] = [item for item in made["checks"] if item["check"] == "concern"]
        self.assertEqual(check["level"], "ok")
        stored = json.loads(self.text("plain", "compilation.json"))
        self.assertIn(check, stored["checks"])


class PolicyTest(BuildCase):
    def test_the_orders_builds_are_a_policy_key_with_its_row_in_decision_14(self):
        policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["paper"], {"builds": 3})
        self.assertIn("paper.builds", spec_policy_keys(SPEC_PATH))
        self.assertEqual(builds.allowed(policy), 3)
        self.assertEqual(builds.allowed({"paper": {"builds": 1}}), 1)

    def test_a_policy_of_one_build_marks_a_failed_first_build_not_passed(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness.setdefault("policy", {})["paper"] = {"builds": 1}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(self.take(Verifier(kill={1}))["outcome"], "not_passed")


class ReplayTest(BuildCase):
    """The journal of a paper not passed under `autonomous`, replayed by what reads it."""

    def setUp(self):
        super().setUp()
        self.autonomy("autonomous")
        verifier = Verifier(kill={1, 2, 3})
        for _ in range(3):
            self.take(verifier)
        self.events = self.journal()

    def test_the_view_has_no_order_open_and_the_tick_relaunches_none_for_it(self):
        self.assertIsNone(replay.replay(self.events).paper_order)
        policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        reason, why = tick.relaunch_decision(self.project, self.ledger, policy, None, 0)
        self.assertIsNone(reason)

    def test_the_account_lists_it_under_waiting_on_you(self):
        [line] = builds.waiting_lines(self.events)
        self.assertIn("is not passed: build 3 left 1 point(s) standing", line)
        waiting = account.account_view(self.project, full=False)
        self.assertIn(line[2:80], json.dumps(waiting))

    def test_three_more_builds_replay_as_the_order_reopened_and_the_tick_relaunches_for_it(self):
        builds.choose(self.project, "more", start=None)
        view = replay.replay(self.journal())
        self.assertEqual(view.paper_order["order"], 1)
        self.assertTrue(view.paper_order["reopened"])
        policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        reason, _ = tick.relaunch_decision(self.project, self.ledger, policy, None, 0)
        self.assertIn("paper order 1 is open", reason)
        self.assertEqual(builds.progress(self.journal(), view.paper_order)["build"], 4)


class ConductorTest(DrawingRunCase):
    """The conductor at an order under `autonomous` whose three builds fail: read back from the journal it wrote."""

    def setUp(self):
        super().setUp()
        path = self.project / "harness.json"
        harness = json.loads(path.read_text(encoding="utf-8"))
        harness["autonomy"] = "autonomous"
        path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "autonomous",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "objectives_closed"})
        paper.order(self.project, start=None, by="decider")

    def test_three_failed_builds_stop_the_paper_under_waiting_on_you_and_the_run_ends_as_it_had(self):
        verifier = Verifier(kill={1, 2, 3})
        notified = []
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            for _ in range(3):
                fake.script(respond=Writer(self.project), role="writer")
            for _ in range(9):
                fake.script(respond=verifier, role="verifier")
            driven = Conductor(self.project, out=io.StringIO())
            driven.readings = machine.recorded
            driven.drawing_python = sys.executable
            driven.notify = lambda *arguments: notified.append(arguments)
            self.addCleanup(driven.settle, 30)
            last = None
            for _ in range(20):
                last = driven.wave()
                driven.settle()
                if last.ended:
                    break
        actions = [(event["payload"]["action"], event["payload"].get("build")) for event in self.events("paper_order")]
        self.assertEqual(actions, [("ordered", None), ("composed", 1), ("gated", 1), ("composed", 2), ("gated", 2),
                                   ("composed", 3), ("not_passed", 3)])
        self.assertTrue(last.ended)
        self.assertEqual(last.reason, "objectives_closed")
        self.assertIn('waits under "Waiting on you"', driven.out.getvalue())
        self.assertEqual([item for item in notified if "not passed" in str(item)], [], "under autonomous nothing is asked")
        self.assertEqual(len(builds.waiting_lines(self.project)), 1)
        self.assertTrue((self.project / "research" / "paper" / "compilations" / "plain" / "compilation.json").is_file(),
                        "the paper not passed is compiled all the same")


class ChangelogTest(BuildCase):
    def test_the_changelog_names_the_builds_under_unreleased(self):
        changelog = (HARNESS_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Builds at the order (ticket 117", unreleased)


if __name__ == "__main__":
    import unittest
    unittest.main()
