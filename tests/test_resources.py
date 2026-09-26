"""Resource detection and slots (Implementation Decisions 6, 14; research-notes 05 A8).

Recorded readings from research-notes 05 R14 seed the detection tests; the boundary tests are
synthetic, one per rule in the free-slot definition.
"""

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tests import lift_backends
from wayline import resources as r

# research-notes 05 R14, verbatim.
R14_GPU_CSV = "0, GPU-0095fb8d-af69-ff0f-6b06-da1a9a89fc7f, 24576, 86, 24170, 0, 0\n"
R14_LOADAVG = "1.10 0.47 0.22 2/2449 2086675\n"
R14_MEMINFO = "MemTotal:       1100000000 kB\nMemAvailable:   1043167188 kB\n"  # 1043167188 * 1024 = 1068203200512
R14_DISK_AVAIL = "        Avail\n10765606739968\n"


def _done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class ReadGpusTest(unittest.TestCase):
    def setUp(self):
        lift_backends(self)  # nvidia-smi is replaced by a recorded answer here

    def test_parses_the_recorded_reading(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(R14_GPU_CSV)):
            gpus = r.read_gpus()
        self.assertEqual(gpus, [{
            "index": 0, "uuid": "GPU-0095fb8d-af69-ff0f-6b06-da1a9a89fc7f",
            "memory_total_mib": 24576, "memory_used_mib": 86, "memory_free_mib": 24170,
            "utilization_gpu": 0, "utilization_memory": 0,
        }])

    def test_degrades_to_cpu_only_when_nvidia_smi_is_absent(self):
        with mock.patch("wayline.resources.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(r.read_gpus(), [])

    def test_a_nonzero_exit_is_also_no_gpus(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("", returncode=1)):
            self.assertEqual(r.read_gpus(), [])

    def test_multiple_gpus_parse_in_order(self):
        csv = "0, GPU-aaa, 100, 0, 100, 0, 0\n1, GPU-bbb, 200, 50, 150, 10, 5\n"
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(csv)):
            gpus = r.read_gpus()
        self.assertEqual([gpu["index"] for gpu in gpus], [0, 1])
        self.assertEqual(gpus[1]["memory_free_mib"], 150)


class ReadGpuProcessesTest(unittest.TestCase):
    def setUp(self):
        lift_backends(self)  # nvidia-smi is replaced by a recorded answer here

    def test_no_compute_processes_is_an_empty_list(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("")):
            self.assertEqual(r.read_gpu_processes(), [])

    def test_parses_pid_and_used_memory(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("1234, 4096\n5678, 2048\n")):
            processes = r.read_gpu_processes()
        self.assertEqual(processes, [{"pid": 1234, "used_memory_mib": 4096}, {"pid": 5678, "used_memory_mib": 2048}])

    def test_absent_nvidia_smi_is_an_empty_list(self):
        with mock.patch("wayline.resources.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(r.read_gpu_processes(), [])


class SampleGpuUtilizationTest(unittest.TestCase):
    def test_takes_n_samples_and_sleeps_between_them(self):
        readings = [[{"uuid": "g0", "utilization_gpu": 5}], [{"uuid": "g0", "utilization_gpu": 8}]]
        calls = iter(readings)
        sleeps = []
        samples = r.sample_gpu_utilization(n=2, interval_s=1.5, sleep=sleeps.append, read=lambda: next(calls))
        self.assertEqual(samples, readings)
        self.assertEqual(sleeps, [1.5])

    def test_stops_early_and_does_not_sleep_when_there_is_no_gpu(self):
        sleeps = []
        samples = r.sample_gpu_utilization(n=3, sleep=sleeps.append, read=lambda: [])
        self.assertEqual(samples, [[]])
        self.assertEqual(sleeps, [])

    def test_a_single_sample_never_sleeps(self):
        sleeps = []
        r.sample_gpu_utilization(n=1, sleep=sleeps.append, read=lambda: [{"uuid": "g0", "utilization_gpu": 1}])
        self.assertEqual(sleeps, [])


class ProcReadingsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="wayline-resources-test-"))
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_loadavg1_reads_the_first_field(self):
        path = self.tmp / "loadavg"
        path.write_text(R14_LOADAVG, encoding="utf-8")
        self.assertEqual(r.read_loadavg1(path), 1.10)

    def test_cpu_pressure_reads_the_some_avg10_field(self):
        path = self.tmp / "pressure_cpu"
        path.write_text("some avg10=3.25 avg60=1.00 avg300=0.50 total=1\nfull avg10=0.00\n", encoding="utf-8")
        self.assertEqual(r.read_cpu_pressure(path), 3.25)

    def test_cpu_pressure_is_none_when_the_file_is_absent(self):
        self.assertIsNone(r.read_cpu_pressure(self.tmp / "missing"))

    def test_mem_available_converts_kib_to_bytes(self):
        path = self.tmp / "meminfo"
        path.write_text(R14_MEMINFO, encoding="utf-8")
        self.assertEqual(r.read_mem_available_bytes(path), 1068203200512)

    def test_mem_available_missing_raises(self):
        path = self.tmp / "meminfo"
        path.write_text("MemTotal: 1 kB\n", encoding="utf-8")
        with self.assertRaises(r.ResourceError):
            r.read_mem_available_bytes(path)


