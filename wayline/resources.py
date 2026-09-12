"""Resources and jobs (Implementation Decisions 6, 14; research-notes 05 A1 to A5, A8).

Two things decision 6 keeps together, and this module with them. The harness reads what the
workstation has (GPU, cores, load, RAM, disk), subtracts the owner's reservation, and hands out
slots by the free-slot rule so a job never starves the machine it runs on. And the job runner
seam (Testing Decisions seam 2): `JobRunner.launch/poll/kill/cleanup` over a `JobSpec`, with the
`systemd_run`, `setsid`, and `fake` backends, so a detached job is launched pinned to its devices,
polled by code, and told apart on failure. The conductor and the resource manager see only a
`JobState`; which backend answered is the job file's business.

Every live reading goes through a module-level path or command so a test can point it at fixture
data instead of the real box. The only thing written here is `jobs/<id>.json`, through the ledger
(Implementation Decisions 2), because a job's exit code and duration are of no use to anyone who
cannot read them back after the session that launched it is gone.
"""

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger, LedgerError, now_ts

__all__ = [
    "ResourceError", "GPU_OOM_SIGNATURES",
    "read_gpus", "read_gpu_processes", "sample_gpu_utilization",
    "read_loadavg1", "read_cpu_pressure", "read_mem_available_bytes", "read_disk_avail_bytes",
    "pids_by_name", "process_cores", "process_reservation",
    "Reservation", "reservation_from_harness",
    "gpu_free", "cpu_slot_free", "ram_free", "core_pool", "CoreAllocator",
    "gpu_slots_view", "cpu_slot_view", "ram_slot_view", "snapshot", "render_resources",
    "JobError", "JOB_STATES", "JobState", "JobSpec", "JobHandle",
    "unit_name", "unit_argument", "systemd_run_argv", "setsid_argv", "parse_show", "decode_show", "decode_exit",
    "log_tail", "gpu_oom_in", "resolve_gpu_indices", "job_record", "spec_from_record", "handle_for",
    "SystemdRun", "Setsid", "FakeJobs", "SYSTEMD_RUN", "SETSID", "FAKE_JOBS",
    "user_manager_reachable", "jobs_backend", "use_fake_jobs", "JobRunner", "add_jobs", "job_command",
]

# --- paths and commands, overridable by tests -------------------------------------------------

PROC_LOADAVG = Path("/proc/loadavg")
PROC_MEMINFO = Path("/proc/meminfo")
PROC_PRESSURE_CPU = Path("/proc/pressure/cpu")
PROC_DIR = Path("/proc")
DISK_PATH = "/home"

GPU_QUERY_FIELDS = "index,uuid,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory"
COMPUTE_APPS_FIELDS = "pid,used_memory"

DEFAULT_GPU_UTIL_FREE_BELOW = 20
DEFAULT_GPU_UTIL_SAMPLES = 2
DEFAULT_GPU_SAMPLE_INTERVAL_S = 0.2

# The OOM signature table (Implementation Decisions 6): a GPU OOM's last 64 KB of log holds one of
# these; a plain `Result=oom-kill` with an empty log is a host RAM kill instead.
GPU_OOM_SIGNATURES = (
    "CUDA out of memory",
    "torch.OutOfMemoryError",
    "torch.cuda.OutOfMemoryError",
    "CUDA_ERROR_OUT_OF_MEMORY",
    "cudaErrorMemoryAllocation",
    "RESOURCE_EXHAUSTED",
    "CUBLAS_STATUS_ALLOC_FAILED",
    "CUDNN_STATUS_ALLOC_FAILED",
)


class ResourceError(RuntimeError):
    """A detection query or an allocator call the harness could not honor."""


# --- detection ----------------------------------------------------------------------------------


def read_gpus():
    """One `nvidia-smi --query-gpu` reading per GPU; `[]` when nvidia-smi is absent (CPU-only degrade)."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=" + GPU_QUERY_FIELDS, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return []
    if done.returncode != 0:
        return []
    gpus = []
    for line in done.stdout.splitlines():
        if not line.strip():
            continue
        index, uuid, total, used, free, util_gpu, util_mem = (part.strip() for part in line.split(","))
        gpus.append({
            "index": int(index),
            "uuid": uuid,
            "memory_total_mib": int(total),
            "memory_used_mib": int(used),
            "memory_free_mib": int(free),
            "utilization_gpu": int(util_gpu),
            "utilization_memory": int(util_mem),
        })
    return gpus


def read_gpu_processes():
    """Per-process GPU memory via `nvidia-smi --query-compute-apps`; `[]` when there are none, or no nvidia-smi."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=" + COMPUTE_APPS_FIELDS, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return []
    if done.returncode != 0:
        return []
    processes = []
    for line in done.stdout.splitlines():
        if not line.strip():
            continue
        pid, used_memory = (part.strip() for part in line.split(","))
        processes.append({"pid": int(pid), "used_memory_mib": int(used_memory)})
    return processes


def sample_gpu_utilization(n=DEFAULT_GPU_UTIL_SAMPLES, interval_s=DEFAULT_GPU_SAMPLE_INTERVAL_S, sleep=time.sleep, read=read_gpus):
    """`n` consecutive GPU readings, most recent last; stops early once a reading comes back empty.

    The free-slot rule needs `utilization.gpu` under the threshold "for two consecutive samples"
    (research-notes 05 A8); this is where those samples come from. `read` and `sleep` are
    parameters so a test can supply canned readings without touching nvidia-smi or the clock.
    """
    samples = []
    for index in range(max(1, n)):
        reading = read()
        samples.append(reading)
        if not reading:
            break
        if index + 1 < n:
            sleep(interval_s)
    return samples


def read_loadavg1(path=PROC_LOADAVG):
    """The 1-minute run-queue average, field 1 of `/proc/loadavg` (proc_loadavg(5))."""
    return float(Path(path).read_text(encoding="utf-8").split()[0])


def read_cpu_pressure(path=PROC_PRESSURE_CPU):
    """PSI `some avg10` from `/proc/pressure/cpu` as a percentage, or `None` when PSI is unavailable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("some "):
            for field_ in line.split():
                if field_.startswith("avg10="):
                    return float(field_.split("=", 1)[1])
    return None


def read_mem_available_bytes(path=PROC_MEMINFO):
    """`MemAvailable` from `/proc/meminfo`, converted from kB to bytes."""
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ResourceError("MemAvailable not found in %s" % path)


def read_disk_avail_bytes(path=DISK_PATH):
    """Free bytes at `path` via `df -B1 --output=avail`."""
    done = subprocess.run(["df", "-B1", "--output=avail", str(path)], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise ResourceError("df %s failed: %s" % (path, done.stderr.strip()))
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if not lines:
        raise ResourceError("df %s produced no output" % path)
    return int(lines[-1])


# --- the reservation ------------------------------------------------------------------------------


def _proc_comm(pid, proc_dir=PROC_DIR):
    try:
        return (Path(proc_dir) / str(pid) / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def pids_by_name(names, proc_dir=PROC_DIR):
    """pid -> comm for every running process whose `/proc/<pid>/comm` matches one of `names`."""
    wanted = set(names)
    if not wanted:
        return {}
    matches = {}
    proc_dir = Path(proc_dir)
    if not proc_dir.is_dir():
        return matches
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        comm = _proc_comm(entry.name, proc_dir=proc_dir)
        if comm in wanted:
            matches[int(entry.name)] = comm
    return matches


def process_cores(pid):
    """The CPU set a running process is pinned to, or `set()` once it has exited or affinity is unreadable."""
    try:
        return set(os.sched_getaffinity(pid))
    except (ProcessLookupError, OSError, AttributeError):
        return set()


def process_reservation(names, gpu_processes=None, proc_dir=PROC_DIR):
    """The GPU memory (MiB) and CPU cores the owner's listed `processes` hold right now.

    Implementation Decisions 6: "the GPU memory and cores of a listed process count as reserved."
    `gpu_processes` defaults to a live `read_gpu_processes()` reading; a test passes canned rows.
    """
    gpu_processes = read_gpu_processes() if gpu_processes is None else gpu_processes
    pids = pids_by_name(names, proc_dir=proc_dir)
    reserved_gpu_mib = sum(entry["used_memory_mib"] for entry in gpu_processes if entry["pid"] in pids)
    reserved_cores = set()
    for pid in pids:
        reserved_cores |= process_cores(pid)
    return reserved_gpu_mib, frozenset(reserved_cores)


@dataclass(frozen=True)
class Reservation:
    """The owner's carve-out: the fixed base plus what the listed processes hold at read time."""

    gpu_indices: frozenset = field(default_factory=frozenset)
    cores: frozenset = field(default_factory=frozenset)
    ram_bytes: int = 0
    extra_gpu_mib: int = 0


