"""Experiment and analysis tickets end to end (ticket 19; M2 criteria 4 to 9).

`fixtures/projects/sweep/` is run with the fake worker and the fake job runner: the experimenter
writes a three-member job array and returns `running`; the conductor integrates its branch, places
the jobs one GPU job at a time on the recorded machine of `tests/machine.py`, retries the member
that runs out of GPU memory with the ticket's ladder, manifests every output, and closes the ticket;
the analysis ticket then files its findings. What is asserted is what the owner and the next
component can read: the journal, the ticket files, the manifest, the findings, the job files.
"""

import io
import json
import shutil

from tests import machine
from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import project, provenance, replay, resources, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.resources import JobState

SWEEP = FIXTURES_DIR / "projects" / "sweep"
OOM_TAIL = "holding 32768 MiB\ncuMemAlloc of 32768 MiB failed: CUDA_ERROR_OUT_OF_MEMORY\n"
RATES = {"t1-1": "0.03", "t1-2": "0.1", "t1-3": "0.3"}


def output(job, auroc=0.86):
    rate = RATES[job]
    return {"results/sweep/lr-%s.json" % rate: json.dumps({"lr": float(rate), "auroc": auroc}) + "\n"}


def gpu_oom():
    return JobState("oom_gpu", result="exit-code", exit_code=1, reason="the log carries 'CUDA_ERROR_OUT_OF_MEMORY'", log_tail=OOM_TAIL)


def host_oom():
    return JobState("oom_host", result="oom-kill", exit_code=9, reason="the host memory cgroup killed it")


class SweepCase(ProjectTestCase):
    """A laid-out copy of the sweep fixture, run wave by wave until it ends or runs out of waves."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "sweep"
        shutil.copytree(SWEEP, self.project)
        project.init_project(self.project)
        self.ledger = Ledger(self.project)

    def script_jobs(self, jobs):
        """The sweep that goes as planned: t1-3's first attempt runs out of GPU memory, and its retry succeeds."""
        jobs.script(["running", "exited"], outputs=output("t1-1"), job_id="t1-1")
        jobs.script(["exited"], outputs=output("t1-2"), job_id="t1-2")
        jobs.script([gpu_oom()], log=OOM_TAIL, job_id="t1-3")
        jobs.script(["running", "exited"], outputs=output("t1-3", 0.87), job_id="t1-3")

    def run_sweep(self, script=None, readings=machine.recorded, waves=20, conductor=None, limit=None):
        with worker.use_fake() as fake, resources.use_fake_jobs() as jobs:
            fake.load(SWEEP / "fake-worker.json")
            (script or self.script_jobs)(jobs)
            if limit is not None:
                worker.simulate_limit(limit)
            try:
                self.results = self.drive(readings, waves)
            finally:
                worker.simulate_limit(None)
            self.launched = list(jobs.launched)
            self.job_calls = list(jobs.calls)
        return self.results

    def drive(self, readings, waves, conductor=None):
        self.conductor = conductor or Conductor(self.project, out=io.StringIO())
        self.conductor.readings = readings
        results = []
        for _ in range(waves):
            results.append(self.conductor.wave())
            if results[-1].ended:
                break
            self.conductor.settle()
        return results

    # --- reading the project back ---

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def names(self):
        return [event["event"] for event in self.events()]

    def status(self, identifier):
        return {entry["id"]: entry["status"] for entry in tickets.read_tickets(self.project)}[identifier]

    def body(self, identifier):
        name = {1: "01-sweep-the-learning-rate.md", 2: "02-analyse-the-sweep.md"}[identifier]
        return (tickets.tickets_dir(self.project) / name).read_text(encoding="utf-8")

    def job(self, identifier):
        return self.ledger.read_json("jobs/%s.json" % identifier)

    def by_job(self, name):
        found = {}
        for event in self.events(name):
            found.setdefault(event["job"], []).append(event["payload"])
        return found


