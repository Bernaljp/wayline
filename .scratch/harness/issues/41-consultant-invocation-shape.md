# 41 — Consultant invocation shape

Type: grilling
Status: resolved
Blocked by: None
Brief: Section 7.4; graduated from fog after OPEN-1 and Workflow scripts from headless sessions

## Question

How is the consultant role invoked, and how do its answers get back into the dossier?

Default: two entry points to one role definition in `roles/consultant`. From code (the planner, the decider, a worker's context-pack builder), `claude -p --agent consultant --add-dir <refs/<slug>> --disallowedTools Edit Write --json-schema consultant_answer.json` with the question as the prompt; the answer (text, locators, confidence, `not_in_source`) is validated and `ledger.py` appends it to `refs/<slug>/qa_log.md`. From inside a session (a Workflow reader or a worker), the Agent tool with `agentType: consultant` and the same schema, whose result the calling Workflow script returns to code for the same append. A question the dossier cannot answer at L1 sets `promote_requested: true` in the answer, which the conductor turns into a promotion (7.2) within the budget or a decision ticket beyond it. Decide whether workers may call the consultant directly (default: yes, read-only, at most five questions per ticket, journaled) or only through the context pack.

## Answer

Resolved 2026-09-11 by the owner: default confirmed on research evidence, without the prototype; the tracer bullet named below re-verifies it as its first acceptance criterion.

One role definition in `roles/consultant`, two entry points: from code, `claude -p --agent consultant --add-dir <refs/<slug>> --disallowedTools Edit Write --json-schema consultant_answer.json`; in-session, the Agent tool with `agentType: consultant` and the same schema. `ledger.py` appends every answer to `refs/<slug>/qa_log.md`; `promote_requested: true` turns into a promotion inside the budget or a decision ticket beyond it. Workers may ask at most five questions per ticket, read-only, journaled.