def reservation_from_harness(harness, gpu_processes=None, proc_dir=PROC_DIR):
    """The `Reservation` a project's `harness.json.reservations` describes, live processes folded in."""
    settings = (harness or {}).get("reservations", {}) or {}
    base_cores = set(range(int(settings.get("cores", 0))))
    extra_gpu_mib, extra_cores = process_reservation(settings.get("processes", []) or [], gpu_processes=gpu_processes, proc_dir=proc_dir)
    return Reservation(
        gpu_indices=frozenset(settings.get("gpu", []) or []),
        cores=frozenset(base_cores | extra_cores),
        ram_bytes=int(float(settings.get("ram_gb", 0)) * (1024 ** 3)),
        extra_gpu_mib=extra_gpu_mib,
    )


# --- the free-slot rule (research-notes 05 A8) -----------------------------------------------------


def gpu_free(gpu, utilization_samples, held, need_mib=0, reserve_mib=0, util_threshold=DEFAULT_GPU_UTIL_FREE_BELOW):
    """A GPU slot is free: enough memory, low utilization for two consecutive samples, and unheld."""
    if held:
        return False
    if gpu["memory_free_mib"] < need_mib + reserve_mib:
        return False
    if len(utilization_samples) < 2:
        return False
    return all(sample < util_threshold for sample in utilization_samples[-2:])


def cpu_slot_free(loadavg1, cores_needed, nproc, reserved_cores_count, allocator):
    """A CPU slot is free: the load headroom exists, and the allocator can actually supply the cores."""
    if loadavg1 + cores_needed > nproc - reserved_cores_count:
        return False
    return len(allocator.free) >= cores_needed


def ram_free(mem_available_bytes, reserved_bytes, running_ram_bytes, need_bytes):
    """RAM is free when what's available, less the reservation and every running job's share, covers `need`."""
    return mem_available_bytes - reserved_bytes - running_ram_bytes >= need_bytes


def core_pool(nproc, reserved_cores, running_cores):
    """The unreserved, currently idle cores a fresh `CoreAllocator` may hand out."""
    return sorted(set(range(nproc)) - set(reserved_cores) - set(running_cores))


class CoreAllocator:
    """Hands out and returns core ranges per job from a pool that never includes the reserved cores.

    `allocate` tries a contiguous range first (kinder to cache locality) and falls back to any
    combination of free cores when the pool is fragmented, matching "a contiguous or listed range
    from the unreserved pool" (research-notes 05 A8).
    """

    def __init__(self, pool):
        self._free = sorted(set(pool))
        self._held = {}

    @property
    def free(self):
        return list(self._free)

    def held(self, job_id):
        return self._held.get(job_id)

    def allocate(self, job_id, count):
        if job_id in self._held:
            raise ResourceError("job %r already holds cores %s" % (job_id, self._held[job_id]))
        if count <= 0:
            raise ResourceError("a job must ask for at least one core, got %r" % (count,))
        free_set = set(self._free)
        for start in self._free:
            window = list(range(start, start + count))
            if all(core in free_set for core in window):
                self._take(job_id, window)
                return self._held[job_id]
        if len(self._free) >= count:
            self._take(job_id, self._free[:count])
            return self._held[job_id]
        return None

    def _take(self, job_id, cores):
        for core in cores:
            self._free.remove(core)
        self._held[job_id] = tuple(sorted(cores))

    def release(self, job_id):
        cores = self._held.pop(job_id, None)
        if cores:
            self._free = sorted(set(self._free) | set(cores))
        return cores


# --- the view `wayline status` renders (Implementation Decisions 6, 14) -----------------------------


def gpu_slots_view(samples, jobs, reservation, need_mib=0, util_threshold=DEFAULT_GPU_UTIL_FREE_BELOW):
    """Each GPU's held/free state across `samples` (>=1 readings from `sample_gpu_utilization`)."""
    if not samples or not samples[-1]:
        return []
    held_indices = {index for job in jobs for index in job["devices"]["gpu_indices"]}
    slots = []
    for gpu in samples[-1]:
        history = [
            next((reading["utilization_gpu"] for reading in sample if reading["uuid"] == gpu["uuid"]), None)
            for sample in samples
        ]
        history = [value for value in history if value is not None]
        held_by_job = gpu["index"] in held_indices
        held_by_reservation = gpu["index"] in reservation.gpu_indices
        slots.append({
            **gpu,
            "held": held_by_job or held_by_reservation,
            "held_by": "job" if held_by_job else ("reservation" if held_by_reservation else None),
            "utilization_samples": history,
            "free": gpu_free(gpu, history, held_by_job or held_by_reservation, need_mib=need_mib,
                              reserve_mib=reservation.extra_gpu_mib, util_threshold=util_threshold),
        })
    return slots


def cpu_slot_view(loadavg1, nproc, reservation, jobs, pressure_avg10=None):
    """Cores in use, reserved, and free, plus whether headroom remains for at least one more core.

    `pressure_avg10` (PSI `some avg10`, research-notes 05 A8) rides along for `status` to show; the
    free-slot rule itself is `loadavg1` against `nproc`, not PSI.
    """
    running_cores = sorted({core for job in jobs for core in job["devices"]["cores"]})
    free_cores = core_pool(nproc, reservation.cores, running_cores)
    return {
        "loadavg1": loadavg1,
        "pressure_avg10": pressure_avg10,
        "nproc": nproc,
        "reserved_cores": sorted(reservation.cores),
        "cores_in_use": running_cores,
        "free_cores": free_cores,
        "free": cpu_slot_free(loadavg1, 1, nproc, len(reservation.cores), CoreAllocator(free_cores)),
    }


def ram_slot_view(mem_available_bytes, reservation, jobs):
    """RAM committed by running jobs, and what's left over the reservation."""
    committed_bytes = sum(int(job["devices"]["ram_gb"] * (1024 ** 3)) for job in jobs)
    return {
        "mem_available_bytes": mem_available_bytes,
        "reserved_bytes": reservation.ram_bytes,
        "committed_bytes": committed_bytes,
        "free_bytes": mem_available_bytes - reservation.ram_bytes - committed_bytes,
    }


def snapshot(harness, jobs, gpu_util_free_below=DEFAULT_GPU_UTIL_FREE_BELOW, gpu_util_samples=DEFAULT_GPU_UTIL_SAMPLES,
             sample_interval_s=DEFAULT_GPU_SAMPLE_INTERVAL_S, disk_path=DISK_PATH):
    """Everything `wayline status` needs: live readings, the reservation, and every slot's state.

    `jobs` are the running job records (schema `job`, `project.LIVE_JOB_STATUSES`); a job holds a
    GPU whole through its `devices.gpu_indices` and commits cores and RAM through the rest of
    `devices`. Raises `ResourceError` (or an `OSError` from a `/proc` read) only for a reading the
    box genuinely cannot produce; a missing GPU is a normal CPU-only degrade, not an error.
    """
    gpu_processes = read_gpu_processes()
    reservation = reservation_from_harness(harness, gpu_processes=gpu_processes)
    samples = sample_gpu_utilization(n=gpu_util_samples, interval_s=sample_interval_s)
    nproc = os.cpu_count() or 1
    loadavg1 = read_loadavg1()
    pressure_avg10 = read_cpu_pressure()
    mem_available = read_mem_available_bytes()
    disk_avail = read_disk_avail_bytes(disk_path)
    settings = (harness or {}).get("reservations", {}) or {}
    return {
        "gpus": gpu_slots_view(samples, jobs, reservation, util_threshold=gpu_util_free_below),
        "cpu": cpu_slot_view(loadavg1, nproc, reservation, jobs, pressure_avg10=pressure_avg10),
        "ram": ram_slot_view(mem_available, reservation, jobs),
        "disk_avail_bytes": disk_avail,
        "reservation": {
            "gpu_indices": sorted(reservation.gpu_indices),
            "cores": sorted(reservation.cores),
            "ram_gb": settings.get("ram_gb", 0),
            "processes": list(settings.get("processes", []) or []),
            "extra_gpu_mib": reservation.extra_gpu_mib,
        },
    }


