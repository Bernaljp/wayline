"""The manifest, findings provenance, and the commit-threshold check (ticket 18)."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from wayline.jsonschema import ValidationError
from wayline.ledger import Ledger
from wayline.provenance import (
    ProvenanceError, commit_threshold_bytes, oversized_tracked_files, read_manifest, register_artifact, sha256_of,
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
