# 135 - The plotter writes the harness's tag form

**What to build:** A drawing's sentences carry provenance tags in the form the linter reads, so a drawing fails only on what it claims, never on how it spells a tag.

On the toy's live run (ticket 122, `docs/verification/m8.md`), drawings R4 and R5 failed their machine acceptance after one resume each. Their sentences ended in tags written `[res:drawings/R4-1/numbers.json#max_sigmoid_minus_true]`; the harness reads only `{res:...}` (`wayline/drawings.py`, `_RES_TAG`; the provenance linter likewise), so the linter called them untagged claims. The plotter's role prompt (`roles/plotter/agent.md`) never states the tag form, and the acceptance message, "a claim sentence ends with at least one provenance tag", does not show it either, so the resume guessed the same form again. Drawings R2 and R3 had happened to use the right one. (R4's numbers check also caught a sentence whose "±8.4" its locator did not hold: that part of the failure was right.)

- The plotter's prompt states the tag form with one example, as the worker and analyst prompts do.
- The linter's message for an untagged claim names the expected form, and when a sentence ends in a bracketed `[res:...]` or `[code:...]` it says so: "tags are written {res:...}".
- A check over every role prompt that asks for tagged sentences: each states the form.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#342](https://github.com/Bernaljp/wayline/issues/342) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (drawings and plots; the provenance linter's tags), 9 (the provenance linter); ticket 100; ticket 122's live record.

- [ ] The plotter's prompt names the `{res:...}` form; a test reads every role prompt that asks for tags.
- [ ] A sentence ending in `[res:...]` fails with a message naming the right form.
- [ ] `python -m unittest` passes.