def render_resources(view):
    """The lines `wayline status` adds for the slots and the reservation."""
    reservation = view["reservation"]
    lines = ["reservation  gpu %s   cores %s   ram %sGB   processes %s" % (
        reservation["gpu_indices"] or "none",
        _range_text(reservation["cores"]) or "none",
        _number(reservation["ram_gb"]),
        ", ".join(reservation["processes"]) or "none",
    )]
    cpu = view["cpu"]
    pressure = "" if cpu.get("pressure_avg10") is None else "   psi %s%%" % _number(cpu["pressure_avg10"])
    lines.append("cpu slot     loadavg1 %s / %d   cores in use %s   free %s   %s%s" % (
        _number(cpu["loadavg1"]), cpu["nproc"], _range_text(cpu["cores_in_use"]) or "none",
        _range_text(cpu["free_cores"]) or "none", "free" if cpu["free"] else "full", pressure,
    ))
    ram = view["ram"]
    lines.append("ram slot     available %s   committed %s   free %s" % (
        _gib(ram["mem_available_bytes"]), _gib(ram["committed_bytes"]), _gib(ram["free_bytes"]),
    ))
    if not view["gpus"]:
        lines.append("gpu slots    none detected (CPU-only)")
    for gpu in view["gpus"]:
        state = "held (%s)" % gpu["held_by"] if gpu["held"] else "free" if gpu["free"] else "busy"
        lines.append("gpu slot %-2d  %s   %d/%d MiB free   util %s%%   %s" % (
            gpu["index"], gpu["uuid"], gpu["memory_free_mib"], gpu["memory_total_mib"],
            ",".join(str(sample) for sample in gpu["utilization_samples"]) or "?", state,
        ))
    return lines


def _range_text(cores):
    """A sorted core list as ranges: `[0, 1, 2, 5]` renders `0-2,5`."""
    cores = sorted(cores)
    if not cores:
        return ""
    ranges, start, previous = [], cores[0], cores[0]
    for core in cores[1:]:
        if core == previous + 1:
            previous = core
            continue
        ranges.append((start, previous))
        start = previous = core
    ranges.append((start, previous))
    return ",".join("%d" % lo if lo == hi else "%d-%d" % (lo, hi) for lo, hi in ranges)


def _gib(value):
    return "%.1fGB" % (value / (1024 ** 3))


def _number(value):
    if isinstance(value, float):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value)


# --- the job runner seam: the vocabulary (Implementation Decisions 6; Testing Decisions seam 2) ---

# The states the conductor and the resource manager see. A job file's status carries one more,
# `pending`, which is what a job file written before its launch says; no poll returns it.
JOB_STATES = ("running", "exited", "oom_host", "oom_gpu", "failed", "killed", "gone")

# The job file statuses that mean a job is still on the machine, holding its slot.
LIVE_JOB_STATUSES = ("pending", "running")

UNIT_PREFIX = "wayline-job-"
JOB_SLICE = "wayline-jobs"
SHOW_PROPERTIES = "LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus"
STOP_TIMEOUT_S = 30  # `TimeoutStopSec`: a hung job cannot hold a slot for systemd's 90 s default
OOM_LOG_TAIL_BYTES = 65536  # `policy.jobs.oom_log_tail_bytes`; the OOM grep reads no more
DEFAULT_WALLCLOCK_MINUTES = 180  # the large budget's wallclock (Implementation Decisions 14)
POLL_INTERVAL_S = 1.0

# The `ActiveState` values that mean the job has not reached its final state yet. `SubState=exited`
# under `active` is the `--remain-after-exit` success (research-notes 05 R2) and is not one of them.
RUNNING_ACTIVE_STATES = ("activating", "active", "reloading", "refreshing", "deactivating")

# The signals a wayline kill sends, as the `setsid` backend's exit file reports them. Under
# `systemd_run` the manager records a SIGTERM exit as `Result=success` (systemd.exec(5) Table 6),
# which is why a cancelled job's `killed` status comes from the kill and not from a later poll.
KILL_EXIT_CODES = {128 + int(signal.SIGTERM): "SIGTERM", 128 + int(signal.SIGKILL): "SIGKILL"}

EXIT_FILE_SUFFIX = ".exit"
PID_FILE_SUFFIX = ".pid"


class JobError(ResourceError):
    """A job the runner refuses to launch, or a backend call it could not make at all.

    A job that failed is not an error: that is a `JobState`. This is for a spec the runner cannot
    honor (a relative path, a uuid this box does not have) and for a manager it cannot reach.
    """


@dataclass(frozen=True)
class JobState:
    """What a poll decoded: one of `JOB_STATES`, with the evidence that named it.

    `result` is the manager's `Result=` value (or the fallback's decoding), `exit_code` the main
    process's status, `reason` the short phrase a report prints, and `log_tail` the bytes the OOM
    rule read, carried only when a failure made them worth carrying.
    """

    name: str
    result: str = None
    exit_code: int = None
    reason: str = None
    log_tail: str = None

    def __post_init__(self):
        if self.name not in JOB_STATES:
            raise JobError("%r is not a job state; the states are %s" % (self.name, ", ".join(JOB_STATES)))

    @property
    def terminal(self):
        """Whether the machine is done with this job: every state but `running`."""
        return self.name != "running"

    @property
    def oom(self):
        """The job file's `oom` field: `host`, `gpu`, or None."""
        return {"oom_host": "host", "oom_gpu": "gpu"}.get(self.name)

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class JobSpec:
    """What a job needs to run: the argv, where, on what, and for how long.

    The fields are the job file's, minus what only a launch knows (`backend`, `unit`, the resolved
    `gpu_indices`, the attempts). GPUs are named by uuid because an index changes at boot
    (research-notes 05 A8).
    """

    id: str
    ticket: int
    command: tuple
    cwd: str
    log: str
    array: str = None
    env: dict = field(default_factory=dict)
    gpu_uuids: tuple = ()
    cores: tuple = ()
    ram_gb: float = 0.0
    expected_outputs: tuple = ()
    retry: dict = field(default_factory=lambda: {"host_oom": [], "gpu_oom": []})
    wallclock_minutes: int = DEFAULT_WALLCLOCK_MINUTES

    def check(self):
        """Refuse a spec no backend could honor, before anything is launched or written."""
        if not self.id or not isinstance(self.id, str):
            raise JobError("a job needs an id")
        if not isinstance(self.command, (list, tuple)) or not self.command:
            raise JobError("job %s has no command; a job is an argv" % self.id)
        # `WorkingDirectory=` and `StandardOutput=append:` both want an absolute path
        # (systemd.exec(5)), and a relative one means something different in every cwd.
        for name in ("cwd", "log"):
            value = getattr(self, name)
            if not value or not Path(value).is_absolute():
                raise JobError("job %s: %s is an absolute path, got %r" % (self.id, name, value))
        if int(self.wallclock_minutes) < 1:
            raise JobError("job %s: wallclock_minutes is at least 1, got %r" % (self.id, self.wallclock_minutes))
        return self


@dataclass(frozen=True)
class JobHandle:
    """What `poll`, `kill`, and `cleanup` need; `handle_for` builds one back out of a job file."""

    id: str
    backend: str
    log: str
    cwd: str
    unit: str = None
    pid: int = None
    gpu_indices: tuple = ()
    cores: tuple = ()
    started_at: str = None

    @property
    def state_dir(self):
        """Where the `setsid` backend keeps its `.exit` and `.pid` files: beside the log.

        research-notes 05 A5 puts them in the jobs directory; that directory is under `research/`,
        which only the ledger writes (Implementation Decisions 2), so they live next to the log
        instead, the one directory a job already writes into.
        """
        return Path(self.log).parent

    @property
    def exit_file(self):
        return self.state_dir / (self.id + EXIT_FILE_SUFFIX)

    @property
    def pid_file(self):
        return self.state_dir / (self.id + PID_FILE_SUFFIX)