class SweepTest(SweepCase):
    """The fixture's whole path, as the M2 demo runs it."""

    def setUp(self):
        super().setUp()
        self.run_sweep()

    def test_both_tickets_are_done_and_the_run_ends_on_an_empty_frontier(self):
        self.assertEqual((self.status(1), self.status(2)), ("done", "done"))
        self.assertTrue(self.results[-1].ended)
        self.assertEqual(self.results[-1].reason, "frontier_empty")

    def test_the_experimenter_wrote_the_array_and_its_result_left_the_ticket_running_after_integration(self):
        result = [event for event in self.events("ticket_result") if event["ticket"] == 1][0]["payload"]
        self.assertEqual((result["status"], result["jobs"]), ("running", ["t1-1", "t1-2", "t1-3"]))
        self.assertEqual({self.job(job)["array"] for job in RATES}, {"t1"})
        names = self.names()
        self.assertLess(names.index("integrated"), names.index("job_launched"), "the jobs run the code on main")
        self.assertTrue((self.project / "sweep" / "plan.md").is_file())

    def test_the_ticket_resources_and_retry_reach_every_job_file(self):
        for job in RATES:
            record = self.job(job)
            self.assertEqual(record["devices"]["ram_gb"], 4)
            self.assertEqual(record["wallclock_minutes"], 10)
            self.assertEqual(record["retry"], {"host_oom": [], "gpu_oom": [{"--batch-size": 256}]})
        self.assertEqual(project.read_jobs(self.project)[1], [], "every job file validates")

    def test_one_gpu_job_runs_at_a_time_on_cores_outside_the_reservation(self):
        self.assertEqual([spec.id for spec, _ in self.launched], ["t1-1", "t1-2", "t1-3", "t1-3"])
        for spec, indices in self.launched:
            self.assertEqual(indices, (0,))
            self.assertEqual(spec.gpu_uuids, (machine.GPU_UUID,))
            self.assertEqual(len(spec.cores), 4)
            self.assertFalse(set(spec.cores) & set(range(8)), "CPUAffinity never names a reserved core")
        spans = {}
        for position, event in enumerate(self.events()):
            if event["event"] == "job_launched":
                spans.setdefault(event["job"], [position, None])
            elif event["event"] in ("job_finished", "job_retried") and event["job"] in spans and spans[event["job"]][1] is None:
                spans[event["job"]][1] = position
        ordered = sorted(spans.values())
        for (_, end), (start, _) in zip(ordered, ordered[1:]):
            self.assertLess(end, start, "a job launched only once the one before it had ended")

    def test_the_members_that_found_the_gpu_held_are_journaled_as_waiting_once(self):
        waiting = self.by_job("job_waiting")
        self.assertEqual(sorted(waiting), ["t1-2", "t1-3"])
        self.assertEqual([payload["reason"] for payload in waiting["t1-2"]], ["needs 1 GPU(s) and 0 of 1 is free"])
        self.assertEqual(waiting["t1-2"][0]["ticket"], 1)

    def test_every_member_journals_its_launch_and_its_finish(self):
        self.assertEqual({job: len(items) for job, items in self.by_job("job_launched").items()}, {"t1-1": 1, "t1-2": 1, "t1-3": 2})
        finished = self.by_job("job_finished")
        self.assertEqual(sorted(finished), sorted(RATES))
        for items in finished.values():
            self.assertEqual([(item["exit_code"], item["outputs_ok"]) for item in items], [(0, True)])

    def test_the_gpu_oom_steps_the_ladder_and_the_retry_runs_the_smaller_batch(self):
        self.assertEqual(self.by_job("job_retried"), {"t1-3": [{"job": "t1-3", "attempt": 2, "oom": "gpu", "overrides": {"--batch-size": 256}}]})
        first, second = [spec for spec, _ in self.launched if spec.id == "t1-3"]
        self.assertIn("4096", first.command)
        self.assertEqual(second.command[second.command.index("--batch-size") + 1], "256")
        attempts = self.job("t1-3")["attempts"]
        self.assertEqual([(item["oom"], item["overrides"]) for item in attempts], [("gpu", {}), (None, {"--batch-size": 256})])
        self.assertIn("4096", self.job("t1-3")["command"], "the job file keeps the command the worker declared")
        logs = self.project / "results" / "logs"
        self.assertIn("CUDA_ERROR_OUT_OF_MEMORY", (logs / "t1-3.1.log").read_text(encoding="utf-8"))
        self.assertFalse((logs / "t1-3.log").exists(), "the retry's log starts empty, so an old signature is never read again")
        self.assertEqual(self.job("t1-3")["status"], "exited")

    def test_every_expected_output_is_in_the_manifest_with_its_job_and_run(self):
        entries = {entry["path"]: entry for entry in provenance.read_manifest(self.project)["entries"]}
        for job, rate in RATES.items():
            entry = entries["results/sweep/lr-%s.json" % rate]
            self.assertEqual((entry["job"], entry["run_id"], entry["ticket"]), (job, "t1-a1", 1))
            self.assertEqual(entry["sha256"], provenance.sha256_of(self.project / entry["path"]))

    def test_the_analysis_ran_only_after_the_experiment_was_done(self):
        names = [(event["event"], event["ticket"]) for event in self.events()]
        self.assertLess(names.index(("ticket_done", 1)), names.index(("ticket_launched", 2)))
        launched = [event["payload"]["role"] for event in self.events("ticket_launched")]
        self.assertEqual(launched, ["experimenter", "analyst"])

    def test_the_analysis_finding_cites_a_manifested_result_and_the_unmanifested_one_is_refused(self):
        written = provenance.read_findings(self.project)
        self.assertEqual([(item["ticket"], item["provenance"]) for item in written], [(2, "results/sweep/lr-0.3.json#auroc")])
        self.assertEqual(len(self.events("finding")), 1)
        self.assertIn("A finding was refused", self.body(2))
        self.assertIn("results/sweep/lr-1.0.json", self.body(2))

    def test_the_view_replayed_from_the_journal_owes_nothing(self):
        view = replay.replay(self.events())
        self.assertEqual({job: (item["status"], item["exit_code"]) for job, item in view.jobs.items()},
                         {job: ("exited", 0) for job in RATES})
        self.assertIsNone(view.tickets[1].latest.owed)


