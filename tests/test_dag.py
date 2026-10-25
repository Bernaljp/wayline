"""The layered DAG layout of research-notes 08 Section 5, over a data fixture rather than a project.

`dag.svg` draws from `(nodes, edges, status)` alone, so these tests do not need a ledger: the
14-node, 18-edge fixture is the same shape research-notes 08 measured its prototype against.
"""

import unittest
import xml.etree.ElementTree as ET

from wayline import dag

SVG_NS = "{http://www.w3.org/2000/svg}"

# A 14-node, 18-edge DAG (acceptance criterion 1): every edge points from a lower id to a higher
# one, so it is acyclic by construction, and every id from 0 to 13 appears in at least one edge.
NODES = list(range(14))
EDGES = [
    (0, 1), (0, 2),
    (1, 3), (1, 4), (2, 4), (2, 5),
    (3, 6), (4, 6), (4, 7), (5, 7),
    (6, 8), (6, 9), (7, 9), (7, 10),
    (8, 11), (9, 11), (9, 12), (10, 13),
]


class LayoutTest(unittest.TestCase):
    def test_a_source_with_no_parents_is_in_layer_zero(self):
        pos, _ = dag.layout(NODES, EDGES)
        self.assertEqual(pos[0][1], 0)

    def test_a_node_is_at_least_one_layer_below_every_parent(self):
        pos, _ = dag.layout(NODES, EDGES)
        for a, b in EDGES:
            self.assertGreater(pos[b][1], pos[a][1])

    def test_the_layout_is_deterministic(self):
        first, _ = dag.layout(NODES, EDGES)
        second, _ = dag.layout(NODES, EDGES)
        self.assertEqual(first, second)

    def test_a_single_node_has_no_edges_to_place(self):
        pos, (w, h) = dag.layout([1], [])
        self.assertEqual(pos[1], (0, 0))
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_an_edge_to_a_node_outside_nodes_is_a_dag_error(self):
        with self.assertRaises(dag.DagError):
            dag.layout([1, 2], [(1, 99)])

    def test_a_cycle_is_a_dag_error(self):
        with self.assertRaises(dag.DagError):
            dag.layout([1, 2, 3], [(1, 2), (2, 3), (3, 1)])

    def test_a_node_blocked_by_two_nodes_one_of_which_blocks_the_other_is_no_cycle(self):
        # The toy run's graph: ticket 96 blocked by 115 and 116, and 116 by 115. 115 waits on the stack for 96's sake
        # while 116 is laid out, which is no path back to 116.
        pos, _ = dag.layout([1, 2, 3], [(3, 1), (2, 1), (3, 2)])
        self.assertLess(pos[3][1], pos[2][1])
        self.assertLess(pos[2][1], pos[1][1])


class SvgTest(unittest.TestCase):
    def status_of(self, nodes, frontier=()):
        return {node: ("frontier" if node in frontier else "open") for node in nodes}

    def test_the_14_node_18_edge_fixture_draws_under_10kb_with_one_rect_per_node_and_one_line_per_edge(self):
        text = dag.svg(NODES, EDGES, self.status_of(NODES))
        self.assertLess(len(text.encode("utf-8")), 10 * 1024)
        root = ET.fromstring(text)
        self.assertEqual(len(root.findall(".//%srect" % SVG_NS)), len(NODES))
        self.assertEqual(len(root.findall(".//%sline" % SVG_NS)), len(EDGES))

    def test_it_is_well_formed_xml_with_one_link_per_node(self):
        text = dag.svg(NODES, EDGES, self.status_of(NODES))
        root = ET.fromstring(text)
        self.assertEqual(len(root.findall(".//%sa" % SVG_NS)), len(NODES))

    def test_it_carries_exactly_one_arrow_marker_definition(self):
        text = dag.svg(NODES, EDGES, self.status_of(NODES))
        root = ET.fromstring(text)
        self.assertEqual(len(root.findall(".//%smarker" % SVG_NS)), 1)

    def test_edges_run_straight_from_the_bottom_of_the_parent_to_the_top_of_the_child(self):
        pos, _ = dag.layout(NODES, EDGES)
        text = dag.svg(NODES, EDGES, self.status_of(NODES))
        root = ET.fromstring(text)
        lines = root.findall(".//%sline" % SVG_NS)
        (a, b) = EDGES[0]
        (x1, y1), (x2, y2) = pos[a], pos[b]
        matching = [line for line in lines if float(line.get("y1")) == y1 + dag.NODE_H and float(line.get("y2")) == y2]
        self.assertTrue(matching, "no straight edge found from the bottom of node %d to the top of node %d" % (a, b))

    def test_a_nodes_fill_comes_from_its_status(self):
        text = dag.svg([1, 2], [(1, 2)], {1: "done", 2: "frontier"})
        self.assertIn('fill="%s"' % dag.STATUS_COLOR["done"], text)
        self.assertIn('fill="%s"' % dag.STATUS_COLOR["frontier"], text)

    def test_a_status_outside_the_color_map_is_a_key_error(self):
        with self.assertRaises(KeyError):
            dag.svg([1], [], {1: "no-such-status"})

    def test_a_custom_link_format_names_the_node(self):
        text = dag.svg([7], [], {7: "open"}, link="#ticket/%s")
        self.assertIn('href="#ticket/7"', text)


if __name__ == "__main__":
    unittest.main()
