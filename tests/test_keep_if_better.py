"""Keep-if-better under a quantitative goal (ticket 39; Implementation Decisions 5 and 14).

The Type-A half (`wayline.goal`) is tested on its own: which files are the seeds, what the goal's
command printed for each, and what the readings say. The conductor half is driven with the fake
worker on the one-ticket fixture, retitled as a goal ticket that writes its per-seed readings in
its worktree, and with the fake job runner on the sweep fixture, whose three jobs each write one
seed's reading after the branch reached `main`. The seeds land on both sides of the margin, and
what is asserted is what the owner and the report read: the journal, `main`, the branches, the
worktrees, the findings, and the ticket files.
"""

import io
import json
import statistics
import unittest

from tests import machine
from tests.projects import open_goal, open_objective
from tests.test_conductor import ConductorCase, done, drive, patch
from tests.test_sweep import RATES, SweepCase
from wayline import goal as goals
from wayline import proposals, replay, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import PROGRESS, make_event

TITLE = "Raise the held-out AUROC"
SEEDS = ("metrics/seed-1.txt", "metrics/seed-2.txt", "metrics/seed-3.txt")


def measure(**overrides):
    """A goal's measure in `objectives.json`'s shape (decision 17): what keep-if-better reads in place of GOAL.json."""
    record = {
        "metric": "auroc", "direction": "up", "target": 0.99, "dataset_or_split": "synthetic",
        "held_out_split": "heldout", "eval_command": "cat {artifact}",
        "baseline": {"value": None, "source": None}, "min_seeds": None,
    }
    record.update(overrides)
    return record


def set_measure(ledger, identifier="O1", **overrides):
    """Give the goal `identifier` the measure `measure(**overrides)`, as `objectives.json` holds it (ticket 87)."""
    record = ledger.read_json("objectives.json")
    for objective in record["objectives"]:
        if objective["id"] == identifier:
            objective["measure"] = measure(**overrides)
    ledger.write_json("objectives.json", record, schema="objectives")


def prior_reading(ledger, value, kept=True, ticket=99, goal="O1"):
    """A reading an earlier ticket left in the journal for the goal `goal`."""
    ledger.append_event(PROGRESS, {"metric": "auroc", "value": value, "ticket": ticket, "run_id": "t%d-a1" % ticket, "kept": kept,
                                   "goal": goal}, ticket=ticket)


def seeds(*values, extra=None):
    """A patch writing one reading per seed, as `auroc: <value>` lines the goal's `cat` prints."""
    files = {"metrics/seed-%d.txt" % index: "auroc: %s\n" % value for index, value in enumerate(values, start=1)}
    files.update(extra or {})
    return patch(files, message="ticket 1: measure the change")


def finding_result(**extra):
    return done(outputs_written=list(SEEDS), findings=[
        {"text": "Interaction terms lift the held-out AUROC.", "provenance": "metrics/seed-1.txt#auroc"}], **extra)


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, event, text, project=None, ticket=None):
        self.sent.append((event, text, ticket))


# --- the Type-A half -------------------------------------------------------------------------


def goal_objective(identifier="O1", metric="auroc", status="open", direction="up", **overrides):
    return {"id": identifier, "text": "Does it improve?", "status": status, "answer": None, "evidence": [], "reframed_as": None,
            "measure": None if metric is None else measure(metric=metric, direction=direction, **overrides)}


class AppliesTest(unittest.TestCase):
    """A ticket names its goal by objective (`goal: "O1"`), and everything it is judged by is that goal's measure."""

    def test_a_ticket_whose_goal_is_an_open_goal_is_judged_on_that_goal(self):
        found, skip = goals.goal_for({"goal": "O2"}, [goal_objective(), goal_objective("O2", metric="loss", direction="down")])
        self.assertIsNone(skip)
        self.assertEqual((found["id"], found["measure"]["metric"]), ("O2", "loss"))

    def test_why_it_is_not_judged(self):
        self.assertEqual(goals.applies({"objectives": ["O1"]}, [goal_objective()]), "the ticket names no goal")
        self.assertEqual(goals.applies({"goal": "O1"}, [goal_objective(metric=None)]),
                         "the ticket's goal O1 has no measure, so nothing measures it")
        self.assertEqual(goals.applies({"goal": "O2"}, [goal_objective()]),
                         "the ticket's goal O2 has no measure, so nothing measures it")

    def test_a_closed_goal_is_not_judged(self):
        for status in ("answered", "parked", "dropped"):
            with self.subTest(status=status):
                self.assertEqual(goals.applies({"goal": "O1"}, [goal_objective(status=status)]),
                                 "the ticket's goal O1 is %s, and keep-if-better judges only a goal pursued now" % status)


