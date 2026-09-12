"""The frontier, the launchable subset, and the pick order (Implementation Decisions 5, steps 7 to 9).

These are pure functions of a graph, so the tests build graphs rather than projects: what is
asserted is which ticket ids a wave would launch and in what order, which is what the conductor
acts on and what the five-ticket fixture then demonstrates end to end.
"""

import unittest

from tests.projects import ProjectTestCase
from wayline import schedule
from wayline.tickets import frontier


def entry(identifier, **fields):
    """One `graph.json` entry: the scheduling fields of decision 2, with the defaults a ticket has."""
    base = {
        "id": identifier, "kind": "code", "status": "open", "difficulty": 1, "blocked_by": [],
        "blocking": None, "human_only": False, "touches": [], "resources": None,
        "role": "coder", "skills": [], "attempt": 0,
    }
    base.update(fields)
    return base


def graph(*entries):
    return {"snapshot": {}, "tickets": list(entries)}


def ids(entries):
    return [item["id"] for item in entries]


class FrontierTest(unittest.TestCase):
    """Open tickets whose blockers are satisfied, minus what an open decision pauses."""

    def test_a_blocker_holds_its_dependents_until_it_is_done_or_accepted(self):
        built = graph(entry(1, status="done"), entry(2, status="accepted"), entry(3, status="failed"),
                      entry(4, blocked_by=[1, 2]), entry(5, blocked_by=[3]), entry(6))
        self.assertEqual(ids(frontier(built)), [4, 6])

    def test_a_difficulty_five_blocker_counts_only_once_it_is_accepted(self):
        done = graph(entry(1, difficulty=5, status="done"), entry(2, blocked_by=[1]))
        self.assertEqual(ids(frontier(done)), [])
        accepted = graph(entry(1, difficulty=5, status="accepted"), entry(2, blocked_by=[1]))
        self.assertEqual(ids(frontier(accepted)), [2])

    def test_a_difficulty_four_blocker_counts_when_it_is_merely_done(self):
        built = graph(entry(1, difficulty=4, status="done"), entry(2, blocked_by=[1]))
        self.assertEqual(ids(frontier(built)), [2])

    def test_an_open_decision_pauses_its_whole_subgraph_and_nothing_else(self):
        built = graph(entry(1, kind="decision", blocking="subgraph"),
                      entry(2, blocked_by=[1]), entry(3, blocked_by=[2]), entry(4))
        # 2 waits on the decision by a blocking edge, 3 waits on 2; 4 is in another part of the graph.
        self.assertEqual(ids(frontier(built)), [1, 4])

    def test_an_answered_decision_pauses_nothing(self):
        built = graph(entry(1, kind="decision", blocking="subgraph", status="done"), entry(2, blocked_by=[1]))
        self.assertEqual(ids(frontier(built)), [2])

    def test_a_parked_decision_pauses_nothing(self):
        built = graph(entry(1, kind="decision", blocking="subgraph", status="parked"), entry(2))
        self.assertEqual(ids(frontier(built)), [2])

    def test_a_blocking_all_decision_leaves_only_the_decision_tickets(self):
        built = graph(entry(1, kind="decision", blocking="all"),
                      entry(2, kind="decision", blocking="subgraph"), entry(3), entry(4))
        self.assertEqual(ids(frontier(built)), [1, 2])

    def test_a_decision_ticket_is_in_the_frontier_like_any_other(self):
        """The decider (ticket 35) is launched for one, so a paused project can still be unpaused."""
        built = graph(entry(1, kind="decision", blocking="subgraph"))
        self.assertEqual(ids(frontier(built)), [1])


class TouchSetTest(ProjectTestCase):
    """Which two touch sets can collide, read as `hooks/touch_set_guard.sh` reads one path."""

    def test_the_same_file_collides_and_two_files_do_not(self):
        self.assertTrue(schedule.touch_sets_collide(["src/a.py"], ["src/a.py"]))
        self.assertFalse(schedule.touch_sets_collide(["src/a.py"], ["src/b.py"]))

    def test_a_directory_entry_collides_with_everything_below_it(self):
        self.assertTrue(schedule.touch_sets_collide(["notes/"], ["notes/alpha.md"]))
        self.assertTrue(schedule.touch_sets_collide(["notes/alpha.md"], ["notes/"]))
        self.assertTrue(schedule.touch_sets_collide(["notes/"], ["notes/deep/alpha.md"]))
        self.assertTrue(schedule.touch_sets_collide(["notes/"], ["notes/inner/"]))

    def test_a_directory_entry_does_not_collide_with_a_sibling_that_shares_its_prefix(self):
        self.assertFalse(schedule.touch_sets_collide(["notes/"], ["notes-archive/alpha.md"]))
        self.assertFalse(schedule.touch_sets_collide(["src/a.py"], ["src/ab.py"]))

    def test_an_entry_with_no_trailing_slash_is_a_directory_when_the_project_has_one(self):
        (self.temp / "notes").mkdir()
        self.assertTrue(schedule.touch_sets_collide(["notes"], ["notes/alpha.md"], root=self.temp))
        self.assertFalse(schedule.touch_sets_collide(["notes"], ["notes/alpha.md"]))

    def test_one_entry_in_common_is_enough_to_collide(self):
        self.assertTrue(schedule.touch_sets_collide(["a.py", "b.py"], ["c.py", "b.py"]))
        self.assertFalse(schedule.touch_sets_collide(["a.py", "b.py"], ["c.py", "d.py"]))


