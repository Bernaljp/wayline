# 36 — Prototype: dashboard transport through the tunnel

Type: prototype
Status: resolved
Blocked by: 08 (Dashboard transport: polling versus server-sent events on the standard library), 15 (OPEN-4 Language)
Blocks: 37 (OPEN-20 Dashboard implementation)
Brief: Section 9.9, M1; fog: polling versus server-sent events

## Question

Which transport feels right from the laptop? Build a throwaway standard-library server with two endpoints over a fake journal that a background thread appends to every second: `/api/journal?since=<n>` polled every two seconds, and `/events` as server-sent events; one static page with project tabs and a journal tail that can switch transport with a query parameter. The owner opens it through `ssh -L` from the laptop and reacts: latency, dropped streams, CPU on the workstation, behavior when the laptop sleeps and wakes.

The answer is the transport M1's read-only dashboard uses. Keep it under `.scratch/proto/dashboard/`.

## Answer

Closed 2026-09-11 by the owner's scoping decision: not built as a throwaway. Its Question becomes the first acceptance criterion of tracer bullet M1 Frontier and windows (BRIEF.md Section 16), which builds the real version; to-tickets must carry it there verbatim.
