# 14 — OPEN-3 Concurrency across projects

Type: grilling
Status: resolved
Blocked by: None
Brief: OPEN-3, Section 5.2

## Question

One active project and one conductor (default), or a global scheduler serving several projects under one usage budget?

Default: one active project. Usage windows are shared across every session, the resource manager is simpler with one owner, and `switch <path>` covers the rare change. The tick serves only the active project.

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

One active project and one conductor. The tick serves only the active project; `switch <path>` moves the pointer.
