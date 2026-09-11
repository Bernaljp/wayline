# 18 — OPEN-6 Verifier backends and order

Type: grilling
Status: resolved
Blocked by: None
Brief: OPEN-6, C6, Section 10

## Question

Order of Type-B backends: a fresh session on a different Claude model, then an optional external model, then the human (default).

Facts: the `codex` CLI is installed at `~/.local/bin/codex` and an MCP codex server is connected in this environment, so an external backend exists when the owner enables it.

Decide:
1. Is a different Claude model enough independence for `accepted`? Default: yes for difficulty 1 to 4.
2. Do research-critical claims (difficulty 5, and every claim in REPORT.md and the paper) require the external backend when one is configured? Default: yes when configured, otherwise the human.
3. Does the verifier also run with a different system prompt and no author skills, to count as independent? Default: yes; it receives paths, not summaries, and a scope limit.

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

Type-B verdicts come from a fresh Claude session on a different model and effort than the author, for every difficulty 1 to 5. No external backend and no human verdict unless the owner decides to enable them per step. The verifier runs with its own system prompt, no author skills, receives paths not summaries, and carries a scope limit. This narrows C6's fallback chain by the owner's choice.
