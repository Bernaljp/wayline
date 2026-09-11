# 19 - Experiment and analysis tickets end to end (M2 demo)

**What to build:** The M2 demo: `experiment` and `analysis` tickets launch detached jobs on assigned GPUs and cores; a sweep fills free slots; an OOM is retried smaller; results and findings land in the ledger; the interactive session's reservation is respected. An experiment worker prepares a job array and returns `status: running`; no session waits; the conductor polls the jobs every wave, closes the ticket when every member exited 0 and its outputs parse, and the dependent analysis ticket runs and files findings with provenance into manifested results. With the window closed, jobs still launch and finish.

**Blocked by:** 07 (Frontier, launchable subset, and two parallel workers), 17 (Job runner seam (verbatim prototype 27)), 18 (Manifest and findings provenance)

**Status:** ready-for-agent

**Milestone:** M2 Hardware. **Spec:** milestone M2 criteria 2 to 9; Implementation Decisions 5 (wave step 2, worker outcome `running`), 6 (sweeps, OOM retry), 1 (roles).

- [ ] `roles/experimenter/` and `roles/analyst/` exist; the experimenter's allowed tools include `Bash(wayline job add*)` and `Bash(nvidia-smi *)`; an experiment ticket's `resources` and `retry` fields reach the job spec.
- [ ] A result with `status: running` and job ids leaves the ticket `running`; each wave polls every job in `jobs/`; when every member exited 0 and every expected output exists and parses (JSON or CSV), the outputs are registered in the manifest and the ticket goes `done`; the dependent `analysis` ticket enters the frontier and runs.
- [ ] Job arrays launch as many members as fit each wave (one GPU job at a time, CPU jobs on the remaining cores) and journal `job_launched` and `job_finished` per member.
- [ ] Host OOM first doubles `MemoryMax` up to free RAM minus the reserve, then steps `retry.host_oom`; GPU OOM steps `retry.gpu_oom`; each step journals `job_retried` with the overrides; an exhausted ladder journals `job_failed` with the log tail and fails the ticket with the tail as the failure output.
- [ ] While paused (simulated with `--simulate-limit`) a wave still launches and polls jobs and runs machine checks; nothing that needs a model launches.
- [ ] `CPUAffinity` never includes the reserved cores; a job whose core request exceeds the free cores waits and is journaled as waiting.
- [ ] `fixtures/projects/sweep/` holds an experiment ticket with a three-member array and a dependent analysis ticket; the suite runs it with fake jobs and the fake worker and asserts the journal, the manifest, and the findings; the same runs live on the GPU with a small script that trains for a minute, including one member that is scripted to OOM once and be retried; `docs/verification/m2.md` records it; the repository is tagged `v0.3.0`.
