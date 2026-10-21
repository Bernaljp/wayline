"""References rendered and important ones raised (Implementation Decision 17; ticket 105).

The seams: the ledger over a temporary project, where fixture dossiers at L0, L1, and L2 and unresolved ones in each
state are filed and cited by passages, and what is asserted is what lands in `research/sections/references.md` and
`research/references.json`; the conductor, by runs whose journals hold a retrying reference, its final failure, and a
"leave it", asserted on the notices and the events the next wave appends; and the linter's reading of a section.
"""

import io
import json
import re
import time
import unittest

from tests import machine
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, patch
from wayline import account, references, sections, worker
from wayline import dossier as dossiers
from wayline import project as projects
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.scout import timestamp

NOW = time.time()
DAY = 86400


def dossier(slug, level=0, existence="verified", title=None, authors=(), year=None, container=None, identifiers=None,
            query=None, attempts=None, retry=None, handed_over=None, **extra):
    """One dossier as the scout and absorb leave it, at `level`."""
    record = {
        "schema_version": 1, "slug": slug, "level": level, "existence": existence,
        "resolved_by": "crossref" if existence == "verified" else None,
        "query": query or {"kind": "title", "value": title or slug},
        "identifiers": dict(identifiers or {}),
        "metadata": {key: value for key, value in (("title", title), ("authors", list(authors)), ("year", year),
                                                   ("container", container)) if value},
        "attempts": list(attempts if attempts is not None else
                         [{"source": "crossref", "url": "https://api.crossref.org/works", "status": 200,
                           "outcome": "found" if existence == "verified" else "no match"}]),
        "created": "2026-10-01T00:00:00.000Z",
    }
    if retry:
        record["retry"] = retry
    if handed_over:
        record["handed_over"] = handed_over
    record.update(extra)
    return record


def failed(source="crossref"):
    return [{"source": source, "url": "https://api.crossref.org/works", "status": 503, "outcome": "failed"}]


class ReferencesCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "paper-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)

    def file(self, record):
        """File a dossier and its knowledge-base node, as absorb does."""
        dossiers.write_l0(self.ledger, record)
        return record["slug"]

    def cite(self, section, text, heading="Background", by="owner"):
        return sections.add_passage(self.ledger, section, heading, text, by=by)

    def text(self):
        return (self.project / "research" / "sections" / "references.md").read_text(encoding="utf-8")

    def entries(self):
        return re.findall(r"^\d+\. .*$", self.text(), re.M)

    def unresolved(self):
        text = self.text()
        tail = text[text.index("## Not yet resolved"):]
        return re.findall(r"^- .*$", tail, re.M)

    def csl(self):
        return json.loads((self.project / "research" / "references.json").read_text(encoding="utf-8"))