def unit_name(job_id):
    """`wayline-job-<id>.service`: the unit name is the job id (research-notes 05 A1).

    This is the poll line's spelling. `--unit=` on the launch line takes the name without the
    suffix, which `systemd-run` appends itself, and `unit_argument` is that spelling.
    """
    return "%s%s.service" % (UNIT_PREFIX, job_id)


def unit_argument(unit_or_id):
    """The `--unit=` value: the unit name without the `.service` the manager appends."""
    text = str(unit_or_id)
    if text.endswith(".service"):
        text = text[: -len(".service")]
    return text if text.startswith(UNIT_PREFIX) else UNIT_PREFIX + text


# --- the launch lines (research-notes 05 A1 and A5) ------------------------------------------------


def systemd_run_argv(spec, gpu_indices=(), unit=None):
    """The launch line of Implementation Decisions 6, in its order, as an argv.

    Never `--collect`: it sets `CollectMode=inactive-or-failed`, which unloads a failed unit
    before the poller reads it, so a job that exited 3 or was OOM killed reads back as
    `Result=success` (research-notes 05 D1, R3, R4). `--remain-after-exit` is what makes success
    observable at all, and `--expand-environment=no` keeps the manager out of the command's `$`.
    """
    argv = [
        "systemd-run", "--user", "--unit=" + unit_argument(unit or spec.id), "--slice=" + JOB_SLICE,
        "--remain-after-exit", "--expand-environment=no",
    ]
    if spec.cores:
        # `CPUAffinity` and not `AllowedCPUs`: the user manager here is delegated only
        # `cpu memory pids`, so the cpuset controller is unavailable (research-notes 05 R5).
        argv += ["-p", "CPUAffinity=" + _range_text(spec.cores)]
    if spec.ram_gb:
        argv += ["-p", "MemoryMax=%d" % int(float(spec.ram_gb) * (1024 ** 3))]
    argv += [
        "-p", "MemorySwapMax=0",
        "-p", "TimeoutStopSec=%d" % STOP_TIMEOUT_S,
        "-p", "RuntimeMaxSec=%d" % (int(spec.wallclock_minutes) * 60),
        "-p", "WorkingDirectory=" + spec.cwd,
        "-p", "StandardOutput=append:" + spec.log,
        "-p", "StandardError=append:" + spec.log,
        "-E", "CUDA_VISIBLE_DEVICES=" + ",".join(str(index) for index in gpu_indices),
        "-E", "PYTHONUNBUFFERED=1",
    ]
    for key in sorted(spec.env):
        argv += ["-E", "%s=%s" % (key, spec.env[key])]
    return argv + [str(part) for part in spec.command]


def setsid_argv(spec, gpu_indices=(), exit_file=None):
    """The fallback launch line of research-notes 05 A5, as an argv the harness can start itself.

    The note's `&` and `$!` are this backend's own: started without a new session the child is
    outside no process group of its own, so `setsid` execs in place and its pid is the group
    leader's, which is what `kill -- -<pid>` needs and what the pid file records.
    """
    environment = ["CUDA_VISIBLE_DEVICES=" + ",".join(str(index) for index in gpu_indices), "PYTHONUNBUFFERED=1"]
    environment += ["%s=%s" % (key, spec.env[key]) for key in sorted(spec.env)]
    argv = ["setsid", "nohup", "env"] + environment
    if spec.cores:
        argv += ["taskset", "-c", _range_text(spec.cores)]
    command = " ".join(shlex.quote(str(part)) for part in spec.command)
    target = Path(exit_file) if exit_file is not None else Path(spec.log).parent / (spec.id + EXIT_FILE_SUFFIX)
    return argv + ["sh", "-c", "%s; echo $? > %s" % (command, shlex.quote(str(target)))]


# --- the poll and the decode table (research-notes 05 A2 and A3) -----------------------------------


