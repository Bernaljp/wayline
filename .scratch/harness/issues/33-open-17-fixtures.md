# 33 — OPEN-17 Fixtures for model behavior

Type: grilling
Status: resolved
Blocked by: 32 (Prototype: one behavior fixture)
Brief: OPEN-17, Section 12

## Question

How strict is a "regression" for a prompt change when outputs are not deterministic?

Default: structural checks on the schema-validated output must all pass; a Type-B verdict on a small fixed sample must pass at or above a threshold (default 2 of 3); a fixture that flakes twice is quarantined and reported, not deleted. Confirm against the prototype's stability run.

## Answer

Resolved 2026-09-11 by the owner: default confirmed on research evidence, without the prototype; the tracer bullet named below re-verifies it as its first acceptance criterion.

Structural checks must pass n of n; judged sample at least 2 of 3; a fixture that flakes twice with unchanged hashes is quarantined and reported, never deleted; layout `fixtures/<kind>/<slug>/` per research-notes/07-model-behavior-fixtures.md; fixtures never use `--bare`. M6 records the first fixture from a real journaled run.
