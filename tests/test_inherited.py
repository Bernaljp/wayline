"""Inherited passages: a project's own earlier writing deconstructed verbatim into the sections (decision 17; ticket 93).

The seam is the ledger over a temporary project. The documents are the synthetic start-midway project of ticket 78
(`fixtures/midway/`, nothing of PINF), kept through ticket 84's verb with every conversion answered from the tool
runner's recordings; the sentence classifier is scripted through the fake launcher with a responder that reads the
numbered sentences it was sent. What is asserted is what a later reader sees: `research/passages.jsonl`, the journal,
`research/documents.json`, `research/DOCUMENTS.md`, and the rendered files under `research/sections/`.
"""

import json
import re

from tests.test_documents import MIDWAY, DocumentsCase, run_verb
from wayline import inherited, sections, worker
from wayline.documents import read_documents
from wayline.ledger import Ledger
from wayline.worker import Envelope

NUMBERED = re.compile(r"^\[(\d+)\] (.*)$", re.M)


def rule(sentence):
    """How the scripted classifier reads a sentence of the midway documents."""
    if sentence.startswith("Why "):
        return "transition"
    if any(word in sentence for word in ("filmed", "band-passed", "is the modulus")):
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


class InheritedCase(DocumentsCase):
    def deconstruct(self, document_id="D1", places=None, sessions=4):
        with worker.use_fake() as fake:
            self.classifier = Classifier()
            for _ in range(sessions):
                fake.script(respond=self.classifier, role="classifier")
            return inherited.deconstruct(self.project, document_id, places=places)

    def passages(self):
        return sections.read_passages(self.project)

    def ours(self, document_id="D1"):
        return [item for item in self.passages() if item["by"] == "document:%s" % document_id]

    def section(self, name):
        return (self.project / "research" / "sections" / ("%s.md" % name)).read_text(encoding="utf-8").split("\n", 1)[1]

    def record(self, document_id="D1"):
        return next(document for document in read_documents(self.project) if document["id"] == document_id)

    def events(self, name):
        return [event for event in Ledger(self.project).read_events()[0] if event["event"] == name]


