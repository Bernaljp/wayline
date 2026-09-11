# 29 — Prototype: the tick

Type: prototype
Status: resolved
Blocked by: 02 (Unattended auth and usage-limit signals), 05 (Detached jobs, the tick, and notifications under systemd), 12 (OPEN-1 Execution engine)
Blocks: None (its answer is the tick's contract, consumed by to-spec for M1)
Brief: Section 9.6, M1; fog: the tick

## Question

Does a recurrent job relaunch work after a closed window and after an answered decision? Build a throwaway script that:

1. Installs a user timer (per the research note's recommendation) firing every minute for the test, running `tick.sh`.
2. `tick.sh` reads an active-project pointer file, checks a conductor heartbeat file (pid plus timestamp), and exits if the conductor is alive; otherwise reads a `window.json` (`{"closed_until": <epoch>}`) and a `answers/` directory, and relaunches a dummy conductor (a script that appends a journal line and exits) when the window is open and work remains or an answer appeared.
3. Sends one `notify-send` from the timer's unit.
4. Simulates a closed window, waits for the reset, and shows the relaunch in the journal.
5. Uninstalls the timer cleanly.

Record what worked. The answer is the tick's contract (files it reads, conditions, actions) that M1 implements. Keep it under `.scratch/proto/tick/`.

## Answer

Closed 2026-09-11 by the owner's scoping decision: not built as a throwaway. Its Question becomes the first acceptance criterion of tracer bullet M1 Frontier and windows (BRIEF.md Section 16), which builds the real version; to-tickets must carry it there verbatim.
