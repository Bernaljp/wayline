"""A recorded reading of the workstation, for the free-slot rule (Testing Decisions seam 2).

The numbers are this machine's (one RTX 3090, 128 cores, the reservation owning cores 0 to 7 and
64 GB), recorded by `wayline status` on 2026-09-12 and trimmed to what `resources.place_jobs`
reads. A test that places jobs sets `Conductor.readings` to `recorded` so no test reads
`nvidia-smi` or `/proc`.
"""

from wayline.resources import GIB, Reservation

GPU_UUID = "GPU-0095fb8d-af69-ff0f-6b06-da1a9a89fc7f"


def gpu(utilization=0, free_mib=23800):
    return {"index": 0, "uuid": GPU_UUID, "memory_total_mib": 24576, "memory_used_mib": 24576 - free_mib,
            "memory_free_mib": free_mib, "utilization_gpu": utilization, "utilization_memory": 0}


def recorded(nproc=128, loadavg1=1.5, available_gb=200, reserved_cores=8, reserved_gb=64, gpus=True, utilization=0):
    """One reading in `resources.read_readings`'s shape; the keywords move one number at a time."""
    samples = [[gpu(utilization)], [gpu(utilization)]] if gpus else [[]]
    return {
        "reservation": Reservation(cores=frozenset(range(reserved_cores)), ram_bytes=reserved_gb * GIB),
        "gpus": samples,
        "loadavg1": loadavg1,
        "nproc": nproc,
        "mem_available_bytes": available_gb * GIB,
    }