class DiskAvailTest(unittest.TestCase):
    def test_parses_the_last_line_of_df_output(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(R14_DISK_AVAIL)):
            self.assertEqual(r.read_disk_avail_bytes("/home"), 10765606739968)

    def test_a_failing_df_raises(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("", returncode=1, stderr="no such file")):
            with self.assertRaises(r.ResourceError):
                r.read_disk_avail_bytes("/nope")


class ProcessReservationTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.proc = Path(tempfile.mkdtemp(prefix="wayline-proc-test-"))
        import shutil
        self.addCleanup(shutil.rmtree, self.proc, ignore_errors=True)

    def _make_process(self, pid, comm):
        directory = self.proc / str(pid)
        directory.mkdir()
        (directory / "comm").write_text(comm + "\n", encoding="utf-8")

    def test_pids_by_name_matches_comm(self):
        self._make_process(111, "trader")
        self._make_process(222, "other")
        (self.proc / "not-a-pid").mkdir()
        matches = r.pids_by_name(["trader"], proc_dir=self.proc)
        self.assertEqual(matches, {111: "trader"})

    def test_pids_by_name_with_no_names_is_empty(self):
        self._make_process(111, "trader")
        self.assertEqual(r.pids_by_name([], proc_dir=self.proc), {})

    def test_process_cores_is_empty_for_a_dead_pid(self):
        self.assertEqual(r.process_cores(2 ** 30), set())

    def test_process_reservation_sums_gpu_memory_and_unions_cores(self):
        self._make_process(111, "trader")
        self._make_process(222, "trader")
        gpu_processes = [{"pid": 111, "used_memory_mib": 500}, {"pid": 222, "used_memory_mib": 300}, {"pid": 333, "used_memory_mib": 1000}]
        with mock.patch("wayline.resources.process_cores", side_effect=lambda pid: {0, 1} if pid == 111 else {2}):
            reserved_mib, reserved_cores = r.process_reservation(["trader"], gpu_processes=gpu_processes, proc_dir=self.proc)
        self.assertEqual(reserved_mib, 800)
        self.assertEqual(reserved_cores, frozenset({0, 1, 2}))

    def test_no_listed_processes_reserves_nothing(self):
        reserved_mib, reserved_cores = r.process_reservation([], gpu_processes=[{"pid": 1, "used_memory_mib": 99}], proc_dir=self.proc)
        self.assertEqual((reserved_mib, reserved_cores), (0, frozenset()))


class ReservationFromHarnessTest(unittest.TestCase):
    def test_the_default_reservation_matches_policy_json(self):
        harness = {"reservations": {"gpu": [], "cores": 8, "ram_gb": 64, "processes": []}}
        reservation = r.reservation_from_harness(harness, gpu_processes=[])
        self.assertEqual(reservation.gpu_indices, frozenset())
        self.assertEqual(reservation.cores, frozenset(range(8)))
        self.assertEqual(reservation.ram_bytes, 64 * (1024 ** 3))
        self.assertEqual(reservation.extra_gpu_mib, 0)

    def test_a_reserved_gpu_index_is_carried(self):
        harness = {"reservations": {"gpu": [1], "cores": 0, "ram_gb": 0, "processes": []}}
        reservation = r.reservation_from_harness(harness, gpu_processes=[])
        self.assertEqual(reservation.gpu_indices, frozenset({1}))

    def test_missing_reservations_block_defaults_to_nothing_reserved(self):
        reservation = r.reservation_from_harness({}, gpu_processes=[])
        self.assertEqual(reservation.cores, frozenset())
        self.assertEqual(reservation.ram_bytes, 0)


