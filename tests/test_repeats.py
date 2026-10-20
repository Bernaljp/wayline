"""Repeated claims (Implementation Decision 17; ticket 95).

The seam is the ledger over a temporary project: the synthetic start-midway project of ticket 78 (its manuscript,
`fixtures/midway/manuscript-v2.docx`, kept through ticket 84's verb with every conversion answered from the tool runner's
recordings and deconstructed by ticket 93's code) and a short supplement of this ticket's own
(`fixtures/repeats/supplement.md`), whose claims repeat and contradict the manuscript's. The consistency read and the
confirmer are scripted through the fake launcher with responders that read the prompt they were sent; the embedding model
runs through the tool runner's recordings (`fixtures/repeats/recorded/embeddings.json`, BAAI/bge-base-en-v1.5's vectors
for every sentence the suite embeds, recorded live by `fixtures/repeats/record.py`). What is asserted is what a later
reader sees: `research/passages.jsonl`, `research/repeats.json`, the batches, the rendered sections, the account, the
grill's questions, and the acceptance result.
"""

import io
import json
import re
import sys
import unittest
from pathlib import Path

from tests import machine
from tests.test_conductor import ConductorCase, done, drive, patch
from tests.test_documents import MIDWAY
from tests.test_inherited import InheritedCase
from wayline import batches, repeats, sections, worker
from wayline.conductor import Conductor
from wayline.tools import ToolOutput, Tools
from wayline.worker import Envelope

ROOT = Path(__file__).resolve().parent.parent
OWN = ROOT / "fixtures" / "repeats"
RECORDED = OWN / "recorded" / "embeddings.json"
SUPPLEMENT = OWN / "supplement.md"

PAIR = re.compile(r"^## Pair (\d+)\n\nFirst: ([PN]\d+), in (\w+) under the heading \"([^\"]*)\"\n> (.*)\n\n"
                  r"Second: (P\d+), in (\w+) under the heading \"([^\"]*)\"\n> (.*)$", re.M)
MERGE = re.compile(r"^## Merge (\d+)\n\nFirst: (P\d+)[^\n]*\n> (.*)\n\nSecond: (P\d+)[^\n]*\n> (.*)\n\nKept:\n> (.*)$", re.M)
CLAIM = re.compile(r"^- (P\d+) \((\w+), under \"([^\"]*)\"\): (.*)$", re.M)


class Embedder:
    """The tool runner answering `embed.py` from the recordings: the vector the live model gave each text."""

    def __init__(self):
        self.calls = []
        self.table = json.loads(RECORDED.read_text(encoding="utf-8"))
        self.missing = []

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        if len(argv) != 4 or not argv[1].endswith("embed.py"):
            return ToolOutput(127, b"", b"not recorded")
        texts = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
        missing = [text for text in texts if text not in self.table]
        if missing:
            self.missing.extend(missing)
            return ToolOutput(1, b"", ("nothing recorded for %r" % missing[0]).encode())
        return ToolOutput(0, json.dumps({"model": Path(argv[2]).name, "vectors": [self.table[text] for text in texts]}).encode(), b"")


class Reader:
    """The consistency read: returns the groups it was scripted with, and keeps the claims each prompt listed."""

    def __init__(self, groups=()):
        self.groups = list(groups)
        self.prompts = []

    def __call__(self, request, message):
        self.prompts.append(request.prompt)
        return Envelope(structured_output={"groups": self.groups})


class Confirmer:
    """The confirmer: labels each pair it is sent as scripted (different by default), and answers each merge check."""

    def __init__(self, labels=None, covers=None):
        self.labels = {frozenset(pair): answer for pair, answer in (labels or {}).items()}
        self.covers = {frozenset(pair): answer for pair, answer in (covers or {}).items()}
        self.prompts = []

    def __call__(self, request, message):
        self.prompts.append(request.prompt)
        if "## Merge 1" in request.prompt:
            merges = []
            for number, first, _, second, _, _ in MERGE.findall(request.prompt):
                covers, lost = self.covers.get(frozenset((first, second)), (True, None))
                merges.append({"merge": int(number), "covers": covers, "lost": lost})
            return Envelope(structured_output={"merges": merges})
        pairs = []
        for number, first, _, _, _, second, _, _, _ in PAIR.findall(request.prompt):
            answer = dict({"label": "different", "kept": None, "text": None, "flag": False, "why": "they say different things"},
                          **self.labels.get(frozenset((first, second)), {}))
            pairs.append(dict(answer, pair=int(number)))
        return Envelope(structured_output={"pairs": pairs})


