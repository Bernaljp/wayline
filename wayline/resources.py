"""Resource detection and slots (Implementation Decisions 6, 14; research-notes 05 A8).

The harness reads what the workstation has (GPU, cores, load, RAM, disk), subtracts the owner's
reservation, and hands out slots by the free-slot rule so a job never starves the machine it runs
on. Every live reading goes through a module-level path or command so a test can point it at
fixture data instead of the real box; nothing here writes anything (the ledger module is the only
writer, Implementation Decisions 2).
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ResourceError", "GPU_OOM_SIGNATURES",
    "read_gpus", "read_gpu_processes", "sample_gpu_utilization",
    "read_loadavg1", "read_cpu_pressure", "read_mem_available_bytes", "read_disk_avail_bytes",
    "pids_by_name", "process_cores", "process_reservation",
    "Reservation", "reservation_from_harness",
    "gpu_free", "cpu_slot_free", "ram_free", "core_pool", "CoreAllocator",
    "gpu_slots_view", "cpu_slot_view", "ram_slot_view", "snapshot", "render_resources",
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