def parse_show(text):
    """`systemctl show -p ...` output as a dict: the format is one `KEY=VALUE` per line."""
    fields = {}
    for line in (text or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def log_tail(path, limit=OOM_LOG_TAIL_BYTES):
    """The last `limit` bytes of a log, decoded leniently; an absent or unreadable log is empty."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - int(limit)))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def gpu_oom_in(text):
    """The signature of `GPU_OOM_SIGNATURES` a log tail carries, or None."""
    for signature in GPU_OOM_SIGNATURES:
        if signature in (text or ""):
            return signature
    return None


def decode_show(fields, tail=""):
    """One `systemctl show` reading as a `JobState`, by the table of research-notes 05 A2.

    `tail` is the last bytes of the job's log, which the OOM rule of A3 needs in the `exit-code`
    branch alone: GPU memory is invisible to cgroups, so a CUDA OOM arrives as a framework's
    message in the log and an ordinary nonzero exit in the unit.
    """
    load = fields.get("LoadState")
    active = fields.get("ActiveState")
    sub = fields.get("SubState")
    result = fields.get("Result")
    code = _int_or_none(fields.get("ExecMainCode"))
    status = _int_or_none(fields.get("ExecMainStatus"))
    if load == "not-found":
        # Never infer success: the unit was never launched, or cleanup has already unloaded it.
        return JobState("gone", result=result, reason="the unit is not loaded; read the job file and the log")
    if active in RUNNING_ACTIVE_STATES and sub != "exited":
        return JobState("running", result=result)
    if result == "oom-kill":
        # The host memory cgroup (`MemoryMax`) or systemd-oomd. The log is empty: SIGKILL.
        return JobState("oom_host", result=result, exit_code=status, reason="the host memory cgroup killed it")
    if result == "timeout":
        return JobState("failed", result=result, exit_code=status, reason="wallclock")
    if result == "exit-code":
        signature = gpu_oom_in(tail)
        if signature:
            return JobState("oom_gpu", result=result, exit_code=status,
                            reason="the log carries %r" % signature, log_tail=tail)
        return JobState("failed", result=result, exit_code=status,
                        reason="exited %s" % status, log_tail=tail or None)
    if result == "signal":
        if status == int(signal.SIGKILL):
            return JobState("killed", result=result, exit_code=status, reason="SIGKILL and no oom-kill")
        return JobState("failed", result=result, exit_code=status, reason="signal %s" % status)
    if result == "success":
        # `active/exited` under `--remain-after-exit` (R2), or `inactive` after a stop, whose
        # SIGTERM exit systemd counts as success (systemd.exec(5) Table 6). `ExecMainCode` is the
        # wait(2) class of the main process, and 0 means the manager recorded none: the unit is
        # loaded but its process has not run, which is not an exit 0 to go looking for outputs of.
        if code == 0:
            return JobState("running", result=result, reason="loaded, with no main process status yet")
        return JobState("exited", result=result, exit_code=status if status is not None else 0)
    if result is None:
        raise JobError("the poll output carries no Result; the user manager did not answer (%r)" % fields)
    # protocol, core-dump, watchdog, start-limit-hit, resources (systemd.exec(5) Table 5).
    return JobState("failed", result=result, exit_code=status, reason=result)


def decode_exit(code, tail=""):
    """The `setsid` fallback's exit file as a `JobState`.

    What it cannot see, because there is no manager and no cgroup: a host OOM kill, which lives in
    `dmesg` and needs root here (research-notes 05 A5). A host OOM arrives as `failed`.
    """
    code = int(code)
    if code == 0:
        return JobState("exited", result="success", exit_code=0)
    if code in KILL_EXIT_CODES:
        return JobState("killed", result="signal", exit_code=code, reason=KILL_EXIT_CODES[code])
    signature = gpu_oom_in(tail)
    if signature:
        return JobState("oom_gpu", result="exit-code", exit_code=code,
                        reason="the log carries %r" % signature, log_tail=tail)
    return JobState("failed", result="exit-code", exit_code=code, reason="exited %d" % code, log_tail=tail or None)


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --- the backends -----------------------------------------------------------------------------------


def _run(argv):
    """Run one short command and hand back its result; a missing executable is a `JobError`."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as failure:
        raise JobError("%s could not be run: %s" % (argv[0], failure)) from None


def _prepare(spec):
    """Make the log's directory, and refuse a cwd that is not there: systemd would fail obscurely."""
    if not Path(spec.cwd).is_dir():
        raise JobError("job %s: cwd %s does not exist" % (spec.id, spec.cwd))
    Path(spec.log).parent.mkdir(parents=True, exist_ok=True)


class SystemdRun:
    """The real backend: the launch line of Implementation Decisions 6 under the user manager.

    Everything a poller needs is the manager's: the exit code, the `oom-kill` result, the wallclock
    expiry, and a cgroup-wide kill. `cleanup` is what unloads a unit, never `--collect`.
    """

    name = "systemd_run"

    def launch(self, spec, gpu_indices=()):
        spec.check()
        _prepare(spec)
        unit = unit_name(spec.id)
        self._clear_finished(spec, unit)
        done = _run(systemd_run_argv(spec, gpu_indices, unit=unit))
        if done.returncode != 0:
            raise JobError("systemd-run refused job %s: %s" % (spec.id, (done.stderr or done.stdout).strip()))
        return JobHandle(id=spec.id, backend=self.name, log=spec.log, cwd=spec.cwd, unit=unit,
                         gpu_indices=tuple(gpu_indices), cores=tuple(spec.cores), started_at=now_ts())

    def _clear_finished(self, spec, unit):
        """Unload a finished unit of the same id, because `systemd-run` refuses a loaded name.

        The footprint ladder relaunches the same job id (Implementation Decisions 6), and
        `--remain-after-exit` keeps the finished unit loaded until something unloads it, so a
        retry after a poll that did not clean up would be refused. A unit that is still running is
        another matter: relaunching a live job would double it, so that is refused here instead.
        """
        fields = parse_show(_run(["systemctl", "--user", "show", unit, "-p", SHOW_PROPERTIES]).stdout)
        if fields.get("LoadState") in (None, "", "not-found"):
            return
        if fields.get("ActiveState") in RUNNING_ACTIVE_STATES and fields.get("SubState") != "exited":
            raise JobError("job %s is already running as %s; poll or kill it before relaunching" % (spec.id, unit))
        self.cleanup(JobHandle(id=spec.id, backend=self.name, log=spec.log, cwd=spec.cwd, unit=unit))

    def poll(self, handle):
        unit = handle.unit or unit_name(handle.id)
        done = _run(["systemctl", "--user", "show", unit, "-p", SHOW_PROPERTIES])
        fields = parse_show(done.stdout)
        if "LoadState" not in fields:
            raise JobError("could not poll %s: %s" % (unit, (done.stderr or done.stdout).strip() or "no output"))
        tail = log_tail(handle.log) if fields.get("Result") == "exit-code" else ""
        return decode_show(fields, tail)

    def kill(self, handle, hard=False):
        """SIGTERM the whole cgroup (SIGKILL after `TimeoutStopSec`), or SIGKILL at once.

        An error is ignored, as research-notes 05 A4 says: a unit that is already gone is exactly
        what a kill wanted, and the reason for the nonzero exit is not worth a failure.
        """
        unit = handle.unit or unit_name(handle.id)
        argv = ["systemctl", "--user", "kill", "--signal=SIGKILL", unit] if hard else ["systemctl", "--user", "stop", unit]
        return _run(argv).returncode == 0

    def cleanup(self, handle):
        """Unload the unit once its result has been read: `reset-failed` for a failure, `stop` for a success."""
        unit = handle.unit or unit_name(handle.id)
        _run(["systemctl", "--user", "reset-failed", unit])
        _run(["systemctl", "--user", "stop", unit])
        return True

    def kill_all(self):
        """Stop the whole slice, which is every wayline job at once (research-notes 05 A4)."""
        return _run(["systemctl", "--user", "stop", JOB_SLICE + ".slice"]).returncode == 0


class Setsid:
    """The fallback backend, for a box with no reachable user manager (research-notes 05 A5).

    It loses `MemoryMax` and the `oom-kill` result, the cgroup-wide kill, and the manager's record
    of the exit status; the `.exit` file is the substitute and is missing when the shell itself was
    killed, which is why a job with neither an exit file nor a live pid reads `gone` and not
    `exited`. The job file records `backend: setsid` so a report can say which it was.
    """

    name = "setsid"

    def launch(self, spec, gpu_indices=()):
        spec.check()
        _prepare(spec)
        handle = JobHandle(id=spec.id, backend=self.name, log=spec.log, cwd=spec.cwd,
                           gpu_indices=tuple(gpu_indices), cores=tuple(spec.cores), started_at=now_ts())
        for stale in (handle.exit_file, handle.pid_file):
            stale.unlink(missing_ok=True)  # a relaunch must not read the last attempt's answer
        argv = setsid_argv(spec, gpu_indices, exit_file=handle.exit_file)
        try:
            with open(spec.log, "ab") as log:
                process = subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    cwd=spec.cwd, env=_child_env(spec, gpu_indices),
                )
        except OSError as failure:
            raise JobError("could not start job %s with setsid: %s" % (spec.id, failure)) from None
        handle = replace(handle, pid=process.pid)
        handle.pid_file.write_text("%d\n" % process.pid, encoding="utf-8")
        return handle

    def poll(self, handle):
        code = self._exit_code(handle)
        if code is not None:
            tail = log_tail(handle.log) if code != 0 else ""
            return decode_exit(code, tail)
        pid = self._pid(handle)
        if pid is not None and _pid_alive(pid):
            return JobState("running")
        return JobState("gone", reason="no exit file and no live pid; read the job file and the log")

    def kill(self, handle, hard=False):
        """Signal the process group `setsid` made, which is where the job's children are."""
        pid = self._pid(handle)
        if pid is None:
            return False
        try:
            os.killpg(pid, signal.SIGKILL if hard else signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        return True

    def cleanup(self, handle):
        for path in (handle.exit_file, handle.pid_file):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return True

    @staticmethod
    def _exit_code(handle):
        try:
            text = handle.exit_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return _int_or_none(text)

    @staticmethod
    def _pid(handle):
        if handle.pid is not None:
            return int(handle.pid)
        try:
            return _int_or_none(handle.pid_file.read_text(encoding="utf-8").strip())
        except OSError:
            return None


def _child_env(spec, gpu_indices):
    """The environment the fallback's child inherits; `env` sets the same names on the command line."""
    child = dict(os.environ)
    child["CUDA_VISIBLE_DEVICES"] = ",".join(str(index) for index in gpu_indices)
    child["PYTHONUNBUFFERED"] = "1"
    child.update({str(key): str(value) for key, value in spec.env.items()})
    return child


def _pid_alive(pid, proc_dir=PROC_DIR):
    """Whether the kernel still knows the pid; a pid we may not signal is alive (research-notes 05 A5).

    A zombie is not: the fallback's process group leader is a direct child of whatever launched
    it, and nothing reaps it, so `kill(pid, 0)` keeps succeeding for a job that is dead. Without
    this a killed job polls `running` forever and a `wait` never returns.
    """
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False
    return not _is_zombie(pid, proc_dir=proc_dir)


def _is_zombie(pid, proc_dir=PROC_DIR):
    """Whether `/proc/<pid>/status` says the process has exited and is waiting to be reaped."""
    try:
        text = (Path(proc_dir) / str(int(pid)) / "status").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        if line.startswith("State:"):
            return line.split()[1] == "Z"
    return False


@dataclass
class FakeJob:
    """One scripted job: the states a poll walks through, and what the job writes when it ends."""

    states: list
    outputs: dict = field(default_factory=dict)
    log: str = None
    job_id: str = None


class FakeJobs:
    """The fake backend: scripted `JobState` sequences, scripted outputs, and a scripted log.

    `script(states, outputs=, log=, job_id=)` queues one job. A `launch` takes the first entry
    whose `job_id` matches it (an entry without one matches any job), writes the scripted log, and
    every `poll` takes the next state, keeping the last once the sequence runs out, so a test walks
    a job from `running` to any of the seven states without a clock. The scripted outputs are
    written, relative to the job's cwd, when the first terminal state is reached, which is what
    lets the manifest and the retry ladder be tested: a state of `oom_gpu` writes no outputs and an
    `exited` writes them all.
    """

    name = "fake"

    def __init__(self):
        self.reset()

    def reset(self):
        self.queue = []
        self.calls = []  # (kind, job id) per call, in order, for assertions
        self.live = {}   # job id -> the remaining states, the outputs, and whether they were written

    def script(self, states, outputs=None, log=None, job_id=None):
        """Queue one job's answers. `states` are `JobState`s or the names of `JOB_STATES`."""
        if isinstance(states, (str, JobState)):
            states = [states]
        decoded = [state if isinstance(state, JobState) else JobState(str(state)) for state in states]
        if not decoded:
            raise JobError("a scripted fake job needs at least one state")
        entry = FakeJob(states=decoded, outputs=dict(outputs or {}), log=log, job_id=job_id)
        self.queue.append(entry)
        return entry

    def _take(self, spec):
        for index, entry in enumerate(self.queue):
            if entry.job_id is None or entry.job_id == spec.id:
                del self.queue[index]
                return entry
        raise JobError("the fake job runner has nothing scripted for job %s" % spec.id)

    def launch(self, spec, gpu_indices=()):
        spec.check()
        _prepare(spec)
        entry = self._take(spec)
        if entry.log is not None:
            Path(spec.log).write_text(entry.log, encoding="utf-8")
        self.calls.append(("launch", spec.id))
        self.live[spec.id] = {"states": list(entry.states), "outputs": entry.outputs, "written": False, "cwd": spec.cwd}
        return JobHandle(id=spec.id, backend=self.name, log=spec.log, cwd=spec.cwd,
                         unit=unit_name(spec.id), gpu_indices=tuple(gpu_indices), cores=tuple(spec.cores),
                         started_at=now_ts())

    def poll(self, handle):
        self.calls.append(("poll", handle.id))
        job = self.live.get(handle.id)
        if job is None:
            return JobState("gone", reason="the fake was never asked to launch this job")
        state = job["states"].pop(0) if len(job["states"]) > 1 else job["states"][0]
        if state.terminal and not job["written"]:
            job["written"] = True
            if state.name == "exited":
                for relative, content in job["outputs"].items():
                    target = Path(job["cwd"]) / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
        return state

    def kill(self, handle, hard=False):
        self.calls.append(("kill", handle.id))
        job = self.live.get(handle.id)
        if job is None:
            return False
        job["states"] = [JobState("killed", result="signal", exit_code=137, reason="the fake was killed")]
        return True

    def cleanup(self, handle):
        self.calls.append(("cleanup", handle.id))
        self.live.pop(handle.id, None)
        return True

    def kill_all(self):
        for job in self.live.values():
            job["states"] = [JobState("killed", reason="the fake slice was stopped")]
        return True


SYSTEMD_RUN = SystemdRun()
SETSID = Setsid()
FAKE_JOBS = FakeJobs()
JOBS_BACKENDS = {SystemdRun.name: SYSTEMD_RUN, Setsid.name: SETSID, FakeJobs.name: FAKE_JOBS}


def user_manager_reachable():
    """Whether `systemctl --user` can reach a manager, which is what picks the backend (A5)."""
    try:
        done = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, check=False)
    except OSError:
        return False
    return done.returncode == 0