class TheManuscriptTest(InheritedCase):
    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")

    def test_the_body_under_mapped_headings_becomes_passages_by_the_document(self):
        self.deconstruct()
        ours = self.ours()
        self.assertEqual([(item["section"], item["heading"]) for item in ours],
                         [("introduction", "Introduction")] * 3 + [("results", "Results")] * 4
                         + [("discussion", "Discussion")] * 2 + [("methods", "Methods")])
        self.assertEqual(len(self.passages()), len(ours), "nothing but the document's passages")
        self.assertEqual([event["payload"]["id"] for event in self.events("passage")], [item["id"] for item in ours])
        self.assertTrue(all(event["payload"]["by"] == "document:D1" for event in self.events("passage")))

    def test_each_claim_is_one_passage_and_the_sentences_between_claims_stay_together(self):
        self.deconstruct()
        introduction = [item for item in self.ours() if item["section"] == "introduction"]
        self.assertEqual([item["doc"] for item in introduction], ["D1#p2.s1", "D1#p2.s2", "D1#p2.s3"])
        self.assertEqual([item.get("standing") for item in introduction], ["unchecked", None, "unchecked"])
        self.assertEqual(introduction[1]["text"], "Why they synchronize is unknown.{doc:D1#p2.s2}")
        results = [item for item in self.ours() if item["section"] == "results"]
        self.assertEqual([item["doc"] for item in results], ["D1#p4.s1", "D1#p4.s2", "D1#p5.s1", "D1#p6"])
        self.assertEqual(results[1]["text"], "The order parameter is lowest at dusk across every colony.{doc:D1#p4.s2}")
        self.assertEqual(results[3]["text"], r"$$R = |\frac{1}{N}\sum exp(i\varphi)|$$ {doc:D1#p6}", "a display equation is kept whole")
        self.assertNotIn("standing", results[3])
        self.assertIn("The order parameter is lowest at dusk across every colony.", self.classifier.batches[0],
                      "the classifier read every sentence")

    def test_a_run_of_sentences_between_claims_is_one_passage_with_its_range(self):
        (self.temp / "notes.md").write_text(
            "# Methods\n\nEach colony was filmed at dusk. The traces were band-passed. Phase locking held in every colony. "
            "Why it held is open.\n", encoding="utf-8")
        self.add(self.temp / "notes.md")
        self.deconstruct("D2")
        self.assertEqual([(item["doc"], item.get("standing")) for item in self.ours("D2")],
                         [("D2#p2.s1-s2", None), ("D2#p2.s3", "unchecked"), ("D2#p2.s4", None)])
        self.assertEqual(self.ours("D2")[0]["text"], "Each colony was filmed at dusk. The traces were band-passed.{doc:D2#p2.s1-s2}")

    def test_inherited_citations_become_identifier_ref_tags_with_no_locator(self):
        self.deconstruct()
        first = self.ours()[0]
        self.assertEqual(first["text"], "Lantern moths gather in dusk swarms whose wingbeats lock together."
                                        "{ref:title:Invented reference Okafor2017}{doc:D1#p2.s1}")
        self.assertNotIn("[@", "".join(item["text"] for item in self.ours()))

    def test_a_rendered_paragraph_still_splits_into_its_sentences_and_the_doc_tag_is_no_word(self):
        from wayline import provenance

        self.deconstruct()
        paragraph = next(line for line in self.section("introduction").splitlines() if line.startswith("Lantern"))
        found = provenance.sentences(paragraph)
        self.assertEqual([sentence.text[:8] for sentence in found], ["Lantern ", "Why they", "Phase lo"])
        self.assertTrue(found[0].text.endswith("{doc:D1#p2.s1} [unchecked]"), "the mark stays with its claim")
        self.assertEqual(provenance.strip_tags(found[0].text),
                         "Lantern moths gather in dusk swarms whose wingbeats lock together.")
        self.assertEqual(provenance.strip_tags("Why they synchronize is unknown.{doc:D1#p2.s2}"), "Why they synchronize is unknown.")

    def test_a_citation_after_the_full_stop_stays_with_its_sentence(self):
        (self.temp / "cited.md").write_text("# Introduction\n\nMoths swarm at dusk. [@Okafor2017] Crickets do not.\n",
                                            encoding="utf-8")
        self.add(self.temp / "cited.md")
        self.deconstruct("D2")
        self.assertEqual([item["text"] for item in self.ours("D2")],
                         ["Moths swarm at dusk [@Okafor2017].{doc:D2#p2.s1}", "Crickets do not.{doc:D2#p2.s2}"])

    def test_a_work_with_a_doi_or_an_arxiv_id_is_tagged_by_it(self):
        self.assertEqual(inherited.citation_tag({"id": "a", "DOI": "https://doi.org/10.1038/ABC.1", "title": "A"}), "{ref:doi:10.1038/abc.1}")
        self.assertEqual(inherited.citation_tag({"id": "b", "URL": "https://arxiv.org/abs/1802.03426v2", "title": "B"}),
                         "{ref:arxiv:1802.03426}")
        self.assertIsNone(inherited.citation_tag({"id": "c"}))

    def test_title_abstract_captions_back_matter_and_references_are_kept_and_never_passages(self):
        self.deconstruct()
        texts = " ".join(item["text"] for item in self.passages())
        for words in ("Wingbeat synchrony in captive", "We measure how closely", "Figure 1. Order parameter",
                      "moth keepers", "Invented phase locking in crickets"):
            self.assertNotIn(words, texts)
        kept = self.record()["deconstructed"]["kept"]
        self.assertEqual(kept, [{"locator": "front", "part": "title"}, {"locator": "front", "part": "abstract"},
                                {"locator": "p7", "part": "caption"}, {"locator": "p13", "part": "back_matter"},
                                {"locator": "p15", "part": "references"}, {"locator": "p16", "part": "references"}])
        headings = {heading["text"]: (heading["to"], heading["by"]) for heading in self.record()["deconstructed"]["headings"]}
        self.assertEqual(headings, {"Introduction": ("introduction", "table"), "Results": ("results", "table"),
                                    "Discussion": ("discussion", "table"), "Methods": ("methods", "table"),
                                    "Acknowledgements": ("kept", "table"), "References": ("kept", "table")})
        index = (self.project / "research" / "DOCUMENTS.md").read_text(encoding="utf-8")
        self.assertIn("- Deconstructed (version 1) into 10 inherited passages, 7 of them claims; kept, never deconstructed: "
                      "the title, the abstract, captions, back matter, the reference list", index)