class LadderTest(SweepCase):
    """Out-of-memory retries and the failures that end a sweep."""

    def test_a_host_oom_doubles_memory_first_then_steps_the_ladder_and_an_exhausted_ladder_fails_the_ticket(self):
        def script(jobs):
            jobs.script([host_oom()], job_id="t1-1")
            jobs.script([host_oom()], job_id="t1-1")
        self.run_sweep(script, waves=6)
        self.assertEqual(self.by_job("job_retried")["t1-1"], [{"job": "t1-1", "attempt": 2, "oom": "host", "overrides": {"ram_gb": 8}}])
        second = [spec for spec, _ in self.launched if spec.id == "t1-1"][1]
        self.assertEqual(second.ram_gb, 8)
        failed = self.by_job("job_failed")["t1-1"][0]
        self.assertEqual(failed["reason"], "the host OOM ladder is exhausted after 2 attempt(s)")
        self.assertEqual(self.status(1), "failed")
        reason = self.events("ticket_failed")[-1]["payload"]
        self.assertEqual((reason["ticket"], reason["next"]), (1, "resume"))
        self.assertEqual(sorted(self.by_job("job_cancelled")), ["t1-2", "t1-3"], "the rest of the sweep is cancelled")
        self.assertEqual({self.job(job)["status"] for job in ("t1-2", "t1-3")}, {"killed"})
        self.assertNotIn(2, [event["ticket"] for event in self.events("ticket_launched")])

    def test_the_doubling_is_capped_by_the_free_ram_over_the_reservation(self):
        def script(jobs):
            jobs.script([host_oom()], job_id="t1-1")
            jobs.script(["running"], job_id="t1-1")
        self.run_sweep(script, readings=lambda: machine.recorded(available_gb=70), waves=5)
        self.assertEqual(self.by_job("job_retried")["t1-1"][0]["overrides"], {"ram_gb": 6})

    def test_an_exhausted_gpu_ladder_fails_the_ticket_with_the_log_tail(self):
        def script(jobs):
            jobs.script(["exited"], outputs=output("t1-1"), job_id="t1-1")
            jobs.script(["exited"], outputs=output("t1-2"), job_id="t1-2")
            jobs.script([gpu_oom()], log=OOM_TAIL, job_id="t1-3")
            jobs.script([gpu_oom()], log=OOM_TAIL, job_id="t1-3")
        self.run_sweep(script)
        failed = self.by_job("job_failed")["t1-3"][0]
        self.assertEqual(failed["reason"], "the gpu OOM ladder is exhausted after 2 attempt(s)")
        self.assertIn("CUDA_ERROR_OUT_OF_MEMORY", failed["log_tail"])
        self.assertEqual(self.status(1), "failed")
        self.assertIn("CUDA_ERROR_OUT_OF_MEMORY", self.body(1), "the tail is the ticket's failure output")
        self.assertEqual(self.status(2), "open")

    def test_an_output_that_does_not_parse_fails_the_job_and_the_ticket(self):
        def script(jobs):
            jobs.script(["exited"], outputs={"results/sweep/lr-0.03.json": "{not json"}, job_id="t1-1")
        self.run_sweep(script, waves=5)
        self.assertEqual(self.by_job("job_finished")["t1-1"][0]["outputs_ok"], False)
        self.assertIn("does not parse", self.by_job("job_failed")["t1-1"][0]["reason"])
        self.assertEqual(self.status(1), "failed")
        self.assertEqual(provenance.read_manifest(self.project)["entries"], [])

    def test_a_job_that_fails_without_an_oom_fails_the_ticket_at_once(self):
        def script(jobs):
            jobs.script([JobState("failed", result="exit-code", exit_code=3, reason="exited 3", log_tail="Traceback: boom\n")], job_id="t1-1")
        self.run_sweep(script, waves=5)
        self.assertEqual(self.by_job("job_failed")["t1-1"][0]["reason"], "exited 3")
        self.assertIsNone(self.by_job("job_retried").get("t1-1"))
        self.assertEqual(self.status(1), "failed")


