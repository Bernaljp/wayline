# Intake

What the owner handed over, normalized by `wayline intake`. `harness.json` holds the same autonomy, radius, budgets, and human-only classes, and is the copy the conductor reads.

## Intent

I want to understand which gene programs separate the two cell states in our expression table, and whether the programs the papers below describe show up in our data at all. I care more about an honest answer than a positive one.

## References

- arXiv:1706.03762
- https://doi.org/10.1038/s41592-019-0686-2
- Highly accurate protein structure prediction with AlphaFold

## Data

- `data/expression.csv` (a file, 63 bytes)
- as delivered the table holds 2 cells (c1 in state A, c2 in state B) and 3 genes (GENE1, GENE2, GENE3), with columns cell,state,GENE1..GENE3
- no held-out split was stated

## Code

None.

## Constraints

- The owner: 'I care more about an honest answer than a positive one.'
- Assumed: nothing in data/ is held out, because the owner named no split.
- Assumed: the data stays on this machine, because the owner did not say whether it may leave.
- Assumed: the table's two states, A and B, are the 'two cell states' of the intent.
- Assumed: a table of 2 cells and 3 genes is too small to find separating gene programs statistically; the run reports that as it stands rather than stretching it, and asks the owner whether a larger table exists before any claim rests on it.
- Assumed: the references are recorded exactly as given. On their face none of them describes gene programs (arXiv:1706.03762 appears to be the Transformer paper, the DOI appears to be SciPy 1.0, the third is AlphaFold). The scout confirms what each one is, and the run does not invent gene programs to stand in for them.
- Assumed: no code repository, deadline, hardware limit, licence, or excluded method, because none was stated.
- Assumed: no quantitative goal, so there is no GOAL.json; the owner stated none and there is no eval script.
- Assumed: autonomy checkpoints and radius moderate are the defaults; budgets stay not stated.

## Autonomy

`checkpoints`: the owner approves the spec and the graph and answers decision tickets; waves run alone.

## Radius

`moderate`: they may also add follow-ups that directly probe a claim's failure.

## Budgets

- GPU hours: not stated
- Wall clock: not stated
- Usage windows: not stated

## Decisions that stay human-only

The decider never resolves these; they wait for the owner.

- `objective`: a decision that changes an objective: adding, parking, dropping, or reframing one, or a goal's measure (its metric, target, splits, or the command that measures it).
- `data`: a decision that changes the data: what is used, what is held out, or what may leave the machine.
