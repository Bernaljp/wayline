"""Results: findings cluster into results at acceptance, and the owner merges or renames them (decision 17; ticket 90).

The seams are the ledger over a temporary project (findings filed through `sections.file_finding`, merges and renames
through `wayline result`, asserting on `research/results.json`, the journal, and the rendered Results section) and
replayed journals, which rebuild the same clustering from the `finding` and `result` events alone.
"""

import io
import json
from contextlib import redirect_stderr, redirect_stdout

from tests.projects import ProjectTestCase
from wayline import cli, results, sections
from wayline import project as projects
from wayline.ledger import Ledger, LedgerError


def file(ledger, identifier, text, heading, replaces=None, objectives=(), negative=False, ticket=2,
         provenance=("results/summary.json#auroc",)):
    """One finding through the ledger call the conductor makes at acceptance."""
    return sections.file_finding(ledger, {"id": identifier, "ticket": ticket, "text": text, "provenance": list(provenance),
                                          "negative": negative, "heading": heading, "replaces": replaces,
                                          "objectives": list(objectives)})


class ResultsCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "results-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71, "loss": 0.25}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)

    def events(self, name):
        return [event for event in self.ledger.read_events()[0] if event["event"] == name]

    def record(self):
        return json.loads((self.project / "research" / "results.json").read_text(encoding="utf-8"))

    def results_body(self):
        return (self.project / "research" / "sections" / "results.md").read_text(encoding="utf-8").split("\n", 1)[1]


class ClusteringAtAcceptanceTest(ResultsCase):
    def test_a_new_heading_gets_the_next_r_id_and_a_reused_one_joins_it(self):
        first = file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", "Do the products raise the AUROC?", objectives=["O1"])
        second = file(self.ledger, "t2-a1-f2", "The loss falls to 0.25.", "Does the loss fall?", objectives=["O2"])
        third = file(self.ledger, "t3-a1-f1", "The rise holds on split B.", "Do the products raise the AUROC?", objectives=["O3"])
        self.assertEqual((first["result"], second["result"], third["result"]), ("R1", "R2", "R1"))
        record = self.record()
        self.assertEqual([(item["id"], item["heading"]) for item in record["results"]],
                         [("R1", "Do the products raise the AUROC?"), ("R2", "Does the loss fall?")])
        created = [event["payload"] for event in self.events("result")]
        self.assertEqual([(payload["id"], payload["action"], payload["heading"], payload["by"]) for payload in created],
                         [("R1", "created", "Do the products raise the AUROC?", "code"), ("R2", "created", "Does the loss fall?", "code")])
        self.assertEqual([event["payload"]["result"] for event in self.events("finding")], ["R1", "R2", "R1"])
        view = results.read_results(self.project)
        self.assertEqual([(result.id, result.objectives) for result in view], [("R1", ["O1", "O3"]), ("R2", ["O2"])])

    def test_a_heading_reused_with_other_spacing_or_case_joins_the_same_result(self):
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", "Do the products raise the AUROC?")
        again = file(self.ledger, "t3-a1-f1", "The rise holds.", "  do the products   raise the AUROC? ")
        self.assertEqual(again["result"], "R1")

    def test_a_finding_replacing_a_finding_joins_its_result_under_another_heading(self):
        first = file(self.ledger, "t2-a1-f1", "The products raise the AUROC on every split.", "Do the products raise the AUROC?",
                     objectives=["O1"])
        file(self.ledger, "t2-a1-f2", "The loss falls to 0.25.", "Does the loss fall?")
        narrowed = file(self.ledger, "t5-a1-f1", "The products raise the AUROC on split B only.", "Where do the products help?",
                        replaces=first["id"], objectives=["O4"])
        self.assertEqual(narrowed["result"], "R1")
        view = {result.id: result for result in results.read_results(self.project)}
        self.assertEqual([finding["id"] for finding in view["R1"].current], ["t5-a1-f1"])
        self.assertEqual(view["R1"].objectives, ["O4"], "a result's objectives are the union of its current findings'")
        body = self.results_body()
        self.assertIn("## Do the products raise the AUROC?\n", body)
        self.assertNotIn("Where do the products help?", body, "the Results section renders the result's heading")


