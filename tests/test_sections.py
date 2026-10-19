"""The paper's five sections and the passages that make them (decision 17; ticket 86).

The seam is the ledger over a temporary project: passages and findings go in through the ledger call,
and what is asserted is what lands in `research/passages.jsonl`, `findings.jsonl`, the journal, and the
rendered files under `research/sections/`.
"""

import io
import json

from tests import machine
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, hold_the_ladder, patch
from wayline import project as projects
from wayline import resources, sections, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger, LedgerError


class SectionsCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "paper-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)

    def text(self, section):
        return (self.project / "research" / "sections" / ("%s.md" % section)).read_text(encoding="utf-8")

    def body(self, section):
        """The rendered file below its first-line render stamp."""
        return self.text(section).split("\n", 1)[1]

    def events(self, name):
        return [event for event in self.ledger.read_events()[0] if event["event"] == name]

    def passages(self):
        path = self.project / "research" / "passages.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TwoTicketsCase(ConductorCase):
    """The one-ticket fixture with a second ticket beside it: both `code`, both declaring Methods, disjoint touch sets."""

    def setUp(self):
        super().setUp()
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, sections=["methods"], objectives=["O1"]), body)
        second = dict(fields, id=2, title="Write the world file", touches=["world.txt"], outputs=["world.txt"], sections=["methods"],
                      acceptance={"machine": ["grep -qx world world.txt"], "quality": []}, objectives=[],
                      demo="`world.txt` holds world.")
        tickets.write_ticket(self.ledger, second, "## Demo\n\n`world.txt` holds `world`.\n")

    def methods(self):
        return (self.project / "research" / "sections" / "methods.md").read_text(encoding="utf-8")

    def passages(self):
        return sections.read_passages(self.project)

    @staticmethod
    def passage(text, heading="The files", replaces=None, section="methods"):
        return {"section": section, "heading": heading, "text": text, "replaces": replaces}


    def conduct_keyed(self, *triples, waves=None):
        with worker.use_fake() as fake:
            for identifier, envelope, applied in triples:
                fake.script(envelope, patch=applied, ticket=identifier)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            results = drive(self.conductor, waves)
            self.calls = list(fake.calls)
        return results


class TwoTicketsInOneSectionTest(TwoTicketsCase):
    """Tickets adding to one section run in the same wave and are integrated one at a time in id order."""

    def setUp(self):
        super().setUp()
        self.results = self.conduct_keyed(
            (2, done(2, passages=[self.passage("The world file holds one line, `world`.")]),
             patch({"world.txt": "world\n"}, message="ticket 2: write world.txt")),
            (1, done(1, passages=[self.passage("The hello file holds one line, `hello`.")]), patch()),
        )

    def test_both_launch_in_the_same_wave(self):
        self.assertEqual(sorted(self.results[0].launched), [1, 2])

    def test_their_passages_land_in_id_order_and_render_in_arrival_order(self):
        self.assertEqual([(item["id"], item["by"], item["ticket"], item["objectives"]) for item in self.passages()],
                         [("P1", "t1-a1", 1, ["O1"]), ("P2", "t2-a1", 2, [])])
        methods = self.methods()
        self.assertIn("## The files", methods)
        self.assertLess(methods.index("`hello`"), methods.index("`world`"))
        self.assertEqual(methods.count("## The files"), 1, "the second ticket reused the heading")

    def test_each_passage_is_journaled_after_its_ticket_integrated(self):
        journal = [(event["event"], event["ticket"]) for event in self.events() if event["event"] in ("integrated", "passage")]
        self.assertEqual(journal, [("integrated", 1), ("passage", 1), ("integrated", 2), ("passage", 2)])

    def test_the_ticket_file_carries_its_passages_for_a_verdict_to_read(self):
        body = (tickets.tickets_dir(self.project) / "02-write-the-world-file.md").read_text(encoding="utf-8")
        self.assertIn("Passages:\n\n- methods, The files: The world file holds one line, `world`.", body)

    def test_the_sections_ride_in_the_ledger_commit(self):
        self.assertIn("research/sections/methods.md", self.git("show", "--name-only", "--format=", "main").split("\n"))