class JudgeTest(unittest.TestCase):
    def test_a_mean_better_by_more_than_one_sd_is_kept(self):
        judged = goals.judge("auroc", (0.90, 0.91, 0.92), 0.80, "up")
        self.assertTrue(judged.kept)
        self.assertAlmostEqual(judged.mean, 0.91)
        self.assertAlmostEqual(judged.sd, statistics.stdev((0.90, 0.91, 0.92)))
        self.assertEqual((judged.seeds, judged.best, judged.short), (3, 0.80, None))

    def test_a_gain_of_exactly_one_sd_is_not_more_than_one_and_is_discarded(self):
        judged = goals.judge("auroc", (0.80, 0.85, 0.90), 0.80, "up")
        self.assertAlmostEqual(judged.sd, 0.05)
        self.assertFalse(judged.kept)

    def test_a_worse_mean_is_discarded(self):
        self.assertFalse(goals.judge("auroc", (0.70, 0.71, 0.72), 0.80, "up").kept)

    def test_down_keeps_a_lower_mean_and_discards_a_higher_one(self):
        self.assertTrue(goals.judge("loss", (0.40, 0.41, 0.42), 0.50, "down").kept)
        self.assertFalse(goals.judge("loss", (0.60, 0.61, 0.62), 0.50, "down").kept)

    def test_with_nothing_to_beat_the_change_is_kept(self):
        self.assertTrue(goals.judge("auroc", (0.1, 0.9, 0.5), None, "up").kept)

    def test_fewer_seeds_than_asked_judge_nothing_and_ask_for_more(self):
        judged = goals.judge("auroc", (0.95, 0.96), 0.10, "up", min_seeds=3)
        self.assertFalse(judged.kept)
        self.assertIn("at least 3", judged.short)
        self.assertIn("1 more seed", judged.short)

    def test_the_margin_is_the_policy_s(self):
        self.assertTrue(goals.judge("auroc", (0.80, 0.85, 0.90), 0.80, "up", margin_sd=0.5).kept)
        self.assertFalse(goals.judge("auroc", (0.90, 0.91, 0.92), 0.80, "up", margin_sd=20).kept)

    def test_at_one_seed_any_strict_gain_is_kept(self):
        """A deterministic goal (`min_seeds` 1): one reading, and a gain however small is kept; a tie is not."""
        self.assertTrue(goals.judge("count", (5.0001,), 5.0, "up", min_seeds=1).kept)
        self.assertFalse(goals.judge("count", (5.0,), 5.0, "up", min_seeds=1).kept)
        self.assertFalse(goals.judge("count", (4.0, 6.5), 5.0, "up", min_seeds=1, margin_sd=20).kept, "several readings meet the margin")
        self.assertTrue(goals.judge("error", (0.29,), 0.3, "down", min_seeds=1).kept)


class MinSeedsTest(unittest.TestCase):
    def test_a_measure_s_own_min_seeds_overrides_the_policy_s(self):
        self.assertEqual(goals.min_seeds(measure(min_seeds=1), {"min_seeds": 3}), 1)
        self.assertEqual(goals.min_seeds(measure(min_seeds=None), {"min_seeds": 5}), 5)
        self.assertEqual(goals.min_seeds(measure(), {}), 3)