def jobs_backend(name=None):
    """The backend: `WAYLINE_JOBS` when it is set, else `systemd_run`, else `setsid`.

    The fallback is chosen by asking, once per call, whether a user manager answers; a box with
    `XDG_RUNTIME_DIR` unset (a `sudo -u` shell) has none and gets `setsid` with no configuration.
    """
    name = name or os.environ.get("WAYLINE_JOBS")
    if not name:
        name = SystemdRun.name if user_manager_reachable() else Setsid.name
    try:
        return JOBS_BACKENDS[name]
    except KeyError:
        raise JobError("WAYLINE_JOBS=%s names no backend; the backends are %s" % (name, ", ".join(JOBS_BACKENDS))) from None


@contextmanager
def use_fake_jobs():
    """Select the fake backend for a block (tests) and hand it over for scripting. Not re-entrant."""
    previous = os.environ.get("WAYLINE_JOBS")
    os.environ["WAYLINE_JOBS"] = FakeJobs.name
    FAKE_JOBS.reset()
    try:
        yield FAKE_JOBS
    finally:
        FAKE_JOBS.reset()
        if previous is None:
            os.environ.pop("WAYLINE_JOBS", None)
        else:
            os.environ["WAYLINE_JOBS"] = previous


# --- the job file (schema `job`) --------------------------------------------------------------------


def resolve_gpu_indices(gpu_uuids, gpus=None):
    """The indices of the GPUs a spec names by uuid, resolved at launch because an index moves at boot."""
    if not gpu_uuids:
        return ()
    gpus = read_gpus() if gpus is None else gpus
    by_uuid = {gpu["uuid"]: gpu["index"] for gpu in gpus}
    missing = [uuid for uuid in gpu_uuids if uuid not in by_uuid]
    if missing:
        raise JobError("this machine has no GPU %s (it has %s)" % (", ".join(missing), ", ".join(by_uuid) or "none"))
    return tuple(by_uuid[uuid] for uuid in gpu_uuids)


def job_record(spec, backend=None, unit=None, gpu_indices=(), status="pending", attempts=()):
    """A `job` record for `jobs/<id>.json`, as Implementation Decisions 6 spells the fields."""
    return {
        "id": spec.id,
        "ticket": int(spec.ticket),
        "array": spec.array,
        "backend": backend,
        "unit": unit,
        "command": [str(part) for part in spec.command],
        "cwd": spec.cwd,
        "env": {str(key): str(value) for key, value in spec.env.items()},
        "devices": {
            "gpu_uuids": list(spec.gpu_uuids),
            "gpu_indices": [int(index) for index in gpu_indices],
            "cores": [int(core) for core in spec.cores],
            "ram_gb": spec.ram_gb,
        },
        "log": spec.log,
        "expected_outputs": list(spec.expected_outputs),
        "retry": {
            "host_oom": list((spec.retry or {}).get("host_oom", [])),
            "gpu_oom": list((spec.retry or {}).get("gpu_oom", [])),
        },
        "attempts": [dict(attempt) for attempt in attempts],
        "status": status,
        "wallclock_minutes": int(spec.wallclock_minutes),
    }


def spec_from_record(record):
    """The `JobSpec` a job file describes, so a poll or a retry needs nothing but the file."""
    devices = record.get("devices", {})
    return JobSpec(
        id=record["id"], ticket=record["ticket"], command=tuple(record["command"]), cwd=record["cwd"],
        log=record["log"], array=record.get("array"), env=dict(record.get("env", {})),
        gpu_uuids=tuple(devices.get("gpu_uuids", [])), cores=tuple(devices.get("cores", [])),
        ram_gb=devices.get("ram_gb", 0.0), expected_outputs=tuple(record.get("expected_outputs", [])),
        retry=dict(record.get("retry", {})), wallclock_minutes=record.get("wallclock_minutes", DEFAULT_WALLCLOCK_MINUTES),
    )


def handle_for(record):
    """The handle a job file describes, so a conductor that restarted can still poll and kill."""
    devices = record.get("devices", {})
    attempts = record.get("attempts") or []
    return JobHandle(
        id=record["id"], backend=record.get("backend") or SystemdRun.name, log=record["log"], cwd=record["cwd"],
        unit=record.get("unit"), gpu_indices=tuple(devices.get("gpu_indices", [])),
        cores=tuple(devices.get("cores", [])), started_at=attempts[-1].get("started_at") if attempts else None,
    )


# --- the runner ---------------------------------------------------------------------------------------


