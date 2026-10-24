# 125 - A goal from the conversation

**What to build:** The owner states a goal in words ("held-out AUROC of at least 0.82, measured with `src/toy/eval.py`") and the session records it, with no file handed over.

On the toy's live setup (ticket 122, `docs/verification/m8.md`), the session recorded the owner's question as O1 but not the goal. `wayline objective add --measure FILE --sample ARTIFACT` needs a measure file and a sample artifact, and a setup or chat session holds read tools and the routed verbs only: it can write neither. No verb adds a measure to an objective already recorded either. The owner had to write `owner/measure.json`, train a sample by hand, and hand both over; the goal then became a second objective, O2, beside the question it measures.

- A goal's measure is given on the command line, field by field (`--metric`, `--direction`, `--target`, `--split`, `--eval-command`, `--min-seeds`), as well as through `--measure FILE`.
- A verb gives an open objective its goal (`wayline objective goal <id> ...`, or the name the verb table settles), so a question and its number stay one objective.
- With no sample yet, the goal is recorded as unchecked and checked by code on the first artifact a ticket of that objective produces; a command that prints no number there sends the goal back to the owner as a decision ticket, the way `objective add` refuses it today.
- The setup reference and the routing table use the new form; the chat may run it.

**Blocked by:** None - can start immediately. It touches the objectives module, the verb table, and `skills/wayline/`.

**Status:** ready-for-agent

**GitHub:** (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (objectives, goals, and measures; talking with the project), 1 (the verb table); ticket 122's live record.

- [ ] An objective's goal can be recorded from a session holding only the routed verbs, with no file written by anyone.
- [ ] An open objective gains a goal without a second objective being made.
- [ ] A goal recorded without a sample is checked on the objective's first artifact, and a failed check reaches the owner.
- [ ] The setup reference and the routing table name the new form; the verb table changes in the same commit.
- [ ] Tests over a temporary project, and `python -m unittest` passes.