class BestTest(unittest.TestCase):
    def progress(self, *rows):
        return [{"goal": goal, "metric": "auroc", "value": value, "kept": kept} for goal, value, kept in rows]

    def test_the_best_is_the_best_kept_reading_of_this_goal_in_its_direction(self):
        readings = self.progress(("O1", 0.8, True), ("O1", 0.95, False), ("O1", 0.85, True), ("O2", 0.99, True))
        self.assertEqual(goals.best_kept(readings, goal_objective()), 0.85)
        self.assertEqual(goals.best_kept(readings, goal_objective(direction="down")), 0.8)
        self.assertEqual(goals.best_kept(readings, goal_objective("O2")), 0.99)

    def test_a_reading_of_another_goal_on_the_same_metric_is_not_this_goal_s(self):
        readings = self.progress(("O2", 0.99, True), (None, 0.98, True))
        self.assertIsNone(goals.best_kept(readings, goal_objective()))
        self.assertFalse(goals.reached(readings, goal_objective()))

    def test_before_anything_was_kept_the_baseline_is_the_best_and_never_reaches_the_target(self):
        goal = goal_objective(baseline={"value": 0.995, "source": "the paper"})
        self.assertEqual(goals.best_kept([], goal), 0.995)
        self.assertFalse(goals.reached([], goal))

    def test_the_goal_is_reached_at_or_beyond_the_target(self):
        self.assertTrue(goals.reached(self.progress(("O1", 0.99, True)), goal_objective()))
        self.assertFalse(goals.reached(self.progress(("O1", 0.999, False)), goal_objective()))
        self.assertTrue(goals.reached(self.progress(("O1", 0.2, True)), goal_objective(direction="down", target=0.3)))
        self.assertFalse(goals.reached(self.progress(("O1", 0.999, True)), goal_objective(target=None)))

    def test_the_payloads_come_from_the_journal_in_order(self):
        events = [make_event(PROGRESS, {"goal": "O1", "metric": "auroc", "value": 0.8, "ticket": 1, "run_id": "t1-a1", "kept": True})]
        self.assertEqual(goals.kept_readings(goals.progress_payloads(events), "O1"), [0.8])


class SeedsTest(ConductorCase):
    def test_each_output_is_a_seed_and_a_glob_names_every_match_once(self):
        for name in ("a/1.txt", "a/2.txt", "b.txt"):
            (self.temp / name).parent.mkdir(parents=True, exist_ok=True)
            (self.temp / name).write_text("x", encoding="utf-8")
        found = goals.seed_artifacts(["b.txt", "a/*.txt", "a/1.txt", "missing.txt", "../escape", "/etc/passwd"], self.temp)
        self.assertEqual([path.relative_to(self.temp).as_posix() for path in found], ["b.txt", "a/1.txt", "a/2.txt"])

    def test_the_command_reads_the_artifact_and_the_held_out_split(self):
        artifact = self.temp / "seed.json"
        artifact.write_text(json.dumps({"auroc": 0.7}), encoding="utf-8")
        command = 'test "$WAYLINE_HELD_OUT_SPLIT" = heldout && test {split} = heldout && cat {artifact}'
        self.assertEqual(goals.evaluate(measure(eval_command=command), [artifact], self.project, 30), (0.7,))

    def test_no_seed_a_failing_command_and_no_number_are_each_an_error(self):
        artifact = self.temp / "seed.txt"
        artifact.write_text("nothing here\n", encoding="utf-8")
        with self.assertRaisesRegex(goals.GoalError, "no seed artifact"):
            goals.evaluate(measure(), [], self.project, 30)
        with self.assertRaisesRegex(goals.GoalError, "exited 3"):
            goals.evaluate(measure(eval_command="exit 3"), [artifact], self.project, 30)
        with self.assertRaisesRegex(goals.GoalError, "printed no number for `auroc`"):
            goals.evaluate(measure(), [artifact], self.project, 30)


class ViewTest(unittest.TestCase):
    def test_the_view_keeps_each_evaluation_and_forgets_a_discard_at_the_next_launch(self):
        view = replay.replay([
            make_event("progress", {"metric": "auroc", "value": 0.8, "ticket": 1, "run_id": "t1-a1", "kept": False}, ticket=1),
            make_event("discarded", {"ticket": 1, "metric": "auroc", "best": 0.9, "sd": 0.01, "seeds": 3}, ticket=1),
        ])
        self.assertEqual(view.progress["t1-a1"]["kept"], False)
        self.assertEqual(view.discarded[1]["best"], 0.9)
        replay.replay([make_event("ticket_launched", {"ticket": 1, "attempt": 2}, ticket=1)], view)
        self.assertNotIn(1, view.discarded)
        self.assertIn("t1-a1", view.progress)


# --- the conductor: a done result, judged in its worktree ---------------------------------------