class TwoReplacementsInOneWaveTest(TwoTicketsCase):
    def setUp(self):
        super().setUp()
        sections.add_passage(self.ledger, "methods", "The files", "The project writes no file yet.", by="owner")
        self.conduct_keyed(
            (1, done(1, passages=[self.passage("The project writes hello.txt.", replaces="P1")]), patch()),
            (2, done(2, passages=[self.passage("The project writes world.txt.", replaces="P1")]),
             patch({"world.txt": "world\n"}, message="ticket 2: write world.txt")),
        )

    def test_both_are_kept_and_the_section_notes_it(self):
        methods = self.methods()
        self.assertNotIn("writes no file yet", methods)
        self.assertLess(methods.index("writes hello.txt"), methods.index("writes world.txt"))
        self.assertIn("P2 and P3 each replace P1", methods)
        self.assertEqual([item["wave"] for item in self.passages()][1], self.passages()[2]["wave"])


class DeclaredSectionsAtAcceptanceTest(TwoTicketsCase):
    def test_a_declared_section_without_a_passage_sends_the_worker_back(self):
        hold_the_ladder(self)
        self.conduct_keyed(
            (1, done(1), patch()),
            (1, done(1, passages=[self.passage("The hello file holds `hello`.")]), None),
            (2, done(2, passages=[self.passage("The world file holds `world`.")]),
             patch({"world.txt": "world\n"}, message="ticket 2: write world.txt")),
        )
        first = [event["payload"] for event in self.events("acceptance") if event["ticket"] == 1][0]
        self.assertFalse(first["pass"])
        self.assertIn("declares Methods and returned no passage", first["results"][-1]["tail"])
        resumed = [call for call in self.calls if call.kind == "resume"]
        self.assertEqual(len(resumed), 1)
        self.assertIn("declares Methods and returned no passage", resumed[0].message)
        self.assertEqual(self.ticket(1)["status"], "done")
        self.assertEqual([item["by"] for item in self.passages()], ["t2-a1", "t1-a1"])


class RunningResultTest(ConductorCase):
    """A running result's passages wait for its jobs: written when they close and the change stands, never before."""

    def test_the_passages_are_written_when_the_jobs_close(self):
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, sections=["methods"]), body)
        resources.add_jobs(self.project, {"command": ["/bin/true"]}, ticket=1, backend="fake")
        envelope = done(passages=[TwoTicketsCase.passage("One job runs `/bin/true`.")])
        envelope.structured_output.update({"status": "running", "jobs": ["t1-1"]})
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running", "running", "exited"], job_id="t1-1")
            self.conduct((envelope, patch()), waves=1)
            self.conductor.settle()
            self.conductor.wave()
            self.assertEqual(self.ticket()["status"], "running")
            self.assertEqual(sections.read_passages(self.project), [], "nothing is written before the jobs close")
            for _ in range(4):
                if self.conductor.wave().ended:
                    break
        self.assertEqual(self.ticket()["status"], "done")
        self.assertEqual([(item["id"], item["by"]) for item in sections.read_passages(self.project)], [("P1", "t1-a1")])
        order = [event["event"] for event in self.events() if event["event"] in ("job_finished", "passage")]
        self.assertEqual(order, ["job_finished", "passage"])


