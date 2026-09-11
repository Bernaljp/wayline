# 27 — Prototype: the detached GPU job runner

Type: prototype
Status: resolved
Blocked by: 05 (Detached jobs, the tick, and notifications under systemd)
Blocks: 28 (OPEN-15 Job runner)
Brief: Section 9.3, M2; fog: the detached job runner

## Question

Does the recommended runner work on this machine end to end? Build a throwaway script that:

1. Launches a small GPU job (a Python script that allocates a tensor on CUDA if torch is available, otherwise a `nvidia-smi` loop) through `systemd-run --user` pinned to GPU 0 and eight cores, with stdout and stderr appended to a log, and writes `jobs/<id>.json` with the unit name, command, devices, log path, expected outputs.
2. Polls the unit until it exits, records the exit code and duration in the job file.
3. Launches a second job that deliberately allocates more than 24 GB and shows how the failure is detected as out-of-memory from the log and the unit result.
4. Shows the setsid fallback for the same job.

Record the commands and the job file. The answer is the job file schema and the runner call M2 implements. Keep it under `.scratch/proto/job-runner/`.

## Answer

Closed 2026-09-11 by the owner's scoping decision: not built as a throwaway. Its Question becomes the first acceptance criterion of tracer bullet M2 Hardware (BRIEF.md Section 16), which builds the real version; to-tickets must carry it there verbatim.