class RenderingTest(InheritedCase):
    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")
        self.deconstruct()
        self.by_doc = {item["doc"]: item for item in self.ours()}

    def finding(self, replaces, evidence, text="The order parameter is lowest at dusk in 38 of 40 colonies."):
        return sections.file_finding(self.project, {"id": "t4-a1-f1", "ticket": 4, "text": text,
                                                    "provenance": ["results/dusk.json#min_r"], "negative": False,
                                                    "heading": "Results", "replaces": replaces, "evidence": evidence,
                                                    "objectives": []})

    def test_the_rendered_section_rejoins_a_paragraph_verbatim_with_each_claim_marked_unchecked(self):
        introduction = self.section("introduction")
        ids = " ".join(item["id"] for item in self.ours() if item["section"] == "introduction")
        self.assertIn("<!-- wayline:passage %s -->\n" % ids, introduction)
        self.assertIn("Lantern moths gather in dusk swarms whose wingbeats lock together.{ref:title:Invented reference Okafor2017}"
                      "{doc:D1#p2.s1} [unchecked] Why they synchronize is unknown.{doc:D1#p2.s2} Phase locking has been measured "
                      "in other insects.{ref:title:Invented reference Lindqvist2019}{doc:D1#p2.s3} [unchecked]\n", introduction)
        results = self.section("results")
        self.assertIn("## Results\n", results)
        self.assertIn("Larger colonies beat more nearly in phase than small ones (Figure 1).{doc:D1#p4.s1} [unchecked] "
                      "The order parameter is lowest at dusk across every colony.{doc:D1#p4.s2} [unchecked]\n", results)
        self.assertIn(r"$$R = |\frac{1}{N}\sum exp(i\varphi)|$$ {doc:D1#p6}" + "\n", results, "an equation carries no standing")

    def test_a_finding_that_replaces_an_inherited_claim_with_its_evidence_takes_its_place(self):
        claim = self.by_doc["D1#p4.s2"]
        self.finding(claim["id"], "narrows")
        results = self.section("results")
        self.assertIn("Larger colonies beat more nearly in phase than small ones (Figure 1).{doc:D1#p4.s1} [unchecked] "
                      "The order parameter is lowest at dusk in 38 of 40 colonies.", results)
        self.assertNotIn("lowest at dusk across every colony", results)
        self.assertEqual(self.events("finding")[-1]["payload"]["evidence"], "narrows")
        self.assertEqual(json.loads((self.project / "research" / "findings.jsonl").read_text())["evidence"], "narrows")

    def test_a_ticket_passage_that_replaces_an_inherited_claim_with_its_evidence_takes_its_place(self):
        claim = self.by_doc["D1#p2.s3"]
        sections.add_passage(self.project, "introduction", "Introduction", "Phase locking is known in crickets.{ref:lindqvist2019#abstract}",
                             by="t5-a1", replaces=claim["id"], evidence="supports", ticket=5)
        introduction = self.section("introduction")
        self.assertIn("Why they synchronize is unknown.{doc:D1#p2.s2} Phase locking is known in crickets.{ref:lindqvist2019#abstract}\n",
                      introduction)
        self.assertEqual(self.events("passage")[-1]["payload"]["evidence"], "supports")

    def test_the_acceptance_check_asks_a_replacement_of_an_inherited_claim_for_its_evidence(self):
        claim = self.by_doc["D1#p4.s1"]
        fields = {"id": 4, "sections": ["methods", "results"]}
        result = {"status": "done", "passages": [{"section": "methods", "heading": "Filming", "text": "We filmed.", "replaces": None}],
                  "findings": [{"text": "Synchrony rises with size.", "provenance": "results/size.json#r", "replaces": claim["id"]}]}
        problems = sections.check_result(self.project, fields, result)
        self.assertEqual(len(problems), 1)
        self.assertIn("replaces the inherited claim %s, unchecked: say in `evidence`" % claim["id"], problems[0])
        result["findings"][0]["evidence"] = "supports"
        self.assertEqual(sections.check_result(self.project, fields, result), [])
        result["findings"][0]["replaces"] = None
        self.assertIn("is said only of an inherited claim it replaces", sections.check_result(self.project, fields, result)[0])

    def test_the_context_pack_shows_inherited_claims_with_their_standing(self):
        pack = sections.pack_text(self.project, ["results"])
        self.assertIn("  - %s (inherited claim, unchecked): Larger colonies beat more nearly in phase than small ones (Figure 1).{doc:D1#p4.s1}"
                      % self.by_doc["D1#p4.s1"]["id"], pack)

    def test_an_unverifiable_standing_is_kept_apart_from_unchecked(self):
        claim = self.by_doc["D1#p5.s1"]
        record = inherited.mark_unverifiable(self.project, claim["id"], "data/dusk-sweep-2021.csv is gone")
        self.assertEqual((record["standing"], record["reason"], record["replaces"], record["doc"]),
                         ("unverifiable", "data/dusk-sweep-2021.csv is gone", claim["id"], "D1#p5.s1"))
        results = self.section("results")
        self.assertIn("gave R = 0.71.{doc:D1#p5.s1} [unverifiable: data/dusk-sweep-2021.csv is gone]\n", results)
        self.assertIn("lowest at dusk across every colony.{doc:D1#p4.s2} [unchecked]", results)
        with self.assertRaises(inherited.InheritedError):
            inherited.mark_unverifiable(self.project, self.by_doc["D1#p2.s2"]["id"], "no data")