def same(kept="first", text=None, why="the same claim"):
    return {"label": "same", "kept": kept, "text": text, "why": why}


class RepeatsCase(InheritedCase):
    """The manuscript (D1) and the supplement (D2), deconstructed: P1 to P10 the manuscript's, P11 to P14 the supplement's."""

    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")
        self.add(SUPPLEMENT)
        self.deconstruct("D1")
        self.deconstruct("D2")
        self.embedder = Embedder()
        model = self.temp / "models" / "BAAI--bge-base-en-v1.5"
        model.mkdir(parents=True)
        self.model_tools = Tools(root=self.temp / "embedding-tools", record={"tools": {"embedding-model": {
            "executable": sys.executable, "version": "a5beb1e3e68b", "env": {"HF_HUB_OFFLINE": "1"}, "route": "huggingface",
            "model": "BAAI/bge-base-en-v1.5", "path": str(model)}}})

    def text_of(self, identifier):
        return next(item for item in sections.read_passages(self.project) if item["id"] == identifier)["text"]


class EmbeddingTest(RepeatsCase):
    def test_the_embedding_model_proposes_pairwise_repeats_through_the_tool_runner_with_no_tokens(self):
        texts = [repeats.plain(self.text_of(identifier)) for identifier in ("P4", "P8", "P5", "P11", "P9")]
        with worker.use_fake() as fake:
            vectors = repeats.embed(texts, run=self.embedder, tools=self.model_tools)
            self.assertEqual(fake.calls, [], "the embedding model spends no tokens")
        self.assertEqual(len(self.embedder.calls), 1, "one run of the model for every text")
        argv = self.embedder.calls[0]
        self.assertEqual(argv[0], sys.executable, "the interpreter the embedding model's entry records")
        self.assertTrue(argv[1].endswith("converters/embed.py"))
        pairs = {(first, second) for first, second, _ in repeats.near_pairs(vectors, 0.70)}
        self.assertIn((0, 1), pairs, "the manuscript's claim repeated in Discussion")
        self.assertIn((2, 3), pairs, "the supplement's claim that contradicts the manuscript's")
        self.assertNotIn((0, 4), pairs)

    def test_a_model_that_is_not_recorded_is_said_and_runs_nothing(self):
        with self.assertRaises(repeats.RepeatsError) as caught:
            repeats.embed(["a sentence."], run=self.embedder, tools=Tools(root=self.temp / "none", record={"tools": {}}))
        self.assertIn("embedding-model", str(caught.exception))
        self.assertEqual(self.embedder.calls, [])


