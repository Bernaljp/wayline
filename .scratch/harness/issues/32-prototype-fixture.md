# 32 — Prototype: one behavior fixture

Type: prototype
Status: resolved
Blocked by: 07 (Fixtures for non-deterministic model behavior)
Blocks: 33 (OPEN-17 Fixtures for model behavior)
Brief: Section 12, M6; fog: the fixture format

## Question

Does the proposed fixture format catch a regression? Record one real input pack and output from the worker-launch prototype (or any journaled `claude -p` run), write it in the format the research note proposes, write a small runner that checks the structural assertions and asks one fresh `--model sonnet --effort low` session a rubric question over a sample of three, and run it twice to see stability. Then break the prompt deliberately and show the fixture failing.

The answer is the fixture file format and the runner contract M6 implements. Keep it under `.scratch/proto/fixture/`.

## Answer

Closed 2026-09-11 by the owner's scoping decision: not built as a throwaway. Its Question becomes the first acceptance criterion of tracer bullet M6 Evolve (BRIEF.md Section 16), which builds the real version; to-tickets must carry it there verbatim.
