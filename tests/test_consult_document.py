"""The consultant over one document (Implementation Decision 17; ticket 94).

Documents are kept by `add_documents` against the recorded tool runs of ticket 84 (synthetic
documents from `fixtures/midway/`); the consultant runs over the fake launcher. Each test reads back
what a later session sees: the chunk files under `research/documents/<id>/chunks/`, the answer's
locators, `qa_log.md`, and the journal.
"""

import json
import re
import unittest

from tests.test_documents import MIDWAY, DocumentsCase, run_verb
from wayline import consult, worker
from wayline.documents import DocumentError, chunk_document
from wayline.ledger import Ledger
from wayline.worker import Envelope

QUESTION = "What does the Methods section say about the sampling interval?"


def answer(**fields):
    value = {"answer": "Frames were taken at dusk.", "locators": ["p9"], "confidence": 0.8,
             "not_in_source": False, "promote_requested": False}
    value.update(fields)
    return value


class ConsultDocumentCase(DocumentsCase):
    def setUp(self):
        super().setUp()
        self.fake = self.enterContext(worker.use_fake())
        self.add(MIDWAY / "manuscript-v2.docx")

    def ask(self, question=QUESTION, key="D1", ticket=None, **fields):
        self.fake.script(Envelope(session_id="doc-session", structured_output=answer(**fields)), role="consultant")
        return consult.ask(self.project, key, question, ticket=ticket)

    def chunk_text(self, chunk, document_id="D1"):
        return (self.directory(document_id) / "chunks" / (chunk["id"] + ".md")).read_text(encoding="utf-8")

    def consulted(self):
        return [event for event in Ledger(self.project).read_events()[0] if event["event"] == "consulted"]


class ChunkingTest(ConsultDocumentCase):
    def test_a_document_is_cut_into_chunks_of_whole_blocks_under_the_cap_each_naming_its_anchors(self):
        manifest = chunk_document(self.project, "D1", max_chars=400)
        self.assertGreater(len(manifest["chunks"]), 1)
        anchors = re.findall(r'<a id="(p\d+)"></a>', self.text())
        seen = []
        for chunk in manifest["chunks"]:
            found = re.findall(r'<a id="(p\d+)"></a>', self.chunk_text(chunk))
            self.assertEqual(found, [locator for locator in chunk["locators"] if locator != "front"])
            seen += found
            if len(found) > 1:
                self.assertLessEqual(chunk["chars"], 400)
        self.assertEqual(seen, anchors, "every block lands in exactly one chunk, in reading order")
        self.assertIn("Dusk light may be the cue.", "".join(self.chunk_text(chunk) for chunk in manifest["chunks"]))

    def test_the_front_matter_is_the_first_block_under_the_locator_front(self):
        manifest = chunk_document(self.project, "D1", max_chars=20000)
        self.assertEqual(manifest["chunks"][0]["locators"][0], "front")
        self.assertIn("Wingbeat synchrony in captive lantern moth colonies", self.chunk_text(manifest["chunks"][0]))

    def test_chunks_are_kept_while_the_text_is_unchanged_and_rebuilt_when_the_text_changes(self):
        first = chunk_document(self.project, "D1", max_chars=400)
        stamp = (self.directory() / "chunks.json").stat().st_mtime_ns
        chunk_document(self.project, "D1", max_chars=400)
        self.assertEqual((self.directory() / "chunks.json").stat().st_mtime_ns, stamp)
        (self.directory() / "text.md").write_text(self.text() + '\n<a id="p999"></a>\n\nA new closing block.\n', encoding="utf-8")
        again = chunk_document(self.project, "D1", max_chars=400)
        self.assertNotEqual(again["text_sha256"], first["text_sha256"])
        self.assertEqual(again["chunks"][-1]["locators"][-1], "p999")

    def test_a_smaller_cap_rebuilds_and_leaves_no_stale_chunk_file(self):
        wide = chunk_document(self.project, "D1", max_chars=20000)
        narrow = chunk_document(self.project, "D1", max_chars=300)
        self.assertGreater(len(narrow["chunks"]), len(wide["chunks"]))
        names = sorted(path.name for path in (self.directory() / "chunks").iterdir())
        self.assertEqual(names, sorted(chunk["id"] + ".md" for chunk in narrow["chunks"]))

    def test_an_unknown_document_and_one_with_no_text_are_refused(self):
        with self.assertRaisesRegex(DocumentError, "no document D9"):
            chunk_document(self.project, "D9")
        (self.directory() / "text.md").unlink()
        with self.assertRaisesRegex(DocumentError, "D1 has no text yet"):
            chunk_document(self.project, "D1")