class ArrangeTest(SectionsCase):
    """The rendering rules on chains of replacements, read through the rendered file."""

    def add(self, text, **extra):
        return sections.add_passage(self.ledger, "methods", "Data", text, by=extra.pop("by", "t3-a1"), **extra)

    def body(self, section="methods"):
        return super().body(section)

    def test_a_later_replacement_of_a_twice_replaced_passage_replaces_what_renders_now(self):
        self.add("One.")
        self.add("Two.")
        self.add("One, again.", replaces="P1", wave="r/1")
        self.add("One, a third time.", replaces="P3", wave="r/2")
        self.add("One, from an old pack.", replaces="P1", wave="r/3")
        body = self.body()
        for gone in ("One.", "One, again.", "One, a third time."):
            self.assertNotIn(gone + "\n", body)
        self.assertLess(body.index("One, from an old pack."), body.index("Two."))

    def test_a_note_leaves_once_the_passages_kept_side_by_side_are_no_longer_both_there(self):
        self.add("Old.")
        self.add("New by four.", replaces="P1", wave="r/1")
        self.add("New by five.", replaces="P1", wave="r/1")
        self.assertIn("P2 and P3 each replace P1", self.body())
        self.add("Settled.", replaces="P2", wave="r/2")
        body = self.body()
        self.assertIn("Settled.", body)
        self.assertIn("New by five.", body)
        self.assertNotIn("each replace", body)

    def test_seeding_again_rewords_by_key_rather_than_adding_beside(self):
        key = lambda heading, text: heading
        sections.seed_passages(self.ledger, "introduction", [("The gap", "No work does this.")], by="step:specify", key=key)
        sections.seed_passages(self.ledger, "introduction", [("The gap", "No work does this on real data.")], by="step:specify", key=key)
        body = self.body("introduction")
        self.assertNotIn("No work does this.\n", body)
        self.assertIn("No work does this on real data.", body)
        self.assertEqual(sections.read_passages(self.ledger)[-1]["replaces"], "P1")

    def test_the_sections_part_of_the_pack_keeps_to_the_cap(self):
        for index in range(40):
            self.add("Passage number %d says something long enough to fill the pack quickly." % index)
        text = sections.pack_text(self.ledger, ["methods"], max_chars=600)
        self.assertLessEqual(len(text.split("\n\n[wayline:")[0]), 600)
        self.assertIn("reached the context cap of 600 characters", text)


class ContextPackTest(TwoTicketsCase):
    def test_the_prompt_holds_each_declared_sections_headings_passage_ids_and_first_sentences_and_the_owners_in_full(self):
        sections.add_passage(self.ledger, "methods", "Data", "The data are split by patient. Each split holds ten folds.", by="t9-a1")
        sections.add_passage(self.ledger, "methods", "Data", "Use the 2019 cohort only. It is the one the owner trusts.", by="owner")
        sections.add_passage(self.ledger, "discussion", "Meaning", "Not declared, so not shown.", by="t9-a1")
        self.conduct_keyed((1, done(1, passages=[self.passage("The hello file holds `hello`.")]), patch()), waves=1)
        prompt = [call for call in self.calls if call.request.env.get("WAYLINE_TICKET") == "1"][0].request.prompt
        self.assertIn("# The paper's sections", prompt)
        self.assertIn("## Methods", prompt)
        self.assertIn("- Data\n  - P1: The data are split by patient.\n", prompt)
        self.assertNotIn("Each split holds ten folds.", prompt)
        self.assertIn("  - P2 (the owner's, in full): Use the 2019 cohort only. It is the one the owner trusts.", prompt)
        self.assertNotIn("Not declared, so not shown.", prompt)


class InitTest(SectionsCase):
    def test_init_writes_the_five_sections_each_with_a_render_stamp(self):
        for name in ("introduction", "results", "discussion", "methods", "references"):
            with self.subTest(section=name):
                first = self.text(name).split("\n", 1)[0]
                self.assertTrue(first.startswith("<!-- wayline:render "), first)
                self.assertEqual(sections.read_stamp(self.project, name)["section"], name)
        self.assertIn("# Methods", self.body("methods"))

    def test_a_second_init_changes_no_section(self):
        before = {name: self.text(name) for name in sections.SECTIONS}
        report = projects.init_project(self.project, harness_root=self.temp / "harness", git=False)
        self.assertEqual({name: self.text(name) for name in sections.SECTIONS}, before)
        self.assertFalse([change for change in report["changes"] if "sections" in change])