class LibraryCase(ReferencesCase):
    """Three found works at L0, L1, and L2, one found work nobody cites, and an unresolved one in each state."""

    def setUp(self):
        super().setUp()
        self.file(dossier("vaswani-2017-attention", level=2, title="Attention is all you need", year=2017, container="NeurIPS",
                          authors=("Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"),
                          identifiers={"doi": "10.5555/attention"}))
        self.file(dossier("smith-2020-flows", level=1, title="Normalizing flows", year=2020, container="arXiv",
                          authors=("Ann Smith", "Bo Li"), identifiers={"arxiv_id": "2001.00001"}))
        self.file(dossier("jones-2019-umap", level=0, title="UMAP revisited", year=2019, container="JMLR",
                          authors=("Cy Jones", "Di Wu", "Ed Hall"), identifiers={"doi": "10.5555/umap"}))
        self.file(dossier("nobody-cites-this", title="An uncited work", year=2001, identifiers={"doi": "10.5555/uncited"}))
        self.file(dossier("flaky-2021-work", existence="unresolved", query={"kind": "doi", "value": "10.5555/flaky"},
                          attempts=failed(), retry={"service": "crossref", "failure": "HTTP 503", "date": timestamp(NOW - 3600),
                                                    "since": timestamp(NOW - 2 * DAY)}))
        self.file(dossier("ghost-2018-paper", existence="unresolved", query={"kind": "title", "value": "A paper nobody wrote"}))
        self.file(dossier("left-2015-paper", existence="unresolved", query={"kind": "title", "value": "A paper the owner left"},
                          handed_over=[{"answer": "leave", "value": None, "ts": timestamp(NOW - DAY)}]))
        self.file(dossier("spent-2016-paper", existence="unresolved", query={"kind": "doi", "value": "10.5555/spent"},
                          attempts=failed(), retry={"service": "crossref", "failure": "HTTP 503", "date": timestamp(NOW - 8 * DAY),
                                                    "since": timestamp(NOW - 9 * DAY), "gave_up": timestamp(NOW - DAY)}))
        # Arrival order is not citation order: Methods first, then Discussion, then Introduction.
        self.cite("methods", "We embed with UMAP {ref:jones-2019-umap#abstract}. Retries are flaky {ref:flaky-2021-work#abstract}.",
                  heading="Embedding")
        self.cite("discussion", "Attention helps {ref:vaswani-2017-attention#abstract}. A ghost says so {ref:ghost-2018-paper#abstract}.")
        self.cite("introduction", "Flows are old {ref:arxiv:2001.00001#abstract}, and attention too {ref:vaswani-2017-attention#abstract}. "
                  "Someone left this {ref:left-2015-paper#abstract}. A DOI nobody filed {ref:doi:10.9999/unfiled#abstract}. "
                  "Spent too {ref:spent-2016-paper#abstract}.")


class RenderTest(LibraryCase):
    def test_entries_are_numbered_by_first_citation_through_the_sections_in_outline_order(self):
        entries = self.entries()
        self.assertEqual(len(entries), 3, self.text())
        self.assertTrue(entries[0].startswith("1. Ann Smith, Bo Li (2020). Normalizing flows."), entries[0])
        self.assertTrue(entries[1].startswith("2. Ashish Vaswani, Noam Shazeer, Niki Parmar et al. (2017). Attention is all you need."),
                        entries[1])
        self.assertTrue(entries[2].startswith("3. Cy Jones, Di Wu, Ed Hall (2019). UMAP revisited."), entries[2])

    def test_an_entry_gives_the_venue_the_identifier_and_a_link_to_its_dossier(self):
        second = self.entries()[1]
        self.assertIn("*NeurIPS*", second)
        self.assertIn("doi:10.5555/attention", second)
        self.assertIn("[refs/vaswani-2017-attention](../refs/vaswani-2017-attention/dossier.json)", second)
        self.assertIn("arXiv:2001.00001", self.entries()[0])

    def test_a_work_nobody_cites_is_not_a_reference(self):
        self.assertNotIn("nobody-cites-this", self.text())
        self.assertNotIn("nobody-cites-this", [item["id"] for item in self.csl()])

    def test_the_not_yet_resolved_list_gives_each_unresolved_cited_work_its_state(self):
        lines = self.unresolved()
        self.assertEqual(len(lines), 5, self.text())
        by_name = {name: next(line for line in lines if name in line) for name in
                   ("left-2015-paper", "doi:10.9999/unfiled", "spent-2016-paper", "ghost-2018-paper", "flaky-2021-work")}
        self.assertIn("claim kept, to be resolved", by_name["left-2015-paper"])
        self.assertIn("to the scout", by_name["doi:10.9999/unfiled"])
        self.assertIn("gave up", by_name["spent-2016-paper"])
        self.assertIn("gave up", by_name["ghost-2018-paper"])
        self.assertIn("retrying", by_name["flaky-2021-work"])
        self.assertIn("crossref", by_name["flaky-2021-work"])
        self.assertIn(timestamp(NOW - 3600)[:10], by_name["flaky-2021-work"])
        self.assertIn("(../refs/ghost-2018-paper/dossier.json)", by_name["ghost-2018-paper"])
        self.assertEqual([line for line in lines if "left-2015-paper" in line], [lines[0]], "listed in first-citation order")

    def test_the_not_yet_resolved_list_ends_the_file(self):
        self.assertEqual(self.text().rstrip("\n").splitlines()[-1], self.unresolved()[-1])

    def test_references_json_holds_csl_json_of_the_cited_found_works_only(self):
        items = self.csl()
        self.assertEqual([item["id"] for item in items], ["smith-2020-flows", "vaswani-2017-attention", "jones-2019-umap"])
        attention = items[1]
        self.assertEqual(attention["title"], "Attention is all you need")
        self.assertEqual(attention["DOI"], "10.5555/attention")
        self.assertEqual(attention["issued"], {"date-parts": [[2017]]})
        self.assertEqual(attention["container-title"], "NeurIPS")
        self.assertEqual(attention["author"][0], {"family": "Vaswani", "given": "Ashish"})
        self.assertEqual(len(attention["author"]), 4, "CSL keeps every author; only the list cuts at three")
        self.assertIn("type", attention)

    def test_a_render_that_changes_nothing_writes_nothing(self):
        before = self.text()
        stamp = sections.read_stamp(self.project, "references")
        self.assertTrue(stamp)
        sections.render_sections(self.ledger)
        self.assertEqual(self.text(), before)

    def test_a_work_that_resolves_takes_its_number_at_the_next_render(self):
        self.file(dossier("ghost-2018-paper", title="A paper somebody wrote", year=2018, identifiers={"doi": "10.5555/ghost"}))
        sections.render_sections(self.ledger)
        self.assertEqual(len(self.entries()), 4)
        self.assertTrue(self.entries()[2].startswith("3. "), self.entries())
        self.assertIn("A paper somebody wrote", self.entries()[2])
        self.assertNotIn("ghost-2018-paper", "\n".join(self.unresolved()))

    def test_a_replaced_passage_cites_nothing(self):
        (first,) = [item for item in sections.read_passages(self.ledger) if item["section"] == "methods"]
        sections.add_passage(self.ledger, "methods", "Embedding", "We embed with PCA.", by="owner", replaces=first["id"])
        self.assertNotIn("jones-2019-umap", self.text())
        self.assertNotIn("flaky-2021-work", self.text())

    def test_references_is_written_by_code_and_takes_no_passage(self):
        with self.assertRaises(sections.SectionError):
            sections.add_passage(self.ledger, "references", "Extra", "A reference typed by hand.", by="owner")


