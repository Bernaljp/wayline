"""The paper order and the paper's parts (Implementation Decision 17; ticket 115).

The seams: `wayline paper` and `paper.order` over a temporary project, whose records go in through the ledger calls their
own tickets built (objectives, findings, passages, concerns, contradictions, batches); the fake launcher standing in for
the writer's one session; and the conductor, whose rest point at an order is read back from the journal it wrote. What
is asserted is what the owner and the next component see: the card, the journal, the batch, and the files under
`research/paper/`.
"""

import io
import json
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests import machine
from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.spec_table import spec_verbs
from tests.test_drawings import DrawingRunCase
from tests.test_inherited import InheritedCase
from tests.test_documents import MIDWAY
from tests.test_outline import NOISE, OutlineCase
from wayline import batches, cli, outline, paper, replay, sections, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.worker import Envelope

STATE = "Polynomial fits are standard {ref:doi:10.1000/never-found}."
FIT = "We fit the phase by least squares."
LIMITS = "The noise model is Gaussian."


def asked(prompt):
    """The parts the writer's prompt asks for."""
    found = re.search(r"^The parts to write now: (.*)\.$", prompt, re.M)
    return [part.strip() for part in found.group(1).split(",")] if found and found.group(1) != "none" else []


def answer_for(structure, parts, **override):
    """The writer's answer: each asked part with every heading of the outline, in order, carrying its id; null otherwise."""
    texts = {part: "\n\n".join("## %s {#%s}\n\nWhat %s says, in prose." % (entry["heading"], entry["id"], entry["id"])
                               for entry in structure[part]) for part in outline.PAPER_PARTS}
    found = {"titles": ["Noise and the fit", "How noise bends a polynomial fit", "Fits under noise"],
             "abstract": "We measured how noise changes the fit.", "tables": [{"id": "T1", "caption": "The errors by noise.",
                                                                                "csv": "noise,rmse\n0.1,0.12\n"}],
             "alternatives": [], "proposals": ["Put Limits before the Results' discussion."],
             "left_out": [{"what": "the older fits", "why": "no passage carries them"}], "notes": "Read the Methods first."}
    found.update(texts)
    found.update(override)
    for part in paper.WRITTEN:
        if part not in parts:
            found["titles" if part == "title" else part] = [] if part == "title" else None
    if "results" not in parts:
        found["tables"] = []
    return found


def close_as_passed(project, payload):
    """Close the order as its builds would once they passed: these tests are of the composition, and the builds' gates are
    ticket 117's (`tests/test_builds.py`)."""
    Ledger(project).append_event("paper_order", {"order": payload["order"], "action": "passed", "by": payload.get("by") or "owner",
                                                 "build": 1})


def gates_pass(fake):
    """A build's three gates, each a verifier session that passes: the memo, its adjudication, and the read. A paper whose
    sentences carry no tag samples no claim."""
    for _ in range(3):
        fake.script(Envelope(structured_output={"pass": True, "findings": [], "question_limit": "the paper as built"}), role="verifier")


class Writer:
    """The fake writer: answers each call from the outline as it stands, through `change` when given; keeps its prompts."""

    def __init__(self, project, change=None):
        self.project, self.change, self.prompts = project, change, []

    def __call__(self, request, message):
        self.prompts.append(request.prompt if message is None else message)
        parts = asked(request.prompt)
        found = answer_for(outline.paper_structure(self.project), parts)
        if self.change is not None:
            found = self.change(found, len(self.prompts))
        return Envelope(structured_output=found, usage={"input_tokens": 1200, "output_tokens": 800}, num_turns=4, duration_ms=9000)


