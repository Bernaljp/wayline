"""Ticket files and `graph.json`: the round trip, the scheduling fields, the frontier, regeneration.

The seam is the ledger (Testing Decisions, seam 3): each test builds a project in a temporary
directory, drives the code under test, and reads the ledger back.
"""

import json
import unittest

from tests.projects import ProjectTestCase
from wayline.jsonschema import ValidationError
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.tickets import (
    GRAPH, SCHEDULING_FIELDS, STATUSES, TicketError, answer_section, attempts_from_events, build_graph,
    by_status, filename, frontier, read_graph, read_ticket, read_tickets, refresh_graph, retire_answer,
    slug, snapshot, with_answer, write_ticket,
)


def ticket(identifier, title="A ticket", **extra):
    fields = {
        "id": identifier,
        "title": title,
        "kind": "code",
        "difficulty": 2,
        "status": "open",
        "blocked_by": [],
        "touches": ["src/"],
        "role": "coder",
        "acceptance": {"machine": ["python -m unittest"], "quality": []},
        "proposed_by": "planner",
    }
    fields.update(extra)
    return fields


class AnswerSectionTest(unittest.TestCase):
    """The `## Answer` of a decision ticket: written, read back, and retired by a rerun (decision 2)."""

    BODY = "\n## Question\n\nWhich split is held out?\n"

    def test_an_answer_is_read_back_up_to_the_next_heading(self):
        body = with_answer(self.BODY, "  the second split  ") + "\n## Notes\n\nmore\n"
        self.assertEqual(answer_section(body), "the second split")
        self.assertIsNone(answer_section(self.BODY))

    def test_a_retired_answer_stays_in_the_file_and_is_no_longer_the_answer(self):
        retired = retire_answer(with_answer(self.BODY, "the second split"))
        self.assertIsNone(answer_section(retired))
        self.assertIn("## Superseded answer\n\nthe second split", retired)
        self.assertEqual(answer_section(with_answer(retired, "the first split")), "the first split")


class TicketFileTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness())
        self.ledger = Ledger(self.project)

    def test_a_ticket_round_trips_through_the_parser_and_the_serializer(self):
        fields = ticket(7, "Export the held-out predictions", skills=["pandas"], demo="A CSV.",
                        resources={"gpu": 0, "cpu": 4, "ram_gb": 8, "wallclock_minutes": 30})
        path = write_ticket(self.ledger, fields, "## Demo\n\nOne CSV.\n")
        self.assertEqual(path.name, "07-export-the-held-out-predictions.md")
        read, body = read_ticket(path)
        self.assertEqual(read, fields)
        self.assertIn("## Demo", body)

    def test_the_file_name_is_the_id_and_the_slug(self):
        self.assertEqual(filename(ticket(3, "Train the baseline model")), "03-train-the-baseline-model.md")
        self.assertEqual(filename(ticket(42, "Which split is held out?")), "42-which-split-is-held-out.md")
        self.assertEqual(slug("A  title -- with  punctuation!"), "a-title-with-punctuation")

    def test_a_file_name_that_disagrees_with_the_id_is_refused(self):
        path = write_ticket(self.ledger, ticket(7))
        renamed = path.with_name("08-a-ticket.md")
        path.rename(renamed)
        with self.assertRaises(TicketError) as caught:
            read_ticket(renamed)
        self.assertIn("file name says ticket 8", str(caught.exception))

    def test_frontmatter_outside_the_schema_is_refused(self):
        with self.assertRaises(ValidationError):
            write_ticket(self.ledger, ticket(1, status="finished"))
        with self.assertRaises(ValidationError):
            write_ticket(self.ledger, ticket(1, difficulty=6))

    def test_two_tickets_with_one_id_are_refused(self):
        write_ticket(self.ledger, ticket(4, "First title"))
        write_ticket(self.ledger, ticket(4, "Second title"))
        with self.assertRaises(TicketError) as caught:
            read_tickets(self.project)
        self.assertIn("defined twice", str(caught.exception))

    def test_a_blocker_that_does_not_exist_is_refused(self):
        write_ticket(self.ledger, ticket(1, blocked_by=[99]))
        with self.assertRaises(TicketError) as caught:
            read_tickets(self.project)
        self.assertIn("does not exist", str(caught.exception))

    def test_a_ticket_that_blocks_itself_is_refused(self):
        write_ticket(self.ledger, ticket(1, blocked_by=[1]))
        with self.assertRaises(TicketError):
            read_tickets(self.project)

    def test_a_cycle_is_refused(self):
        with self.assertRaises(TicketError) as caught:
            build_graph([ticket(1, blocked_by=[2]), ticket(2, blocked_by=[3]), ticket(3, blocked_by=[1])])
        self.assertIn("cycle", str(caught.exception))

    def test_a_diamond_is_not_a_cycle(self):
        graph = build_graph([ticket(1), ticket(2, blocked_by=[1]), ticket(3, blocked_by=[1]), ticket(4, blocked_by=[2, 3])])
        self.assertEqual(len(graph["tickets"]), 4)


class GraphTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness())
        self.ledger = Ledger(self.project)

    def test_the_graph_holds_only_the_scheduling_fields(self):
        write_ticket(self.ledger, ticket(1, demo="A demo", context_pack=["research/SPEC.md"], origin="SPEC.md#claim-1"))
        graph, regenerated = refresh_graph(self.project, ledger=self.ledger)
        self.assertTrue(regenerated)
        entry = graph["tickets"][0]
        self.assertEqual(tuple(entry), SCHEDULING_FIELDS)
        self.assertNotIn("title", entry)
        self.assertNotIn("demo", entry)

    def test_a_pinned_difficulty_wins_in_the_graph(self):
        write_ticket(self.ledger, ticket(1, difficulty=2, pinned_difficulty=5))
        graph, _ = refresh_graph(self.project, ledger=self.ledger)
        self.assertEqual(graph["tickets"][0]["difficulty"], 5)
        self.assertEqual(read_ticket(next((self.project / "research" / "tickets").glob("*.md")))[0]["difficulty"], 2)

    def test_the_graph_is_regenerated_when_a_ticket_file_changes(self):
        path = write_ticket(self.ledger, ticket(1))
        refresh_graph(self.project, ledger=self.ledger)
        text = path.read_text(encoding="utf-8").replace("status: open", "status: running")
        path.write_text(text, encoding="utf-8")
        graph, regenerated = refresh_graph(self.project, ledger=self.ledger)
        self.assertTrue(regenerated)
        self.assertEqual(graph["tickets"][0]["status"], "running")

    def test_an_unchanged_tickets_directory_is_not_regenerated(self):
        write_ticket(self.ledger, ticket(1))
        refresh_graph(self.project, ledger=self.ledger)
        path = self.project / "research" / GRAPH
        before = path.read_bytes()
        graph, regenerated = refresh_graph(self.project, ledger=self.ledger)
        self.assertFalse(regenerated)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(graph, read_graph(self.project))

    def test_the_snapshot_records_every_ticket_file(self):
        write_ticket(self.ledger, ticket(1, "One"))
        write_ticket(self.ledger, ticket(2, "Two"))
        graph, _ = refresh_graph(self.project, ledger=self.ledger)
        self.assertEqual(sorted(graph["snapshot"]), ["01-one.md", "02-two.md"])
        self.assertEqual(graph["snapshot"], snapshot(self.project))

    def test_a_removed_ticket_leaves_the_graph(self):
        first = write_ticket(self.ledger, ticket(1, "One"))
        write_ticket(self.ledger, ticket(2, "Two"))
        refresh_graph(self.project, ledger=self.ledger)
        first.unlink()
        graph, regenerated = refresh_graph(self.project, ledger=self.ledger)
        self.assertTrue(regenerated)
        self.assertEqual([entry["id"] for entry in graph["tickets"]], [2])

    def test_the_attempt_counter_comes_from_the_journal(self):
        write_ticket(self.ledger, ticket(1))
        events = [
            {"event": "ticket_launched", "payload": {"ticket": 1, "attempt": 1}},
            {"event": "ticket_launched", "payload": {"ticket": 1, "attempt": 2}},
            {"event": "ticket_done", "payload": {"ticket": 1}},
        ]
        self.assertEqual(attempts_from_events(events), {1: 2})
        graph, regenerated = refresh_graph(self.project, ledger=self.ledger, events=events)
        self.assertTrue(regenerated)
        self.assertEqual(graph["tickets"][0]["attempt"], 2)

    def test_a_new_attempt_regenerates_a_graph_whose_tickets_did_not_change(self):
        write_ticket(self.ledger, ticket(1))
        refresh_graph(self.project, ledger=self.ledger, events=[])
        events = [{"event": "ticket_launched", "payload": {"ticket": 1, "attempt": 1}}]
        graph, regenerated = refresh_graph(self.project, ledger=self.ledger, events=events)
        self.assertTrue(regenerated)
        self.assertEqual(graph["tickets"][0]["attempt"], 1)
        _, again = refresh_graph(self.project, ledger=self.ledger, events=events)
        self.assertFalse(again)

    def test_the_graph_survives_a_second_pass_unchanged(self):
        write_ticket(self.ledger, ticket(1))
        first, _ = refresh_graph(self.project, ledger=self.ledger)
        second, _ = refresh_graph(self.project, ledger=self.ledger, force=True)
        self.assertEqual(first, second)

    def test_a_graph_file_that_is_not_a_graph_reads_as_none_and_is_rebuilt(self):
        write_ticket(self.ledger, ticket(1))
        refresh_graph(self.project, ledger=self.ledger)
        path = self.project / "research" / GRAPH
        for broken in ('{"snapshot": {}, "tickets": [{"kind": "code"}]}', '{"snapshot": {}, "tickets": [1]}',
                       '{"snapshot": [], "tickets": []}', '{"tickets": {}}', "half a file"):
            with self.subTest(graph=broken):
                path.write_text(broken + "\n", encoding="utf-8")
                self.assertIsNone(read_graph(self.project))
                graph, regenerated = refresh_graph(self.project, ledger=self.ledger)
                self.assertTrue(regenerated)
                self.assertEqual([entry["id"] for entry in graph["tickets"]], [1])

    def test_the_graph_is_valid_json_the_ledger_wrote(self):
        write_ticket(self.ledger, ticket(1))
        refresh_graph(self.project, ledger=self.ledger)
        text = (self.project / "research" / GRAPH).read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), read_graph(self.project))
        self.assertTrue(text.endswith("\n"))


class FrontierTest(unittest.TestCase):
    def test_the_frontier_is_open_tickets_whose_blockers_are_done_or_accepted(self):
        graph = build_graph([
            ticket(1, status="accepted"),
            ticket(2, status="done"),
            ticket(3, status="running"),
            ticket(4, status="open", blocked_by=[1, 2]),
            ticket(5, status="open", blocked_by=[3]),
            ticket(6, status="open"),
            ticket(7, status="parked"),
        ])
        self.assertEqual([entry["id"] for entry in frontier(graph)], [4, 6])

    def test_a_failed_blocker_holds_its_dependents(self):
        graph = build_graph([ticket(1, status="failed"), ticket(2, status="open", blocked_by=[1])])
        self.assertEqual(frontier(graph), [])

    def test_by_status_counts_every_status(self):
        graph = build_graph([ticket(index + 1, status=status) for index, status in enumerate(STATUSES)])
        self.assertEqual({status: len(ids) for status, ids in by_status(graph).items()}, {status: 1 for status in STATUSES})


if __name__ == "__main__":
    unittest.main()
