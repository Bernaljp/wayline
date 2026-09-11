# 31 — OPEN-16 Reading budgets

Type: grilling
Status: resolved
Blocked by: 04 (Workflow scripts from headless sessions), 30 (Prototype: inventory one non-arXiv PDF and one arXiv source)
Brief: OPEN-16, Section 7.2

## Question

Default L1 budget per paper and L2 budget per phase; which promotion triggers act automatically and which ask?

Default: L1 is one call at sonnet with a fixed input cap (abstract, introduction, conclusion, captions, results table headers); L2 is capped per phase (P1: 3 papers, P3 and P5: 2 each), every trigger listed in 7.2 promotes automatically inside the budget, beyond it a decision ticket. Set the numbers after the prototype shows the per-paper chunk count and after the Workflow note shows the fan-out cost.

## Answer

Resolved 2026-09-11 by the owner: default confirmed on research evidence, without the prototype; the tracer bullet named below re-verifies it as its first acceptance criterion.

L1 is one sonnet call per paper with a fixed input cap (abstract, introduction, conclusion, captions, results table headers). L2 is capped per phase at 3 papers in P1 and 2 each in P3 and P5. Every trigger in 7.2 promotes automatically inside the budget; beyond it, a decision ticket. Numbers live in `policy.json` and are revised after M3 measures chunk counts and fan-out cost.