class FailedAttemptTest(SweepCase):
    """An experimenter whose attempt fails before its jobs launch: the jobs it wrote never run."""

    def test_the_jobs_of_a_failed_attempt_are_cancelled_before_they_launch(self):
        script = json.loads((SWEEP / "fake-worker.json").read_text(encoding="utf-8"))
        script[0]["patch"]["files"]["sweep/stray.txt"] = "left behind\n"
        script[0]["patch"]["commit"] = False
        path = self.temp / "fake-worker.json"
        path.write_text(json.dumps(script), encoding="utf-8")
        with worker.use_fake() as fake, resources.use_fake_jobs() as jobs:
            fake.load(path)
            self.drive(machine.recorded, 5)
            self.launched = list(jobs.launched)
        self.assertEqual(self.status(1), "failed")
        self.assertIn("uncommitted", self.events("ticket_failed")[-1]["payload"]["reason"])
        self.assertEqual(sorted(self.by_job("job_cancelled")), sorted(RATES))
        self.assertEqual({self.job(job)["status"] for job in RATES}, {"killed"})
        self.assertEqual(self.launched, [])


class TickPolledTest(SweepCase):
    """The tick polls jobs too and records what it read; the conductor concludes them once, and fails the ticket once."""

    def test_two_ended_jobs_the_tick_recorded_fail_the_ticket_once_and_nothing_is_retried(self):
        path = tickets.tickets_dir(self.project) / "01-sweep-the-learning-rate.md"
        path.write_text(path.read_text(encoding="utf-8").replace("  gpu: 1\n", "  gpu: 0\n"), encoding="utf-8")
        from wayline import tick
        with worker.use_fake() as fake, resources.use_fake_jobs() as jobs:
            fake.load(SWEEP / "fake-worker.json")
            jobs.script([JobState("failed", result="timeout", exit_code=15, reason="wallclock")], job_id="t1-1")
            jobs.script([gpu_oom()], log=OOM_TAIL, job_id="t1-2")
            jobs.script(["running"], job_id="t1-3")
            self.drive(machine.recorded, 2)
            self.assertEqual(sorted(self.by_job("job_launched")), sorted(RATES), "no GPU asked, so all three run at once")
            polled = {entry["job"]: entry["now"] for entry in tick.poll_jobs(self.project)}
            self.assertEqual(polled, {"t1-1": "failed", "t1-2": "oom_gpu", "t1-3": "running"})
            self.drive(machine.recorded, 2)
        self.assertEqual(len(self.events("ticket_failed")), 1)
        self.assertEqual(self.by_job("job_failed")["t1-1"][0]["reason"], "wallclock")
        self.assertEqual(self.by_job("job_failed")["t1-2"][0]["reason"], "a gpu OOM")
        self.assertNotIn("job_retried", self.names())
        self.assertEqual(list(self.by_job("job_cancelled")), ["t1-3"])
        self.assertEqual(self.status(1), "failed")


