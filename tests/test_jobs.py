"""The job runner seam (Implementation Decisions 6; Testing Decisions seam 2).

The decode tests are driven by the `systemctl show` readings recorded in research-notes 05,
raw outputs R2 to R9. The note records those readings as the fields it read rather than as the
six lines `show -p LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus` prints, so
each block below is that reading spelled the way the poll line returns it, with the values
verbatim and the R block named. R10 and R11 are the tick's timer units, which carry no job state.

Nothing here launches a real unit or waits on a clock: the live end of the seam is milestone M2's
first criterion and is recorded in `docs/verification/m2.md`.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import resources as r
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger

# --- the recorded readings (research-notes 05) ----------------------------------------------------

# R2, polls 1 to 5: the sleep job while it ran.
R2_RUNNING = """LoadState=loaded
ActiveState=active
SubState=running
Result=success
ExecMainCode=0
ExecMainStatus=0
"""

# R2, polls 6 to 8: the same job after it exited 0, kept by `--remain-after-exit`.
R2_EXITED = """LoadState=loaded
ActiveState=active
SubState=exited
Result=success
ExecMainCode=1
ExecMainStatus=0
"""

# R3, "no --collect": the job that ran `exit 3`, which is the only variant a poller can read.
R3_EXIT_3 = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=exit-code
ExecMainCode=1
ExecMainStatus=3
"""

# R3 and R4, "--collect": the same failure and an OOM kill, both reading back as success once the
# unit is unloaded. This is why the launch line never passes `--collect`.
R3_COLLECTED = """LoadState=not-found
ActiveState=inactive
SubState=dead
Result=success
ExecMainCode=0
ExecMainStatus=0
"""

# R6: `MemoryMax=64M` against a 1 GiB allocation. The log file was empty.
R6_OOM_KILL = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=oom-kill
ExecMainCode=2
ExecMainStatus=9
"""

# R6, after `reset-failed`, and R9's cleanup audit: the unit is unloaded.
R9_NOT_FOUND = """LoadState=not-found
ActiveState=inactive
SubState=dead
Result=success
ExecMainCode=0
ExecMainStatus=0
"""

# R7: `notify-send` inside a unit, which exited 1 with its error text in the log.
R7_EXIT_1 = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=exit-code
ExecMainCode=1
ExecMainStatus=1
"""

# The rows of the decode table the research session recorded no `show` output for. Two of them the
# M2 live check produced and `docs/verification/m2.md` holds: this one, from a
# `kill --signal=SIGKILL`, and the timeout below.
SIGNAL_9 = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=signal
ExecMainCode=2
ExecMainStatus=9
"""

SIGNAL_15 = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=signal
ExecMainCode=2
ExecMainStatus=15
"""

# Live in the M2 check: a job with `RuntimeMaxSec=60` that slept ten minutes.
TIMEOUT = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=timeout
ExecMainCode=2
ExecMainStatus=15
"""

CORE_DUMP = """LoadState=loaded
ActiveState=failed
SubState=failed
Result=core-dump
ExecMainCode=3
ExecMainStatus=11
"""

CUDA_TRACEBACK = (
    "Traceback (most recent call last):\n"
    "  File \"train.py\", line 42, in <module>\n"
    "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 24.00 GiB\n"
)


def _done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _spec(temp, **overrides):
    fields = {
        "id": "t19-1", "ticket": 19, "command": ("/usr/bin/python3", "train.py", "--seed", "1"),
        "cwd": str(temp), "log": str(Path(temp) / "logs" / "t19-1.log"),
    }
    fields.update(overrides)
    return r.JobSpec(**fields)


# --- the decode table ------------------------------------------------------------------------------


class DecodeShowTest(unittest.TestCase):
    """Every row of the table of research-notes 05 A2, from the readings the session recorded."""

    def decode(self, text, tail=""):
        return r.decode_show(r.parse_show(text), tail)

    def test_the_poll_output_parses_as_key_equals_value(self):
        self.assertEqual(r.parse_show(R2_RUNNING), {
            "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
            "Result": "success", "ExecMainCode": "0", "ExecMainStatus": "0",
        })

    def test_r2_while_it_runs_is_running(self):
        state = self.decode(R2_RUNNING)
        self.assertEqual(state.name, "running")
        self.assertFalse(state.terminal)

    def test_r2_after_it_exits_zero_is_exited(self):
        state = self.decode(R2_EXITED)
        self.assertEqual((state.name, state.exit_code, state.result), ("exited", 0, "success"))
        self.assertTrue(state.terminal)

    def test_r3_without_collect_is_the_exit_code(self):
        state = self.decode(R3_EXIT_3)
        self.assertEqual((state.name, state.exit_code), ("failed", 3))
        self.assertIn("3", state.reason)

    def test_r3_with_collect_is_gone_and_never_exited(self):
        """The reading `--collect` produces for a job that exited 3, and why the line refuses it."""
        state = self.decode(R3_COLLECTED)
        self.assertEqual(state.name, "gone")
        self.assertNotEqual(state.name, "exited")

    def test_r6_oom_kill_is_a_host_kill(self):
        state = self.decode(R6_OOM_KILL)
        self.assertEqual((state.name, state.result, state.exit_code, state.oom), ("oom_host", "oom-kill", 9, "host"))

    def test_r9_not_found_is_gone_whatever_the_result_says(self):
        state = self.decode(R9_NOT_FOUND)
        self.assertEqual(state.name, "gone")
        self.assertIn("job file", state.reason)

    def test_r7_exit_one_without_a_signature_is_a_plain_failure(self):
        state = self.decode(R7_EXIT_1, tail="GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown\n")
        self.assertEqual((state.name, state.exit_code, state.oom), ("failed", 1, None))

    def test_exit_one_with_a_cuda_signature_is_a_gpu_oom(self):
        state = self.decode(R7_EXIT_1, tail=CUDA_TRACEBACK)
        self.assertEqual((state.name, state.exit_code, state.oom), ("oom_gpu", 1, "gpu"))
        self.assertIn("CUDA out of memory", state.reason)
        self.assertEqual(state.log_tail, CUDA_TRACEBACK)

    def test_a_signature_in_the_log_of_an_oom_killed_unit_is_still_a_host_kill(self):
        """`oom-kill` is decided before the log is read: the cgroup's word beats a stale traceback."""
        self.assertEqual(self.decode(R6_OOM_KILL, tail=CUDA_TRACEBACK).name, "oom_host")

    def test_sigkill_without_oom_kill_is_a_cancellation(self):
        state = self.decode(SIGNAL_9)
        self.assertEqual((state.name, state.exit_code), ("killed", 9))
        self.assertIsNone(state.oom)

    def test_another_signal_is_a_failure(self):
        state = self.decode(SIGNAL_15)
        self.assertEqual(state.name, "failed")
        self.assertIn("15", state.reason)

    def test_a_wallclock_expiry_is_a_failure_with_that_reason(self):
        state = self.decode(TIMEOUT)
        self.assertEqual((state.name, state.reason), ("failed", "wallclock"))

    def test_a_result_outside_the_table_is_a_failure_named_by_its_result(self):
        state = self.decode(CORE_DUMP)
        self.assertEqual((state.name, state.reason), ("failed", "core-dump"))

    def test_success_with_no_main_process_status_is_not_an_exit_zero(self):
        """`ExecMainCode=0` means the manager recorded no main process; the real exit 0 is 1 (R2)."""
        text = "LoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\nExecMainCode=0\nExecMainStatus=0\n"
        state = self.decode(text)
        self.assertEqual(state.name, "running")
        self.assertNotEqual(state.name, "exited")

    def test_deactivating_is_still_running(self):
        text = "LoadState=loaded\nActiveState=deactivating\nSubState=stop-sigterm\nResult=success\nExecMainCode=0\nExecMainStatus=0\n"
        self.assertEqual(self.decode(text).name, "running")

    def test_a_poll_the_manager_did_not_answer_is_an_error_and_not_a_state(self):
        with self.assertRaises(r.JobError):
            r.decode_show({"LoadState": "loaded", "ActiveState": "failed"})

    def test_the_readings_cover_every_state_but_the_fallback_only_ones(self):
        decoded = {
            self.decode(text, tail).name
            for text, tail in ((R2_RUNNING, ""), (R2_EXITED, ""), (R6_OOM_KILL, ""), (R7_EXIT_1, CUDA_TRACEBACK),
                               (R3_EXIT_3, ""), (SIGNAL_9, ""), (R9_NOT_FOUND, ""))
        }
        self.assertEqual(decoded, set(r.JOB_STATES))


