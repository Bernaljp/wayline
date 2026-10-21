# 109 - The wayline skill and setup as one conversation

**What to build:** The owner talks with a project normally, in any Claude Code session in the project (Remote Control included), and never types a verb or a label. One owner-facing skill, `wayline`, routes everything. Its body is the routing table, and its reference files hold the procedures:

- setup: intake, position, the grill, the stopping rule and budgets, specify, and the plan;
- evolve.

The phase skills `wayline-intake`, `wayline-grill`, `wayline-plan`, `wayline-evolve`, and `wayline-paper` retire. `wayline-interval-claims` stays, and no skill calls another skill. The block `init` writes into the project's CLAUDE.md gains one line: when the owner talks with a session here, use the `wayline` skill.

The session follows three rules:

- **Records without asking** what is clear, and reads each record back in one line with its id. That covers:
  - materials, references, and the documents it sorts;
  - objectives and goals, and the owner's passages;
  - answers to waiting decision tickets, with the owner's words as the rationale;
  - merges and renames of results, and a reference handed over;
  - harness feedback, and requests for work.
- **Asks one line** only when something is unclear: objective, goal, or remark; which section; which decision ticket; project or harness; consolidation or paper order; a document's kind.
- **Confirms first**, saying what will happen and what it costs, for a paper order, a consolidation, and anything on the irreversible list. A human-only class the owner states needs no confirmation.

The session never does the research. It answers from the digests code renders. Work the owner asks for becomes one ticket the session drafts through a checked verb, and code places it in the graph. A new line of work that needs a claim goes through specify. A question about a reference goes to the consultant. Nothing lives only in the conversation.

A batch is shown as text only at five items or fewer, otherwise as one line with the count and a link to the marks view. Under `autonomous`, a conversation the owner opens starts with "Decided for you" as one numbered item recommending "let them stand", and the owner's yes records the review.

Setup is one conversation, and it is the only time an automated run asks the owner anything. Besides intake's settings (autonomy, radius, the fallback and ladder consents, and the `human_only` classes, which can now name `objective` and `concern`), it settles these in order:

1. the documents' sorts and, at a start midway, the merges, contradictions, and concern placements, in one batch;
2. the objectives, open or parked, with "Do the inherited results hold?" proposed at a start midway;
3. the concerns: one question per proposed objective with its concerns, one for the order, and one for the declines;
4. the missing material, in one question;
5. the stopping rule and budgets, in one question;
6. the software the planned work needs, in one question;
7. the code repository's shape, remote, visibility, and license, in one question;
8. under `autonomous`, whether the decider judges the paper order and for which venue;
9. the front matter, which may be left for later;
10. every important unresolved reference, including those still retrying.

Under `autonomous`, nothing about any of these is asked after setup. The user guide (124) says how to start `claude remote-control`, and no unit is installed for it.

Not part of this ticket:

- the skill's paper reference file, which 115 writes with the paper order;
- the dashboard's chat, which loads this skill (114);
- the verbs themselves, each built by the ticket owning its record. This ticket routes to them.

**Blocked by:**
- 79 - Batches and marks
- 80 - The front door reads objectives
- 81 - Specify and the plan name objectives
- 82 - Project tools and the software decision
- 85 - The code repository
- 87 - Keep-if-better per goal, the stopping rule, and budgets; GOAL.json retires
- 88 - The owner's passages, consolidation, and the linter's new tags
- 89 - The account
- 90 - Results and the general report
- 91 - Objective changes
- 96 - Critiques and concerns
- 97 - Verifying inherited results
- 105 - References rendered and important ones raised

It blocks 114 and 115.

**Status:** done

**GitHub:** [#256](https://github.com/Bernaljp/wayline/issues/256) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (talking with the project; setup, at every autonomy; objectives, goals, and measures: the owner talks normally; sections and passages: "compile"; the account: the autonomous opening), 1 (the verb table: the drafted-ticket verb), 10 (intake's `human_only` classes, the phase skills); milestone M8 criterion 15 and the M4 criteria it supersedes for a project at `research_version` 2; user stories 104, 136, 165, 166, and 172.

- [x] `skills/wayline/` holds a body that is the routing table and reference files for setup and evolve. The five phase skills are removed, `wayline-interval-claims` stays, and no skill names another skill to call.
- [x] The routing table names only the verbs the conversation may run, and each is a CLI verb that exists. The registry's skill tests and the docs check pass over the new tree. The tickets before it planned these names, which the table uses unless the verb table says otherwise: `objective add` (76), `mark` (79), `document add --kind` (84), `passage add` and `consolidate <section>` (88), `review <id> stand|reverse` (89), `result merge` and `result rename` (90), `specify --amend <objective>` (92), the outline's verb (104), and the hand-over command (71).
- [x] `init`'s CLAUDE.md block gains the one line about the `wayline` skill, and refreshing an existing block adds it without duplicating it.
- [x] The skill's record, ask, and confirm rules are stated as above, with the one-line read-back carrying the new record's id.
- [x] The drafted-ticket verb takes a ticket the session drafts, checks it against the ticket schema and the touch-set rules, and has code place it in the graph. A draft naming `research/` is refused.
- [x] Intake's `human_only` classes accept `objective` and `concern`.
- [x] The setup reference asks the ten items above in order, each as one question where the spec says one. Under `autonomous`, the setup ends only when every item is answered or explicitly left for later where the spec allows it (the front matter).
- [x] Under `autonomous`, the skill opens a conversation with "Decided for you" as one numbered item when any decision is not yet reviewed, and a yes journals `reviewed` for each one.
- [x] A batch of more than five items is shown as one line with its count and a link to the marks view.
- [x] Nothing installs a unit for `claude remote-control`; how to start it in a project is the user guide's (124).
- [ ] Tests:
  - the skill tree's shape and routing table against the verb table;
  - the CLAUDE.md block;
  - the drafted-ticket verb's checks over a temporary project;
  - the `human_only` classes;
  - the recorded setup conversation fixture (decision 12's fixtures) updated to the new setup order, run on demand.
- [x] The verb table of decision 1 gains the drafted-ticket verb in the same commit as the code.
- [x] The changelog's `## Unreleased` section describes the `wayline` skill and the phase skills' retirement.
- [ ] `python -m unittest` passes.
