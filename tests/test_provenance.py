"""The manifest, findings provenance, and the commit-threshold check (ticket 18)."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from wayline.jsonschema import ValidationError
from wayline.ledger import Ledger
from wayline.provenance import (
    ProvenanceError, add_finding, commit_threshold_bytes, oversized_tracked_files,
    read_findings, read_manifest, register_artifact, render_findings, sha256_of,
)


class ProvenanceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.book = Ledger(self.project)

    def tearDown(self):
        self.temp.cleanup()

    def write_result(self, relative, text="hello\n"):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class RegisterArtifactTest(ProvenanceCase):
    def test_writes_a_manifest_entry_and_journals_it(self):
        self.write_result("results/summary.json", '{"auroc": 0.8}')
        entry = register_artifact(self.book, "results/summary.json", "j-0001", "t3-a1", 3)
        self.assertEqual(entry["path"], "results/summary.json")
        self.assertEqual(entry["job"], "j-0001")
        self.assertEqual(entry["run_id"], "t3-a1")
        self.assertEqual(entry["ticket"], 3)
        self.assertEqual(entry["size"], (self.project / "results/summary.json").stat().st_size)
        self.assertEqual(entry["sha256"], sha256_of(self.project / "results/summary.json"))

        manifest = read_manifest(self.book)
        self.assertEqual(manifest["entries"], [entry])

        events, _ = self.book.read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "manifest")
        self.assertEqual(events[0]["ticket"], 3)
        self.assertEqual(events[0]["payload"], {
            "path": "results/summary.json", "sha256": entry["sha256"], "size": entry["size"],
            "job": "j-0001", "run_id": "t3-a1",
        })

    def test_a_job_less_registration_takes_a_null_job(self):
        self.write_result("results/notes.txt")
        entry = register_artifact(self.book, "results/notes.txt", None, "t1-a1", 1)
        self.assertIsNone(entry["job"])

    def test_reregistering_the_same_path_replaces_its_entry(self):
        path = self.write_result("results/summary.json", "v1")
        first = register_artifact(self.book, "results/summary.json", None, "t1-a1", 1)
        path.write_text("v2", encoding="utf-8")
        second = register_artifact(self.book, "results/summary.json", None, "t1-a2", 1)
        manifest = read_manifest(self.book)
        self.assertEqual(len(manifest["entries"]), 1)
        self.assertEqual(manifest["entries"][0], second)
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_a_project_path_works_as_well_as_a_ledger(self):
        self.write_result("results/summary.json")
        entry = register_artifact(self.project, "results/summary.json", None, "t1-a1", 1)
        self.assertEqual(read_manifest(self.project)["entries"], [entry])

    def test_refuses_a_missing_file(self):
        with self.assertRaises(ProvenanceError):
            register_artifact(self.book, "results/nowhere.json", None, "t1-a1", 1)

    def test_refuses_a_path_outside_the_project(self):
        self.write_result("results/summary.json")
        with self.assertRaises(ProvenanceError):
            register_artifact(self.book, "/etc/passwd", None, "t1-a1", 1)
        with self.assertRaises(ProvenanceError):
            register_artifact(self.book, "../summary.json", None, "t1-a1", 1)

    def test_refuses_a_malformed_run_id(self):
        self.write_result("results/summary.json")
        with self.assertRaises(ProvenanceError):
            register_artifact(self.book, "results/summary.json", None, "run-3", 3)

    def test_a_bad_entry_never_lands_in_the_manifest(self):
        # ticket 0 fails the schema's minimum; the write must not happen at all.
        self.write_result("results/summary.json")
        with self.assertRaises(ValidationError):
            register_artifact(self.book, "results/summary.json", None, "t0-a1", 0)
        self.assertEqual(read_manifest(self.book), {"entries": []})


class AddFindingTest(ProvenanceCase):
    def register(self, relative="results/summary.json", run_id="t2-a1", ticket=2):
        self.write_result(relative)
        return register_artifact(self.book, relative, None, run_id, ticket)

    def test_an_accepted_finding_gets_a_sequential_id_and_is_journaled(self):
        self.register()
        finding = add_finding(self.book, "The metric improved.", "results/summary.json#auroc", 2, negative=False)
        self.assertEqual(finding["id"], "f-0001")
        self.assertEqual(finding["provenance"], ["results/summary.json#auroc"])
        self.assertFalse(finding["negative"])

        second = add_finding(self.book, "A second finding.", ["results/summary.json#loss"], 2)
        self.assertEqual(second["id"], "f-0002")

        stored = read_findings(self.book)
        self.assertEqual([entry["id"] for entry in stored], ["f-0001", "f-0002"])

        events, _ = self.book.read_events()
        finding_events = [event for event in events if event["event"] == "finding"]
        self.assertEqual(len(finding_events), 2)
        self.assertEqual(finding_events[0]["payload"]["id"], "f-0001")
        self.assertEqual(finding_events[0]["ticket"], 2)

    def test_negative_findings_are_accepted_and_marked(self):
        self.register()
        finding = add_finding(self.book, "No improvement over baseline.", "results/summary.json#auroc", 2, negative=True)
        self.assertTrue(finding["negative"])

    def test_refuses_a_provenance_locator_with_no_hash(self):
        self.register()
        with self.assertRaises(ProvenanceError):
            add_finding(self.book, "text", "results/summary.json", 2)

    def test_refuses_an_empty_locator_half(self):
        self.register()
        with self.assertRaises(ProvenanceError):
            add_finding(self.book, "text", "results/summary.json#", 2)

    def test_refuses_an_unmanifested_artifact(self):
        with self.assertRaises(ProvenanceError):
            add_finding(self.book, "text", "results/ghost.json#auroc", 2)

    def test_refuses_an_empty_provenance_list(self):
        self.register()
        with self.assertRaises(ProvenanceError):
            add_finding(self.book, "text", [], 2)

    def test_a_refused_finding_writes_nothing(self):
        with self.assertRaises(ProvenanceError):
            add_finding(self.book, "text", "results/ghost.json#auroc", 2)
        self.assertEqual(read_findings(self.book), [])
        events, _ = self.book.read_events()
        self.assertEqual(events, [])

    def test_one_finding_may_cite_more_than_one_artifact(self):
        self.register("results/a.json", "t2-a1", 2)
        self.register("results/b.json", "t2-a1", 2)
        finding = add_finding(self.book, "text", ["results/a.json#x", "results/b.json#y"], 2)
        self.assertEqual(finding["provenance"], ["results/a.json#x", "results/b.json#y"])

    def test_refuses_when_any_of_several_locators_is_unmanifested(self):
        self.register("results/a.json", "t2-a1", 2)
        with self.assertRaises(ProvenanceError):
            add_finding(self.book, "text", ["results/a.json#x", "results/ghost.json#y"], 2)
        self.assertEqual(read_findings(self.book), [])


class RenderFindingsTest(ProvenanceCase):
    def test_renders_none_yet_for_an_empty_ledger(self):
        render_findings(self.book)
        text = (self.book.research / "findings.md").read_text(encoding="utf-8")
        self.assertIn("None yet.", text)

    def test_is_grouped_by_ticket_and_marks_negative_results(self):
        self.write_result("results/a.json")
        register_artifact(self.book, "results/a.json", None, "t2-a1", 2)
        self.write_result("results/b.json")
        register_artifact(self.book, "results/b.json", None, "t5-a1", 5)
        add_finding(self.book, "Ticket 2's finding.", "results/a.json#x", 2)
        add_finding(self.book, "Ticket 5's finding, discarded.", "results/b.json#y", 5, negative=True)

        text = (self.book.research / "findings.md").read_text(encoding="utf-8")
        self.assertLess(text.index("Ticket 2"), text.index("Ticket 5"))
        self.assertIn("f-0001", text)
        self.assertIn("Ticket 2's finding.", text)
        self.assertIn("(negative)", text)
        self.assertIn("Ticket 5's finding, discarded.", text)

    def test_add_finding_keeps_findings_md_in_step_with_findings_jsonl(self):
        self.write_result("results/a.json")
        register_artifact(self.book, "results/a.json", None, "t2-a1", 2)
        add_finding(self.book, "First.", "results/a.json#x", 2)
        first_text = (self.book.research / "findings.md").read_text(encoding="utf-8")
        add_finding(self.book, "Second.", "results/a.json#y", 2)
        second_text = (self.book.research / "findings.md").read_text(encoding="utf-8")
        self.assertIn("First.", first_text)
        self.assertNotIn("Second.", first_text)
        self.assertIn("First.", second_text)
        self.assertIn("Second.", second_text)


class CommitThresholdTest(ProvenanceCase):
    def test_the_shipped_default_is_read_when_the_project_has_no_override(self):
        default = commit_threshold_bytes(self.project)
        self.assertIsInstance(default, int)
        self.assertGreater(default, 0)

    def test_a_project_harness_json_overrides_the_default(self):
        (self.project / "harness.json").write_text(
            json.dumps({"policy": {"artifacts": {"commit_threshold_bytes": 42}}}), encoding="utf-8",
        )
        self.assertEqual(commit_threshold_bytes(self.project), 42)


class OversizedTrackedFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self._git("init", "-q")
        self._git("config", "user.email", "wayline@localhost")
        self._git("config", "user.name", "wayline")

    def tearDown(self):
        self.temp.cleanup()

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def _commit(self, relative, size):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        self._git("add", relative)
        self._git("commit", "-q", "-m", "add " + relative)

    def test_a_tracked_file_over_the_threshold_is_warned_about(self):
        self._commit("big.bin", 100)
        warnings = oversized_tracked_files(self.project, threshold=50)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["path"], "big.bin")
        self.assertEqual(warnings[0]["size"], 100)
        self.assertIn("manifest", warnings[0]["note"])

    def test_a_tracked_file_under_the_threshold_is_not_warned_about(self):
        self._commit("small.bin", 10)
        self.assertEqual(oversized_tracked_files(self.project, threshold=50), [])

    def test_an_untracked_heavy_file_is_not_warned_about(self):
        self._commit("small.bin", 10)
        (self.project / "results").mkdir()
        (self.project / "results" / "heavy.bin").write_bytes(b"x" * 1000)
        self.assertEqual(oversized_tracked_files(self.project, threshold=50), [])

    def test_the_threshold_defaults_to_the_policy_value(self):
        self._commit("small.bin", 10)
        self.assertEqual(oversized_tracked_files(self.project), [])
