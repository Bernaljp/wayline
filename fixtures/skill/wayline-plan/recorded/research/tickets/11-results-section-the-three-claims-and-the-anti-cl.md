---
id: 11
title: "Results section: the three claims and the anti-claims from the findings"
kind: writing
difficulty: 3
status: open
blocked_by: [9, 10]
touches: [report/]
role: writer
skills: []
acceptance:
  machine: [test -f report/results.md && grep -q 'C1' report/results.md && grep -q 'C2' report/results.md && grep -q 'C3' report/results.md, grep -qi 'synthetic-only' report/results.md]
  quality: ["Does every claim sentence carry a provenance tag that resolves to a filed finding, does the prose use CONTEXT.md's terms (gain, no-product baseline, oracle reference), and does it state A1 and A2 without reading any product as a discovery?"]
context_pack: [research/CONTEXT.md#language, research/SPEC.md#claims, research/SPEC.md#anti-claims, research/SPEC.md#out-of-scope, analysis/e1-e3/verdict.md, analysis/e2/verdict.md, research/findings.jsonl]
origin: research/SPEC.md#claims
proposed_by: planner
demo: "report/results.md reads as the answer to the spec's question: a table of per-seed AUROC for the four models, the E1/E2/E3 means with sd, one paragraph per claim ending in its verdict, and the anti-claims stated as limits."
---

## Demo

report/results.md reads as the answer to the spec's question: a table of per-seed AUROC for the four models, the E1/E2/E3 means with sd, one paragraph per claim ending in its verdict, and the anti-claims stated as limits.

## Notes

Write from the findings only; a number not in a finding is not written. Keep to the spec's out-of-scope list.