class GpuFreeRuleTest(unittest.TestCase):
    GPU = {"index": 0, "memory_free_mib": 1000, "memory_total_mib": 2000}

    def test_free_when_memory_covers_need_and_two_low_samples(self):
        self.assertTrue(r.gpu_free(self.GPU, [5, 10], held=False, need_mib=500, reserve_mib=0, util_threshold=20))

    def test_not_free_when_held(self):
        self.assertFalse(r.gpu_free(self.GPU, [5, 10], held=True, need_mib=500, reserve_mib=0, util_threshold=20))

    def test_not_free_when_memory_is_short_by_one_mib(self):
        self.assertFalse(r.gpu_free(self.GPU, [5, 10], held=False, need_mib=1000, reserve_mib=1, util_threshold=20))

    def test_free_at_the_exact_memory_boundary(self):
        self.assertTrue(r.gpu_free(self.GPU, [5, 10], held=False, need_mib=999, reserve_mib=1, util_threshold=20))

    def test_not_free_with_only_one_sample(self):
        self.assertFalse(r.gpu_free(self.GPU, [5], held=False, need_mib=0, reserve_mib=0, util_threshold=20))

    def test_not_free_with_no_samples(self):
        self.assertFalse(r.gpu_free(self.GPU, [], held=False, need_mib=0, reserve_mib=0, util_threshold=20))

    def test_not_free_when_the_latest_sample_is_at_the_threshold(self):
        self.assertFalse(r.gpu_free(self.GPU, [5, 20], held=False, need_mib=0, reserve_mib=0, util_threshold=20))

    def test_free_when_the_latest_sample_is_just_under_the_threshold(self):
        self.assertTrue(r.gpu_free(self.GPU, [5, 19], held=False, need_mib=0, reserve_mib=0, util_threshold=20))

    def test_only_the_last_two_samples_of_a_longer_history_matter(self):
        self.assertTrue(r.gpu_free(self.GPU, [90, 5, 10], held=False, need_mib=0, reserve_mib=0, util_threshold=20))


class CpuSlotFreeTest(unittest.TestCase):
    def test_free_when_load_and_the_allocator_agree(self):
        allocator = r.CoreAllocator(range(8, 128))
        self.assertTrue(r.cpu_slot_free(loadavg1=1.0, cores_needed=4, nproc=128, reserved_cores_count=8, allocator=allocator))

    def test_not_free_when_load_plus_the_request_exceeds_the_unreserved_cores(self):
        allocator = r.CoreAllocator(range(8, 128))
        self.assertFalse(r.cpu_slot_free(loadavg1=119.0, cores_needed=4, nproc=128, reserved_cores_count=8, allocator=allocator))

    def test_free_at_the_exact_load_boundary(self):
        allocator = r.CoreAllocator(range(8, 128))
        self.assertTrue(r.cpu_slot_free(loadavg1=116.0, cores_needed=4, nproc=128, reserved_cores_count=8, allocator=allocator))

    def test_not_free_when_the_allocator_pool_is_smaller_than_the_request_even_with_load_headroom(self):
        allocator = r.CoreAllocator([8, 9])
        self.assertFalse(r.cpu_slot_free(loadavg1=0.0, cores_needed=4, nproc=128, reserved_cores_count=8, allocator=allocator))


class RamFreeTest(unittest.TestCase):
    def test_free_when_the_remainder_covers_the_need(self):
        self.assertTrue(r.ram_free(mem_available_bytes=100, reserved_bytes=20, running_ram_bytes=30, need_bytes=50))

    def test_not_free_by_one_byte(self):
        self.assertFalse(r.ram_free(mem_available_bytes=100, reserved_bytes=20, running_ram_bytes=30, need_bytes=51))

    def test_free_at_the_exact_boundary(self):
        self.assertTrue(r.ram_free(mem_available_bytes=100, reserved_bytes=20, running_ram_bytes=30, need_bytes=50))


class CorePoolTest(unittest.TestCase):
    def test_excludes_reserved_and_running_cores(self):
        self.assertEqual(r.core_pool(nproc=8, reserved_cores=[0, 1], running_cores=[2, 3]), [4, 5, 6, 7])

    def test_an_empty_pool_when_everything_is_taken(self):
        self.assertEqual(r.core_pool(nproc=4, reserved_cores=range(4), running_cores=[]), [])