class LinterTest(LibraryCase):
    def test_before_the_order_the_linter_lists_an_unresolved_citation_in_a_section_and_never_fails_it(self):
        reading = sections.lint_section(self.ledger, "discussion")
        self.assertEqual(reading["problems"], [])
        listed = [(item["problem"], item["tag"]) for item in reading["listed"]]
        self.assertIn(("unresolved_ref", "ref:ghost-2018-paper#abstract"), listed)
        self.assertNotIn(("unresolved_ref", "ref:vaswani-2017-attention#abstract"), listed, "a found work resolves")

    def test_the_render_records_the_listing(self):
        record = self.ledger.read_json("sections/lint.json")["sections"]["introduction"]
        tags = sorted(item["tag"] for item in record["listed"] if item["problem"] == "unresolved_ref")
        self.assertEqual(tags, ["ref:doi:10.9999/unfiled#abstract", "ref:left-2015-paper#abstract", "ref:spent-2016-paper#abstract"])
        self.assertEqual(record["problems"], [])


def unresolved_three():
    """A retrying reference, one whose failure is final, and one the owner left, as fixture dossiers."""
    return (
        dossier("flaky-2021-work", existence="unresolved", query={"kind": "doi", "value": "10.5555/flaky"}, attempts=failed(),
                retry={"service": "crossref", "failure": "HTTP 503", "date": timestamp(NOW - 3600), "since": timestamp(NOW - 2 * DAY)}),
        dossier("ghost-2018-paper", existence="unresolved", query={"kind": "title", "value": "A paper nobody wrote"}),
        dossier("left-2015-paper", existence="unresolved", query={"kind": "title", "value": "A paper the owner left"},
                handed_over=[{"answer": "leave", "value": None, "ts": timestamp(NOW - DAY)}]),
    )


CITING_ALL = ("Retries are flaky {ref:flaky-2021-work#abstract}. A ghost says so {ref:ghost-2018-paper#abstract}. "
              "Someone left this {ref:left-2015-paper#abstract}.")