class VersionTest(DocumentsCase):
    def test_a_newer_version_taken_in_replaces_the_chunks_with_ones_cut_from_its_text(self):
        self.add(MIDWAY / "manuscript-v1.docx")
        before = chunk_document(self.project, "D1")
        self.assertNotIn("gather in dusk swarms", "".join(
            (self.directory() / "chunks" / (chunk["id"] + ".md")).read_text(encoding="utf-8") for chunk in before["chunks"]))
        self.add(MIDWAY / "manuscript-v2.docx")
        self.assertEqual(self.record()["version"], 2)
        self.assertFalse((self.directory() / "chunks").exists(), "the old version's chunks are dropped with its other files")
        after = chunk_document(self.project, "D1")
        self.assertNotEqual(after["text_sha256"], before["text_sha256"])
        self.assertEqual(after["version"], 2)
        self.assertIn("gather in dusk swarms", "".join(
            (self.directory() / "chunks" / (chunk["id"] + ".md")).read_text(encoding="utf-8") for chunk in after["chunks"]))


class AskTest(ConsultDocumentCase):
    def test_the_consultant_is_launched_over_the_document_directory_and_its_locators_name_block_anchors(self):
        report = self.ask()
        self.assertEqual(report["answer"]["locators"], ["p9"])
        request = self.fake.calls[0].request
        self.assertEqual([str(path) for path in request.add_dirs], [str(self.directory())])
        self.assertIn("document `D1`", request.prompt)
        self.assertIn("chunks.json", request.prompt)
        self.assertEqual(request.allowed_tools, ["Read", "Glob", "Grep"])
        self.assertTrue((self.directory() / "chunks.json").is_file(), "the chunks exist by the time the consultant reads")

    def test_the_exchange_is_logged_beside_the_document_and_journaled(self):
        self.ask()
        log = (self.directory() / "qa_log.md").read_text(encoding="utf-8")
        lines = [line for line in log.splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("Q: " + QUESTION, lines[0])
        self.assertIn("Locators: p9", lines[0])
        self.assertEqual([(event["payload"]["slug"], event["payload"]["by"]) for event in self.consulted()], [("D1", "cli")])

    def test_a_promotion_request_on_a_document_is_ignored_for_a_document_has_no_levels(self):
        self.assertIsNone(self.ask(promote_requested=True)["promotion"])
        self.assertNotIn("promotion requested", (self.directory() / "qa_log.md").read_text(encoding="utf-8"))
        self.assertFalse(self.consulted()[0]["payload"]["promote_requested"])

    def test_the_ticket_limit_counts_document_questions_and_refuses_the_one_past_it(self):
        limit = consult.question_limit({})
        for number in range(limit):
            self.ask(question="Question %d?" % number, ticket=7)
        calls = len(self.fake.calls)
        with self.assertRaises(consult.ConsultRefused):
            self.ask(question="One too many?", ticket=7)
        self.assertEqual(len(self.fake.calls), calls, "refused before a session starts")
        self.assertEqual(len(self.consulted()), limit)

    def test_a_refused_question_leaves_the_documents_directory_as_it_was(self):
        for number in range(consult.question_limit({})):
            self.ask(question="Question %d?" % number, ticket=7)
        chunks = self.directory() / "chunks.json"
        chunks.unlink()
        with self.assertRaises(consult.ConsultRefused):
            self.ask(question="One too many?", ticket=7)
        self.assertFalse(chunks.exists())

    def test_an_unknown_document_and_one_with_no_text_are_refused_before_a_session_starts(self):
        with self.assertRaisesRegex(consult.ConsultError, "no document D9"):
            self.ask(key="D9")
        (self.directory() / "text.md").unlink()
        with self.assertRaisesRegex(consult.ConsultError, "D1 has no text yet"):
            self.ask()
        self.assertEqual(self.fake.calls, [])

    def test_the_verb_takes_a_document_id_and_refuses_an_unknown_one_in_one_line(self):
        code, _, err = run_verb("consult", "D9", "Anything?", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn("no document D9", err)


if __name__ == "__main__":
    unittest.main()