class GoalTicketCase(ConductorCase):
    """The one-ticket fixture as a goal ticket: it writes three seeds under `metrics/` and reports `auroc`."""

    def setUp(self):
        super().setUp()
        ticket, body = self.ticket_and_body()
        ticket.update(title=TITLE, touches=["metrics/"], outputs=["metrics/seed-*.txt"],
                      objectives=["O1"], goal="O1",
                      acceptance={"machine": ["test -f metrics/seed-1.txt"], "quality": []})
        tickets.write_ticket(self.ledger, ticket, body)
        (tickets.tickets_dir(self.project) / "01-write-the-hello-file.md").unlink()  # the new title names a new file
        open_goal(self.project, metric="auroc")  # O1: the goal the ticket names, whose measure gives the metric
        self.recorder = Recorder()

    def ticket_and_body(self):
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        if not path.exists():
            path = tickets.tickets_dir(self.project) / tickets.filename({"id": 1, "title": TITLE})
        return tickets.read_ticket(path)

    def body(self):
        return self.ticket_and_body()[1]

    def set_goal(self, identifier="O1", **overrides):
        set_measure(self.ledger, identifier, **overrides)

    def prior(self, value, kept=True, ticket=99, goal="O1"):
        prior_reading(self.ledger, value, kept, ticket, goal)

    def set_harness(self, **changes):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness.update(changes)
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def conduct(self, *scripted, waves=None, conductor=None):
        with worker.use_fake() as fake:
            for envelope, applied in scripted:
                fake.script(envelope, patch=applied)
            self.conductor = conductor or Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.notify = self.recorder
            results = drive(self.conductor, waves)
            self.calls = list(fake.calls)
        return results

    def findings(self):
        text = (self.project / "research" / "findings.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def said(self):
        return self.conductor.out.getvalue()

    def aim_at(self, objective):
        """Point the ticket's `goal` at `objective`."""
        ticket, body = self.ticket_and_body()
        tickets.write_ticket(self.ledger, dict(ticket, objectives=[objective["id"]], goal=objective["id"]), body)

    def on_main(self, path):
        return path in self.git("ls-tree", "-r", "--name-only", "main").split("\n")


class KeptTest(GoalTicketCase):
    def test_a_change_better_by_more_than_one_sd_is_fast_forwarded_and_journaled_as_kept(self):
        self.set_goal()
        self.prior(0.80)
        results = self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)))
        self.assertEqual(self.ticket()["status"], "done")
        self.assertIn("integrated", self.sequence())
        self.assertTrue(self.on_main("metrics/seed-2.txt"))
        progress = self.payload("progress")
        self.assertEqual((progress["ticket"], progress["run_id"], progress["kept"], progress["metric"]), (1, "t1-a1", True, "auroc"))
        self.assertAlmostEqual(progress["value"], 0.91)
        self.assertNotIn("discarded", self.sequence())
        self.assertFalse(self.worktree().exists())
        self.assertNotIn("ticket/1", self.branches())
        self.assertEqual(sum(result.kept for result in results), 1)
        # The fast-forward comes first: a kept change is journaled as kept only once it is on main.
        names = self.sequence()
        self.assertLess(names.index("integrated"), len(names) - 1 - names[::-1].index("progress"))
        finding = self.findings()[-1]
        self.assertEqual((finding["negative"], finding["provenance"]), (False, "metrics/seed-1.txt#auroc"))

    def test_with_nothing_kept_before_and_no_baseline_the_first_change_is_kept(self):
        self.set_goal()
        self.conduct((finding_result(), seeds(0.1, 0.5, 0.9)))
        self.assertTrue(self.payload("progress")["kept"])
        self.assertIn("integrated", self.sequence())

    def test_down_keeps_a_lower_mean(self):
        self.set_goal(direction="down", target=0.01)
        self.prior(0.50)
        self.conduct((finding_result(), seeds(0.40, 0.41, 0.42)))
        self.assertTrue(self.payload("progress")["kept"])

    def test_the_goal_command_runs_from_main_with_the_held_out_split(self):
        self.set_goal(eval_command='test "$WAYLINE_HELD_OUT_SPLIT" = heldout && test "$PWD" = "$WAYLINE_PROJECT" && cat {artifact}')
        self.conduct((finding_result(), seeds(0.9, 0.9, 0.9)))
        self.assertTrue(self.payload("progress")["kept"], self.said())

    def test_the_worker_s_own_goal_progress_is_not_what_is_judged(self):
        self.set_goal()
        self.prior(0.80)
        self.conduct((finding_result(goal_progress={"metric": "auroc", "value": 0.99}), seeds(0.70, 0.71, 0.72)))
        self.assertFalse(self.payload("progress")["kept"])
        self.assertAlmostEqual(self.payload("progress")["value"], 0.71)

    def test_an_objectives_json_that_cannot_be_read_is_said_and_the_ticket_integrated_unjudged(self):
        self.set_goal()
        self.ledger.write_json("objectives.json", {"objectives": 3})
        self.conduct((finding_result(), seeds(0.1, 0.1, 0.1)))
        self.assertIn("integrated", self.sequence())
        self.assertNotIn("progress", self.sequence())
        self.assertIn("research/objectives.json cannot be read", self.said())

    def test_a_ticket_serving_an_objective_with_no_measure_is_integrated_with_nothing_in_place_of_keep_if_better(self):
        objective = open_objective(self.project, "Is the hello file read?")
        ticket, body = self.ticket_and_body()
        tickets.write_ticket(self.ledger, dict(ticket, objectives=[objective["id"]], goal=None), body)
        self.conduct((finding_result(), seeds(0.1, 0.1, 0.1)))
        self.assertIn("integrated", self.sequence())
        self.assertNotIn("progress", self.sequence())
        self.assertNotIn("discarded", self.sequence())