class DecodeExitTest(unittest.TestCase):
    """The fallback's decoding: an exit file and a log, with no manager to ask (A5)."""

    def test_zero_is_exited(self):
        state = r.decode_exit(0)
        self.assertEqual((state.name, state.exit_code), ("exited", 0))

    def test_a_nonzero_exit_with_a_signature_is_a_gpu_oom(self):
        self.assertEqual(r.decode_exit(1, CUDA_TRACEBACK).name, "oom_gpu")

    def test_a_nonzero_exit_without_one_is_a_failure(self):
        state = r.decode_exit(3, "loss 0.5\n")
        self.assertEqual((state.name, state.exit_code, state.reason), ("failed", 3, "exited 3"))

    def test_the_two_signals_a_wayline_kill_sends_are_cancellations(self):
        self.assertEqual(r.decode_exit(143).name, "killed")
        self.assertEqual(r.decode_exit(137).name, "killed")
        self.assertEqual(r.decode_exit(137).reason, "SIGKILL")


class OomRuleTest(ProjectTestCase):
    def test_the_signature_table_is_the_eight_of_the_spec(self):
        self.assertEqual(r.GPU_OOM_SIGNATURES, (
            "CUDA out of memory", "torch.OutOfMemoryError", "torch.cuda.OutOfMemoryError",
            "CUDA_ERROR_OUT_OF_MEMORY", "cudaErrorMemoryAllocation", "RESOURCE_EXHAUSTED",
            "CUBLAS_STATUS_ALLOC_FAILED", "CUDNN_STATUS_ALLOC_FAILED",
        ))

    def test_every_signature_is_found(self):
        for signature in r.GPU_OOM_SIGNATURES:
            with self.subTest(signature=signature):
                self.assertEqual(r.gpu_oom_in("step 3\n%s: at 24 GiB\n" % signature), signature)

    def test_a_log_without_one_matches_nothing(self):
        self.assertIsNone(r.gpu_oom_in("epoch 1 loss 0.4\nepoch 2 loss 0.3\n"))

    def test_the_tail_is_the_last_bytes_and_no_more(self):
        log = self.temp / "big.log"
        log.write_text("x" * 200000 + "CUDA out of memory\n", encoding="utf-8")
        self.assertEqual(len(r.log_tail(log)), r.OOM_LOG_TAIL_BYTES)
        self.assertIsNotNone(r.gpu_oom_in(r.log_tail(log)))
        early = self.temp / "early.log"
        early.write_text("CUDA out of memory\n" + "x" * 200000, encoding="utf-8")
        self.assertIsNone(r.gpu_oom_in(r.log_tail(early)), "a signature older than the tail is not read")
        self.assertEqual(len(r.log_tail(early, limit=32)), 32)

    def test_an_absent_log_is_empty_text(self):
        self.assertEqual(r.log_tail("/nonexistent/wayline/job.log"), "")

    def test_the_tail_limit_is_the_policy_default(self):
        policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(r.OOM_LOG_TAIL_BYTES, policy["jobs"]["oom_log_tail_bytes"])


# --- the launch lines -------------------------------------------------------------------------------


class SystemdRunLineTest(ProjectTestCase):
    """The launch line of Implementation Decisions 6, option by option and in order."""

    def setUp(self):
        super().setUp()
        self.spec = _spec(self.temp, cores=(8, 9, 10, 11), ram_gb=64, wallclock_minutes=90,
                          gpu_uuids=("GPU-0095fb8d",))

    def test_the_line_is_the_spec_line(self):
        argv = r.systemd_run_argv(self.spec, (0,))
        self.assertEqual(argv, [
            "systemd-run", "--user", "--unit=wayline-job-t19-1", "--slice=wayline-jobs",
            "--remain-after-exit", "--expand-environment=no",
            "-p", "CPUAffinity=8-11",
            "-p", "MemoryMax=%d" % (64 * 1024 ** 3),
            "-p", "MemorySwapMax=0",
            "-p", "TimeoutStopSec=30",
            "-p", "RuntimeMaxSec=5400",
            "-p", "WorkingDirectory=%s" % self.temp,
            "-p", "StandardOutput=append:%s/logs/t19-1.log" % self.temp,
            "-p", "StandardError=append:%s/logs/t19-1.log" % self.temp,
            "-E", "CUDA_VISIBLE_DEVICES=0",
            "-E", "PYTHONUNBUFFERED=1",
            "/usr/bin/python3", "train.py", "--seed", "1",
        ])

    def test_it_never_passes_collect(self):
        self.assertNotIn("--collect", r.systemd_run_argv(self.spec, (0,)))

    def test_the_unit_name_is_the_job_id_and_the_poll_line_spells_it_with_the_suffix(self):
        self.assertEqual(r.unit_name("t19-1"), "wayline-job-t19-1.service")
        self.assertEqual(r.unit_argument("wayline-job-t19-1.service"), "wayline-job-t19-1")

    def test_a_cpu_job_is_told_it_has_no_gpu(self):
        argv = r.systemd_run_argv(_spec(self.temp, cores=(8,)), ())
        self.assertIn("CUDA_VISIBLE_DEVICES=", argv)
        self.assertNotIn("CUDA_VISIBLE_DEVICES=0", argv)

    def test_a_job_without_cores_or_ram_omits_the_options_it_has_no_value_for(self):
        argv = r.systemd_run_argv(_spec(self.temp), ())
        self.assertNotIn("CPUAffinity=", " ".join(argv))
        self.assertNotIn("MemoryMax=", " ".join(argv))

    def test_the_ticket_environment_rides_after_the_two_the_line_always_sets(self):
        argv = r.systemd_run_argv(_spec(self.temp, env={"WAYLINE_TICKET": "19", "SEED": "7"}), ())
        self.assertEqual(argv[argv.index("-E", argv.index("PYTHONUNBUFFERED=1")):], [
            "-E", "SEED=7", "-E", "WAYLINE_TICKET=19",
            "/usr/bin/python3", "train.py", "--seed", "1",
        ])

    def test_a_relative_path_is_refused_before_anything_is_launched(self):
        for field in ("cwd", "log"):
            with self.subTest(field=field):
                with self.assertRaises(r.JobError):
                    _spec(self.temp, **{field: "results/train.log"}).check()

    def test_a_job_without_a_command_is_refused(self):
        with self.assertRaises(r.JobError):
            _spec(self.temp, command=()).check()


