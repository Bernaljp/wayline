# 128 - A rejected login holds the run

**What to build:** A session refused for its login holds the run as a login problem, with one notice, and fails no ticket.

On the toy's live run (ticket 122, `docs/verification/m8.md`), the units loaded `CLAUDE_CODE_OAUTH_TOKEN` from `~/.wayline/env`, and the service rejected it: every session ended at once with `is_error: true`, `terminal_reason: api_error`, and the text "Failed to authenticate. API Error: 401 Invalid bearer token". The launcher read that as "the result carries no structured_output (subtype success)": within one minute it resumed, split, and tiered up tickets 2 and 5 and the decider on #28, sent all three to `needs_human`, and a stall started a replan. `wayline rerun` then reopened them with the escalation state the failures had spent, so ticket 5 relaunched two rungs up. A chat message failed with the same misleading reason, since the dashboard unit kept the env file it started with. The tick's login check had said "the stored login ends at 2026-11-08, in 14.7 days": it reads the token's stored expiry and never asks the service. The run's own retrospective proposed two harness changes from this (change records 001 and 002 in the toy).

- The launcher recognises an authentication refusal (`api_error_status` 401 or 403, or "Failed to authenticate") apart from a missing structured output, for tickets, verdicts, the decider, the planner, the writer, and the chat.
- Such a refusal journals `paused` with a reason naming the login, notifies once, launches nothing more, and fails nothing: the refused attempt is relaunched, never resumed, after the pause, the way a session refused before its first turn already is (decision 15).
- The tick checks the login with a call that costs no turn, and an unpause follows a login that works again.
- A ticket failed by a login refusal before this lands can be rerun at its first rung (`wayline rerun --fresh`, or `rerun` clears steps no work was done in).

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#335](https://github.com/Bernaljp/wayline/issues/335) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 5 (the pause, the login warning), 15 (a session refused before its first turn), 16 (the escalation chain); ticket 122's live record.

- [ ] A recorded 401 result pauses the run with one notice and leaves every ticket's escalation state as it was; covered by replaying a fixture stream.
- [ ] The chat answers a 401 with "the login was refused" rather than a structured-output error.
- [ ] The tick notices a refused login.
- [ ] `python -m unittest` passes.