class PaperCase(OutlineCase):
    """A project with an objective, one result of its own evidence, and a passage in each written section."""

    def setUp(self):
        super().setUp()
        self.o1 = self.objective(NOISE)
        self.finding("The error grows with the noise", objectives_=[self.o1])
        self.passage("introduction", "State of the art", STATE)
        self.owners = self.passage("methods", "Fitting", FIT, by="owner")["id"]
        self.passage("discussion", "Limits", LIMITS)
        self.started = []

    def start(self, project):
        self.started.append(project)
        return "started"

    def autonomy(self, level):
        path = self.project / "harness.json"
        harness = json.loads(path.read_text(encoding="utf-8"))
        harness["autonomy"] = level
        path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def verb(self, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(paper, "_start_conductor", self.start):
            if stdin is not None:
                with mock.patch("sys.stdin", io.StringIO(stdin)):
                    code = cli.main(["paper", *args, "--project", str(self.project)])
            else:
                code = cli.main(["paper", *args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def journal(self):
        return self.ledger.read_events()[0]

    def orders(self):
        return [event["payload"] for event in self.journal() if event["event"] == "paper_order"]

    def compose(self, change=None, order=None, close=True):
        """Order (when none is open) and compose with the fake writer, taking the batch's defaults first; the order is then
        closed as passed unless `close` is false (`close_as_passed`)."""
        payload = paper.open_order(self.project)
        if payload is None:
            paper.order(self.project, start=None)
            payload = paper.open_order(self.project)
        if payload.get("batch"):
            batches.take_defaults(self.project, payload["batch"])
        self.writer = Writer(self.project, change)
        with worker.use_fake() as fake:
            fake.script(respond=self.writer, role="writer")
            fake.script(respond=self.writer, role="writer")
            try:
                record = paper.compose(self.project, payload)
            finally:
                self.calls = list(fake.calls)
        if close:
            close_as_passed(self.project, payload)
        return record

    def read(self, name):
        return (self.project / "research" / "paper" / name).read_text(encoding="utf-8")


class CardTest(PaperCase):
    def setUp(self):
        super().setUp()
        self.ledger.append_event("verdict", {"subject_kind": "report", "subject": "research/REPORT.md#v3", "verdict_type": "kill_argument",
                                             "pass": False, "session_id": "s", "model": "opus",
                                             "findings": [{"text": "The noise claim overreaches.", "locator": "REPORT.md:3"}]})
        self.concerns({"said": "Cite the older fits.", "place": "order"})

    def test_the_card_lists_the_readiness_and_the_cost_and_launches_nothing(self):
        with worker.use_fake() as fake:
            code, out, _ = self.verb()
            self.assertEqual(fake.calls, [], "the card is code's: no model is called")
        self.assertEqual(code, 0)
        for words in ("Open objectives: %s: %s" % (self.o1, NOISE), "The outline's gaps", "kill argument",
                      "standing: The noise claim overreaches.", "Results changed since their last drawing", "R1",
                      "Unresolved references", "Concerns for the order", "K1: Cite the older fits.", "research/OUTLINE.md",
                      "Front matter not given yet", "$35 to $40", "$10 more", "Confirm: wayline paper --yes"):
            self.assertIn(words, out)

    def test_not_now_does_nothing(self):
        before = self.journal()
        self.verb()
        self.verb("--json")
        self.assertEqual(self.journal(), before)
        self.assertEqual(batches.read_batches(self.project), [])
        self.assertEqual(tickets.read_tickets(self.project), [], "no decision ticket opens")

    def test_the_card_as_json_carries_each_readiness_item(self):
        _, out, _ = self.verb("--json")
        found = json.loads(out)
        self.assertEqual([item["key"] for item in found["readiness"]],
                         ["objectives", "gaps", "kill", "changed", "inherited", "contradictions", "references", "concerns", "front",
                          "outline"])
        self.assertFalse(found["blocks"])
        self.assertEqual(found["main_results"], 1)


class OrderTest(PaperCase):
    def setUp(self):
        super().setUp()
        self.claim = self.inherited("Earlier noise study", "Noise inflates the error.", "D1#p1.s1")["id"]
        self.other = self.inherited("Earlier noise study", "Noise inflates the error tenfold.", "D1#p1.s2")["id"]
        self.gone = sections.add_passage(self.ledger, "results", "Old SINDy cases", "SINDy recovers the cubic.", by="document:D1",
                                         doc="D1#p2.s1", standing="unverifiable", reason="the data are gone")["id"]
        self.contradiction(self.claim, self.other, "Earlier noise study")
        self.merges = batches.open_batch(self.project, "outline_proposals", "Merges", [{"ref": "R1+R2", "text": "Merge R1 and R2?",
                                                                                         "default": "decline"}])["id"]

    def test_the_owners_confirm_journals_the_order_and_asks_one_batch_with_defaults(self):
        code, out, err = self.verb("--yes")
        self.assertEqual(code, 0, err)
        [made] = self.orders()
        self.assertEqual((made["order"], made["action"], made["by"], made["run"]), (1, "ordered", "owner", "stopped"))
        batch = batches.read_batch(self.project, made["batch"])
        self.assertEqual(batch["kind"], "paper_order")
        by_ref = {item["ref"]: item for item in batch["items"]}
        contradiction = by_ref["contradiction:%s+%s" % (self.claim, self.other)]
        self.assertEqual(contradiction["marks"], ["the first", "the second", "a typo, fix it"])
        self.assertEqual(by_ref["unverifiable:%s" % self.gone]["default"], "leave out")
        self.assertIn("the data are gone", by_ref["unverifiable:%s" % self.gone]["text"])
        reference = next(ref for ref in by_ref if ref.startswith("reference:"))
        self.assertEqual((by_ref[reference]["marks"], by_ref[reference]["default"]), (["hand over", "drop", "to be resolved"], "to be resolved"))
        self.assertEqual(by_ref["outline:%s#1" % self.merges]["default"], "decline")
        self.assertEqual(by_ref[paper.UNCHECKED_REF]["default"], "keep as stated", "nothing inherited is verified yet")
        self.assertTrue(all(item["default"] for item in batch["items"]))
        _, settled = batches.take_defaults(self.project, made["batch"])
        self.assertEqual(len(settled), len(batch["items"]), "take all defaults is one answer")
        self.assertEqual(self.started, [self.project.resolve()], "no conductor ran, so the order started one")
        self.assertIn("paper order 1 made", out)
        self.assertEqual(tickets.read_tickets(self.project), [], "no decision ticket")

    def test_a_contradiction_that_differs_only_in_a_number_suggests_a_typo(self):
        first = self.inherited("Rates", "The rate is 10 Hz.", "D1#p3.s1")["id"]
        second = self.inherited("Rates", "The rate is 100 Hz.", "D1#p3.s2")["id"]
        self.contradiction(first, second, "Rates")
        items = {item["ref"]: item for item in paper.batch_items(self.project)}
        self.assertEqual(items["contradiction:%s+%s" % (first, second)]["default"], "a typo, fix it")

    def test_under_autonomous_no_batch_is_asked(self):
        self.autonomy("autonomous")
        paper.order(self.project, start=None)
        self.assertIsNone(self.orders()[0]["batch"])
        self.assertEqual(batches.read_batches(self.project, status="open"), [batches.read_batch(self.project, self.merges)])

    def test_under_autonomous_codes_defaults_leave_the_outlines_proposals_for_the_decider(self):
        self.autonomy("autonomous")
        self.compose()
        self.assertIsNone(batches.read_batch(self.project, self.merges)["items"][0]["mark"])
        self.assertIn("No batch was asked under `autonomous`", self.read("PAPER.md"))

    def test_a_proposal_marked_first_in_its_own_batch_is_what_the_paper_follows(self):
        made = paper.order(self.project, start=None)
        batches.mark(self.project, self.merges, 1, "take")
        record = self.compose()
        [followed] = [item for item in record["answers"] if item["ref"].startswith("outline:")]
        self.assertEqual(followed["mark"], "take")
        self.assertIn("marked take in %s first" % self.merges, followed["note"])
        self.assertIsNotNone(made["batch"])

    def test_a_second_order_while_one_is_open_is_refused(self):
        paper.order(self.project, start=None)
        code, _, err = self.verb("--yes")
        self.assertEqual(code, 2)
        self.assertIn("paper order 1 is open", err)

    def test_the_batch_waits_and_the_composition_follows_its_answers(self):
        made = paper.order(self.project, start=None)
        self.assertEqual(paper.waiting_on(self.project, paper.open_order(self.project)), made["batch"])
        batch = batches.read_batch(self.project, made["batch"])
        number = {item["ref"]: item["id"] for item in batch["items"]}
        batches.mark(self.project, made["batch"], number["unverifiable:%s" % self.gone], "keep, not verified")
        batches.mark(self.project, made["batch"], number[paper.UNCHECKED_REF], "leave out")
        record = self.compose()
        prompt = self.writer.prompts[0]
        self.assertIn("keep %s, stated as not verified, with why: the data are gone" % self.gone, prompt)
        self.assertIn("leave the unchecked inherited results out", prompt)
        self.assertIn("hold to %s's claim" % self.other, prompt, "code's default side for the contradiction")
        self.assertEqual(record["unchecked"], "left out")
        report = self.read("PAPER.md")
        self.assertIn("None of the inherited results was checked before this order; the unchecked ones were left out.", report)
        self.assertIn("unverifiable:%s: keep, not verified (by owner, %s item" % (self.gone, made["batch"]), report)
        self.assertEqual(batches.read_batch(self.project, self.merges)["items"][0]["mark"], "decline",
                         "the order's answer is given on the outline's own batch")


class ComposeTest(PaperCase):
    def setUp(self):
        super().setUp()
        self.record = self.compose(close=False)

    def test_one_read_only_writer_session_on_opus_xhigh_returns_each_part(self):
        [call] = self.calls
        self.assertEqual((call.request.role, call.request.model, call.request.effort), ("writer", "opus", "xhigh"))
        self.assertTrue(str(call.request.schema_path).endswith("paper_parts.json"))
        for tool in ("Edit", "Write", "Bash"):
            self.assertIn(tool, call.request.disallowed_tools)
        self.assertEqual(asked(call.request.prompt), list(paper.WRITTEN))
        self.assertIn("{#R1}", call.request.prompt)
        self.assertIn("{#introduction-state-of-the-art}", call.request.prompt)

    def test_code_writes_the_eight_parts_with_outline_ids_and_the_records_beside_them(self):
        directory = self.project / "research" / "paper"
        for part in paper.PARTS:
            self.assertTrue((directory / ("%s.md" % part)).is_file(), part)
        self.assertEqual(self.read("title.md"), "Noise and the fit\n")
        self.assertIn("## State of the art {#introduction-state-of-the-art}", self.read("introduction.md"))
        results = self.read("results.md")
        self.assertLess(results.index("{#%s}" % self.o1), results.index("{#R1}"))
        self.assertIn("{#methods-fitting}", self.read("methods.md"))
        self.assertIn("{#discussion-limits}", self.read("discussion.md"))
        self.assertEqual(self.read("tables/T1.csv"), "noise,rmse\n0.1,0.12\n")
        self.assertIn("**Table 1.** The errors by noise.", self.read("tables/T1.md"))
        self.assertIn("| noise | rmse |", self.read("tables/T1.md"))
        self.assertEqual(json.loads(self.read("references.json")), [], "the one cited work never resolved")
        for number, title in enumerate(["Noise and the fit", "How noise bends a polynomial fit", "Fits under noise"], start=1):
            self.assertEqual(self.read("alternatives/title-%d.md" % number), title + "\n", "the writer offers three titles")
        record = json.loads(self.read("paper.json"))
        self.assertEqual(record["version"], 1)
        self.assertEqual({part: entry["version"] for part, entry in record["parts"].items()}, {part: 1 for part in paper.PARTS})
        self.assertFalse(record["gated"])

    def test_the_build_report_says_what_was_made_and_from_what(self):
        report = self.read("PAPER.md")
        for words in ("# The paper, version 1", "paper order 1 (owner)", "not yet gated", "| introduction | introduction.md | 1 | made afresh |",
                      "the older fits: no passage carries them", "Put Limits before the Results' discussion.",
                      "Read the Methods first.", "1200 input and 800 output token(s)", "$35 to $40", "Nothing was submitted"):
            self.assertIn(words, report)

    def test_the_owners_passage_reworded_by_the_writer_is_listed(self):
        self.assertEqual(self.record["reworded"], [self.owners])
        self.assertIn("- %s: the paper does not carry it word for word" % self.owners, self.read("PAPER.md"))

    def test_the_composition_is_journaled_with_its_build_and_the_order_lasts_through_its_gates(self):
        composed = self.orders()[-1]
        self.assertEqual((composed["action"], composed["order"], composed["version"], composed["build"]), ("composed", 1, 1, 1))
        self.assertEqual(composed["parts"], list(paper.PARTS))
        self.assertEqual(paper.open_order(self.project)["order"], 1, "the build's gates are owed (ticket 117)")
        self.assertEqual(replay.replay(self.journal()).paper_order["order"], 1)

    def test_the_front_matter_is_code_s_with_placeholders_and_the_availability_statements(self):
        front = self.read("front.md")
        for words in ("[TO BE GIVEN: the authors and their affiliations]", "[TO BE GIVEN: acknowledgments]", "[TO BE GIVEN: funding]",
                      "[TO BE GIVEN: competing interests]", "## Data availability", "1 artifact(s) recorded with their SHA-256",
                      "## Code availability", "[TO BE GIVEN: the code repository, which setup has not settled]"):
            self.assertIn(words, front)
        [call] = self.calls
        self.assertIn("The front matter", call.request.prompt)
        self.assertNotIn("front", asked(call.request.prompt))


class FrontMatterTest(PaperCase):
    def test_the_owners_front_matter_replaces_the_placeholders(self):
        code, out, err = self.verb("front", "-", stdin=json.dumps({
            "authors": [{"name": "Ada Lovelace", "affiliations": ["Analytical Engines Ltd"], "corresponding": True, "email": "ada@example.org"},
                        {"name": "Charles Babbage", "affiliations": ["Analytical Engines Ltd"]}],
            "funding": "None."}))
        self.assertEqual(code, 0, err)
        self.assertIn("still to be given: the acknowledgments, the competing interests", out)
        self.compose()
        front = self.read("front.md")
        self.assertIn("- Ada Lovelace^1^ (corresponding author, ada@example.org)", front)
        self.assertIn("1. Analytical Engines Ltd", front)
        self.assertIn("## Funding\n\nNone.", front)
        self.assertNotIn("the authors and their affiliations]", front)
        self.assertIn("[TO BE GIVEN: acknowledgments]", front)

    def test_front_matter_outside_its_schema_is_refused(self):
        code, _, err = self.verb("front", "-", stdin=json.dumps({"authors": [{"name": ""}]}))
        self.assertEqual(code, 2)
        self.assertIn("front matter", err)
        self.assertFalse((self.project / "research" / "front.json").exists())


class StructureTest(PaperCase):
    def test_headings_off_the_outlines_order_are_sent_back_once_and_then_fail_the_order(self):
        def swapped(found, call):
            found["results"] = "## The error grows {#R1}\n\nText.\n\n## %s {#%s}\n\nText." % (NOISE, self.o1)
            return found
        with self.assertRaisesRegex(paper.PaperError, "the outline's order is %s, R1" % self.o1):
            self.compose(swapped)
        self.assertEqual(len(self.calls), 2, "resumed once with what failed")
        self.assertIn("the outline's order is", self.writer.prompts[1])
        self.assertFalse((self.project / "research" / "paper" / "results.md").exists(), "nothing is written")

    def test_a_writer_mended_on_its_resume_is_written(self):
        def mended(found, call):
            if call == 1:
                found["methods"] = "## Fitting {#methods-fitting}\n\nText.\n\n## References\n\n1. A work."
            return found
        self.compose(mended)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("a reference list (References) is code's", self.writer.prompts[1])
        self.assertNotIn("References", self.read("methods.md"))

    def test_the_check_names_a_heading_placed_elsewhere_an_unknown_one_and_one_missing(self):
        structure = outline.paper_structure(self.project)
        problems = paper.check_structure(structure, {
            "introduction": "## Fitting {#methods-fitting}\n\nText.\n\n## A new idea {#introduction-new}\n\n## No id\n",
            "methods": "Text with no heading."})
        joined = "\n".join(problems)
        self.assertIn("{#methods-fitting} is placed in methods by the outline", joined)
        self.assertIn("{#introduction-new}", joined)
        self.assertIn('"No id" carries no outline id', joined)
        self.assertIn("introduction: the outline's {#introduction-state-of-the-art} is missing", joined)
        self.assertIn("methods: the outline's {#methods-fitting} is missing", joined)

    def test_a_writers_wanted_change_is_a_proposal_in_the_report(self):
        self.compose()
        self.assertIn("## Proposed by the writer, never made\n\n- Put Limits before the Results' discussion.", self.read("PAPER.md"))

    def test_three_titles_are_asked_for(self):
        with self.assertRaisesRegex(paper.PaperError, "three titles"):
            self.compose(lambda found, call: dict(found, titles=["Only one"]))


class ReorderTest(PaperCase):
    def setUp(self):
        super().setUp()
        self.compose()
        self.first = json.loads(self.read("paper.json"))
        (self.project / "research" / "paper" / "introduction.md").write_text("## State of the art {#introduction-state-of-the-art}\n\n"
                                                                             "The owner's own wording.\n", encoding="utf-8")
        self.passage("discussion", "Limits", "The noise model is Gaussian, and heavier tails are untested.")
        self.second = self.compose()

    def test_the_first_version_is_frozen_under_earlier(self):
        earlier = self.project / "research" / "paper" / "earlier" / "v1"
        for name in ("title.md", "results.md", "PAPER.md", "paper.json", "tables/T1.csv", "alternatives/title-2.md"):
            self.assertTrue((earlier / name).is_file(), name)
        self.assertEqual(json.loads((earlier / "paper.json").read_text(encoding="utf-8"))["version"], 1)
        self.assertIn("The owner's own wording", (earlier / "introduction.md").read_text(encoding="utf-8"),
                      "the version is frozen as the order found it on disk, the owner's edit of it included")

    def test_only_the_parts_whose_inputs_changed_are_recomposed_with_the_title_and_abstract(self):
        [call] = self.calls
        self.assertEqual(asked(call.request.prompt), ["title", "abstract", "discussion", "supplement"])
        self.assertIn("research/paper/: version 1, the whole of it", call.request.prompt, "the writer reads the whole version")
        versions = {part: entry["version"] for part, entry in self.second["parts"].items()}
        self.assertEqual(versions, {"title": 2, "abstract": 2, "introduction": 1, "results": 1, "discussion": 2, "methods": 1,
                                    "supplement": 2, "front": 1})
        self.assertEqual(self.orders()[-2]["parts"], ["title", "abstract", "discussion", "supplement"])

    def test_the_owners_edit_of_an_unchanged_part_is_kept(self):
        self.assertIn("The owner's own wording.", self.read("introduction.md"))
        self.assertEqual(self.second["kept_edits"], ["introduction"])
        self.assertIn("| introduction | introduction.md | 1 | your edit kept |", self.read("PAPER.md"))

    def test_a_version_is_frozen_once(self):
        frozen = self.project / "research" / "paper" / "earlier" / "v1" / "title.md"
        before = frozen.read_bytes()
        (self.project / "research" / "paper" / "paper.json").write_text(json.dumps(dict(self.first)), encoding="utf-8")
        self.passage("discussion", "Limits", "Heavier tails come next.")
        self.compose()
        self.assertEqual(frozen.read_bytes(), before, "a second freeze of v1, as after a composition that failed partway, writes nothing")

    def test_an_owners_edit_of_a_part_whose_inputs_changed_is_recomposed(self):
        (self.project / "research" / "paper" / "discussion.md").write_text("## Limits {#discussion-limits}\n\nMine.\n", encoding="utf-8")
        self.passage("discussion", "Limits", "The noise model is Gaussian; heavier tails come next.")
        third = self.compose()
        self.assertNotIn("Mine.", self.read("discussion.md"))
        self.assertEqual(third["parts"]["discussion"]["version"], 3)
        self.assertIn("Mine.", (self.project / "research" / "paper" / "earlier" / "v2" / "discussion.md").read_text(encoding="utf-8"))


class KeptTest(InheritedCase):
    """An earlier manuscript's title, abstract, and captions never reach the paper."""

    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")
        self.deconstruct()
        self.kept = paper.inherited_kept(self.project)

    def test_the_title_the_abstract_and_the_captions_are_what_is_kept(self):
        whats = [what for what, _ in self.kept]
        self.assertIn("the title of D1", whats)
        self.assertTrue(any(what.startswith("the abstract of D1") for what in whats) or any("caption" in what for what in whats))

    def test_a_part_carrying_the_inherited_title_fails_the_check(self):
        title = dict(self.kept)["the title of D1"]
        problems = paper.kept_problems({"results": "## Old {#R1}\n\nAs %s showed." % title, "methods": "Our own words."}, self.kept)
        self.assertEqual(len(problems), 1)
        self.assertIn("results carries the title of D1", problems[0])


class OrderRunTest(DrawingRunCase):
    """The conductor at a paper order: the rest point, read back from the journal it wrote."""

    def setUp(self):
        super().setUp()
        third = dict(self.ticket(1), id=3, status="open", title="Write another file", touches=["other.txt"], outputs=["other.txt"],
                     acceptance={"machine": ["test -f other.txt"], "quality": []})
        tickets.write_ticket(self.ledger, third, "\nAnother.\n")
        fourth = dict(third, id=4, title="Write a third file", touches=["third.txt"], outputs=["third.txt"], blocked_by=[3],
                      acceptance={"machine": ["test -f third.txt"], "quality": []})
        tickets.write_ticket(self.ledger, fourth, "\nA third.\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "two more tickets")

    def conductor(self):
        driven = Conductor(self.project, out=io.StringIO())
        driven.readings = machine.recorded
        driven.drawing_python = sys.executable
        self.addCleanup(driven.settle, 30)
        return driven

    def wrote(self, identifier, name):
        from tests.test_conductor import done, patch
        return dict(envelope=done(ticket_id=identifier, outputs_written=[name]),
                    patch=patch({name: "written\n"}, "ticket %d: write %s" % (identifier, name)), ticket=str(identifier))

    def until(self, driven, done_when, waves=20):
        for _ in range(waves):
            result = driven.wave()
            driven.settle()
            if result.ended or done_when():
                return result
        self.fail("never came about: %s" % self.sequence())

    def order_events(self):
        return [event for event in self.events() if event["event"] == "paper_order"]

    def index(self, predicate):
        return next(number for number, event in enumerate(self.events()) if predicate(event))

    def test_running_tickets_finish_nothing_new_launches_the_results_are_drawn_and_the_run_resumes(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        with worker.use_fake() as fake:
            fake.script(delay=600, **self.wrote(3, "other.txt"))
            fake.script(respond=self.plotter(), role="plotter")
            fake.script(respond=Writer(self.project), role="writer")
            gates_pass(fake)
            fake.script(**self.wrote(4, "third.txt"))
            driven = self.conductor()
            self.assertEqual(driven.wave().launched, [3])
            made = paper.order(self.project, start=None)
            self.assertIsNone(made["run"], "a run was going: it resumes after the paper")
            waiting = driven.wave()
            self.assertEqual(waiting.launched, [])
            self.assertIn("waits for ticket(s) 3 to finish", driven.out.getvalue())
            fake.release(ticket="3")
            driven.settle()
            self.until(driven, lambda: any(event["payload"]["action"] == "composed" for event in self.order_events()))
            self.until(driven, lambda: 4 in [event["payload"]["ticket"] for event in self.events("ticket_launched")])
        done3 = self.index(lambda event: event["event"] == "ticket_done" and event["payload"]["ticket"] == 3)
        drawn = self.index(lambda event: event["event"] == "drawing" and event["payload"]["outcome"] == "opened")
        composed = self.index(lambda event: event["event"] == "paper_order" and event["payload"]["action"] == "composed")
        launched4 = self.index(lambda event: event["event"] == "ticket_launched" and event["payload"]["ticket"] == 4)
        self.assertLess(done3, drawn)
        self.assertLess(drawn, composed)
        self.assertLess(composed, launched4, "nothing new launched before the paper was composed")
        self.assertEqual(self.events("drawing")[0]["payload"]["rest"], "order")
        self.assertNotIn("run_ended", [event["event"] for event in self.events()[:launched4]])
        self.assertTrue((self.project / "research" / "paper" / "results.md").is_file())

    def test_an_order_with_no_run_going_runs_for_itself_and_ends_as_the_last_run_did(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "objectives_closed"})
        made = paper.order(self.project, start=None)
        self.assertEqual(made["run"], "objectives_closed")
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            fake.script(respond=Writer(self.project), role="writer")
            gates_pass(fake)
            driven = self.conductor()  # a conductor started afresh replays the order from the journal
            last = self.until(driven, lambda: False)
        self.assertTrue(last.ended)
        self.assertEqual(last.reason, "objectives_closed")
        self.assertEqual([event["payload"]["ticket"] for event in self.events("ticket_launched")],
                         [self.events("drawing")[0]["payload"]["ticket"]], "the drawing alone launched; ticket 3 never")
        self.assertEqual(self.events("run_ended")[-1]["payload"]["reason"], "objectives_closed")
        composed = self.index(lambda event: event["event"] == "paper_order" and event["payload"]["action"] == "composed")
        self.assertLess(composed, len(self.events()) - 1)

    def test_once_composed_the_order_compiles_the_paper_and_a_compilation_that_cannot_be_made_is_said(self):
        """Ticket 118: the conductor compiles `compilations/plain/` after the composition; with no pandoc recorded in
        `tools.json`, the compilation records why each output is missing and the order still ends composed."""
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "objectives_closed"})
        paper.order(self.project, start=None)
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            fake.script(respond=Writer(self.project), role="writer")
            gates_pass(fake)
            driven = self.conductor()
            self.until(driven, lambda: False)
        self.assertEqual([event["payload"]["action"] for event in self.order_events()], ["ordered", "composed", "passed"])
        record = json.loads((self.project / "research" / "paper" / "compilations" / "plain" / "compilation.json").read_text())
        self.assertEqual(record["outcome"], "failed")
        self.assertIn("is not recorded", record["outputs"]["latex"]["problem"])
        self.assertIn("compilation plain of version 1: failed", driven.out.getvalue())

    def ended_notice(self, writer):
        """The notice the order's end sent, with the writer answering `writer` (a fake's respond, or an envelope twice)."""
        from wayline import notify
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "objectives_closed"})
        paper.order(self.project, start=None)
        from tests.test_builds import Verifier  # ticket 117's gates run after the composition
        notices = []
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            for _ in range(2):
                fake.script(writer, role="writer") if isinstance(writer, Envelope) else fake.script(respond=writer, role="writer")
            for _ in range(3):
                fake.script(respond=Verifier(), role="verifier")
            driven = self.conductor()
            driven.notify = lambda event, text, project=None, ticket=None: notices.append((event, text))
            self.until(driven, lambda: False)
        [text] = [text for event, text in notices if event == notify.PAPER_ENDED]
        return text

    def test_the_orders_end_is_a_notice_when_composed(self):
        """Ticket 121: an order's end notifies; `notify.holds` keeps it back under `autonomous` alone."""
        self.assertIn("paper order 1 composed: research/paper/PAPER.md says what was made; compiled as plain (failed)",
                      self.ended_notice(Writer(self.project)))

    def test_the_orders_end_is_a_notice_when_it_failed(self):
        self.assertIn("paper order 1 failed: ", self.ended_notice(Envelope(structured_output=None, errors=["no answer"])))

    def test_a_composition_that_fails_closes_the_order_and_is_said(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "frontier_empty"})
        paper.order(self.project, start=None)
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            for _ in range(2):
                fake.script(Envelope(structured_output=None, errors=["no answer"]), role="writer")
            driven = self.conductor()
            last = self.until(driven, lambda: False)
        self.assertEqual([event["payload"]["action"] for event in self.order_events()], ["ordered", "failed"])
        self.assertIn("paper order 1 failed", driven.out.getvalue())
        self.assertEqual(last.reason, "frontier_empty")