class SetsidLineTest(ProjectTestCase):
    """The fallback launch line of research-notes 05 A5."""

    def test_the_line_is_the_note_line(self):
        spec = _spec(self.temp, cores=(8, 9))
        argv = r.setsid_argv(spec, (0,), exit_file="%s/logs/t19-1.exit" % self.temp)
        self.assertEqual(argv, [
            "setsid", "nohup", "env", "CUDA_VISIBLE_DEVICES=0", "PYTHONUNBUFFERED=1",
            "taskset", "-c", "8-9",
            "sh", "-c", "/usr/bin/python3 train.py --seed 1; echo $? > %s/logs/t19-1.exit" % self.temp,
        ])

    def test_the_exit_file_defaults_to_the_log_directory(self):
        argv = r.setsid_argv(_spec(self.temp), ())
        self.assertIn("echo $? > %s/logs/t19-1.exit" % self.temp, argv[-1])

    def test_a_command_with_spaces_is_quoted_for_the_shell(self):
        argv = r.setsid_argv(_spec(self.temp, command=("/usr/bin/python3", "-c", "print('a b')")), ())
        self.assertIn("'print('\"'\"'a b'\"'\"')'", argv[-1])


# --- the backends -------------------------------------------------------------------------------------


class SystemdRunBackendTest(ProjectTestCase):
    """The real backend's three commands, with `subprocess` answered from recorded output."""

    def setUp(self):
        super().setUp()
        self.spec = _spec(self.temp, cores=(8,))
        self.handle = r.JobHandle(id="t19-1", backend="systemd_run", log=self.spec.log,
                                  cwd=self.spec.cwd, unit="wayline-job-t19-1.service")

    def test_launch_runs_the_line_and_hands_back_a_handle(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("Running as unit: wayline-job-t19-1.service\n")) as run:
            handle = r.SYSTEMD_RUN.launch(self.spec, (0,))
        self.assertEqual(run.call_args[0][0][:2], ["systemd-run", "--user"])
        self.assertEqual((handle.unit, handle.backend, handle.gpu_indices), ("wayline-job-t19-1.service", "systemd_run", (0,)))
        self.assertTrue(Path(self.spec.log).parent.is_dir(), "the log directory is made before the launch")

    def test_a_refused_launch_is_an_error_and_not_a_state(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("", 1, "Unit wayline-job-t19-1.service already exists.")):
            with self.assertRaises(r.JobError) as caught:
                r.SYSTEMD_RUN.launch(self.spec, ())
        self.assertIn("already exists", str(caught.exception))

    def test_a_missing_cwd_is_refused(self):
        with self.assertRaises(r.JobError):
            r.SYSTEMD_RUN.launch(_spec(self.temp, cwd=str(self.temp / "gone")), ())

    def test_poll_asks_for_the_six_properties(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(R2_RUNNING)) as run:
            state = r.SYSTEMD_RUN.poll(self.handle)
        self.assertEqual(run.call_args[0][0], [
            "systemctl", "--user", "show", "wayline-job-t19-1.service", "-p",
            "LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus",
        ])
        self.assertEqual(state.name, "running")

    def test_poll_reads_the_log_only_when_the_result_is_an_exit_code(self):
        Path(self.spec.log).parent.mkdir(parents=True, exist_ok=True)
        Path(self.spec.log).write_text(CUDA_TRACEBACK, encoding="utf-8")
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(R7_EXIT_1)):
            self.assertEqual(r.SYSTEMD_RUN.poll(self.handle).name, "oom_gpu")
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(R6_OOM_KILL)):
            self.assertEqual(r.SYSTEMD_RUN.poll(self.handle).name, "oom_host")

    def test_a_manager_that_does_not_answer_a_poll_is_an_error(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("", 1, "Failed to connect to bus")):
            with self.assertRaises(r.JobError):
                r.SYSTEMD_RUN.poll(self.handle)

    def test_kill_stops_the_unit_and_hard_kill_signals_it(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done()) as run:
            r.SYSTEMD_RUN.kill(self.handle)
            self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "stop", "wayline-job-t19-1.service"])
            r.SYSTEMD_RUN.kill(self.handle, hard=True)
            self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "kill", "--signal=SIGKILL", "wayline-job-t19-1.service"])

    def test_a_finished_unit_of_the_same_id_is_unloaded_before_a_relaunch(self):
        """The footprint ladder relaunches a job id, and `systemd-run` refuses a loaded name."""
        answers = [_done(R2_EXITED), _done(), _done(), _done("Running as unit: wayline-job-t19-1.service\n")]
        with mock.patch("wayline.resources.subprocess.run", side_effect=answers) as run:
            r.SYSTEMD_RUN.launch(self.spec, ())
        commands = [call[0][0][:1] + call[0][0][2:4] for call in run.call_args_list]
        self.assertEqual(commands, [
            ["systemctl", "show", "wayline-job-t19-1.service"],
            ["systemctl", "reset-failed", "wayline-job-t19-1.service"],
            ["systemctl", "stop", "wayline-job-t19-1.service"],
            ["systemd-run", "--unit=wayline-job-t19-1", "--slice=wayline-jobs"],
        ])

    def test_relaunching_a_running_job_is_refused_and_never_stops_it(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done(R2_RUNNING)) as run:
            with self.assertRaises(r.JobError) as caught:
                r.SYSTEMD_RUN.launch(self.spec, ())
        self.assertIn("already running", str(caught.exception))
        self.assertEqual(len(run.call_args_list), 1, "nothing but the poll ran")

    def test_a_job_whose_unit_is_gone_is_launched_without_a_cleanup(self):
        answers = [_done(R9_NOT_FOUND), _done("Running as unit: wayline-job-t19-1.service\n")]
        with mock.patch("wayline.resources.subprocess.run", side_effect=answers) as run:
            r.SYSTEMD_RUN.launch(self.spec, ())
        self.assertEqual([call[0][0][0] for call in run.call_args_list], ["systemctl", "systemd-run"])

    def test_kill_all_stops_the_slice(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done()) as run:
            r.SYSTEMD_RUN.kill_all()
        self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "stop", "wayline-jobs.slice"])

    def test_cleanup_resets_a_failure_and_stops_an_exited_unit_and_ignores_both_errors(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("", 1, "Unit not loaded.")) as run:
            self.assertTrue(r.SYSTEMD_RUN.cleanup(self.handle))
        self.assertEqual([call[0][0][2:4] for call in run.call_args_list], [["reset-failed", "wayline-job-t19-1.service"], ["stop", "wayline-job-t19-1.service"]])

    def test_a_kill_the_manager_refuses_is_reported_and_never_raised(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done("", 5, "Unit not loaded.")):
            self.assertFalse(r.SYSTEMD_RUN.kill(self.handle))


