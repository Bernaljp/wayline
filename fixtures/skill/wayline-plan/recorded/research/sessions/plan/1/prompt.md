# What you are asked for

The ticket graph of this project: phase P4, plan. The harness numbers what you return, has the librarian assign a role and skills to every ticket, runs the plan-time checks, writes `research/tickets/NN-slug.md` and `research/graph.json`, opens a decision ticket for every choice you report open, and, by the project's autonomy, asks for the graph's confirmation before the conductor runs it.

- the cut: the first cut of this project's graph
- autonomy: checkpoints; radius: moderate

# The records

Read them in this order; the spec is what the tickets implement, and nothing else.

## research/SPEC.md

```
# Spec: Do pairwise interaction terms improve held-out AUROC on the synthetic set?

Rendered by `wayline specify` from `research/spec.json`; change the spec by answering its confirmation with what to change, never by editing here.

## Question

On the toy generator's synthetic two-class set, does a logistic regression given all 28 pairwise products of x0..x7 reach a higher held-out AUROC on split_b than the same model without them, by at least +0.02 averaged over ten generator seeds, and does that gain survive a flexible model without products and vanish on a set with no planted interaction?

## Claims

- **C1.** Adding all 28 pairwise products to a logistic regression raises held-out AUROC on split_b by at least +0.02, mean over ten generator seeds, paired within a seed. (experiments: E1)
- **C2.** The products' gain is not matched by a small multilayer network on the raw features, so explicit products carry information a flexible model without them does not recover at this size. (experiments: E2)
- **C3.** The gain comes from the planted interaction: on a set generated with interaction 0 the products change held-out AUROC by less than 0.005. (experiments: E3)

## Anti-claims

- **A1.** No claim is made about real data: the set plants exactly one product, and the result is synthetic-only. (confirmed by: E3)
- **A2.** No product's coefficient is read as a discovery; if the gain appears on the null set, the method is fitting noise and C1 is withdrawn. (confirmed by: E3)

## Methods

- **logistic regression**: scikit-learn LogisticRegression with library defaults, installed in the project's own virtual environment (Q3), on the raw features, with and without the 28 pairwise products (Q4).
- **small network**: scikit-learn MLPClassifier on the raw features, its settings tuned by 5-fold cross-validation inside split_a with the same grid on every seed.
- **paired comparison**: Each seed generates a fresh 20000-row set, split_b its last quarter; each model is scored on split_b and differences are paired within a seed (Q5).

## Experiments

### E1 (claims: C1)

- design: For generator seeds 0-9 at the default signal and interaction, fit the logistic regression with and without products on split_a and score both on split_b; report the mean and standard deviation of the paired difference.
- baselines: B1
- data: D1
- metrics: auroc, auroc_gain
- success: mean paired auroc_gain >= 0.02 over the ten seeds
- budget: about 5 minutes of CPU

### E2 (claims: C2)

- design: On the same ten sets, fit the small network on the raw features and score it on split_b; compare with the with-products logistic regression, paired within a seed.
- baselines: B1, B2
- data: D1
- metrics: auroc, auroc_gain
- success: the with-products logistic regression beats the network by a mean paired margin above zero
- budget: up to 3 hours of CPU for the cross-validated grid

### E3 (claims: C3)

- design: Repeat E1 on sets generated with interaction 0 for seeds 0-9.
- baselines: B1
- data: D2
- metrics: auroc, auroc_gain
- success: absolute mean paired auroc_gain < 0.005
- budget: about 5 minutes of CPU

## Baselines

- **B1.** logistic regression on the raw features, no products (source: GOAL.json baseline; Q1)
- **B2.** small multilayer network on the raw features, no products (source: Q2, Q8; paper-b)
- **B3.** planted-only logistic regression (x2*x3 alone), an oracle reference, not a competitor (source: Q4)

## Data

- **D1.** toy/make_synthetic.py at default signal 1.0 and interaction 0.6, seeds 0-9, 20000 rows each; split_a the first three quarters, split_b the last (source: toy/make_synthetic.py)
- **D2.** the same generator at interaction 0, seeds 0-9 (the null control) (source: toy/make_synthetic.py --interaction 0)

## Metrics

- **auroc**: area under the ROC curve of the model's scores on split_b (script: `python3 toy/eval.py {artifact}`)
- **auroc_gain**: paired difference in split_b AUROC between the with-products model and its comparison, per seed, then the mean over seeds (script: `python3 toy/paired_gain.py {artifact}`)

## Success criteria

- C1 holds when E1's mean paired gain is at least +0.02 (the goal of GOAL.json). (experiments: E1)
- C3 holds when E3's gain is under 0.005 in absolute value; otherwise C1 is withdrawn (A2). (experiments: E3)

## Budgets

- GPU: 0 hours
- wall clock: 4 hours
- usage windows: not set
- notes: 4 hours of CPU wall clock in total (Q6); no GPU.

## Out of scope

- real datasets
- a sweep of the generator's interaction strength beyond 0 and the default
- product selection or any reading of which product matters

## Risks

- The network's cross-validated grid overruns the 4-hour budget. Mitigation: cap the grid at what fits 3 hours on the first seed, and keep that grid for every seed.
- The ceiling spread across seeds (0.7445-0.7511) is a third of the target gain. Mitigation: pair every comparison within a seed and report the paired standard deviation.

## Seams

- **the set**: toy/make_synthetic.py writes one CSV per seed and interaction; every experiment reads only those files.
- **the scores**: each fitted model writes predictions/<model>-<seed>.csv with a score per split_b row; toy/eval.py and toy/paired_gain.py read only those.
```

## research/GOAL.json

