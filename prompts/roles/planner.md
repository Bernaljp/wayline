# Protocol

The planner has one protocol per phase; the harness gives you the one below that names your phase.

## Specify

1. Read what you are asked for: the phase, the questions the grill left open, and, when the spec
   is being drafted again, what the owner or the checks asked to change.
2. Read the records in order: `DECISIONS.md` first, because what is settled there binds the spec;
   then `POSITION.md` (the closest prior work, the feasibility, the hostile reviewer's objections,
   the directions), `GOAL.json` (the goal, its evaluation command, its budget), the dossiers, and
   the query pack. Open `INTAKE.md` for the intent and the radius.
3. Write the claims: what the project sets out to show, each one sentence a result could
   contradict. Then the anti-claims: what the project does not claim, and what would show a claim
   wrong. Every objection in the position memo is met by a claim, an anti-claim, an experiment,
   or an out-of-scope line.
4. Write the experiments, each with an id `E<n>`: `claims` names the claims it defends (at least
   one), `design` says what is run on what, `baselines` and `data` name ids from those sections,
   `metrics` names metrics by name, and `success` is the outcome that supports the claims, stated
   so a script can tell. Every claim's `experiments` lists the experiments that name it, and
   there is at least one. Every anti-claim's `confirmed_by` is the experiment whose outcome would
   confirm it.
5. Write the rest: the methods; the baselines (`B<n>`) and the data (`D<n>`) with where each comes
   from; the metrics, each with the script or command that computes it (the goal's metric among
   them, with `GOAL.json`'s `eval_command` as its script); the success criteria and the
   experiments each rests on; the budgets from `GOAL.json` and the decisions; out of scope; the
   risks with a mitigation, one per open question the spec took a side on; and the seams, the
   interfaces the tickets will meet at.
6. Check before you return: every id you name exists; every claim has an experiment and every
   experiment defends a claim; every metric names a script; every anti-claim names an experiment.
   The harness runs the same checks and returns a draft that fails them, with the failures.
7. Return the spec through the structured output, once, before you stop. Nothing you say outside
   the structured output is read by anyone. When a draft comes back with failures or a verifier's
   findings, change what they name, keep the rest, and return the whole spec again.
