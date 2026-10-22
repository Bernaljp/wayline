"""The dashboard's Paper and Inherited views (Implementation Decision 17; ticket 111), over HTTP against a fixture ledger.

The seam is the server's JSON, as for ticket 110's views: `paper` and `inherited`, the projects page's rows in
`/api/projects`, and `items/<id>`, which resolves an item link `#/<project>/<id>` to what the popup viewer opens. The
project is a start midway built as setup builds it (`test_repeats`): the synthetic manuscript (D1) and supplement (D2)
deconstructed into inherited passages, one consistency check that merged a repeated claim and listed a contradiction,
the manuscript's open comment threads taken as concerns, the critic's table of missing material with the owner's
replies, one verdict reached by a port, and one claim found unverifiable; then what a run adds on the Paper side: a
cited work that resolved, the code repository with its last push, and Methods' generated part.
"""

import json

from tests.test_dashboard_views import DrawnProjectCase, Serving
from tests.test_repeats import CONTRADICTION, REPEAT, SetupCase, same
from tests.test_verification import finding, material_rows
from tests.test_references_rendered import dossier
from wayline import concerns, inherited, sections, verification
from wayline import dossier as dossiers
from wayline.ledger import Ledger

PUSHED = "3f2a9c1d4b5e6f708192a3b4c5d6e7f8091a2b3c"
UNVERIFIABLE = "the 2021 recordings are gone"


class MidwayServedCase(Serving, SetupCase):
    """A start midway at the end of its setup, with a verdict and a run's paper records, served."""

    def setUp(self):
        super().setUp()
        self.check([REPEAT, CONTRADICTION], {("P1", "P14"): same("first"),
                                             ("P5", "P11"): {"label": "contradicting", "why": "lowest against peaks at dusk"}})
        concerns.from_comments(self.project)
        verification.follow(self.project)
        verification.take_memo(self.project, {"material": material_rows()})
        verification.take_replies(self.project, ["M1", "M2"], "M1: I'll provide it; M2: port to Python", "owner")
        sections.file_finding(self.project, finding("t7-a1-f1", 7, "P4", "supports", text="Larger colonies lock more tightly.",
                                                    heading="Results"))
        verification.take_result(self.project, {"id": 7, "verifies": "Results"},
                                 {"status": "done", "verification": {"route": "ported", "commit": None}})
        self.unverifiable = inherited.mark_unverifiable(self.project, "P6", UNVERIFIABLE)["id"]
        verification.follow(self.project)
        self.ledger = Ledger(self.project)
        dossiers.write_l0(self.ledger, dossier("jones-2019-umap", title="UMAP revisited", authors=["A. Jones"], year=2019,
                                               container="JMLR", identifiers={"doi": "10.5555/umap"}))
        sections.add_passage(self.ledger, "methods", "Embedding", "We embed the phases with UMAP {ref:jones-2019-umap#abstract}.",
                             by="owner")
        self.serve()

    def item(self, identifier):
        return self.api("/items/%s" % identifier)