class PerGoalTest(GoalTicketCase):
    """Ticket 87: keep-if-better runs per goal, each from its own events and on its own measure."""

    def test_each_goal_is_judged_from_its_own_best_and_a_change_is_measured_on_its_own_goal_only(self):
        second = open_goal(self.project, "Does the change lower the loss?", metric="loss", direction="down")
        self.set_goal()
        self.set_goal(second["id"], metric="loss", direction="down", eval_command="touch measured-on-o2 && cat {artifact}")
        self.prior(0.80)
        self.prior(0.99, ticket=98, goal=second["id"])  # a reading of another goal, better than anything here, is not O1's
        self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)))
        progress = self.payload("progress")
        self.assertEqual((progress["goal"], progress["kept"]), ("O1", True))
        self.assertFalse((self.project / "measured-on-o2").exists(), "a change kept for O1 is never measured on O2")
        self.assertEqual([event["payload"]["goal"] for event in self.events("progress")], ["O1", second["id"], "O1"])

    def test_a_discard_names_its_goal(self):
        self.set_goal()
        self.prior(0.80)
        self.conduct((finding_result(), seeds(0.80, 0.85, 0.90)))
        self.assertEqual(self.payload("discarded")["goal"], "O1")

    def test_a_measure_with_one_seed_keeps_any_strict_gain(self):
        self.set_goal(min_seeds=1)
        self.prior(0.80)
        self.conduct((done(outputs_written=["metrics/seed-1.txt"], findings=[]), seeds(0.8001)))
        progress = self.payload("progress")
        self.assertEqual((progress["kept"], progress["goal"]), (True, "O1"))
        self.assertIn("integrated", self.sequence())

    def test_a_measure_with_one_seed_does_not_keep_a_tie(self):
        self.set_goal(min_seeds=1)
        self.prior(0.80)
        self.conduct((done(outputs_written=["metrics/seed-1.txt"], findings=[]), seeds(0.80)))
        self.assertFalse(self.payload("progress")["kept"])


