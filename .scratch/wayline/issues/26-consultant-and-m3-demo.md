# 26 - The consultant and the M3 demo

**What to build:** Any session asks a consultant one question about one dossier and gets an answer with locators, a confidence, and "not in source" when that is true; every exchange is appended to the dossier's question log by code; a question the dossier cannot answer at L1 triggers a promotion inside the budget or a decision ticket beyond it; a worker may ask at most five questions per ticket. Then the M3 demo runs live end to end.

**Blocked by:** 24 (The absorb workflow for L2), 25 (Code dossiers)

**Status:** ready-for-agent

**GitHub:** [#27](https://github.com/Bernaljp/wayline/issues/27) (mirror; the local file is the source)

**Milestone:** M3 Dossiers. **Spec:** milestone M3 criteria 8 to 11 and its demo; Implementation Decisions 9 (the consultant); map ticket 41.

- [ ] `roles/consultant/` exists with read-only tools; `wayline consult <slug> "<question>"` launches `claude -p "<question>" --agent consultant --add-dir <project>/research/refs/<slug> --disallowedTools Edit Write --json-schema consultant_answer.json` through the launcher with the same `dontAsk`, `--permission-prompts none`, stream-json flags and the `NotebookEdit Bash Agent WebFetch WebSearch` removals as every read-only role.
- [ ] Inside a Workflow script, `agent(question, {agentType: 'consultant', schema})` returns the same answer shape and the script returns it to code; `absorb.js` gains an optional consultant call for a reader's clarification question so the path is exercised.
- [ ] The answer (`answer, locators[], confidence, not_in_source, promote_requested`) is validated; the ledger appends the exchange to `refs/<slug>/qa_log.md` and journals `consulted`; `promote_requested: true` calls the promotion function of ticket 23.
- [ ] `wayline consult` reads `WAYLINE_TICKET`, counts the ticket's `consulted` events, refuses the sixth question, and is on the coder's, experimenter's, and analyst's allowed tools.
- [ ] Live M3 demo, recorded in `docs/verification/m3.md`: ten references get L0 records; four get L1 skims; one primary paper with code is promoted to L2 with its inventory extracted, every item covered, figures described, and its recipe verified by running it; three consultant questions are answered with locators; one question triggers a promotion; the OPEN-16 numbers in `policy.json` are revised from the measured chunk counts and fan-out cost; the repository is tagged `v0.4.0`.
