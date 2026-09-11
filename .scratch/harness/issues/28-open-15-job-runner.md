# 28 — OPEN-15 Job runner

Type: grilling
Status: resolved
Blocked by: 27 (Prototype: the detached GPU job runner)
Brief: OPEN-15, Section 9.3

## Question

A user-level service manager (`systemd-run --user`, default) or detached processes with a session leader?

Default: `systemd-run --user`, with `setsid` as the fallback when the user manager is unavailable. Confirm against the prototype, and decide whether resource pinning uses `CPUAffinity` alone or also `MemoryMax` (default: both, with `MemoryMax` from the ticket's `ram_gb`).

## Answer

Resolved 2026-09-11 by the owner: default confirmed on research evidence, without the prototype; the tracer bullet named below re-verifies it as its first acceptance criterion.

`systemd-run --user` with the research launch line (`--unit`, `--slice=sdr-jobs`, `--remain-after-exit`, `--expand-environment=no`, `CPUAffinity`, `MemoryMax`, `MemorySwapMax=0`, append logs, `CUDA_VISIBLE_DEVICES`; never `--collect`); polled with `systemctl --user show`; `setsid nohup` as the lossy fallback. M2's first acceptance criterion runs one pinned job and one OOM job.