class CriticalPathTest(unittest.TestCase):
    """The longest chain of unfinished dependents, which is what the pick order asks for first."""

    def test_a_chain_is_as_long_as_what_waits_behind_it(self):
        built = graph(entry(1), entry(2, blocked_by=[1]), entry(3, blocked_by=[2]), entry(4))
        self.assertEqual(schedule.critical_path_lengths(built), {1: 3, 2: 2, 3: 1, 4: 1})

    def test_the_longest_branch_wins_when_a_ticket_has_several(self):
        built = graph(entry(1), entry(2, blocked_by=[1]), entry(3, blocked_by=[1]), entry(4, blocked_by=[3]))
        self.assertEqual(schedule.critical_path_lengths(built)[1], 3)

    def test_a_finished_dependent_holds_up_nothing(self):
        built = graph(entry(1), entry(2, blocked_by=[1], status="done"), entry(3, blocked_by=[2], status="accepted"))
        self.assertEqual(schedule.critical_path_lengths(built)[1], 1)


class LaunchableTest(unittest.TestCase):
    """The frontier minus what collides with running work, minus what the machine cannot host."""

    def test_a_ticket_whose_touch_set_meets_a_running_one_is_not_launchable(self):
        ready = [entry(2, touches=["notes/alpha.md"]), entry(3, touches=["reports/beta.md"])]
        running = [entry(1, status="running", touches=["notes/"])]
        self.assertEqual(ids(schedule.launchable(ready, running)), [3])

    def test_nothing_is_removed_when_nothing_is_running(self):
        ready = [entry(2, touches=["notes/alpha.md"]), entry(3, touches=["notes/alpha.md"])]
        self.assertEqual(ids(schedule.launchable(ready)), [2, 3])

    def test_a_ticket_whose_resources_are_not_free_is_not_launchable(self):
        ready = [entry(2, resources={"gpu": 1}), entry(3)]
        self.assertEqual(ids(schedule.launchable(ready, free=lambda item: not item["resources"])), [3])


class PickTest(unittest.TestCase):
    """Wave step 9: up to `max_parallel_workers`, in the spec's order, never two that collide."""

    def test_the_longer_critical_path_goes_first(self):
        built = graph(entry(1), entry(2), entry(3, blocked_by=[2]))
        self.assertEqual(ids(schedule.pick(built, slots=2)), [2, 1])

    def test_a_ticket_that_reports_a_goal_metric_goes_before_one_that_does_not(self):
        built = graph(entry(1), entry(2))
        self.assertEqual(ids(schedule.pick(built, slots=2, goal_tickets={2})), [2, 1])

    def test_the_harder_ticket_goes_first_and_cheap_only_turns_that_around(self):
        built = graph(entry(1, difficulty=1), entry(2, difficulty=4))
        self.assertEqual(ids(schedule.pick(built, slots=2)), [2, 1])
        self.assertEqual(ids(schedule.pick(built, slots=2, action=schedule.CHEAP_ONLY)), [1, 2])

    def test_the_lower_id_breaks_a_tie(self):
        built = graph(entry(3), entry(1), entry(2))
        self.assertEqual(ids(schedule.pick(built, slots=3)), [1, 2, 3])

    def test_a_pick_joins_the_running_set_so_one_wave_never_launches_a_collision(self):
        built = graph(entry(1, touches=["notes/alpha.md"]), entry(2, touches=["notes/"]), entry(3, touches=["reports/"]))
        self.assertEqual(ids(schedule.pick(built, slots=3)), [1, 3])

    def test_no_more_than_the_slots_are_picked(self):
        built = graph(entry(1), entry(2), entry(3))
        self.assertEqual(ids(schedule.pick(built, slots=2)), [1, 2])
        self.assertEqual(ids(schedule.pick(built, slots=1)), [1])

    def test_an_empty_frontier_picks_nothing(self):
        self.assertEqual(schedule.pick(graph(entry(1, status="done")), slots=2), [])