class JobRunner:
    """The seam: `launch(spec) -> handle`, `poll(handle) -> JobState`, `kill(handle, hard=)`, `cleanup(handle)`.

    With a project the runner keeps `jobs/<id>.json` up to date through the ledger: the launch
    writes the record and opens an attempt, and the first poll that sees a terminal state closes it
    with the result, the exit code, and the timestamps that are the job's duration. Without one it
    is the bare seam, which is what a live check or a backend test wants.

    It journals `job_launched` and `job_cancelled`, the two things only it knows. `job_finished`,
    `job_retried`, and `job_failed` belong to the conductor, which alone knows whether the outputs
    parsed and whether a footprint ladder has a step left.
    """

    def __init__(self, project=None, backend=None):
        self.project = Path(project).resolve() if project is not None else None
        self.backend = backend if backend is not None else jobs_backend()
        self._ledger = Ledger(self.project) if self.project is not None else None

    # --- the four calls ---

    def launch(self, spec, gpu_indices=None):
        """Start one job, record it, and hand back the handle its poll needs."""
        spec.check()
        indices = resolve_gpu_indices(spec.gpu_uuids) if gpu_indices is None else tuple(gpu_indices)
        handle = self.backend.launch(spec, indices)
        self._record_launch(spec, handle, indices)
        return handle

    def poll(self, handle):
        """Decode where the job is, and write a terminal state into its file once."""
        state = self._backend_for(handle).poll(handle)
        self._record_state(handle, state)
        return state

    def kill(self, handle, hard=False):
        """Cancel a job: SIGTERM the whole job, or SIGKILL it. Errors are ignored (A4)."""
        killed = self._backend_for(handle).kill(handle, hard=hard)
        self._record_kill(handle, hard)
        return killed

    def cleanup(self, handle):
        """Unload what the backend left behind, after the result has been read."""
        return self._backend_for(handle).cleanup(handle)

    def _backend_for(self, handle):
        """The backend that launched this job, which is not always the one this runner would pick.

        A job outlives the runner that started it: a conductor that restarted has the job file and
        nothing else, and `handle_for` reads the backend out of it. Polling a `setsid` job with
        `systemctl` would read `gone` for a job that is running.
        """
        if handle.backend and handle.backend != self.backend.name:
            return JOBS_BACKENDS.get(handle.backend, self.backend)
        return self.backend

    def kill_all(self, hard=False):
        """Stop every wayline job at once: the slice where the backend has one, job by job otherwise.

        The fallback has no slice, and it is the backend a box with no user manager gets, so a
        "cancel everything" there walks the job files the ledger still calls live and kills each
        process group. Without a project there is nothing to walk, and the answer is False.
        """
        killer = getattr(self.backend, "kill_all", None)
        if killer is not None:
            return bool(killer())
        if self.project is None:
            return False
        for record in self.live_records():
            # A job whose process is already gone is not a failure: it is cancelled in the only
            # sense that matters, and the job file says so afterwards either way.
            self.kill(handle_for(record), hard=hard)
        return True

    def live_records(self):
        """Every job file the ledger still calls live (`pending` or `running`), oldest id first."""
        if self.project is None:
            return []
        live = []
        for path in sorted((self.project / "research" / "jobs").glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get("status") in LIVE_JOB_STATUSES:
                live.append(record)
        return live

    def wait(self, handle, timeout_s=None, interval_s=POLL_INTERVAL_S, sleep=time.sleep):
        """Poll until the job is no longer running, and hand back the state that ended it.

        Only a live check and a script use this; the conductor polls once per wave and goes on with
        its work, because no session ever waits on a job.
        """
        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        while True:
            state = self.poll(handle)
            if state.terminal:
                return state
            if deadline is not None and time.monotonic() >= deadline:
                return state
            sleep(interval_s)

    # --- the job file ---

    def relpath(self, job_id):
        return "jobs/%s.json" % job_id

    def read(self, job_id):
        """The job file, or None when there is none (or no project)."""
        if self._ledger is None:
            return None
        try:
            return self._ledger.read_json(self.relpath(job_id))
        except (OSError, ValueError, LedgerError):
            return None

    def write(self, record):
        """Validate and write one job file; the ledger is the only writer of `research/`."""
        if self._ledger is None:
            return None
        return self._ledger.write_json(self.relpath(record["id"]), record, schema="job")

    def _record_launch(self, spec, handle, indices):
        if self._ledger is None:
            return None
        record = self.read(spec.id) or job_record(spec, gpu_indices=indices)
        record.update(backend=handle.backend, unit=handle.unit, status="running")
        record["devices"]["gpu_indices"] = [int(index) for index in indices]
        record["attempts"] = list(record.get("attempts") or []) + [{
            "n": len(record.get("attempts") or []) + 1,
            "started_at": handle.started_at or now_ts(),
            "ended_at": None, "result": None, "exit_code": None, "oom": None, "overrides": {},
        }]
        self.write(record)
        self._ledger.append_event("job_launched", {
            "unit": handle.unit, "gpu_uuids": list(spec.gpu_uuids),
            "cores": [int(core) for core in spec.cores], "ram_gb": spec.ram_gb,
            "attempt": len(record["attempts"]),
        }, ticket=int(spec.ticket), job=spec.id)
        return record

    def _record_state(self, handle, state):
        """Close the open attempt when a job ends, and leave a finished file alone on later polls."""
        record = self.read(handle.id)
        if record is None:
            return None
        attempts = record.get("attempts") or []
        open_attempt = attempts[-1] if attempts and attempts[-1].get("ended_at") is None else None
        # A job the harness cancelled stays `killed`, whatever a later poll reads. Every backend
        # reads a cancellation as something else: a graceful stop exits SIGTERM, which systemd
        # counts as `Result=success`; the fallback's shell dies before it can write an exit file,
        # which reads `gone`; and a stop is `deactivating`, which reads `running`, for up to
        # `TimeoutStopSec`. The cancellation is a fact about the harness, not a reading, so the
        # status keeps it and the attempt keeps whatever the machine said.
        status = "killed" if record["status"] == "killed" else state.name
        closing = state.terminal and open_attempt is not None
        if status == record["status"] and not closing:
            return record  # a poll that changes nothing writes nothing
        record["status"] = status
        if closing:
            open_attempt.update(ended_at=now_ts(), result=state.result, exit_code=state.exit_code, oom=state.oom)
        self.write(record)
        return record

    def _record_kill(self, handle, hard):
        record = self.read(handle.id)
        if record is None:
            return None
        if record["status"] not in LIVE_JOB_STATUSES:
            # The ordinary race: the conductor cancelled a job that had just finished. A job that
            # already ended was not cancelled, and calling it so would lose its exit code.
            return record
        record["status"] = "killed"
        self.write(record)
        self._ledger.append_event("job_cancelled", {
            "job": handle.id, "reason": "SIGKILL" if hard else "SIGTERM",
        }, ticket=record.get("ticket"), job=handle.id)
        return record


# --- `wayline job add` ---------------------------------------------------------------------------------


# What a job spec on stdin may carry: the job file's own fields, plus the two an array needs.
SPEC_FIELDS = (
    "id", "ticket", "array_id", "members", "command", "cwd", "env", "log", "devices",
    "expected_outputs", "retry", "wallclock_minutes",
)
MEMBER_FIELDS = tuple(name for name in SPEC_FIELDS if name not in ("array_id", "members"))
LOGS_DIR = "results/logs"


def add_jobs(project, spec, ticket=None, backend=None):
    """Write one job file per job the spec describes, validated; returns the records written.

    One object is one job. With `members` it is a job array: every member inherits the base fields
    and overrides what it names, and all of them carry the same `array` id, which is what lets the
    conductor launch as many members as fit a wave and close the ticket when every one of them
    exited 0.

    The record names the backend this machine would use, because a `pending` job file is still a
    job file and the schema asks which runner it is for; the launch records the one that ran.
    """
    project = Path(project).resolve()
    if not isinstance(spec, dict):
        raise JobError("a job spec is a JSON object, got %s" % type(spec).__name__)
    unknown = sorted(set(spec) - set(SPEC_FIELDS))
    if unknown:
        raise JobError("a job spec has no field(s) %s; it has %s" % (", ".join(unknown), ", ".join(SPEC_FIELDS)))
    members = spec.get("members")
    if members is not None and (not isinstance(members, list) or not members):
        raise JobError("members is a non-empty list of job objects")
    base = {key: value for key, value in spec.items() if key in MEMBER_FIELDS}
    array_id = _array_id(spec, base, ticket) if members is not None else None
    taken = {path.stem for path in (project / "research" / "jobs").glob("*.json")}
    backend = backend or jobs_backend().name
    schema = load_schema("job")
    records = []
    for index, member in enumerate([None] if members is None else members, start=1):
        if member is not None:
            if not isinstance(member, dict):
                raise JobError("member %d is a JSON object, got %s" % (index, type(member).__name__))
            stray = sorted(set(member) - set(MEMBER_FIELDS))
            if stray:
                raise JobError("member %d has no field(s) %s" % (index, ", ".join(stray)))
        fields = dict(base, **(member or {}))
        # A spec's own `id` names the array, not its members: an array whose members inherited it
        # would write every one of them to the same job file, and the last would be the only one.
        named = (member or {}).get("id") if members is not None else fields.get("id")
        job_id = str(named) if named else _next_job_id(fields, ticket, array_id, index, taken)
        if job_id in taken:
            raise JobError("job %s already has a job file; every job id is written once" % job_id)
        taken.add(job_id)
        record = job_record(_spec_from_input(project, fields, job_id, ticket, array_id if members else None),
                            backend=backend)
        try:
            check(record, schema, name="jobs/%s.json" % job_id)
        except ValidationError as failure:
            raise JobError(str(failure)) from None
        records.append(record)
    # Written only once every member validated: half an array on disk is worse than none.
    ledger = Ledger(project)
    for record in records:
        ledger.write_json("jobs/%s.json" % record["id"], record, schema="job")
    return records


def _array_id(spec, base, ticket):
    """The group id every member of an array carries: the spec's, else its `id`, else the ticket's.

    An array whose members carry no group id is not an array as far as the conductor is concerned,
    so this never leaves one unnamed.
    """
    named = spec.get("array_id") or base.get("id")
    if named:
        return str(named)
    ticket_id = base.get("ticket", ticket)
    if ticket_id is None:
        raise JobError("a job array needs a ticket; pass it in the spec or run inside a worker session")
    return "t%s" % ticket_id


def _spec_from_input(project, fields, job_id, ticket, array_id):
    """One member's fields as a `JobSpec`: the paths absolute, the devices unpacked, the rest checked.

    Every field is type-checked here rather than at the schema, because a JSON spec arrives from a
    worker session and a string where a list belongs is a plausible mistake: `"command": "python
    train.py"` would otherwise pass `tuple()` as one argv element per character and validate.
    """
    devices = fields.get("devices") or {}
    if not isinstance(devices, dict):
        raise JobError("job %s: devices is an object of gpu_uuids, cores, ram_gb" % job_id)
    stray = sorted(set(devices) - {"gpu_uuids", "cores", "ram_gb"})
    if stray:
        raise JobError("job %s: devices has no field(s) %s" % (job_id, ", ".join(stray)))
    ticket_id = fields.get("ticket", ticket)
    if ticket_id is None:
        raise JobError("job %s: no ticket; pass it in the spec or run inside a worker session" % job_id)
    log = fields.get("log") or str(project / LOGS_DIR / (job_id + ".log"))
    wallclock = fields.get("wallclock_minutes")
    environment = fields.get("env") or {}
    if not isinstance(environment, dict):
        raise JobError("job %s: env is an object of name to value, got %s" % (job_id, type(environment).__name__))
    try:
        spec = JobSpec(
            id=job_id, ticket=_whole(ticket_id, "ticket", job_id),
            command=_string_list(fields.get("command"), "command", job_id),
            cwd=_absolute(project, fields.get("cwd") or str(project)), log=_absolute(project, log),
            array=array_id, env={str(key): str(value) for key, value in environment.items()},
            gpu_uuids=_string_list(devices.get("gpu_uuids"), "devices.gpu_uuids", job_id),
            cores=_core_list(devices.get("cores"), job_id),
            ram_gb=_amount(devices.get("ram_gb", 0.0), "devices.ram_gb", job_id),
            expected_outputs=_string_list(fields.get("expected_outputs"), "expected_outputs", job_id),
            retry=_retry(fields.get("retry"), job_id),
            wallclock_minutes=DEFAULT_WALLCLOCK_MINUTES if wallclock is None else _whole(wallclock, "wallclock_minutes", job_id),
        )
    except (TypeError, ValueError) as failure:
        raise JobError("job %s: %s" % (job_id, failure)) from None
    return spec.check()


def _string_list(value, name, job_id):
    """A JSON list of strings, refusing the string that would otherwise become a list of characters."""
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise JobError("job %s: %s is a list of strings, got %s" % (job_id, name, type(value).__name__))
    return tuple(str(item) for item in value)


def _core_list(value, job_id):
    """A JSON list of core numbers; `CPUAffinity` takes indices and nothing else."""
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise JobError("job %s: devices.cores is a list of core numbers, got %s" % (job_id, type(value).__name__))
    cores = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise JobError("job %s: devices.cores holds core numbers, got %r" % (job_id, item))
        cores.append(int(item))
    return tuple(cores)


def _amount(value, name, job_id):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobError("job %s: %s is a number, got %r" % (job_id, name, value))
    return value


def _whole(value, name, job_id):
    if isinstance(value, bool) or not isinstance(value, int):
        raise JobError("job %s: %s is a whole number, got %r" % (job_id, name, value))
    return int(value)


def _retry(value, job_id):
    """The two footprint ladders, each a list of override objects (Implementation Decisions 6)."""
    if value is None:
        return {"host_oom": [], "gpu_oom": []}
    if not isinstance(value, dict):
        raise JobError("job %s: retry is an object of host_oom and gpu_oom, got %s" % (job_id, type(value).__name__))
    stray = sorted(set(value) - {"host_oom", "gpu_oom"})
    if stray:
        raise JobError("job %s: retry has no field(s) %s" % (job_id, ", ".join(stray)))
    ladders = {}
    for name in ("host_oom", "gpu_oom"):
        steps = value.get(name) or []
        if isinstance(steps, (str, bytes)) or not isinstance(steps, (list, tuple)):
            raise JobError("job %s: retry.%s is a list of override objects, got %s" % (job_id, name, type(steps).__name__))
        for step in steps:
            if not isinstance(step, dict):
                raise JobError("job %s: retry.%s holds override objects, got %r" % (job_id, name, step))
        ladders[name] = list(steps)
    return ladders


def _absolute(project, value):
    """A path the spec gave, resolved against the project, because systemd wants an absolute one."""
    path = Path(str(value)).expanduser()
    return str(path if path.is_absolute() else (Path(project) / path))


def _next_job_id(fields, ticket, array_id, index, taken):
    """`t<ticket>-<n>` for a single job, `<array id>-<n>` for an array member; never one already on disk."""
    stem = str(array_id) if array_id else "t%s" % (fields.get("ticket", ticket))
    candidate = "%s-%d" % (stem, index)
    number = index
    while candidate in taken:
        number += 1
        candidate = "%s-%d" % (stem, number)
    return candidate


def job_command(args):
    """`wayline job add [<file>] [--project <path>] [--ticket <id>]`; the spec is JSON on stdin by default.

    The project comes from `WAYLINE_PROJECT` when a worker session runs the verb, as `wayline
    accept` reads it, so an experimenter inside a worktree writes to the project's ledger without
    knowing where the project is.
    """
    # Imported here and not at the top of the module: `project` reads the slots from this module,
    # so the import runs the other way and only a verb, which runs after both are loaded, may ask.
    from wayline.project import ProjectError, find_project

    parser = argparse.ArgumentParser(prog="wayline job", description="write a job file for the runner")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="write one job file, or one per array member, from a JSON spec")
    add.add_argument("file", nargs="?", help="the spec file; stdin when omitted or -")
    add.add_argument("--project", help="the project to write into; WAYLINE_PROJECT or the active one by default")
    add.add_argument("--ticket", type=int, help="the ticket the job belongs to; WAYLINE_TICKET by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        text = sys.stdin.read() if options.file in (None, "-") else Path(options.file).read_text(encoding="utf-8")
        spec = json.loads(text)
    except (OSError, ValueError) as failure:
        print("wayline job add: the spec is not readable JSON: %s" % failure, file=sys.stderr)
        return 1
    ticket = options.ticket or _int_or_none(os.environ.get("WAYLINE_TICKET"))
    try:
        project = options.project or os.environ.get("WAYLINE_PROJECT") or find_project(None)
        records = add_jobs(project, spec, ticket=ticket)
    except (JobError, ProjectError, ValidationError, LedgerError, OSError) as failure:
        print("wayline job add: %s" % failure, file=sys.stderr)
        return 1
    for record in records:
        print("job  %s  ticket %d  %s" % (record["id"], record["ticket"], record["log"]))
    return 0