class PassageTest(SectionsCase):
    def add(self, heading, text, **extra):
        extra.setdefault("by", "t3-a1")
        return sections.add_passage(self.ledger, extra.pop("section", "methods"), heading, text, **extra)

    def test_a_passage_lands_in_the_log_the_journal_and_the_rendered_section(self):
        record = self.add("Data", "The data are split by patient.", objectives=["O1"], ticket=3)
        self.assertEqual(record["id"], "P1")
        self.assertEqual([(item["id"], item["section"], item["heading"], item["text"], item["replaces"], item["by"], item["objectives"])
                          for item in self.passages()],
                         [("P1", "methods", "Data", "The data are split by patient.", None, "t3-a1", ["O1"])])
        event = self.events("passage")[-1]
        self.assertEqual(event["ticket"], 3)
        self.assertEqual(event["payload"], {"id": "P1", "section": "methods", "heading": "Data", "text": "The data are split by patient.",
                                            "replaces": None, "by": "t3-a1", "objectives": ["O1"]})
        self.assertIn("## Data\n\n<!-- wayline:passage P1 -->\nThe data are split by patient.\n", self.body("methods"))
        self.assertEqual(sections.read_stamp(self.ledger, "methods")["last"], "P1")

    def test_ids_run_on_from_p1_across_sections(self):
        self.add("Data", "One.")
        self.assertEqual(self.add("Gap", "Two.", section="introduction", by="step:specify")["id"], "P2")

    def test_a_replaced_passage_leaves_the_file_and_stays_in_the_log(self):
        self.add("Data", "First.")
        self.add("Data", "Second.")
        self.add("Data", "First, narrowed.", replaces="P1")
        body = self.body("methods")
        self.assertNotIn("First.\n", body)
        self.assertLess(body.index("First, narrowed."), body.index("Second."))  # it takes the place of what it replaced
        self.assertEqual([item["id"] for item in self.passages()], ["P1", "P2", "P3"])

    def test_headings_keep_their_first_appearance_order_and_passages_their_arrival_order(self):
        self.add("Data", "One.")
        self.add("Model", "Two.")
        self.add("Data", "Three.")
        body = self.body("methods")
        self.assertLess(body.index("## Data"), body.index("## Model"))
        self.assertLess(body.index("One."), body.index("Three."))
        self.assertLess(body.index("Three."), body.index("## Model"))

    def test_two_replacements_of_one_passage_in_one_wave_are_both_kept_and_noted(self):
        self.add("Data", "Old claim.")
        self.add("Data", "Narrowed by ticket 4.", replaces="P1", wave="run-a/3", by="t4-a1")
        self.add("Data", "Narrowed by ticket 5.", replaces="P1", wave="run-a/3", by="t5-a1")
        body = self.body("methods")
        self.assertNotIn("Old claim.", body)
        self.assertLess(body.index("Narrowed by ticket 4."), body.index("Narrowed by ticket 5."))
        self.assertIn("P2 and P3 each replace P1", body)

    def test_a_replacement_in_a_later_wave_replaces_what_stands_in_the_place(self):
        self.add("Data", "Old claim.")
        self.add("Data", "Narrowed once.", replaces="P1", wave="run-a/3")
        self.add("Data", "Narrowed again.", replaces="P1", wave="run-a/4")
        body = self.body("methods")
        self.assertNotIn("Narrowed once.", body)
        self.assertIn("Narrowed again.", body)
        self.assertNotIn("Note:", body)

    def test_the_ledger_refuses_what_it_cannot_place(self):
        for heading, text, extra in (("Data", "x", {"section": "results"}), ("", "x", {}), ("Data", "  ", {}),
                                     ("Data", "x", {"by": "somebody"}), ("Data", "x", {"replaces": "P9"})):
            with self.subTest(extra=extra, heading=heading, text=text):
                with self.assertRaises(LedgerError):
                    self.add(heading, text, **extra)
        self.assertEqual(self.passages(), [])

    def test_a_finding_is_a_results_passage_and_a_scope_down_replaces_the_one_it_narrows(self):
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71}\n', encoding="utf-8")
        from wayline.provenance import add_finding, register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)
        first = add_finding(self.ledger, "The products raise the AUROC on every split.", "results/summary.json#auroc", 2,
                            heading="Products and AUROC", objectives=["O1"])
        add_finding(self.ledger, "The baseline holds on split A.", "results/summary.json#auroc", 2, heading="Baseline")
        narrowed = add_finding(self.ledger, "The products raise the AUROC on split B only.", "results/summary.json#auroc", 5,
                               heading="Products and AUROC", replaces=first["id"], objectives=["O1"])
        written = [json.loads(line) for line in (self.project / "research" / "findings.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(item["id"], item["heading"], item["replaces"], item["objectives"]) for item in written],
                         [(first["id"], "Products and AUROC", None, ["O1"]), (written[1]["id"], "Baseline", None, []),
                          (narrowed["id"], "Products and AUROC", first["id"], ["O1"])])
        self.assertEqual(self.events("finding")[-1]["payload"]["replaces"], first["id"])
        body = self.body("results")
        self.assertNotIn("every split", body)
        self.assertIn("The products raise the AUROC on split B only.{res:t2-a1/results/summary.json#auroc}", body)
        self.assertLess(body.index("## Products and AUROC"), body.index("## Baseline"))
        with self.assertRaises(LedgerError):
            add_finding(self.ledger, "text", "results/summary.json#auroc", 2, heading="Baseline", replaces="P1")

    def test_a_render_that_changes_nothing_keeps_the_file(self):
        self.add("Data", "One.")
        before = self.text("methods")
        self.assertEqual(sections.render_sections(self.ledger), [])
        self.assertEqual(self.text("methods"), before)


class DeclaredSectionsTest(SectionsCase):
    """The Type-A check at acceptance: a declared section that got no passage (for Results, no finding) sends the worker back."""

    def ticket(self, kind="analysis", **extra):
        fields = {"id": 7, "title": "Analyse the seeds", "kind": kind, "sections": sections.sections_for_kind(kind)}
        fields.update(extra)
        return fields

    def result(self, passages=(), findings=()):
        return {"ticket_id": 7, "status": "done", "summary": "s", "passages": list(passages), "findings": list(findings)}

    def test_the_kinds_declare_what_decision_17_lists(self):
        self.assertEqual({kind: sections.sections_for_kind(kind) for kind in
                          ("code", "experiment", "analysis", "lit", "writing", "docs", "review", "figure", "dossier", "harness")},
                         {"code": ["methods"], "experiment": ["methods"], "analysis": ["methods", "results"], "lit": ["introduction"],
                          "writing": [], "docs": [], "review": [], "figure": [], "dossier": [], "harness": []})

    def test_a_result_that_covers_every_declared_section_passes(self):
        passage = {"section": "methods", "heading": "Seeds", "text": "Ten seeds were run.", "replaces": None}
        finding = {"text": "The mean rose.", "provenance": "results/a.json#mean", "heading": "Seeds and the mean"}
        self.assertEqual(sections.check_result(self.project, self.ticket(), self.result([passage], [finding])), [])

    def test_a_declared_section_without_a_passage_and_results_without_a_finding_fail(self):
        passage = {"section": "results", "heading": "x", "text": "A Results passage is not a finding.", "replaces": None}
        problems = sections.check_result(self.project, self.ticket(), self.result([passage]))
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("Methods", problems[0])
        self.assertIn("Results", problems[1])
        self.assertIn("finding", problems[1])

    def test_a_replaces_naming_nothing_the_section_holds_fails(self):
        sections.add_passage(self.ledger, "introduction", "Gap", "No method does this.", by="step:specify")
        good = {"section": "methods", "heading": "Seeds", "text": "Ten seeds.", "replaces": None}
        wrong = {"section": "methods", "heading": "Seeds", "text": "Nine seeds.", "replaces": "P1"}  # P1 is the Introduction's
        problems = sections.check_result(self.project, self.ticket("code"), self.result([good, wrong]))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("P1", problems[0])

    def test_a_ticket_without_sections_is_not_held_to_any(self):
        fields = self.ticket()
        del fields["sections"]
        self.assertEqual(sections.check_result(self.project, fields, self.result()), [])

    def test_a_writing_ticket_is_held_to_what_it_declares(self):
        problems = sections.check_result(self.project, self.ticket("writing", sections=["discussion"]), self.result())
        self.assertEqual(len(problems), 1)
        self.assertIn("Discussion", problems[0])
