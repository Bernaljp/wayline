"""The free-slot rule over pending jobs, and the footprint ladder (Implementation Decisions 6; ticket 19).

Everything here is a pure function of job records and a recorded machine reading (`tests.machine`),
so nothing reads `nvidia-smi` or `/proc`.
"""

import shutil
import unittest

from tests import machine
from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import project, resources
from wayline.resources import (
    JobError, Reservation, apply_overrides, effective_overrides, job_request, ladder_position, next_retry, parse_step,
    place_jobs,
)


def pending(job_id, gpu_uuids=(), cores=(), ram_gb=0):
    return {"id": job_id, "ticket": 1, "status": "pending",
            "devices": {"gpu_uuids": list(gpu_uuids), "gpu_indices": [], "cores": list(cores), "ram_gb": ram_gb}}


def running(job_id, gpu_indices=(), cores=(), ram_gb=0):
    return {"id": job_id, "ticket": 1, "status": "running",
            "devices": {"gpu_uuids": [], "gpu_indices": list(gpu_indices), "cores": list(cores), "ram_gb": ram_gb}}


def place(jobs, requests, readings=None, running_jobs=()):
    return place_jobs(jobs, list(running_jobs), readings or machine.recorded(), requests)


GPU_JOB = {"gpu": 1, "cpu": 4, "ram_gb": 4}
CPU_JOB = {"gpu": 0, "cpu": 8, "ram_gb": 2}


