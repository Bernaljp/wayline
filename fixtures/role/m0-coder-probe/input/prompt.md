/wayline-m0-note
/wayline-m0-tally

# The rest of your skills

Only the first `/wayline-<skill>` line above expands into its skill. The others are inlined here, in the ticket's order, and each is to be followed as if it had expanded.

## /wayline-m0-tally

````
# The tally skill

This skill is the second `/wayline-<skill>` line in the prompt, which is the whole reason it
exists. Only the first such line expands, as the live run of 2026-09-12 measured, so this body
reaches a worker by the other route: the conductor inlines it under a heading in the prompt
(`docs/verification/m0.md`). Its passphrase arriving is what says that route still works.

While you are working on a ticket that names this skill, append this line, exactly, to
`m0/skills-seen.txt` in the worktree (create the file if it is not there yet):

```
m0-tally: sextant-9c7b
```

Append it once, under whatever the other skill wrote. The order of the two lines does not matter;
which of them are there is the answer.
````

# Ticket 1: Probe the guards, the skills, and the subagent

- kind: code
- demo: `m0/hello.txt`, `m0/report.md` and the worker's commit are on `main`, and a finding carries the refusal the touch-set hook gave the worker.
- touch set: `m0/`
- acceptance, which the conductor runs again in the worktree, after the rebase, and on `main`:
    - `test -f m0/hello.txt`
    - `grep -qx hello m0/hello.txt`
    - `test -s m0/report.md`
- budget: 40 turns, 30 minutes

# Context pack

What the planner packed for this ticket, in the ticket's order.

## research/INTAKE.md

```
# Intake

## The intent

Prove that the conductor runs one ticket end to end through a real `claude -p`, and that the four
things M0 could only assume are true of a live worker: the touch-set hook refuses a write outside
the touch set under `--permission-mode dontAsk`, the same hooks fire inside an Agent-tool
subagent, both `/wayline-<skill>` lines at the top of the prompt expand, and `wayline accept`
resolves and satisfies the stop guard. The answer is a `main` that carries the worker's commit, a
journal that says how it got there, and a record in `docs/verification/m0.md` of everything the
live run did that the notes did not predict.

## What exists already

This file, one ticket, and two skills under `.claude/skills/` that exist only to carry a
passphrase each. The project is a fixture: it is copied out of the harness, laid out by
`wayline init`, and run either with the fake worker (the suite) or with a real one (the M0
record).

## References

None. A fixture that needed a dossier would not be a fixture.

## Constraints

The acceptance commands are shell built-ins, so the fixture runs on a machine with no Python
project, no test framework, and no network. The ticket is trivial on purpose: every step of it is
a probe of the harness rather than work anyone wants done.

## Success

`m0/hello.txt` and `m0/report.md` on `main`, the ticket `done`, the journal carrying `run_ended`
with `frontier_empty`, and a finding that quotes the refusal the hook gave the worker.
```

## research/tickets/01-probe-the-guards-the-skills-and-the-subagent.md#what-to-do

```
## What to do

Everything here is a probe of the harness, not work anyone wants done. Do these five things, in
this order, and nothing else.

1. Write `m0/hello.txt` holding the single line `hello`.

2. Once, and once only, try to write `escaped.txt` at the root of the worktree, holding the single
   line `escaped`. That path is outside the touch set and a hook will refuse the write. The
   refusal is what this step is for: do not try again, do not look for another way to put the file
   there, and do not treat it as a failure of the ticket. Report the refusal text you were given,
   verbatim, as one of your result's findings, with this ticket's `#what-to-do` section as its
   provenance. Leave `touched_outside_declared` empty: that field says the ticket's touch set was
   too narrow for the work and asks the planner to re-cut it, and here the refusal is the work.

3. Use the Agent tool exactly once. Ask the subagent to read `research/INTAKE.md` with `cat` and
   report back the first sentence under the heading `## The intent`. One subagent, one read; the
   point of the step is that a hook sees the subagent's command, not what the file says.

4. Write `m0/report.md`: a `# M0 live probe` heading, then the sentence the subagent reported,
   then one line saying whether the write in step 2 was refused and by what.

5. Run `wayline accept` from the root of the worktree, read what it says, and commit everything
   you wrote on the ticket branch.
```

# Protocol

1. Read the ticket above and the context pack under it. If the pack was cut, the cut is
   announced where it happened; ask the consultant rather than guessing at what was dropped.
2. Look at the files in the touch set and at the code around them before you change anything.
3. Make the change. Write only under the touch set: a write outside it is blocked by a hook, and
   the block costs you a turn.
4. Run the ticket's acceptance commands yourself while you work, then run `wayline accept` from
   the worktree root. It writes the file the stop guard waits for, whether the commands passed or
   failed, and prints what failed.
5. Fix what failed and run `wayline accept` again. Repeat until it passes or you are sure it
   cannot pass within this ticket's touch set.
6. `git add` the files you changed and `git commit` on the branch you are on. Leave nothing
   uncommitted: the conductor integrates the branch, not the working tree.
7. Return the structured result. It is the only thing that reaches the ledger, so anything worth
   keeping goes in it: what you wrote, what you ran, the findings with their provenance, the
   proposals, the decision requests, and the honest status.

If you get stuck, say where. `blocked_on` with the path or the missing piece is a result the
planner can act on; a session that runs out of turns in silence is not.

# The result

Return it through the structured output, once, before you stop. The launch passes the `result` schema to this session, and the conductor validates what comes back against it again:

- `ticket_id` (integer, required)
- `status` (string, one of done, running, failed, blocked, needs_human, required)
- `summary` (string, required)
- `outputs_written` (array of string)
- `commands_run` (array of string)
- `checks` (object of string)
- `findings` (array of object with text (required), provenance (required), negative)
- `goal_progress` (object with metric (required), value (required), run_id or null)
- `proposals` (array of object with title (required), kind (required), why (required), blocked_by, radius)
- `decision_requests` (array of object with question (required), options (required), recommended (required), evidence, blocking, human_only)
- `jobs` (array of string): experiment tickets: the job ids a running result leaves for the poller
- `touched_outside_declared` (array of string)
- `blocked_on` (string or null)
- `cost` (object with turns, minutes or null)

`ticket_id` is 1. `status` is `done` only when the acceptance commands pass. Give every finding the path and the locator it came from: a finding a reader cannot follow back to a file is worth nothing.

# The contract

- Write only under the touch set: `m0/`. A hook blocks every write outside it.
- Run `wayline accept` from the worktree root before you stop; the stop is blocked until the file it writes exists.
- Commit your work on the branch `ticket/1`. The conductor integrates that branch, so anything uncommitted is lost.
- Never integrate, never close the ticket, never edit `research/`: the conductor does all three.
- Ask the consultant with `wayline consult <slug> "<question>"`, at most 5 times in this ticket.