class ImportantTest(ReferencesCase):
    """What makes an unresolved reference important: the owner named it, or a standing passage, a concern, or an objective cites it."""

    def setUp(self):
        super().setUp()
        for record in unresolved_three():
            self.file(record)
        self.file(dossier("idle-2010-paper", existence="unresolved", query={"kind": "title", "value": "A paper nobody cites"}))

    def slugs(self):
        return {item["slug"]: item["reason"] for item in references.important(self.project)}

    def test_an_unresolved_reference_nothing_names_or_cites_is_not_important(self):
        self.assertEqual(self.slugs(), {})

    def test_a_standing_passage_citing_it_makes_it_important_and_a_replaced_one_no_longer(self):
        passage = self.cite("discussion", "A ghost says so {ref:ghost-2018-paper#abstract}.")
        self.assertEqual(self.slugs(), {"ghost-2018-paper": "passage"})
        sections.add_passage(self.ledger, "discussion", "Background", "Nothing says so.", by="owner", replaces=passage["id"])
        self.assertEqual(self.slugs(), {})

    def test_the_owner_naming_it_at_intake_makes_it_important(self):
        path = self.project / "research" / "INTAKE.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n## References\n\n- A paper nobody wrote\n", encoding="utf-8")
        self.assertEqual(self.slugs(), {"ghost-2018-paper": "owner"})

    def test_an_objective_citing_it_makes_it_important(self):
        from wayline.objectives import add_objective
        add_objective(self.project, "Does the flaky claim {ref:flaky-2021-work#abstract} hold here?")
        self.assertEqual(self.slugs(), {"flaky-2021-work": "objective"})

    def test_a_concern_citing_it_makes_it_important(self):
        from wayline import concerns
        record = concerns.read_record(self.ledger)
        record["concerns"].append({"id": "K1", "sources": [{"critique": "D1", "locator": "D1#p2",
                                                            "text": "The ghost {ref:ghost-2018-paper#abstract} says otherwise."}],
                                   "targets": [], "place": None, "objectives": [], "status": "open", "answer": None, "reason": None,
                                   "proposed": None, "returned": None, "sorted_by": None})
        self.ledger.write_json("concerns.json", record)
        self.assertEqual(self.slugs(), {"ghost-2018-paper": "concern"})

    def test_setup_asks_about_every_important_one_but_those_left_including_those_still_retrying(self):
        self.cite("introduction", CITING_ALL)
        self.assertEqual([item["slug"] for item in references.at_setup(self.project)], ["flaky-2021-work", "ghost-2018-paper"])

    def test_before_setup_ends_nothing_is_raised(self):
        self.cite("introduction", CITING_ALL)
        self.assertEqual(references.raise_final(self.project, notify=lambda *args: self.fail("notified")), [])
        self.assertFalse([event for event in self.ledger.read_events()[0] if event["event"] == "reference_raised"])


class RaiseCase(ConductorCase):
    """Runs over the one-ticket fixture whose journal holds a retrying reference, its final failure, and a "leave it"."""

    def setUp(self):
        super().setUp()
        for record in unresolved_three():
            dossiers.write_l0(self.ledger, record)
        sections.add_passage(self.ledger, "introduction", "Background", CITING_ALL, by="owner")
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})  # setup ended

    def set_autonomy(self, level):
        path = self.project / "harness.json"
        path.write_text(json.dumps(dict(json.loads(path.read_text(encoding="utf-8")), autonomy=level), indent=2), encoding="utf-8")

    def run_once(self, first=True):
        sent = []
        with worker.use_fake() as fake:
            if first:
                fake.script(done(), patch=patch())
            conductor = Conductor(self.project, out=io.StringIO())
            conductor.readings = machine.recorded
            conductor.notify = lambda event, text, project=None, ticket=None: sent.append((event, text))
            drive(conductor)
        return sent

    def give_up_the_flag(self):
        record = self.ledger.read_json("refs/flaky-2021-work/dossier.json")
        dossiers.give_up(self.ledger, record, timestamp(NOW))

    def raised(self):
        return [event["payload"]["slug"] for event in self.events("reference_raised")]

    def waiting_on_you(self):
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        if "## Waiting on you" not in text:
            return ""  # an empty section is left out
        start = text.index("## Waiting on you")
        end = text.find("\n## ", start + 1)
        return text[start:end if end != -1 else None]


