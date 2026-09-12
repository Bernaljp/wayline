"""The knowledge base: typed nodes, the seven edge types, and a query pack that holds no prose."""

import json
import unittest

from tests.projects import ProjectTestCase
from wayline.kb import (
    EDGE_TYPES, EDGES, NODE_KINDS, QUERY_PACK, KBError, add_edge, make_edge, make_node, node_id,
    read_edges, read_nodes, rebuild_query_pack, render_query_pack, write_node,
)
from wayline.ledger import Ledger

ABSTRACT = "The dominant sequence transduction models are based on complex recurrent networks."


def paper(identifier, title, **fields):
    return make_node(identifier, "paper", title, **fields)


class NodeTest(unittest.TestCase):
    def test_the_four_kinds_of_the_spec(self):
        self.assertEqual(NODE_KINDS, ("paper", "idea", "experiment", "claim"))
        for kind in NODE_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(make_node("n-1", kind, "A title")["kind"], kind)

    def test_a_kind_outside_the_four_is_refused(self):
        with self.assertRaises(KBError):
            make_node("n-1", "person", "A title")

    def test_an_id_that_is_not_a_slug_is_refused(self):
        for bad in ("Not A Slug", "", "a/b", "x" * 81):
            with self.subTest(identifier=bad):
                with self.assertRaises(KBError):
                    make_node(bad, "paper", "A title")

    def test_a_node_needs_a_title(self):
        with self.assertRaises(KBError):
            make_node("n-1", "paper", "   ")

    def test_a_field_the_graph_does_not_carry_is_refused(self):
        """A typed graph is the point; an unknown key would be prose sneaking in by another name."""
        with self.assertRaises(KBError):
            make_node("n-1", "paper", "A title", abstract=ABSTRACT)

    def test_node_id_makes_a_slug_out_of_free_text(self):
        self.assertEqual(node_id("Attention Is All You Need!"), "attention-is-all-you-need")
        self.assertEqual(node_id("a claim", prefix="claim"), "claim-a-claim")
        with self.assertRaises(KBError):
            node_id("...")


class EdgeTest(unittest.TestCase):
    def test_the_seven_types_of_the_spec(self):
        self.assertEqual(EDGE_TYPES, ("extends", "contradicts", "tested_by", "supports", "refutes", "uses", "depends_on"))
        for edge_type in EDGE_TYPES:
            with self.subTest(edge=edge_type):
                self.assertEqual(make_edge("a", "b", edge_type)["type"], edge_type)

    def test_a_type_outside_the_seven_is_refused(self):
        with self.assertRaises(KBError):
            make_edge("a", "b", "cites")

    def test_an_edge_to_itself_is_refused(self):
        with self.assertRaises(KBError):
            make_edge("a", "a", "extends")

    def test_an_end_that_is_not_a_node_id_is_refused(self):
        with self.assertRaises(KBError):
            make_edge("a", "Not A Slug", "extends")


class LedgerTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        (self.project / "research").mkdir(parents=True)
        self.ledger = Ledger(self.project)

    def test_a_node_lands_under_kb_nodes_and_reads_back(self):
        write_node(self.ledger, paper("vaswani-2017-attention", "Attention Is All You Need", year=2017, level=0, existence="verified"))
        path = self.project / "research" / "kb" / "nodes" / "vaswani-2017-attention.json"
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["year"], 2017)
        self.assertEqual(list(read_nodes(self.ledger)), ["vaswani-2017-attention"])

    def test_edges_land_in_edges_jsonl_one_per_line(self):
        add_edge(self.ledger, make_edge("a", "b", "extends"))
        add_edge(self.ledger, make_edge("b", "c", "tested_by", note="by the ablation"))
        lines = (self.project / "research" / EDGES).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(read_edges(self.ledger)[1]["note"], "by the ablation")

    def test_the_same_edge_twice_is_written_once(self):
        add_edge(self.ledger, make_edge("a", "b", "extends"))
        add_edge(self.ledger, make_edge("a", "b", "extends"))
        self.assertEqual(len(read_edges(self.ledger)), 1)

    def test_a_torn_line_is_skipped_rather_than_raising(self):
        add_edge(self.ledger, make_edge("a", "b", "extends"))
        path = self.project / "research" / EDGES
        path.write_text(path.read_text(encoding="utf-8") + '{"from": "c", "to"\n', encoding="utf-8")
        self.assertEqual(len(read_edges(self.ledger)), 1)

    def test_the_query_pack_is_written_through_the_ledger(self):
        write_node(self.ledger, paper("a-1", "A paper"))
        rebuild_query_pack(self.ledger, 20000)
        self.assertIn("a-1", (self.project / "research" / QUERY_PACK).read_text(encoding="utf-8"))


class QueryPackTest(unittest.TestCase):
    def setUp(self):
        self.nodes = {
            "vaswani-2017-attention": paper("vaswani-2017-attention", "Attention Is All You Need", year=2017, level=0, existence="verified", identifiers={"arxiv_id": "1706.03762"}),
            "harris-2020-array-programming": paper("harris-2020-array-programming", "Array programming with NumPy", year=2020, level=0, existence="verified", identifiers={"doi": "10.1038/s41586-020-2649-2"}),
            "nowhere": paper("nowhere", "A taxonomy of interpretive marmalade", level=0, existence="unresolved"),
            "idea-1": make_node("idea-1", "idea", "Attention over the feature table"),
        }
        self.edges = [make_edge("idea-1", "vaswani-2017-attention", "extends"), make_edge("idea-1", "harris-2020-array-programming", "uses")]

    def test_the_pack_holds_the_edges_and_the_node_identities(self):
        text = render_query_pack(self.nodes, self.edges, 20000)
        self.assertIn("`idea-1` extends `vaswani-2017-attention`", text)
        self.assertIn("`idea-1` uses `harris-2020-array-programming`", text)
        for identifier in self.nodes:
            self.assertIn(identifier, text)
        self.assertIn("arxiv_id 1706.03762", text)
        self.assertIn("unresolved", text)

    def test_the_pack_never_carries_dossier_prose(self):
        """Dossiers hold depth, the knowledge base holds relations; no prose is duplicated."""
        nodes = dict(self.nodes)
        text = render_query_pack(nodes, self.edges, 20000)
        self.assertNotIn(ABSTRACT, text)
        self.assertNotIn("sequence transduction", text)

    def test_the_cap_is_respected_and_the_cut_is_announced(self):
        many = {("n-%03d" % index): paper("n-%03d" % index, "Paper number %d" % index, year=2000 + index % 20) for index in range(400)}
        text = render_query_pack(many, [], 4000)
        self.assertLessEqual(len(text), 4000)
        self.assertIn("left out", text)
        self.assertIn("capped at 4000 characters", text)

    def test_an_unconnected_node_is_dropped_before_a_connected_one(self):
        text = render_query_pack(self.nodes, self.edges, 700)
        self.assertLessEqual(len(text), 700)
        self.assertIn("idea-1", text)

    def test_an_edge_whose_ends_are_not_nodes_is_left_out(self):
        text = render_query_pack(self.nodes, self.edges + [make_edge("idea-1", "ghost", "supports")], 20000)
        self.assertNotIn("ghost", text)

    def test_an_empty_base_still_renders(self):
        text = render_query_pack({}, [], 20000)
        self.assertIn("0 node(s)", text)
        self.assertIn("none yet", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