class SetsidBackendTest(ProjectTestCase):
    """The fallback's poll, kill, and cleanup over the files A5 leaves behind."""

    def setUp(self):
        super().setUp()
        self.spec = _spec(self.temp)
        Path(self.spec.log).parent.mkdir(parents=True, exist_ok=True)
        self.handle = r.JobHandle(id="t19-1", backend="setsid", log=self.spec.log, cwd=self.spec.cwd, pid=None)

    def test_the_state_files_live_beside_the_log(self):
        self.assertEqual(self.handle.exit_file, Path(self.spec.log).parent / "t19-1.exit")
        self.assertEqual(self.handle.pid_file, Path(self.spec.log).parent / "t19-1.pid")

    def test_an_exit_file_is_the_answer(self):
        self.handle.exit_file.write_text("0\n", encoding="utf-8")
        self.assertEqual(r.SETSID.poll(self.handle).name, "exited")

    def test_a_nonzero_exit_reads_the_log(self):
        self.handle.exit_file.write_text("1\n", encoding="utf-8")
        Path(self.spec.log).write_text(CUDA_TRACEBACK, encoding="utf-8")
        self.assertEqual(r.SETSID.poll(self.handle).name, "oom_gpu")

    def test_a_live_pid_with_no_exit_file_is_running(self):
        self.handle.pid_file.write_text("%d\n" % os.getpid(), encoding="utf-8")
        self.assertEqual(r.SETSID.poll(self.handle).name, "running")

    def test_neither_an_exit_file_nor_a_live_pid_is_gone_and_never_exited(self):
        """A5: the exit file is missing when the shell itself was killed; that is not a success."""
        self.handle.pid_file.write_text("2147483646\n", encoding="utf-8")
        state = r.SETSID.poll(self.handle)
        self.assertEqual(state.name, "gone")

    def test_a_kill_without_a_pid_is_reported_and_never_raised(self):
        self.assertFalse(r.SETSID.kill(self.handle))

    def test_a_zombie_pid_is_not_a_running_job(self):
        """A killed fallback job leaves an unreaped child, which keeps answering `kill(pid, 0)`."""
        if not hasattr(os, "fork"):
            self.skipTest("no fork on this platform")
        pid = os.fork()
        if pid == 0:  # the child exits at once and is nobody's business to reap but ours
            os._exit(0)
        self.addCleanup(self._reap, pid)
        deadline = time.monotonic() + 5
        while not r._is_zombie(pid) and time.monotonic() < deadline:
            pass
        self.assertTrue(r._is_zombie(pid), "the child should be a zombie until it is reaped")
        self.assertFalse(r._pid_alive(pid))
        self.handle.pid_file.write_text("%d\n" % pid, encoding="utf-8")
        self.assertEqual(r.SETSID.poll(self.handle).name, "gone", "not `running`, and not `exited`")

    @staticmethod
    def _reap(pid):
        try:
            os.waitpid(pid, 0)
        except (ChildProcessError, OSError):
            pass

    def test_this_process_is_alive_and_a_state_file_saying_zombie_is_not(self):
        self.assertTrue(r._pid_alive(os.getpid()))
        fake = self.temp / "proc" / str(os.getpid())
        fake.mkdir(parents=True)
        (fake / "status").write_text("Name:\tpython3\nState:\tZ (zombie)\n", encoding="utf-8")
        self.assertFalse(r._pid_alive(os.getpid(), proc_dir=self.temp / "proc"))

    def test_cleanup_removes_the_two_files(self):
        self.handle.exit_file.write_text("0\n", encoding="utf-8")
        self.handle.pid_file.write_text("1\n", encoding="utf-8")
        r.SETSID.cleanup(self.handle)
        self.assertFalse(self.handle.exit_file.exists() or self.handle.pid_file.exists())


class BackendSelectionTest(unittest.TestCase):
    def test_the_environment_names_a_backend(self):
        with mock.patch.dict(os.environ, {"WAYLINE_JOBS": "fake"}):
            self.assertIs(r.jobs_backend(), r.FAKE_JOBS)
        with mock.patch.dict(os.environ, {"WAYLINE_JOBS": "setsid"}):
            self.assertIs(r.jobs_backend(), r.SETSID)

    def test_a_name_that_is_no_backend_is_an_error(self):
        with mock.patch.dict(os.environ, {"WAYLINE_JOBS": "slurm"}):
            with self.assertRaises(r.JobError):
                r.jobs_backend()

    def test_the_fallback_is_chosen_when_no_user_manager_answers(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WAYLINE_JOBS", None)
            with mock.patch("wayline.resources.user_manager_reachable", return_value=False):
                self.assertIs(r.jobs_backend(), r.SETSID)
            with mock.patch("wayline.resources.user_manager_reachable", return_value=True):
                self.assertIs(r.jobs_backend(), r.SYSTEMD_RUN)

    def test_the_reachability_question_is_the_note_command(self):
        with mock.patch("wayline.resources.subprocess.run", return_value=_done()) as run:
            self.assertTrue(r.user_manager_reachable())
        self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "show-environment"])

    def test_the_three_backends_of_the_spec_and_no_fourth(self):
        self.assertEqual(sorted(r.JOBS_BACKENDS), ["fake", "setsid", "systemd_run"])
        self.assertEqual(sorted(load_schema("job")["properties"]["backend"]["enum"]), sorted(r.JOBS_BACKENDS))


