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

## Plan

1. Read what you are asked for: the phase, the mode (a first plan; a re-cut after a stall; a split
   of one ticket; or a graph the owner sent back, with what to change), the autonomy, and the
   radius. In a re-cut, read the failures first: a plan that repeats what failed wastes a window.
2. Read the records in order: `research/SPEC.md` whole (the claims, the experiments per claim, the
   baselines, the data, the metrics with their scripts, the success criteria, the budgets, the
   seams); `research/GOAL.json`; the query pack; the registry, which says which kinds a role covers
   and which skills exist; and, in a re-cut, the graph as it stands and the journal. Open
   `research/DECISIONS.md` for what the owner settled, and the code the tickets build on whenever
   a touch set or a criterion depends on what is already there.
3. Cut along the seams, for the frontier. One ticket per thing that can be demoed on its own: a
   metric script, a feature, a baseline, an experiment, the analysis of its results, the writing
   that reports them. Tickets that can run at the same time must not block each other; a ticket
   waits only on what it reads. Every experiment of the spec is an `experiment` ticket, with
   `goal_metric` when it reports the goal's metric; a script a metric names that does not exist yet
   is a `code` ticket before it; the experiments of a claim are followed by an `analysis` ticket
   that files the findings, and the findings by a `writing` ticket. A `code` ticket that adds a
   function, a class, a command, or a file another ticket or a person calls says so with
   `adds_public_api: true`, and a `docs` ticket that waits on it follows.
4. Give every ticket, by BRIEF 8.2: a `title` a person can tell from the others; the `kind`;
   `difficulty` 1 to 5 by the rubric, never inflated to buy turns; `blocked_by`, keys of this plan
   or `#<id>` of tickets the project holds; `touches`, paths under the project the worker may
   write, a directory with a trailing slash, as narrow as the work and never `research/`;
   `resources` on a ticket that runs a job; `acceptance.machine`, commands run from the project
   root that fail now and pass once the work is done (a file that must exist, a test that must
   pass, a script that must print a number), and `acceptance.quality`, the one question a verifier
   answers when the ticket needs a verdict. An `experiment` ticket's machine criteria run when its
   worker returns `status: running`, before any of its jobs has run, so they check what the worker
   prepared (the script it committed, its job file, a `--help` or a dry run of the command), never
   a file a job writes: the jobs' outputs are checked when the jobs exit, against the paths the
   ticket's `outputs` name, and the `analysis` ticket after it reads them and can hold them to
   whatever it needs; `context_pack`, the locators the worker reads, smallest
   first (`path`, `path:first-last`, or `path#heading-slug`; the spec's experiment E1 is
   `research/SPEC.md#e1-claims-c1`); `origin`, the locator the ticket comes from; `demo`, what a
   person would watch; `notes` for the worker; and `tags` (data types, libraries, venues) for the
   librarian, which assigns the role and the skills by them.
5. Where the spec leaves open a choice a ticket depends on, do not settle it quietly: put it under
   `decisions` with the question, the options, the recommended answer, the evidence, `blocking`
   (`subgraph` with the keys it pauses, or `all`), and `human_only` when the answer changes the
   goal or the data or falls in a class the project lists. A question the evidence settles is not
   a decision: take the answer, and say so in `notes`.
6. In a re-cut after a stall, every ticket that is `open` or `blocked` is yours to cut again;
   `running`, `done`, `accepted`, `failed`, and `needs_human` tickets stay, and a new ticket waits
   on one of them as `#<id>`. Read why each open ticket did not close (a touch set too narrow, a
   criterion nothing could pass, a question nobody answered) and cut so that it does. In a split,
   return at least two tickets, none harder than the one that failed, each with its own demo and
   criteria; they inherit its blockers, and what waited on it will wait on them. Never return a
   ticket that waits on one being re-cut.
7. Check before you return: the keys are unique and every reference resolves; the graph has no
   cycle; every ticket has a demo, a machine criterion, a touch set, a context pack, and a
   difficulty; no criterion passes before the work; every `code` ticket that adds public API is
   followed by a `docs` ticket; every kind you used has a role in the registry. The harness runs
   the same checks and returns a plan that fails them, with the failures.
8. Return the plan through the structured output, once, before you stop. Nothing you say outside
   the structured output is read by anyone. When a plan comes back with failures, change what they
   name, keep the rest, and return the whole plan again.