class InteractiveRaiseTest(RaiseCase):
    def test_a_final_failure_is_a_notice_a_line_and_the_next_conversations_first_item_and_a_retrying_one_waits(self):
        self.set_autonomy("interactive")
        sent = self.run_once()
        self.assertEqual(self.raised(), ["ghost-2018-paper"])
        (event,) = self.events("reference_raised")
        self.assertEqual(event["payload"], {"slug": "ghost-2018-paper", "reason": "passage", "outcome": "no such work",
                                            "autonomy": "interactive"})
        notices = [text for name, text in sent if name == "reference_raised"]
        self.assertEqual(len(notices), 1)
        self.assertIn("ghost-2018-paper", notices[0])
        self.assertIn("research/sections/references.md", notices[0])
        self.assertIn("Reference `ghost-2018-paper`", self.waiting_on_you())
        self.assertNotIn("flaky-2021-work", self.waiting_on_you(), "still retrying")
        self.assertEqual([item["slug"] for item in references.waiting(self.project)], ["ghost-2018-paper"])

        self.give_up_the_flag()
        sent = self.run_once(first=False)
        self.assertEqual(self.raised(), ["ghost-2018-paper", "flaky-2021-work"], "each raised once")
        notices = [text for name, text in sent if name == "reference_raised"]
        self.assertEqual(len(notices), 1)
        self.assertIn("flaky-2021-work", notices[0])
        self.assertEqual([item["slug"] for item in references.waiting(self.project)], ["ghost-2018-paper", "flaky-2021-work"])
        self.assertNotIn("left-2015-paper", self.waiting_on_you())

    def test_an_item_the_owner_leaves_is_settled_and_not_raised_again(self):
        self.set_autonomy("interactive")
        self.run_once()
        dossiers.hand_over(self.project, "ghost-2018-paper", "leave it")
        self.run_once(first=False)
        self.assertEqual(self.raised(), ["ghost-2018-paper"])
        self.assertEqual(references.waiting(self.project), [])
        self.assertNotIn("ghost-2018-paper", self.waiting_on_you())


class CheckpointsRaiseTest(RaiseCase):
    def test_a_final_failure_waits_on_the_owner_with_no_notice_and_rides_the_end_notice(self):
        self.set_autonomy("checkpoints")
        sent = self.run_once()
        self.assertEqual(self.raised(), ["ghost-2018-paper"])
        self.assertEqual(self.events("reference_raised")[0]["payload"]["autonomy"], "checkpoints")
        self.assertNotIn("reference_raised", [name for name, _ in sent])
        (end,) = [text for name, text in sent if name == "run_ended"]
        self.assertIn("ghost-2018-paper", end)
        self.assertNotIn("flaky-2021-work", end)
        self.assertIn("Reference `ghost-2018-paper`", self.waiting_on_you())
        self.assertEqual([item["slug"] for item in references.waiting(self.project)], ["ghost-2018-paper"])


class AutonomousRaiseTest(RaiseCase):
    def test_after_setup_a_final_failure_is_listed_and_never_notified(self):
        self.set_autonomy("autonomous")
        sent = self.run_once()
        self.give_up_the_flag()
        sent += self.run_once(first=False)
        self.assertEqual(self.raised(), [])
        self.assertNotIn("reference_raised", [name for name, _ in sent])
        self.assertTrue(all("ghost-2018-paper" not in text for _, text in sent))
        waiting = self.waiting_on_you()
        self.assertIn("Reference `ghost-2018-paper`", waiting)
        self.assertIn("Reference `flaky-2021-work`", waiting)
        self.assertNotIn("left-2015-paper", waiting)
        self.assertEqual(references.waiting(self.project), [])


