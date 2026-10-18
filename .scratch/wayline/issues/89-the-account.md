# 89 - The account

**What to build:** What wayline did leaves the general report and moves to `research/ACCOUNT.md`, so the reports stay about the science and the audit stays complete. Code renders the account in the same pass as the reports. It is committed each wave, read-only under the reports' edit rule (an edit is committed as it stood and listed, never taken in), and journaled through `report_rendered`.

Its first line says that code writes it, that the research is in `REPORT.md`, and that anything the owner wants to tell the project goes to the conversation. Its sections follow, in order, with empty sections left out:

- **Where the project stands.** One paragraph: running since when, or ended and why; each objective's status; the stopping rule; each budget spent against its limit. The same text opens the end notice.
- **Decided for you.** Each decider decision and conductor default not yet reviewed, one line each, with:
  - when it was made, what it decided, the answer, and the confidence;
  - "on Opus while Fable was spent", where it applies;
  - a link to the rationale where it already lives.

  Superseded decisions leave the list.
- **Waiting on you.** Decision tickets for the owner, tickets needing a person, proposed global harness changes, important unresolved references, reports edited and not yet turned into passages, a repository still private at the order, and the outline's open proposals as one line with their count. Proposed global harness changes use one wording: `wayline evolve --apply <id>`.
- **Changed without asking you.** The owner's passages a later passage replaced, with the reason and evidence, and the merges made at setup.
- **Runs.** The latest run in full:
  - its start, end, reason, and waves;
  - each ticket's outcome with its verdict type and model;
  - the run-end gates and the scope-downs they filed;
  - the drawings with their tokens, turns, and minutes, and what they left out;
  - the verdicts and decisions made on Opus while Fable was spent;
  - wall-clock and GPU hours, pauses and holds, and peak utilization;
  - turns, minutes, and tokens per ticket from `ticket_result.usage`, with no dollar figure, since none is journaled.

  Earlier runs get one table row each.
- **Not pursued.** Parked proposals with their reason, parked tickets, and proposals not upheld.
- **Library.** Papers by dossier level, promotions not read in full, and dossiers that now resolve to a different work.

**Reviewing.** A decider decision stays listed until the owner lets it stand or reverses it, by saying so or by marking it. Each one is an item in the batch record of ticket 79 (marks: stand, reverse), and the review is journaled as `reviewed` through `wayline review <id> stand|reverse`. A reviewed decision stays counted in its run. A reversal is the owner's own answer through the existing verbs (`grill answer --revise`, the owner's answer to the decision ticket, or admitting a parked proposal). It makes that decision human-only so the decider never takes it again, and it never stops the run. "Undo it", said without what to do instead, reopens the decision human-only and asks in one line.

**One end notice per run end.** The conductor sends it after the gates, or the tick sends it when the conductor died first. It opens with the account's first paragraph plus "N decided for you, M waiting on you" and the path. It replaces the split between the conductor's and the tick's notices. Other notices follow the autonomy:

- Under `interactive`, each decision ticket and notice reaches the phone as it arises. That covers a `needs_human` result, an important unresolved reference, and a replaced passage.
- Under `checkpoints`, decision tickets notify as they open, and other notices wait for the next conversation or the end notice.
- Under `autonomous`, only the end notice and a login's expiry notify after setup.

`wayline status` stays the live view. Its decisions narrow to those not yet reviewed, and it gains one line: "Account: N decided for you, M waiting on you: research/ACCOUNT.md". The events table of v1.0's report goes. The sections of v1.0's `REPORT.md` that describe what wayline did move here before ticket 90 rewrites the general report.

Not part of this ticket:

- the general report and the R ids (90);
- the Library's pointer to References' "Not yet resolved" list (105);
- the conversation opening with "Decided for you" under `autonomous` (109);
- the Run view's account in the popup viewer (110).

**Blocked by:** 79 - Batches and marks; 86 - Passages and the five sections; 87 - Keep-if-better per goal, the stopping rule, and budgets; GOAL.json retires. It blocks 90, 91, 105, 109, 110, 112, and 115.

**Status:** ready-for-agent

**GitHub:** [#236](https://github.com/Bernaljp/wayline/issues/236) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("The account"; "Talking with the project": notices per autonomy; "Defects found while charting": one wording for applying a global change; "Vocabulary the build adds": `reviewed`, the `report` field on `report_rendered`); decisions 1 (the verb table: `review`; `status`), 2 (the event table: `reviewed`, `report_rendered`), 7 (the tick's and the conductor's notices), 11 (the report), 12 (global changes proposed in the account), 15 (the verdicts and decisions on Opus while Fable was spent); M8 criterion 7; user stories 45, 78, 131, 132, 133.

- [ ] `research/ACCOUNT.md` renders by code in the same pass as `REPORT.md`, opens with its first line, holds the seven sections in order with empty ones left out, is committed each wave, and is journaled through `report_rendered` with `report: account`.
- [ ] "Decided for you" lists each unreviewed decider decision and conductor default with when, what, the answer, the confidence, the Fable note where it applies, and the rationale's link. Superseded ones leave.
- [ ] "Waiting on you" lists each kind decision 17 names, and every proposed global change reads `wayline evolve --apply <id>`.
- [ ] "Runs" shows the latest run in full and earlier runs one row each, with turns, minutes, and tokens per ticket from `ticket_result.usage` and no dollar figure.
- [ ] `wayline review <id> stand|reverse` journals `reviewed`. Each unreviewed decision is an item in an open batch with the marks stand and reverse. A reversal makes that decision human-only and never stops the run, and "undo it" without an instead reopens it human-only and asks.
- [ ] An edit to `ACCOUNT.md` is noticed by its hash, committed as it stood, listed in the next render's banner, and never taken in.
- [ ] One end notice per run end opens with the account's first paragraph, "N decided for you, M waiting on you", and the path, sent by the conductor after the gates or by the tick when the conductor died. Notices follow the per-autonomy rules.
- [ ] `wayline status` narrows decisions to the unreviewed ones and prints the account line.
- [ ] v1.0's report sections about what wayline did, and its events table, are no longer rendered into `REPORT.md`, and their content is in the account.
- [ ] Tests:
  - the ledger seam over a temporary project, asserting on the rendered file;
  - replayed journals for a run ended by each reason, a reviewed and a reversed decision, and a conductor that died before its notice, idempotence included;
  - the notifier fake under each autonomy;
  - `status` rendered from a fixture journal.
- [ ] The verb table of decision 1 and the event table of decision 2 gain these rows in the same commit as the code.
- [ ] `CHANGELOG.md` under `## Unreleased` describes the account and the end notice.
- [ ] `python -m unittest` passes.
