# 20 — OPEN-8 Parallelism and budgets

Type: grilling
Status: resolved
Blocked by: 02 (Unattended auth and usage-limit signals)
Brief: OPEN-8, Section 9.6

## Question

Start with `max_parallel_workers: 2`, hardware slots from detection minus the reservation, and measure a night (default).

Facts: one RTX 3090 with 24 GB, 128 cores, 1 TB RAM.

Decide:
1. The default reservation for the interactive session on a one-GPU machine (default: no GPU reserved, 8 cores and 64 GB reserved; the owner lists processes to protect in `harness.json`).
2. Whether experiment jobs take the GPU whole or share it by memory fraction (default: whole GPU, one GPU job at a time; CPU jobs fill the remaining cores).
3. The per-window worker budget and quiet hours (default: none until a night is measured), and whether the conductor paces on the `rate_limits` percentages if the research note found they are readable headless.

## Answer

Resolved 2026-09-11 by the owner in a grilling round.

Start at `max_parallel_workers: 2` and measure a night. On this one-GPU machine the default reservation is no GPU, 8 cores, and 64 GB for the owner; experiment jobs take the GPU whole, one GPU job at a time, CPU jobs fill the remaining cores. Pacing reads five-hour and weekly utilization from `rate_limit_event` on every worker and from `claude -p "/usage"` at every tick. Thresholds: launch nothing new above 90 percent of the five-hour window; prefer difficulty 1 and 2 tickets above 80 percent. Both thresholds are set at `init` in `harness.json` and adjustable from the dashboard (added to its action set). No quiet hours until measured.