class DiscardedTest(GoalTicketCase):
    def setUp(self):
        super().setUp()
        self.set_goal()
        self.prior(0.80)
        self.results = self.conduct((finding_result(), seeds(0.80, 0.85, 0.90)))

    def test_it_is_journaled_with_the_metric_the_best_the_sd_and_the_seeds(self):
        discarded = self.payload("discarded")
        self.assertEqual((discarded["ticket"], discarded["metric"], discarded["best"], discarded["seeds"]), (1, "auroc", 0.80, 3))
        self.assertAlmostEqual(discarded["sd"], 0.05)
        progress = self.payload("progress")
        self.assertEqual((progress["kept"], progress["run_id"]), (False, "t1-a1"))
        self.assertAlmostEqual(progress["value"], 0.85)

    def test_the_ticket_is_done_and_not_integrated(self):
        self.assertEqual(self.ticket()["status"], "done")
        self.assertIn("ticket_done", self.sequence())
        self.assertNotIn("integrated", self.sequence())
        self.assertFalse(self.on_main("metrics/seed-1.txt"))
        self.assertEqual(self.results[-1].reason, "frontier_empty")
        self.assertIn("Discarded by keep-if-better", self.body())

    def test_the_branch_and_its_worktree_stay_under_the_attempt_s_name(self):
        self.assertIn("ticket/1-a1", self.branches())
        self.assertNotIn("ticket/1", self.branches())
        self.assertTrue((self.project / ".worktrees" / "1-a1" / "metrics" / "seed-1.txt").is_file())
        self.assertFalse(self.worktree().exists())
        self.assertIn("ticket/1-a1", self.body())

    def test_its_findings_are_negative_results_citing_the_worktree(self):
        finding = self.findings()[-1]
        self.assertEqual((finding["ticket"], finding["negative"]), (1, True))
        self.assertEqual(finding["provenance"], ".worktrees/1-a1/metrics/seed-1.txt#auroc")
        from wayline import provenance
        self.assertIn(".worktrees/1-a1/metrics/seed-1.txt", provenance.manifest_paths(provenance.read_manifest(self.ledger)))
        self.assertTrue(self.payload("finding")["negative"])

    def test_it_earns_no_verdict(self):
        self.assertEqual(self.conductor.verdicts, [])
        self.assertNotIn("verdict", self.sequence())

    def test_a_restart_keeps_the_worktree_and_journals_nothing_twice(self):
        again = Conductor(self.project, out=io.StringIO())
        again.readings, again.notify = machine.recorded, self.recorder
        again.wave()
        self.assertTrue((self.project / ".worktrees" / "1-a1").exists())
        self.assertIn("ticket/1-a1", self.branches())
        self.assertEqual([len(self.events(name)) for name in ("progress", "discarded")], [2, 1])

    def test_the_report_draws_the_discard_on_the_trajectory(self):
        from wayline import provenance
        provenance.render_report(self.project, offline=True, draft=False)
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("ticket 1: mean 0.85 against the best 0.8, standard deviation 0.05, seeds 3", text)
        self.assertIn("(ticket 1): Interaction terms lift the held-out AUROC.", text)
        self.assertNotIn("res:unmanifested/.#", text)

    def test_a_rerun_starts_from_main_and_leaves_the_discarded_change_where_it_is(self):
        tickets.write_ticket(self.ledger, dict(self.ticket(), status="open"), self.body())
        self.ledger.append_event("ticket_rerun", {"ticket": 1, "by": "cli"}, ticket=1)
        again = Conductor(self.project, out=io.StringIO())
        self.conduct((finding_result(), seeds(0.95, 0.96, 0.97, extra={"metrics/seed-9.txt": "auroc: 0.96\n"})),
                     conductor=again)
        progress = [event["payload"] for event in self.events("progress")]
        self.assertEqual([(payload["run_id"], payload["kept"]) for payload in progress],
                         [("t99-a1", True), ("t1-a1", False), ("t1-a2", True)])
        self.assertTrue(self.on_main("metrics/seed-9.txt"))
        self.assertTrue((self.project / ".worktrees" / "1-a1" / "metrics" / "seed-1.txt").is_file())
        self.assertIn("ticket/1-a1", self.branches())
        self.assertIn("auroc: 0.8\n", (self.project / ".worktrees" / "1-a1" / "metrics" / "seed-1.txt").read_text())

    def test_a_proposal_that_merely_reruns_it_is_parked_as_a_duplicate(self):
        outcome = proposals.admit_proposals(self.project, [{
            "title": TITLE, "kind": "code", "why": "run it again, it may pass this time", "radius": "moderate",
            "touches": ["metrics/"]}], origin_ticket=1, origin_prefix="ticket 1 attempt 2", proposed_by="worker:1")
        self.assertEqual((outcome[0]["outcome"], outcome[0]["reason"]), ("parked", "duplicate"))


class StaleJudgmentTest(GoalTicketCase):
    def test_a_keep_saved_before_a_better_change_was_kept_is_judged_again(self):
        """A change judged better, whose integration waited while another ticket raised the best, is not kept on the old word."""
        self.set_goal()
        self.prior(0.80)
        self.ledger.write_json("sessions/1/1/goal.json", {"metric": "auroc", "values": [0.90, 0.91, 0.92], "mean": 0.91,
                                                          "sd": 0.01, "best": 0.80, "kept": True})
        self.prior(0.95, ticket=98)
        self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)))
        self.assertEqual(self.payload("discarded")["best"], 0.95)
        self.assertNotIn("integrated", self.sequence())
        self.assertFalse(self.ledger.read_json("sessions/1/1/goal.json")["kept"])