class PlaceJobsTest(unittest.TestCase):

    def test_one_gpu_job_at_a_time_and_cpu_jobs_fill_the_remaining_cores(self):
        jobs = [pending("g1"), pending("g2"), pending("c1"), pending("c2")]
        placed, waiting = place(jobs, {"g1": GPU_JOB, "g2": GPU_JOB, "c1": CPU_JOB, "c2": CPU_JOB})
        self.assertEqual([item.job for item in placed], ["g1", "c1", "c2"])
        self.assertEqual(placed[0].gpu_indices, (0,))
        self.assertEqual((placed[1].gpu_indices, placed[2].gpu_indices), ((), ()))
        self.assertEqual(waiting, {"g2": "needs 1 GPU(s) and 0 of 1 is free"})
        cores = [set(item.cores) for item in placed]
        self.assertEqual(cores, [set(range(8, 12)), set(range(12, 20)), set(range(20, 28))], "contiguous, and never overlapping")

    def test_no_core_ever_comes_from_the_reservation_or_a_running_job(self):
        placed, _ = place([pending("a")], {"a": {"gpu": 0, "cpu": 4, "ram_gb": 0}},
                          readings=machine.recorded(nproc=16), running_jobs=[running("r", cores=range(8, 12))])
        self.assertEqual(placed[0].cores, (12, 13, 14, 15))
        self.assertFalse(set(placed[0].cores) & set(range(8)))

    def test_a_request_beyond_the_free_cores_waits(self):
        placed, waiting = place([pending("a")], {"a": {"gpu": 0, "cpu": 12, "ram_gb": 0}},
                                readings=machine.recorded(nproc=24, loadavg1=0), running_jobs=[running("r", cores=range(8, 16))])
        self.assertEqual(placed, [])
        self.assertEqual(waiting, {"a": "needs 12 core(s) and 8 are free outside the reservation"})

    def test_the_load_counts_against_the_unreserved_cores(self):
        _, waiting = place([pending("a")], {"a": {"gpu": 0, "cpu": 4, "ram_gb": 0}}, readings=machine.recorded(nproc=16, loadavg1=6))
        self.assertEqual(waiting, {"a": "needs 4 core(s) and the load is 6 of the 8 cores outside the reservation"})

    def test_named_cores_are_honored_only_when_every_one_is_free_and_unreserved(self):
        placed, waiting = place([pending("a", cores=[6, 7, 8, 9]), pending("b", cores=[10, 11])],
                                {"a": job_request(pending("a", cores=[6, 7, 8, 9])), "b": job_request(pending("b", cores=[10, 11]))})
        self.assertEqual([item.job for item in placed], ["b"])
        self.assertEqual(placed[0].cores, (10, 11))
        self.assertIn("not all of them are free outside the reservation", waiting["a"])

    def test_ram_is_free_only_over_the_reservation_and_the_running_jobs(self):
        _, waiting = place([pending("a")], {"a": {"gpu": 0, "cpu": 1, "ram_gb": 10}},
                           readings=machine.recorded(available_gb=80), running_jobs=[running("r", cores=[8], ram_gb=8)])
        self.assertEqual(waiting, {"a": "needs 10.0GB of RAM and 8.0GB is free over the reservation and the running jobs"})
        placed, _ = place([pending("a")], {"a": {"gpu": 0, "cpu": 1, "ram_gb": 8}},
                          readings=machine.recorded(available_gb=80), running_jobs=[running("r", cores=[8], ram_gb=8)])
        self.assertEqual(len(placed), 1)

    def test_a_waiting_job_releases_the_cores_it_would_have_taken(self):
        placed, waiting = place([pending("big"), pending("small")],
                                {"big": {"gpu": 0, "cpu": 4, "ram_gb": 500}, "small": {"gpu": 0, "cpu": 4, "ram_gb": 1}})
        self.assertIn("big", waiting)
        self.assertEqual(placed[0].cores, (8, 9, 10, 11))

    def test_a_busy_or_reserved_or_held_gpu_is_not_free(self):
        requests = {"a": GPU_JOB}
        self.assertIn("a", place([pending("a")], requests, readings=machine.recorded(utilization=55))[1])
        self.assertIn("a", place([pending("a")], requests, running_jobs=[running("r", gpu_indices=[0], cores=[8])])[1])
        reserved = machine.recorded()
        reserved["reservation"] = Reservation(gpu_indices=frozenset([0]), cores=frozenset(range(8)))
        self.assertIn("a", place([pending("a")], requests, readings=reserved)[1])
        owner = machine.recorded()
        owner["reservation"] = Reservation(cores=frozenset(range(8)), extra_gpu_mib=24000)
        self.assertIn("a", place([pending("a")], requests, readings=owner)[1], "the owner's processes' GPU memory counts as reserved")

    def test_a_gpu_request_on_a_machine_with_none_waits_and_says_so(self):
        _, waiting = place([pending("a")], {"a": GPU_JOB}, readings=machine.recorded(gpus=False))
        self.assertEqual(waiting, {"a": "needs 1 GPU(s) and this machine reports none"})

    def test_a_job_naming_its_gpu_gets_that_one_or_waits(self):
        placed, _ = place([pending("a", gpu_uuids=[machine.GPU_UUID])], {"a": GPU_JOB})
        self.assertEqual(placed[0].gpu_uuids, (machine.GPU_UUID,))
        _, waiting = place([pending("a", gpu_uuids=["GPU-other"])], {"a": GPU_JOB})
        self.assertEqual(waiting, {"a": "GPU GPU-other is not free"})

    def test_the_request_is_the_job_files_where_it_names_devices_and_the_tickets_otherwise(self):
        resources_ = {"gpu": 1, "cpu": 6, "ram_gb": 16}
        self.assertEqual(job_request(pending("a"), resources_), {"gpu": 1, "cpu": 6, "ram_gb": 16.0})
        self.assertEqual(job_request(pending("a", cores=[9, 10], ram_gb=2), resources_), {"gpu": 1, "cpu": 2, "ram_gb": 2.0})
        self.assertEqual(job_request(pending("a"), None), {"gpu": 0, "cpu": 1, "ram_gb": 0.0})


