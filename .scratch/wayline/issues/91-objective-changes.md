# 91 - Objective changes

**What to build:** Objectives change as results come in, but no worker closes its own question. A ticket result and a verdict gain `objective_proposals[]`, each `{kind, objective, reason, evidence, feasibility}`:

- `kind` is one of `add`, `answer`, `park`, `drop`, `reframe`, or `reopen`;
- `objective` names the objective, or gives the new question's text for an `add` and a reframe's successor;
- `feasibility`, in the memo's row form, comes with `add` and `reframe`.

Whoever proposes never makes the change. Each proposal is journaled as `objective_proposed`.

**Judging.** A ticket that carries a proposal always gets its Type-B verdict, forced even at difficulty 1 and 2. In the same session the verdict judges each proposal "upheld" or "not upheld", with a reason. A proposal made inside a verdict goes straight on. One not upheld is journaled and listed in the account under "Not pursued".

**The batch.** Code gathers every upheld proposal into one open decision ticket, "Objective changes", which takes new proposals until it is answered. Its items are in the batch record of ticket 79 (marks: approve, decline). It pauses the unstarted tickets that serve only an objective that an upheld `park`, `drop`, `reframe`, or `answer` names. `add` and `reopen` pause nothing, and a declined proposal resumes what it paused.

**Who approves.** The owner approves under `interactive` and `checkpoints`. Under `autonomous` the decider takes each batch in one session:

- It answers, parks, and drops, never parking or dropping an objective the stopping rule names.
- It adds, reframes, or reopens only if the owner took `objective` off the human-only list at setup.
- Its additions are bounded by the radius. Under `strict` it adds none. Under `moderate` it adds a prerequisite, or a narrowing reframe that an open objective's own work raises. Under `exploratory` it may also add one new question within the intent per wave.
- Reopening a parked objective is allowed at every radius.

The decider reads the radius since 80, which fixed that charting defect; this ticket is where the radius first bounds what it adds. What the decider may not take waits on the owner, and the tickets it paused resume. The owner's word in the conversation applies directly through `wayline objective` verbs, with no proposal and no verdict.

**Answers.** Code writes a goal "reached" from the measured values (ticket 87). Another objective's answer is written by the verifier that upheld it, never by the worker. When the owner or the decider chooses "answer it as it stands" (here or at the empty frontier), one fresh verifier session per objective on `opus high` writes it. Either answer passes the numbers and locator checks, and code writes it as a Discussion passage.

**When approved:**

- An objective answered, parked, or dropped parks the unstarted tickets serving only that objective, journaled as `ticket_cancelled` with the reason. A ticket serving several keeps going while one of them is open.
- Claims tied only to closed objectives are **set aside**: kept in the spec, shown as set aside in `SPEC.md`, and back when an objective reopens.
- A reframe re-ties claims and tickets to the successor, and code writes a Discussion passage.
- Reopening an answered or dropped objective is the owner's alone. The old answer is kept as superseded, and the planner cuts fresh tickets.
- A claim no objective asked for is a result under "Beyond the objectives" when its evidence holds, and an `add` when it needs more work.
- A batch still waiting when the frontier empties folds into the empty-frontier ticket.

Decision 4's "change the goal or the data" becomes "change a goal's measure, or the data". Adding, answering, parking, dropping, reframing, and reopening an objective leave the irreversible list. A stall proposes nothing, and position is never re-run for a new objective unless the owner asks.

Not part of this ticket:

- the spec amendment an added or reframed objective gets (92);
- sorting a dropped objective's concerns again, which 96 built (asking it inside this ticket's answer is this ticket's);
- the marks view itself (112).

**Blocked by:** 79 - Batches and marks; 80 - The front door reads objectives; 81 - Specify and the plan name objectives; 86 - Passages and the five sections; 89 - The account. It blocks 92, 109, and 112.

**Status:** done

**GitHub:** [#238](https://github.com/Bernaljp/wayline/issues/238) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("How objectives change as results come in"; "Defects found while charting": the decider reads the radius; "Vocabulary the build adds": `objective_proposals` on `result` and `verdict`, the `objective` event with `by` and `proposal`, `objective_proposed`, set-aside standing); decisions 2 (the event table: `objective`, `objective_proposed`, `ticket_cancelled`), 4 (the irreversible list; "change a goal's measure, or the data"), 10 (the decider), 11 (the Type-B verdict), the schemas list (`result`, `verdict`, `spec`); M8 criterion 2; user stories 106, 107, 108, 110, 111.

- [x] `result` and `verdict` gain `objective_proposals[]` with the six kinds and their fields, and each proposal is journaled as `objective_proposed`.
- [x] A ticket carrying a proposal always gets its Type-B verdict, at every difficulty, which judges each proposal upheld or not with a reason. A proposal not upheld goes to the account's "Not pursued".
- [x] Code gathers upheld proposals into one open "Objective changes" decision ticket whose items are in a batch. It pauses only the unstarted tickets serving solely an objective a `park`, `drop`, `reframe`, or `answer` names, and a declined proposal resumes them.
- [x] Under `autonomous` the decider takes the batch in one session within the rules: never parking or dropping a named objective; adding, reframing, or reopening only with `objective` off the human-only list; additions bounded by the radius it now reads; reopening a parked objective at every radius. What it may not take waits on the owner.
- [x] An objective's answer is written by the upholding verifier, or by one fresh `opus high` verifier per objective for "answer it as it stands". It passes the numbers and locator checks and becomes a Discussion passage written by code.
- [x] Approval cancels the unstarted tickets serving only a closed objective with `ticket_cancelled`, sets aside claims tied only to closed objectives (shown in `SPEC.md`, restored on reopen), re-ties claims and tickets on a reframe, and keeps a superseded answer on an owner's reopen.
- [x] The owner's word applies directly through the objective verbs with no proposal or verdict. Decision 4's wording and the irreversible list change as decision 17 says.
- [x] When the answer drops an objective, its concerns go back to sorting inside the same "Objective changes" answer. Ticket 96 built the re-sort as a `concern` decision ticket of its own after setup, and a grill question during setup; inside this answer it is asked there instead.
- [x] Tests:
  - replayed journals for a proposal upheld and batched, one not upheld, a decline resuming paused tickets, the decider's batch under each radius, a reopen, and a set-aside claim restored, idempotence included;
  - the fake launcher for the verdict's judgment, the decider's batch, and the answering verifier.
- [x] The event table of decision 2 and the schemas list gain these rows in the same commit as the code.
- [x] `CHANGELOG.md` under `## Unreleased` describes how objectives change.
- [ ] `python -m unittest` passes.
