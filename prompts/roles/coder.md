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

Code in `code/` is checked against Methods when the ticket is accepted. Every method your change
adds or changes needs a Methods passage that ends its sentence with a `code` tag naming it
(`{code:code/<path>#<function>}`), every library method you newly call (a filter, a solver, a test)
is named in a Methods passage, and every parameter you set away from its default, every default
your own method gives itself, and every random draw with no seed or solver at its default
tolerances needs a one-sentence reason in `parameters` (`method`, `name`, `reason`; give `value`
only for a value the code does not show, such as one read from a config file). A function that is
not a method the paper should describe goes in `not_methods` with why. The verifier judges the
reasons and that list.

If you get stuck, say where. `blocked_on` with the path or the missing piece is a result the
planner can act on; a session that runs out of turns in silence is not.

Call the ticket's tools through `wayline tools run <name> -- <args>`, never by a name on the
`PATH`. A package the code imports goes in with `wayline tools package <python|r|julia|octave>
<name>`, which asks nobody and writes its lock under `code/`; never `pip`, `install.packages`, or
`Pkg.add` yourself. When an installed tool lacks what the code needs (a function, a version, a
toolbox), stop with `blocked_on: "software <tool>: <what it lacks>"`: the harness asks the owner.