class FakeBackendTest(ProjectTestCase):
    """The fake advances scripted states, writes scripted outputs, and fakes both OOMs."""

    def test_every_state_can_be_reached(self):
        for name in r.JOB_STATES:
            with self.subTest(state=name):
                with r.use_fake_jobs() as fake:
                    fake.script(["running", name] if name != "running" else ["running"])
                    runner = r.JobRunner(backend=fake)
                    handle = runner.launch(_spec(self.temp))
                    self.assertEqual(runner.poll(handle).name, "running")
                    self.assertEqual(runner.poll(handle).name, name)

    def test_the_last_state_is_kept_for_every_later_poll(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running", "exited"])
            runner = r.JobRunner(backend=fake)
            handle = runner.launch(_spec(self.temp))
            self.assertEqual([runner.poll(handle).name for _ in range(4)], ["running", "exited", "exited", "exited"])

    def test_an_exited_job_writes_its_scripted_outputs(self):
        with r.use_fake_jobs() as fake:
            fake.script(["exited"], outputs={"results/summary.json": '{"auroc": 0.81}\n'})
            handle = r.JobRunner(backend=fake).launch(_spec(self.temp))
            self.assertEqual(fake.poll(handle).name, "exited")
        self.assertEqual(json.loads((self.temp / "results" / "summary.json").read_text(encoding="utf-8")), {"auroc": 0.81})

    def test_an_oom_writes_no_outputs_and_carries_the_log_the_ladder_reads(self):
        with r.use_fake_jobs() as fake:
            fake.script([r.JobState("oom_gpu", result="exit-code", exit_code=1)],
                        outputs={"results/summary.json": "{}"}, log=CUDA_TRACEBACK)
            spec = _spec(self.temp)
            handle = r.JobRunner(backend=fake).launch(spec)
            state = fake.poll(handle)
        self.assertEqual((state.name, state.oom), ("oom_gpu", "gpu"))
        self.assertFalse((self.temp / "results" / "summary.json").exists())
        self.assertIn("CUDA out of memory", r.log_tail(spec.log))

    def test_a_host_oom_is_fakeable_too(self):
        with r.use_fake_jobs() as fake:
            fake.script(["oom_host"], log="")
            handle = r.JobRunner(backend=fake).launch(_spec(self.temp))
            self.assertEqual(fake.poll(handle).oom, "host")

    def test_a_kill_turns_the_rest_of_the_script_into_a_cancellation(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running", "running", "exited"])
            runner = r.JobRunner(backend=fake)
            handle = runner.launch(_spec(self.temp))
            self.assertEqual(runner.poll(handle).name, "running")
            runner.kill(handle)
            self.assertEqual(runner.poll(handle).name, "killed")

    def test_a_job_with_nothing_scripted_is_an_error(self):
        with r.use_fake_jobs() as fake:
            with self.assertRaises(r.JobError):
                fake.launch(_spec(self.temp))

    def test_a_script_may_name_the_job_it_answers_for(self):
        with r.use_fake_jobs() as fake:
            fake.script(["exited"], job_id="t19-2")
            fake.script(["failed"], job_id="t19-1")
            first = fake.launch(_spec(self.temp, id="t19-1"))
            second = fake.launch(_spec(self.temp, id="t19-2", log=str(self.temp / "logs" / "t19-2.log")))
            self.assertEqual((fake.poll(first).name, fake.poll(second).name), ("failed", "exited"))

    def test_the_calls_are_recorded_in_order(self):
        with r.use_fake_jobs() as fake:
            fake.script(["exited"])
            handle = fake.launch(_spec(self.temp))
            fake.poll(handle)
            fake.cleanup(handle)
            self.assertEqual(fake.calls, [("launch", "t19-1"), ("poll", "t19-1"), ("cleanup", "t19-1")])

    def test_the_selected_backend_is_restored_afterwards(self):
        with mock.patch.dict(os.environ, {"WAYLINE_JOBS": "setsid"}):
            with r.use_fake_jobs():
                self.assertEqual(os.environ["WAYLINE_JOBS"], "fake")
            self.assertEqual(os.environ["WAYLINE_JOBS"], "setsid")


# --- the runner and the job file -----------------------------------------------------------------------


class JobFileTest(ProjectTestCase):
    def test_the_record_is_the_schema(self):
        spec = _spec(self.temp, cores=(8, 9), ram_gb=32, gpu_uuids=("GPU-0095fb8d",),
                     expected_outputs=("results/summary.json",), array="sweep-lr",
                     retry={"host_oom": [{"--workers": 2}], "gpu_oom": [{"--batch-size": 16}]})
        record = r.job_record(spec, backend="systemd_run", unit=r.unit_name(spec.id), gpu_indices=(0,), status="running")
        check(record, load_schema("job"), name="job")
        self.assertEqual(record["devices"], {
            "gpu_uuids": ["GPU-0095fb8d"], "gpu_indices": [0], "cores": [8, 9], "ram_gb": 32,
        })
        self.assertEqual(record["array"], "sweep-lr")

    def test_a_record_round_trips_through_a_spec_and_a_handle(self):
        spec = _spec(self.temp, cores=(8,), ram_gb=8, gpu_uuids=("GPU-0095fb8d",))
        record = r.job_record(spec, backend="setsid", unit=None, gpu_indices=(0,), status="running")
        again = r.spec_from_record(record)
        self.assertEqual((again.id, again.command, again.cores, again.gpu_uuids), (spec.id, spec.command, spec.cores, spec.gpu_uuids))
        handle = r.handle_for(record)
        self.assertEqual((handle.id, handle.backend, handle.gpu_indices), ("t19-1", "setsid", (0,)))

    def test_a_uuid_is_resolved_to_an_index_at_launch(self):
        gpus = [{"index": 0, "uuid": "GPU-aaa"}, {"index": 1, "uuid": "GPU-bbb"}]
        self.assertEqual(r.resolve_gpu_indices(("GPU-bbb",), gpus=gpus), (1,))
        self.assertEqual(r.resolve_gpu_indices((), gpus=gpus), ())
        with self.assertRaises(r.JobError):
            r.resolve_gpu_indices(("GPU-ccc",), gpus=gpus)


class JobRunnerRecordsTest(ProjectTestCase):
    """What the job file and the journal say after a launch, a poll, and a kill."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        (self.project / "results").mkdir(exist_ok=True)

    def spec(self, **overrides):
        fields = {"cwd": str(self.project), "log": str(self.project / "results" / "t19-1.log")}
        fields.update(overrides)
        return _spec(self.project, **fields)

    def events(self, name):
        return [event for event in Ledger(self.project).read_events()[0] if event["event"] == name]

    def record(self, job_id="t19-1"):
        return json.loads((self.project / "research" / "jobs" / ("%s.json" % job_id)).read_text(encoding="utf-8"))

    def test_the_fixture_ledger_holds_one_live_job_of_its_own(self):
        """What the live-record tests below count against (`fixtures/ledger/research/jobs/`)."""
        self.assertEqual(sorted(record["status"] for record in r.JobRunner(self.project).live_records()), ["running"])

    def test_a_launch_writes_the_job_file_and_journals_it(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running"])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec(cores=(8, 9), ram_gb=16))
        record = self.record()
        check(record, load_schema("job"), name="job")
        self.assertEqual((record["status"], record["backend"], record["unit"]), ("running", "fake", handle.unit))
        self.assertEqual(len(record["attempts"]), 1)
        self.assertEqual(record["attempts"][0]["n"], 1)
        self.assertIsNone(record["attempts"][0]["ended_at"])
        launched = [event for event in self.events("job_launched") if event["job"] == "t19-1"]
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0]["payload"]["cores"], [8, 9])
        self.assertEqual(launched[0]["payload"]["unit"], handle.unit)
        self.assertEqual(launched[0]["ticket"], 19)

    def test_the_first_terminal_poll_closes_the_attempt_with_the_exit_code(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running", r.JobState("exited", result="success", exit_code=0)])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            runner.poll(handle)
            runner.poll(handle)
        attempt = self.record()["attempts"][0]
        self.assertEqual((attempt["result"], attempt["exit_code"], attempt["oom"]), ("success", 0, None))
        self.assertIsNotNone(attempt["ended_at"])
        self.assertLessEqual(attempt["started_at"], attempt["ended_at"], "the two timestamps are the job's duration")
        self.assertEqual(self.record()["status"], "exited")

    def test_a_gpu_oom_is_recorded_as_one(self):
        with r.use_fake_jobs() as fake:
            fake.script([r.JobState("oom_gpu", result="exit-code", exit_code=1)])
            runner = r.JobRunner(self.project, backend=fake)
            runner.poll(runner.launch(self.spec()))
        attempt = self.record()["attempts"][0]
        self.assertEqual((self.record()["status"], attempt["oom"], attempt["result"]), ("oom_gpu", "gpu", "exit-code"))

    def test_a_poll_that_changes_nothing_rewrites_nothing(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running"])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            path = self.project / "research" / "jobs" / "t19-1.json"
            before = path.stat().st_mtime_ns, path.read_text(encoding="utf-8")
            runner.poll(handle)
            self.assertEqual((path.stat().st_mtime_ns, path.read_text(encoding="utf-8")), before)

    def test_a_cancelled_job_stays_cancelled_when_the_manager_calls_it_a_success(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running", "exited"])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            runner.kill(handle)
            self.assertEqual(self.record()["status"], "killed")
            fake.live[handle.id]["states"] = [r.JobState("exited", result="success", exit_code=0)]
            runner.poll(handle)
        self.assertEqual(self.record()["status"], "killed")
        self.assertEqual(self.record()["attempts"][0]["result"], "success")
        self.assertEqual(len(self.events("job_cancelled")), 1)

    def test_a_cancelled_job_stays_cancelled_whatever_a_later_poll_reads(self):
        """Every backend reads a cancellation as something else; none of them may undo it."""
        for reading in ("gone", "running", "exited", "failed"):
            with self.subTest(poll=reading):
                with r.use_fake_jobs() as fake:
                    fake.script(["running"])
                    runner = r.JobRunner(self.project, backend=fake)
                    handle = runner.launch(self.spec(), )
                    runner.kill(handle)
                    fake.live[handle.id]["states"] = [r.JobState(reading)]
                    runner.poll(handle)
                    self.assertEqual(self.record()["status"], "killed")
                (self.project / "research" / "jobs" / "t19-1.json").unlink()

    def test_cancelling_a_job_that_already_finished_leaves_its_result_alone(self):
        """The ordinary race: the conductor cancels a job that exited a moment earlier."""
        with r.use_fake_jobs() as fake:
            fake.script([r.JobState("exited", result="success", exit_code=0)])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            runner.poll(handle)
            runner.kill(handle)
        record = self.record()
        self.assertEqual(record["status"], "exited")
        self.assertEqual(record["attempts"][0]["exit_code"], 0)
        self.assertEqual([event for event in self.events("job_cancelled") if event["job"] == "t19-1"], [])

    def test_cancel_everything_walks_the_live_jobs_when_a_backend_has_no_slice(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running"], job_id="t19-1")
            fake.script(["running"], job_id="t19-2")
            runner = r.JobRunner(self.project, backend=fake)
            runner.launch(self.spec())
            runner.launch(self.spec(id="t19-2", log=str(self.project / "results" / "t19-2.log")))
            with mock.patch.object(r.FakeJobs, "kill_all", None):  # a backend without one, as `setsid` is
                self.assertTrue(runner.kill_all())
        self.assertEqual([self.record(job)["status"] for job in ("t19-1", "t19-2")], ["killed", "killed"])

    def test_cancel_everything_uses_the_slice_when_the_backend_has_one(self):
        with r.use_fake_jobs() as fake:
            fake.script(["running"])
            runner = r.JobRunner(self.project, backend=fake)
            runner.launch(self.spec())
            self.assertTrue(runner.kill_all())
            self.assertEqual(fake.poll(r.handle_for(self.record())).name, "killed")

    def test_the_live_records_are_the_pending_and_running_ones(self):
        with r.use_fake_jobs() as fake:
            fake.script([r.JobState("exited", result="success", exit_code=0)])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            self.assertEqual([record["id"] for record in runner.live_records()], ["j-0001", "t19-1"])
            runner.poll(handle)
            self.assertEqual([record["id"] for record in runner.live_records()], ["j-0001"])

    def test_a_second_launch_of_the_same_job_opens_a_second_attempt(self):
        with r.use_fake_jobs() as fake:
            fake.script(["oom_gpu"])
            fake.script(["exited"])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            runner.poll(handle)
            runner.launch(self.spec())
        attempts = self.record()["attempts"]
        self.assertEqual([attempt["n"] for attempt in attempts], [1, 2])
        self.assertEqual(attempts[0]["oom"], "gpu")
        self.assertIsNone(attempts[1]["ended_at"])

    def test_the_runner_without_a_project_writes_nothing_and_still_runs(self):
        with r.use_fake_jobs() as fake:
            fake.script(["exited"])
            runner = r.JobRunner(backend=fake)
            handle = runner.launch(_spec(self.temp))
            self.assertEqual(runner.poll(handle).name, "exited")

    def test_wait_polls_until_the_job_is_no_longer_running(self):
        naps = []
        with r.use_fake_jobs() as fake:
            fake.script(["running", "running", "exited"])
            runner = r.JobRunner(self.project, backend=fake)
            handle = runner.launch(self.spec())
            state = runner.wait(handle, sleep=naps.append)
        self.assertEqual(state.name, "exited")
        self.assertEqual(len(naps), 2, "one nap per poll that found it running")

    def test_the_conductor_can_poll_a_job_it_did_not_launch(self):
        """The handle is rebuildable from the file, which is what a restarted conductor has."""
        with r.use_fake_jobs() as fake:
            fake.script(["running", "exited"])
            runner = r.JobRunner(self.project, backend=fake)
            launched = runner.launch(self.spec())
            rebuilt = r.handle_for(self.record())
            self.assertEqual((rebuilt.id, rebuilt.unit, rebuilt.log), (launched.id, launched.unit, launched.log))
            self.assertEqual(r.JobRunner(self.project, backend=fake).poll(rebuilt).name, "running")

    def test_a_poll_follows_the_backend_that_launched_the_job(self):
        """A runner that would pick systemd must not poll a `setsid` job with `systemctl`."""
        with r.use_fake_jobs() as fake:
            fake.script(["running"])
            handle = r.JobRunner(self.project, backend=fake).launch(self.spec())
            runner = r.JobRunner(self.project, backend=r.SYSTEMD_RUN)
            self.assertIs(runner._backend_for(handle), fake)
            self.assertEqual(runner.poll(handle).name, "running")
            self.assertIs(runner._backend_for(r.handle_for(self.record())), fake)


# --- `wayline job add` -------------------------------------------------------------------------------


class AddJobsTest(ProjectTestCase):
    """`add_jobs` is the verb's function; the backend is named so a `pending` file validates."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()

    def add(self, spec, **options):
        return r.add_jobs(self.project, spec, backend="systemd_run", **options)

    def jobs(self):
        return sorted(path.stem for path in (self.project / "research" / "jobs").glob("*.json"))

    def read(self, job_id):
        return json.loads((self.project / "research" / "jobs" / ("%s.json" % job_id)).read_text(encoding="utf-8"))

    def test_one_spec_writes_one_validated_job_file(self):
        records = self.add({
            "ticket": 19, "command": ["python", "-m", "toy.train"], "devices": {"cores": [8, 9], "ram_gb": 16},
            "expected_outputs": ["results/summary.json"], "wallclock_minutes": 30,
        })
        self.assertEqual(len(records), 1)
        record = self.read(records[0]["id"])
        check(record, load_schema("job"), name="job")
        self.assertEqual((record["ticket"], record["array"], record["status"]), (19, None, "pending"))
        self.assertEqual(record["devices"]["cores"], [8, 9])
        self.assertEqual((record["backend"], record["unit"]), ("systemd_run", None),
                         "a job file written before a launch names the runner but no unit yet")

    def test_the_paths_are_resolved_against_the_project(self):
        record = self.add({"ticket": 19, "command": ["true"], "cwd": ".", "log": "results/run.log"})[0]
        self.assertEqual(record["cwd"], str(self.project))
        self.assertEqual(record["log"], str(self.project / "results" / "run.log"))

    def test_the_log_defaults_under_results(self):
        record = self.add({"ticket": 19, "command": ["true"], "id": "t19-x"})[0]
        self.assertEqual(record["log"], str(self.project / "results" / "logs" / "t19-x.log"))

    def test_an_array_writes_one_file_per_member_with_one_array_id(self):
        records = self.add({
            "ticket": 19, "array_id": "sweep-lr", "command": ["python", "train.py"],
            "devices": {"cores": [8], "ram_gb": 8},
            "members": [{"env": {"LR": "0.1"}}, {"env": {"LR": "0.01"}}, {"id": "sweep-lr-slow", "env": {"LR": "0.001"}}],
        })
        self.assertEqual([record["id"] for record in records], ["sweep-lr-1", "sweep-lr-2", "sweep-lr-slow"])
        self.assertEqual({record["array"] for record in records}, {"sweep-lr"})
        self.assertEqual([record["env"]["LR"] for record in records], ["0.1", "0.01", "0.001"])
        self.assertEqual(self.jobs(), ["j-0001", "j-0002", "sweep-lr-1", "sweep-lr-2", "sweep-lr-slow"])

    def test_a_member_overrides_what_it_names_and_inherits_the_rest(self):
        records = self.add({
            "ticket": 19, "array_id": "sweep", "command": ["python", "train.py"],
            "devices": {"cores": [8]}, "wallclock_minutes": 20,
            "members": [{}, {"command": ["python", "train.py", "--big"], "wallclock_minutes": 90}],
        })
        self.assertEqual(records[0]["command"], ["python", "train.py"])
        self.assertEqual(records[1]["command"], ["python", "train.py", "--big"])
        self.assertEqual([record["wallclock_minutes"] for record in records], [20, 90])
        self.assertEqual([record["devices"]["cores"] for record in records], [[8], [8]])

    def test_an_id_never_lands_on_a_job_already_on_disk(self):
        first = self.add({"ticket": 19, "command": ["true"]})[0]
        second = self.add({"ticket": 19, "command": ["true"]})[0]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual([first["id"], second["id"]], ["t19-1", "t19-2"])

    def test_the_ticket_may_come_from_the_worker_session(self):
        record = self.add({"command": ["true"]}, ticket=7)[0]
        self.assertEqual((record["ticket"], record["id"]), (7, "t7-1"))

    def test_a_spec_without_a_ticket_anywhere_is_refused(self):
        with self.assertRaises(r.JobError):
            self.add({"command": ["true"]})

    def test_a_field_the_spec_does_not_have_is_refused(self):
        with self.assertRaises(r.JobError) as caught:
            self.add({"ticket": 19, "command": ["true"], "gpu": 1})
        self.assertIn("gpu", str(caught.exception))
        with self.assertRaises(r.JobError):
            self.add({"ticket": 19, "command": ["true"], "devices": {"gpus": 1}})

    def test_a_spec_that_is_not_an_object_is_refused(self):
        for value in ([], "train.py", 3):
            with self.subTest(spec=value):
                with self.assertRaises(r.JobError):
                    self.add(value)

    def test_an_array_whose_member_is_invalid_writes_nothing(self):
        with self.assertRaises(r.JobError):
            self.add({
                "ticket": 19, "array_id": "sweep", "command": ["true"],
                "members": [{}, {"wallclock_minutes": 0}],
            })
        self.assertEqual(self.jobs(), ["j-0001", "j-0002"])

    def test_a_job_without_a_command_is_refused(self):
        with self.assertRaises(r.JobError):
            self.add({"ticket": 19})

    def test_a_spec_id_names_the_array_and_not_every_member(self):
        """Members that inherited the spec's id would all be written to one file, and one would live."""
        records = self.add({
            "id": "sweep", "ticket": 19, "command": ["python", "train.py"],
            "members": [{"env": {"LR": "0.1"}}, {"env": {"LR": "0.01"}}],
        })
        self.assertEqual([record["id"] for record in records], ["sweep-1", "sweep-2"])
        self.assertEqual({record["array"] for record in records}, {"sweep"})
        self.assertEqual(self.jobs(), ["j-0001", "j-0002", "sweep-1", "sweep-2"])
        self.assertEqual([self.read(record["id"])["env"]["LR"] for record in records], ["0.1", "0.01"])

    def test_an_array_that_names_no_group_is_grouped_by_its_ticket(self):
        records = self.add({"ticket": 19, "command": ["true"], "members": [{}, {}]})
        self.assertEqual([record["id"] for record in records], ["t19-1", "t19-2"])
        self.assertEqual({record["array"] for record in records}, {"t19"},
                         "a member with no array id is not in an array as far as the conductor can tell")

    def test_two_members_naming_one_id_are_refused(self):
        with self.assertRaises(r.JobError) as caught:
            self.add({"ticket": 19, "command": ["true"], "array_id": "sweep",
                      "members": [{"id": "same"}, {"id": "same"}]})
        self.assertIn("same", str(caught.exception))
        self.assertEqual(self.jobs(), ["j-0001", "j-0002"])

    def test_a_job_id_that_already_has_a_file_is_refused_rather_than_overwritten(self):
        self.add({"id": "once", "ticket": 19, "command": ["true"]})
        with self.assertRaises(r.JobError):
            self.add({"id": "once", "ticket": 19, "command": ["false"]})
        self.assertEqual(self.read("once")["command"], ["true"], "the first job's file is untouched")

    def test_a_string_where_a_list_belongs_is_refused_and_not_split_into_characters(self):
        for spec, complaint in (
            ({"command": "python train.py"}, "command"),
            ({"command": ["true"], "expected_outputs": "results/summary.json"}, "expected_outputs"),
            ({"command": ["true"], "devices": {"gpu_uuids": "GPU-0095fb8d"}}, "gpu_uuids"),
            ({"command": ["true"], "devices": {"cores": "8-9"}}, "cores"),
        ):
            with self.subTest(field=complaint):
                with self.assertRaises(r.JobError) as caught:
                    self.add(dict(spec, ticket=19))
                self.assertIn(complaint, str(caught.exception))
        self.assertEqual(self.jobs(), ["j-0001", "j-0002"])

    def test_a_field_of_the_wrong_shape_is_a_complaint_and_never_a_traceback(self):
        for spec in (
            {"command": ["true"], "devices": {"cores": [8, "nine"]}},
            {"command": ["true"], "devices": {"ram_gb": "lots"}},
            {"command": ["true"], "env": ["SEED=1"]},
            {"command": ["true"], "wallclock_minutes": "90"},
            {"command": ["true"], "retry": {"gpu_oom": ["--batch-size 16"]}},
            {"command": ["true"], "retry": {"ladder": []}},
            {"command": ["true"], "ticket": "nineteen"},
        ):
            with self.subTest(spec=spec):
                with self.assertRaises(r.JobError):
                    self.add(dict(spec, ticket=spec.get("ticket", 19)))

    def test_a_retry_ladder_of_override_objects_is_kept(self):
        record = self.add({"ticket": 19, "command": ["true"],
                           "retry": {"gpu_oom": [{"--batch-size": 16}, {"--batch-size": 8}]}})[0]
        self.assertEqual(record["retry"], {"host_oom": [], "gpu_oom": [{"--batch-size": 16}, {"--batch-size": 8}]})


class JobVerbTest(ProjectTestCase):
    """`wayline job add` as a worker runs it: the spec on stdin, the project in the environment."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()

    def run_verb(self, spec, args=("add",), env=None):
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home), PYTHONPATH=str(HARNESS_ROOT))
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, "-m", "wayline", "job", *args], input=json.dumps(spec), text=True,
            capture_output=True, cwd=str(HARNESS_ROOT), env=environment,
        )

    def test_the_spec_arrives_on_stdin_and_the_project_in_the_environment(self):
        done = self.run_verb({"command": ["python", "train.py"]},
                             env={"WAYLINE_PROJECT": str(self.project), "WAYLINE_TICKET": "19"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("t19-1", done.stdout)
        record = json.loads((self.project / "research" / "jobs" / "t19-1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["ticket"], 19)

    def test_a_spec_file_works_too(self):
        path = self.temp / "spec.json"
        path.write_text(json.dumps({"ticket": 19, "command": ["true"]}), encoding="utf-8")
        done = self.run_verb({}, args=("add", str(path)), env={"WAYLINE_PROJECT": str(self.project)})
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_spec_that_is_not_json_exits_1_with_the_complaint(self):
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home), PYTHONPATH=str(HARNESS_ROOT),
                           WAYLINE_PROJECT=str(self.project), WAYLINE_TICKET="19")
        done = subprocess.run([sys.executable, "-m", "wayline", "job", "add"], input="not json", text=True,
                              capture_output=True, cwd=str(HARNESS_ROOT), env=environment)
        self.assertEqual(done.returncode, 1)
        self.assertIn("not readable JSON", done.stderr)

    def test_a_refused_spec_exits_1(self):
        done = self.run_verb({"command": ["true"], "nonsense": 1},
                             env={"WAYLINE_PROJECT": str(self.project), "WAYLINE_TICKET": "19"})
        self.assertEqual(done.returncode, 1)
        self.assertIn("nonsense", done.stderr)

    def test_a_malformed_field_is_a_one_line_complaint_and_never_a_traceback(self):
        for spec in ({"command": ["true"], "devices": {"cores": "8-9"}},
                     {"command": "python train.py"},
                     {"command": ["true"], "wallclock_minutes": 0}):
            with self.subTest(spec=spec):
                done = self.run_verb(spec, env={"WAYLINE_PROJECT": str(self.project), "WAYLINE_TICKET": "19"})
                self.assertEqual(done.returncode, 1)
                self.assertNotIn("Traceback", done.stderr)
                self.assertTrue(done.stderr.startswith("wayline job add: "), done.stderr)
                self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    def test_the_verb_is_built_and_in_the_overview(self):
        from wayline import cli

        verb = cli.lookup("job")
        self.assertIsNotNone(verb.handler, "wayline job is built")
        self.assertIn("job add [<file>]", cli.overview())


if __name__ == "__main__":
    unittest.main()
