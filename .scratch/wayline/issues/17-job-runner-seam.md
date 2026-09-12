# 17 - Job runner seam (verbatim prototype 27)

**What to build:** A detached job is launched under the owner's systemd user manager pinned to assigned GPUs and cores with a memory cap, polled by code, told apart on failure (exit code, host out-of-memory, GPU out-of-memory, cancellation), killed and cleaned up on request, and falls back to `setsid` when no user manager is reachable. `wayline job add` is the verb an experimenter uses to describe a job or a job array for the runner. The first criterion is the closed prototype ticket's Question, carried verbatim; the real runner stands in for the throwaway script.

**Blocked by:** 16 (Resources detection and slots)

**Status:** done

**GitHub:** [#18](https://github.com/Bernaljp/wayline/issues/18) (mirror; the local file is the source)

**Milestone:** M2 Hardware. **Spec:** milestone M2 criterion 1; Implementation Decisions 6 (interface, launch line, poll, OOM rule, kill, fallback, job file); Testing Decisions seam 2; research-notes 05 A1 to A5 and the raw outputs R2 to R11.

- [x] Carried verbatim from the closed prototype ticket 27 (Prototype: the detached GPU job runner):

  > Does the recommended runner work on this machine end to end? Build a throwaway script that:
  >
  > 1. Launches a small GPU job (a Python script that allocates a tensor on CUDA if torch is available, otherwise a `nvidia-smi` loop) through `systemd-run --user` pinned to GPU 0 and eight cores, with stdout and stderr appended to a log, and writes `jobs/<id>.json` with the unit name, command, devices, log path, expected outputs.
  > 2. Polls the unit until it exits, records the exit code and duration in the job file.
  > 3. Launches a second job that deliberately allocates more than 24 GB and shows how the failure is detected as out-of-memory from the log and the unit result.
  > 4. Shows the setsid fallback for the same job.
  >
  > Record the commands and the job file. The answer is the job file schema and the runner call M2 implements. Keep it under `.scratch/proto/job-runner/`.

  The real job runner stands in for the throwaway script; `docs/verification/m2.md` holds the commands, the job files, and the poll outputs for the pinned job, the OOM job, and the fallback.
- [x] `JobRunner.launch(spec) -> handle`, `poll(handle) -> JobState` (`running, exited, oom_host, oom_gpu, failed, killed, gone`), `kill(handle, hard=False)`, `cleanup(handle)`; backends `systemd_run`, `setsid` (chosen automatically when `systemctl --user show-environment` fails), and `fake`.
- [x] The `systemd_run` backend runs the Implementation Decisions 6 launch line verbatim (unit `wayline-job-<id>`, slice `wayline-jobs`, `--remain-after-exit`, `--expand-environment=no`, `CPUAffinity`, `MemoryMax`, `MemorySwapMax=0`, `TimeoutStopSec=30`, `RuntimeMaxSec` from `wallclock_minutes`, `WorkingDirectory`, `StandardOutput=append:` and `StandardError=append:` to the same log, `CUDA_VISIBLE_DEVICES`, `PYTHONUNBUFFERED=1`) and never `--collect`; polls with `systemctl --user show wayline-job-<id>.service -p LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus` and decodes per the table; `LoadState=not-found` never implies success.
- [x] The OOM rule: `Result=oom-kill` is `oom_host`; `Result=exit-code` plus one of the eight CUDA signatures in the last 64 KB of the log is `oom_gpu`; the signature list is one table; `Result=signal` with 9 and no `oom-kill` is `killed`; `Result=timeout` is `failed` with reason `wallclock`.
- [x] Kill and cleanup follow research-notes 05 A4 (`stop`, `kill --signal=SIGKILL`, `stop wayline-jobs.slice`, `reset-failed`, `stop` for exited units, errors ignored); the `setsid` backend follows A5 with the `.exit` and `.pid` files and records `backend: setsid` in the job file.
- [x] `jobs/<id>.json` follows the `job` schema (`id, ticket, array, backend, unit, command, cwd, env, devices: {gpu_uuids, gpu_indices, cores, ram_gb}, log, expected_outputs, retry: {host_oom, gpu_oom}, attempts[], status, wallclock_minutes`); GPUs are recorded by uuid and resolved to an index at launch.
- [ ] `wayline job add` writes one job file (or one per array member with a shared `array` id) from a JSON spec on stdin, validating it against the schema, and is on the experimenter's allowed tools.
- [x] Tests decode the recorded `systemctl show` outputs R2 to R11 and drive the fake backend through every `JobState` value; the live criterion above runs on the GPU.