class SeparateDocumentsTest(InheritedCase):
    def test_the_separate_methods_of_the_midway_project_is_deconstructed_into_methods(self):
        self.add(MIDWAY / "methods.tex")
        self.deconstruct()
        self.assertEqual([(item["section"], item["doc"], item.get("standing")) for item in self.ours()],
                         [("methods", "D1#p2.s1-s3", None)])
        self.assertIn("over a window of 256 samples", self.ours()[0]["text"])

    def test_a_separate_methods_is_placed_by_content_and_the_move_is_listed(self):
        (self.temp / "methods-notes.md").write_text(
            "# Methods\n\nColonies were filmed at night. The order parameter is the modulus of the mean phase vector. "
            "Synchrony rose with colony size on every night.\n", encoding="utf-8")
        self.add(self.temp / "methods-notes.md")
        self.deconstruct()
        methods = self.ours()
        self.assertEqual([(item["section"], item["doc"], item.get("standing")) for item in methods],
                         [("methods", "D1#p2.s1-s2", None), ("methods", "D1#p2.s3", "unchecked")])
        outcome = methods[1]
        moved = inherited.move_passage(self.project, outcome["id"], "results")
        self.assertEqual((moved["section"], moved["moved_from"], moved["doc"], moved["text"]),
                         ("results", outcome["id"], outcome["doc"], outcome["text"]))
        withdrawal = self.passages()[-2]
        self.assertEqual((withdrawal["section"], withdrawal["replaces"], withdrawal["withdrawn"]), ("methods", outcome["id"], True))
        self.assertNotIn("Synchrony rose with colony size", self.section("methods"))
        self.assertIn("Synchrony rose with colony size on every night.{doc:D1#p2.s3} [unchecked]", self.section("results"))
        self.assertEqual(self.record()["deconstructed"]["moves"],
                         [{"passage": outcome["id"], "to_passage": moved["id"], "from": "methods", "to": "results"}])
        index = (self.project / "research" / "DOCUMENTS.md").read_text(encoding="utf-8")
        self.assertIn("- Moved %s from Methods to Results, now %s" % (outcome["id"], moved["id"]), index)
        with self.assertRaises(inherited.InheritedError):
            inherited.move_passage(self.project, outcome["id"], "discussion")  # withdrawn where it stood

    def test_a_separate_documents_front_matter_is_kept_not_deconstructed(self):
        (self.temp / "supplement-notes.md").write_text(
            "Supplementary information for the moth study.\n\nVarga lab, 2023.\n\n# Methods\n\nColonies were filmed at night.\n",
            encoding="utf-8")
        self.add(self.temp / "supplement-notes.md")
        self.deconstruct()
        self.assertEqual([item["text"] for item in self.ours()], ["Colonies were filmed at night.{doc:D1#p4.s1}"])
        self.assertEqual(self.record()["deconstructed"]["kept"], [{"locator": "p1", "part": "front_matter"},
                                                                   {"locator": "p2", "part": "front_matter"}])

    def test_a_supplement_with_no_heading_is_one_unmapped_part_and_its_caption_is_kept(self):
        self.add(MIDWAY / "supplement.pdf")
        done = self.deconstruct()
        self.assertEqual(self.ours(), [])
        self.assertEqual(self.record()["deconstructed"]["kept"], [{"locator": "p1", "part": "caption"}])
        self.assertEqual(done["listed"], ["supplement placed under Results as written: no session placed it"])

    def test_only_results_or_discussion_or_the_other_sections_are_a_move_target(self):
        self.add(MIDWAY / "methods.tex")
        self.deconstruct()
        with self.assertRaises(inherited.InheritedError):
            inherited.move_passage(self.project, self.ours()[0]["id"], "references")
        with self.assertRaises(inherited.InheritedError):
            inherited.move_passage(self.project, self.ours()[0]["id"], "methods")


