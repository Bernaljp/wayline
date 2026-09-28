# 68 - A tier up carries the last failure

**What to build:** A tier up after a failure starts its fresh session knowing what failed. Its prompt carries the last failure output, with a failed verdict's findings, as a resume's message already does.

Today a tier up opens a fresh session on the ticket as the planner wrote it. The findings the conductor wrote into the ticket's `## Result` never reach that prompt. When the ticket's earlier work is already on `main` and passes its machine criteria, the new session finds nothing to do and returns `done` with no diff. In 51's live run that attempt took 19 s, and only the later `resume` did the work (`docs/verification/m7.md`, "What differed, and what it found in the harness", item 1).

This affects any integrated ticket whose verdict fails and then tiers up.

**Blocked by:** 70 (The rung ladder without Fable). Both edit the escalation chain's tests, and this ticket's are written against the new rung ladder.

**Status:** done

**GitHub:** [#165](https://github.com/Bernaljp/wayline/issues/165) (mirror; the local file is the source)

**Milestone:** after M7 (v1.0.1). **Spec:** Implementation Decisions 5 (the conductor and the escalation chain), 16 (the escalation chain by rung), 3 (the prompt); 51's live record in `docs/verification/m7.md`.

- [x] A tier-up attempt's prompt carries, in a section of its own, the last failure output of the attempt before it, in the text a resume sends. After a failed verdict, that includes the verdict's type, its model, and its findings. After a failure the machine criteria caught, it includes their output.
- [x] The section survives a restart. An attempt relaunched from the journal carries the same text, the way a fallback's notes survive in `fallback.json`.
- [x] An attempt whose ticket has not failed before carries no such section.
- [x] Tests by journal replay with the fake launcher:
  - a ticket integrated on `main` whose verdict fails and tiers up gets a prompt holding the findings;
  - a restart relaunches it with the same section;
  - a first attempt carries none.
- [x] The changelog names the change under the next release.
- [x] `python -m unittest` passes.