class PausedTest(SweepCase):
    """M2 criterion 9: with the window closed, a wave still launches and polls jobs and runs machine checks."""

    def test_a_paused_run_finishes_the_sweep_and_launches_no_model_work(self):
        self.run_sweep(limit=3600)
        self.assertEqual(len(self.events("paused")), 1, "the experimenter's stream carried the limit")
        self.assertEqual(self.status(1), "done")
        self.assertEqual(len(self.by_job("job_launched")["t1-3"]), 2)
        self.assertIn("acceptance", self.names())
        self.assertEqual([event["ticket"] for event in self.events("ticket_launched")], [1], "the analyst waits for the reset")
        self.assertEqual(self.status(2), "open")
        self.assertNotIn("run_ended", self.names())


class ReservationTest(SweepCase):
    """M2 criterion 8, through the conductor: a job whose core request exceeds the free cores waits."""

    def test_a_job_that_cannot_get_its_cores_waits_and_is_journaled_once(self):
        loads = iter([6.5, 7.25, 6.0, 7.0, 6.75, 6.5])
        self.run_sweep(lambda jobs: None, readings=lambda: machine.recorded(nproc=16, loadavg1=next(loads)), waves=6)
        waiting = self.by_job("job_waiting")
        self.assertEqual(waiting["t1-1"], [{"job": "t1-1", "ticket": 1,
                                            "reason": "needs 4 core(s) and the load is 6.5 of the 8 cores outside the reservation"}],
                         "a load that moves is the same wait, journaled once")
        self.assertEqual(self.launched, [])
        self.assertEqual(self.status(1), "running")

    def test_a_request_larger_than_the_machine_fails_the_ticket_at_once(self):
        self.run_sweep(lambda jobs: None, readings=lambda: machine.recorded(nproc=10), waves=5)
        self.assertEqual(self.by_job("job_failed")["t1-1"][0]["reason"],
                         "it asks for 4 core(s) and this machine has 2 outside the reservation")
        self.assertEqual(self.status(1), "failed")
        self.assertEqual(sorted(self.by_job("job_cancelled")), ["t1-2", "t1-3"])
        self.assertNotIn("job_waiting", self.names())
        self.assertEqual(self.launched, [])


class RestartTest(SweepCase):
    """A conductor that stops mid-sweep leaves the jobs to the next one, which polls and closes them."""

    def test_a_new_conductor_carries_on_polling_the_jobs_the_last_one_launched(self):
        with worker.use_fake() as fake, resources.use_fake_jobs() as jobs:
            fake.load(SWEEP / "fake-worker.json")
            self.script_jobs(jobs)
            self.drive(machine.recorded, 3)
            self.assertEqual(self.status(1), "running")
            results = self.drive(machine.recorded, 20, conductor=Conductor(self.project, out=io.StringIO()))
        self.assertTrue(results[-1].ended)
        self.assertEqual((self.status(1), self.status(2)), ("done", "done"))
        self.assertEqual({job: len(items) for job, items in self.by_job("job_launched").items()}, {"t1-1": 1, "t1-2": 1, "t1-3": 2})