class CoreAllocatorTest(unittest.TestCase):
    def test_allocates_a_contiguous_range_first(self):
        allocator = r.CoreAllocator(range(8, 16))
        cores = allocator.allocate("job-1", 4)
        self.assertEqual(cores, (8, 9, 10, 11))
        self.assertEqual(allocator.free, [12, 13, 14, 15])

    def test_falls_back_to_a_fragmented_listed_range(self):
        allocator = r.CoreAllocator([8, 10, 12, 14])
        cores = allocator.allocate("job-1", 2)
        # No two of these cores are adjacent, so the allocator must fall back to a listed set.
        self.assertEqual(cores, (8, 10))

    def test_release_returns_cores_to_the_pool(self):
        allocator = r.CoreAllocator(range(8, 12))
        allocator.allocate("job-1", 4)
        self.assertEqual(allocator.free, [])
        released = allocator.release("job-1")
        self.assertEqual(released, (8, 9, 10, 11))
        self.assertEqual(allocator.free, [8, 9, 10, 11])

    def test_releasing_an_unknown_job_is_a_no_op(self):
        allocator = r.CoreAllocator(range(8, 12))
        self.assertIsNone(allocator.release("no-such-job"))

    def test_allocate_returns_none_when_the_pool_cannot_supply_the_request(self):
        allocator = r.CoreAllocator([8, 9])
        self.assertIsNone(allocator.allocate("job-1", 4))
        self.assertEqual(allocator.free, [8, 9], "a failed allocation must not touch the pool")

    def test_double_allocating_the_same_job_raises(self):
        allocator = r.CoreAllocator(range(8, 16))
        allocator.allocate("job-1", 2)
        with self.assertRaises(r.ResourceError):
            allocator.allocate("job-1", 2)

    def test_never_hands_out_the_reserved_cores(self):
        pool = r.core_pool(nproc=8, reserved_cores=range(4), running_cores=[])
        allocator = r.CoreAllocator(pool)
        cores = allocator.allocate("job-1", 4)
        self.assertEqual(set(cores) & set(range(4)), set())


class SlotViewsTest(unittest.TestCase):
    RESERVATION = r.Reservation(gpu_indices=frozenset(), cores=frozenset(range(8)), ram_bytes=64 * (1024 ** 3), extra_gpu_mib=0)

    def _job(self, gpu_indices=(), cores=(), ram_gb=0):
        return {"devices": {"gpu_indices": list(gpu_indices), "gpu_uuids": [], "cores": list(cores), "ram_gb": ram_gb}}

    def test_gpu_slots_view_is_empty_with_no_gpus(self):
        self.assertEqual(r.gpu_slots_view([[]], [], self.RESERVATION), [])

    def test_a_gpu_a_wayline_job_holds_is_not_free(self):
        samples = [[{"index": 0, "uuid": "g0", "utilization_gpu": 0, "memory_free_mib": 1000, "memory_total_mib": 2000, "memory_used_mib": 0, "utilization_memory": 0}]] * 2
        jobs = [self._job(gpu_indices=[0])]
        slots = r.gpu_slots_view(samples, jobs, self.RESERVATION)
        self.assertEqual(len(slots), 1)
        self.assertTrue(slots[0]["held"])
        self.assertEqual(slots[0]["held_by"], "job")
        self.assertFalse(slots[0]["free"])

    def test_a_gpu_the_reservation_withholds_is_held_but_not_by_a_job(self):
        samples = [[{"index": 1, "uuid": "g1", "utilization_gpu": 0, "memory_free_mib": 1000, "memory_total_mib": 2000, "memory_used_mib": 0, "utilization_memory": 0}]] * 2
        reservation = r.Reservation(gpu_indices=frozenset({1}), cores=frozenset(), ram_bytes=0, extra_gpu_mib=0)
        slots = r.gpu_slots_view(samples, [], reservation)
        self.assertEqual(slots[0]["held_by"], "reservation")

    def test_an_unheld_low_utilization_gpu_with_enough_memory_is_free(self):
        samples = [[{"index": 0, "uuid": "g0", "utilization_gpu": 3, "memory_free_mib": 1000, "memory_total_mib": 2000, "memory_used_mib": 0, "utilization_memory": 0}]] * 2
        slots = r.gpu_slots_view(samples, [], self.RESERVATION, util_threshold=20)
        self.assertTrue(slots[0]["free"])

    def test_cpu_slot_view_reports_cores_in_use_and_free(self):
        jobs = [self._job(cores=[8, 9])]
        view = r.cpu_slot_view(loadavg1=0.5, nproc=16, reservation=self.RESERVATION, jobs=jobs)
        self.assertEqual(view["cores_in_use"], [8, 9])
        self.assertEqual(view["reserved_cores"], list(range(8)))
        self.assertEqual(view["free_cores"], [10, 11, 12, 13, 14, 15])
        self.assertTrue(view["free"])

    def test_ram_slot_view_sums_running_jobs(self):
        jobs = [self._job(ram_gb=10), self._job(ram_gb=5)]
        view = r.ram_slot_view(mem_available_bytes=200 * (1024 ** 3), reservation=self.RESERVATION, jobs=jobs)
        self.assertEqual(view["committed_bytes"], 15 * (1024 ** 3))
        self.assertEqual(view["free_bytes"], (200 - 64 - 15) * (1024 ** 3))