class NoPandocTest(InheritedCase):
    def test_a_docx_kept_without_pandoc_is_not_deconstructed_and_the_reason_is_listed(self):
        self.add(MIDWAY / "manuscript-v2.docx", tools=self.tools_without("pandoc"))
        with worker.use_fake() as fake:
            done = inherited.deconstruct(self.project, "D1")
            self.assertEqual(fake.calls, [], "nothing to classify")
        self.assertEqual(self.passages(), [])
        self.assertIn("pandoc is not recorded in tools.json", done["reason"])
        self.assertEqual(self.record()["deconstructed"]["reason"], done["reason"])
        index = (self.project / "research" / "DOCUMENTS.md").read_text(encoding="utf-8")
        self.assertIn("- Not deconstructed (version 1): manuscript-v2.docx was kept as given and has no text (not converted: "
                      "pandoc is not recorded in tools.json", index)


class NewerVersionTest(InheritedCase):
    def test_a_newer_version_is_taken_in_like_a_section_edit(self):
        self.add(MIDWAY / "manuscript-v1.docx")
        self.deconstruct()
        before = {item["doc"]: item for item in self.ours()}
        self.add(MIDWAY / "manuscript-v2.docx")
        self.assertEqual(self.record()["version"], 2)
        done = self.deconstruct()
        self.assertEqual((done["new"], done["replaced"], done["withdrawn"], done["retagged"]), (1, 1, 0, 0))
        changed = [item for item in self.ours() if item.get("replaces")]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["replaces"], before["D1#p2.s1"]["id"])
        self.assertTrue(changed[0]["text"].startswith("Lantern moths gather in dusk swarms"))
        added = self.ours()[-1]
        self.assertEqual((added["text"], added["standing"], added["replaces"]), ("Dusk light may be the cue.{doc:D1#p9.s2}", "unchecked", None))
        self.assertNotIn("nightly", self.section("introduction"))
        self.assertIn("Our central finding is that synchrony rises with colony size.{doc:D1#p9.s1} [unchecked] Dusk light may be the cue.",
                      self.section("discussion"))
        self.assertIn("- Deconstructed (version 2)", (self.project / "research" / "DOCUMENTS.md").read_text(encoding="utf-8"))

    NOTES = ("# Introduction\n\nMoths swarm at dusk.\n\n# Results\n\nSynchrony rises with size. It is lowest at dusk.\n\n"
             "The dusk sweep gave R = 0.71.\n\n# Discussion\n\nSize matters.\n")

    def test_removed_text_is_withdrawn_and_a_moved_block_is_tagged_again(self):
        (self.temp / "notes.md").write_text(self.NOTES, encoding="utf-8")
        self.add(self.temp / "notes.md")
        self.deconstruct()
        before = {item["doc"]: item for item in self.ours()}
        newer = self.NOTES.replace("The dusk sweep gave R = 0.71.\n\n", "").replace("# Introduction\n\n", "# Introduction\n\nMoths are old.\n\n")
        (self.temp / "notes-v2.md").write_text(newer, encoding="utf-8")
        self.add(self.temp / "notes-v2.md")
        self.assertEqual(self.record()["version"], 2)
        done = self.deconstruct()
        self.assertEqual((done["new"], done["replaced"], done["withdrawn"], done["retagged"]), (1, 0, 1, 3))
        withdrawal = next(item for item in self.ours() if item.get("withdrawn"))
        self.assertEqual((withdrawal["replaces"], withdrawal["section"]), (before["D1#p5.s1"]["id"], "results"))
        self.assertNotIn("dusk sweep", self.section("results"))
        retagged = next(item for item in self.ours() if item.get("replaces") == before["D1#p4.s2"]["id"])
        self.assertEqual((retagged["doc"], retagged["standing"], retagged["text"]),
                         ("D1#p5.s2", "unchecked", "It is lowest at dusk.{doc:D1#p5.s2}"))
        self.assertIn("Moths are old.{doc:D1#p2.s1} [unchecked]", self.section("introduction"))
        self.assertIn("Synchrony rises with size.{doc:D1#p5.s1} [unchecked] It is lowest at dusk.{doc:D1#p5.s2} [unchecked]\n",
                      self.section("results"))
        self.assertEqual(inherited.deconstruct(self.project, "D1")["written"], [], "taking the same version in again changes nothing")

    def test_unchanged_text_the_newer_version_moves_to_another_section_or_heading_follows_it(self):
        (self.temp / "notes.md").write_text(self.NOTES, encoding="utf-8")
        self.add(self.temp / "notes.md")
        self.deconstruct()
        newer = self.NOTES.replace("\n\n# Discussion\n\nSize matters.\n", "\n\nSize matters.\n").replace("# Introduction", "# Background")
        (self.temp / "notes-v2.md").write_text(newer, encoding="utf-8")
        self.add(self.temp / "notes-v2.md")
        done = self.deconstruct()
        self.assertEqual((done["new"], done["withdrawn"], done["retagged"]), (1, 1, 1))
        self.assertNotIn("Size matters", self.section("discussion"))
        self.assertIn("The dusk sweep gave R = 0.71.{doc:D1#p5.s1} [unchecked]\n\n<!-- wayline:passage", self.section("results"))
        self.assertIn("Size matters.{doc:D1#p6.s1} [unchecked]", self.section("results"))
        self.assertIn("## Background\n\n<!-- wayline:passage", self.section("introduction"))
        self.assertNotIn("## Introduction", self.section("introduction"))

    def test_a_newer_version_kept_without_pandoc_leaves_the_earlier_passages_and_says_so(self):
        self.add(MIDWAY / "manuscript-v1.docx")
        self.deconstruct()
        self.add(MIDWAY / "manuscript-v2.docx", tools=self.tools_without("pandoc"))
        done = inherited.deconstruct(self.project, "D1")
        self.assertEqual(len(self.ours()), 9, "nothing written, nothing withdrawn")
        record = self.record()["deconstructed"]
        self.assertEqual((record["version"], record["passages"], record["claims"]), (2, 9, 6))
        self.assertIn("the inherited passages of version 1 stand", done["reason"])

    def test_a_claim_a_ticket_already_answered_keeps_its_answer_when_the_document_changes_around_it(self):
        self.add(MIDWAY / "manuscript-v1.docx")
        self.deconstruct()
        claim = next(item for item in self.ours() if item["doc"] == "D1#p4.s2")
        sections.file_finding(self.project, {"id": "t4-a1-f1", "ticket": 4, "text": "R is lowest at dusk in 38 of 40 colonies.",
                                             "provenance": ["results/dusk.json#min_r"], "negative": False, "heading": "Results",
                                             "replaces": claim["id"], "evidence": "narrows", "objectives": [],
                                             })
        self.add(MIDWAY / "manuscript-v2.docx")
        self.deconstruct()
        self.assertIn("R is lowest at dusk in 38 of 40 colonies.", self.section("results"))
        self.assertNotIn("lowest at dusk across every colony", self.section("results"))