class ReplayTest(PaperCase):
    def test_the_view_holds_the_open_order_through_its_builds_until_they_settle_or_it_fails(self):
        events = [{"event": "paper_order", "payload": {"order": 1, "action": "ordered", "by": "owner", "run": None, "batch": None}}]
        self.assertEqual(replay.replay(events).paper_order["order"], 1)
        for action in ("composed", "gated"):
            self.assertEqual(replay.replay(events + [{"event": "paper_order", "payload": {"order": 1, "action": action}}]).paper_order["order"], 1)
        for action in ("passed", "not_passed", "failed"):
            self.assertIsNone(replay.replay(events + [{"event": "paper_order", "payload": {"order": 1, "action": action}}]).paper_order)

    def test_the_tick_relaunches_a_conductor_for_an_order_on_a_project_never_run(self):
        from wayline import tick
        made = paper.order(self.project, start=lambda path: (_ for _ in ()).throw(ValueError("the unit is busy")))
        self.assertIn("not started (the unit is busy)", made["started"])
        reason, _ = tick.relaunch_decision(self.project, self.ledger, json.loads((HARNESS_ROOT / "policy.json").read_text()), None, 0)
        self.assertIn("paper order 1 is open", reason)

    def test_the_tick_relaunches_a_conductor_for_an_open_order(self):
        from wayline import tick
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "stopped"})
        paper.order(self.project, start=None)
        reason, why = tick.relaunch_decision(self.project, self.ledger, json.loads((HARNESS_ROOT / "policy.json").read_text()),
                                             None, 0)
        self.assertIn("paper order 1 is open", reason or why)
        self.ledger.append_event("run_started", {"resume": True, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 2})
        self.ledger.append_event("run_ended", {"reason": "stopped"})
        reason, why = tick.relaunch_decision(self.project, self.ledger, json.loads((HARNESS_ROOT / "policy.json").read_text()),
                                             None, 0)
        self.assertIsNone(reason, "the owner's stop since the order holds")