class SnapshotTest(unittest.TestCase):
    def test_snapshot_combines_every_reading_into_one_view(self):
        harness = {"reservations": {"gpu": [], "cores": 8, "ram_gb": 64, "processes": []}}
        with mock.patch("wayline.resources.read_gpu_processes", return_value=[]), \
             mock.patch("wayline.resources.sample_gpu_utilization", return_value=[[]]), \
             mock.patch("wayline.resources.read_loadavg1", return_value=1.1), \
             mock.patch("wayline.resources.read_cpu_pressure", return_value=0.0), \
             mock.patch("wayline.resources.read_mem_available_bytes", return_value=1068203200512), \
             mock.patch("wayline.resources.read_disk_avail_bytes", return_value=10765606739968), \
             mock.patch("os.cpu_count", return_value=128):
            view = r.snapshot(harness, jobs=[])
        self.assertEqual(view["gpus"], [])
        self.assertEqual(view["cpu"]["loadavg1"], 1.1)
        self.assertEqual(view["cpu"]["pressure_avg10"], 0.0)
        self.assertEqual(view["cpu"]["nproc"], 128)
        self.assertEqual(view["ram"]["mem_available_bytes"], 1068203200512)
        self.assertEqual(view["disk_avail_bytes"], 10765606739968)
        self.assertEqual(view["reservation"]["cores"], list(range(8)))

    def test_a_missing_meminfo_field_raises_resource_error(self):
        harness = {"reservations": {}}
        with mock.patch("wayline.resources.read_gpu_processes", return_value=[]), \
             mock.patch("wayline.resources.sample_gpu_utilization", return_value=[[]]), \
             mock.patch("wayline.resources.read_loadavg1", return_value=0.0), \
             mock.patch("wayline.resources.read_cpu_pressure", return_value=None), \
             mock.patch("wayline.resources.read_mem_available_bytes", side_effect=r.ResourceError("boom")):
            with self.assertRaises(r.ResourceError):
                r.snapshot(harness, jobs=[])


class RenderResourcesTest(unittest.TestCase):
    def test_renders_a_reservation_and_a_gpu_line_with_no_trailing_whitespace(self):
        harness = {"reservations": {"gpu": [], "cores": 8, "ram_gb": 64, "processes": ["trader"]}}
        with mock.patch("wayline.resources.read_gpu_processes", return_value=[]), \
             mock.patch("wayline.resources.sample_gpu_utilization",
                         return_value=[[{"index": 0, "uuid": "GPU-x", "memory_free_mib": 1000, "memory_total_mib": 2000,
                                          "memory_used_mib": 1000, "utilization_gpu": 5, "utilization_memory": 1}]] * 2), \
             mock.patch("wayline.resources.read_loadavg1", return_value=0.2), \
             mock.patch("wayline.resources.read_cpu_pressure", return_value=1.5), \
             mock.patch("wayline.resources.read_mem_available_bytes", return_value=10 * (1024 ** 3)), \
             mock.patch("wayline.resources.read_disk_avail_bytes", return_value=1024 ** 4), \
             mock.patch("os.cpu_count", return_value=16):
            view = r.snapshot(harness, jobs=[])
        lines = r.render_resources(view)
        text = "\n".join(lines)
        self.assertIn("reservation", text)
        self.assertIn("trader", text)
        self.assertIn("gpu slot 0", text)
        self.assertIn("psi 1.5%", text)
        for line in lines:
            self.assertEqual(line, line.rstrip())

    def test_renders_cpu_only_when_there_are_no_gpus(self):
        view = {
            "gpus": [], "cpu": {"loadavg1": 0.1, "nproc": 8, "reserved_cores": [], "cores_in_use": [], "free_cores": list(range(8)), "free": True},
            "ram": {"mem_available_bytes": 1024 ** 3, "reserved_bytes": 0, "committed_bytes": 0, "free_bytes": 1024 ** 3},
            "disk_avail_bytes": 0,
            "reservation": {"gpu_indices": [], "cores": [], "ram_gb": 0, "processes": [], "extra_gpu_mib": 0},
        }
        text = "\n".join(r.render_resources(view))
        self.assertIn("CPU-only", text)


if __name__ == "__main__":
    unittest.main()
