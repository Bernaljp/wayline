# 32 - Type-B verdicts: the verifier role and gates

**What to build:** Nothing is acquitted by its author: a done ticket with quality criteria, and every ticket of difficulty 3 to 5, receives a verdict from a fresh session on a different model with its own prompt, no author skills, paths rather than summaries, and a scope limit; a pass makes the ticket accepted, a fail sends the findings back as the next failure output. The same gate serves every later Type-B question (the spec, the dossier spot-check, sampled claims, figures, docs, the kill argument).

**Blocked by:** 05 (The conductor's M0 path with the fake worker)

**Status:** ready-for-agent

**GitHub:** [#33](https://github.com/Bernaljp/wayline/issues/33) (mirror; the local file is the source)

**Milestone:** M4 Front door (used from M4 on; M5 exercises it overnight). **Spec:** Implementation Decisions 11 (verdicts, what gets a verdict, the kill argument), 14 (`verifier` table); OPEN-6 (map ticket 18).

- [ ] `roles/verifier/` exists with read-only tools and its own system prompt; `gates.verdict(subject_kind, subject, question, paths, scope_limit)` launches it through the launcher on the model the `policy.verifier` table gives for the author's model (sonnet author: opus high; opus author: fable high; fable author: opus max), with the paths and the one question, and validates `{pass, findings: [{text, locator, severity}], question_limit, session_id, model}`.
- [ ] The conductor queues a verdict after `ticket_done` for every ticket with `acceptance.quality` and for every ticket of difficulty 3 (on the diff), 4, and 5 (on the result); the queue is model work subject to pacing; a pass journals `verdict` and `ticket_accepted`; a fail journals `verdict` with findings and `ticket_failed` with `next: resume` and the findings as the failure output.
- [ ] `gates.kill_argument(paths)` runs two verifier sessions: the first writes the strongest rejection memo, the second adjudicates it point by point against the artifacts; the result is one verdict whose fail scopes claims down by filing a `writing` ticket.
- [ ] Tests use the fake launcher for pass, fail, and the two-thread kill argument; a test asserts the verifier's model always differs from the author's; live: one verdict on a closed M1 ticket.