class ReplayTest(ResultsCase):
    """Recorded journals replayed: the clustering is rebuilt from the `finding` and `result` events alone."""

    @staticmethod
    def finding(identifier, heading, replaces=None, objectives=()):
        return {"event": "finding", "payload": {"id": identifier, "ticket": 2, "text": "x", "provenance": ["a.json#b"],
                                                "negative": False, "heading": heading, "replaces": replaces,
                                                "objectives": list(objectives)}}

    def test_clustering_by_heading(self):
        journal = [self.finding("F1", "Does A hold?"), self.finding("F2", "Does B hold?"), self.finding("F3", "does a hold?"),
                   {"event": "wave", "payload": {"number": 1}}, self.finding("F4", "Does C hold?")]
        replayed = results.replay(journal)
        self.assertEqual(replayed.of, {"F1": "R1", "F2": "R2", "F3": "R1", "F4": "R3"})
        self.assertEqual([(item["id"], item["heading"]) for item in replayed.record()["results"]],
                         [("R1", "Does A hold?"), ("R2", "Does B hold?"), ("R3", "Does C hold?")])

    def test_clustering_by_replaces_follows_a_chain_of_scope_downs(self):
        journal = [self.finding("F1", "Does A hold?"), self.finding("F2", "Where does A hold?", replaces="F1"),
                   self.finding("F3", "When does A hold?", replaces="F2"), self.finding("F4", "Where does A hold?")]
        self.assertEqual(results.replay(journal).of, {"F1": "R1", "F2": "R1", "F3": "R1", "F4": "R2"},
                         "a replacement joins the result of what it replaces; its own heading names no result")

    def test_a_merge_and_a_rename_replay_in_their_place(self):
        journal = [self.finding("F1", "Does A hold?"), self.finding("F2", "Does B hold?"),
                   {"event": "result", "payload": {"id": "R2", "action": "merged", "into": "R1", "heading": "Does B hold?", "by": "owner"}},
                   self.finding("F3", "Does B hold?"),
                   {"event": "result", "payload": {"id": "R1", "action": "renamed", "heading": "Do A and B hold?",
                                                   "from": "Does A hold?", "by": "owner"}},
                   self.finding("F4", "Does A hold?"), self.finding("F5", "Do A and B hold?")]
        replayed = results.replay(journal)
        self.assertEqual({finding: replayed.resolve(result) for finding, result in replayed.of.items()},
                         {"F1": "R1", "F2": "R1", "F3": "R1", "F4": "R1", "F5": "R1"})
        self.assertEqual([(item["id"], item["heading"], item["merged_into"]) for item in replayed.record()["results"]],
                         [("R1", "Do A and B hold?", None), ("R2", "Does B hold?", "R1")])

    def test_the_project_journal_replays_to_the_record_written_at_acceptance(self):
        first = file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", "Do the products raise the AUROC?")
        file(self.ledger, "t2-a1-f2", "The loss falls to 0.25.", "Does the loss fall?")
        file(self.ledger, "t3-a1-f1", "On split B only.", "Where?", replaces=first["id"])
        results.merge(self.project, "R2", "R1")
        replayed = results.replay(self.ledger.read_events()[0])
        self.assertEqual([{key: item[key] for key in ("id", "heading", "headings", "merged_into")} for item in replayed.record()["results"]],
                         [{key: item[key] for key in ("id", "heading", "headings", "merged_into")} for item in self.record()["results"]])


class MergeAndRenameTest(ResultsCase):
    def setUp(self):
        super().setUp()
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", "Do the products raise the AUROC?", objectives=["O1"])
        file(self.ledger, "t2-a1-f2", "The loss falls to 0.25.", "Does the loss fall?", objectives=["O2"])

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["result", *args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def test_a_merge_is_journaled_and_the_merged_results_findings_join_the_other(self):
        code, out, err = self.run_cli("merge", "R2", "R1")
        self.assertEqual(code, 0, err)
        self.assertIn("R2", out)
        payload = self.events("result")[-1]["payload"]
        self.assertEqual((payload["id"], payload["action"], payload["into"], payload["by"]), ("R2", "merged", "R1", "owner"))
        self.assertEqual(self.record()["results"][1]["merged_into"], "R1")
        view = results.read_results(self.project)
        self.assertEqual([result.id for result in view], ["R1"])
        self.assertEqual([finding["id"] for finding in view[0].current], ["t2-a1-f1", "t2-a1-f2"])
        self.assertEqual(view[0].objectives, ["O1", "O2"])
        body = self.results_body()
        self.assertNotIn("## Does the loss fall?", body)
        self.assertIn("The loss falls to 0.25.", body)
        later = file(self.ledger, "t4-a1-f1", "The loss falls further.", "Does the loss fall?")
        self.assertEqual(later["result"], "R1", "a finding under the merged result's heading joins the result it went into")
        report = [event for event in self.events("report_rendered") if not event["payload"].get("report")]
        self.assertTrue(report, "the merge re-renders the general report")

    def test_a_rename_is_journaled_and_the_results_section_uses_the_new_heading(self):
        code, _, err = self.run_cli("rename", "R1", "Where do the products help?")
        self.assertEqual(code, 0, err)
        payload = self.events("result")[-1]["payload"]
        self.assertEqual((payload["id"], payload["action"], payload["heading"], payload["from"]),
                         ("R1", "renamed", "Where do the products help?", "Do the products raise the AUROC?"))
        body = self.results_body()
        self.assertIn("## Where do the products help?\n", body)
        self.assertNotIn("## Do the products raise the AUROC?", body)
        self.assertEqual(file(self.ledger, "t4-a1-f1", "Still.", "Do the products raise the AUROC?")["result"], "R1",
                         "the old heading still names the result it named")

    def test_what_cannot_be_merged_or_renamed_is_refused_and_writes_nothing(self):
        before = self.record()
        for args in (("merge", "R1", "R1"), ("merge", "R9", "R1"), ("merge", "R1", "R9"), ("rename", "R9", "x"),
                     ("rename", "R1", "  "), ("rename", "R1", "Does the loss fall?")):
            with self.subTest(args=args):
                code, _, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                self.assertTrue(err.strip())
        results.merge(self.project, "R2", "R1")
        with self.assertRaises(results.ResultError):
            results.merge(self.project, "R1", "R2")
        self.assertEqual(len(self.record()["results"]), len(before["results"]))

    def test_the_ledger_refuses_a_result_event_outside_its_vocabulary(self):
        with self.assertRaises(LedgerError):
            self.ledger.append_event("result", {"id": "R1", "action": "split", "heading": "x", "by": "owner"})