class OverridesTest(unittest.TestCase):

    def test_an_argument_is_replaced_in_either_spelling_and_appended_when_absent(self):
        command = ["/usr/bin/python3", "train.py", "--batch-size", "64", "--lr=0.1"]
        argv, env = apply_overrides(command, {"A": "1"}, {"--batch-size": 16, "--lr": 0.05, "--seed": 3, "--fp16": True,
                                                         "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True", "ram_gb": 8})
        self.assertEqual(argv, ["/usr/bin/python3", "train.py", "--batch-size", "16", "--lr=0.05", "--seed", "3", "--fp16"])
        self.assertEqual(env, {"A": "1", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
        self.assertEqual(command[3], "64", "the declared command is left alone")

    def test_a_ticket_file_spells_a_step_as_key_value_text(self):
        self.assertEqual(parse_step("--batch-size=16 --fp16=true NAME=a=b"), {"--batch-size": 16, "--fp16": True, "NAME": "a=b"})
        self.assertEqual(parse_step({"--batch-size": 8}), {"--batch-size": 8})
        with self.assertRaises(JobError):
            parse_step("--batch-size 16")


def with_attempts(*attempts, ram_gb=4, host=(), gpu=()):
    return {"devices": {"ram_gb": ram_gb}, "retry": {"host_oom": list(host), "gpu_oom": list(gpu)},
            "attempts": [{"oom": oom, "overrides": overrides} for oom, overrides in attempts]}


class LadderTest(unittest.TestCase):
    HOST = [{"--workers": 2}, {"--workers": 1}]
    GPU = [{"--batch-size": 32}, {"--batch-size": 16}]

    def test_a_host_oom_doubles_once_up_to_the_cap_then_steps_its_ladder(self):
        record = with_attempts(("host", {}), host=self.HOST)
        self.assertEqual(next_retry(record, "host", cap_gb=100), {"ram_gb": 8})
        self.assertEqual(next_retry(record, "host", cap_gb=6), {"ram_gb": 6})
        self.assertEqual(next_retry(record, "host", cap_gb=3), {"--workers": 2}, "a doubling that would not raise it is skipped")
        self.assertEqual(next_retry(record, "host", cap_gb=100, double_first=False), {"--workers": 2})
        doubled = with_attempts(("host", {}), ("host", {"ram_gb": 8}), ram_gb=8, host=self.HOST)
        self.assertEqual(next_retry(doubled, "host", cap_gb=100), {"--workers": 2})
        stepped = with_attempts(("host", {}), ("host", {"ram_gb": 8}), ("host", {"--workers": 2}), ("host", {"--workers": 1}), host=self.HOST)
        self.assertIsNone(next_retry(stepped, "host", cap_gb=100))

    def test_a_gpu_oom_steps_its_own_ladder_and_the_next_launch_carries_both(self):
        record = with_attempts(("gpu", {}), ("host", {"--batch-size": 32}), ("gpu", {"ram_gb": 8}), gpu=self.GPU, host=self.HOST)
        self.assertEqual(ladder_position(record), {"host": 0, "gpu": 1, "doubled": True})
        self.assertEqual(next_retry(record, "gpu", cap_gb=0), {"--batch-size": 16})
        self.assertEqual(effective_overrides(record), {"--batch-size": 32})
        self.assertIsNone(next_retry(with_attempts(("gpu", {})), "gpu", cap_gb=0), "no ladder, no retry")


class JobAddDefaultsTest(ProjectTestCase):
    """An experiment ticket's `resources` and `retry` reach the job files `wayline job add` writes."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "sweep"
        shutil.copytree(FIXTURES_DIR / "projects" / "sweep", self.project)
        project.init_project(self.project)

    def test_the_ticket_fills_what_the_spec_leaves_out(self):
        record = resources.add_jobs(self.project, {"command": ["/bin/true"]}, ticket=1, backend="fake")[0]
        self.assertEqual((record["devices"]["ram_gb"], record["wallclock_minutes"]), (4, 10))
        self.assertEqual(record["retry"], {"host_oom": [], "gpu_oom": [{"--batch-size": 256}]})
        self.assertEqual((record["devices"]["cores"], record["devices"]["gpu_uuids"]), ([], []), "the conductor places the job")

    def test_the_spec_wins_where_it_speaks(self):
        record = resources.add_jobs(self.project, {"command": ["/bin/true"], "devices": {"ram_gb": 1}, "wallclock_minutes": 2,
                                                   "retry": {"gpu_oom": []}}, ticket=1, backend="fake")[0]
        self.assertEqual((record["devices"]["ram_gb"], record["wallclock_minutes"], record["retry"]["gpu_oom"]), (1, 2, []))

    def test_a_ticket_without_resources_leaves_the_defaults(self):
        record = resources.add_jobs(self.project, {"command": ["/bin/true"]}, ticket=2, backend="fake")[0]
        self.assertEqual((record["devices"]["ram_gb"], record["wallclock_minutes"]), (0.0, resources.DEFAULT_WALLCLOCK_MINUTES))


if __name__ == "__main__":
    unittest.main()