class RevertTest(GoalTicketCase):
    def test_a_change_main_already_undid_is_not_reverted_again(self):
        from types import SimpleNamespace
        base = self.git("rev-parse", "main")
        self.commit_on_main("extra.txt")
        commit = self.git("rev-parse", "main")
        self.git("rm", "-q", "extra.txt")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main: drop extra.txt")
        head = self.git("rev-parse", "main")
        self.ledger.write_json("sessions/1/1/integration.json", {"base": base, "commit": commit})
        driven = Conductor(self.project, out=io.StringIO())
        self.assertIsNone(driven._revert(SimpleNamespace(id=1, number=1)))
        self.assertEqual(self.git("rev-parse", "main"), head)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")  # nothing left staged


class ReportMeansTest(unittest.TestCase):
    def test_each_discard_is_paired_with_its_own_attempt_s_mean(self):
        from wayline.provenance import _discarded_means
        def progress(value, run, kept=False):
            return make_event("progress", {"metric": "auroc", "value": value, "ticket": 1, "run_id": run, "kept": kept, "goal": "O1"},
                              ticket=1)
        def discarded():
            return make_event("discarded", {"ticket": 1, "metric": "auroc", "best": 0.9, "sd": 0.01, "seeds": 3, "goal": "O1"}, ticket=1)
        pairs = _discarded_means([progress(0.5, "t1-a1"), discarded(), progress(0.6, "t1-a2"), discarded(),
                                  progress(0.7, "t1-a3")], "O1")
        self.assertEqual([mean for _, mean in pairs], [0.5, 0.6])


class ShortOrUnmeasuredTest(GoalTicketCase):
    def test_fewer_seeds_than_the_policy_fail_the_ticket_with_a_request_for_more(self):
        self.set_goal()
        self.conduct((finding_result(), seeds(0.9, 0.95)))
        failed = self.events("ticket_failed")[0]["payload"]
        self.assertIn("at least 3", failed["reason"])
        self.assertEqual(failed["next"], "resume")
        self.assertEqual(self.ticket()["status"], "needs_human", "its resume had nothing scripted")
        self.assertNotIn("progress", self.sequence())
        self.assertNotIn("integrated", self.sequence())

    def test_a_command_that_measures_nothing_fails_the_ticket(self):
        self.set_goal(eval_command="exit 3")
        self.conduct((finding_result(), seeds(0.9, 0.9, 0.9)))
        self.assertIn("keep-if-better measured nothing", self.events("ticket_failed")[0]["payload"]["reason"])
        self.assertNotIn("integrated", self.sequence())

    def test_the_baseline_is_the_best_before_anything_was_kept(self):
        self.set_goal(baseline={"value": 0.95, "source": "the paper"})
        self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)))
        self.assertEqual(self.payload("discarded")["best"], 0.95)


class GoalReachedTest(GoalTicketCase):
    def test_code_writes_the_goal_reached_and_the_rule_ends_the_run_goal_reached(self):
        self.set_goal(target=0.9)
        results = self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)), waves=4)
        self.assertTrue(results[-1].ended)
        self.assertEqual(results[-1].reason, "goal_reached")
        self.assertEqual([event["payload"]["reason"] for event in self.events("run_ended")], ["goal_reached"])
        self.assertEqual([event for event, _, _ in self.recorder.sent], ["goal_reached"])
        self.assertIn("every goal the stopping rule waits on is reached (O1)", self.recorder.sent[0][1])
        written = [event["payload"] for event in self.events("objective") if event["payload"]["status"] == "answered"]
        self.assertEqual([(payload["id"], payload["by"]) for payload in written], [("O1", "code")])
        record = json.loads((self.project / "research" / "objectives.json").read_text(encoding="utf-8"))["objectives"][0]
        self.assertIn("reached: the best kept auroc is 0.91 against the target 0.9 (up), measured by code on t1-a1", record["answer"])

    def test_a_goal_closed_by_another_way_ends_the_rule_objectives_closed(self):
        self.set_goal(target=0.9)
        second = open_objective(self.project, "Is the hello file read?")
        from wayline.objectives import change_objective
        change_objective(self.project, second["id"], "dropped", "owner", answer="not worth asking")
        results = self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)), waves=4)
        self.assertEqual(results[-1].reason, "objectives_closed")

    def test_a_discarded_reading_beyond_the_target_does_not_reach_it(self):
        self.set_goal(target=0.5)
        self.prior(0.45)
        results = self.conduct((finding_result(), seeds(0.1, 0.5, 0.9)))
        self.assertEqual(results[-1].reason, "frontier_empty")
        self.assertEqual(json.loads((self.project / "research" / "objectives.json").read_text(encoding="utf-8"))["objectives"][0]["status"],
                         "open")

    def test_under_frontier_the_run_goes_on_past_the_target(self):
        self.set_goal(target=0.9)
        self.set_harness(stop_when="frontier")
        results = self.conduct((finding_result(), seeds(0.90, 0.91, 0.92)))
        self.assertEqual(results[-1].reason, "frontier_empty")
        self.assertEqual(self.recorder.sent, [])