class PaperViewTest(MidwayServedCase):
    def test_it_lists_the_five_sections_and_the_outline_each_opening_in_the_viewer(self):
        view = self.api("/paper").json
        self.assertEqual([section["id"] for section in view["sections"]],
                         ["introduction", "results", "discussion", "methods", "references"])
        results = view["sections"][1]
        self.assertEqual((results["title"], results["path"], results["exists"]), ("Results", "research/sections/results.md", True))
        self.assertGreater(results["passages"], 0)
        self.assertEqual((view["outline"]["id"], view["outline"]["path"], view["outline"]["exists"]),
                         ("outline", "research/OUTLINE.md", True))

    def test_references_lists_its_entries_and_its_not_yet_resolved_rows_with_their_states(self):
        references = self.api("/paper").json["references"]
        [entry] = references["entries"]
        self.assertEqual((entry["number"], entry["slug"], entry["title"], entry["year"], entry["identifier"]),
                         (1, "jones-2019-umap", "UMAP revisited", 2019, "doi:10.5555/umap"))
        unresolved = {row["named"]: row for row in references["unresolved"]}
        okafor = unresolved["title:Invented reference Okafor2017"]
        self.assertEqual((okafor["state"], okafor["detail"]), ("to the scout", "no lookup has answered yet"))
        self.assertEqual(references["path"], "research/sections/references.md")

    def test_the_code_repository_shows_its_link_its_visibility_and_its_last_push(self):
        self.assertEqual(self.api("/paper").json["code_repository"],
                         {"settled": False, "repository": None, "url": None, "visibility": None, "shape": None, "license": None,
                          "last_push": None})
        from wayline.project import HARNESS_JSON, read_harness
        harness = read_harness(self.project)
        harness["code_repository"] = {"shape": "reproducibility", "visibility": "private", "license": "MIT", "remote": {
            "repository": "owner/lantern-sync", "url": "https://github.com/owner/lantern-sync", "how": "new", "branch": "main"}}
        (self.project / HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.ledger.append_event("code_pushed", {"commit": PUSHED, "remote": "owner/lantern-sync", "main": "a" * 40})
        repository = self.api("/paper").json["code_repository"]
        self.assertEqual((repository["settled"], repository["repository"], repository["url"], repository["visibility"]),
                         (True, "owner/lantern-sync", "https://github.com/owner/lantern-sync", "private"))
        self.assertEqual(repository["last_push"]["commit"], PUSHED)
        self.assertTrue(repository["last_push"]["ts"])

    def test_methods_shows_its_parameter_table_and_the_methods_with_no_code_behind_them(self):
        from wayline import methods_inventory
        record = methods_inventory.read_record(self.project)
        record["parameters"] = [{"method": "scipy.signal.butter", "name": "N", "value": "4", "default": None,
                                 "reason": "a fourth order keeps the wingbeat band flat", "path": "code/phaselock.py", "line": 12,
                                 "code": "{code:code/phaselock.py#L12}", "ticket": 7, "by": "owner"}]
        record["not_reproduced"] = [{"passage": "P10", "heading": "Methods", "named": "Hilbert transform",
                                     "why": "no code under `code/` calls Hilbert transform (hilbert)", "reproduced_by_repository": False}]
        self.ledger.write_json(methods_inventory.INVENTORY_JSON, record, schema=methods_inventory.SCHEMA)
        methods = self.api("/paper").json["methods"]
        [row] = methods["parameters"]
        self.assertEqual((row["method"], row["name"], row["value"], row["reason"], row["by"], row["code"]),
                         ("scipy.signal.butter", "N", "4", "a fourth order keeps the wingbeat band flat", "owner",
                          "{code:code/phaselock.py#L12}"))
        [missing] = methods["no_code"]
        self.assertEqual((missing["passage"], missing["named"]), ("P10", "Hilbert transform"))
        self.assertIn("no code under `code/`", missing["why"])

    def test_an_unchanged_ledger_answers_304_and_an_owners_edit_of_a_section_moves_the_tag(self):
        from unittest import mock
        from wayline import dashboard_views
        self.enterContext(mock.patch.object(dashboard_views, "REFERENCES_TICK_S", 10 ** 9))  # no minute turns mid-test
        for route in ("/paper", "/inherited"):
            with self.subTest(route=route):
                first = self.api(route)
                self.assertEqual(self.api(route, {"If-None-Match": first.etag}).status, 304)
        first = self.api("/paper")
        discussion = self.project / "research" / "sections" / "discussion.md"
        discussion.write_text(discussion.read_text(encoding="utf-8") + "\nThe owner's own line.\n", encoding="utf-8")
        self.assertEqual(self.api("/paper", {"If-None-Match": first.etag}).status, 200,
                         "a section file is no ledger file, and its edit still reaches the page")


class NoDocumentsTest(DrawnProjectCase):
    """A start from zero: no document was handed over, so the project has no Inherited view."""

    def test_the_inherited_view_is_absent_and_the_projects_page_says_so(self):
        absent = self.api("/inherited")
        self.assertEqual(absent.status, 404)
        self.assertIn("no documents", absent.json["line"])
        [entry] = self.get("/api/projects").json["projects"]
        self.assertEqual(entry["documents"], 0)

    def test_its_paper_view_answers_with_nothing_yet(self):
        view = self.api("/paper").json
        self.assertEqual(view["references"]["unresolved"], [])
        self.assertFalse(view["code_repository"]["settled"])
        self.assertEqual(view["methods"], {"parameters": [], "no_code": []})


class InheritedViewTest(MidwayServedCase):
    def test_the_projects_page_counts_the_documents_that_offer_the_view(self):
        [entry] = self.get("/api/projects").json["projects"]
        self.assertEqual(entry["documents"], 2)

    def test_it_lists_the_documents_with_their_headings(self):
        documents = self.api("/inherited").json["documents"]
        self.assertEqual([(document["id"], document["kind"]) for document in documents], [("D1", "inherited"), ("D2", "inherited")])
        manuscript = documents[0]
        self.assertEqual(manuscript["path"], "research/documents/D1/text.md")
        self.assertIn("Results", [heading["text"] for heading in manuscript["headings"]])
        self.assertTrue(all(heading["locator"].startswith("p") for heading in manuscript["headings"]))

    def test_each_concern_shows_its_sources_and_its_standing(self):
        concerns_listed = {concern["id"]: concern for concern in self.api("/inherited").json["concerns"]}
        self.assertEqual(sorted(concerns_listed), ["K1", "K2"])
        first = concerns_listed["K1"]
        self.assertEqual(first["sources"], [{"critique": "D1", "locator": "D1#p4", "text": "This contradicts the abstract. Which is right?"}])
        self.assertEqual((first["targets"], first["status"], first["place"]), (["P5"], "open", None))
        self.assertEqual(first["text"], "This contradicts the abstract. Which is right?")
        concerns.place(self.project, ["K2"], concerns.parse_place("decline: the funder is in the acknowledgements"), "owner")
        declined = {concern["id"]: concern for concern in self.api("/inherited").json["concerns"]}["K2"]
        self.assertEqual((declined["status"], declined["reason"]), ("declined", "the funder is in the acknowledgements"))

    def test_each_inherited_claim_shows_its_standing_its_verdict_and_its_route(self):
        claims = {claim["id"]: claim for claim in self.api("/inherited").json["claims"]}
        checked = claims["P4"]
        self.assertEqual((checked["section"], checked["heading"], checked["standing"], checked["verdict"], checked["route"], checked["ticket"]),
                         ("results", "Results", "verified", "supports", "ported", 7))
        self.assertEqual(checked["by"], "t7-a1-f1")
        self.assertTrue(checked["text"].startswith("Larger colonies beat more nearly in phase"), "its words, not its tags")
        self.assertNotIn("{doc:", checked["text"])
        self.assertEqual((claims["P5"]["standing"], claims["P5"]["verdict"], claims["P5"]["route"]), ("unchecked", None, None))
        self.assertEqual(claims["P15"]["section"], "introduction", "a claim outside Results stands with no verdict to reach")
        self.assertEqual(claims["P15"]["standing"], "unchecked")
        self.assertNotIn("P10", claims, "a Methods sentence that claims nothing is no claim")
        self.assertNotIn("P1", claims, "the merge's first occurrence stands as the merged passage")

    def test_a_results_claim_moved_to_discussion_is_listed_once_where_it_stands(self):
        moved = inherited.move_passage(self.project, "P12", "discussion")["id"]
        claims = [claim for claim in self.api("/inherited").json["claims"] if claim["claim"] == "P12" or claim["id"] == moved]
        self.assertEqual([(claim["id"], claim["section"]) for claim in claims], [(moved, "discussion")])

    def test_an_unreadable_documents_record_still_offers_the_view_which_says_why(self):
        (self.project / "research" / "documents.json").write_text("{not json", encoding="utf-8")
        [entry] = self.get("/api/projects").json["projects"]
        self.assertIsNone(entry["documents"], "not known, which is not none: the page still offers Inherited")
        view = self.api("/inherited")
        self.assertEqual(view.status, 200)
        self.assertTrue(any("documents.json" in problem for problem in view.json["problems"]))

    def test_the_unverifiable_claims_carry_their_reasons(self):
        view = self.api("/inherited").json
        claim = {claim["id"]: claim for claim in view["claims"]}[self.unverifiable]
        self.assertEqual((claim["standing"], claim["reason"]), ("unverifiable", UNVERIFIABLE))
        self.assertEqual([(row["id"], row["heading"], row["reason"]) for row in view["unverifiable"]],
                         [(self.unverifiable, "Results", UNVERIFIABLE)])

    def test_the_contradicting_pairs_are_listed_with_why_and_both_claims(self):
        [pair] = self.api("/inherited").json["contradictions"]
        self.assertEqual((pair["id"], pair["a"], pair["b"], pair["why"], pair["results"]),
                         ("P5+P11", "P5", "P11", "lowest against peaks at dusk", ["Results"]))
        self.assertEqual(pair["texts"], ["The order parameter is lowest at dusk across every colony.",
                                         "The order parameter peaks at dusk in every colony."])

    def test_the_setups_merges_are_listed_with_what_was_kept_and_the_owners_mark(self):
        from wayline import batches
        [merge] = self.api("/inherited").json["merges"]
        self.assertEqual((merge["id"], merge["passage"], merge["kept"], merge["outcome"], merge["mark"]),
                         ("P1+P14", "P15", "first", "merged", None))
        self.assertEqual(merge["text"], "Lantern moths gather in dusk swarms whose wingbeats lock together.")
        batches.mark(self.project, merge["batch"], merge["item"], "split")
        self.assertEqual(self.api("/inherited").json["merges"][0]["mark"], "split", "a mark not yet taken shows as given")

    def test_the_missing_material_shows_the_owners_replies(self):
        material = self.api("/inherited").json["material"]
        self.assertEqual([(item["id"], item["kind"], item["reply"], item["by"]) for item in material],
                         [("M1", "data", "I'll provide it", "owner"), ("M2", "software", "port to Python", "owner")])
        self.assertEqual(material[0]["item"], "data/dusk-sweep-2021.csv")
        self.assertEqual(material[0]["heading"], "Results")


class ItemLinkTest(MidwayServedCase):
    """`#/<project>/<id>` opens each Paper and Inherited item in the popup viewer over its view."""

    def opens(self, identifier):
        answer = self.item(identifier)
        self.assertEqual(answer.status, 200, identifier)
        item = answer.json
        return item["kind"], item["view"], item["path"]

    def test_each_section_and_the_outline_open_their_files_over_paper(self):
        for name in ("introduction", "results", "discussion", "methods", "references"):
            with self.subTest(section=name):
                self.assertEqual(self.opens(name), ("section", "paper", "research/sections/%s.md" % name))
        self.assertEqual(self.opens("outline"), ("outline", "paper", "research/OUTLINE.md"))
        self.assertEqual(self.item("results").json["title"], "Results")

    def test_a_claim_opens_its_section_at_its_heading_over_inherited_and_another_passage_over_paper(self):
        claim = self.item("P5").json
        self.assertEqual((claim["kind"], claim["view"], claim["path"], claim["focus"], claim["status"]),
                         ("claim", "inherited", "research/sections/results.md", "Results", "unchecked"))
        self.assertEqual(claim["title"], "The order parameter is lowest at dusk across every colony.")
        self.assertEqual(self.item(self.unverifiable).json["status"], "unverifiable")
        passage = self.item("P10").json
        self.assertEqual((passage["kind"], passage["view"], passage["path"], passage["focus"]),
                         ("passage", "paper", "research/sections/methods.md", "Methods"))

    def test_a_verified_claim_opens_with_its_verdict_and_what_replaced_it(self):
        claim = self.item("P4").json
        self.assertEqual((claim["kind"], claim["view"], claim["status"], claim["replaced_by"]), ("claim", "inherited", "verified", "t7-a1-f1"))

    def test_an_owners_reason_for_a_parameter_stands_as_a_passage_of_methods(self):
        reason = sections.add_owners_passage(self.ledger, "methods", "Parameters", "A fourth order keeps the band flat.",
                                             parameter="scipy.signal.butter:N")["id"]
        passage = self.item(reason).json
        self.assertEqual((passage["kind"], passage["view"], passage["status"]), ("passage", "paper", None))

    def test_a_pair_record_that_cannot_be_read_is_not_found_rather_than_an_error(self):
        (self.project / "research" / "repeats.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.item("P5+P11").status, 404)

    def test_a_document_a_concern_and_a_missing_item_open_their_files_over_inherited(self):
        self.assertEqual(self.opens("D1"), ("document", "inherited", "research/documents/D1/text.md"))
        concern = self.item("K1").json
        self.assertEqual((concern["kind"], concern["view"], concern["path"], concern["focus"], concern["status"]),
                         ("concern", "inherited", "research/CONCERNS.md", "K1", "open"))
        material = self.item("M2").json
        self.assertEqual((material["kind"], material["view"], material["path"], material["focus"], material["status"]),
                         ("material", "inherited", "research/VERIFICATIONS.md", "Missing material", "port to Python"))
        self.assertEqual(material["title"], "MATLAB with the Signal Processing Toolbox")

    def test_a_contradicting_pair_and_a_merge_open_both_claims_side_by_side(self):
        pair = self.item("P5+P11").json
        self.assertEqual((pair["kind"], pair["view"], pair["path"]), ("contradiction", "inherited", None))
        self.assertEqual([(side["id"], side["text"]) for side in pair["sides"]],
                         [("P5", "The order parameter is lowest at dusk across every colony."),
                          ("P11", "The order parameter peaks at dusk in every colony.")])
        self.assertIn(["why", "lowest against peaks at dusk"], pair["fields"])
        merge = self.item("P1+P14").json
        self.assertEqual((merge["kind"], merge["view"], merge["status"]), ("merge", "inherited", "merged"))
        self.assertIn(["kept", "Lantern moths gather in dusk swarms whose wingbeats lock together."], merge["fields"])
        self.assertEqual(self.item("P1%2BP14").json["id"], "P1+P14", "the id as the page encodes it")

    def test_an_id_that_names_nothing_here_answers_404(self):
        for identifier in ("K9", "D9", "M9", "P99", "P2+P9", "appendix", "P1+"):
            with self.subTest(identifier=identifier):
                self.assertEqual(self.item(identifier).status, 404)