class RetiredTest(PaperCase):
    def test_paper_md_build_json_continue_and_the_gates_writing_tickets_are_gone(self):
        verb = cli.lookup("paper")
        self.assertNotIn("--continue", verb.usage)
        self.assertNotIn("--venue", verb.usage)
        self.assertIn("--yes", verb.usage)
        self.assertIn("paper", spec_verbs(SPEC_PATH))
        source = (HARNESS_ROOT / "wayline" / "paper.py").read_text(encoding="utf-8")
        for gone in ("paper.md", "build.json", "carry_on", "READ_TITLE"):
            self.assertNotIn(gone, source)
        self.assertFalse((HARNESS_ROOT / "schemas" / "paper_draft.json").exists())
        self.compose()
        names = sorted(path.name for path in (self.project / "research" / "paper").iterdir())
        self.assertNotIn("paper.md", names)
        self.assertNotIn("build.json", names)
        self.assertEqual([fields for fields in tickets.read_tickets(self.project) if fields["kind"] == "writing"], [])

    def test_the_skill_carries_the_paper_reference_file(self):
        reference = (HARNESS_ROOT / "skills" / "wayline" / "paper.md").read_text(encoding="utf-8")
        for words in ("wayline paper --project .", "wayline paper --yes --project .", "readiness", "rest point", "wayline paper front"):
            self.assertIn(words, reference)
        skill = (HARNESS_ROOT / "skills" / "wayline" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`paper.md`", skill)

    def test_the_changelog_names_the_paper_order_under_unreleased(self):
        changelog = (HARNESS_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        self.assertIn("The paper order and the paper's parts (ticket 115", unreleased)

    def test_the_docs_carry_p7s_retirement_p8_as_the_paper_order_and_r26s_wording(self):
        brief = (HARNESS_ROOT / "BRIEF.md").read_text(encoding="utf-8")
        self.assertIn("The general report is always current; the paper is made only on an explicit order, from the owner, or "
                      "from the decider in an autonomous run.", " ".join(brief.split()))
        self.assertRegex(brief, r"P7[^\n]*retire")
        self.assertRegex(brief, r"P8[^\n]*Paper order")


if __name__ == "__main__":
    import unittest
    unittest.main()