class ListingTest(RaiseCase):
    """`wayline reference` with no slug: what the conversation puts to the owner, the setup's list before setup ends."""

    def listing(self):
        from contextlib import redirect_stdout
        from wayline import cli
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["reference", "--project", str(self.project)])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_after_setup_it_lists_the_raised_ones_in_the_order_raised(self):
        self.set_autonomy("interactive")
        self.run_once()
        listed = self.listing()
        self.assertIn("ghost-2018-paper", listed)
        self.assertNotIn("flaky-2021-work", listed)
        self.assertNotIn("left-2015-paper", listed)

    def test_before_setup_ends_it_lists_what_setup_asks_retrying_ones_included(self):
        path = self.project / "research" / "journal.jsonl"
        path.write_text("".join(line + "\n" for line in path.read_text(encoding="utf-8").splitlines() if '"phase"' not in line),
                        encoding="utf-8")
        listed = self.listing()
        self.assertIn("ghost-2018-paper", listed)
        self.assertIn("flaky-2021-work", listed)
        self.assertNotIn("left-2015-paper", listed)


class LibraryPointerTest(RaiseCase):
    def test_the_accounts_library_counts_the_unresolved_and_points_to_not_yet_resolved(self):
        account.render_account(self.project)
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        library = text[text.index("## Library"):]
        self.assertIn("3 cited reference(s) not yet resolved", library)
        self.assertIn("[References](sections/references.md#not-yet-resolved)", library)


class AfterTheOrderTest(LibraryCase):
    def test_after_the_paper_order_an_unresolved_citation_in_a_section_fails(self):
        self.ledger.append_event("paper_started", {"venue": "arxiv"})
        reading = sections.lint_section(self.ledger, "discussion")
        self.assertIn(("unresolved_ref", "ref:ghost-2018-paper#abstract"), [(item["problem"], item["tag"]) for item in reading["problems"]])


class CslNameTest(unittest.TestCase):
    def test_each_way_the_services_write_a_name_reads_as_family_and_given(self):
        for name, expected in (("Ashish Vaswani", {"family": "Vaswani", "given": "Ashish"}),
                               ("Smith J", {"family": "Smith", "given": "J"}),
                               ("Van der Berg AB", {"family": "Van der Berg", "given": "AB"}),
                               ("Smith, J.", {"family": "Smith", "given": "J."}),
                               ("Plato", {"family": "Plato"})):
            with self.subTest(name=name):
                item = references.csl_item(dossier("x", title="T", authors=(name,)))
                self.assertEqual(item["author"], [expected])


class NoReferencesPassageTest(ReferencesCase):
    def test_a_result_passage_naming_references_is_sent_back_and_a_ticket_declaring_it_is_held_to_nothing_there(self):
        fields = {"id": 3, "sections": ["references"]}
        self.assertEqual(sections.check_result(self.ledger, fields, {"passages": []}), [])
        problems = sections.check_result(self.ledger, fields, {"passages": [{"section": "references", "heading": "R", "text": "x"}]})
        self.assertEqual(len(problems), 1)
        self.assertIn("References is written by code", problems[0])

    def test_a_consolidation_of_references_is_refused(self):
        from wayline import consolidation
        with self.assertRaises(consolidation.Refused):
            consolidation.consolidate(self.project, "references")

    def test_the_context_pack_shows_no_references_section(self):
        self.assertEqual(sections.pack_text(self.ledger, ["references"]), "")

    def test_init_reports_both_files(self):
        fresh = self.temp / "fresh"
        report = projects.init_project(fresh, harness_root=self.fake_harness(), git=False)
        self.assertIn("research/sections/references.md", report["changes"])
        self.assertIn("research/references.json", report["changes"])


class EmptyTest(ReferencesCase):
    def test_the_library_says_nothing_of_references_when_none_is_unresolved(self):
        self.file(dossier("only-2020-paper", title="The only paper", year=2020))
        self.cite("introduction", "It holds {ref:only-2020-paper#abstract}.")
        account.render_account(self.project)
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        self.assertIn("## Library", text)
        self.assertNotIn("not yet resolved", text[text.index("## Library"):])

    def test_init_writes_an_empty_references_and_an_empty_csl_list(self):
        self.assertIn("# References", self.text())
        self.assertIn("## Not yet resolved", self.text())
        self.assertEqual(self.csl(), [])