class PolicyTest(unittest.TestCase):
    def test_the_rungs_and_the_threshold_are_the_spec_tables(self):
        policy = json.loads((ROOT / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["roles"]["consistency-reader"], {"model": "opus", "effort": "high"})
        self.assertEqual(policy["roles"]["confirmer"], {"model": "opus", "effort": "medium"})
        self.assertEqual(policy["repeats"], {"similarity": 0.70, "max_pairs": 100})
        spec = (ROOT / ".scratch" / "wayline" / "spec.md").read_text(encoding="utf-8")
        self.assertIn("consistency reader opus high; confirmer opus medium", spec)


class SetupCase(RepeatsCase):
    def check(self, groups=(), labels=None, covers=None):
        """One setup check with the consistency read and the confirmer scripted; keeps the launches it made."""
        self.reader, self.confirmer = Reader(groups), Confirmer(labels, covers)
        with worker.use_fake() as fake:
            fake.script(respond=self.reader, role="consistency-reader")
            fake.script(respond=self.confirmer, role="confirmer")
            fake.script(respond=self.confirmer, role="confirmer")
            report = repeats.check_setup(self.project, run=self.embedder, tools=self.model_tools)
            self.calls = list(fake.calls)
        return report

    def current(self, section):
        return [item["id"] for item in sections.arrange(sections.section_items(self.project, section)).current()]

    def merged(self):
        return [item for item in sections.read_passages(self.project) if item.get("merges")]

    def record(self):
        return json.loads((self.project / "research" / "repeats.json").read_text(encoding="utf-8"))

    def pair(self, first, second):
        return next(entry for entry in self.record()["pairs"] if {entry["a"], entry["b"]} == {first, second})


REPEAT = {"kind": "repeat", "passages": ["P1", "P14"], "why": "both say the swarms lock their wingbeats"}
CONTRADICTION = {"kind": "contradiction", "passages": ["P5", "P11"], "why": "lowest at dusk against peaks at dusk"}


class ConsistencyReadTest(SetupCase):
    def test_one_consistency_read_on_opus_high_reads_every_inherited_claim_through_the_launcher(self):
        self.check([REPEAT])
        reads = [call for call in self.calls if call.request.role == "consistency-reader"]
        self.assertEqual(len(reads), 1)
        self.assertEqual((reads[0].request.model, reads[0].request.effort), ("opus", "high"))
        listed = [found[0] for found in CLAIM.findall(self.reader.prompts[0])]
        self.assertEqual(listed, ["P1", "P3", "P4", "P5", "P6", "P8", "P9", "P11", "P12", "P14"], "every inherited claim, nothing else")
        self.assertIn('- P4 (results, under "Results"): Larger colonies beat more nearly in phase than small ones (Figure 1).',
                      self.reader.prompts[0])

    def test_the_same_set_is_not_read_twice(self):
        self.check([REPEAT], {("P1", "P14"): same()})
        report = self.check()
        self.assertEqual([call for call in self.calls if call.request.role == "consistency-reader"], [], "read once per inherited set")
        self.assertFalse(report["read"])

    def test_every_launch_is_on_opus_and_neither_tf_idf_nor_haiku_takes_part(self):
        self.check([REPEAT, CONTRADICTION], {("P1", "P14"): same(), ("P5", "P11"): {"label": "contradicting"}})
        self.assertTrue(self.calls)
        self.assertEqual({call.request.model for call in self.calls}, {"opus"})
        self.assertEqual({call.request.role for call in self.calls}, {"consistency-reader", "confirmer"})
        source = (ROOT / "wayline" / "repeats.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("tf-idf", source)
        self.assertNotIn("haiku", source)


class VerbTest(SetupCase):
    def test_document_repeats_runs_the_check_and_says_what_it_did_and_what_it_could_not(self):
        from tests.test_documents import run_verb

        self.reader, self.confirmer = Reader([REPEAT]), Confirmer({("P1", "P14"): same()})
        with worker.use_fake() as fake:
            fake.script(respond=self.reader, role="consistency-reader")
            fake.script(respond=self.confirmer, role="confirmer")
            fake.script(respond=self.confirmer, role="confirmer")
            code, out, err = run_verb("document", "repeats", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("merged into P15", out)
        self.assertIn("for your marks: B1", out)
        self.assertIn("the embedding net proposed nothing: the embedding model is not recorded", out,
                      "this machine's tools record has no embedding model, and the read's pairs are still confirmed")


class ConfirmerTest(SetupCase):
    def test_the_confirmer_sees_each_sentence_with_its_heading_and_labels_every_pair_proposed(self):
        self.check([REPEAT, CONTRADICTION])
        labelled = PAIR.findall(self.confirmer.prompts[0])
        pairs = {frozenset((found[1], found[5])) for found in labelled}
        self.assertIn(frozenset(("P1", "P14")), pairs, "the consistency read's repeat group")
        self.assertIn(frozenset(("P5", "P11")), pairs, "its contradiction, and the embedding net's pair too")
        self.assertIn(frozenset(("P8", "P12")), pairs, "the embedding net's pair the read did not name")
        found = next(entry for entry in labelled if {entry[1], entry[5]} == {"P1", "P14"})
        self.assertEqual((found[2], found[3], found[4]), ("introduction", "Introduction",
                                                         "Lantern moths gather in dusk swarms whose wingbeats lock together."))
        self.assertEqual((found[6], found[7]), ("discussion", "Discussion"))
        record = self.record()
        self.assertTrue(all(entry["label"] in ("same", "contradicting", "different") for entry in record["pairs"]))
        self.assertEqual(self.pair("P1", "P14")["found_by"], ["consistency", "embedding"])
        self.assertEqual(self.pair("P8", "P12")["found_by"], ["embedding"])


class MergeTest(SetupCase):
    def test_a_merge_keeping_the_fuller_occurrence_verbatim_cites_every_doc_tag_and_work(self):
        report = self.check([REPEAT], {("P1", "P14"): same("first")})
        [merge] = self.merged()
        self.assertEqual(merge["text"], "Lantern moths gather in dusk swarms whose wingbeats lock together."
                                        "{ref:title:Invented reference Okafor2017}{doc:D1#p2.s1}{doc:D2#p4.s1}")
        self.assertEqual((merge["section"], merge["heading"], merge["merges"], merge["replaces"]),
                         ("introduction", "Introduction", ["P1", "P14"], "P1"))
        self.assertEqual(merge.get("standing"), "unchecked", "a merged claim is still unchecked")
        self.assertIn(merge["id"], self.current("introduction"))
        self.assertNotIn("P1", self.current("introduction"))
        self.assertNotIn("P14", self.current("discussion"), "the other occurrence leaves its section")
        self.assertNotIn("gather in swarms at dusk", self.section("discussion"))
        self.assertEqual(self.pair("P1", "P14")["outcome"], "merged")
        self.assertEqual(report["merged"], [merge["id"]])

    def test_a_combined_sentence_cites_the_works_of_both_occurrences(self):
        self.check([], {("P8", "P12"): same("combined", "Synchrony rises with colony size.")})
        [merge] = self.merged()
        self.assertEqual(merge["text"], "Synchrony rises with colony size.{ref:doi:10.5555/invented.moths}{doc:D1#p9.s1}{doc:D2#p2.s2}")
        self.assertEqual((merge["section"], merge["merges"]), ("discussion", ["P8", "P12"]))
        self.assertNotIn("P12", self.current("results"))

    def test_a_merge_the_confirmer_finds_loses_content_stays_apart_with_no_fallback(self):
        self.check([], {("P8", "P12"): same("second")}, covers={("P8", "P12"): (False, "it drops that this is the central finding")})
        self.assertEqual(self.merged(), [])
        self.assertIn("P8", self.current("discussion"))
        self.assertIn("P12", self.current("results"))
        entry = self.pair("P8", "P12")
        self.assertEqual((entry["outcome"], entry["flag"]), ("apart", True))
        self.assertIn("drops that this is the central finding", entry["why"])

    def test_a_combined_sentence_that_adds_a_number_stays_apart(self):
        text = "Colonies of more than 40 moths lock their wingbeats within a minute of dusk."
        self.check([REPEAT], {("P1", "P14"): same("combined", text)})
        self.assertEqual(self.merged(), [])
        self.assertIn("P1", self.current("introduction"))
        self.assertIn("P14", self.current("discussion"))
        entry = self.pair("P1", "P14")
        self.assertEqual((entry["outcome"], entry["flag"]), ("apart", True))
        self.assertEqual(entry["added"], ["40"])
        no_loss = [prompt for prompt in self.confirmer.prompts if "## Merge 1" in prompt]
        self.assertTrue(no_loss, "the confirmer still checked what the merge would lose")

    def test_a_citation_or_symbol_neither_occurrence_has_is_an_addition(self):
        self.assertEqual(repeats.additions("Synchrony rises with colony size [@Okafor2017] by $\\alpha$.",
                                           ["Synchrony grows with the size of the colony.", "Our finding is that synchrony rises."]),
                         ["@Okafor2017", "\\alpha"])
        self.assertEqual(repeats.additions("R = 0.71 in 2021.", ["The sweep of 2021 gave R = 0.71."]), [])


class ContradictionTest(SetupCase):
    def test_a_contradicting_pair_both_stays_listed_for_the_grill_and_the_verification_of_its_result(self):
        report = self.check([CONTRADICTION], {("P5", "P11"): {"label": "contradicting", "why": "lowest against peaks at dusk"}})
        self.assertEqual(report["contradictions"], ["P5+P11"])
        self.assertIn("P5", self.current("results"))
        self.assertIn("P11", self.current("results"))
        self.assertEqual(self.merged(), [])
        self.assertEqual(repeats.contradictions(self.project, heading="Results"),
                         [{"a": "P5", "b": "P11", "why": "lowest against peaks at dusk", "results": ["Results"]}])
        self.assertEqual(repeats.contradictions(self.project, heading="Discussion"), [])
        [item] = repeats.grill_items(self.project)
        self.assertEqual(item["pair"], "P5+P11")
        self.assertIn("contradict", item["question"])
        self.assertIn("The order parameter is lowest at dusk across every colony.", item["question"])

    def test_a_flagged_pair_kept_apart_is_listed_for_the_grill_and_an_unflagged_one_is_not(self):
        self.check([], {("P4", "P8"): {"label": "different", "flag": True, "why": "one is about colony size, one is the central finding"},
                        ("P4", "P12"): {"label": "different", "why": "not the same"}})
        listed = {item["pair"]: item for item in repeats.grill_items(self.project)}
        self.assertIn("P4+P8", listed)
        self.assertNotIn("P4+P12", listed)
        self.assertEqual(self.pair("P4", "P8")["outcome"], "different")
        self.assertEqual(listed["P4+P8"]["recommended"], "keep them apart")

    def test_a_merge_refused_by_a_check_is_listed_for_the_grill(self):
        self.check([], {("P8", "P12"): same("second")}, covers={("P8", "P12"): (False, "it drops the central finding")})
        self.assertEqual([item["pair"] for item in repeats.grill_items(self.project)], ["P8+P12"])

    def test_the_grill_asks_one_question_per_listed_pair_while_the_project_is_in_its_setup(self):
        from wayline import grill

        self.check([CONTRADICTION], {("P5", "P11"): {"label": "contradicting"}})
        grill.grill_view(self.project)
        asked = [record for record in grill.read_records(self.project) if "contradict" in record["question"]]
        self.assertEqual(len(asked), 1)
        self.assertTrue(asked[0]["human_only"])
        grill.grill_view(self.project)
        self.assertEqual(len([record for record in grill.read_records(self.project) if "contradict" in record["question"]]), 1,
                         "asked once")


class BatchTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.report = self.check([REPEAT, CONTRADICTION], {("P1", "P14"): same("first"), ("P5", "P11"): {"label": "contradicting"}})
        self.merges, self.contradicting = (batches.read_batch(self.project, identifier) for identifier in self.report["batches"])

    def test_the_merges_and_the_contradictions_are_put_before_the_owner_with_their_marks(self):
        self.assertEqual((self.merges["kind"], self.contradicting["kind"]), ("merges", "contradictions"))
        [merge] = self.merges["items"]
        self.assertEqual((merge["ref"], merge["marks"], merge["default"]), ("P1+P14", ["right", "split"], "right"))
        self.assertIn("merged into P15", merge["text"])
        [contradiction] = self.contradicting["items"]
        self.assertEqual((contradiction["ref"], contradiction["marks"], contradiction["default"]),
                         ("P5+P11", ["real", "not a contradiction"], "real"))
        self.assertEqual((self.pair("P1", "P14")["batch"], self.pair("P1", "P14")["item"]), (self.merges["id"], 1))

    def test_a_split_mark_undoes_the_merge_and_restores_both_passages(self):
        batches.mark(self.project, self.merges["id"], 1, "split")
        self.assertEqual(repeats.take_marks(self.project), [])
        self.assertNotIn("P15", self.current("introduction"))
        standing = set(self.current("introduction")) | set(self.current("discussion"))
        restored = {item["text"]: item for item in sections.read_passages(self.project) if item["id"] in standing}
        self.assertIn(self.text_of("P1"), restored)
        self.assertIn(self.text_of("P14"), restored)
        self.assertEqual(restored[self.text_of("P14")]["standing"], "unchecked")
        self.assertIn("gather in swarms at dusk", self.section("discussion"))
        self.assertEqual(self.pair("P1", "P14")["outcome"], "split")
        self.assertEqual(repeats.account_lines(self.project), [])
        self.assertEqual(repeats.take_marks(self.project), [], "taken once")
        self.assertEqual(len([item for item in sections.read_passages(self.project) if item["text"] == self.text_of("P14")]), 3,
                         "P14, its withdrawal, and its restoration: nothing written twice")

    def test_a_right_mark_leaves_the_merge(self):
        batches.mark(self.project, self.merges["id"], 1, "right")
        repeats.take_marks(self.project)
        self.assertIn("P15", self.current("introduction"))
        self.assertEqual(self.pair("P1", "P14")["outcome"], "merged")

    def test_not_a_contradiction_takes_it_off_the_lists_and_real_keeps_it(self):
        batches.mark(self.project, self.contradicting["id"], 1, "not a contradiction")
        repeats.take_marks(self.project)
        self.assertEqual(repeats.contradictions(self.project), [])
        self.assertEqual(repeats.grill_items(self.project), [])
        self.assertIn("P5", self.current("results"))
        self.assertIn("P11", self.current("results"))

    def test_the_merges_are_in_the_account_under_changed_without_asking_you(self):
        from wayline import account

        account.render_account(self.project)
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        changed = text.split("## Changed without asking you", 1)[1].split("\n## ", 1)[0]
        self.assertIn("P1 (Introduction) and P14 (Discussion) were merged at setup into P15", changed)
        self.assertIn("Lantern moths gather in dusk swarms whose wingbeats lock together.", changed)
        batches.mark(self.project, self.merges["id"], 1, "split")
        account.render_account(self.project)
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        self.assertNotIn("merged at setup", text, "a merge split is no longer a change made without asking")


def finding(text, heading="Colony size", replaces=None):
    return {"id": "f1", "text": text, "provenance": [], "negative": False, "heading": heading, "replaces": replaces}


class AcceptanceTest(RepeatsCase):
    """The check at a ticket's acceptance, a Type-A function over a result and the ledger."""

    def accept(self, result, labels=None, tools=None):
        self.confirmer = Confirmer(labels)
        with worker.use_fake() as fake:
            fake.script(respond=self.confirmer, role="confirmer")
            checked = repeats.check_result(self.project, result, run=self.embedder, tools=tools or self.model_tools)
            self.calls = list(fake.calls)
        return checked

    def test_a_finding_that_repeats_a_current_passage_without_naming_it_sends_the_worker_back(self):
        checked = self.accept({"findings": [finding("Synchrony rises with colony size.")]}, {("N1", "P12"): same()})
        outcome = checked.acceptance_result()
        self.assertEqual((outcome["cmd"], outcome["exit_code"]), ("repeats", 1))
        self.assertIn("P12", outcome["tail"])
        self.assertIn("Synchrony grows with the size of the colony.", outcome["tail"], "the passage it repeats, said whole")
        self.assertIn("replaces", outcome["tail"])
        [call] = self.calls
        self.assertEqual((call.request.role, call.request.model), ("confirmer", "opus"))
        labelled = PAIR.findall(self.confirmer.prompts[0])
        self.assertIn(("N1", "results", "Colony size"), {entry[1:4] for entry in labelled}, "the new finding, with its heading")

    def test_a_new_passage_naming_what_it_repeats_in_replaces_passes(self):
        checked = self.accept({"findings": [finding("Synchrony rises with colony size.", heading="Results", replaces="P12")]},
                              {("N1", "P12"): same()})
        self.assertEqual(checked.acceptance_result()["exit_code"], 0)
        labelled = {(entry[1], entry[5]) for entry in PAIR.findall(self.confirmer.prompts[0])}
        self.assertNotIn(("N1", "P12"), labelled, "what it replaces is not a repeat of it")

    def test_a_passage_the_confirmer_finds_different_passes(self):
        checked = self.accept({"passages": [{"section": "discussion", "heading": "Discussion",
                                             "text": "Larger colonies are more synchronized.", "replaces": None}]})
        self.assertEqual(checked.acceptance_result()["exit_code"], 0)
        self.assertTrue(self.calls, "the net proposed pairs, and the confirmer labelled them")

    def test_only_the_tickets_own_text_is_checked_so_what_the_harness_wrote_is_allowed(self):
        checked = self.accept({"findings": [finding("The wingbeat phase drifts by less than a cycle over ten minutes.")]})
        self.assertEqual(checked.acceptance_result()["exit_code"], 0)
        self.assertEqual(self.calls, [], "P8 and P12 repeat each other, but nothing new is near them: no session")

    def test_without_the_embedding_model_the_check_is_listed_not_failed(self):
        checked = self.accept({"findings": [finding("Synchrony rises with colony size.")]},
                              tools=Tools(root=self.temp / "none", record={"tools": {}}))
        outcome = checked.acceptance_result()
        self.assertEqual(outcome["exit_code"], 0)
        self.assertIn("not checked", outcome["tail"])
        self.assertEqual(self.calls, [])

    def test_a_result_with_no_passage_and_no_finding_has_no_check(self):
        self.assertIsNone(repeats.check_result(self.project, {"summary": "nothing written"}, run=self.embedder, tools=self.model_tools))


class AtAcceptanceTest(ConductorCase):
    """The conductor runs the check at the worktree's acceptance and sends the worker back with the passage repeated."""

    def test_a_finding_repeating_a_current_passage_sends_the_worker_back_and_a_new_one_is_accepted(self):
        sections.add_passage(self.ledger, "results", "Colony size", "Synchrony grows with the size of the colony.", by="owner")
        model = self.temp / "models" / "BAAI--bge-base-en-v1.5"
        model.mkdir(parents=True)
        tools = Tools(root=self.temp / "embedding-tools", record={"tools": {"embedding-model": {
            "executable": sys.executable, "version": "a5beb1e3e68b", "env": {}, "route": "huggingface", "path": str(model)}}})
        repeated = done(findings=[{"text": "Synchrony rises with colony size.", "provenance": "hello.txt#L1"}])
        fresh = done(findings=[{"text": "The wingbeat phase drifts by less than a cycle over ten minutes.", "provenance": "hello.txt#L1"}])
        confirmer = Confirmer({("N1", "P1"): same()})
        with worker.use_fake() as fake:
            fake.script(repeated, patch=patch())
            fake.script(respond=confirmer, role="confirmer")
            fake.script(fresh)
            conductor = Conductor(self.project, out=io.StringIO())
            conductor.readings = machine.recorded
            conductor.plan_pre_check = False
            conductor.repeats_run, conductor.repeats_tools = Embedder(), tools
            drive(conductor)
            calls = list(fake.calls)
        acceptance = self.events("acceptance")
        self.assertEqual([(event["payload"]["where"], event["payload"]["pass"]) for event in acceptance][:2],
                         [("worktree", False), ("worktree", True)])
        checked = next(result for result in acceptance[0]["payload"]["results"] if result["cmd"] == "repeats")
        self.assertIn("repeats P1", checked["tail"])
        resume = calls[-1]
        self.assertIn("Synchrony grows with the size of the colony.", resume.message, "the worker is told the passage it repeats")
        self.assertEqual(self.payload("ticket_resumed")["reason"], "acceptance_failed")
        self.assertEqual([event["payload"]["text"] for event in self.events("finding")],
                         ["The wingbeat phase drifts by less than a cycle over ten minutes."])
