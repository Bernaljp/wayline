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

Call the ticket's tools through `wayline tools run <name> -- <args>`, never by a name on the
`PATH`. A package the code imports goes in with `wayline tools package <python|r|julia|octave>
<name>`, which asks nobody and writes its lock under `code/`; never `pip`, `install.packages`, or
`Pkg.add` yourself. When an installed tool lacks what the code needs (a function, a version, a
toolbox), stop with `blocked_on: "software <tool>: <what it lacks>"`: the harness asks the owner.