class VerbTest(InheritedCase):
    def test_the_session_deconstructs_places_and_moves_through_the_verb(self):
        (self.temp / "study.md").write_text(HeadingsTest.PAPER, encoding="utf-8")
        self.add(self.temp / "study.md")
        with worker.use_fake() as fake:
            fake.script(respond=Classifier(), role="classifier")
            code, out, err = run_verb("document", "deconstruct", "D1", "--place", "Field notes=discussion",
                                      "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("D1 version 1: 8 new, 0 replaced, 0 withdrawn, 0 tagged again", out)
        notes = next(item for item in self.ours() if item["heading"] == "Field notes")
        self.assertEqual(notes["section"], "discussion")
        code, out, err = run_verb("document", "move", notes["id"], "results", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("moved %s from Discussion to Results" % notes["id"], out)
        code, out, err = run_verb("document", "deconstruct", "D1", "--place", "Field notes", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("<heading or locator>=<section>", err)


class HeadingsTest(InheritedCase):
    def add_text(self, name, text):
        (self.temp / name).write_text(text, encoding="utf-8")
        return self.add(self.temp / name)[0]["id"]

    PAPER = ("# A study of moths\n\nAn author, an affiliation.\n\n## Background\n\nMoths swarm at dusk.\n\n"
             "## Materials & Methods\n\nColonies were filmed.\n\n### Model\n\nThe model couples phases.\n\n"
             "## 3. Results and Discussion\n\nSynchrony rises with size.\n\n## Conclusions\n\nSize matters.\n\n"
             "## Field notes\n\nThe lamps flickered.\n\n### Night two\n\nRain fell.\n\n"
             "## Data availability\n\nAll data are in data/.\n\n## Outlook\n\nMore colonies come next.\n")

    def test_the_heading_table_maps_and_a_subheading_follows_its_parent(self):
        document_id = self.add_text("study.md", self.PAPER)
        self.deconstruct(document_id)
        placed = [(item["heading"], item["section"]) for item in self.ours(document_id)]
        self.assertEqual(placed, [("Background", "introduction"), ("Materials & Methods", "methods"), ("Model", "methods"),
                                  ("3. Results and Discussion", "results"), ("Conclusions", "discussion"),
                                  ("Field notes", "results"), ("Night two", "results"), ("Outlook", "discussion")])
        texts = " ".join(item["text"] for item in self.passages())
        self.assertNotIn("All data are in data/", texts, "an availability statement is kept, never deconstructed")
        self.assertNotIn("An author", texts, "front matter before the first heading is kept")
        record = self.record(document_id)["deconstructed"]
        self.assertIn({"locator": "p1", "text": "A study of moths", "to": "kept", "by": "title"}, record["headings"])
        self.assertIn({"locator": "p7", "text": "Model", "to": "methods", "by": "parent"}, record["headings"])

    def test_an_unmapped_heading_with_no_session_lands_under_results_as_written_and_is_listed(self):
        document_id = self.add_text("study.md", self.PAPER)
        done = self.deconstruct(document_id)
        self.assertIn("Field notes placed under Results as written: no session placed it", done["listed"])
        self.assertEqual([heading["text"] for heading in self.record(document_id)["deconstructed"]["headings"] if heading["by"] == "default"],
                         ["Field notes"], "its subheading follows it and is not listed again")
        index = (self.project / "research" / "DOCUMENTS.md").read_text(encoding="utf-8")
        self.assertIn("- Placed under Results as written, no session placed them: `%s#p13` Field notes" % document_id, index)

    def test_the_setup_session_places_an_unmapped_heading(self):
        document_id = self.add_text("study.md", self.PAPER)
        done = self.deconstruct(document_id, places={"Field notes": "discussion"})
        self.assertEqual([item["section"] for item in self.ours(document_id) if item["heading"] in ("Field notes", "Night two")],
                         ["discussion", "discussion"])
        self.assertEqual(done["listed"], [])
        self.assertIn({"locator": "p13", "text": "Field notes", "to": "discussion", "by": "session"},
                      self.record(document_id)["deconstructed"]["headings"])

    def test_under_an_unmapped_top_heading_a_heading_the_table_maps_goes_by_the_table(self):
        document_id = self.add_text("draft.md", "# Draft\n\nAn author.\n\n# Lantern moth synchrony in dusk swarms\n\n"
                                                "A claim before any section.\n\n## Introduction\n\nMoths swarm.\n\n"
                                                "## Methods\n\nColonies were filmed.\n\n## Asides\n\nA claim aside.\n")
        self.deconstruct(document_id)
        self.assertEqual([(item["heading"], item["section"]) for item in self.ours(document_id)],
                         [("Lantern moth synchrony in dusk swarms", "results"), ("Introduction", "introduction"),
                          ("Methods", "methods"), ("Asides", "results")])

    def test_a_place_that_places_nothing_is_refused_before_anything_is_written(self):
        document_id = self.add_text("study.md", self.PAPER)
        for places in ({"Feild notes": "discussion"}, {"Model": "results"}, {"Background": "discussion"}):
            with self.subTest(places=places), self.assertRaises(inherited.InheritedError) as raised:
                inherited.deconstruct(self.project, document_id, places=places)
            self.assertIn("places no heading", str(raised.exception))
        self.assertEqual(self.passages(), [])

    def test_the_session_can_place_a_subheading_of_an_unmapped_heading(self):
        document_id = self.add_text("study.md", self.PAPER)
        self.deconstruct(document_id, places={"p15": "methods"})
        self.assertEqual([(item["heading"], item["section"]) for item in self.ours(document_id) if item["heading"] in ("Field notes", "Night two")],
                         [("Field notes", "results"), ("Night two", "methods")])

    def test_a_place_outside_the_sections_is_refused(self):
        document_id = self.add_text("study.md", self.PAPER)
        with self.assertRaises(inherited.InheritedError):
            inherited.deconstruct(self.project, document_id, places={"Field notes": "references"})

    def test_a_document_not_sorted_inherited_is_refused(self):
        (self.temp / "referee.md").write_text("# Report\n\nThe claims are overstated.\n", encoding="utf-8")
        self.add(self.temp / "referee.md", kind="critique")
        with self.assertRaises(inherited.InheritedError) as raised:
            inherited.deconstruct(self.project, "D1")
        self.assertIn("only an inherited document is deconstructed", str(raised.exception))
