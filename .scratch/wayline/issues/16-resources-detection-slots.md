# 16 - Resources detection and slots

**What to build:** The harness knows what the workstation has and what it may use: it reads the GPU (uuid, memory, utilization), the cores, the load, the RAM, and the disk, subtracts the owner's reservation (no GPU, 8 cores, 64 GB, plus the listed processes), and hands out slots by the free-slot rule; `wayline status` shows the slots in use and free.

**Blocked by:** 02 (init lays out a project and status reads it)

**Status:** ready-for-agent

**Milestone:** M2 Hardware. **Spec:** Implementation Decisions 6 (detection and slots), 14 (`reservations`, `jobs`); research-notes 05 A8.

- [ ] Detection runs `nvidia-smi --query-gpu=index,uuid,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory --format=csv,noheader,nounits` and `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits`, reads `/proc/loadavg` field 1 against `nproc`, `/proc/pressure/cpu`, `MemAvailable` from `/proc/meminfo`, and `df -B1 --output=avail /home`, and degrades to CPU-only when `nvidia-smi` is absent.
- [ ] The reservation comes from `harness.json.reservations` (gpu, cores, ram_gb, processes); the GPU memory and cores of a listed process count as reserved.
- [ ] A GPU slot is free when `memory.free >= need + reserve`, `utilization.gpu < policy.jobs.gpu_util_free_below` for two consecutive samples, and no wayline job holds it (jobs take the GPU whole, one at a time on this machine); a CPU slot is free when `loadavg1 + cores_needed <= nproc - reserved_cores` and the core allocator can supply a contiguous or listed range from the unreserved pool; RAM is free when `MemAvailable - reserved - sum(MemoryMax of running jobs) >= need`.
- [ ] The core allocator hands out and returns core ranges per job and never includes the reserved cores.
- [ ] `wayline status` prints the slots (GPU held or free, cores in use, RAM committed) and the reservation.
- [ ] Tests use recorded readings from research-notes 05 and synthetic ones for the boundaries of every rule.