```
{
  "metric": "auroc",
  "direction": "up",
  "target": 0.02,
  "dataset_or_split": null,
  "held_out_split": "split_b",
  "eval_command": "python3 toy/eval.py {artifact}",
  "baseline": {
    "value": null,
    "source": null
  },
  "budget": {
    "gpu_hours": null,
    "wallclock": 4,
    "usage_windows": null
  },
  "stop_when": "goal_reached"
}
```

## research/kb/query_pack.md

```
# Query pack

- paper-a extends paper-b: the held-out protocol of paper-b is what paper-a's gains are measured under
```

# The registry

The librarian assigns every ticket its role and its skills from research/registry.json, by the ticket's kind and tags. A kind no role covers cannot be cut: a ticket of one comes back to you as a failure.

Roles, by the kinds they cover:
- `analyst` for analysis tickets: Analyses the manifested results of finished experiments and files findings whose provenance the manifest resolves.
- `coder` for code, docs, harness tickets: Implements one code ticket in its worktree and returns the structured result.
- `experimenter` for experiment tickets: Prepares one experiment ticket's detached jobs with wayline job add and returns status running with their ids.
- `reader` for dossier tickets: Reads a capped input (an L1 skim, or one absorb chunk) with no tools and returns a short structured record.
- `writer` for writing tickets: Writes report and paper prose under C8 from the findings and the knowledge base, ending every claim sentence with a provenance tag that resolves.
- no role covers `lit`, `figure`, `review` tickets; do not cut one, and say in `notes` what would need it

Skills, by kind and tags:
- none matches a ticket by kind yet, so every ticket's `skills` will be empty; that is expected

# The difficulty rubric

Difficulty sets the model, the effort, and the budget a ticket's worker gets (policy.difficulty):

- 1: mechanical, one file, fully machine-checkable. sonnet at low, a small budget.
- 2: a routine change, a known pattern, few files. sonnet at medium, a small budget.
- 3: a new code path or an experiment, numerical care; an independent verdict on the diff follows. opus at high, a medium budget.
- 4: design judgment, several modules, ambiguous acceptance; an independent verdict on the result follows. fable at xhigh, a large budget.
- 5: research-critical, the claim depends on it; the verdict is mandatory and the ticket is accepted only after it. fable at max, a large budget.

# What the journal says

Read it before you cut: what failed and why, what a person or the decider answered, and what progressed. A plan that repeats what failed wastes a window.

- 2026-09-13T06:18:47 decision of the grill or the owner by the owner: goal: `auroc` up to 0.85 on the held-out split `split_b`, measured by `python3 toy/eval.py {artifact}`, stop when `goal_reached`
- 2026-09-13T06:24:16 decision of the grill or the owner by the owner: Q1 What does the goal become, given that no model can reach 0.85 AUROC on split_b at the generator defaults? Answer: the +0.02 gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds
- 2026-09-13T06:24:17 decision of the grill or the owner by the owner: Q2 Which of the position memo's directions does the project take? Answer: moderate: nearest plus a flexible model without products as a second baseline
- 2026-09-13T06:24:19 decision of the grill or the owner by the owner: Q3 scikit-learn is not installed: what fits the models? Answer: install scikit-learn, but into a virtual environment of the project's own, not the tools venv
- 2026-09-13T06:24:20 decision of the grill or the owner by the owner: Q4 Which interaction terms does the with-products model get? Answer: all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery
- 2026-09-13T06:24:21 decision of the grill or the owner by the owner: Q6 What wall-clock budget does the project run under? Answer: 4 hours of CPU wall clock in total
- 2026-09-13T06:25:44 decision of the grill or the owner by the owner: Q5 What varies across repeats, and how many repeats are there? Answer: ten generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed
- 2026-09-16T23:03:03 decision of the grill or the owner by the owner: spec c39e5fdc08f3: confirm

# The paths you may open

The project is `/home/bernaljp/.claude/jobs/88bb50bb/tmp/plan-live/toy2`; open these with the Read tool when a record points into them:

- `research/SPEC.md` and `research/spec.json`: the spec, inlined above when it fit
- `research/DECISIONS.md`: what the owner settled, which binds every ticket
- `research/INTAKE.md`: the intent, the data, the constraints, the radius
- `research/refs/<slug>/dossier.json`, and `dossier.md` for a reference read in full
- `research/tickets/<n>-<slug>.md`: the tickets the project holds, listed above when there are any
- `research/journal.jsonl`: the whole journal, digested above
- the project's own code, for the touch sets and the criteria: what exists, and what a ticket has to add

# Protocol

The planner has one protocol per phase; the harness gives you the one below that names your phase.

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
   answers when the ticket needs a verdict; `context_pack`, the locators the worker reads, smallest
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

# The plan

Return it through the structured output, once, before you stop. The launch passes the `plan` schema to this session, and the harness validates what comes back against it again:

- `tickets` (array of object with key (required), title (required), kind (required), difficulty (required), blocked_by (required), touches (required), resources, inputs, outputs, acceptance (required), goal_metric, context_pack (required), origin (required), demo (required), notes, adds_public_api, tags, retry, required): the work tickets, in the order they are numbered; a decision ticket is never here, it is under decisions
- `decisions` (array of object with question (required), options (required), recommended (required), evidence (required), blocking (required), human_only (required), pauses (required), origin, required): one decision ticket per choice the spec leaves open, with what it pauses
- `notes` (array of string, required): what the planner could not cut or had to take a side on: a kind no role covers, a choice taken with the recommended answer

Keys are `T<n>`; a `blocked_by` or `pauses` entry is a key of this plan or `#<id>` for a ticket the project holds. `role`, `skills`, `status`, and the ids are the harness's, not yours.