# --- the conductor: a running result, judged once its jobs wrote the seeds ------------------------


class JobsGoalCase(SweepCase):
    """The sweep fixture's experiment as a goal ticket: each of its three jobs writes one seed's `auroc`."""

    def setUp(self):
        super().setUp()
        path = tickets.tickets_dir(self.project) / "01-sweep-the-learning-rate.md"
        ticket, body = tickets.read_ticket(path)
        ticket.update(objectives=["O1"], goal="O1")
        tickets.write_ticket(self.ledger, ticket, body)
        open_goal(self.project, metric="auroc")
        set_measure(self.ledger)

    def plain_jobs(self, jobs):
        for job in ("t1-1", "t1-2", "t1-3"):
            jobs.script(["running", "exited"], outputs=self.output(job), job_id=job)

    @staticmethod
    def output(job):
        values = {"t1-1": 0.86, "t1-2": 0.86, "t1-3": 0.87}
        return {"results/sweep/lr-%s.json" % RATES[job]: json.dumps({"lr": float(RATES[job]), "auroc": values[job]}) + "\n"}

    def prior(self, value):
        prior_reading(self.ledger, value)

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True).stdout

    def on_main(self, path):
        return path in self.git("ls-tree", "-r", "--name-only", "main").split("\n")


class JobsKeptTest(JobsGoalCase):
    def test_the_jobs_seeds_are_judged_and_a_better_change_stays_on_main(self):
        self.prior(0.80)
        self.run_sweep(script=self.plain_jobs)
        self.assertEqual((self.status(1), self.status(2)), ("done", "done"))
        progress = [event["payload"] for event in self.events("progress")][-1]
        self.assertEqual((progress["ticket"], progress["kept"], progress["run_id"]), (1, True, "t1-a1"))
        self.assertAlmostEqual(progress["value"], statistics.fmean((0.86, 0.86, 0.87)))
        self.assertTrue(self.on_main("sweep/plan.md"))
        self.assertFalse((self.project / ".worktrees" / "1").exists())
        self.assertNotIn("ticket/1", self.git("branch"))


class JobsDiscardedTest(JobsGoalCase):
    def setUp(self):
        super().setUp()
        self.prior(0.86)
        self.run_sweep(script=self.plain_jobs)

    def test_the_change_is_reverted_on_main_and_kept_on_its_branch(self):
        self.assertEqual(self.status(1), "done")
        self.assertFalse(self.on_main("sweep/plan.md"))
        self.assertIn("ticket 1: discarded by keep-if-better", self.git("log", "--format=%s", "main"))
        self.assertIn("ticket/1-a1", self.git("branch"))
        self.assertTrue((self.project / ".worktrees" / "1-a1" / "sweep" / "plan.md").is_file())
        self.assertIn("sweep/plan.md", self.git("ls-tree", "-r", "--name-only", "ticket/1-a1"))

    def test_it_is_journaled_as_discarded_and_the_run_goes_on(self):
        discarded = [event["payload"] for event in self.events("discarded")]
        self.assertEqual([(payload["ticket"], payload["best"], payload["seeds"]) for payload in discarded], [(1, 0.86, 3)])
        self.assertFalse([event for event in self.events("progress")][-1]["payload"]["kept"])
        self.assertEqual(self.status(2), "done")
        self.assertEqual(self.results[-1].reason, "frontier_empty")


if __name__ == "__main__":
    unittest.main()
